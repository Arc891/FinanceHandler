"""
UI components for managing cached transactions.
"""

import discord
from discord.ui import View, Button
from typing import List
import asyncio
import logging

logger = logging.getLogger(__name__)

class CachedTransactionsView(View):
    """View for managing cached transactions"""
    
    def __init__(self, user_id: int, cached_transactions: List):
        super().__init__(timeout=300)  # 5 minute timeout
        self.user_id = user_id
        self.cached_transactions = cached_transactions
        
        self.process_button = Button(
            label=f"🔧 Process Cached ({len(cached_transactions)})", 
            style=discord.ButtonStyle.primary
        )
        self.process_button.callback = self.process_cached
        self.add_item(self.process_button)
        
        self.clear_button = Button(
            label="🗑️ Clear All", 
            style=discord.ButtonStyle.danger
        )
        self.clear_button.callback = self.clear_all
        self.add_item(self.clear_button)
    
    async def on_timeout(self):
        # Disable all buttons when view times out
        self.process_button.disabled = True
        self.clear_button.disabled = True
    
    async def process_cached(self, interaction: discord.Interaction):
        """Start processing cached transactions one by one"""
        from finance_core.session_management import session_exists
        
        if not self.cached_transactions:
            await interaction.response.send_message("📭 No cached transactions to process.", ephemeral=True)
            return
        
        # Disable buttons to prevent duplicate processing
        self.process_button.disabled = True
        self.clear_button.disabled = True
        
        # Process cached transactions independently of CSV sessions
        await interaction.response.send_message("🔧 Starting cached transaction processing...", ephemeral=True)
        
        # Update the original message to show processing started
        try:
            await interaction.edit_original_response(view=self)
        except:
            pass  # Message might already be updated
        
        # Start the actual processing workflow
        await self._start_cached_processing(interaction)

    async def _start_cached_processing(self, interaction: discord.Interaction):
        """Start the cached transaction processing workflow"""
        if not self.cached_transactions:
            await interaction.followup.send("✅ All cached transactions processed!", ephemeral=True)
            return
        
        # Get the first cached transaction
        cached_tx = self.cached_transactions[0]
        
        # Import here to avoid circular imports
        from finance_core.ui.transaction_prompt import start_cached_transaction_prompt
        
        await start_cached_transaction_prompt(interaction, self.user_id, cached_tx)
    
    async def clear_all(self, interaction: discord.Interaction):
        """Clear all cached transactions"""
        try:
            from finance_core.session_management import clear_cached_transactions
            
            count = len(self.cached_transactions)
            clear_cached_transactions(self.user_id)
            
            # Disable buttons
            self.process_button.disabled = True
            self.clear_button.disabled = True
            
            await interaction.response.send_message(
                f"🗑️ Cleared {count} cached transaction(s). Note: Dummy entries remain in your Google Sheet - you may want to clean them up manually.", 
                ephemeral=True
            )
            
            # Auto-delete after 8 seconds
            response = await interaction.original_response()
            asyncio.create_task(self._delete_after_delay(response, 8))
            
        except Exception as e:
            logger.error(f"❌ Error clearing cached transactions: {e}")
            await interaction.response.send_message(f"❌ Error clearing cached transactions: {str(e)}", ephemeral=True)
    
    async def _delete_after_delay(self, message, delay: int):
        """Delete a message after a delay"""
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except:
            pass  # Message might already be deleted
