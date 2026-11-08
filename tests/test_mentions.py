"""Mentions are explained to Claude, and made readable for Gemini and seeded thread history."""
import asyncio
from types import SimpleNamespace

from harness import FakeGuild, FakeMessage, TestBot, load

claude_mod = load("claude", "claude")
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "blueberry pwncakes")
    chris = guild.add(2, "Chris")
    bot = TestBot(guild)
    cc = claude_mod.ClaudeChat(bot)
    await bot.add_cog(cc)
    role = SimpleNamespace(id=77, name="Officers")
    chan = SimpleNamespace(id=88, name="general")

    msg = FakeMessage(guild.channel, "!ai please have head butler <@2> bring sugar, ask <@&77> in <#88>", author=brad)
    msg.mentions, msg.role_mentions, msg.channel_mentions = [chris, guild.me], [role], [chan]
    session = claude_mod.Session() if hasattr(claude_mod, "Session") else None
    blocks, _ = await cc._build_user_turn(msg, "please have head butler <@2> bring sugar", "CHANNEL_500", session)
    text = blocks[-1]["text"]
    check("<@2> is Chris" in text, text)
    check("<@999> is you" in text and "<@&77> is the role @Officers" in text and "<#88> is the channel #general" in text, text)
    check(text.startswith("blueberry pwncakes: (Who's who: <@1> is blueberry pwncakes (speaking); <@2> is Chris"), text)

    plain = FakeMessage(guild.channel, "!ai hi", author=brad)
    plain.role_mentions = plain.channel_mentions = []
    blocks, _ = await cc._build_user_turn(plain, "hi", "CHANNEL_500", session)
    check(blocks[-1]["text"] == "blueberry pwncakes: (Who's who: <@1> is blueberry pwncakes (speaking))\nhi",
          blocks[-1]["text"])

    # Replying to someone's message: their ID is in the note too
    ref = FakeMessage(guild.channel, "I'm the head butler", author=chris)
    reply = FakeMessage(guild.channel, "!ai is he right?", author=brad)
    async def referenced(message):
        return ref if message is reply else None
    cc._referenced_message = referenced
    blocks, _ = await cc._build_user_turn(reply, "is he right?", "CHANNEL_500", session)
    check("<@1> is blueberry pwncakes (speaking); <@2> is Chris)" in blocks[-1]["text"], blocks[-1]["text"])

    check(cc._readable("draw <@!2> and <@2> in <#88> for <@&77>", msg) == "draw @Chris and @Chris in #general for @Officers",
          cc._readable("draw <@!2> and <@2> in <#88> for <@&77>", msg))
    system = await cc._system_prompt(guild, False, False)
    check("Who's who" in system and "<@id> exactly" in system, "system prompt explains mentions")
    await bot.remove_cog("ClaudeChat")


FakeMessage.role_mentions = []
FakeMessage.channel_mentions = []
asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
