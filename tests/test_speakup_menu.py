"""SpeakUp: right-click "Summarize link", answered privately."""
import asyncio
from types import SimpleNamespace

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, dcommands, discord, load

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
        self.calls = []

    async def summarize_link(self, url, member):
        self.calls.append(url)
        return "- the gist"


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
    menu = bot.tree.get_command("Summarize link", type=discord.AppCommandType.message)
    check(menu is not None, "context menu registered")

    url = "https://example.com/story"
    msg = FakeMessage(channel, f"read this {url}", author=alex)
    msg.embeds = [SimpleNamespace(type="article", url=url)]
    i = FakeInteraction(bot, guild, chris, channel)
    await sp.summarize_from_menu(i, msg)
    content, kw = i.followup.calls[-1]
    check(kw.get("ephemeral") and "**Summary** of <https://example.com/story>" in content and "the gist" in content,
          "summary shown only to the asker")
    check(not channel.sent, "nothing posted in the channel")

    i2 = FakeInteraction(bot, guild, alex, channel)
    await sp.summarize_from_menu(i2, msg)
    check(claude.calls == [url], "second request reuses the cached summary")

    gif = FakeMessage(channel, "https://gifs.example.net/x", author=alex)
    gif.embeds = [SimpleNamespace(type="gifv", url="https://gifs.example.net/x")]
    i3 = FakeInteraction(bot, guild, chris, channel)
    await sp.summarize_from_menu(i3, gif)
    check("no article link" in i3.followup.calls[-1][0], "GIFs aren't summarized")

    sp._summaries[chris.id] = [__import__("time").time()] * sp_mod.SUMMARIES_PER_HOUR
    i4 = FakeInteraction(bot, guild, chris, channel)
    other = FakeMessage(channel, "https://example.com/other", author=alex)
    other.embeds = [SimpleNamespace(type="article", url="https://example.com/other")]
    await sp.summarize_from_menu(i4, other)
    check("summaries this hour" in i4.followup.calls[-1][0] and i4.followup.calls[-1][1].get("ephemeral"),
          "rate limit applies, privately")

    await bot.remove_cog("SpeakUp")
    check(bot.tree.get_command("Summarize link", type=discord.AppCommandType.message) is None, "removed on unload")
    await bot.remove_cog("ClaudeChat")


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
