# bot_commands.py

from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands
import os
import logging
import asyncio
from finance_core.csv_helper import load_transactions_from_csv
from finance_core.session_management import (
    session_exists, load_session, clear_session, save_session
)
from finance_core.ui.cached_transactions_view import CachedTransactionsView
from finance_core.export import process_csv_file
from config_settings import UPLOAD_DIR

logger = logging.getLogger(__name__)

class FinanceBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="resume", description="Resume a previously paused finance session")
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

    @app_commands.command(name="status", description="Check your current finance session status")
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
        progress_percent = (processed / total_transactions) * 100 if total_transactions > 0 else 0
        
        status_msg = f"📊 **Session Status**\n"
        status_msg += f"⏳ Remaining: {len(remaining)} | "
        status_msg += f"💵 Income: {len(income)} | "
        status_msg += f"💸 Expenses: {len(expenses)}\n"
        status_msg += f"📈 Progress: {progress_percent:.1f}% ({processed}/{total_transactions})"
        
        # Note: Transactions are automatically uploaded to Google Sheets upon categorization
        if processed > 0:
            status_msg += f"\n✅ {processed} transactions automatically uploaded to Google Sheets"
        
        await interaction.response.send_message(status_msg, ephemeral=True)
        # Auto-delete after 8 seconds
        response = await interaction.original_response()
        asyncio.create_task(self._delete_after_delay(response, 8))

    @app_commands.command(name="cancel", description="Cancel and delete your current session")
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

    @app_commands.command(name="upload", description="Upload a CSV file to start processing transactions")
    async def upload(self, interaction: discord.Interaction, attachment: discord.Attachment):
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
        file_path = os.path.join(UPLOAD_DIR, f"{user_id}_{attachment.filename}")
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

    @app_commands.command(name="cached", description="View and process your cached transactions")
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
                      f"📅 {cached_tx['timestamp'][:19].replace('T', ' ')}",  # Simple timestamp formatting
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

    async def _delete_after_delay(self, message, delay: int):
        """Delete a message after a delay"""
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except:
            pass  # Message might already be deleted

async def setup(bot):
    """Required function for loading the cog"""
    await bot.add_cog(FinanceBot(bot))
    logger.info("✅ FinanceBot cog loaded")
