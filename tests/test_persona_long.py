import asyncio
from harness import FakeGuild, FakeMessage, TestBot, load

claude_mod = load("claude", "claude")
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


class Att:
    def __init__(self, text):
        self.data = text.encode("utf-8")
        self.size = len(self.data)
        self.filename = "persona.txt"

    async def read(self):
        return self.data


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "Brad")
    channel = guild.channel
    bot = TestBot(guild)
    cc = claude_mod.ClaudeChat(bot)
    await bot.add_cog(cc)

    async def run(content, attachment=None):
        msg = FakeMessage(channel, content, author=brad)
        if attachment:
            msg.attachments = [attachment]
        before = len(channel.sent)
        await bot.invoke(await bot.get_context(msg))
        return [m.content for m in channel.sent[before:]]

    long_text = ("You are ButlerBot. " + "You resent the silver. " * 120).strip()[:2600]
    out = await run("!claude persona", Att(long_text))
    check(await cc.config.guild(guild).persona() == long_text and "2,600 characters" in out[-1], f"file persona: {out}")
    out = await run("!claude persona")
    check(len(out) == 2 and all(len(o) <= 2000 for o in out) and out[0].startswith("**Current persona:**"),
          f"long persona shown in {len(out)} messages")
    out = await run("!claude persona", Att("x" * 8001))
    check("under 8,000" in out[-1] and await cc.config.guild(guild).persona() == long_text, "over-limit rejected")
    out = await run("!claude defaultpersona current")
    check(await cc.config.guild(guild).default_persona() == long_text, "long persona saved as default")
    await run("!claude persona Be brief.")
    out = await run("!claude persona reset")
    check(await cc._persona(guild) == long_text and all(len(o) <= 2000 for o in out), "reset to long default")
    out = await run("!claude defaultpersona", Att(""))
    check("empty" in out[-1], "empty file rejected")


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
