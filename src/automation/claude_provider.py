"""
Claude Provider - Abstraction layer for Claude API access

Provides a unified interface that tries:
1. Claude Code CLI (free, uses your subscription)
2. Anthropic API (requires API key and credits)

This allows using Claude Code as a fallback to avoid API costs.
"""

import json
import logging
import subprocess
import asyncio
from typing import Optional, Dict, Any

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
                logger.error("API key provided but anthropic module not installed")
                logger.info("Install with: pip install anthropic")
            else:
                logger.info("Using Anthropic API (requires credits)")
                self.api_client = AsyncAnthropic(api_key=api_key)
        else:
            logger.warning("No Claude access available - neither CLI nor API key")

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

    async def complete(self, prompt: str, max_tokens: int = 500, temperature: float = 0.3) -> str:
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

    async def _complete_cli(self, prompt: str) -> str:
        """
        Complete using Claude Code CLI (async version).

        Note: First-time CLI usage may require interactive approval.
        Test manually first: claude -p "test prompt"
        """
        try:
            cmd = [
                "claude", "-p", prompt,
                "--model", self.model,
                "--output-format", "json",
                "--max-turns", "1"  # Single response, no back-and-forth
            ]

            logger.debug(f"Calling Claude Code CLI with model: {self.model}")

            # Use async subprocess to avoid blocking Discord bot
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Wait for completion with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=180  # 3 minutes max (first request may be slow)
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.error(
                    "Claude Code CLI timeout (180s). "
                    "First-time use may require manual approval. "
                    "Try: claude -p 'test' manually first."
                )
                raise RuntimeError(
                    "Claude Code CLI timed out. "
                    "If this is your first time, run 'claude -p \"test\"' manually to initialize."
                )

            # Decode output
            stdout_str = stdout.decode('utf-8') if stdout else ""
            stderr_str = stderr.decode('utf-8') if stderr else ""

            if process.returncode != 0:
                error_msg = stderr_str or "Unknown error"
                logger.error(f"Claude Code CLI error: {error_msg}")
                raise RuntimeError(f"Claude Code CLI failed: {error_msg}")

            # Parse JSON response
            response = json.loads(stdout_str)

            if response.get("is_error"):
                raise RuntimeError(f"Claude Code error: {response.get('result')}")

            response_text = response.get("result", "")
            cost = response.get("total_cost_usd", 0)

            logger.info(f"Claude Code CLI response received (cost: ${cost:.4f})")
            logger.debug(f"Response text length: {len(response_text)} chars")

            if not response_text:
                logger.warning("Empty response from Claude Code CLI")
                logger.debug(f"Full response keys: {list(response.keys())}")

            return response_text

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse CLI response: {e}")
            raise RuntimeError("Invalid JSON response from Claude Code CLI")
        except Exception as e:
            logger.error(f"CLI completion failed: {e}")
            raise

    async def _complete_api(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """Complete using Anthropic API (async version)."""
        try:
            # Map model alias to full API model name
            model_map = {
                "haiku": "claude-3-5-haiku-20241022",
                "sonnet": "claude-3-5-sonnet-20241022",
                "opus": "claude-opus-4-5-20251101"
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
