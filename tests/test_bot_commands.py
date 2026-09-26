"""
Tests for Phase 3 step 4: the Discord command surface (plan 4.8).

The cog is driven with fake interactions, attachments and threads, and a
fake Pipeline, so no Discord or Google connection is made. Covered: /upload
refuses a non-CSV file or a non-household user before saving anything, saves
attachments in order under a fresh upload folder, replies at once and posts
progress and the summary to the user's thread; a refusal is a private reply;
a crash posts the exception type only; the summary fits Discord's limits; the
other commands; the removed ones are gone; and the config self-check. All data
is synthetic.
"""

import asyncio
import os
import sys
import types
from types import SimpleNamespace

import pytest

import bot_commands as bc
import config_check
from finance_core.export import RunRefused, RunReport
from finance_core.sheet_index import IndexConflict
from finance_core.sheet_registry import StaleSheetError

HOUSEHOLD = [111, 222]
SECRET = "Jolanda Vermeulen"


# ── fakes ───────────────────────────────────────────────────────────────────

class Sent(list):
    """Everything a fake endpoint was asked to send, as dicts."""

    def texts(self):
        out = []
        for m in self:
            out.append(m.get("content") or "")
            out += [e.description or "" for e in m.get("embeds") or []]
        return "\n".join(out)


class Endpoint:
    def __init__(self):
        self.sent = Sent()

    async def send(self, content=None, **kwargs):
        self.sent.append({"content": content, **kwargs})


class Response(Endpoint):
    def __init__(self):
        super().__init__()
        self.done = False

    async def send_message(self, content=None, **kwargs):
        assert not self.done, "an interaction can be answered once"
        self.done = True
        await self.send(content, **kwargs)

    async def defer(self, **kwargs):
        assert not self.done
        self.done = True
        self.sent.append({"deferred": True, **kwargs})

    def is_done(self):
        return self.done


class Interaction:
    def __init__(self, user_id=111):
        self.user = SimpleNamespace(id=user_id, display_name=f"user{user_id}")
        self.response = Response()
        self.followup = Endpoint()

    def replies(self):
        return Sent(self.response.sent + self.followup.sent)


class Attachment:
    def __init__(self, filename, data=b"a;b\n"):
        self.filename, self.data = filename, data
        self.saved_to = None

    async def save(self, fp):
        with open(fp, "wb") as f:
            f.write(self.data)
        self.saved_to = os.fspath(fp)


class Registry:
    def __init__(self, months=(), register=None):
        self.months = list(months)
        self._register = register or (lambda label, url, force: "added")
        self.registered = []

    def list_months(self):
        return self.months

    def register(self, label, url_or_id, *, force=False):
        self.registered.append((label, url_or_id, force))
        return self._register(label, url_or_id, force)


class Pipeline:
    def __init__(self, report=None, refuse=None, crash=None, lines=(),
                 registry=None):
        self.report = report or RunReport("u1", "Upload u1\nPeriods:\n  done",
                                          True)
        self.refuse, self.crash, self.lines = refuse, crash, lines
        self.registry = registry or Registry()
        self.calls = []

    async def _run(self, progress):
        for line in self.lines:
            await progress(line)
        if self.refuse:
            raise RunRefused(self.refuse)
        if self.crash:
            raise self.crash
        return self.report

    async def process_upload(self, upload_id, files, *, force=False,
                             progress=None):
        self.calls.append(("upload", upload_id, list(files), force))
        return await self._run(progress)

    async def resume(self, upload_id=None, *, progress=None):
        self.calls.append(("resume", upload_id))
        return await self._run(progress)

    def cancel(self, upload_id=None, *, confirm=False):
        self.calls.append(("cancel", upload_id, confirm))
        if self.refuse:
            raise RunRefused(self.refuse)
        return f"Run {upload_id} cancelled."

    async def sort(self, labels=None):
        self.calls.append(("sort", labels))
        if self.refuse:
            raise RunRefused(self.refuse)
        return ["03/2026: sorted (5 expenses, 1 income)"]

    def status(self):
        self.calls.append(("status",))
        return self.report.text


