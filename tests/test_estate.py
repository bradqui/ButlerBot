"""Estate: the owner's spend view, budget caps and alerts, the remote AI switch, new servers, health; plus the
Claude and Gemini cogs' monthly counts and budget checks."""
import asyncio
import logging
import sys
import types
from unittest.mock import MagicMock

from harness import card_text, FakeGuild, FakeInteraction, FakeMessage, TestBot, discord, load

# a stub google.genai, enough to load the Gemini cog
google, genai, genai_types = (types.ModuleType(n) for n in ("google", "google.genai", "google.genai.types"))
genai_types.GenerateContentConfig = lambda **kw: kw
genai.Client = MagicMock
genai.types = genai_types
google.genai = genai
sys.modules.update({"google": google, "google.genai": genai, "google.genai.types": genai_types})

estate_mod = load("estate", "estate")
claude_mod = load("claude", "claude")
gemini_mod = load("gemini", "gemini")
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


class Client:
    class messages:
        @staticmethod
        async def create(**kw):
            r = MagicMock()
            r.model, r.stop_reason = kw["model"], "end_turn"
            r.content = [MagicMock(type="text", text="Hello there")]
            r.usage = MagicMock(input_tokens=100_000, output_tokens=10_000, cache_read_input_tokens=0,
                                cache_creation_input_tokens=0, server_tool_use=None)
            return r


Client.beta = Client


