# finance_core/export.py

import discord
from discord.ext import commands
from finance_core.csv_helper import load_transactions_from_csv
from finance_core.session_management import (
    save_session, load_session, clear_session, session_exists
)
from finance_core.ui.transaction_prompt import start_transaction_prompt
from typing import Optional, Union
import os

async def send_message(ctx_or_interaction: Union[discord.Interaction, commands.Context], message: str, ephemeral: bool = False) -> None:
    """Helper function to send messages to both Context and Interaction objects"""
    if isinstance(ctx_or_interaction, discord.Interaction):
        if ctx_or_interaction.response.is_done():
            await ctx_or_interaction.followup.send(message, ephemeral=ephemeral)
        else:
            await ctx_or_interaction.response.send_message(message, ephemeral=ephemeral)
    else:
        # It's a Context object
        await ctx_or_interaction.send(message)

async def process_csv_file(file_path: Optional[str], ctx_or_interaction: Union[discord.Interaction, commands.Context]) -> None:
    """
    Process CSV file for both legacy context and new interaction patterns
    """
    # Handle both interaction and context objects
    if isinstance(ctx_or_interaction, discord.Interaction):
        user_id = ctx_or_interaction.user.id
    else:
        user_id = ctx_or_interaction.author.id

    if file_path:
        try:
            transactions = load_transactions_from_csv(file_path)
            income, expenses = [], []
        except Exception as e:
            error_msg = f"❌ Failed to load CSV file: {str(e)}"
            await send_message(ctx_or_interaction, error_msg, ephemeral=True)
            return
    else:
        transactions, income, expenses = load_session(user_id)

    if not transactions:
        success_msg = "✅ No transactions to process or failed to load data."
        await send_message(ctx_or_interaction, success_msg, ephemeral=True)
        return

    save_session(user_id, transactions, income, expenses)

    # Start processing the first transaction
    if isinstance(ctx_or_interaction, discord.Interaction):
        await start_transaction_prompt(ctx_or_interaction, user_id)
    else:
        # For legacy context, we need to convert to an interaction-like object
        # This is a simplified approach - you might need to adjust based on your UI needs
        success_msg = f"📊 Processing {len(transactions)} transactions. Please use slash commands for interactive processing."
        await send_message(ctx_or_interaction, success_msg)

    # Clear file once done if applicable
    if file_path and os.path.exists(file_path):
        os.remove(file_path)