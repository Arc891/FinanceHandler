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

    # Categorize all transactions with progress feedback
    logger.info(f"Processing {len(transactions)} transactions with categorization engine")
    auto_categorized_count = {"regex": 0, "ai": 0}
    manual_needed = []
    auto_income = []
    auto_expenses = []

    # Send initial progress message
    progress_msg = await send_message(ctx_or_interaction, "🔄 Categorizing transactions...", ephemeral=True)

    try:
        for i, tx in enumerate(transactions, 1):
            result = await engine.categorize(tx)

            # Update progress every 5 transactions or on AI categorization
            if i % 5 == 0 or result.method == 'ai_auto':
                progress_text = f"🔄 Processing {i}/{len(transactions)} transactions..."
                if result.method == 'ai_auto':
                    progress_text += f" (🤖 AI: {result.category})"

                # Update progress message
                try:
                    if isinstance(ctx_or_interaction, discord.Interaction):
                        await ctx_or_interaction.edit_original_response(content=progress_text)
                except:
                    pass  # Ignore if message update fails

            if result.method in ['regex', 'ai_auto']:
                # High confidence - store for later upload
                tx_type = "income" if tx.get("credit_debit_indicator") == "CRDT" else "expense"

                # Create categorized transaction
                categorized_tx = {
                    **tx,
                    "category": result.category,
                    "description": result.description
                }

                # Store in session (will upload after sorting)
                if tx_type == "income":
                    auto_income.append(categorized_tx)
                else:
                    auto_expenses.append(categorized_tx)

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
            else:
                # Low confidence or no match - needs manual review
                # Store transaction WITH the AI result to avoid re-categorizing
                manual_needed.append({
                    "transaction": tx,
                    "ai_category": result.category,
                    "ai_description": result.description,
                    "ai_confidence": result.confidence
                })
    except Exception as e:
        logger.error(f"Error during categorization loop: {e}", exc_info=True)
        # Save whatever we categorized so far before crashing
        # Extract raw transactions for session storage
        raw_manual = [item["transaction"] if isinstance(item, dict) and "transaction" in item else item for item in manual_needed]
        save_session(user_id, raw_manual, auto_income, auto_expenses)
        await send_message(ctx_or_interaction, f"❌ Error during categorization: {e}\nPartial progress saved. Use `/resume` to continue.", ephemeral=True)
        raise  # Re-raise to let caller handle

    # Upload auto-categorized transactions IMMEDIATELY (don't wait for manual review)
    total_auto = auto_categorized_count["regex"] + auto_categorized_count["ai"]

    if auto_income or auto_expenses:
        logger.info(f"Uploading {len(auto_income)} income + {len(auto_expenses)} expenses immediately")
        await _upload_auto_categorized(user_id, auto_income, auto_expenses, ctx_or_interaction)

    # Save session with ONLY manual-needed transactions (auto ones are already uploaded)
    # Extract raw transactions for session storage (manual_needed contains dicts with AI results)
    raw_manual = [item["transaction"] for item in manual_needed]
    save_session(user_id, raw_manual, [], [])

    # Show summary message
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

    if total_auto > 0:
        summary += f"\n📤 Uploaded {total_auto} auto-categorized transactions!"

    if manual_needed:
        summary += f"\n🔍 {len(manual_needed)} transaction{'s' if len(manual_needed) > 1 else ''} need manual review."
        if total_auto > 0:
            summary += f"\n💡 Use `/review` to check auto-categorizations."
    else:
        summary += "\n\n🎉 All transactions processed automatically!"
        if total_auto > 0:
            summary += f"\n💡 Use `/review` to check categorizations."

    # Log summary (in case Discord message fails)
    logger.info(f"Summary: {summary.replace(chr(10), ' ')}")

    # Update final progress message (may fail if interaction token expired)
    try:
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.edit_original_response(content=summary)
            logger.debug("Successfully edited original response with summary")
        else:
            await send_message(ctx_or_interaction, summary, ephemeral=True)
            logger.debug("Successfully sent summary via send_message")
    except discord.errors.NotFound:
        logger.warning("Interaction token expired - unable to send summary message to Discord")
        # Continue anyway - upload and manual processing should still happen
    except Exception as e:
        logger.error(f"Failed to send summary message: {e}")
        # Continue anyway - upload and manual processing should still happen

    # Handle low-confidence transactions
    if manual_needed:
        # Check if approval channel is configured for proactive Discord approvals
        try:
            from config.config_settings import APPROVAL_CHANNEL_ID
        except ImportError:
            APPROVAL_CHANNEL_ID = 0

        if APPROVAL_CHANNEL_ID and APPROVAL_CHANNEL_ID > 0 and isinstance(ctx_or_interaction, discord.Interaction):
            # Use new proactive Discord approval flow
            await _send_approval_requests(
                ctx_or_interaction,
                manual_needed,
                user_id,
                total_auto
            )
            # Clear session since transactions are in pending queue
            clear_session(user_id)
        elif isinstance(ctx_or_interaction, discord.Interaction):
            # Fall back to manual review UI
            try:
                await start_transaction_prompt(ctx_or_interaction, user_id)
            except Exception as e:
                logger.error(f"Failed to start transaction prompt: {e}")
                logger.warning(f"User {user_id} should manually run /resume to continue categorization")
        else:
            # For legacy context
            await send_message(ctx_or_interaction, "📊 Starting manual categorization. Use slash commands.")

    # Clear file once done
    if file_path and os.path.exists(file_path):
        os.remove(file_path)


