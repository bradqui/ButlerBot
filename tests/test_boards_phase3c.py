"""UI phase 3 (boards), part C: trivia lists, the guess-the-game leaderboard, reminders, help cards, image models."""
import asyncio
import re
import time

from harness import (enable_dms, DATA_DIR, FakeGuild, FakeInteraction, FakeMessage, TestBot, card_buttons, card_color, card_text,
                     dcommands, discord, load)
import sys  # noqa: E402
import types  # noqa: E402

# ---- a stub google.genai, enough to import the Gemini cog ----
google = types.ModuleType("google")
genai = types.ModuleType("google.genai")
genai_types = types.ModuleType("google.genai.types")
genai_types.GenerateContentConfig = lambda **kw: kw
genai.Client = lambda api_key: types.SimpleNamespace(aio=types.SimpleNamespace())
genai.types = genai_types
google.genai = genai
sys.modules.update({"google": google, "google.genai": genai, "google.genai.types": genai_types})

bf_mod = load("parlor", "parlor")
sp_mod = load("speakup", "speakup")
hb_mod = load("handbook", "handbook")
gemini_mod = load("gemini", "gemini")
gm_mod = load("gamemanager", "gamemanager")
ui = bf_mod.ui
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


def no_pings(am) -> bool:
    return am is not None and not am.everyone and not am.users and not am.roles


def nav(msg, which):
    return next((b for b in card_buttons(msg) if str(b.emoji) == which), None)


async def all_pages(bot, guild, user, msg) -> list:
    """Click ▶ until it greys out; the text of every page, in order."""
    texts = [card_text(msg)]
    for _ in range(50):
        nxt = nav(msg, "▶️")
        if nxt is None or nxt.disabled:
            break
        i = FakeInteraction(bot, guild, user, msg.channel, msg)
        await nxt.callback(i)
        check(no_pings(msg.edits[-1].get("allowed_mentions")), "paging edits don't ping")
        texts.append(card_text(msg))
    return texts


