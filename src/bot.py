# Modern bot.py - Updated to work with slash commands and bot_commands.py

import discord
from discord.ext import commands, tasks
import os
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from config_settings import DISCORD_TOKEN, DAILY_REMINDER_TIME, REMINDER_CHANNEL_ID, MENTION_USER_IDS

# Set up logging with unified format and colors
class ColoredFormatter(logging.Formatter):
    """Custom formatter to add colors to log levels"""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green  
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        # Add color to the level name
        level_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{level_color}{record.levelname}{self.RESET}"
        return super().format(record)

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

# Apply colored formatter to the root handler
root_logger = logging.getLogger()
for handler in root_logger.handlers:
    handler.setFormatter(ColoredFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# Reduce Discord.py logging noise - only show warnings and errors
logging.getLogger('discord').setLevel(logging.WARNING)
logging.getLogger('discord.client').setLevel(logging.WARNING)
logging.getLogger('discord.gateway').setLevel(logging.WARNING)
logging.getLogger('discord.http').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Get system timezone
import subprocess

# Initialize with default
SYSTEM_TIMEZONE: str = 'UTC'

try:
    # Priority 1: TZ environment variable
    tz_env = os.environ.get('TZ')
    if tz_env:
        SYSTEM_TIMEZONE = tz_env
    else:
        # Priority 2: Get timezone from system
        result = subprocess.run(['timedatectl', 'show', '--property=Timezone', '--value'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            SYSTEM_TIMEZONE = result.stdout.strip()
except Exception as e:
    # Final fallback - keep the default UTC
    logger.warning(f"⚠️ Timezone detection failed, using UTC: {e}")

logger.info("🚀 Starting Discord Finance Bot...")
logger.info(f"⏰ Daily reminder: {DAILY_REMINDER_TIME} ({SYSTEM_TIMEZONE})")
logger.info(f"📢 Channel: {REMINDER_CHANNEL_ID}, Users: {len(MENTION_USER_IDS)}")

# Set up Discord intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

# Create bot instance with slash command support
bot = commands.Bot(command_prefix="!", intents=intents)

logger.info("✅ Bot instance created")

@bot.event
async def on_ready():
    logger.info(f"🤖 {bot.user} connected to Discord ({len(bot.guilds)} guilds)")
    
    # Load the finance commands cog
    try:
        await bot.load_extension("bot_commands")
        logger.info("✅ Finance commands loaded")
    except Exception as e:
        logger.error(f"❌ Failed to load finance commands: {e}")
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        logger.info(f"✅ Synced {len(synced)} slash command(s)")
    except Exception as e:
        logger.error(f"❌ Failed to sync commands: {e}")
    
    # Start the daily reminder task
    if not daily_reminder.is_running():
        daily_reminder.start()
        logger.info("⏰ Daily reminder task started")
    else:
        logger.warning("⚠️ Daily reminder task was already running")

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
        logger.error(f"❌ Unexpected error: {error}")
        await ctx.send("❌ An unexpected error occurred")

@tasks.loop(minutes=1)
async def daily_reminder():
    """Send daily finance reminders at the specified time"""
    try:
        # Get current time in system timezone
        now = datetime.now(ZoneInfo(SYSTEM_TIMEZONE))
        current_time = now.strftime("%H:%M")
        
        if current_time == DAILY_REMINDER_TIME:
            try:
                channel = bot.get_channel(REMINDER_CHANNEL_ID)
                if channel and isinstance(channel, discord.TextChannel):
                    mentions = " ".join([f"<@{user_id}>" for user_id in MENTION_USER_IDS])
                    message = f"⏰ **Daily Finance Reminder!** {mentions}\n\n📋 Please upload your CSV file using `/upload` to process your transactions."
                    await channel.send(message)
                    logger.info(f"✅ Daily reminder sent to #{channel.name} at {current_time} {SYSTEM_TIMEZONE}")
                else:
                    logger.error(f"❌ Channel not found or not a text channel. Channel ID: {REMINDER_CHANNEL_ID}")
            except Exception as e:
                logger.error(f"❌ Failed to send daily reminder: {e}")
    except Exception as e:
        logger.error(f"❌ Error in daily reminder task: {e}")

@daily_reminder.before_loop
async def before_daily_reminder():
    """Wait for bot to be ready before starting the reminder loop"""
    await bot.wait_until_ready()
    logger.info("⏰ Daily reminder task initialized")

@daily_reminder.error
async def daily_reminder_error(task, error):
    """Handle errors in the daily reminder task"""
    logger.error(f"❌ Daily reminder task error: {error}")
    # Wait 5 minutes before restarting
    await asyncio.sleep(300)
    daily_reminder.restart()
    logger.info("🔄 Daily reminder task restarted")

# Legacy command support (keeping the old prefix command for backward compatibility)
@bot.command(name="ping")
async def ping(ctx):
    """Simple ping command to test bot responsiveness"""
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Latency: {latency}ms")

if __name__ == "__main__":
    # Ensure we have a token
    if not DISCORD_TOKEN or DISCORD_TOKEN == "your_discord_token_here":
        logger.error("❌ Error: DISCORD_TOKEN not set in environment variables or config_settings.py")
        logger.info("💡 Please set your Discord bot token in the config_settings.py file or as an environment variable")
        exit(1)
    
    # Run the bot
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.error("❌ Error: Invalid Discord token")
    except Exception as e:
        logger.error(f"❌ Error starting bot: {e}")

