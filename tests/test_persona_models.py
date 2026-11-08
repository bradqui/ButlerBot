import asyncio
from harness import FakeGuild, FakeMessage, TestBot, load

claude_mod = load("claude", "claude")
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "Brad")
    alex = guild.add(2, "Alex")
    channel = guild.channel
    bot = TestBot(guild)
    cc = claude_mod.ClaudeChat(bot)
    await bot.add_cog(cc)

    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        check(ctx.valid, f"parses: {content}")
        await bot.invoke(ctx)
        return channel.sent[-1].content

    check(await cc._persona(guild) == claude_mod.DEFAULT_PERSONA, "built-in default")
    await run(brad, "!claude persona You are a pirate.")
    await run(brad, "!claude defaultpersona current")
    check(await cc.config.guild(guild).default_persona() == "You are a pirate.", "save current as default")
    await run(brad, "!claude persona You are a robot.")
    check(await cc._persona(guild) == "You are a robot.", "temporary persona")
    out = await run(brad, "!claude persona reset")
    check(await cc._persona(guild) == "You are a pirate." and "pirate" in out, "reset returns to saved default")
    check("You are a pirate." in await cc._system_prompt(guild, False, False), "AI prompt uses default")
    check("You are a pirate." in await cc._system_prompt(guild, False, False, actions=True), "the AI uses the default")
    await run(brad, "!claude defaultpersona clear")
    check(await cc._persona(guild) == claude_mod.DEFAULT_PERSONA, "clear -> built-in")
    await run(brad, "!claude defaultpersona Be brief.")
    out = await run(brad, "!claude defaultpersona")
    check("Be brief." in out, "show default")

    # Personal conversations and models are gone (2026-11-05); channels pick from the allowed models
    check(bot.get_command("myai") is None and bot.get_command("claude mymodel") is None, "no !myai or mymodel")
    await cc.config.channel(channel).model.set("claude-opus-5-5")
    check(await cc._model_for("CHANNEL_1", alex, channel) == "claude-opus-5-5", "channel model")
    await run(brad, "!claude disallowmodel opus")
    check(await cc._model_for("CHANNEL_1", alex, channel) == "claude-opus-5-5", "disallowing keeps channel picks")


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
