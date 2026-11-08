"""UI phase 2 (cards), Handbook / Claude / Gemini: help cards, AI settings, models, usage, image settings and lists."""
import asyncio
import re
import sys
import types

from harness import (FakeChannel, FakeGuild, FakeInteraction, FakeMessage, TestBot, card_buttons, card_color, card_text, dcommands,
                     discord, enable_dms, load)
enable_dms()

# ---- a stub google.genai, enough to import the Gemini cog ----
google = types.ModuleType("google")
genai = types.ModuleType("google.genai")
genai_types = types.ModuleType("google.genai.types")
genai_types.GenerateContentConfig = lambda **kw: kw
genai.Client = lambda api_key: types.SimpleNamespace(aio=types.SimpleNamespace())
genai.types = genai_types
google.genai = genai
sys.modules.update({"google": google, "google.genai": genai, "google.genai.types": genai_types})

hb_mod = load("handbook", "handbook")
gm_mod = load("gamemanager", "gamemanager")
claude_mod = load("claude", "claude")
gemini_mod = load("gemini", "gemini")
ui = sys.modules["butlerui"]
FakeMessage._state = None
results = []
BASE = "https://bradqui.github.io/ButlerBot/"


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


def is_clean_card(msg) -> bool:
    """A card message: V2 flag, no content, no embed, ping-free."""
    return (msg.flags.components_v2 and not msg.content and "embed" not in msg.kw
            and msg.kw.get("allowed_mentions") is ui.NO_PINGS)


class DMChannel(FakeChannel):
    def __init__(self, bot_user):
        super().__init__(None, cid=777)
        self.bot_user = bot_user

    async def send(self, content=None, **kw):
        msg = FakeMessage(self, content, author=self.bot_user, **kw)
        self.sent.append(msg)
        return msg


