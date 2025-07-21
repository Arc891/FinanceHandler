# finance_core/ui/transaction_prompt.py

import discord
from discord.ui import View, Button, Select, Modal, TextInput
from typing import List, Dict, Any, Tuple, Optional
import re
from finance_core.session_management import load_session, save_session, clear_session

# Import the proper categories from constants
try:
    from constants import ExpenseCategory, IncomeCategory, CATEGORIZATION_RULES_EXPENSE, CATEGORIZATION_RULES_INCOME
    CATEGORY_OPTIONS = {
        "income": [cat.value for cat in IncomeCategory],
        "expense": [cat.value for cat in ExpenseCategory]
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
        import asyncio
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
            import asyncio
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
            import asyncio
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

        # Disable all buttons and selects to prevent further interactions
        self.switch_type_button.disabled = True
        self.category_select.disabled = True
        self.confirm_button.disabled = True

        # Send concise confirmation message
        progress_info = f"({len(income) + len(expenses)}/{len(remaining) + len(income) + len(expenses)} done)"
        
        # Add smart categorization indicator
        smart_indicator = ""
        if self.suggested_description and not description:
            smart_indicator = " 🤖"
        
        if remaining:
            await interaction.response.send_message(
                content=f"✅ Categorized as {self.selected_category}{description_source}{smart_indicator} {progress_info}", 
                ephemeral=True
            )
            await start_transaction_prompt(interaction, self.user_id)
        else:
            await interaction.response.send_message(
                content=f"🎉 All {len(income) + len(expenses)} transactions processed!", 
                ephemeral=True
            )
            clear_session(self.user_id)
            
            # Auto-delete completion message after 5 seconds
            import asyncio
            asyncio.create_task(self._delete_response_after_delay(interaction, 5))

    async def _delete_response_after_delay(self, interaction: discord.Interaction, delay: int):
        import asyncio
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
    workflow_text = "1️⃣ Select category → 2️⃣ Click **Confirm & Add Description** → 3️⃣ Review/edit description"
    if suggested_category:
        workflow_text += "\n\n✨ *Category and description pre-filled based on transaction data*"
    
    embed.add_field(
        name="📋 Next Steps", 
        value=workflow_text, 
        inline=False
    )

    view = TransactionView(user_id, tx)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)