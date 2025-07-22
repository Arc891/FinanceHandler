# bot_commands.py

from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands
import os
import logging
from finance_core.csv_helper import load_transactions_from_csv
from finance_core.session_management import (
    session_exists, load_session, clear_session, save_session
)
from finance_core.export import process_csv_file
from finance_core.google_sheets import export_to_google_sheets
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
            import asyncio
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
            import asyncio
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
            status_msg += f"\n✅ {processed} transactions have been uploaded to Google Sheets"
        
        await interaction.response.send_message(status_msg, ephemeral=True)
        # Auto-delete after 8 seconds
        import asyncio
        response = await interaction.original_response()
        asyncio.create_task(self._delete_after_delay(response, 8))

    @app_commands.command(name="export", description="Export your categorized transactions to Google Sheets")
    async def export_transactions(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not session_exists(user_id):
            await interaction.response.send_message("❌ No session found. Please upload and categorize transactions first.", ephemeral=True)
            return

        remaining, income, expenses = load_session(user_id)
        
        if not income and not expenses:
            await interaction.response.send_message("❌ No categorized transactions to export.", ephemeral=True)
            return
        
        if remaining:
            embed = discord.Embed(
                title="⚠️ Partial Export", 
                description=f"You have {len(remaining)} uncategorized transactions remaining.", 
                color=discord.Color.orange()
            )
            embed.add_field(name="Options", value="• Use `/resume` to continue categorizing\n• Click 'Export Now' to export categorized transactions and continue with remaining ones", inline=False)
            
            view = ExportConfirmView(user_id, income, expenses)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            # All transactions categorized, proceed with export
            await interaction.response.send_message("📤 Exporting transactions to Google Sheets...", ephemeral=True)
            await self._perform_export(interaction, user_id, income, expenses)

    async def _perform_export(self, interaction: discord.Interaction, user_id: int, income: list, expenses: list):
        """Perform the actual export to Google Sheets"""
        try:
            expense_count, income_count = export_to_google_sheets(income, expenses)
            
            # Update session to remove exported transactions, keeping only remaining ones
            remaining, _, _ = load_session(user_id)
            if remaining:
                # Keep the session alive with only remaining transactions
                save_session(user_id, remaining, [], [])
                session_status = f"Session updated: {len(remaining)} transactions remaining"
            else:
                # All transactions processed, clear the session
                clear_session(user_id)
                session_status = "Session completed and cleared"
            
            # Send concise success message
            message = f"✅ Exported {expense_count + income_count} transactions ({income_count} income, {expense_count} expenses) to Google Sheets!\n🔄 {session_status}"
            
            if interaction.response.is_done():
                response = await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
                response = await interaction.original_response()
            
            # Auto-delete after 8 seconds
            import asyncio
            asyncio.create_task(self._delete_after_delay(response, 8))
                
        except FileNotFoundError:
            error_msg = "❌ Google credentials not found. Check `src/config/google_service_account.json`"
            
            if interaction.response.is_done():
                response = await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)
                response = await interaction.original_response()
            
            # Auto-delete error after 10 seconds
            import asyncio
            asyncio.create_task(self._delete_after_delay(response, 10))
                
        except Exception as e:
            logger.error(f"Export failed for user {user_id}: {str(e)}")
            error_msg = f"❌ Export failed: {str(e)}"
            
            if interaction.response.is_done():
                response = await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)
                response = await interaction.original_response()
            
            # Auto-delete error after 10 seconds
            import asyncio
            asyncio.create_task(self._delete_after_delay(response, 10))

    async def _delete_after_delay(self, message, delay: int):
        """Delete a message after a delay"""
        import asyncio
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except:
            pass  # Message might already be deleted

    @app_commands.command(name="cancel", description="Cancel and delete your current session")
    async def cancel(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not session_exists(user_id):
            await interaction.response.send_message("❌ No session to cancel.", ephemeral=True)
            # Auto-delete after 3 seconds
            import asyncio
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 3))
            return

        clear_session(user_id)
        await interaction.response.send_message("✅ Session canceled and data cleared.", ephemeral=True)
        # Auto-delete after 5 seconds
        import asyncio
        response = await interaction.original_response()
        asyncio.create_task(self._delete_after_delay(response, 5))

    @app_commands.command(name="upload", description="Upload a CSV file to start processing transactions")
    async def upload(self, interaction: discord.Interaction, attachment: discord.Attachment):
        user_id = interaction.user.id

        if session_exists(user_id):
            await interaction.response.send_message("⚠️ Active session exists. Use `/cancel` first.", ephemeral=True)
            # Auto-delete after 5 seconds
            import asyncio
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 5))
            return

        if not attachment.filename.endswith(".csv"):
            await interaction.response.send_message("❌ Please upload a CSV file.", ephemeral=True)
            # Auto-delete after 4 seconds
            import asyncio
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
            import asyncio
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 8))
            # Clean up file if it exists
            if os.path.exists(file_path):
                os.remove(file_path)

class ExportConfirmView(discord.ui.View):
    """View for confirming export when there are still uncategorized transactions"""
    
    def __init__(self, user_id: int, income: list, expenses: list):
        super().__init__(timeout=None)  # No timeout to allow long-running sessions
        self.user_id = user_id
        self.income = income
        self.expenses = expenses
    
    @discord.ui.button(label="Export Now", style=discord.ButtonStyle.primary, emoji="📤")
    async def export_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ You cannot use this button.", ephemeral=True)
            return
        
        await interaction.response.send_message("📤 Exporting categorized transactions...", ephemeral=True)
        
        # Perform export directly
        try:
            expense_count, income_count = export_to_google_sheets(self.income, self.expenses)
            
            # Update session to remove exported transactions, keeping only remaining ones
            remaining, _, _ = load_session(self.user_id)
            if remaining:
                # Keep the session alive with only remaining transactions
                save_session(self.user_id, remaining, [], [])
                session_status = f"{len(remaining)} transactions remaining"
                session_emoji = "🔄"
            else:
                # All transactions processed, clear the session
                clear_session(self.user_id)
                session_status = "Session completed"
                session_emoji = "✅"
            
            embed = discord.Embed(
                title="✅ Export Successful!",
                description="Your transactions have been exported to Google Sheets.",
                color=discord.Color.green()
            )
            embed.add_field(name="💸 Expenses", value=str(expense_count), inline=True)
            embed.add_field(name="💵 Income", value=str(income_count), inline=True)
            embed.add_field(name="📊 Total", value=str(expense_count + income_count), inline=True)
            
            embed.add_field(name=f"{session_emoji} Session", value=session_status, inline=False)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            logger.error(f"Export failed for user {self.user_id}: {str(e)}")
            error_embed = discord.Embed(
                title="❌ Export Failed",
                description=f"An error occurred during export: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)
        
        # Disable the buttons
        self.export_now.disabled = True
        self.continue_categorizing.disabled = True
        await interaction.edit_original_response(view=self)
    
    @discord.ui.button(label="Continue Categorizing", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def continue_categorizing(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ You cannot use this button.", ephemeral=True)
            return
        
        await interaction.response.send_message("🔄 Resuming categorization...", ephemeral=True)
        await process_csv_file(file_path=None, ctx_or_interaction=interaction)
        
        # Disable the buttons
        self.export_now.disabled = True
        self.continue_categorizing.disabled = True
        await interaction.edit_original_response(view=self)

async def setup(bot):
    """Required function for loading the cog"""
    await bot.add_cog(FinanceBot(bot))
    logger.info("✅ FinanceBot cog loaded")
