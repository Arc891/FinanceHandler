# Modern bot.py - Updated to work with slash commands and bot_commands.py

import discord
from discord.ext import commands, tasks
import os
import asyncio
from datetime import datetime
from config_settings import DISCORD_TOKEN, DAILY_REMINDER_TIME, REMINDER_CHANNEL_ID, MENTION_USER_IDS

# Set up Discord intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

# Create bot instance with slash command support
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"🤖 {bot.user} has connected to Discord!")
    print(f"📊 Bot is in {len(bot.guilds)} guilds")
    
    # Load the finance commands cog
    try:
        await bot.load_extension("bot_commands")
        print("✅ Finance commands loaded successfully")
    except Exception as e:
        print(f"❌ Failed to load finance commands: {e}")
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")
    
    # Start the daily reminder task
    if not daily_reminder.is_running():
        daily_reminder.start()
        print("⏰ Daily reminder task started")

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors gracefully"""
    if isinstance(error, commands.CommandNotFound):
        return  # Ignore unknown commands
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: {error.param}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Invalid argument provided")
    else:
        print(f"❌ Unexpected error: {error}")
        await ctx.send("❌ An unexpected error occurred")

@tasks.loop(minutes=1)
async def daily_reminder():
    """Send daily finance reminders at the specified time"""
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    
    if current_time == DAILY_REMINDER_TIME:
        try:
            channel = bot.get_channel(REMINDER_CHANNEL_ID)
            if channel and isinstance(channel, discord.TextChannel):
                mentions = " ".join([f"<@{user_id}>" for user_id in MENTION_USER_IDS])
                message = f"⏰ **Daily Finance Reminder!** {mentions}\n\n📋 Please upload your CSV file using `/upload` to process your transactions."
                await channel.send(message)
                print(f"✅ Daily reminder sent to #{channel.name}")
        except Exception as e:
            print(f"❌ Failed to send daily reminder: {e}")

@daily_reminder.before_loop
async def before_daily_reminder():
    """Wait for bot to be ready before starting the reminder loop"""
    await bot.wait_until_ready()
    print("⏰ Daily reminder task initialized")

@daily_reminder.error
async def daily_reminder_error(task, error):
    """Handle errors in the daily reminder task"""
    print(f"❌ Daily reminder task error: {error}")
    # Wait 5 minutes before restarting
    await asyncio.sleep(300)
    daily_reminder.restart()

# Legacy command support (keeping the old prefix command for backward compatibility)
@bot.command(name="ping")
async def ping(ctx):
    """Simple ping command to test bot responsiveness"""
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Latency: {latency}ms")

if __name__ == "__main__":
    # Ensure we have a token
    if not DISCORD_TOKEN or DISCORD_TOKEN == "your_discord_token_here":
        print("❌ Error: DISCORD_TOKEN not set in environment variables or config_settings.py")
        print("💡 Please set your Discord bot token in the config_settings.py file or as an environment variable")
        exit(1)
    
    # Run the bot
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("❌ Error: Invalid Discord token")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")

