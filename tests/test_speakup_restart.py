"""SpeakUp: offers still work after a reload (rebuilt from the message)."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from harness import FakeGuild, FakeMessage, TestBot, card_text, dcommands, load

sp_mod = load("speakup", "speakup")
sp_mod.EMBED_WAIT = 0
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


class ClaudeChat(dcommands.Cog):
    def __init__(self):
        self.urls = []

    async def summarize_link(self, url, member):
        self.urls.append(url)
        return "- point one"


async def main():
    guild = FakeGuild()
    alex = guild.add(2, "Alex")
    chris = guild.add(3, "Chris")
    channel = guild.channel
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    claude = ClaudeChat()
    await bot.add_cog(claude)
    sp = sp_mod.SpeakUp(bot)
    await bot.add_cog(sp)
    sp.reminder_loop.cancel()

    async def fetch_message(mid):
        return channel.messages[mid]
    channel.fetch_message = fetch_message

    link_msg = FakeMessage(channel, "good read https://example.com/story", author=alex)
    link_msg.reactions = [SimpleNamespace(emoji="📄", me=True)]
    channel.messages[link_msg.id] = link_msg
    # nothing tracked: as if SpeakUp was reloaded after the 📄 was added
    await sp.on_raw_reaction_add(SimpleNamespace(message_id=link_msg.id, user_id=3, emoji="📄", guild_id=guild.id,
                                                 channel_id=channel.id, member=chris))
    check(claude.urls == ["https://example.com/story"] and "**Summary**" in channel.sent[-1].content,
          "link offer rebuilt after a reload")

    # someone else's 📄 on a message we never reacted to: ignored
    other = FakeMessage(channel, "https://example.com/other", author=alex)
    other.reactions = [SimpleNamespace(emoji="📄", me=False)]
    channel.messages[other.id] = other
    await sp.on_raw_reaction_add(SimpleNamespace(message_id=other.id, user_id=3, emoji="📄", guild_id=guild.id,
                                                 channel_id=channel.id, member=chris))
    check(claude.urls == ["https://example.com/story"], "not our reaction: ignored")

    # a time said earlier is read as of when it was said
    time_msg = FakeMessage(channel, "anyone up to play at 9?", author=alex)
    time_msg.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    time_msg.reactions = [SimpleNamespace(emoji="🕘", me=True)]
    channel.messages[time_msg.id] = time_msg
    await sp.on_raw_reaction_add(SimpleNamespace(message_id=time_msg.id, user_id=3, emoji="🕘", guild_id=guild.id,
                                                 channel_id=channel.id, member=chris))
    check("**at 9** is <t:" in card_text(channel.sent[-1]), card_text(channel.sent[-1]))

    # too old: ignored
    old = FakeMessage(channel, "https://example.com/old", author=alex)
    old.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    old.reactions = [SimpleNamespace(emoji="📄", me=True)]
    channel.messages[old.id] = old
    await sp.on_raw_reaction_add(SimpleNamespace(message_id=old.id, user_id=3, emoji="📄", guild_id=guild.id,
                                                 channel_id=channel.id, member=chris))
    check(claude.urls == ["https://example.com/story"], "offers expire after a day")
    for name in ("SpeakUp", "ClaudeChat"):
        await bot.remove_cog(name)


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