async def _send_approval_requests(
    ctx_or_interaction: Union[discord.Interaction, commands.Context],
    transactions_with_ai: list,
    user_id: int,
    auto_categorized_count: int
) -> None:
    """
    Add low-confidence transactions to pending queue and send Discord approval requests.

    Args:
        ctx_or_interaction: Discord interaction or context
        transactions_with_ai: List of dicts containing transaction + pre-computed AI results
        user_id: Discord user ID
        auto_categorized_count: Number of auto-categorized transactions (for summary)
    """
    from finance_core.pending_transactions import add_pending_transaction, get_user_pending_transactions
    from automation.discord_notifier import send_approval_requests, send_batch_summary
    from config.config_settings import APPROVAL_CHANNEL_ID

    logger.info(f"Adding {len(transactions_with_ai)} transactions to pending approval queue")

    # Add each transaction to pending queue (AI results already computed)
    for item in transactions_with_ai:
        tx = item["transaction"]
        tx_type = "income" if tx.get("credit_debit_indicator") == "CRDT" else "expense"

        add_pending_transaction(
            user_id=user_id,
            transaction=tx,
            ai_category=item.get("ai_category"),
            ai_description=item.get("ai_description"),
            ai_confidence=item.get("ai_confidence", 0.0),
            transaction_type=tx_type
        )

    # Get all pending transactions for this user
    pending_txs = get_user_pending_transactions(user_id)

    # Get the bot client from the interaction
    if isinstance(ctx_or_interaction, discord.Interaction):
        bot = ctx_or_interaction.client
    else:
        bot = ctx_or_interaction.bot

    # Send approval requests to Discord
    sent_count = await send_approval_requests(bot, pending_txs, APPROVAL_CHANNEL_ID)

    # Send summary message
    await send_batch_summary(
        bot=bot,
        channel_id=APPROVAL_CHANNEL_ID,
        auto_categorized=auto_categorized_count,
        needs_approval=len(pending_txs),
        user_id=user_id
    )

    logger.info(f"Sent {sent_count} approval requests to channel {APPROVAL_CHANNEL_ID}")


async def _upload_auto_categorized(
    user_id: int,
    income_txs: list,
    expense_txs: list,
    ctx_or_interaction: Union[discord.Interaction, commands.Context],
    trigger_sort: bool = True
) -> None:
    """Upload auto-categorized transactions immediately (sorted by date)."""
    from datetime import datetime

    if not income_txs and not expense_txs:
        logger.info("No auto-categorized transactions to upload")
        return

    def parse_date(tx):
        """Parse booking_date to datetime for sorting"""
        date_str = tx.get("booking_date", "01-01-1970")
        try:
            return datetime.strptime(date_str, "%d-%m-%Y")
        except:
            return datetime(1970, 1, 1)

    # Sort by date (oldest first) before queueing
    income_sorted = sorted(income_txs, key=parse_date)
    expenses_sorted = sorted(expense_txs, key=parse_date)

    logger.info(f"Queueing {len(income_sorted)} income + {len(expenses_sorted)} expenses for upload")

    try:
        from finance_core.background_upload import queue_transaction_upload, sort_sheet_after_uploads_async

        for tx in income_sorted:
            queue_transaction_upload(tx, "income", user_id)

        for tx in expenses_sorted:
            queue_transaction_upload(tx, "expense", user_id)

        logger.info(f"Successfully queued {len(income_sorted) + len(expenses_sorted)} auto-categorized transactions")

        # Trigger sheet sort after uploads complete (runs in background)
        if trigger_sort:
            logger.info("Triggering sheet sort after uploads complete...")
            await sort_sheet_after_uploads_async(timeout=120.0)

    except Exception as e:
        logger.error(f"Failed to queue auto-categorized transactions: {e}", exc_info=True)
        raise


async def _upload_sorted_transactions(user_id: int, ctx_or_interaction: Union[discord.Interaction, commands.Context]) -> None:
    """Sort all categorized transactions by date and upload to Google Sheets (for manual review completion)"""
    from datetime import datetime

    # Load all categorized transactions from session
    _, income_txs, expense_txs = load_session(user_id)

    if not income_txs and not expense_txs:
        logger.info("No transactions to upload from session")
        return

    def parse_date(tx):
        """Parse booking_date to datetime for sorting"""
        date_str = tx.get("booking_date", "01-01-1970")
        try:
            return datetime.strptime(date_str, "%d-%m-%Y")
        except:
            return datetime(1970, 1, 1)

    income_sorted = sorted(income_txs, key=parse_date)
    expenses_sorted = sorted(expense_txs, key=parse_date)

    logger.info(f"Uploading {len(income_sorted)} income + {len(expenses_sorted)} expenses sorted by date")

    try:
        from finance_core.background_upload import queue_transaction_upload, sort_sheet_after_uploads_async

        for tx in income_sorted:
            queue_transaction_upload(tx, "income", user_id)

        for tx in expenses_sorted:
            queue_transaction_upload(tx, "expense", user_id)

        upload_msg = f"📤 Uploaded {len(income_sorted) + len(expenses_sorted)} transactions sorted by date!"
        try:
            await send_message(ctx_or_interaction, upload_msg, ephemeral=True)
        except:
            pass  # Ignore message failures

        # Trigger sheet sort after uploads complete
        logger.info("Triggering sheet sort after manual review uploads...")
        await sort_sheet_after_uploads_async(timeout=120.0)

    except Exception as e:
        logger.error(f"Failed to queue sorted transactions: {e}")
        try:
            error_msg = f"❌ Error uploading transactions: {str(e)}"
            await send_message(ctx_or_interaction, error_msg, ephemeral=True)
        except:
            pass