def big_cog():
    """A cog with 50 commands and a group with 45 subcommands and a very long description."""
    attrs = {"__doc__": "A category with lots of commands."}
    for i in range(50):
        async def cb(self, ctx):
            pass
        cb.__doc__ = f"Command number {i}. " + "It does a great many interesting things. " * 5
        attrs[f"cmd{i:02d}"] = dcommands.command(name=f"cmd{i:02d}")(cb)

    async def grp(self, ctx):
        pass
    grp.__doc__ = "A huge group.\n\n" + "\n".join(f"Paragraph {i}: " + "words " * 30 for i in range(30))
    group = dcommands.group(name="hugegroup")(grp)
    attrs["hugegroup"] = group
    for i in range(45):
        async def sub(self, ctx):
            pass
        sub.__doc__ = f"Subcommand {i} " + "with a long description " * 6
        attrs[f"sub{i:02d}"] = group.command(name=f"sub{i:02d}")(sub)
    return type("Huge", (dcommands.Cog,), attrs)()


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex = guild.add(2, "Alex")
    channel = guild.channel
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()

    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        await bot.invoke(ctx)
        await asyncio.sleep(0.02)
        return channel.sent[-1] if channel.sent else None

    # ================= Parlor: maketrivia show =================
    bf = bf_mod.Parlor(bot)
    await bot.add_cog(bf)
    questions = {f"Question {k} about <@2> and @everyone?": [f"Answer {k}", f"alt {k}"] for k in range(60)}
    questions["A hand-edited question that goes on and on " + "and on " * 150 + "?"] = ["Long|answer " * 40]
    bf_mod.write_trivia(DATA_DIR / "bb_boardtest.yaml", {"AUTHOR": "x"}, questions)
    enable_dms()
    await run(brad, "!maketrivia show boardtest")
    msg = brad.dms[-1]   # Phase 4: the answers go to the mod's DMs
    check(msg.flags.components_v2 and "file" not in msg.kw and no_pings(msg.kw.get("allowed_mentions")),
          "trivia list: one ping-free board, no file")
    first = card_text(msg)
    check(first.startswith("### 🧠 bb_boardtest\n")
          and "\n**1.** Question 0 about <@2> and @everyone?\n-# ||Answer 0, alt 0||\n" in first
          and card_color(msg) == ui.BRAND, first[:200])
    check(first.endswith("-# Page 1 of 8 · 61 questions · `!maketrivia remove bb_boardtest <numbers>` drops some"),
          first[-300:])
    check([str(b.emoji) for b in card_buttons(msg)] == ["◀️", "▶️"] and nav(msg, "◀️").disabled, "arrows, ◀ off on page 1")
    jump = [i for i in msg.view.walk_children() if isinstance(i, discord.ui.Select)]
    check(len(jump) == 1 and jump[0].options[0].label == "Page 1" and len(jump[0].options) == 8,
          "a Jump to menu past 5 pages")
    pages = await all_pages(bot, guild, alex, msg)
    check(len(pages) == 8 and nav(msg, "▶️").disabled and not nav(msg, "◀️").disabled, len(pages))
    rows = [m for p in pages for m in re.findall(r"^\*\*(\d+)\.\*\* (.*)\n-# (.*)$", p, flags=re.M)]
    check(len(rows) == 61 and [int(n) for n, _, _ in rows] == list(range(1, 62)), len(rows))
    check(all(a.count("||") == 2 and a.startswith("||") and a.endswith("||") and len(q) + len(a) <= 600
              for _, q, a in rows), "every answer stays spoilered, on the line under its question")
    check("|" not in rows[-1][2][2:-2], "pipes in answers can't break the spoiler")
    check(all(len(p) <= 4000 for p in pages), [len(p) for p in pages])
    # every list
    msg = await run(brad, "!maketrivia show")
    check(card_text(msg).startswith("### 🧠 Trivia lists\n") and "**`bb_boardtest`**\n-# 61 questions" in card_text(msg)
          and card_text(msg).endswith("-# `!maketrivia show <name>` shows one") and not card_buttons(msg), card_text(msg))

    # ================= Parlor: the guessing games' leaderboard =================
    for uid in range(10, 32):
        member = guild.add(uid, f"Player {uid}")
        await bf.config.member(member).wins.set({"guess": uid})
    msg = await run(alex, "!guessgame top")
    text = card_text(msg)
    check(msg.flags.components_v2 and card_color(msg) == ui.HIGHLIGHT and no_pings(msg.kw.get("allowed_mentions")),
          "leaderboard: a ping-free HIGHLIGHT board")
    check(text.startswith("### 🃏 Parlor games: top players\n**1. Player 31** 🥇\n-# 31 wins · 31 picture games\n"
                          "**2. Player 30** 🥈\n-# 30 wins · 30 picture games\n**3. Player 29** 🥉\n"
                          "-# 29 wins · 29 picture games\n**4. Player 28**\n-# 28 wins · 28 picture games\n")
          and "Page 1 of 3" in text and "<@" not in text, text[:200])
    pages = await all_pages(bot, guild, alex, msg)
    check(len(pages) == 3 and "**22. Player 10**\n-# 10 wins · 10 picture games" in pages[2], pages[-1][:200])

    # ================= SpeakUp: reminders =================
    sp = sp_mod.SpeakUp(bot)
    await bot.add_cog(sp)
    sp.reminder_loop.cancel()
    async with sp.config.reminders() as rem:
        for k in range(25):
            rid = f"r{k:02d}"
            rem[rid] = {"id": rid, "user": 2, "guild": 1, "channel": channel.id, "jump": "",
                        "text": f"reminder {k} for <@1> and @everyone", "due": time.time() + 3600 * (k + 1),
                        "created": time.time()}
    msg = await run(alex, "!reminders")
    text = card_text(msg)
    check(msg.flags.components_v2 and no_pings(msg.kw.get("allowed_mentions"))
          and text.startswith("### ⏰ Your reminders\n**reminder 0 for <@1> and @everyone**\n-# <t:")
          and f" · in <#{channel.id}> · ID `r00`\n" in text
          and text.endswith("-# Page 1 of 4 · `!reminders cancel <id>` cancels one"), text[-200:])
    pages = await all_pages(bot, guild, brad, msg)
    check(len(pages) == 4 and "`r24`" in pages[3] and "`r07`" in pages[0] and "`r08`" not in pages[0], "25 reminders page")

    # ================= Handbook: help boards =================
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
    base = hb_mod.DEFAULT_URL if hb_mod.DEFAULT_URL.endswith("/") else hb_mod.DEFAULT_URL + "/"

    async def ctx_for(author, content="!help"):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        ctx.me = guild.me
        return ctx

    await fmt.send_help(await ctx_for(alex), "hugegroup")
    msg = channel.sent[-1]
    pages = [card_text(msg)]
    check(pages[0].startswith("### 📖 !hugegroup\n`!hugegroup") and "-# Who: Everyone\n\nA huge group." in pages[0]
          and re.search(r"\*\*Subcommands\*\*\n`!hugegroup sub00[^`\n]*`\n-# Subcommand 0 with a long", pages[0])
          and "…and" not in pages[0]
          and no_pings(msg.kw.get("allowed_mentions")), pages[0][:200])
    links = [(b.label, b.url) for b in card_buttons(msg) if b.url]
    check(links == [("Open the reference", base + "reference/huge/#hugegroup")], links)
    pages = await all_pages(bot, guild, alex, msg)
    subs = [ln for p in pages for ln in p.splitlines() if ln.startswith("`!hugegroup sub")]
    check(len(subs) == 45 and len(set(subs)) == 45 and len(pages) == 6, f"every subcommand on some page ({len(subs)})")
    check(any(isinstance(i, discord.ui.Select) for i in msg.view.walk_children()), "six pages: a Jump to menu")
    check(all(len(p) <= 4000 for p in pages) and all("A huge group." in p for p in pages), [len(p) for p in pages])
    check([(b.label, b.url) for b in card_buttons(msg) if b.url] == links, "link buttons kept after paging")
    msg.view.message = msg
    await msg.view.on_timeout()
    link_buttons = [b for b in card_buttons(msg) if b.url]
    check(link_buttons and not any(b.disabled for b in link_buttons) and nav(msg, "▶️").disabled
          and "Run the command again to page through it." in card_text(msg), "after expiry: arrows off, links live")

    # a cog with many commands
    await fmt.send_help(await ctx_for(alex), "Huge")
    msg = channel.sent[-1]
    first = card_text(msg)
    check(re.match(r"### 📖 Huge\nA category with lots of commands.\n`!cmd00[^`\n]*`\n-# Command number 0\n`!cmd01", first)
          and "Page 1 of " in first
          and "more in the command reference" not in first, first[:200])
    check(any(isinstance(c, discord.ui.Separator) for c in msg.view.children[0].children[:3]), "divider under the description")
    pages = await all_pages(bot, guild, alex, msg)
    cmds = [ln for p in pages for ln in p.splitlines() if ln.startswith("`!cmd") or ln.startswith("`!hugegroup")]
    check(len(cmds) == 51 and all(len(p) <= 4000 for p in pages), len(cmds))
    check([b.label for b in card_buttons(msg) if b.url] == ["Open the reference"], "cog board keeps its link")

    # a short group and a plain command stay simple cards (one page: no arrows)
    await fmt.send_help(await ctx_for(alex), bot.get_command("games"))
    msg = channel.sent[-1]
    check([b.label for b in card_buttons(msg) if b.url] == ["Open handbook page", "Open the reference"]
          and "**Subcommands**\n`!games admin`\n-# " in card_text(msg), "games group board keeps both links")
    await fmt.send_help(await ctx_for(alex), bot.get_command("games own"))
    msg = channel.sent[-1]
    check(nav(msg, "▶️") is None and [b.label for b in card_buttons(msg)] == ["Open handbook page", "Open the reference"],
          [b.label for b in card_buttons(msg)])
    await fmt.send_help(await ctx_for(alex), gm)
    msg = channel.sent[-1]
    check([b.url for b in card_buttons(msg) if b.url] == [base + "games/library/", base + "reference/gamemanager/"],
          "games cog links")

    # rows: the command to type, then the first sentence of its help; who can use it only when not everyone
    row = hb._command_row(bot.get_command("games admin add"), "!", "Bot", "game admins only")
    check(row == ("`!games admin add <game_names>`", "Add games to the server library · game admins only"), row)

    # ================= Gemini: image models =================
    gem = gemini_mod.GeminiChat(bot)
    await bot.add_cog(gem)

    async def yes():
        return True

    async def models():
        return [f"gemini-model-{i:02d}-image" for i in range(20)]
    gem._init_genai, gem.image_models = yes, models
    msg = await run(alex, "!gemini list")
    pages = await all_pages(bot, guild, alex, msg)
    check(len(pages) == 3 and pages[0].startswith("### 🎨 Image models\n`gemini-model-00-image`\n")
          and "Pick one with !gemini channelmodel" in pages[2] and "`gemini-model-19-image`" in pages[2]
          and "Shortcuts" not in pages[2], pages[-1][-200:])


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