async def main():
    # ---- helpers ----
    p = estate_mod.parse_amount
    check(p("$25") == (True, 25.0) and p("12.5") == (True, 12.5) and p("off") == (True, None) and p("0") == (True, None)
          and p("lots")[0] is False and p("-5")[0] is False, "amounts")
    check(estate_mod.split_last("Gaming Hall 10") == ("Gaming Hall", "10") and estate_mod.split_last("off") == ("", "off"),
          "server, then the last word")
    check(estate_mod.money(1234.5) == "$1,234.50", "money")

    # ---- setup ----
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)   # the bot's owner
    alex = guild.add(2, "Alex")
    channel = guild.channel
    guild.member_count, guild.owner, guild.owner_id = 2, brad, 1
    guild.me.guild_permissions = discord.Permissions(send_messages=True, embed_links=True, attach_files=True,
                                                     add_reactions=True, read_message_history=True)
    import datetime as _dt
    guild.me.joined_at = _dt.datetime(2026, 1, 2, tzinfo=_dt.timezone.utc)
    left = []

    async def leave():
        left.append(guild.id)
    guild.leave = leave
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    TestBot.guilds = property(lambda self: [self.test_guild])
    owner_dms = []

    async def send_to_owners(content=None, **kw):
        owner_dms.append((content, kw))
    bot.send_to_owners = send_to_owners
    errors = []

    async def on_command_error(ctx, error):
        errors.append(f"{ctx.message.content}: {error!r}")
    bot.on_command_error = on_command_error

    cc = claude_mod.ClaudeChat(bot)
    await bot.add_cog(cc)

    async def get_client():
        return Client()
    cc._get_client = get_client
    gem = gemini_mod.GeminiChat(bot)
    await bot.add_cog(gem)

    async def init_genai():
        return True
    gem._init_genai = init_genai
    est = estate_mod.Estate(bot)
    await bot.add_cog(est)
    est.alert_loop.cancel()

    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        await bot.invoke(ctx)
        await asyncio.sleep(0.05)
        return channel.sent[-1]

    # ---- monthly counts: Claude's cost, Gemini's images ----
    text, err = await cc.complete(alex, channel, system="x", messages=[{"role": "user", "content": "hi"}])
    month = estate_mod.this_month()
    months = await cc.config.guild(guild).usage_months()
    check(text == "Hello there" and month in months and months[month]["cost"] > 0 and months[month]["requests"] == 1,
          f"Claude counts the month: {months}")
    await gem._count_image(guild)
    await gem._count_image(guild)
    check(await gem.monthly_images(month) == {guild.id: 2}, "Gemini counts images per month")
    data = await est.spend(fresh=True)
    cost = months[month]["cost"]
    check(abs(data["claude"] - cost) < 1e-9 and data["images"] == 2
          and abs(data["total"] - (cost + 2 * estate_mod.IMAGE_COST)) < 1e-9
          and abs(data["guilds"][guild.id]["cost"] - data["total"]) < 1e-9, data)

    # ---- the remote switch and budgets block AI everywhere it's used ----
    check(await est.ai_blocked(guild) is None, "nothing blocks by default")
    await est.config.guild(guild).ai_off.set(True)
    text, err = await cc.complete(alex, channel, system="x", messages=[{"role": "user", "content": "hi"}])
    data_, why = await gem.render_image("a cat", channel=channel)
    check(text is None and err.startswith("⚠️ AI features are switched off in this server") and data_ is None
          and why == err, f"switched off: {err}")
    check(await cc.summarize_link("https://example.com", alex) is None, "link summaries stop too")
    await est.config.guild(guild).ai_off.set(False)
    await est.config.budget.set(round(data["total"] / 2, 6))
    est._spend_cache = (0.0, "", {})
    text, err = await cc.complete(alex, channel, system="x", messages=[{"role": "user", "content": "hi"}])
    check(text is None and err.startswith("⏳ The bot has used this month's AI budget") and "<t:" in err, err)
    await est.config.budget.set(None)
    await est.config.guild(guild).budget.set(round(data["total"] / 2, 6))
    text, err = await cc.complete(alex, channel, system="x", messages=[{"role": "user", "content": "hi"}])
    check(text is None and err.startswith("⏳ This server has used its AI budget"), err)
    await est.config.guild(guild).budget.set(None)

    # ---- alerts: 50/80/100%, each once a month ----
    await est.config.budget.set(round(data["total"] * 1.5, 6))   # about 67% used
    await est.alert_loop.coro(est)
    check(len(owner_dms) == 1 and owner_dms[-1][0].startswith("⚠️ The bot has used 50% of its"), owner_dms)
    await est.alert_loop.coro(est)
    check(len(owner_dms) == 1, "the same step isn't sent twice")
    await est.config.budget.set(round(data["total"] * 0.9, 6))   # over
    await est.alert_loop.coro(est)
    check(len(owner_dms) == 2 and owner_dms[-1][0].startswith("⏳ The bot has reached its")
          and "paused until the month ends" in owner_dms[-1][0], owner_dms[-1][0])
    await est.config.guild(guild).budget.set(round(data["total"] * 0.6, 6))
    await est.alert_loop.coro(est)
    check(owner_dms[-1][0].startswith("⏳ **Test Server** has reached its"), owner_dms[-1][0])
    await est.config.budget.set(None)
    await est.config.guild(guild).budget.set(None)

    # ---- a new server: a DM with a Leave button, and leaving after a confirmation ----
    await est.on_guild_join(guild)
    content, kw = owner_dms[-1]
    button = kw["view"].children[0]
    check(content.startswith("🏰 I joined **Test Server**: 2 members, owned by Brad.")
          and button.item.custom_id == f"est:leave:{guild.id}", content)
    i = FakeInteraction(bot, guild, alex, channel)
    await estate_mod.LeaveButton(guild.id).callback(i)
    check(i.response.calls[-1][1].startswith("🔒"), "only the owner can make the bot leave")
    i = FakeInteraction(bot, guild, brad, channel)
    await estate_mod.LeaveButton(guild.id).callback(i)
    confirm = i.response.calls[-1][2]["view"]
    check(i.response.calls[-1][1].startswith("⚠️ Leave **Test Server**?") and isinstance(confirm, estate_mod.ConfirmLeave),
          "asks first")
    await confirm.leave.callback(FakeInteraction(bot, guild, brad, channel))
    check(left == [guild.id], "leaves after the confirmation")
    await est.config.join_alerts.set(False)
    n = len(owner_dms)
    await est.on_guild_join(guild)
    check(len(owner_dms) == n, "no DM when join alerts are off")

    # ---- commands (owner) ----
    logging.getLogger("red.parlor").error("Something broke\nTraceback…")
    sent = await run(brad, "!estate")
    text = card_text(sent)
    check(text.startswith("### 🏰 The estate: 1 server\n**This month: $") and "-# Claude $" in text
          and "no monthly budget" in text and "**1 error in the last day**" in text and "⚠️ missing permissions" in text
          and "**Test Server** ⚠️\n-# 2 members · $" in text and "2 images" in text
          and text.endswith("-# Owner only · `!estate server <name>` shows one"), text)
    text = card_text(await run(brad, "!estate server test"))
    check(text.startswith("### 🏰 Test Server\n**Members** · 2\n**Owner** · Brad") and "**AI** · On" in text
          and "**Missing permissions** · Manage Events, Create Public Threads, Send Messages in Threads" in text
          and "**This month** · $" in text, text)
    check((await run(brad, "!estate server nowhere")).content.startswith("❓ I'm not in a server called nowhere."), "?")
    check((await run(brad, "!estate budget 25")).content == "✅ The bot's monthly AI budget is $25.00."
          and await est.config.budget() == 25.0, "set the budget")
    check("($" not in (await run(brad, "!estate budget")).content and "The monthly budget is $25.00" in channel.sent[-1].content,
          channel.sent[-1].content)
    check((await run(brad, "!estate budget lots")).content.startswith("❓ I couldn't read `lots`"), "bad amount")
    check((await run(brad, "!estate cap Test Server 10")).content == "✅ **Test Server** has a monthly AI budget of $10.00."
          and await est.config.guild(guild).budget() == 10.0, "server cap")
    check((await run(brad, "!estate ai Test Server off")).content == "✅ AI features are off in **Test Server**."
          and await est.config.guild(guild).ai_off(), "remote switch")
    text = card_text(await run(brad, "!estate"))
    check("**Test Server** 🔇" in text and "🔇 AI switched off" in text and "cap $10.00" in text, text)
    await run(brad, "!estate ai Test Server on")
    text = card_text(await run(brad, "!estate health"))
    check(text.startswith("### 🏰 Health\n**1 background task stopped**") and "1 error in the last day" in text
          and "**Stopped background tasks**\n-# Estate.alert_loop" in text and "red.parlor: Something broke" in text
          and "**Test Server** ⚠️\n-# Missing Manage Events" in text, text)
    check((await run(brad, "!estate alerts on")).content.startswith("✅ You get a DM when I join a new server."), "alerts")
    check(not errors, f"command errors: {errors}")

    await bot.remove_cog("Estate")
    check(est.errors not in logging.getLogger("red").handlers, "the error log is detached on unload")
    text, err = await cc.complete(alex, channel, system="x", messages=[{"role": "user", "content": "hi"}])
    check(text == "Hello there", "without the Estate cog, nothing is capped")
    print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")


asyncio.run(main())
