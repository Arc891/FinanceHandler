"""
The user's progress thread, Approvals-<name> (plan 4.1).

Moved unchanged from ui/discord_notifier.py, which step 5 of Phase 3 deletes.
The thread keeps its name; it is now a progress log, not an approval surface.
"""

import logging
from typing import Optional

import discord

logger = logging.getLogger(__name__)


async def get_or_create_user_thread(
    channel: discord.TextChannel,
    user_id: int,
    bot: discord.Client
) -> Optional[discord.Thread]:
    """
    Get existing private thread for user or create a new one.
    Thread named: Approvals-{username}
    """
    # Get user for naming
    user = bot.get_user(user_id)
    if not user:
        try:
            user = await bot.fetch_user(user_id)
        except BaseException:
            user = None

    username = user.display_name if user else str(user_id)
    thread_name = f"Approvals-{username}"

    try:
        # Check active threads
        for thread in channel.threads:
            if thread.name == thread_name:
                logger.info(f"Found existing thread for user {user_id}")
                return thread

        # Check archived threads
        async for thread in channel.archived_threads(limit=100):
            if thread.name == thread_name:
                logger.info(f"Unarchiving thread for user {user_id}")
                await thread.edit(archived=False)
                return thread

        # Create new private thread
        thread = await channel.create_thread(
            name=thread_name,
            type=discord.ChannelType.private_thread,
            reason=f"Approval thread for {username}"
        )

        # Add user to thread
        if user:
            await thread.add_user(user)
            logger.info(
                f"Created private thread '{thread_name}' and added user")
        else:
            logger.warning(f"Could not fetch user {user_id} to add to thread")

        return thread

    except discord.Forbidden:
        logger.error("Bot lacks permission to create private threads")
        return None
    except Exception as e:
        logger.error(f"Failed to get/create thread for user {user_id}: {e}")
        return None