def big_cog():
    """A cog with 60 commands with long help, and a group with 40 subcommands and very long help."""
    attrs = {"__doc__": "A test category with lots of commands."}
    for i in range(60):
        async def cb(self, ctx):
            pass
        cb.__doc__ = f"Command number {i}. " + "This command does a great many interesting things. " * 4
        attrs[f"cmd{i:02d}"] = dcommands.command(name=f"cmd{i:02d}")(cb)

    async def grp(self, ctx):
        pass
    grp.__doc__ = "A huge group.\n\n" + "\n".join(f"Paragraph {i}: " + "words " * 30 for i in range(30))
    group = dcommands.group(name="biggroup")(grp)
    attrs["biggroup"] = group
    for i in range(40):
        async def sub(self, ctx):
            pass
        sub.__doc__ = f"Subcommand {i} " + "with a long description " * 6
        attrs[f"sub{i:02d}"] = group.command(name=f"sub{i:02d}")(sub)
    return type("Big", (dcommands.Cog,), attrs)()


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)     # bot owner
    alex = guild.add(2, "Alex")
    channel = guild.channel
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    formatters = []
    bot.set_help_formatter = formatters.append
    bot.reset_help_formatter = lambda: formatters.clear()
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    await bot.add_cog(big_cog())
    hb = hb_mod.Handbook(bot)
    await bot.add_cog(hb)
    fmt = formatters[0]
    footer = "-# " + hb_mod.HELP_FOOTER.format(p="!")

    async def ctx_for(author, content="!help", where=None):
        ctx = await bot.get_context(FakeMessage(where or channel, content, author=author))
        if where is None:
            ctx.me = guild.me
        return ctx

    # ================= Handbook =================
    await fmt.send_help(await ctx_for(alex), None)
    home = channel.sent[-1]
    text = card_text(home)
    urls = {b.label: b.url for b in card_buttons(home)}
    check(is_clean_card(home) and card_color(home) == ui.BRAND, "home is a ping-free BRAND card")
    check(text.startswith("### 📖 Quillbot handbook\nEverything I can do") and "`!butler how do I…`" in text
          and "👋 **[Getting started](" + BASE + "start/)**\n-# New here?" in text and text.endswith(footer), text[:300])
    check("For mods and admins" not in text and "Moderation" not in text and "Server setup" not in text,
          "members don't see the staff section")
    check(urls == {"Open the handbook": BASE, "Browse all commands": BASE + "reference/"}, urls)
    check(all(b.style is discord.ButtonStyle.link for b in card_buttons(home)), "home buttons are links")
    await fmt.send_help(await ctx_for(brad), bot)
    staff_text = card_text(channel.sent[-1])
    check("**For mods and admins**\n🔨 **[Moderation](" + BASE + "moderation/)**\n-# Warnings" in staff_text
          and "⚙️ **[Server setup](" in staff_text, "staff section for staff")
    check(staff_text.index("For mods and admins") > staff_text.index("Getting started"), "staff section after topics")
    lines = [ln for ln in staff_text.splitlines() if ln and not ln.startswith(("###", "-#"))]
    check(all(sum(ch in ln for ch in "👋🤵🤖🎮🎲🎉📊🗣🔊🌐🔨🛡⚙📚") <= 1 for ln in lines), "one emoji per line")

    # help in DMs (no guild): the card still goes out, named after the bot user
    dm = DMChannel(guild.me)
    await fmt.send_help(await ctx_for(alex, "!help", where=dm), None)
    check(dm.sent and is_clean_card(dm.sent[-1]) and card_text(dm.sent[-1]).startswith("### 📖 Quillbot handbook"),
          "help works in DMs")
    await fmt.send_help(await ctx_for(alex, "!help games own", where=dm), "games own")
    check(card_text(dm.sent[-1]).startswith("### 📖 !games own"), "command card in DMs")

    # command card (a Command object, a Group object, and a name)
    await fmt.send_help(await ctx_for(alex), bot.get_command("games own"))
    card = channel.sent[-1]
    text = card_text(card)
    check(is_clean_card(card) and card_color(card) == ui.BRAND, "command card is a BRAND card")
    check(text.startswith("### 📖 !games own\n`!games own [game_names]`\n-# Who: Everyone · Also: `!games ")
          and "`!games iown`" in text and text.endswith("-# `!help games` for related commands"), text[:200])
    check([(b.label, b.url) for b in card_buttons(card)]
          == [("Open handbook page", BASE + "games/library/"), ("Open the reference", BASE + "reference/gamemanager/#games-own")],
          [(b.label, b.url) for b in card_buttons(card)])
    group = bot.get_command("games")
    check(isinstance(group, dcommands.Group), "games is a group")
    await fmt.send_help(await ctx_for(alex), group)
    text = card_text(channel.sent[-1])
    check("**Subcommands**\n`!games admin`\n-# " in text and "\n`!games install [game_names]`\n-# Mark games as "
          "installed" in text, "group card subcommands")
    await fmt.send_help(await ctx_for(alex), "biggroup")
    text = card_text(channel.sent[-1])
    check(len(text) <= 4000 and text.count("```") % 2 == 0 and "**Subcommands**" in text and "Page 1 of " in text
          and not re.search(r"…and \d+ more", text) and text.endswith("-# Page 1 of 5 · " + footer[3:]),
          f"long group card pages ({len(text)} chars)")
    links = [b for b in card_buttons(channel.sent[-1]) if b.url]
    check(len(links) == 1 and links[0].label == "Open the reference",
          "no handbook page for an unmapped cog, reference only")

    # cog card (a Cog object and a friendly name)
    await fmt.send_help(await ctx_for(alex), gm)
    cog_card = channel.sent[-1]
    text = card_text(cog_card)
    check(is_clean_card(cog_card) and text.startswith("### 📖 Games\n") and "\n`!games`\n-# Your game library" in text
          and text.endswith(footer), text[:200])
    check([b.url for b in card_buttons(cog_card)] == [BASE + "games/library/", BASE + "reference/gamemanager/"],
          "cog card links")
    await fmt.send_help(await ctx_for(alex), "Big")
    text = card_text(channel.sent[-1])
    check(len(text) <= 4000 and "A test category with lots of commands." in text and "Page 1 of " in text
          and "more in the command reference." not in text, f"long cog card pages ({len(text)} chars)")

    # not found and errors
    await fmt.send_help(await ctx_for(alex), "gmaes")
    check(channel.sent[-1].content.startswith("❓") and not channel.sent[-1].flags.components_v2, "not found stays a line")
    real = hb.send_home

    async def broken(ctx):
        raise ValueError("boom")
    hb.send_home = broken
    await fmt.send_help(await ctx_for(alex), None)
    check(channel.sent[-1].content == "❌ Something went wrong showing help. The error was logged.", "fallback line")
    hb.send_home = real

    # !handbook <topic>
    await bot.invoke(await ctx_for(alex, "!handbook game nights"))
    topic = channel.sent[-1]
    check(is_clean_card(topic) and card_text(topic).startswith("### 📖 Game nights\nSessions, weekly")
          and [(b.label, b.url) for b in card_buttons(topic)] == [("Open this page", BASE + "games/nights/")],
          card_text(topic))
    await bot.invoke(await ctx_for(alex, "!handbook"))
    check(card_text(channel.sent[-1]).startswith("### 📖 Quillbot handbook"), "!handbook alone is the home card")
    await bot.invoke(await ctx_for(alex, "!handbook zzzqqq"))
    check(channel.sent[-1].content.startswith("❓ No handbook topic"), "unknown topic stays a line")
    for name in ("Handbook", "GameManager", "Big"):
        await bot.remove_cog(name)

    # ================= Claude =================
    cc = claude_mod.ClaudeChat(bot)
    await bot.add_cog(cc)

    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        await bot.invoke(ctx)
        return channel.sent[-1]

    await cc.config.guild(guild).persona.set("Line one of the persona <@2>.\n" + "Be a butler. " * 100)
    await cc.config.guild(guild).daily_limit.set(30)
    msg = await run(alex, "!claude settings")
    text = card_text(msg)
    check(is_clean_card(msg) and card_color(msg) == ui.BRAND, "settings is a ping-free BRAND card")
    check(text.startswith("### 🤖 AI chat settings\n**Models**\n**This channel** · ") and "private" not in text
          and "**This server**\n" in text
          and "**Bot-wide**\n" in text and "**Web search** · " in text and "**Daily limit** · 30 messages per person" in text,
          text)
    persona_row = next(ln for ln in text.splitlines() if ln.startswith("**Persona**"))
    check(len(persona_row) < 230 and persona_row.endswith("…") and "\n" not in persona_row
          and "(default)" not in persona_row, persona_row)
    check(text.endswith("\n-# !help claude shows how to change these")
          and "Staff only" not in text and "[p]" not in text, text[-200:])
    check(not card_buttons(msg), "settings card has no buttons")
    await cc.config.guild(guild).persona.set(None)
    await cc.config.guild(guild).daily_limit.set(0)
    text = card_text(await run(alex, "!claude settings"))
    check("(default)" in text and "**Daily limit** · Unlimited" in text, "default persona and no limit")

    msg = await run(alex, "!claude models")
    text = card_text(msg)
    check(is_clean_card(msg) and text.startswith("### 🤖 AI models\n**Sonnet 5.5**\n-# `sonnet` · $2 in, $10 out")
          and "\n-# Channel managers pick from the allowed ones with !claude channelmodel" in text, text)

    # usage: own, someone else's (staff), the server's (staff)
    usage = dict(claude_mod.EMPTY_USAGE, requests=12, input=34567, output=8900, cost=1.234)
    await cc.config.member(alex).usage.set(usage)
    await cc.config.guild(guild).usage.set(dict(usage, requests=20, cost=3.5))
    await cc.config.guild(guild).usage_since.set("2026-11-01")
    await run(alex, "!claude usage")
    msg = alex.dms[-1]   # Phase 4: your own usage comes by DM
    text = card_text(msg)
    check(is_clean_card(msg) and text.startswith("### 🤖 AI usage: Alex\n**Requests** · 12\n")
          and "**Estimated cost** · $1.23" in text and "**Messages today** · 0" in text
          and "Staff only" not in text, text)
    ctx = await bot.get_context(FakeMessage(channel, "!claude usage Brad", author=alex))
    await cc.claude_usage.callback(cc, ctx, brad)
    check(channel.sent[-1].content.startswith("🔒"), "members can't see others' usage")
    ctx = await bot.get_context(FakeMessage(channel, "!claude usage Alex", author=brad))
    await cc.claude_usage.callback(cc, ctx, alex)
    text = card_text(channel.sent[-1])
    check(text.startswith("### 🤖 AI usage: Alex") and text.endswith("Staff only"), text[-80:])
    msg = await run(brad, "!claude usage")
    text = card_text(msg)
    check(is_clean_card(msg) and text.startswith("### 🤖 AI usage: Test Server\n**Requests** · 20")
          and "**Counting since** · <t:1793491200:D>" in text and "**Members**\n**Alex**\n-# 12 requests · $1.23" in text
          and text.endswith("\n-# Staff only"), text)

    # persona display stays plain text in code blocks
    out = await run(brad, "!claude persona")
    check(out.content.startswith("**Current persona:**```") and not out.flags.components_v2, "persona stays plain")
    await bot.remove_cog("ClaudeChat")

    # ================= Gemini =================
    gem = gemini_mod.GeminiChat(bot)
    await bot.add_cog(gem)
    await gem.config.channel(channel).image_model.set("gemini-3-pro-image-preview")
    msg = await run(alex, "!gemini settings")
    text = card_text(msg)
    check(is_clean_card(msg) and card_color(msg) == ui.BRAND
          and text.startswith("### 🎨 Image settings\n**This channel** · `gemini-3-pro-image-preview`")
          and text.endswith("\n-# Change with !gemini channelmodel"), text)

    async def yes():
        return True
    gem._init_genai = yes
    names = [f"gemini-test-{i:03d}-image-preview-with-a-long-name" for i in range(150)]

    async def many():
        return names
    gem.image_models = many
    before = len(channel.sent)
    await run(alex, "!gemini list")
    cards = channel.sent[before:]
    check(len(cards) == 1 and is_clean_card(cards[0]), "one board for a long model list")
    board = cards[0]
    texts = [card_text(board)]
    while True:
        nxt = [b for b in card_buttons(board) if str(b.emoji) == "▶️"]
        if not nxt or nxt[0].disabled:
            break
        await nxt[0].callback(FakeInteraction(bot, guild, brad, channel, board))
        texts.append(card_text(board))
    check(len(texts) == 19 and all(len(t) <= 4000 for t in texts), [len(t) for t in texts])
    check(texts[0].startswith("### 🎨 Image models\n`") and "Page 1 of 19" in texts[0]
          and texts[-1].endswith("Page 19 of 19 · Pick one with !gemini channelmodel"), texts[-1][-120:])
    joined = "\n".join(texts)
    check(all(joined.count(f"`{n}`") == 1 for n in names), "every model listed once across pages")

    async def few():
        return ["gemini-2.5-flash-image"]
    gem.image_models = few
    msg = await run(alex, "!gemini list")
    check(card_text(msg).startswith("### 🎨 Image models\n`gemini-2.5-flash-image`"), card_text(msg))
    await bot.remove_cog("GeminiChat")


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
