# finance_core/export.py

import discord
from discord.ext import commands
from finance_core.csv_helper import load_transactions_from_csv
from finance_core.session_management import (
    save_session, load_session, clear_session, session_exists,
    add_auto_categorized_transaction
)
from finance_core.ui.transaction_prompt import start_transaction_prompt
from typing import Optional, Union
import os
import logging

logger = logging.getLogger(__name__)

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
    Process CSV file with automatic categorization for high-confidence transactions.

    Flow:
    1. Load transactions from CSV
    2. Run categorization engine on all (regex + AI)
    3. Auto-upload high confidence (≥75%) immediately
    4. Manual review for low confidence (<75%)
    """
    # Handle both interaction and context objects
    if isinstance(ctx_or_interaction, discord.Interaction):
        user_id = ctx_or_interaction.user.id
    else:
        user_id = ctx_or_interaction.author.id

    # Load transactions
    if file_path:
        try:
            transactions = load_transactions_from_csv(file_path)
        except Exception as e:
            error_msg = f"❌ Failed to load CSV file: {str(e)}"
            await send_message(ctx_or_interaction, error_msg, ephemeral=True)
            return
    else:
        # Resume existing session
        transactions, income, expenses = load_session(user_id)

    if not transactions:
        success_msg = "✅ No transactions to process or failed to load data."
        await send_message(ctx_or_interaction, success_msg, ephemeral=True)
        return

    # Check if AI categorization is available
    try:
        from finance_core.categorization_engine import create_categorization_engine
        from automation.claude_provider import ClaudeProvider

        # Auto-enable AI if Claude CLI detected (5C)
        provider = ClaudeProvider(api_key=None, model="haiku")
        ai_enabled = provider.use_cli or provider.api_client is not None

        if ai_enabled:
            logger.info("AI categorization enabled - will auto-categorize high-confidence transactions")
        else:
            logger.info("AI categorization disabled - only regex matching available")

        engine = create_categorization_engine(ai_enabled=ai_enabled)
    except Exception as e:
        logger.warning(f"Failed to initialize categorization engine: {e}. Falling back to manual mode.")
        # Fallback: Save all transactions for manual processing
        save_session(user_id, transactions, [], [])
        if isinstance(ctx_or_interaction, discord.Interaction):
            await start_transaction_prompt(ctx_or_interaction, user_id)
        else:
            await send_message(ctx_or_interaction, f"📊 Processing {len(transactions)} transactions manually.")
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        return

    # Categorize all transactions
    logger.info(f"Processing {len(transactions)} transactions with categorization engine")
    auto_categorized_count = {"regex": 0, "ai": 0}
    manual_needed = []

    for tx in transactions:
        result = engine.categorize(tx)

        if result.method in ['regex', 'ai_auto']:
            # High confidence - auto-upload
            tx_type = "income" if tx.get("credit_debit_indicator") == "CRDT" else "expense"

            # Create categorized transaction
            categorized_tx = {
                **tx,
                "category": result.category,
                "description": result.description
            }

            # Queue for immediate upload
            try:
                from finance_core.background_upload import queue_transaction_upload
                queue_transaction_upload(categorized_tx, tx_type, user_id)

                # Track in session for /review command
                add_auto_categorized_transaction(
                    user_id=user_id,
                    transaction=tx,
                    category=result.category,
                    description=result.description,
                    transaction_type=tx_type,
                    method=result.method,
                    confidence=result.confidence
                )

                if result.method == 'regex':
                    auto_categorized_count["regex"] += 1
                else:
                    auto_categorized_count["ai"] += 1

            except Exception as e:
                logger.error(f"Failed to queue auto-categorized transaction: {e}")
                # On error, add to manual queue
                manual_needed.append(tx)
        else:
            # Low confidence or no match - needs manual review
            manual_needed.append(tx)

    # Save session with manual-review transactions
    save_session(user_id, manual_needed, [], [])

    # Show summary message (4A)
    total_auto = auto_categorized_count["regex"] + auto_categorized_count["ai"]
    summary = f"✅ Auto-categorized {total_auto}/{len(transactions)} transactions"
    if auto_categorized_count["regex"] > 0:
        summary += f" ({auto_categorized_count['regex']} regex"
    if auto_categorized_count["ai"] > 0:
        if auto_categorized_count["regex"] > 0:
            summary += f", {auto_categorized_count['ai']} AI"
        else:
            summary += f" ({auto_categorized_count['ai']} AI"
    if total_auto > 0:
        summary += ")"

    if manual_needed:
        summary += f"\n🔍 {len(manual_needed)} transaction{'s' if len(manual_needed) > 1 else ''} need manual review."
        if total_auto > 0:
            summary += f"\n\n💡 Use `/review` to check auto-categorizations."
    else:
        summary += "\n\n🎉 All transactions processed automatically!"
        if total_auto > 0:
            summary += f"\n💡 Use `/review` to check categorizations."

    await send_message(ctx_or_interaction, summary, ephemeral=True)

    # Start manual processing if needed
    if manual_needed and isinstance(ctx_or_interaction, discord.Interaction):
        await start_transaction_prompt(ctx_or_interaction, user_id)
    elif manual_needed:
        # For legacy context
        await send_message(ctx_or_interaction, "📊 Starting manual categorization. Use slash commands.")

    # Clear file once done
    if file_path and os.path.exists(file_path):
        os.remove(file_path)