@pytest.fixture
def env(tmp_path):
    """A cog wired to fakes; env.cog, env.pipeline, env.thread, env.root."""
    ns = SimpleNamespace(pipeline=Pipeline(), thread=Endpoint(),
                         root=tmp_path / "uploads", opened=[])

    async def open_thread(user):
        ns.opened.append(user.id)
        return ns.thread

    def make(**kwargs):
        for k, v in kwargs.items():
            setattr(ns, k, v)
        ns.cog = bc.FinanceBot(
            bot=None, pipeline_factory=lambda: ns.pipeline,
            open_thread=open_thread if ns.thread is not None else _no_thread,
            household=lambda: HOUSEHOLD, upload_root=str(ns.root))
        return ns

    make()
    ns.make = make
    return ns


async def _no_thread(user):
    return None


async def call(command, cog, *args, **kwargs):
    await command.callback(cog, *args, **kwargs)
    await cog.drain()


def saved_files(root):
    return sorted(os.path.relpath(os.path.join(d, f), root)
                  for d, _, fs in os.walk(root) for f in fs)


# ── /upload ─────────────────────────────────────────────────────────────────

async def test_non_csv_is_refused_before_anything_is_saved(env):
    good, bad = Attachment("export.csv"), Attachment("statement.pdf")
    it = Interaction()
    await call(env.cog.upload, env.cog, it, good, bad)
    assert "statement.pdf" in it.replies().texts()
    assert it.response.sent[0].get("ephemeral") is True
    assert good.saved_to is None and bad.saved_to is None
    assert not env.root.exists() or saved_files(env.root) == []
    assert env.pipeline.calls == []


async def test_csv_extension_is_case_insensitive(env):
    it = Interaction()
    await call(env.cog.upload, env.cog, it, Attachment("EXPORT.CSV"))
    assert env.pipeline.calls[0][0] == "upload"


async def test_a_user_outside_the_household_is_refused(env):
    att = Attachment("export.csv")
    it = Interaction(user_id=999)
    await call(env.cog.upload, env.cog, it, att)
    assert it.response.sent[0].get("ephemeral") is True
    assert att.saved_to is None and env.pipeline.calls == []
    assert env.opened == []


async def test_no_thread_refuses_before_saving(env):
    env.make(thread=None)
    att = Attachment("export.csv")
    it = Interaction()
    await call(env.cog.upload, env.cog, it, att)
    assert "thread" in it.replies().texts().lower()
    assert att.saved_to is None and env.pipeline.calls == []


async def test_attachments_are_saved_in_order_under_a_fresh_upload_folder(env):
    atts = [Attachment("b.csv", b"2"), Attachment("a.csv", b"1"),
            Attachment("c.csv", b"3")]
    it = Interaction()
    await call(env.cog.upload, env.cog, it, *atts, force=True)
    kind, upload_id, files, force = env.pipeline.calls[0]
    assert kind == "upload" and force is True
    assert [os.path.dirname(f) for f in files] == \
        [os.path.join(str(env.root), upload_id)] * 3
    assert [open(f, "rb").read() for f in files] == [b"2", b"1", b"3"]


async def test_same_named_attachments_do_not_overwrite_each_other(env):
    atts = [Attachment("export.csv", b"1"), Attachment("export.csv", b"2")]
    await call(env.cog.upload, env.cog, Interaction(), *atts)
    files = env.pipeline.calls[0][2]
    assert len(set(files)) == 2
    assert [open(f, "rb").read() for f in files] == [b"1", b"2"]


async def test_a_filename_cannot_escape_the_upload_folder(env):
    await call(env.cog.upload, env.cog, Interaction(),
               Attachment("../../evil.csv"))
    _, upload_id, files, _ = env.pipeline.calls[0]
    folder = os.path.join(str(env.root), upload_id)
    assert os.path.dirname(os.path.abspath(files[0])) == folder


async def test_upload_replies_at_once_then_posts_progress_and_summary(env):
    env.make(pipeline=Pipeline(lines=["03/2026: written (40 rows)",
                                      "04/2026: written (12 rows)"]))
    it = Interaction()
    await call(env.cog.upload, env.cog, it, Attachment("export.csv"))
    first = it.response.sent[0]
    assert first.get("ephemeral") is True and "thread" in first["content"]
    posted = env.thread.sent
    assert posted[0]["content"] == "03/2026: written (40 rows)"
    assert posted[1]["content"] == "04/2026: written (12 rows)"
    assert "Upload u1" in Sent(posted[2:]).texts()


