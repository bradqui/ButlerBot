"""Handbook: help cards, topic links, generated reference."""
import asyncio
import io
import re
import zipfile

from harness import (FakeConfig, FakeGuild, FakeMessage, TestBot, card_buttons, card_color, card_text, dcommands,
                     discord, load)

hb_mod = load("handbook", "handbook")
gm_mod = load("gamemanager", "gamemanager")
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


class CustomCommands(dcommands.Cog):
    def __init__(self):
        self.config = FakeConfig()
        self.config.register_guild(commands={})


class Alias(dcommands.Cog):
    def __init__(self):
        self.config = FakeConfig()
        self.config.register_guild(entries=[])
        self.config.register_global(entries=[])


class Secret(dcommands.Cog):
    """Owner stuff."""

    @dcommands.command()
    @dcommands.is_owner()
    async def shutdownish(self, ctx):
        """Owner only."""


async def _menu_cb(interaction: discord.Interaction, message: discord.Message):
    pass


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
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
    cc, alias = CustomCommands(), Alias()
    await bot.add_cog(cc)
    await bot.add_cog(alias)
    await bot.add_cog(Secret())
    from types import SimpleNamespace
    from harness import PrivilegeLevel
    bot.get_command("shutdownish").requires = SimpleNamespace(privilege_level=PrivilegeLevel.BOT_OWNER, user_perms=None)
    hb = hb_mod.Handbook(bot)
    await bot.add_cog(hb)
    check(hb.formatter_active and isinstance(formatters[0], hb_mod.HandbookHelp), "help formatter installed")
    fmt = formatters[0]

    async def ctx_for(author, content="!help"):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        ctx.me = guild.me
        return ctx

    # home
    await fmt.send_help(await ctx_for(alex), None)
    home = channel.sent[-1]
    desc = card_text(home)
    check("[Your games](https://bradqui.github.io/ButlerBot/games/library/)" in desc and "Moderation" not in desc
          and home.flags.components_v2 and not home.content and "embed" not in home.kw,
          "home lists member topics with links")
    await fmt.send_help(await ctx_for(brad), bot)
    check("For mods and admins" in card_text(channel.sent[-1]), "staff see the mod topics")
    check("🎮 **[Your games](https://bradqui.github.io/ButlerBot/games/library/)**\n-# Your library, profile setup"
          in desc and "Everything I can do, explained by task.\n-# Not sure what to type? Ask me: `!butler how do I…`"
          in desc and desc.endswith("-# `!help <command>` for details"), "home: a two-line block per topic")
    # command card
    await fmt.send_help(await ctx_for(alex), "games own")
    card = channel.sent[-1]
    text = card_text(card)
    check(text.startswith("### 📖 !games own\n`!games own [game_names]`\n-# Who: Everyone · Also: ")
          and "`!games iown`" in text and text.endswith("-# `!help games` for related commands"), text[:300])
    urls = [b.url for b in card_buttons(card)]
    check(urls == ["https://bradqui.github.io/ButlerBot/games/library/",
                   "https://bradqui.github.io/ButlerBot/reference/gamemanager/#games-own"], urls)
    await fmt.send_help(await ctx_for(alex), bot.get_command("games session"))
    check(card_buttons(channel.sent[-1])[0].url.endswith("/games/nights/"), "session links to game nights")
    await fmt.send_help(await ctx_for(alex), bot.get_command("games admin add"))
    check("-# Who: Game admins only" in card_text(channel.sent[-1]), card_text(channel.sent[-1])[:300])
    await fmt.send_help(await ctx_for(alex), bot.get_command("games"))
    text = card_text(channel.sent[-1])
    check("\n**Subcommands**\n`!games admin`\n-# Library management for game admins" in text
          and "admin setrole`) · game admins only\n" in text and len(text) <= 4000, "group card lists subcommands")
    check(re.search(r"-# Page 1 of \d+ · `!help <command>` for details$", text), "group footer: the page and one hint")
    rows = [i.content for i in channel.sent[-1].view.walk_children() if isinstance(i, discord.ui.TextDisplay)
            and i.content.startswith("`!games ")]
    check(len(rows) == 8 and all(r.count("\n") == 1 and r.split("\n")[1].startswith("-# ") for r in rows),
          "subcommands are two-line rows, 8 a page, each its own block")
    check(hb_mod.first_sentence("Add games you own. Separate several with commas.") == "Add games you own"
          and hb_mod.first_sentence("Ping everyone (e.g. raiders).") == "Ping everyone (e.g. raiders)"
          and len(hb_mod.first_sentence("word " * 60)) <= 100, "first sentence of the short help")
    # cog card and not found
    await fmt.send_help(await ctx_for(alex), "GameManager")
    cog_text = card_text(channel.sent[-1])
    check(cog_text.startswith("### 📖 Games\n") and "\n`!games`\n-# Your game library, play sessions, and votes on "
          "what to play\n" in cog_text, "cog card")
    footer = "-# " + hb_mod.HELP_FOOTER.format(p="!")
    check(cog_text.endswith(footer) and footer == "-# `!help <command>` for details", "cog card footer: one hint")
    await fmt.send_help(await ctx_for(alex), "Games")   # a cog's friendly name finds it too
    check(card_text(channel.sent[-1]).startswith("### 📖 Games\n"), "friendly name finds the cog")
    check(hb_mod.friendly_name(gm) == "Games" and hb_mod.friendly_name(cc) == "Custom commands"
          and hb_mod.friendly_name(alias) == "Alias" and hb_mod.friendly_name(bot.get_cog("Secret")) == "Secret",
          "friendly cog names")

    class SpeakUp(dcommands.Cog):
        pass

    class ClaudeChat(dcommands.Cog):
        pass
    check(hb_mod.friendly_name(SpeakUp()) == "Reminders and auto-replies"
          and hb_mod.friendly_name(ClaudeChat()) == "AI chat", "names from the handbook topic or the override")
    long_help = "Intro line.\n```\n" + "\n".join(f"code line {i}" for i in range(300)) + "\n```"
    fitted = hb_mod.fit(long_help, 1500)
    check(len(fitted) <= 1500 and fitted.count("```") % 2 == 0 and "code line 1" in fitted
          and not fitted.rstrip("`\n").endswith("code line"), "long help cut at a line, code block closed")
    await fmt.send_help(await ctx_for(alex), "gmaes")
    check(channel.sent[-1].content.startswith("❓ There's no command or category called `gmaes`. Did you mean "
                                              "`!help games`?\n-# Or ask me in plain English: `!butler gmaes`"),
          channel.sent[-1].content)
    await fmt.send_help(await ctx_for(alex), bot.get_command("shutdownish"))
    check(not any("reference" in b.url for b in card_buttons(channel.sent[-1])),
          "owner-only command gets no reference link")

    # Red's own check helpers, and Permissions default-deny rules
    def _can_manage_channel_deco(privilege_level=None):
        async def predicate(ctx):
            return privilege_level
        return predicate
    manage_check = _can_manage_channel_deco(privilege_level=PrivilegeLevel.ADMIN)
    cmd = bot.get_command("games list")
    cmd.checks.append(manage_check)
    label = hb_mod.requirement(cmd)
    check(label == ("admins, or anyone who can manage the channel", False), f"manage-channel check labeled: {label}")
    cmd.checks.remove(manage_check)

    class Rules:
        DEFAULT, GLOBAL = "default", 0

        def __init__(self, deny):
            self.deny = deny

        def get_rule(self, model, guild_id):
            return SimpleNamespace(name="ACTIVE_DENY" if self.deny and guild_id == 0 else "NORMAL")
    bot.get_cog("Secret").requires = Rules(deny=True)
    check(hb_mod.denied_by_default(bot.get_cog("Secret"), guild.id)
          and not hb_mod.denied_by_default(gm, guild.id), "default-deny detection")

    # !handbook
    ctx = await ctx_for(alex, "!handbook game nights")
    await bot.invoke(ctx)
    sent = channel.sent[-1]
    text = card_text(sent)
    check(text.startswith("### 📖 Game nights\nSessions, weekly game nights") and "http" not in text
          and card_buttons(sent)[0].url == "https://bradqui.github.io/ButlerBot/games/nights/", text)
    await bot.invoke(await ctx_for(alex, "!handbook voice"))
    check(card_buttons(channel.sent[-1])[0].url.endswith("/voice/"), card_text(channel.sent[-1]))
    await bot.invoke(await ctx_for(alex, "!handbook zzzqqq"))
    check("No handbook topic" in channel.sent[-1].content, "unknown topic")
    links = await hb.guide_links()
    check(("Voice rooms", "https://bradqui.github.io/ButlerBot/voice/", "Make your own temporary voice channel.") in links,
          "guide links")

    # export
    await cc.config.guild(guild).commands.set({"rules": {"response": "Read #rules | be nice"},
                                               "hype": {"response": ["a", "b"]}})
    await alias.config.guild(guild).entries.set([{"name": "own", "command": "games own"}])
    menu = discord.app_commands.ContextMenu(name="Summarize link", callback=_menu_cb)
    bot.tree.add_command(menu)
    pages = await hb.build_reference(guild, "!")
    idx = pages["reference/index.md"]
    check("## Right-click options" in idx and "| **Summarize link** | A three-line summary" in idx
          and "{{ '/speakup/' | relative_url }}" in idx and idx.index("## Right-click") < idx.index("## Commands"),
          "right-click options listed in the reference")
    bot.tree.remove_command("Summarize link", type=discord.AppCommandType.message)
    check({"reference/index.md", "reference/gamemanager.md", "reference/custom-commands.md"} <= set(pages), list(pages))
    gm_page = pages["reference/gamemanager.md"]
    check('<a id="games-own"></a>' in gm_page and "### !games own" in gm_page and "{% raw %}" in gm_page
          and "permalink: /reference/gamemanager/" in gm_page
          and "[Your games]({{ '/games/library/' | relative_url }})" in gm_page, gm_page[:400])
    check("reference/secret.md" not in pages and "shutdownish" not in "".join(pages.values()), "owner-only left out")
    custom = pages["reference/custom-commands.md"]
    check("| `!rules` | Read #rules / be nice |" in custom and "one of 2 random replies" in custom
          and "| `!own` | `!games own` |" in custom, custom)
    index = pages["reference/index.md"]
    check("[GameManager]({{ '/reference/gamemanager/' | relative_url }})" in index and "has_children: true" in index,
          index[:500])
    ctx = await ctx_for(brad, "!handbook export")
    await bot.invoke(ctx)
    file = channel.sent[-1].kw.get("file")
    names = zipfile.ZipFile(io.BytesIO(file.fp.read())).namelist() if file else []
    check("reference/gamemanager.md" in names, names)

    await bot.remove_cog("Handbook")
    check(not formatters, "help formatter reset on unload")
    for name in ("GameManager", "CustomCommands", "Alias", "Secret"):
        await bot.remove_cog(name)


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
