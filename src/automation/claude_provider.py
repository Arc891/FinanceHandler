"""
Claude Provider - Abstraction layer for Claude API access

Provides a unified interface that tries:
1. Claude Code CLI (free, uses your subscription)
2. Anthropic API (requires API key and credits)

This allows using Claude Code as a fallback to avoid API costs.
"""

import json
import logging
import os
import signal
import subprocess
import asyncio
import tempfile
from typing import Optional

# Make anthropic optional - only needed if using API
try:
    from anthropic import AsyncAnthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False
    AsyncAnthropic = None

logger = logging.getLogger(__name__)


class ClaudeProvider:
    """
    Provides Claude API access with automatic fallback.

    Priority:
    1. Claude Code CLI (if available)
    2. Anthropic API (if API key provided)
    """

    # Seconds one CLI call may take (the first request may be slow), and
    # seconds to wait for the process to be reaped after it is killed.
    cli_timeout = 180
    kill_grace = 10
    # Characters of CLI error text carried into an exception message.
    error_text_limit = 200

    def __init__(self, api_key: Optional[str] = None, model: str = "haiku"):
        """
        Initialize Claude provider.

        Args:
            api_key: Optional Anthropic API key (for API fallback)
            model: Model alias (haiku, sonnet, opus)
        """
        self.api_key = api_key
        self.model = model
        self.use_cli = self._check_cli_available()
        self.api_client = None

        if self.use_cli:
            logger.info("Using Claude Code CLI (free)")
        elif api_key:
            if not HAS_ANTHROPIC:
                logger.error(
                    "API key provided but anthropic module not installed")
                logger.info("Install with: pip install anthropic")
            else:
                logger.info("Using Anthropic API (requires credits)")
                self.api_client = AsyncAnthropic(api_key=api_key)
        else:
            logger.warning(
                "No Claude access available - neither CLI nor API key")

    def _check_cli_available(self) -> bool:
        """Check if Claude Code CLI is available."""
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            available = result.returncode == 0
            if available:
                logger.debug("Claude Code CLI detected")
            return available
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.debug("Claude Code CLI not available")
            return False

    async def complete(self, prompt: str, max_tokens: int = 500,
                       temperature: float = 0.3) -> str:
        """
        Get completion from Claude (CLI or API).

        Args:
            prompt: The prompt to send
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            Response text

        Raises:
            RuntimeError: If no Claude access available or request fails
        """
        if self.use_cli:
            return await self._complete_cli(prompt)
        elif self.api_client:
            return await self._complete_api(prompt, max_tokens, temperature)
        else:
            raise RuntimeError(
                "No Claude access available. Install Claude Code or provide API key."
            )

    @staticmethod
    def _parse_cli_response(stdout_str: str) -> tuple:
        """
        Extract (result_text, cost) from a `claude -p --output-format json` reply.

        Handles both CLI output shapes:
        - Newer CLI: a JSON array of message objects; the final assistant
          result is the element with type == "result".
        - Older CLI: a single JSON object with is_error/result/total_cost_usd.

        Raises:
            RuntimeError: if the CLI reported an error or no result is present.
        """
        result_obj = ClaudeProvider._result_object(json.loads(stdout_str))

        if result_obj.get("is_error"):
            raise RuntimeError(
                f"Claude Code error: {result_obj.get('result')}")

        return result_obj.get("result", ""), result_obj.get("total_cost_usd", 0)

    @staticmethod
    def _result_object(parsed) -> dict:
        """The result object of parsed `--output-format json` output."""
        if isinstance(parsed, list):
            # Find the result object; fall back to the last dict in the stream.
            result_obj = next(
                (m for m in parsed
                 if isinstance(m, dict) and m.get("type") == "result"),
                None,
            )
            if result_obj is None:
                result_obj = next(
                    (m for m in reversed(parsed) if isinstance(m, dict)), None)
            if result_obj is None:
                raise RuntimeError(
                    "Claude Code CLI returned no result object in array output")
        elif isinstance(parsed, dict):
            result_obj = parsed
        else:
            raise RuntimeError(
                f"Unexpected Claude Code CLI output type: {type(parsed).__name__}")
        return result_obj

    @classmethod
    def _describe_failure(cls, returncode, stdout_str, stderr_str) -> str:
        """Why a CLI call exited non-zero, from its JSON result and stderr.

        Reports the result's subtype and terminal_reason, and its text only
        when it is an error message. Stdout that is not JSON is described by
        size alone: it could hold anything, the prompt included.
        """
        limit = cls.error_text_limit
        parts = [f"exit {returncode}"]
        if stdout_str.strip():
            try:
                result_obj = cls._result_object(json.loads(stdout_str))
            except (json.JSONDecodeError, RuntimeError):
                parts.append(f"stdout not JSON ({len(stdout_str)} bytes)")
            else:
                for field in ("subtype", "terminal_reason"):
                    if result_obj.get(field):
                        parts.append(f"{field}={result_obj[field]}")
                if result_obj.get("is_error") and result_obj.get("result"):
                    parts.append(f"result: {str(result_obj['result'])[:limit]}")
        if stderr_str.strip():
            parts.append(f"stderr: {stderr_str.strip()[:limit]}")
        if len(parts) == 1:
            parts.append("no output")
        return "; ".join(parts)

    async def _complete_cli(self, prompt: str, **kwargs) -> str:
        """
        Complete using Claude Code CLI (async version).

        Note: CLI does not support temperature or max_tokens parameters.
        First-time CLI usage may require interactive approval.
        Test manually first: claude -p "test prompt"
        """
        if kwargs.get('temperature') or kwargs.get('max_tokens'):
            logger.debug(
                "CLI path: temperature and max_tokens params are ignored "
                "(not supported by claude -p)")

        try:
            cmd = [
                "claude", "-p", prompt,
                "--model", self.model,
                "--output-format", "json",
                "--max-turns", "1",  # Single response, no back-and-forth
                # No tools: with one turn, a tool call ends the run as
                # error_max_turns (exit 1) instead of giving an answer.
                "--tools", ""
            ]

            logger.debug(f"Calling Claude Code CLI with model: {self.model}")

            # Output goes to temp files, not pipes: in Python 3.12
            # process.wait() only returns once every pipe has closed, and a
            # child of claude that outlives it would hold a pipe open forever.
            # Its own session lets a kill reach that child too.
            with tempfile.TemporaryFile() as out, \
                    tempfile.TemporaryFile() as err:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    start_new_session=True
                )

                try:
                    await asyncio.wait_for(process.wait(),
                                           timeout=self.cli_timeout)
                except asyncio.CancelledError:
                    # The run's AI budget cancelled this call: never leave
                    # the claude process running behind it.
                    await self._kill_cli(process)
                    raise
                except asyncio.TimeoutError:
                    await self._kill_cli(process)
                    logger.error(
                        f"Claude Code CLI timeout ({self.cli_timeout}s). "
                        "First-time use may require manual approval. "
                        "Try: claude -p 'test' manually first."
                    )
                    raise RuntimeError(
                        "Claude Code CLI timed out. "
                        "If this is your first time, run 'claude -p \"test\"' manually to initialize."
                    )
                # Anything claude left running would outlive the call.
                self._kill_group(process)

                out.seek(0)
                err.seek(0)
                stdout_str = out.read().decode('utf-8', errors='replace')
                stderr_str = err.read().decode('utf-8', errors='replace')

            if process.returncode != 0:
                error_msg = self._describe_failure(
                    process.returncode, stdout_str, stderr_str)
                logger.error(f"Claude Code CLI error: {error_msg}")
                raise RuntimeError(f"Claude Code CLI failed: {error_msg}")

            # Parse JSON response (format varies by CLI version)
            response_text, cost = self._parse_cli_response(stdout_str)

            logger.info(
                f"Claude Code CLI response received (cost: ${cost:.4f})")
            logger.debug(f"Response text length: {len(response_text)} chars")

            if not response_text:
                logger.warning("Empty response from Claude Code CLI")

            return response_text

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse CLI response: {e}")
            raise RuntimeError("Invalid JSON response from Claude Code CLI")
        except Exception as e:
            logger.error(f"CLI completion failed: {e}")
            raise

    @staticmethod
    def _kill_group(process) -> None:
        """SIGKILL the CLI's process group (claude and its children)."""
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    async def _kill_cli(self, process) -> None:
        """Kill the CLI's process group and wait, boundedly, for the reap."""
        self._kill_group(process)
        try:
            await asyncio.wait_for(process.wait(), timeout=self.kill_grace)
        except asyncio.TimeoutError:
            logger.error(
                f"Claude Code CLI not reaped {self.kill_grace}s after kill")

    async def _complete_api(
            self, prompt: str, max_tokens: int, temperature: float) -> str:
        """Complete using Anthropic API (async version)."""
        try:
            # Map model alias to full API model name
            model_map = {
                "haiku": "claude-haiku-4-5-20251001",
                "sonnet": "claude-sonnet-4-6-20250514",
                "opus": "claude-opus-4-6-20250514"
            }
            api_model = model_map.get(self.model, "claude-3-5-haiku-20241022")

            logger.debug(f"Calling Anthropic API with model: {api_model}")

            # Use async API client
            response = await self.api_client.messages.create(
                model=api_model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = response.content[0].text
            logger.info("Anthropic API response received")

            return response_text

        except Exception as e:
            logger.error(f"API completion failed: {e}")
            raise


def get_claude_provider(
    api_key: Optional[str] = None,
    model: str = "haiku",
    prefer_cli: bool = True
) -> ClaudeProvider:
    """
    Factory function to get a Claude provider.

    Args:
        api_key: Optional Anthropic API key
        model: Model to use (haiku, sonnet, opus)
        prefer_cli: Whether to prefer CLI over API if both available

    Returns:
        Configured ClaudeProvider instance
    """
    provider = ClaudeProvider(api_key=api_key, model=model)

    if not provider.use_cli and not provider.api_client:
        logger.warning(
            "No Claude access available. "
            "Install Claude Code or set CLAUDE_API_KEY environment variable."
        )

    return provider