async def test_a_refusal_is_a_private_reply_and_the_saved_files_go(env):
    env.make(pipeline=Pipeline(refuse="a run started at 10:00 is in progress"))
    it = Interaction()
    await call(env.cog.upload, env.cog, it, Attachment("export.csv"))
    follow = it.followup.sent
    assert follow and follow[-1].get("ephemeral") is True
    assert "in progress" in follow[-1]["content"]
    assert env.thread.sent == []
    assert saved_files(env.root) == []


async def test_a_crash_posts_the_exception_type_only(env, caplog):
    env.make(pipeline=Pipeline(crash=RuntimeError(f"row of {SECRET}")))
    await call(env.cog.upload, env.cog, Interaction(), Attachment("x.csv"))
    text = env.thread.sent.texts()
    assert "RuntimeError" in text and SECRET not in text
    assert "/status" in text
    assert "RuntimeError" in caplog.text and SECRET not in caplog.text


async def test_every_upload_gets_its_own_folder(env):
    await call(env.cog.upload, env.cog, Interaction(), Attachment("a.csv"))
    await call(env.cog.upload, env.cog, Interaction(), Attachment("a.csv"))
    first, second = env.pipeline.calls[0][1], env.pipeline.calls[1][1]
    assert first != second


# ── the summary fits Discord ────────────────────────────────────────────────

def long_report(lines=400, width=60, attachment=None):
    text = "\n".join(f"{i:04d} " + "x" * width for i in range(lines))
    return RunReport("u9", text, False, attachment)


def embeds_of(sent):
    return [e for m in sent for e in m.get("embeds") or []]


def test_summary_messages_respect_the_embed_limits():
    report = long_report()
    messages = bc.summary_messages(report)
    for m in messages:
        embeds = m["embeds"]
        assert 1 <= len(embeds) <= 10
        assert all(len(e.description) <= 4096 for e in embeds)
        assert sum(len(e.description) + len(e.title or "")
                   for e in embeds) <= 6000
    joined = "\n".join(e.description for m in messages for e in m["embeds"])
    assert joined == report.text


@pytest.mark.parametrize("text, pieces", [
    ("a" * 9 + "\n" + "b" * 5, ["a" * 9 + "\n" + "b" * 5]),   # exactly 15
    ("a" * 10 + "\n" + "b" * 5, ["a" * 10, "b" * 5]),          # 16: split
])
def test_split_text_counts_the_newline_it_keeps(text, pieces):
    assert bc.split_text(text, limit=15) == pieces


def test_a_line_longer_than_an_embed_is_split_losslessly():
    report = RunReport("u9", "y" * 9000, True)
    messages = bc.summary_messages(report)
    parts = [e.description for m in messages for e in m["embeds"]]
    assert all(len(p) <= 4096 for p in parts)
    assert "".join(parts) == "y" * 9000


async def test_the_full_flagged_list_is_attached_as_a_text_file(env):
    report = long_report(lines=5, attachment="row 1\nrow 2\n")
    env.make(pipeline=Pipeline(report=report))
    await call(env.cog.upload, env.cog, Interaction(), Attachment("a.csv"))
    files = [m["file"] for m in env.thread.sent if m.get("file")]
    assert len(files) == 1
    assert files[0].filename == "flagged-u9.txt"
    assert files[0].fp.read() == b"row 1\nrow 2\n"


async def test_incomplete_and_complete_runs_are_told_apart(env):
    env.make(pipeline=Pipeline(report=RunReport("u2", "Upload u2", False)))
    await call(env.cog.upload, env.cog, Interaction(), Attachment("a.csv"))
    title = embeds_of(env.thread.sent)[0].title
    assert "incomplete" in title.lower()


# ── /resume ─────────────────────────────────────────────────────────────────

async def test_resume_posts_progress_and_summary_to_the_thread(env):
    env.make(pipeline=Pipeline(lines=["05/2026: written (3 rows)"]))
    it = Interaction(user_id=222)
    await call(env.cog.resume, env.cog, it, upload_id="u7")
    assert env.pipeline.calls == [("resume", "u7")]
    assert env.thread.sent[0]["content"] == "05/2026: written (3 rows)"
    assert "Upload u1" in env.thread.sent.texts()


