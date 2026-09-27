# bot_commands.py
"""
Discord slash commands (plan 4.8).

/upload saves up to five CSV exports and hands them to the Pipeline, which
splits them into financial months and writes each month's sheet with no
review step. The interaction token dies after 15 minutes, so the command
answers at once and the run posts its progress and summary to the user's
Approvals-<name> thread in the reminder channel. A refusal (RunRefused) is
a private reply. Every command is limited to the household
(MENTION_USER_IDS).
"""

import asyncio
import io
import logging
import os
import shutil
import traceback
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from finance_core.config_access import project_path, setting
from finance_core.discord_threads import get_or_create_user_thread
from finance_core.export import Pipeline, RunRefused, RunReport, new_upload_id
from finance_core.sheet_registry import SheetRegistryError

logger = logging.getLogger(__name__)

# Discord's caps: an embed description, all embeds of one message together,
# and the number of embeds in one message.
EMBED_LIMIT = 4096
MESSAGE_LIMIT = 6000
EMBEDS_PER_MESSAGE = 10
SHEET_URL = "https://docs.google.com/spreadsheets/d/{}"


# ── fitting text into Discord ───────────────────────────────────────────────

def split_text(text: str, limit: int = EMBED_LIMIT) -> list:
    """Cut text into pieces of at most ``limit`` characters.

    Breaks fall between lines, and the newline at a break is dropped, so
    "\\n".join(pieces) gives the text back. A single line longer than the
    limit is cut mid-line; those cuts drop nothing.
    """
    pieces, current = [], None
    for line in text.split("\n"):
        while len(line) > limit:
            if current is not None:
                pieces.append(current)
                current = None
            pieces.append(line[:limit])
            line = line[limit:]
        if current is None:
            current = line
        elif len(current) + 1 + len(line) <= limit:
            current += "\n" + line
        else:
            pieces.append(current)
            current = line
    if current is not None:
        pieces.append(current)
    return pieces


def embed_messages(text: str, title: Optional[str] = None,
                   colour: Optional[discord.Colour] = None) -> list:
    """Keyword arguments for one or more send() calls that carry ``text``."""
    embeds = [discord.Embed(description=piece or "​", colour=colour)
              for piece in split_text(text)]
    embeds[0].title = title
    messages, batch, size = [], [], 0
    for embed in embeds:
        n = len(embed.description) + len(embed.title or "")
        if batch and (size + n > MESSAGE_LIMIT
                      or len(batch) == EMBEDS_PER_MESSAGE):
            messages.append({"embeds": batch})
            batch, size = [], 0
        batch.append(embed)
        size += n
    messages.append({"embeds": batch})
    return messages


def summary_messages(report: RunReport) -> list:
    """The run summary; the full flagged list rides on the last message."""
    state = "complete" if report.complete else "incomplete"
    colour = discord.Colour.green() if report.complete else discord.Colour.orange()
    messages = embed_messages(report.text, f"Upload {report.upload_id}: {state}",
                              colour)
    if report.flagged_attachment:
        messages[-1]["file"] = discord.File(
            io.BytesIO(report.flagged_attachment.encode("utf-8")),
            filename=f"flagged-{report.upload_id}.txt")
    return messages


def _safe_name(filename: str) -> str:
    return os.path.basename(filename.replace("\\", "/")) or "upload.csv"


# ── the cog ─────────────────────────────────────────────────────────────────

