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

logger = logging.getLogger(__name__)

class FinanceBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="resume", description="Resume a previously paused finance session")
    async def resume(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not session_exists(user_id):
            await interaction.response.send_message("❌ There is no session to resume.", ephemeral=True)
            return

        await interaction.response.send_message("🔄 Resuming your saved transaction session...", ephemeral=True)
        await process_csv_file(file_path=None, ctx_or_interaction=interaction)

    @app_commands.command(name="status", description="Check your current finance session status")
    async def status(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not session_exists(user_id):
            await interaction.response.send_message("❌ You have no active session.", ephemeral=True)
            return

        remaining, income, expenses = load_session(user_id)
        embed = discord.Embed(title="📊 Session Status", color=discord.Color.blue())
        embed.add_field(name="⏳ Remaining", value=len(remaining), inline=True)
        embed.add_field(name="💵 Income", value=len(income), inline=True)
        embed.add_field(name="💸 Expenses", value=len(expenses), inline=True)
        
        total_transactions = len(remaining) + len(income) + len(expenses)
        processed = len(income) + len(expenses)
        
        if total_transactions > 0:
            progress_percent = (processed / total_transactions) * 100
            embed.add_field(name="📈 Progress", value=f"{progress_percent:.1f}% ({processed}/{total_transactions})", inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
                title="⚠️ Incomplete Session", 
                description=f"You still have {len(remaining)} uncategorized transactions.", 
                color=discord.Color.orange()
            )
            embed.add_field(name="Options", value="• Use `/resume` to continue categorizing\n• Click 'Export Anyway' to export only categorized transactions", inline=False)
            
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
            
            embed = discord.Embed(
                title="✅ Export Successful!",
                description="Your transactions have been exported to Google Sheets.",
                color=discord.Color.green()
            )
            embed.add_field(name="💸 Expenses", value=str(expense_count), inline=True)
            embed.add_field(name="💵 Income", value=str(income_count), inline=True)
            embed.add_field(name="📊 Total", value=str(expense_count + income_count), inline=True)
            
            # Clear the session after successful export
            clear_session(user_id)
            embed.add_field(name="🗑️ Session", value="Cleared after export", inline=False)
            
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
        except FileNotFoundError:
            error_embed = discord.Embed(
                title="❌ Configuration Error",
                description="Google service account credentials not found.",
                color=discord.Color.red()
            )
            error_embed.add_field(
                name="Setup Required",
                value="Please ensure `google_service_account.json` is in the `src/config/` directory.",
                inline=False
            )
            
            if interaction.response.is_done():
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
                
        except Exception as e:
            logger.error(f"Export failed for user {user_id}: {str(e)}")
            error_embed = discord.Embed(
                title="❌ Export Failed",
                description=f"An error occurred during export: {str(e)}",
                color=discord.Color.red()
            )
            
            if interaction.response.is_done():
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=error_embed, ephemeral=True)

    @app_commands.command(name="cancel", description="Cancel and delete your current session")
    async def cancel(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not session_exists(user_id):
            await interaction.response.send_message("❌ No session to cancel.", ephemeral=True)
            return

        clear_session(user_id)
        await interaction.response.send_message("❌ Your session has been canceled and data cleared.", ephemeral=True)

    @app_commands.command(name="upload", description="Upload a CSV file to start processing transactions")
    async def upload(self, interaction: discord.Interaction, attachment: discord.Attachment):
        user_id = interaction.user.id

        if session_exists(user_id):
            await interaction.response.send_message("⚠️ You already have an active session. Please finish or cancel it first.", ephemeral=True)
            return

        if not attachment.filename.endswith(".csv"):
            await interaction.response.send_message("❌ Please upload a valid CSV file.", ephemeral=True)
            return

        # Create user-specific filename to avoid conflicts
        file_path = os.path.join("uploads", f"{user_id}_{attachment.filename}")
        os.makedirs("uploads", exist_ok=True)

        try:
            await attachment.save(Path(file_path))
            await interaction.response.send_message("📥 File received. Processing...", ephemeral=True)
            await process_csv_file(file_path=file_path, ctx_or_interaction=interaction)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error processing file: {str(e)}", ephemeral=True)
            # Clean up file if it exists
            if os.path.exists(file_path):
                os.remove(file_path)

class ExportConfirmView(discord.ui.View):
    """View for confirming export when there are still uncategorized transactions"""
    
    def __init__(self, user_id: int, income: list, expenses: list):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.income = income
        self.expenses = expenses
    
    @discord.ui.button(label="Export Anyway", style=discord.ButtonStyle.primary, emoji="📤")
    async def export_anyway(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ You cannot use this button.", ephemeral=True)
            return
        
        await interaction.response.send_message("📤 Exporting categorized transactions...", ephemeral=True)
        
        # Perform export directly
        try:
            expense_count, income_count = export_to_google_sheets(self.income, self.expenses)
            
            embed = discord.Embed(
                title="✅ Export Successful!",
                description="Your transactions have been exported to Google Sheets.",
                color=discord.Color.green()
            )
            embed.add_field(name="💸 Expenses", value=str(expense_count), inline=True)
            embed.add_field(name="💵 Income", value=str(income_count), inline=True)
            embed.add_field(name="📊 Total", value=str(expense_count + income_count), inline=True)
            
            # Clear the session after successful export
            clear_session(self.user_id)
            embed.add_field(name="🗑️ Session", value="Cleared after export", inline=False)
            
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
        self.export_anyway.disabled = True
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
        self.export_anyway.disabled = True
        self.continue_categorizing.disabled = True
        await interaction.edit_original_response(view=self)

async def setup(bot):
    """Required function for loading the cog"""
    await bot.add_cog(FinanceBot(bot))
    print("✅ FinanceBot cog loaded successfully")
