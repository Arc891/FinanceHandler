# finance_core/export.py

import os
from typing import List, Dict, Any, Optional
import discord
from discord.ext import commands
from discord.ui import View, Select
from finance_core.session_management import (
    save_session, load_session, clear_session, session_exists
)
from finance_core.csv_helper import load_transactions_from_csv
from finance_core.resume_button_ui import SwitchTypeView

EXPENSE_CATEGORIES = ["Groceries", "Rent", "Utilities", "Entertainment"]
INCOME_CATEGORIES = ["Salary", "Interest", "Investment Return"]
DEFAULT_CATEGORY = "Uncategorized"

class CategorySelect(Select):
    def __init__(self, transaction: Dict[str, Any], user_id: int, is_income: bool):
        self.transaction = transaction
        self.user_id = user_id
        category_list = INCOME_CATEGORIES if is_income else EXPENSE_CATEGORIES
        options = [
            discord.SelectOption(label=cat, description=f"Categorize as {cat}")
            for cat in category_list
        ]
        super().__init__(placeholder="Select a category", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("You can't interact with this menu.", ephemeral=True)
            return
        if self.view:
            self.view.selected_category = self.values[0]
            self.view.stop()

class CategoryView(View):
    def __init__(self, transaction: Dict[str, Any], user_id: int, is_income: bool):
        super().__init__(timeout=None)
        self.selected_category: Optional[str] = None
        self.add_item(CategorySelect(transaction, user_id, is_income))

async def process_csv_file(file_path: Optional[str], ctx: commands.Context):
    user_id = ctx.author.id
    remaining: List[Dict[str, Any]]
    income: List[Dict[str, Any]]
    expenses: List[Dict[str, Any]]

    if session_exists(user_id):
        if not file_path:
            remaining, income, expenses = load_session(user_id)
        else:
            await ctx.send("⚠️ You already have an active session. Please complete it using `/resume` before uploading a new file.")
            return
    else:
        if not file_path:
            await ctx.send("❌ Something went wrong, no csv file provided.")
            return
        remaining = load_transactions_from_csv(file_path)
        income, expenses = [], []

    await ctx.send(f"📥 Starting categorization. {len(remaining)} transactions to process.")

    for tx in remaining[:]:
        is_income = tx["credit_debit_indicator"] == "CRDT"
        amount_str = tx["transaction_amount"]["amount"]
        currency = tx["transaction_amount"]["currency"]
        amount = float(amount_str)

        embed = discord.Embed(title="Categorize Transaction", color=0x00ffcc)
        embed.add_field(name="Amount", value=f"{amount} {currency}", inline=True)
        embed.add_field(name="Date", value=tx.get("booking_date", "N/A"), inline=True)
        embed.add_field(name="Remittance Info", value=", ".join(tx.get("remittance_information", [])), inline=False)
        embed.set_footer(text="Detected as INCOME" if is_income else "Detected as EXPENSE")

        await ctx.send(embed=embed)
        await ctx.send("Please provide a short description for this transaction:")

        def check(m):
            return m.author.id == user_id and m.channel == ctx.channel

        try:
            desc_msg = await ctx.bot.wait_for("message", check=check)
            tx["description"] = desc_msg.content

            view = SwitchTypeView(user_id)
            await ctx.send("Do you want to switch the transaction type?", view=view)
            await view.wait()

            if view.switch is True:
                is_income = not is_income

            view = CategoryView(tx, user_id, is_income)
            await ctx.send("Select a category:", view=view)
            await view.wait()

            if view.selected_category is None:
                tx["category"] = DEFAULT_CATEGORY
                await ctx.send(f"⚠️ No category selected. Defaulted to '{DEFAULT_CATEGORY}'.")
            else:
                tx["category"] = view.selected_category

            if is_income:
                income.append(tx)
            else:
                expenses.append(tx)

            remaining.remove(tx)
            save_session(user_id, remaining, income, expenses)

        except Exception as e:
            await ctx.send(f"⏸️ Saving progress and pausing due to error: {e}")
            save_session(user_id, remaining, income, expenses)
            return

    await ctx.send(f"✅ Processed {len(income)} income and {len(expenses)} expense transactions. Uploading to Google Sheets...")
    # upload_to_gsheet(income, expenses)
    clear_session(user_id)
    if file_path:
        os.remove(file_path)
    await ctx.send("✅ Done!")


@commands.command()
async def resume(ctx: commands.Context):
    user_id = ctx.author.id
    if not session_exists(user_id):
        await ctx.send("There is no session to resume.")
        return

    await ctx.send("🔄 Resuming your saved transaction session...")
    await process_csv_file(None, ctx)
