# finance_core/ui/discord_notifier.py
"""
Sends transaction approval requests to Discord via private threads.
Uses a single summary message with a "Start Review" button that launches
the existing ephemeral transaction flow.
"""

import asyncio
import discord
from discord import ui
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


def _get_counterparty_name(tx: Dict[str, Any]) -> str:
    """Extract counterparty name from transaction with fallback chain."""
    name = tx.get("debtor", {}).get("name", "") or tx.get("creditor", {}).get("name", "")
    if not name.strip():
        remittance = tx.get("remittance_information", [])
        name = remittance[0][:60] if remittance else "Unknown"
    return name.strip() or "Unknown"


class PendingReviewView(ui.View):
    """Simple view with Start Review button to launch ephemeral transaction flow."""

    def __init__(self, user_id: int, pending_count: int):
        super().__init__(timeout=None)  # Persistent
        self.user_id = user_id
        self.pending_count = pending_count

        start_btn = ui.Button(
            label=f"Start Review ({pending_count})",
            style=discord.ButtonStyle.primary,
            emoji="📋",
            custom_id=f"start_review:{user_id}"
        )
        start_btn.callback = self.start_review
        self.add_item(start_btn)

        skip_all_btn = ui.Button(
            label="Skip All",
            style=discord.ButtonStyle.danger,
            emoji="⏭️",
            custom_id=f"skip_all:{user_id}"
        )
        skip_all_btn.callback = self.skip_all
        self.add_item(skip_all_btn)

    async def start_review(self, interaction: discord.Interaction):
        """Load pending transactions to session and start ephemeral review flow."""
        # Validate user
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "You can only review your own transactions.",
                ephemeral=True
            )
            return

        from finance_core.pending_transactions import get_user_pending_transactions, clear_user_pending
        from finance_core.session_management import save_session, load_session
        from finance_core.ui.transaction_prompt import start_transaction_prompt

        pending = get_user_pending_transactions(self.user_id)
        if not pending:
            await interaction.response.send_message(
                "No pending transactions to review.",
                ephemeral=True
            )
            # Update original message to show completed
            await self._update_message_completed(interaction, 0, 0)
            return

        # Load pending transactions into session for the ephemeral flow
        # Attach AI suggestions to transactions so TransactionView can use them
        transactions_for_session = []
        for item in pending:
            tx = item["transaction"].copy()
            # Store AI suggestion in transaction for TransactionView to pick up
            if item.get("ai_category"):
                tx["_ai_suggestion"] = {
                    "category": item["ai_category"],
                    "description": item.get("ai_description", ""),
                    "confidence": item.get("ai_confidence", 0)
                }
            transactions_for_session.append(tx)

        # Save to session (this will be picked up by start_transaction_prompt)
        existing_remaining, existing_income, existing_expenses = load_session(
            self.user_id)
        # Prepend pending transactions to any existing remaining
        all_remaining = transactions_for_session + existing_remaining
        save_session(
            self.user_id,
            all_remaining,
            existing_income,
            existing_expenses)

        # Clear pending queue since they're now in session
        clear_user_pending(self.user_id)

        # Update the thread message
        await self._update_message_in_progress(interaction, len(pending))

        # Start the ephemeral review flow
        await interaction.response.defer(ephemeral=True)
        await start_transaction_prompt(interaction, self.user_id)

    async def skip_all(self, interaction: discord.Interaction):
        """Skip all pending transactions."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "You can only manage your own transactions.",
                ephemeral=True
            )
            return

        from finance_core.pending_transactions import clear_user_pending

        count = clear_user_pending(self.user_id)
        await self._update_message_skipped(interaction, count)

    async def _update_message_in_progress(
            self, interaction: discord.Interaction, count: int):
        """Update message to show review in progress."""
        embed = discord.Embed(
            title="📋 Review In Progress",
            description=f"Reviewing {count} transaction(s)...\n\nCheck your ephemeral messages below.",
            color=discord.Color.blue()
        )
        # Disable buttons
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(embed=embed, view=self)
        except BaseException:
            pass

    async def _update_message_completed(
            self, interaction: discord.Interaction, approved: int, skipped: int):
        """Update message to show review completed."""
        embed = discord.Embed(
            title="✅ Review Complete",
            description="All transactions have been processed.",
            color=discord.Color.green()
        )
        # Disable buttons
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(embed=embed, view=self)
        except BaseException:
            pass

    async def _update_message_skipped(
            self, interaction: discord.Interaction, count: int):
        """Update message to show all skipped."""
        embed = discord.Embed(
            title="⏭️ All Skipped",
            description=f"Skipped {count} transaction(s).",
            color=discord.Color.dark_grey()
        )
        # Disable buttons
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)


async def get_or_create_user_thread(
    channel: discord.TextChannel,
    user_id: int,
    bot: discord.Client
) -> Optional[discord.Thread]:
    """
    Get existing private thread for user or create a new one.
    Thread named: Approvals-{username}
    """
    # Get user for naming
    user = bot.get_user(user_id)
    if not user:
        try:
            user = await bot.fetch_user(user_id)
        except BaseException:
            user = None

    username = user.display_name if user else str(user_id)
    thread_name = f"Approvals-{username}"

    try:
        # Check active threads
        for thread in channel.threads:
            if thread.name == thread_name:
                logger.info(f"Found existing thread for user {user_id}")
                return thread

        # Check archived threads
        async for thread in channel.archived_threads(limit=100):
            if thread.name == thread_name:
                logger.info(f"Unarchiving thread for user {user_id}")
                await thread.edit(archived=False)
                return thread

        # Create new private thread
        thread = await channel.create_thread(
            name=thread_name,
            type=discord.ChannelType.private_thread,
            reason=f"Approval thread for {username}"
        )

        # Add user to thread
        if user:
            await thread.add_user(user)
            logger.info(
                f"Created private thread '{thread_name}' and added user")
        else:
            logger.warning(f"Could not fetch user {user_id} to add to thread")

        return thread

    except discord.Forbidden:
        logger.error("Bot lacks permission to create private threads")
        return None
    except Exception as e:
        logger.error(f"Failed to get/create thread for user {user_id}: {e}")
        return None


def create_review_summary_embed(
    pending_count: int,
    auto_categorized: int,
    user_id: int
) -> discord.Embed:
    """Create embed summarizing transactions needing review."""
    embed = discord.Embed(
        title="🔍 Transactions Need Review",
        color=discord.Color.orange()
    )

    embed.add_field(
        name="✅ Auto-Categorized",
        value=str(auto_categorized),
        inline=True
    )
    embed.add_field(
        name="🔍 Need Review",
        value=str(pending_count),
        inline=True
    )

    embed.add_field(
        name="📋 Next Steps",
        value=(
            f"<@{user_id}> Click **Start Review** to process transactions one by one.\n"
            "You'll see each transaction with AI suggestions pre-filled.\n\n"
            "Or click **Skip All** to discard all pending transactions."
        ),
        inline=False
    )

    return embed


async def send_approval_requests(
    bot: discord.Client,
    pending_transactions: List[Dict[str, Any]],
    channel_id: int
) -> int:
    """
    Send a single review summary message to the user's private thread.
    Returns number of users notified.
    """
    channel = bot.get_channel(channel_id)
    if not channel:
        logger.error(f"Could not find approval channel {channel_id}")
        return 0

    # Group by user
    user_transactions: Dict[int, List[Dict[str, Any]]] = {}
    for pending in pending_transactions:
        uid = pending["user_id"]
        if uid not in user_transactions:
            user_transactions[uid] = []
        user_transactions[uid].append(pending)

    notified_count = 0

    for user_id, transactions in user_transactions.items():
        thread = await get_or_create_user_thread(channel, user_id, bot)
        if not thread:
            logger.error(f"Could not get thread for user {user_id}")
            continue

        try:
            # Note: auto_categorized count is passed via send_batch_summary, not here
            # We just know pending count
            embed = create_review_summary_embed(
                pending_count=len(transactions),
                auto_categorized=0,  # Will be shown in batch summary
                user_id=user_id
            )

            view = PendingReviewView(user_id, len(transactions))
            await thread.send(embed=embed, view=view)
            notified_count += 1

            logger.info(
                f"Sent review request to thread for user {user_id}: {len(transactions)} transactions")

        except Exception as e:
            logger.error(
                f"Failed to send review request for user {user_id}: {e}")

    return notified_count


async def send_batch_summary(
    bot: discord.Client,
    channel_id: int,
    auto_categorized: int,
    needs_approval: int,
    user_id: int
) -> None:
    """
    Send/update batch summary in user's thread.
    Note: The main review message (PendingReviewView) is sent by send_approval_requests.
    This just adds context about auto-categorized count.
    """
    channel = bot.get_channel(channel_id)
    if not channel:
        logger.error(f"Could not find channel {channel_id}")
        return

    thread = await get_or_create_user_thread(channel, user_id, bot)
    if not thread:
        logger.error("Could not get thread for batch summary")
        return

    embed = discord.Embed(
        title="📊 Processing Complete",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="✅ Auto-Uploaded",
        value=str(auto_categorized),
        inline=True)
    embed.add_field(
        name="🔍 Need Review",
        value=str(needs_approval),
        inline=True)

    if needs_approval > 0:
        embed.add_field(
            name="",
            value="Use the **Start Review** button above to process remaining transactions.",
            inline=False
        )
    else:
        embed.add_field(
            name="🎉",
            value="All transactions were auto-categorized!",
            inline=False
        )

    await thread.send(embed=embed)


def create_transaction_overview_embed(
    transactions: List[Dict[str, Any]],
    user_id: int
) -> discord.Embed:
    """Create an embed listing all transactions with AI suggestions for batch review."""
    embed = discord.Embed(
        title=f"🔍 {len(transactions)} Transactions Need Review",
        color=discord.Color.orange()
    )

    lines = []
    total_expense = 0.0
    total_income = 0.0
    max_display = 40

    for i, tx in enumerate(transactions, 1):
        if i > max_display:
            lines.append(f"\n... and {len(transactions) - max_display} more")
            break

        date = tx.get("booking_date", "??-??")[:5]
        amount_str = tx.get("transaction_amount", {}).get("amount", "0")
        try:
            amount = float(amount_str)
        except ValueError:
            amount = 0.0
        is_income = tx.get("credit_debit_indicator") == "CRDT"
        emoji = "💵" if is_income else "💸"

        if is_income:
            total_income += abs(amount)
        else:
            total_expense += abs(amount)

        counterparty = _get_counterparty_name(tx)
        if len(counterparty) > 22:
            counterparty = counterparty[:20] + ".."

        ai = tx.get("_ai_suggestion", {})
        ai_cat = ai.get("category", "—")
        ai_conf = int(ai.get("confidence", 0) * 100)

        lines.append(
            f"{emoji} `{date}` **{amount_str}** {counterparty}\n"
            f"      → _{ai_cat}_ ({ai_conf}%)"
        )

    embed.description = "\n".join(lines)

    embed.add_field(
        name="💰 Totals",
        value=f"Expenses: €{total_expense:.2f} | Income: €{total_income:.2f}",
        inline=False
    )

    embed.set_footer(text=f"User: {user_id}")
    return embed


class BatchReviewView(ui.View):
    """View with batch action buttons for processing remaining transactions."""

    def __init__(self, user_id: int, transaction_count: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.transaction_count = transaction_count

        accept_ai_btn = ui.Button(
            label=f"Accept All - AI ({transaction_count})",
            style=discord.ButtonStyle.success,
            emoji="🤖",
            custom_id=f"batch_accept_ai:{user_id}"
        )
        accept_ai_btn.callback = self.batch_accept_ai
        self.add_item(accept_ai_btn)

        accept_placeholder_btn = ui.Button(
            label="Accept All - Placeholder",
            style=discord.ButtonStyle.secondary,
            emoji="📦",
            custom_id=f"batch_accept_placeholder:{user_id}"
        )
        accept_placeholder_btn.callback = self.batch_accept_placeholder
        self.add_item(accept_placeholder_btn)

        start_btn = ui.Button(
            label="Start Review",
            style=discord.ButtonStyle.primary,
            emoji="📋",
            custom_id=f"batch_start_review:{user_id}"
        )
        start_btn.callback = self.start_review
        self.add_item(start_btn)

        skip_btn = ui.Button(
            label="Skip All",
            style=discord.ButtonStyle.danger,
            emoji="⏭️",
            custom_id=f"batch_skip_all:{user_id}"
        )
        skip_btn.callback = self.skip_all
        self.add_item(skip_btn)

    async def batch_accept_ai(self, interaction: discord.Interaction):
        """Batch accept all transactions with AI-suggested categories."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "You can only manage your own transactions.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        from finance_core.session_management import load_session, save_session
        from finance_core.background_upload import (
            queue_transaction_upload, get_upload_queue,
            sort_sheet_after_uploads_async
        )

        remaining, income, expenses = load_session(self.user_id)

        if not remaining:
            await interaction.followup.send(
                "Already processed - no remaining transactions.", ephemeral=True)
            return

        # Ensure upload queue is running
        queue = get_upload_queue()
        if not queue.is_running:
            queue.start()

        queued = 0
        for tx in remaining:
            ai = tx.get("_ai_suggestion", {})
            upload_tx = tx.copy()
            upload_tx.pop("_ai_suggestion", None)
            upload_tx["category"] = ai.get("category", "! Nog in te delen !")
            upload_tx["description"] = ai.get("description") or _get_counterparty_name(tx)

            tx_type = "income" if tx.get("credit_debit_indicator") == "CRDT" else "expense"
            queue_transaction_upload(upload_tx, tx_type, self.user_id)
            queued += 1

        save_session(self.user_id, [], income, expenses)

        await self._update_message_batch_complete(
            interaction, queued, "AI suggestions")
        await interaction.followup.send(
            f"✅ Queued {queued} transactions for upload with AI categories. "
            "Uploading in background...", ephemeral=True)

        task = asyncio.create_task(sort_sheet_after_uploads_async(timeout=120.0))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    async def batch_accept_placeholder(self, interaction: discord.Interaction):
        """Batch accept all transactions with '! Nog in te delen !' category."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "You can only manage your own transactions.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        from finance_core.session_management import load_session, save_session
        from finance_core.background_upload import (
            queue_transaction_upload, get_upload_queue,
            sort_sheet_after_uploads_async
        )

        remaining, income, expenses = load_session(self.user_id)

        if not remaining:
            await interaction.followup.send(
                "Already processed - no remaining transactions.", ephemeral=True)
            return

        queue = get_upload_queue()
        if not queue.is_running:
            queue.start()

        queued = 0
        for tx in remaining:
            upload_tx = tx.copy()
            upload_tx.pop("_ai_suggestion", None)
            upload_tx["category"] = "! Nog in te delen !"
            upload_tx["description"] = _get_counterparty_name(tx)

            tx_type = "income" if tx.get("credit_debit_indicator") == "CRDT" else "expense"
            queue_transaction_upload(upload_tx, tx_type, self.user_id)
            queued += 1

        save_session(self.user_id, [], income, expenses)

        await self._update_message_batch_complete(
            interaction, queued, "! Nog in te delen !")
        await interaction.followup.send(
            f"✅ Queued {queued} transactions for upload as placeholder. "
            "Uploading in background...", ephemeral=True)

        task = asyncio.create_task(sort_sheet_after_uploads_async(timeout=120.0))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    async def start_review(self, interaction: discord.Interaction):
        """Start one-by-one review of remaining transactions."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "You can only manage your own transactions.", ephemeral=True)
            return

        from finance_core.ui.transaction_prompt import start_transaction_prompt

        # Update thread message to show in progress
        embed = discord.Embed(
            title="📋 Review In Progress",
            description="Reviewing transactions one by one...\n\nCheck your ephemeral messages below.",
            color=discord.Color.blue()
        )
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(embed=embed, view=self)
        except Exception:
            pass

        await interaction.response.defer(ephemeral=True)
        await start_transaction_prompt(interaction, self.user_id)

    async def skip_all(self, interaction: discord.Interaction):
        """Skip all remaining transactions."""
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "You can only manage your own transactions.", ephemeral=True)
            return

        from finance_core.session_management import load_session, save_session

        remaining, income, expenses = load_session(self.user_id)
        count = len(remaining)
        save_session(self.user_id, [], income, expenses)

        embed = discord.Embed(
            title="⏭️ All Skipped",
            description=f"Skipped {count} transaction(s).",
            color=discord.Color.dark_grey()
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    async def _update_message_batch_complete(
            self, interaction: discord.Interaction, count: int, method: str):
        """Update thread message to show batch upload complete."""
        embed = discord.Embed(
            title="✅ Batch Upload Complete",
            description=f"Uploaded {count} transaction(s) using **{method}**.\n\n"
                        "Sheet will be sorted automatically.",
            color=discord.Color.green()
        )
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(embed=embed, view=self)
        except Exception:
            pass