class FinanceBot(commands.Cog):
    months = app_commands.Group(
        name="months", description="The index of monthly budget sheets")

    def __init__(self, bot, *, pipeline_factory=None, open_thread=None,
                 household=None, upload_root=None):
        self.bot = bot
        self._pipeline_factory = pipeline_factory or Pipeline.from_settings
        self._pipeline = None
        self._open_thread = open_thread or self._reminder_thread
        self._household = household or (
            lambda: list(setting("MENTION_USER_IDS", [])))
        self._upload_root = upload_root or project_path(
            setting("UPLOAD_DIR", "data/uploads"))
        self._tasks = set()

    # ── /upload and /resume ───────────────────────────────────────────────
    @app_commands.command(
        name="upload",
        description="Upload up to five ASN CSV exports and write them to the monthly sheets")
    @app_commands.describe(
        attachment="An ASN CSV export",
        attachment2="Another export (optional)",
        attachment3="Another export (optional)",
        attachment4="Another export (optional)",
        attachment5="Another export (optional)",
        force="Write even when the split looks suspicious (4.3)",
        note="Context for the AI, e.g. 'vakantie Italië 10-07 t/m 24-07'; sent as written")
    async def upload(self, interaction: discord.Interaction,
                     attachment: discord.Attachment,
                     attachment2: Optional[discord.Attachment] = None,
                     attachment3: Optional[discord.Attachment] = None,
                     attachment4: Optional[discord.Attachment] = None,
                     attachment5: Optional[discord.Attachment] = None,
                     force: bool = False,
                     note: Optional[app_commands.Range[str, 1, 300]] = None):
        attachments = [a for a in (attachment, attachment2, attachment3,
                                   attachment4, attachment5) if a is not None]
        if not await self._allowed(interaction):
            return
        not_csv = [a.filename for a in attachments
                   if not a.filename.lower().endswith(".csv")]
        if not_csv:
            await self._private(
                interaction, f"❌ Not a CSV file: {', '.join(not_csv)}. "
                "Nothing was saved.")
            return
        pipeline = await self._get_pipeline(interaction)
        if pipeline is None:
            return
        thread = await self._thread(interaction)
        if thread is None:
            return

        upload_id = new_upload_id()
        folder = os.path.join(self._upload_root, upload_id)
        try:
            files = await self._save(attachments, folder)
        except Exception as e:
            shutil.rmtree(folder, ignore_errors=True)
            logger.error("Saving upload %s failed: %s", upload_id,
                         type(e).__name__)
            await self._private(
                interaction, f"❌ Could not save the attachments "
                f"({type(e).__name__}). Nothing was started.")
            return

        await self._private(
            interaction, f"📥 Processing {len(files)} file(s) as upload "
            f"{upload_id}; progress and the summary follow in your thread "
            f"{getattr(thread, 'mention', '')}".rstrip())
        self._spawn(self._run(
            interaction, thread,
            lambda progress: pipeline.process_upload(
                upload_id, files, force=force, progress=progress, note=note),
            refused_cleanup=folder))

    @app_commands.command(name="resume",
                          description="Continue an unfinished upload run")
    @app_commands.describe(
        upload_id="The run to continue; the newest open run by default")
    async def resume(self, interaction: discord.Interaction,
                     upload_id: Optional[str] = None):
        if not await self._allowed(interaction):
            return
        pipeline = await self._get_pipeline(interaction)
        if pipeline is None:
            return
        thread = await self._thread(interaction)
        if thread is None:
            return
        await self._private(
            interaction, "🔄 Resuming; progress and the summary follow in "
            f"your thread {getattr(thread, 'mention', '')}".rstrip())
        self._spawn(self._run(
            interaction, thread,
            lambda progress: pipeline.resume(upload_id, progress=progress)))

    # ── /status, /cancel, /sort ───────────────────────────────────────────
    @app_commands.command(
        name="status",
        description="Show every open upload run and what it has not written")
    async def status(self, interaction: discord.Interaction):
        if not await self._allowed(interaction):
            return
        pipeline = await self._get_pipeline(interaction)
        if pipeline is None:
            return
        await self._private_embeds(interaction, pipeline.status(),
                                   "Open runs")

    @app_commands.command(
        name="cancel",
        description="Abandon an open upload run (never undoes a write)")
    @app_commands.describe(
        upload_id="The run to cancel; the newest open run by default",
        confirm="Discard the rows the run has not written yet")
    async def cancel(self, interaction: discord.Interaction,
                     upload_id: Optional[str] = None, confirm: bool = False):
        if not await self._allowed(interaction):
            return
        pipeline = await self._get_pipeline(interaction)
        if pipeline is None:
            return
        try:
            message = pipeline.cancel(upload_id, confirm=confirm)
        except RunRefused as e:
            await self._private(interaction, f"❌ {e}")
            return
        await self._private(interaction, f"✅ {message}")

    @app_commands.command(
        name="sort", description="Sort monthly sheets by date")
    @app_commands.describe(
        month="MM/YYYY; by default every sheet the last run touched")
    async def sort_sheet(self, interaction: discord.Interaction,
                         month: Optional[str] = None):
        if not await self._allowed(interaction):
            return
        pipeline = await self._get_pipeline(interaction)
        if pipeline is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            lines = await pipeline.sort([month] if month else None)
        except RunRefused as e:
            await self._private(interaction, f"❌ {e}")
            return
        except Exception as e:
            logger.error("Sort failed: %s", type(e).__name__)
            await self._private(interaction,
                                f"❌ Sort failed ({type(e).__name__}).")
            return
        await self._private_embeds(
            interaction, "\n".join(lines) or "Nothing to sort.", "Sort")

    # ── /months list, /months register ────────────────────────────────────
    @months.command(name="list", description="List the month -> sheet index")
    async def months_list(self, interaction: discord.Interaction):
        if not await self._allowed(interaction):
            return
        pipeline = await self._get_pipeline(interaction)
        if pipeline is None:
            return
        months = pipeline.registry.list_months()
        if not months:
            await self._private(
                interaction, "The index is empty; /months register adds a "
                "sheet.")
            return
        text = "\n".join(f"`{label}` {SHEET_URL.format(entry['id'])}"
                         for label, entry in months)
        await self._private_embeds(interaction, text, "Monthly sheets")

    @months.command(name="register",
                    description="Add a sheet the bot did not create")
    @app_commands.describe(
        label="The month, MM/YYYY",
        url="The sheet's URL or spreadsheet id",
        force="Re-point a label or sheet that is already registered")
    async def months_register(self, interaction: discord.Interaction,
                              label: str, url: str, force: bool = False):
        if not await self._allowed(interaction):
            return
        pipeline = await self._get_pipeline(interaction)
        if pipeline is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await asyncio.to_thread(
                pipeline.registry.register, label, url, force=force)
        except (SheetRegistryError, ValueError) as e:
            await self._private(interaction, f"❌ {e}")
            return
        except Exception as e:
            logger.error("Register failed: %s", type(e).__name__)
            await self._private(interaction,
                                f"❌ Register failed ({type(e).__name__}).")
            return
        await self._private(interaction, f"✅ {label}: {result}")

    # ── the background run ────────────────────────────────────────────────
    async def _run(self, interaction, thread, start, refused_cleanup=None):
        async def progress(line):
            await thread.send(line)

        try:
            report = await start(progress)
        except RunRefused as e:
            # process_upload refuses only before it creates the run state,
            # so no run refers to these files yet.
            if refused_cleanup:
                shutil.rmtree(refused_cleanup, ignore_errors=True)
            await self._private(interaction, f"❌ {e}")
            return
        except Exception as e:
            # The message could quote a row; log and post the type only.
            logger.error("Run stopped on %s\n%s", type(e).__name__,
                         "".join(traceback.format_tb(e.__traceback__)))
            await thread.send(
                f"❌ The run stopped on an unexpected {type(e).__name__}. "
                "Its state is kept: /status shows what was written, "
                "/resume continues.")
            return
        for message in summary_messages(report):
            await thread.send(**message)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wait for every background run (tests, and a clean shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ── helpers ───────────────────────────────────────────────────────────
    async def _allowed(self, interaction) -> bool:
        if interaction.user.id in self._household():
            return True
        await self._private(interaction,
                            "❌ Only the household can use this bot.")
        return False

    async def _get_pipeline(self, interaction):
        if self._pipeline is None:
            try:
                self._pipeline = self._pipeline_factory()
            except Exception as e:
                logger.error("Pipeline setup failed: %s", type(e).__name__)
                await self._private(
                    interaction, f"❌ The bot cannot reach its sheets: "
                    f"{type(e).__name__}: {e}")
                return None
        return self._pipeline

    async def _thread(self, interaction):
        thread = await self._open_thread(interaction.user)
        if thread is None:
            await self._private(
                interaction, "❌ Could not open your progress thread (can the "
                "bot create private threads in the reminder channel?). "
                "Nothing was saved.")
        return thread

    async def _reminder_thread(self, user):
        channel = self.bot.get_channel(setting("REMINDER_CHANNEL_ID"))
        if channel is None:
            logger.error("Reminder channel not found")
            return None
        return await get_or_create_user_thread(channel, user.id, self.bot)

    @staticmethod
    async def _save(attachments, folder) -> list:
        """Save in attachment order; the index prefix keeps names unique."""
        os.makedirs(folder, exist_ok=True)
        files = []
        for i, attachment in enumerate(attachments, start=1):
            path = os.path.join(folder, f"{i}-{_safe_name(attachment.filename)}")
            await attachment.save(path)
            files.append(path)
        return files

    @staticmethod
    async def _private(interaction, content: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)

    @staticmethod
    async def _private_embeds(interaction, text: str, title: str) -> None:
        for message in embed_messages(text, title):
            if interaction.response.is_done():
                await interaction.followup.send(ephemeral=True, **message)
            else:
                await interaction.response.send_message(ephemeral=True,
                                                        **message)


async def setup(bot):
    """Required function for loading the cog"""
    await bot.add_cog(FinanceBot(bot))
    logger.info("✅ FinanceBot cog loaded")
