# finance_core/ui/transaction_prompt.py

import discord
from discord.ui import View, Button, Select
from typing import List, Dict, Any
from finance_core.session_management import load_session, save_session, clear_session

# Import the proper categories from constants
try:
    from constants import ExpenseCategory, IncomeCategory
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

class TransactionView(View):
    def __init__(self, user_id: int, transaction: Dict[str, Any]):
        super().__init__(timeout=300)  # 5 minute timeout instead of None
        self.user_id = user_id
        self.transaction = transaction
        self.transaction_type = "income" if transaction["credit_debit_indicator"] == "CRDT" else "expense"
        self.selected_category = None

        self.switch_type_button = Button(label=f"Switch to {'expense' if self.transaction_type == 'income' else 'income'}", style=discord.ButtonStyle.secondary)
        self.switch_type_button.callback = self.switch_type
        self.add_item(self.switch_type_button)

        # Limit categories to 25 (Discord's maximum for select options)
        categories = CATEGORY_OPTIONS[self.transaction_type][:25]
        self.category_select = Select(
            placeholder="Select a category",
            options=[discord.SelectOption(label=cat) for cat in categories]
        )
        self.category_select.callback = self.select_category
        self.add_item(self.category_select)

        self.confirm_button = Button(label="Confirm", style=discord.ButtonStyle.success)
        self.confirm_button.callback = self.confirm_transaction
        self.add_item(self.confirm_button)

    async def on_timeout(self):
        # Disable all items when view times out
        self.switch_type_button.disabled = True
        self.category_select.disabled = True
        self.confirm_button.disabled = True

    async def switch_type(self, interaction: discord.Interaction):
        self.transaction_type = "expense" if self.transaction_type == "income" else "income"
        self.switch_type_button.label = f"Switch to {'expense' if self.transaction_type == 'income' else 'income'}"
        
        # Update category options with limit
        categories = CATEGORY_OPTIONS[self.transaction_type][:25]
        self.category_select.options = [discord.SelectOption(label=cat) for cat in categories]
        self.selected_category = None
        await interaction.response.edit_message(view=self)

    async def select_category(self, interaction: discord.Interaction):
        self.selected_category = self.category_select.values[0]
        await interaction.response.defer()

    async def confirm_transaction(self, interaction: discord.Interaction):
        if not self.selected_category:
            await interaction.response.send_message("⚠️ Please select a category before confirming.", ephemeral=True)
            return

        remaining, income, expenses = load_session(self.user_id)
        if not remaining:
            await interaction.response.send_message("❌ No transactions remaining.", ephemeral=True)
            return

        tx = remaining.pop(0)
        categorized_tx = {**tx, "category": self.selected_category}
        if self.transaction_type == "income":
            income.append(categorized_tx)
        else:
            expenses.append(categorized_tx)

        save_session(self.user_id, remaining, income, expenses)

        # Disable all buttons and selects to prevent further interactions
        self.switch_type_button.disabled = True
        self.category_select.disabled = True
        self.confirm_button.disabled = True

        # Send confirmation message and update the current message
        if remaining:
            await interaction.response.edit_message(
                content="✅ Transaction categorized! Loading next transaction...", 
                embed=None, 
                view=self
            )
            await start_transaction_prompt(interaction, self.user_id)
        else:
            await interaction.response.edit_message(
                content="🎉 All transactions processed and saved!", 
                embed=None, 
                view=self
            )
            clear_session(self.user_id)

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
    embed.add_field(name="📝 Description", value=remittance_text, inline=False)

    # Add counterparty info if available
    if debtor_name := tx.get("debtor", {}).get("name"):
        embed.add_field(name="👤 From", value=debtor_name, inline=True)
    if creditor_name := tx.get("creditor", {}).get("name"):
        embed.add_field(name="👤 To", value=creditor_name, inline=True)
    
    # Add progress indicator
    total_transactions = len(remaining) + len(income) + len(expenses)
    processed = len(income) + len(expenses)
    embed.add_field(name="📈 Progress", value=f"{processed}/{total_transactions} completed", inline=True)

    view = TransactionView(user_id, tx)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)