async def test_resume_refusal_is_private(env):
    env.make(pipeline=Pipeline(refuse="no open run to resume"))
    it = Interaction()
    await call(env.cog.resume, env.cog, it)
    assert it.followup.sent[-1]["content"].endswith("no open run to resume")
    assert it.followup.sent[-1].get("ephemeral") is True


async def test_resume_refuses_a_user_outside_the_household(env):
    await call(env.cog.resume, env.cog, Interaction(user_id=999))
    assert env.pipeline.calls == []


# ── /status, /cancel, /sort ─────────────────────────────────────────────────

async def test_status_is_private_and_fits_discord(env):
    env.make(pipeline=Pipeline(report=long_report()))
    it = Interaction()
    await call(env.cog.status, env.cog, it)
    sent = it.replies()
    assert all(m.get("ephemeral") is True for m in sent if "deferred" not in m)
    assert all(len(e.description) <= 4096 for e in embeds_of(sent))
    assert "\n".join(e.description for e in embeds_of(sent)) == \
        long_report().text


async def test_cancel_passes_confirm_and_reports(env):
    it = Interaction()
    await call(env.cog.cancel, env.cog, it, upload_id="u3", confirm=True)
    assert env.pipeline.calls == [("cancel", "u3", True)]
    assert "cancelled" in it.replies().texts()


async def test_cancel_refusal_is_private(env):
    env.make(pipeline=Pipeline(refuse="repeat with confirm: true"))
    it = Interaction()
    await call(env.cog.cancel, env.cog, it)
    assert "confirm: true" in it.replies().texts()
    assert all(m.get("ephemeral") for m in it.replies()
               if "deferred" not in m)


@pytest.mark.parametrize("month, labels", [("03/2026", ["03/2026"]),
                                           (None, None)])
async def test_sort_takes_an_optional_month(env, month, labels):
    it = Interaction()
    await call(env.cog.sort_sheet, env.cog, it, month=month)
    assert env.pipeline.calls == [("sort", labels)]
    assert "sorted (5 expenses, 1 income)" in it.replies().texts()


async def test_sort_refusal_is_reported(env):
    env.make(pipeline=Pipeline(refuse="sorting is refused"))
    it = Interaction()
    await call(env.cog.sort_sheet, env.cog, it, month=None)
    assert "sorting is refused" in it.replies().texts()


# ── /months ─────────────────────────────────────────────────────────────────

async def test_months_list_prints_label_and_link(env):
    env.make(pipeline=Pipeline(registry=Registry(months=[
        ("02/2026", {"id": "AAA"}), ("03/2026", {"id": "BBB"})])))
    it = Interaction()
    await call(env.cog.months_list, env.cog, it)
    text = it.replies().texts()
    assert "02/2026" in text and "https://docs.google.com/spreadsheets/d/AAA" in text
    assert text.index("02/2026") < text.index("03/2026")


async def test_months_list_of_an_empty_index_says_so(env):
    it = Interaction()
    await call(env.cog.months_list, env.cog, it)
    assert "empty" in it.replies().texts().lower()


async def test_months_register_calls_the_registry(env):
    it = Interaction()
    await call(env.cog.months_register, env.cog, it, label="04/2026",
               url="https://docs.google.com/spreadsheets/d/CCC/edit",
               force=True)
    assert env.pipeline.registry.registered == [
        ("04/2026", "https://docs.google.com/spreadsheets/d/CCC/edit", True)]
    assert "added" in it.replies().texts()


@pytest.mark.parametrize("error", [
    IndexConflict("04/2026 is already registered to AAA, not CCC"),
    StaleSheetError("the sheet no longer opens"),
    ValueError("not a month label (MM/YYYY): '4/26'")])
async def test_months_register_errors_are_reported(env, error):
    def boom(label, url, force):
        raise error
    env.make(pipeline=Pipeline(registry=Registry(register=boom)))
    it = Interaction()
    await call(env.cog.months_register, env.cog, it, label="04/2026",
               url="CCC", force=False)
    assert str(error) in it.replies().texts()


