import discord
from discord.ui import Button, View

class SwitchTypeView(View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.switch = None
        self.add_item(SwitchTypeButton(label="Yes", style=discord.ButtonStyle.primary, value=True))
        self.add_item(SwitchTypeButton(label="No", style=discord.ButtonStyle.secondary, value=False))

class SwitchTypeButton(Button):
    def __init__(self, label, style, value):
        super().__init__(label=label, style=style)
        self.value = value

    async def callback(self, interaction: discord.Interaction):
        if self.view and isinstance(self.view, SwitchTypeView):
            if interaction.user.id != self.view.user_id:
                await interaction.response.send_message("You cannot interact with this button.", ephemeral=True)
                return
            self.view.switch = self.value
            self.view.stop()
            await interaction.response.defer()
