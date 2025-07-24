# finance_core/ui/transaction_prompt.py

import discord
from discord.ui import View, Button, Select, Modal, TextInput
from typing import List, Dict, Any, Tuple, Optional
import re
import asyncio
import logging
from finance_core.session_management import load_session, save_session, clear_session

logger = logging.getLogger(__name__)

# Import the proper categories from constants
try:
    from constants import ExpenseCategory, IncomeCategory, CATEGORIZATION_RULES_EXPENSE, CATEGORIZATION_RULES_INCOME
    CATEGORY_OPTIONS = {
        "income": [cat.value for cat in IncomeCategory if cat != IncomeCategory.DUMMY_CACHED],
        "expense": [cat.value for cat in ExpenseCategory if cat != ExpenseCategory.DUMMY_CACHED]
    }
except ImportError:
    # Fallback to simple categories if constants not available
    CATEGORY_OPTIONS = {
        "income": ["Salary", "Gift", "Interest", "Other"],
        "expense": ["Food", "Transport", "Entertainment", "Bills", "Other"]
    }
    CATEGORIZATION_RULES_EXPENSE = {}
    CATEGORIZATION_RULES_INCOME = {}


def apply_categorization_rules(transaction: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Apply categorization rules to suggest category and description.
    Returns (suggested_category, suggested_description) or (None, None) if no match.
    """
    # Determine transaction type
    is_income = transaction.get("credit_debit_indicator") == "CRDT"
    rules = CATEGORIZATION_RULES_INCOME if is_income else CATEGORIZATION_RULES_EXPENSE
    
    if not rules:
        return None, None
    
    # Gather text to search from various transaction fields
    search_texts = []
    
    # Add counterparty names
    if debtor_name := transaction.get("debtor", {}).get("name"):
        search_texts.append(debtor_name.lower())
    if creditor_name := transaction.get("creditor", {}).get("name"):
        search_texts.append(creditor_name.lower())
    
    # Add remittance information
    remittance = transaction.get("remittance_information", [])
    for item in remittance:
        if item:
            search_texts.append(item.lower())
    
    # Combine all text for searching
    combined_text = " ".join(search_texts)
    
    # Try each rule pattern
    for pattern, (description_template, category) in rules.items():
        match = re.search(pattern, combined_text, re.IGNORECASE)
        if match:
            # Generate description using template
            if "{c}" in description_template:
                # Extract the matched text for {c} placeholder
                matched_text = match.group(1) if match.groups() else match.group(0)
                suggested_description = description_template.replace("{c}", matched_text.title())
            else:
                suggested_description = description_template
            
            return category.value, suggested_description
    
    return None, None

class DescriptionModal(Modal):
    def __init__(self, transaction_view, suggested_description: str):
        super().__init__(title="Confirm Transaction & Description")
        self.transaction_view = transaction_view
        
        # Truncate placeholder to Discord's 100 character limit
        placeholder_text = suggested_description[:95] + "..." if len(suggested_description) > 95 else suggested_description
        
        self.description_input = TextInput(
            label="Transaction Description",
            placeholder=placeholder_text,
            max_length=500,
            required=False,  # Allow empty to use auto-description
            style=discord.TextStyle.paragraph,
            default=suggested_description[:500]  # Pre-fill with suggestion
        )
        self.add_item(self.description_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        # Store the custom description in the transaction view
        custom_desc = self.description_input.value.strip()
        self.transaction_view.custom_description = custom_desc
        
        # Complete the transaction with the description
        await self.transaction_view.complete_transaction(interaction, custom_desc)
    
    async def _delete_after_delay(self, interaction: discord.Interaction, delay: int):
        await asyncio.sleep(delay)
        try:
            await interaction.delete_original_response()
        except:
            pass  # Message might already be deleted

class TransactionView(View):
    def __init__(self, user_id: int, transaction: Dict[str, Any]):
        super().__init__(timeout=300)  # 5 minute timeout instead of None
        self.user_id = user_id
        self.transaction = transaction
        self.transaction_type = "income" if transaction["credit_debit_indicator"] == "CRDT" else "expense"
        self.custom_description = None
        
        # Apply categorization rules to get smart defaults
        suggested_category, suggested_description = apply_categorization_rules(transaction)
        self.selected_category = suggested_category
        self.suggested_description = suggested_description

        self.switch_type_button = Button(label=f"Switch to {'expense' if self.transaction_type == 'income' else 'income'}", style=discord.ButtonStyle.secondary)
        self.switch_type_button.callback = self.switch_type
        self.add_item(self.switch_type_button)

        # Limit categories to 25 (Discord's maximum for select options)
        categories = CATEGORY_OPTIONS[self.transaction_type][:25]
        
        # Create category select with smart default
        category_options = []
        for cat in categories:
            option = discord.SelectOption(label=cat)
            # Pre-select the suggested category if we have one
            if suggested_category and cat == suggested_category:
                option.default = True
            category_options.append(option)
        
        self.category_select = Select(
            placeholder="Select a category" if not suggested_category else f"✨ Suggested: {suggested_category}",
            options=category_options
        )
        self.category_select.callback = self.select_category
        self.add_item(self.category_select)

        self.confirm_button = Button(label="Confirm & Add Description", style=discord.ButtonStyle.success)
        self.confirm_button.callback = self.confirm_transaction
        self.add_item(self.confirm_button)

        self.skip_button = Button(label="Skip Transaction", style=discord.ButtonStyle.secondary)
        self.skip_button.callback = self.skip_transaction
        self.add_item(self.skip_button)

        self.cache_button = Button(label="Cache for Later", style=discord.ButtonStyle.secondary)
        self.cache_button.callback = self.cache_transaction
        self.add_item(self.cache_button)

    def _extract_suggested_description(self, transaction: Dict[str, Any]) -> str:
        """Extract a suggested description from transaction data"""
        description_parts = []
        
        # Add counterparty information (most important)
        debtor_name = transaction.get("debtor", {}).get("name", "")
        creditor_name = transaction.get("creditor", {}).get("name", "")
        counterparty = debtor_name or creditor_name
        if counterparty:
            # Clean up common bank codes/prefixes to make it more readable
            cleaned_counterparty = counterparty.replace("NL", "").replace("INGB", "").strip()
            description_parts.append(cleaned_counterparty)
        
        # Add first line of remittance information (transaction details)
        remittance = transaction.get("remittance_information", [])
        if remittance and remittance[0]:
            first_line = remittance[0].strip()
            if first_line and first_line not in description_parts:
                # Clean up common patterns to make it more readable
                cleaned_remittance = first_line.replace("SEPA", "").replace("IBAN", "").strip()
                description_parts.append(cleaned_remittance)
        
        # Combine and limit length for Discord placeholder
        if description_parts:
            suggested = " - ".join(description_parts)
        else:
            suggested = "Enter transaction description"
        
        # Limit to 90 chars to leave room for "..." if needed
        return suggested[:90]

    async def on_timeout(self):
        # Disable all items when view times out
        self.switch_type_button.disabled = True
        self.category_select.disabled = True
        self.confirm_button.disabled = True
        self.skip_button.disabled = True
        self.cache_button.disabled = True

    async def switch_type(self, interaction: discord.Interaction):
        self.transaction_type = "expense" if self.transaction_type == "income" else "income"
        self.switch_type_button.label = f"Switch to {'expense' if self.transaction_type == 'income' else 'income'}"
        
        # Re-apply categorization rules for the new transaction type
        suggested_category, suggested_description = apply_categorization_rules(self.transaction)
        
        # Only update suggestions if they match the new transaction type
        if self.transaction_type == "income" and suggested_category in CATEGORY_OPTIONS["income"]:
            self.selected_category = suggested_category
            self.suggested_description = suggested_description
        elif self.transaction_type == "expense" and suggested_category in CATEGORY_OPTIONS["expense"]:
            self.selected_category = suggested_category
            self.suggested_description = suggested_description
        else:
            # No smart suggestion for this type, reset
            self.selected_category = None
            self.suggested_description = None
        
        # Update category options with limit and smart defaults
        categories = CATEGORY_OPTIONS[self.transaction_type][:25]
        category_options = []
        for cat in categories:
            option = discord.SelectOption(label=cat)
            # Pre-select the suggested category if we have one
            if self.selected_category and cat == self.selected_category:
                option.default = True
            category_options.append(option)
        
        self.category_select.options = category_options
        self.category_select.placeholder = "Select a category" if not self.selected_category else f"✨ Suggested: {self.selected_category}"
        
        await interaction.response.edit_message(view=self)

    async def select_category(self, interaction: discord.Interaction):
        self.selected_category = self.category_select.values[0]
        await interaction.response.defer()

    async def confirm_transaction(self, interaction: discord.Interaction):
        if not self.selected_category:
            await interaction.response.send_message("⚠️ Please select a category first.", ephemeral=True)
            # Auto-delete after 3 seconds
            asyncio.create_task(self._delete_response_after_delay(interaction, 3))
            return

        # Use smart suggested description if available, otherwise fall back to extracted description
        smart_suggestion = self.suggested_description
        if not smart_suggestion:
            smart_suggestion = self._extract_suggested_description(self.transaction)
        
        # Open description modal with smart suggestion
        modal = DescriptionModal(self, smart_suggestion)
        await interaction.response.send_modal(modal)

    async def complete_transaction(self, interaction: discord.Interaction, description: str):
        """Complete the transaction after description is provided"""
        remaining, income, expenses = load_session(self.user_id)
        if not remaining:
            await interaction.response.send_message("❌ No transactions remaining.", ephemeral=True)
            asyncio.create_task(self._delete_response_after_delay(interaction, 3))
            return

        tx = remaining.pop(0)
        categorized_tx = {**tx, "category": self.selected_category}
        
        # Always add a description - either custom or auto-generated
        description_source = ""
        if description:
            categorized_tx["description"] = description
            description_source = " + custom description"
        else:
            # Use smart suggested description if available, otherwise fall back to extracted description
            if self.suggested_description:
                categorized_tx["description"] = self.suggested_description
                description_source = " + smart description"
            else:
                auto_desc = self._extract_suggested_description(self.transaction)
                categorized_tx["description"] = auto_desc
                description_source = " + auto-description"
        
        if self.transaction_type == "income":
            income.append(categorized_tx)
        else:
            expenses.append(categorized_tx)

        save_session(self.user_id, remaining, income, expenses)
        
        # Queue transaction for immediate upload to Google Sheets
        try:
            from finance_core.background_upload import queue_transaction_upload
            
            # Check if this is a cached transaction being processed
            if '_cache_id' in tx:
                # This is a processed cached transaction - remove from cache
                from finance_core.session_management import remove_cached_transaction
                cache_id = tx['_cache_id']
                remove_cached_transaction(self.user_id, cache_id)
                
                # Remove the cache marker before uploading
                categorized_tx = {k: v for k, v in categorized_tx.items() if k != '_cache_id'}
                queue_transaction_upload(categorized_tx, self.transaction_type, self.user_id)
                upload_indicator = " 🔄📤"
                logger.info(f"Processed cached transaction {cache_id}")
            else:
                # Regular transaction
                queue_transaction_upload(categorized_tx, self.transaction_type, self.user_id)
                upload_indicator = " 📤"
        except Exception as e:
            logger.error(f"❌ Failed to queue transaction for upload: {e}")
            upload_indicator = ""

        # Disable all buttons and selects to prevent further interactions
        self.switch_type_button.disabled = True
        self.category_select.disabled = True
        self.confirm_button.disabled = True
        self.skip_button.disabled = True
        self.cache_button.disabled = True

        # Send concise confirmation message
        progress_info = f"({len(income) + len(expenses)}/{len(remaining) + len(income) + len(expenses)} done)"
        
        # Add smart categorization indicator
        smart_indicator = ""
        if self.suggested_description and not description:
            smart_indicator = " 🤖"
        
        if remaining:
            await interaction.response.send_message(
                content=f"✅ Categorized as {self.selected_category}{description_source}{smart_indicator}{upload_indicator} {progress_info}", 
                ephemeral=True
            )
            # Update the original message to disable buttons immediately
            try:
                await interaction.edit_original_response(view=self)
            except Exception as e:
                logger.debug(f"Could not edit original message: {e}")
            await start_transaction_prompt(interaction, self.user_id)
        else:
            await interaction.response.send_message(
                content=f"🎉 All {len(income) + len(expenses)} transactions processed{upload_indicator}!", 
                ephemeral=True
            )
            # Update the original message to disable buttons immediately
            try:
                await interaction.edit_original_response(view=self)
            except Exception as e:
                logger.debug(f"Could not edit original message: {e}")
            clear_session(self.user_id)
            
            # Auto-delete completion message after 5 seconds
            asyncio.create_task(self._delete_response_after_delay(interaction, 5))

    async def skip_transaction(self, interaction: discord.Interaction):
        """Skip the current transaction and move to the next one"""
        remaining, income, expenses = load_session(self.user_id)
        if not remaining:
            await interaction.response.send_message("❌ No transactions remaining.", ephemeral=True)
            asyncio.create_task(self._delete_response_after_delay(interaction, 3))
            return

        # Remove the current transaction from remaining (skip it)
        tx = remaining.pop(0)
        save_session(self.user_id, remaining, income, expenses)

        # Disable all buttons and selects to prevent further interactions
        self.switch_type_button.disabled = True
        self.category_select.disabled = True
        self.confirm_button.disabled = True
        self.skip_button.disabled = True
        self.cache_button.disabled = True

        # Send confirmation message
        progress_info = f"({len(income) + len(expenses)}/{len(remaining) + len(income) + len(expenses)} done, 1 skipped)"
        
        if remaining:
            await interaction.response.send_message(
                content=f"⏭️ Transaction skipped {progress_info}", 
                ephemeral=True
            )
            # Update the original message to show completion
            try:
                await interaction.edit_original_response(view=self)
            except Exception as e:
                logger.warning(f"Failed to edit the original response: {e}")  # Message might already be updated
            await start_transaction_prompt(interaction, self.user_id)
        else:
            await interaction.response.send_message(
                content=f"🎉 All transactions processed! {len(income) + len(expenses)} categorized, 1 skipped.", 
                ephemeral=True
            )
            # Update the original message to show completion
            try:
                await interaction.edit_original_response(view=self)
            except:
                pass  # Message might already be updated
            clear_session(self.user_id)
            
            # Auto-delete completion message after 5 seconds
            asyncio.create_task(self._delete_response_after_delay(interaction, 5))

    async def cache_transaction(self, interaction: discord.Interaction):
        """Cache the current transaction for later processing"""
        remaining, income, expenses = load_session(self.user_id)
        if not remaining:
            await interaction.response.send_message("❌ No transactions remaining.", ephemeral=True)
            asyncio.create_task(self._delete_response_after_delay(interaction, 3))
            return

        tx = remaining.pop(0)
        
        # Generate auto-description without cache icon
        auto_description = self._extract_suggested_description(tx)
        
        try:
            from finance_core.session_management import cache_transaction
            from constants import ExpenseCategory, IncomeCategory
            
            # Cache the transaction in the session
            cache_id = cache_transaction(self.user_id, tx, self.transaction_type, auto_description)
            
            # Queue a dummy transaction for immediate upload to Google Sheets
            dummy_transaction = {**tx}
            dummy_transaction["category"] = ExpenseCategory.DUMMY_CACHED.value if self.transaction_type == "expense" else IncomeCategory.DUMMY_CACHED.value
            dummy_transaction["description"] = auto_description  # Clean description without cache icon
            dummy_transaction["cache_id"] = cache_id  # Add cache_id for tracking
            
            from finance_core.background_upload import queue_transaction_upload
            queue_transaction_upload(dummy_transaction, self.transaction_type, self.user_id)
            
            cache_indicator = f" 📦 (ID: {cache_id})"
        except Exception as e:
            logger.error(f"❌ Failed to cache transaction: {e}")
            # Put transaction back if caching failed
            remaining.insert(0, tx)
            save_session(self.user_id, remaining, income, expenses)
            await interaction.response.send_message("❌ Failed to cache transaction.", ephemeral=True)
            asyncio.create_task(self._delete_response_after_delay(interaction, 3))
            return
        
        # Save updated session (with transaction removed from remaining)
        save_session(self.user_id, remaining, income, expenses)
        
        # Disable all buttons and selects to prevent further interactions
        self.switch_type_button.disabled = True
        self.category_select.disabled = True
        self.confirm_button.disabled = True
        self.skip_button.disabled = True
        self.cache_button.disabled = True

        # Send confirmation message
        progress_info = f"({len(income) + len(expenses)}/{len(remaining) + len(income) + len(expenses)} done, 1 cached)"
        
        if remaining:
            await interaction.response.send_message(
                content=f"📦 Transaction cached for later{cache_indicator} {progress_info}", 
                ephemeral=True
            )
            # Update the original message to show completion
            try:
                await interaction.edit_original_response(view=self)
            except Exception:
                pass  # Message might already be updated
            await start_transaction_prompt(interaction, self.user_id)
        else:
            await interaction.response.send_message(
                content=f"🎉 All transactions processed! 📦 Last one cached{cache_indicator}", 
                ephemeral=True
            )
            # Update the original message to show completion
            try:
                await interaction.edit_original_response(view=self)
            except Exception:
                pass  # Message might already be updated
            clear_session(self.user_id)
            
            # Auto-delete completion message after 5 seconds
            asyncio.create_task(self._delete_response_after_delay(interaction, 5))

    async def _delete_response_after_delay(self, interaction: discord.Interaction, delay: int):
        await asyncio.sleep(delay)
        try:
            await interaction.delete_original_response()
        except:
            pass  # Message might already be deleted

async def start_transaction_prompt(interaction: discord.Interaction, user_id: int):
    remaining, income, expenses = load_session(user_id)
    if not remaining:
        await interaction.followup.send("⚠️ No transactions left to process.", ephemeral=True)
        return

    tx = remaining[0]
    embed = discord.Embed(title="🧾 Transaction to Categorize", color=discord.Color.blurple())
    
    # Add basic transaction info
    embed.add_field(name="📅 Date", value=tx.get("booking_date", "Unknown"), inline=True)
    
    # Format amount with proper sign
    amount = tx.get('transaction_amount', {}).get('amount', '0')
    currency = tx.get('transaction_amount', {}).get('currency', 'EUR')
    embed.add_field(name="💰 Amount", value=f"{amount} {currency}", inline=True)
    
    # Show transaction type with emoji
    tx_type = tx.get("credit_debit_indicator", "UNKNOWN")
    type_emoji = "💵" if tx_type == "CRDT" else "💸"
    type_text = "Income" if tx_type == "CRDT" else "Expense"
    embed.add_field(name="📊 Type", value=f"{type_emoji} {type_text}", inline=True)
    
    # Add remittance information (transaction description)
    remittance = tx.get("remittance_information") or ["No description"]
    # Limit to first 1000 characters to avoid embed limits
    remittance_text = "\n".join(remittance)[:1000]
    if len("\n".join(remittance)) > 1000:
        remittance_text += "..."
    embed.add_field(name="📝 Bank Description", value=remittance_text, inline=False)

    # Add counterparty info if available
    if debtor_name := tx.get("debtor", {}).get("name"):
        embed.add_field(name="👤 From", value=debtor_name, inline=True)
    if creditor_name := tx.get("creditor", {}).get("name"):
        embed.add_field(name="👤 To", value=creditor_name, inline=True)
    
    # Add progress indicator
    total_transactions = len(remaining) + len(income) + len(expenses)
    processed = len(income) + len(expenses)
    embed.add_field(name="📈 Progress", value=f"{processed}/{total_transactions} completed", inline=True)

    # Check if auto-categorization found a match
    suggested_category, suggested_description = apply_categorization_rules(tx)
    if suggested_category:
        embed.add_field(name="🤖 Smart Suggestion", value=f"**{suggested_category}**\n{suggested_description}", inline=False)

    # Add workflow info
    workflow_text = "1️⃣ Select category → 2️⃣ Click **Confirm & Add Description** → 3️⃣ Review/edit description\n\n⏭️ **Skip Transaction** if already processed manually\n📦 **Cache for Later** to save with dummy data for later processing"
    if suggested_category:
        workflow_text += "\n\n✨ *Category and description pre-filled based on transaction data*"
    
    embed.add_field(
        name="📋 Next Steps", 
        value=workflow_text, 
        inline=False
    )

    view = TransactionView(user_id, tx)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)

async def start_cached_transaction_prompt(interaction: discord.Interaction, user_id: int, cached_tx: Dict[str, Any]):
    """Start processing a single cached transaction"""
    
    # Extract the original transaction from the cached data
    tx = cached_tx["original_transaction"]
    
    # Add cache tracking to the transaction
    tx["_cache_id"] = cached_tx["cache_id"]
    
    embed = discord.Embed(title="🧾📦 Cached Transaction to Process", color=discord.Color.orange())
    
    # Add basic transaction info
    embed.add_field(name="📅 Date", value=tx.get("booking_date", "Unknown"), inline=True)
    
    # Format amount with proper sign
    amount = tx.get('transaction_amount', {}).get('amount', '0')
    currency = tx.get('transaction_amount', {}).get('currency', 'EUR')
    embed.add_field(name="💰 Amount", value=f"{amount} {currency}", inline=True)
    
    # Show transaction type with emoji
    tx_type = tx.get("credit_debit_indicator", "UNKNOWN")
    type_emoji = "💵" if tx_type == "CRDT" else "💸"
    type_text = "Income" if tx_type == "CRDT" else "Expense"
    embed.add_field(name="📊 Type", value=f"{type_emoji} {type_text}", inline=True)
    
    # Add remittance information (transaction description)
    remittance = tx.get("remittance_information") or ["No description"]
    # Limit to first 1000 characters to avoid embed limits
    remittance_text = "\n".join(remittance)[:1000]
    if len("\n".join(remittance)) > 1000:
        remittance_text += "..."
    embed.add_field(name="📝 Bank Description", value=remittance_text, inline=False)

    # Add counterparty info if available
    if debtor_name := tx.get("debtor", {}).get("name"):
        embed.add_field(name="👤 From", value=debtor_name, inline=True)
    if creditor_name := tx.get("creditor", {}).get("name"):
        embed.add_field(name="👤 To", value=creditor_name, inline=True)
    
    # Add cache info
    embed.add_field(name="📦 Cache Info", value=f"**ID:** {cached_tx['cache_id']}\n**Cached:** {cached_tx['timestamp'][:10]}", inline=True)

    # Check if auto-categorization found a match
    suggested_category, suggested_description = apply_categorization_rules(tx)
    if suggested_category:
        embed.add_field(name="🤖 Smart Suggestion", value=f"**{suggested_category}**\n{suggested_description}", inline=False)

    # Add workflow info for cached transactions
    workflow_text = "1️⃣ Select category → 2️⃣ Click **Confirm & Add Description** → 3️⃣ Review/edit description\n\n"
    workflow_text += "📦 This transaction was cached earlier and has a dummy entry in your sheet.\n"
    workflow_text += "✅ Processing it will **replace** the dummy entry with the proper categorization."
    if suggested_category:
        workflow_text += "\n\n✨ *Category and description pre-filled based on transaction data*"
    
    embed.add_field(
        name="📋 Processing Cached Transaction", 
        value=workflow_text, 
        inline=False
    )

    # Create a special view for cached transactions (doesn't need session management)
    view = CachedTransactionView(user_id, tx, cached_tx["cache_id"])
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class CachedTransactionView(View):
    """Special view for processing individual cached transactions"""
    
    def __init__(self, user_id: int, transaction: Dict[str, Any], cache_id: str):
        super().__init__(timeout=300)  # 5 minute timeout
        self.user_id = user_id
        self.transaction = transaction
        self.cache_id = cache_id
        self.transaction_type = "income" if transaction["credit_debit_indicator"] == "CRDT" else "expense"
        self.custom_description = None
        
        # Apply categorization rules to get smart defaults
        suggested_category, suggested_description = apply_categorization_rules(transaction)
        self.selected_category = suggested_category
        self.suggested_description = suggested_description

        self.switch_type_button = Button(label=f"Switch to {'expense' if self.transaction_type == 'income' else 'income'}", style=discord.ButtonStyle.secondary)
        self.switch_type_button.callback = self.switch_type
        self.add_item(self.switch_type_button)

        # Limit categories to 25 (Discord's maximum for select options)
        categories = CATEGORY_OPTIONS[self.transaction_type][:25]
        
        # Create category select with smart default
        category_options = []
        for cat in categories:
            option = discord.SelectOption(label=cat)
            # Pre-select the suggested category if we have one
            if suggested_category and cat == suggested_category:
                option.default = True
            category_options.append(option)
        
        self.category_select = Select(
            placeholder="Select a category" if not suggested_category else f"✨ Suggested: {suggested_category}",
            options=category_options
        )
        self.category_select.callback = self.select_category
        self.add_item(self.category_select)

        self.confirm_button = Button(label="Process & Replace Dummy", style=discord.ButtonStyle.success)
        self.confirm_button.callback = self.confirm_transaction
        self.add_item(self.confirm_button)

        self.cancel_button = Button(label="Cancel", style=discord.ButtonStyle.secondary)
        self.cancel_button.callback = self.cancel_processing
        self.add_item(self.cancel_button)

    def _extract_suggested_description(self, transaction: Dict[str, Any]) -> str:
        """Extract a suggested description from transaction data"""
        description_parts = []
        
        # Add counterparty information (most important)
        debtor_name = transaction.get("debtor", {}).get("name", "")
        creditor_name = transaction.get("creditor", {}).get("name", "")
        counterparty = debtor_name or creditor_name
        if counterparty:
            # Clean up common bank codes/prefixes to make it more readable
            cleaned_counterparty = counterparty.replace("NL", "").replace("INGB", "").strip()
            description_parts.append(cleaned_counterparty)
        
        # Add first line of remittance information (transaction details)
        remittance = transaction.get("remittance_information", [])
        if remittance and remittance[0]:
            first_line = remittance[0].strip()
            if first_line and first_line not in description_parts:
                # Clean up common patterns to make it more readable
                cleaned_remittance = first_line.replace("SEPA", "").replace("IBAN", "").strip()
                description_parts.append(cleaned_remittance)
        
        # Combine and limit length for Discord placeholder
        if description_parts:
            suggested = " - ".join(description_parts)
        else:
            suggested = "Enter transaction description"
        
        # Limit to 90 chars to leave room for "..." if needed
        return suggested[:90]

    async def on_timeout(self):
        # Disable all items when view times out
        self.switch_type_button.disabled = True
        self.category_select.disabled = True
        self.confirm_button.disabled = True
        self.cancel_button.disabled = True

    async def switch_type(self, interaction: discord.Interaction):
        self.transaction_type = "expense" if self.transaction_type == "income" else "income"
        self.switch_type_button.label = f"Switch to {'expense' if self.transaction_type == 'income' else 'income'}"
        
        # Re-apply categorization rules for the new transaction type
        suggested_category, suggested_description = apply_categorization_rules(self.transaction)
        
        # Only update suggestions if they match the new transaction type
        if self.transaction_type == "income" and suggested_category in CATEGORY_OPTIONS["income"]:
            self.selected_category = suggested_category
            self.suggested_description = suggested_description
        elif self.transaction_type == "expense" and suggested_category in CATEGORY_OPTIONS["expense"]:
            self.selected_category = suggested_category
            self.suggested_description = suggested_description
        else:
            # No smart suggestion for this type, reset
            self.selected_category = None
            self.suggested_description = None
        
        # Update category options with limit and smart defaults
        categories = CATEGORY_OPTIONS[self.transaction_type][:25]
        category_options = []
        for cat in categories:
            option = discord.SelectOption(label=cat)
            # Pre-select the suggested category if we have one
            if self.selected_category and cat == self.selected_category:
                option.default = True
            category_options.append(option)
        
        self.category_select.options = category_options
        self.category_select.placeholder = "Select a category" if not self.selected_category else f"✨ Suggested: {self.selected_category}"
        
        await interaction.response.edit_message(view=self)

    async def select_category(self, interaction: discord.Interaction):
        self.selected_category = self.category_select.values[0]
        await interaction.response.defer()

    async def confirm_transaction(self, interaction: discord.Interaction):
        if not self.selected_category:
            await interaction.response.send_message("⚠️ Please select a category first.", ephemeral=True)
            # Auto-delete after 3 seconds
            asyncio.create_task(self._delete_response_after_delay(interaction, 3))
            return

        # Use smart suggested description if available, otherwise fall back to extracted description
        smart_suggestion = self.suggested_description
        if not smart_suggestion:
            smart_suggestion = self._extract_suggested_description(self.transaction)
        
        # Open description modal with smart suggestion
        modal = CachedDescriptionModal(self, smart_suggestion)
        await interaction.response.send_modal(modal)

    async def complete_cached_transaction(self, interaction: discord.Interaction, description: str):
        """Complete the cached transaction processing"""
        try:
            # Create the properly categorized transaction
            categorized_tx = {**self.transaction, "category": self.selected_category}
            
            # Always add a description - either custom or auto-generated
            if description:
                categorized_tx["description"] = description
                description_source = " + custom description"
            else:
                # Use smart suggested description if available, otherwise fall back to extracted description
                if self.suggested_description:
                    categorized_tx["description"] = self.suggested_description
                    description_source = " + smart description"
                else:
                    auto_desc = self._extract_suggested_description(self.transaction)
                    categorized_tx["description"] = auto_desc
                    description_source = " + auto-description"
            
            # Keep the cache_id for replacement logic
            categorized_tx["cache_id"] = self.cache_id
            
            # Get the reserved row before removing from cache
            from finance_core.session_management import get_cached_transactions
            cached_transactions = get_cached_transactions(self.user_id)
            reserved_row = None
            
            for cached_tx in cached_transactions:
                if cached_tx["cache_id"] == self.cache_id:
                    reserved_row = cached_tx.get("sheet_row")
                    break
            
            if not reserved_row:
                await interaction.response.send_message("❌ Error: Could not find reserved row for cached transaction. Please try again.", ephemeral=True)
                return
            
            # Store the reserved row in the transaction for the background worker
            categorized_tx["_reserved_row"] = reserved_row
            
            # Queue transaction for replacement in Google Sheets (will replace dummy entry)
            from finance_core.background_upload import queue_cached_replacement
            queue_cached_replacement(self.cache_id, categorized_tx, self.transaction_type, self.user_id)
            
            # IMPORTANT: Remove the cached transaction from session IMMEDIATELY to prevent duplicates
            # The background upload will also try to remove it, but we need to remove it here
            # to ensure it's not visible in the UI anymore
            from finance_core.session_management import remove_cached_transaction
            remove_cached_transaction(self.user_id, self.cache_id)
            
            # Disable all buttons and selects to prevent further interactions
            self.switch_type_button.disabled = True
            self.category_select.disabled = True
            self.confirm_button.disabled = True
            self.cancel_button.disabled = True

            # Check if there are more cached transactions (after removing current one)
            from finance_core.session_management import get_cached_transactions
            remaining_cached = get_cached_transactions(self.user_id)
            
            # Add smart categorization indicator
            smart_indicator = ""
            if self.suggested_description and not description:
                smart_indicator = " 🤖"
            
            if remaining_cached:
                await interaction.response.send_message(
                    content=f"✅ Cached transaction processed as {self.selected_category}{description_source}{smart_indicator} 📤\n🔄 {len(remaining_cached)} more cached transactions remaining.", 
                    ephemeral=True
                )
                
                # Update the original message to show completion
                try:
                    await interaction.edit_original_response(view=self)
                except Exception as e:
                    logger.warning(f"Failed to edit the original response: {e}")
                
                # Continue with next cached transaction
                next_cached = remaining_cached[0]
                await start_cached_transaction_prompt(interaction, self.user_id, next_cached)
            else:
                await interaction.response.send_message(
                    content=f"🎉 All cached transactions processed! Last one: {self.selected_category}{description_source}{smart_indicator} 📤", 
                    ephemeral=True
                )
                
                # Update the original message to show completion
                try:
                    await interaction.edit_original_response(view=self)
                except Exception:
                    pass  # Message might already be updated
                
                # Auto-delete completion message after 5 seconds
                asyncio.create_task(self._delete_response_after_delay(interaction, 5))
            
        except Exception as e:
            logger.error(f"❌ Failed to process cached transaction: {e}")
            await interaction.response.send_message(f"❌ Error processing cached transaction: {str(e)}", ephemeral=True)

    async def cancel_processing(self, interaction: discord.Interaction):
        """Cancel processing of cached transactions"""
        # Disable all buttons
        self.switch_type_button.disabled = True
        self.category_select.disabled = True
        self.confirm_button.disabled = True
        self.cancel_button.disabled = True
        
        await interaction.response.send_message("❌ Cached transaction processing cancelled.", ephemeral=True)
        
        # Update the original message to show cancellation
        try:
            await interaction.edit_original_response(view=self)
        except Exception:
            pass  # Message might already be updated
        
        # Auto-delete after 3 seconds
        asyncio.create_task(self._delete_response_after_delay(interaction, 3))

    async def _delete_response_after_delay(self, interaction: discord.Interaction, delay: int):
        await asyncio.sleep(delay)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass  # Message might already be deleted


class CachedDescriptionModal(Modal):
    def __init__(self, cached_view, suggested_description: str):
        super().__init__(title="Process Cached Transaction")
        self.cached_view = cached_view
        
        # Truncate placeholder to Discord's 100 character limit
        placeholder_text = suggested_description[:95] + "..." if len(suggested_description) > 95 else suggested_description
        
        self.description_input = TextInput(
            label="Transaction Description",
            placeholder=placeholder_text,
            max_length=500,
            required=False,  # Allow empty to use auto-description
            style=discord.TextStyle.paragraph,
            default=suggested_description[:500]  # Pre-fill with suggestion
        )
        self.add_item(self.description_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        # Store the custom description in the cached view
        custom_desc = self.description_input.value.strip()
        self.cached_view.custom_description = custom_desc
        
        # Complete the cached transaction with the description
        await self.cached_view.complete_cached_transaction(interaction, custom_desc)