async def test_months_register_refuses_a_user_outside_the_household(env):
    await call(env.cog.months_register, env.cog, Interaction(user_id=999),
               label="04/2026", url="CCC", force=False)
    assert env.pipeline.registry.registered == []


# ── the command surface ─────────────────────────────────────────────────────

def test_only_the_new_commands_exist(env):
    names = {c.qualified_name for c in env.cog.walk_app_commands()}
    assert names == {"upload", "resume", "status", "cancel", "sort",
                     "months", "months list", "months register"}


def test_upload_takes_five_attachments_and_force(env):
    params = [p.name for p in env.cog.upload.parameters]
    assert params == ["attachment", "attachment2", "attachment3",
                      "attachment4", "attachment5", "force"]


# ── config self-check (plan 4.10) ───────────────────────────────────────────

@pytest.fixture
def fake_config(monkeypatch):
    def install(**attrs):
        mod = types.ModuleType("fake_cfg")
        for k, v in attrs.items():
            setattr(mod, k, v)
        monkeypatch.setitem(sys.modules, "fake_cfg", mod)
    return install


def test_self_check_passes_when_every_key_is_set(fake_config):
    fake_config(**{k: 1 for k in config_check.REQUIRED_SETTINGS})
    config_check.check_required_settings("fake_cfg")


def test_self_check_names_the_missing_keys_on_one_line(fake_config, capsys):
    present = config_check.REQUIRED_SETTINGS[2:]
    fake_config(**{k: 1 for k in present})
    with pytest.raises(SystemExit) as info:
        config_check.check_required_settings("fake_cfg")
    assert info.value.code == 1
    out = capsys.readouterr()
    lines = (out.out + out.err).strip().splitlines()
    assert len(lines) == 1
    for key in config_check.REQUIRED_SETTINGS[:2]:
        assert key in lines[0]


def test_self_check_reports_a_missing_config_module(capsys):
    with pytest.raises(SystemExit):
        config_check.check_required_settings("no_such_cfg_module")
    out = capsys.readouterr()
    assert len((out.out + out.err).strip().splitlines()) == 1


def test_self_check_requires_the_new_keys():
    for key in ("DISCORD_TOKEN", "MENTION_USER_IDS", "REMINDER_CHANNEL_ID",
                "GOOGLE_OAUTH_TOKEN_PATH", "GSHEET_TEMPLATE_ID",
                "GSHEET_FOLDER_ID", "SHEET_INDEX_PATH", "PERIOD_STATE_PATH",
                "UPLOAD_LEDGER_PATH", "AI_BUDGET_TRIP_ACTION"):
        assert key in config_check.REQUIRED_SETTINGS
    assert "APPROVAL_CHANNEL_ID" not in config_check.REQUIRED_SETTINGS


def test_the_example_config_passes_the_self_check(monkeypatch):
    """A fresh copy of the example must start; it defines every key."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "src", "config", "config_settings.example.py")
    spec = importlib.util.spec_from_file_location("example_cfg", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    missing = [k for k in config_check.REQUIRED_SETTINGS
               if not hasattr(mod, k)]
    assert missing == []


def test_bot_runs_the_self_check_before_any_config_import():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "src", "bot.py")
    src = open(path).read()
    check = src.index("check_required_settings(")
    first_config = src.index("from config.config_settings import")
    assert check < first_config
    for gone in ("start_upload_queue", "PendingReviewView",
                 "BatchReviewView"):
        assert gone not in src


def test_drain_is_harmless_when_idle(env):
    asyncio.run(env.cog.drain())


async def test_the_cog_loads_into_a_real_command_tree():
    """Discord refuses the whole sync on a description over 100 characters."""
    import discord
    from discord.ext import commands
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    await bot.add_cog(bc.FinanceBot(bot, pipeline_factory=Pipeline,
                                    household=lambda: HOUSEHOLD))
    payloads = [c.to_dict(bot.tree) for c in bot.tree.get_commands()]
    assert {p["name"] for p in payloads} == {"upload", "resume", "status",
                                            "cancel", "sort", "months"}

    def walk(items):
        for item in items:
            yield item
            yield from walk(item.get("options", []))

    for item in walk(payloads):
        assert 1 <= len(item["description"]) <= 100, item["name"]
        assert len(item["name"]) <= 32
