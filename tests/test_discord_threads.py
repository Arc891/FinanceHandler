"""Exercise progress-thread lookup and failures without connecting to Discord."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from finance_core.discord_threads import get_or_create_user_thread


def fake_thread(name):
    return SimpleNamespace(name=name, edit=AsyncMock(), add_user=AsyncMock())


class FakeChannel:
    def __init__(self, active=(), archived=()):
        self.threads = list(active)
        self.archived = list(archived)
        self.archive_limits = []
        self.create_thread = AsyncMock(side_effect=self._create_thread)

    async def archived_threads(self, *, limit):
        self.archive_limits.append(limit)
        for thread in self.archived:
            yield thread

    async def _create_thread(self, *, name, **kwargs):
        thread = fake_thread(name)
        self.threads.append(thread)
        return thread


@pytest.fixture
def bot():
    user = SimpleNamespace(id=123, display_name="Synthetic User")
    return SimpleNamespace(get_user=Mock(return_value=user), fetch_user=AsyncMock())


async def test_existing_active_thread_is_reused(bot):
    existing = fake_thread("Approvals-Synthetic User")
    channel = FakeChannel(active=[fake_thread("unrelated"), existing])

    assert await get_or_create_user_thread(channel, 123, bot) is existing

    bot.get_user.assert_called_once_with(123)
    bot.fetch_user.assert_not_awaited()
    channel.create_thread.assert_not_awaited()
    assert channel.archive_limits == []
    existing.edit.assert_not_awaited()
    existing.add_user.assert_not_awaited()


async def test_archived_thread_is_unarchived_and_reused(bot):
    existing = fake_thread("Approvals-Synthetic User")
    channel = FakeChannel(archived=[fake_thread("unrelated"), existing])

    assert await get_or_create_user_thread(channel, 123, bot) is existing

    existing.edit.assert_awaited_once_with(archived=False)
    existing.add_user.assert_not_awaited()
    channel.create_thread.assert_not_awaited()
    assert channel.archive_limits == [100]


async def test_missing_thread_is_created_once_and_user_added(bot):
    channel = FakeChannel(active=[fake_thread("unrelated")])

    created = await get_or_create_user_thread(channel, 123, bot)
    assert created is not None
    assert await get_or_create_user_thread(channel, 123, bot) is created

    channel.create_thread.assert_awaited_once_with(
        name="Approvals-Synthetic User",
        type=discord.ChannelType.private_thread,
        reason="Approval thread for Synthetic User",
    )
    created.add_user.assert_awaited_once_with(bot.get_user.return_value)


async def test_uncached_user_is_fetched_and_added(bot):
    user = bot.get_user.return_value
    bot.get_user.return_value = None
    bot.fetch_user.return_value = user
    channel = FakeChannel()

    created = await get_or_create_user_thread(channel, 123, bot)

    bot.fetch_user.assert_awaited_once_with(123)
    assert created.name == "Approvals-Synthetic User"
    created.add_user.assert_awaited_once_with(user)


async def test_failed_user_fetch_falls_back_to_id_without_adding_user(bot):
    bot.get_user.return_value = None
    bot.fetch_user.side_effect = RuntimeError("synthetic fetch failure")
    channel = FakeChannel()

    created = await get_or_create_user_thread(channel, 123, bot)

    assert created.name == "Approvals-123"
    bot.fetch_user.assert_awaited_once_with(123)
    created.add_user.assert_not_awaited()


@pytest.mark.parametrize("error, message", [
    (discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"),
                       "synthetic denial"), "Bot lacks permission"),
    (RuntimeError("synthetic creation failure"), "Failed to get/create thread"),
])
async def test_creation_error_returns_none_and_logs(bot, caplog, error, message):
    channel = FakeChannel()
    channel.create_thread.side_effect = error

    assert await get_or_create_user_thread(channel, 123, bot) is None

    channel.create_thread.assert_awaited_once()
    assert message in caplog.text
