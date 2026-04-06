# bot_commands.py

from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands
import os
import logging
import asyncio
from finance_core.session_management import (
    session_exists, load_session, clear_session
)
from finance_core.ui.cached_transactions_view import CachedTransactionsView
from finance_core.export import process_csv_file
from config.config_settings import UPLOAD_DIR

logger = logging.getLogger(__name__)


class FinanceBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="resume",
                          description="Resume a previously paused finance session")
    async def resume(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not session_exists(user_id):
            await interaction.response.send_message("❌ No session to resume.", ephemeral=True)
            # Auto-delete after 3 seconds
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 3))
            return

        await interaction.response.send_message("🔄 Resuming session...", ephemeral=True)
        await process_csv_file(file_path=None, ctx_or_interaction=interaction)

    @app_commands.command(name="status",
                          description="Check your current finance session status")
    async def status(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not session_exists(user_id):
            await interaction.response.send_message("❌ No active session.", ephemeral=True)
            # Auto-delete after 3 seconds
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 3))
            return

        remaining, income, expenses = load_session(user_id)
        total_transactions = len(remaining) + len(income) + len(expenses)
        processed = len(income) + len(expenses)
        progress_percent = (processed / total_transactions) * \
            100 if total_transactions > 0 else 0

        status_msg = "📊 **Session Status**\n"
        status_msg += f"⏳ Remaining: {len(remaining)} | "
        status_msg += f"💵 Income: {len(income)} | "
        status_msg += f"💸 Expenses: {len(expenses)}\n"
        status_msg += f"📈 Progress: {progress_percent:.1f}% ({processed}/{total_transactions})"

        # Note: Transactions are automatically uploaded to Google Sheets upon
        # categorization
        if processed > 0:
            status_msg += f"\n✅ {processed} transactions automatically uploaded to Google Sheets"

        await interaction.response.send_message(status_msg, ephemeral=True)
        # Auto-delete after 8 seconds
        response = await interaction.original_response()
        asyncio.create_task(self._delete_after_delay(response, 8))

    @app_commands.command(name="cancel",
                          description="Cancel and delete your current session")
    async def cancel(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not session_exists(user_id):
            await interaction.response.send_message("❌ No session to cancel.", ephemeral=True)
            # Auto-delete after 3 seconds
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 3))
            return

        clear_session(user_id)
        await interaction.response.send_message("✅ Session canceled and data cleared.", ephemeral=True)
        # Auto-delete after 5 seconds
        response = await interaction.original_response()
        asyncio.create_task(self._delete_after_delay(response, 5))

    @app_commands.command(name="upload",
                          description="Upload a CSV file to start processing transactions")
    async def upload(self, interaction: discord.Interaction,
                     attachment: discord.Attachment):
        user_id = interaction.user.id

        if session_exists(user_id):
            await interaction.response.send_message("⚠️ Active session exists. Use `/cancel` first.", ephemeral=True)
            # Auto-delete after 5 seconds
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 5))
            return

        if not attachment.filename.endswith(".csv"):
            await interaction.response.send_message("❌ Please upload a CSV file.", ephemeral=True)
            # Auto-delete after 4 seconds
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 4))
            return

        # Create user-specific filename to avoid conflicts
        file_path = os.path.join(
            UPLOAD_DIR, f"{user_id}_{attachment.filename}")
        os.makedirs(UPLOAD_DIR, exist_ok=True)

        try:
            await attachment.save(Path(file_path))
            await interaction.response.send_message("📥 Processing CSV file...", ephemeral=True)
            await process_csv_file(file_path=file_path, ctx_or_interaction=interaction)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
            # Auto-delete error after 8 seconds
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 8))
            # Clean up file if it exists
            if os.path.exists(file_path):
                os.remove(file_path)

    @app_commands.command(name="cached",
                          description="View and process your cached transactions")
    async def cached(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        try:
            from finance_core.session_management import get_cached_transactions
            cached_transactions = get_cached_transactions(user_id)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error loading cached transactions: {str(e)}", ephemeral=True)
            return

        if not cached_transactions:
            await interaction.response.send_message("📦 No cached transactions found.", ephemeral=True)
            # Auto-delete after 3 seconds
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 3))
            return

        # Create summary of cached transactions
        embed = discord.Embed(
            title="📦 Cached Transactions",
            description=f"You have {len(cached_transactions)} cached transaction(s)",
            color=discord.Color.orange()
        )

        # Add up to 10 transactions to avoid embed limits
        for i, cached_tx in enumerate(cached_transactions[:10]):
            tx_type_emoji = "💵" if cached_tx["transaction_type"] == "income" else "💸"
            embed.add_field(
                name=f"{tx_type_emoji} {cached_tx['cache_id']} - {cached_tx['amount']} EUR",
                value=f"**{cached_tx['auto_description'][:100]}{'...' if len(cached_tx['auto_description']) > 100 else ''}**\n"
                      # Simple timestamp formatting
                      f"📅 {cached_tx['timestamp'][:19].replace('T', ' ')}",
                inline=False
            )

        if len(cached_transactions) > 10:
            embed.add_field(
                name="📋 More transactions",
                value=f"... and {len(cached_transactions) - 10} more. Use the buttons below to process them.",
                inline=False
            )

        # Add processing instructions
        embed.add_field(
            name="🔧 Next Steps",
            value="Use **Process Cached** to categorize these transactions properly.\n"
                  "Use **Clear All** to remove all cached transactions.\n"
                  "⚠️ Processed transactions will replace the dummy entries in your Google Sheet.",
            inline=False
        )

        # Create view with action buttons
        view = CachedTransactionsView(user_id, cached_transactions)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="review",
                          description="Review auto-categorized transactions from current session")
    async def review(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        try:
            from finance_core.session_management import get_auto_categorized_transactions
            auto_cats = get_auto_categorized_transactions(user_id)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error loading auto-categorizations: {str(e)}", ephemeral=True)
            return

        if not auto_cats:
            await interaction.response.send_message("✅ No auto-categorized transactions in current session.", ephemeral=True)
            # Auto-delete after 3 seconds
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 3))
            return

        # Create summary embed
        embed = discord.Embed(
            title="🤖 Auto-Categorized Transactions",
            description=f"Review {len(auto_cats)} automatically categorized transaction{'s' if len(auto_cats) > 1 else ''} from your current session.",
            color=discord.Color.green()
        )

        # Add up to 10 transactions to avoid embed limits
        for i, auto_cat in enumerate(auto_cats[:10]):
            tx = auto_cat["transaction"]
            amount = tx.get("transaction_amount", {}).get("amount", "0")
            tx_type_emoji = "💵" if auto_cat["transaction_type"] == "income" else "💸"
            method_emoji = "📋" if auto_cat["method"] == "regex" else "🤖"
            confidence_pct = int(auto_cat["confidence"] * 100)

            # Get counterparty name
            counterparty = tx.get(
                "creditor",
                {}).get("name") or tx.get(
                "debtor",
                {}).get(
                "name",
                "Unknown")

            embed.add_field(
                name=f"{tx_type_emoji} {method_emoji} {counterparty} - €{amount}",
                value=f"**{auto_cat['category']}** • {auto_cat['description'][:80]}{'...' if len(auto_cat['description']) > 80 else ''}\n"
                      f"Confidence: {confidence_pct}%",
                inline=False
            )

        if len(auto_cats) > 10:
            embed.add_field(
                name="📋 More transactions",
                value=f"... and {len(auto_cats) - 10} more auto-categorized transactions.",
                inline=False
            )

        # Add legend and notes
        legend = "📋 = Regex matched | 🤖 = AI categorized\n"
        legend += "💸 = Expense | 💵 = Income\n\n"
        legend += "✅ All transactions shown have been uploaded to Google Sheets.\n"
        legend += "⚠️ To correct a categorization, you'll need to edit it directly in your Google Sheet or use the background upload queue."

        embed.add_field(
            name="ℹ️ Legend & Notes",
            value=legend,
            inline=False
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
        # Auto-delete after 60 seconds to keep chat clean
        response = await interaction.original_response()
        asyncio.create_task(self._delete_after_delay(response, 60))

    @app_commands.command(name="pending",
                          description="Resend notification for pending approval transactions")
    async def pending(self, interaction: discord.Interaction):
        """Show batch review overview for pending/remaining transactions."""
        user_id = interaction.user.id

        try:
            from finance_core.pending_transactions import (
                get_user_pending_transactions, clear_user_pending
            )
            from finance_core.session_management import load_session, save_session
            from finance_core.ui.discord_notifier import (
                get_or_create_user_thread,
                create_transaction_overview_embed,
                BatchReviewView
            )
            from config.config_settings import REMINDER_CHANNEL_ID

            # Merge pending queue items into session remaining
            pending_queue = get_user_pending_transactions(user_id)
            if pending_queue:
                transactions_for_session = []
                for item in pending_queue:
                    tx = item["transaction"].copy()
                    if item.get("ai_category"):
                        tx["_ai_suggestion"] = {
                            "category": item["ai_category"],
                            "description": item.get("ai_description", ""),
                            "confidence": item.get("ai_confidence", 0)
                        }
                    transactions_for_session.append(tx)

                existing_remaining, existing_income, existing_expenses = load_session(user_id)
                all_remaining = transactions_for_session + existing_remaining
                save_session(user_id, all_remaining, existing_income, existing_expenses)
                clear_user_pending(user_id)
                logger.info(f"Merged {len(pending_queue)} pending queue items into session for user {user_id}")

            # Load unified remaining list
            remaining, _, _ = load_session(user_id)

            if not remaining:
                await interaction.response.send_message(
                    "✅ No pending transactions to review.", ephemeral=True)
                response = await interaction.original_response()
                asyncio.create_task(self._delete_after_delay(response, 3))
                return

            await interaction.response.send_message(
                f"📤 Sending overview for {len(remaining)} transactions...",
                ephemeral=True)

            # Get or create thread and send notification
            channel = self.bot.get_channel(REMINDER_CHANNEL_ID)
            if not channel:
                await interaction.edit_original_response(
                    content="❌ Could not find approval channel.")
                return

            thread = await get_or_create_user_thread(channel, user_id, self.bot)
            if not thread:
                await interaction.edit_original_response(
                    content="❌ Could not create approval thread.")
                return

            embed = create_transaction_overview_embed(remaining, user_id)
            view = BatchReviewView(user_id, len(remaining))
            await thread.send(embed=embed, view=view)

            await interaction.edit_original_response(
                content=f"✅ Sent! Check your thread for {len(remaining)} transactions.")
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 5))

        except Exception as e:
            logger.error(f"Error in /pending command: {e}", exc_info=True)
            await interaction.edit_original_response(
                content=f"❌ Error: {str(e)}")

    @app_commands.command(name="resetsheet",
                          description="Reset Google Sheets connection and re-detect row positions")
    async def resetsheet(self, interaction: discord.Interaction):
        """Reset the sheet exporter and re-detect row positions (owner only)"""
        user_id = interaction.user.id

        # Access control: only bot owners (from MENTION_USER_IDS) can use this
        try:
            from config.config_settings import MENTION_USER_IDS
            if user_id not in MENTION_USER_IDS:
                await interaction.response.send_message(
                    "❌ Only bot owners can use this command.", ephemeral=True)
                response = await interaction.original_response()
                asyncio.create_task(self._delete_after_delay(response, 5))
                return
        except ImportError:
            pass  # If config unavailable, allow anyone (dev mode)

        await interaction.response.send_message(
            "🔄 Resetting Google Sheets connection...", ephemeral=True)

        try:
            from finance_core.background_upload import get_upload_queue

            queue = get_upload_queue()

            # Reset the exporter (forces full reconnection)
            if queue.exporter:
                queue.exporter.sheet = None
                queue.exporter.client = None

            # Reset and re-detect positions
            queue.reset_row_positions(user_id)

            result_msg = "✅ Sheet connection reset!\n"
            result_msg += f"📍 Detected positions: expenses=row {queue.current_expense_row}, income=row {queue.current_income_row}"

            await interaction.edit_original_response(content=result_msg)
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 15))

        except Exception as e:
            logger.error(f"Error in /resetsheet command: {e}", exc_info=True)
            await interaction.edit_original_response(
                content=f"❌ Error: {str(e)}")

    @app_commands.command(name="sort",
                          description="Sort all transactions in Google Sheets by date")
    async def sort_sheet(self, interaction: discord.Interaction):
        """Manually trigger sorting of all transactions in Google Sheets by date"""
        await interaction.response.send_message("📊 Sorting transactions by date...", ephemeral=True)

        try:
            from finance_core.google_sheets import sort_google_sheet_transactions

            # Run sort in executor to not block event loop
            loop = asyncio.get_event_loop()
            expense_sorted, income_sorted = await loop.run_in_executor(
                None, sort_google_sheet_transactions
            )

            result_msg = "✅ Sort complete!\n"
            result_msg += f"📊 Sorted {expense_sorted} expense rows and {income_sorted} income rows by date."

            await interaction.edit_original_response(content=result_msg)
            # Auto-delete after 10 seconds
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 10))

        except Exception as e:
            logger.error(f"Error sorting sheet: {e}", exc_info=True)
            await interaction.edit_original_response(content=f"❌ Error sorting sheet: {str(e)}")
            # Auto-delete after 10 seconds
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 10))

    async def _delete_after_delay(self, message, delay: int):
        """Delete a message after a delay"""
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except BaseException:
            pass  # Message might already be deleted


async def setup(bot):
    """Required function for loading the cog"""
    await bot.add_cog(FinanceBot(bot))
    logger.info("✅ FinanceBot cog loaded")
