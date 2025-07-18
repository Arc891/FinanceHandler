# bot_commands.py

from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands
import os
from finance_core.csv_helper import load_transactions_from_csv
from finance_core.session_management import (
    session_exists, load_session, clear_session, save_session
)
from finance_core.export import process_csv_file

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
        embed.add_field(name="Remaining", value=len(remaining), inline=True)
        embed.add_field(name="Income", value=len(income), inline=True)
        embed.add_field(name="Expenses", value=len(expenses), inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

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

async def setup(bot):
    """Required function for loading the cog"""
    await bot.add_cog(FinanceBot(bot))
    print("✅ FinanceBot cog loaded successfully")
