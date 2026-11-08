"""SpeakUp: no summary offer on links Discord previews as a picture or GIF."""
import asyncio
from types import SimpleNamespace

from harness import FakeGuild, FakeMessage, TestBot, dcommands, load

sp_mod = load("speakup", "speakup")
sp_mod.EMBED_WAIT = 0
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


async def add_reaction(self, emoji):
    self.reactions_added = getattr(self, "reactions_added", []) + [emoji]
FakeMessage.add_reaction = add_reaction


class ClaudeChat(dcommands.Cog):
    async def summarize_link(self, url, member):
        return "- x"


def embed(kind, url):
    return SimpleNamespace(type=kind, url=url)


async def main():
    guild = FakeGuild()
    alex = guild.add(2, "Alex")
    channel = guild.channel
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    await bot.add_cog(ClaudeChat())
    sp = sp_mod.SpeakUp(bot)
    await bot.add_cog(sp)
    sp.reminder_loop.cancel()
    fetched = {}

    async def fetch_message(mid):
        return fetched[mid]
    channel.fetch_message = fetch_message

    async def post(text, embeds_now=(), embeds_later=()):
        m = FakeMessage(channel, text, author=alex)
        m.embeds = list(embeds_now)
        fetched[m.id] = SimpleNamespace(embeds=list(embeds_later))
        sp._cooldowns.clear()
        await sp._offer_summary(m)
        return getattr(m, "reactions_added", [])

    url = "https://example.com/news/story"
    check(await post(url, [embed("article", url)]) == ["📄"], "article gets the offer")
    gif = "https://gifs.example.net/abc123"
    check(await post(gif, [embed("gifv", gif)]) == [], "GIF link from an unlisted site: no offer")
    img = "https://cdn.example.org/media/XYZ?format=jpg&name=large"
    check(await post(img, embeds_later=[embed("image", img)]) == [], "image preview that arrives late: no offer")
    check(await post(f"{url} and {gif}", [embed("article", url), embed("gifv", gif)]) == ["📄"]
          and sp._tracked[max(sp._tracked)]["url"] == url, "mixed: the article is offered, not the GIF")
    check(await post("https://pbs.twimg.com/media/abc?format=png") == [], "known image host skipped outright")
    check(await post("https://www.youtube.com/watch?v=x", [embed("video", "https://www.youtube.com/watch?v=x")])
          == [], "YouTube links get no summary offer")
    check(await post("https://example.tv/clip/9", [embed("video", "https://example.tv/clip/9")])
          == [], "nor does any link Discord previews as a video")
    for name in ("SpeakUp", "ClaudeChat"):
        await bot.remove_cog(name)


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
