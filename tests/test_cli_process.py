"""
Tests for the Claude Code CLI subprocess: a call always comes back.

The eval once sat idle for 3.5 h: the claude process had been killed, but a
child of it still held the stdout pipe, and in Python 3.12 process.wait()
only returns once every pipe transport has closed. These tests run a real
fake `claude` script that leaves such a grandchild behind, so they fail by
timing out (never by hanging) if the provider goes back to pipes.
"""

import asyncio
import os
import time

import pytest

from automation.claude_provider import ClaudeProvider

RESULT = '{"type":"result","result":"ok","total_cost_usd":0}'


def alive(pid):
    """True while pid is a running (non-zombie) process."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            state = f.read().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return False                       # ESRCH: it exited mid-read
    return state != "Z"


async def gone(pid, within=3.0):
    end = time.monotonic() + within
    while time.monotonic() < end:
        if not alive(pid):
            return True
        await asyncio.sleep(0.05)
    return False


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """Install a `claude` shell script on PATH; returns (install, pidfile)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pidfile = tmp_path / "grandchild.pid"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GRANDCHILD_PIDFILE", str(pidfile))

    def install(body):
        script = bin_dir / "claude"
        script.write_text("#!/bin/sh\n" + body)
        script.chmod(0o755)

    return install, pidfile


def provider(timeout=0.5, grace=2.0):
    p = ClaudeProvider.__new__(ClaudeProvider)
    p.model, p.use_cli, p.api_client = "sonnet", True, None
    p.cli_timeout, p.kill_grace = timeout, grace
    return p


# A grandchild that inherits stdout and outlives its parent.
GRANDCHILD = 'sleep 300 &\necho $! > "$GRANDCHILD_PIDFILE"\n'


def grandchild_pid(pidfile):
    return int(pidfile.read_text().strip())


async def test_timeout_returns_even_when_a_grandchild_holds_stdout(fake_claude):
    install, pidfile = fake_claude
    install(GRANDCHILD + "sleep 300\n")
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="timed out"):
        await asyncio.wait_for(provider().complete("prompt"), timeout=15)
    assert time.monotonic() - started < 5
    assert await gone(grandchild_pid(pidfile))


async def test_cancel_returns_and_kills_the_whole_process_group(fake_claude):
    install, pidfile = fake_claude
    install(GRANDCHILD + "sleep 300\n")
    task = asyncio.create_task(provider(timeout=60).complete("prompt"))
    while not pidfile.exists():
        await asyncio.sleep(0.02)
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=15)
    assert time.monotonic() - started < 5
    assert await gone(grandchild_pid(pidfile))


async def test_normal_exit_is_not_held_up_by_a_lingering_grandchild(fake_claude):
    install, pidfile = fake_claude
    install(GRANDCHILD + f"echo '{RESULT}'\n")
    started = time.monotonic()
    text = await asyncio.wait_for(provider(timeout=60).complete("prompt"),
                                  timeout=15)
    assert text == "ok"
    assert time.monotonic() - started < 5
    assert await gone(grandchild_pid(pidfile))


async def test_cli_never_waits_on_our_stdin(fake_claude):
    """claude -p appends piped stdin to the prompt; it must see EOF at once."""
    install, _ = fake_claude
    install(f"cat > /dev/null\necho '{RESULT}'\n")
    # Our own stdin becomes a pipe that never reaches EOF, as under a
    # supervisor; an inherited stdin would leave `cat` blocked until timeout.
    read_end, write_end = os.pipe()
    saved = os.dup(0)
    os.dup2(read_end, 0)
    try:
        text = await asyncio.wait_for(provider(timeout=3).complete("prompt"),
                                      timeout=15)
    finally:
        os.dup2(saved, 0)
        for fd in (saved, read_end, write_end):
            os.close(fd)
    assert text == "ok"


async def test_large_output_is_read_in_full(fake_claude):
    """Output beyond a pipe buffer (64 KiB) must neither block nor truncate."""
    install, _ = fake_claude
    big = "x" * 200_000
    install(f"printf '%s' '{{\"type\":\"result\",\"result\":\"{big}\"}}'\n")
    text = await asyncio.wait_for(provider(timeout=10).complete("prompt"),
                                  timeout=15)
    assert text == big
