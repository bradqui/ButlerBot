"""
Handbook cog for Red-DiscordBot.

Replaces Red's `[p]help` with short, linked cards and points people at the online handbook (Markdown pages in the
repo's docs/ folder, published with GitHub Pages):

- `[p]help`: a card listing the handbook's topics, with links.
- `[p]help <command>` / `[p]help <category>`: one compact card (usage, who can use it, what it does, subcommands)
  with links to the matching handbook page and its entry in the command reference.
- `[p]handbook [topic]`: links to the handbook.
- `[p]handbook export` (bot owner): the full command reference, generated from the running bot, as Markdown files
  to commit under docs/reference/.

Only one cog can replace the help command: unload customhelp before loading this.
"""

import difflib
import importlib.util
import inspect
import io
import logging
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from discord.ext.commands.bot import BotBase
from redbot.core.commands.help import HelpFormatterABC

log = logging.getLogger("red.handbook")


def _load_butlerui():
    """The shared style module (../_shared/butlerui.py), re-read when the file changes."""
    path = Path(__file__).resolve().parent.parent / "_shared" / "butlerui.py"
    module, mtime = sys.modules.get("butlerui"), path.stat().st_mtime
    if module is None or getattr(module, "_mtime", None) != mtime:
        spec = importlib.util.spec_from_file_location("butlerui", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module._mtime = mtime
        sys.modules["butlerui"] = module
    return module


ui = _load_butlerui()

DEFAULT_URL = "https://bradqui.github.io/ButlerBot/"
PRIVILEGE_NAMES = {
    commands.PrivilegeLevel.MOD: "mod",
    commands.PrivilegeLevel.ADMIN: "admin",
    commands.PrivilegeLevel.GUILD_OWNER: "server owner",
    commands.PrivilegeLevel.BOT_OWNER: "bot owner",
}

# Handbook topics: (path under the site, emoji, title, one-line description, who it's for).
# Keep these in step with docs/: each path is a page's permalink.
TOPICS = [
    ("start/", "👋", "Getting started", "New here? Start with this.", "everyone"),
    ("butler/", "🤵", "Asking ButlerBot", "Ask in plain English, or have it run commands for you.", "everyone"),
    ("ai/", "🤖", "AI chat and images", "Chat with Claude, catch up on a channel, make images.", "everyone"),
    ("ai-use/", "🔍", "What uses AI", "Which features use AI, what they send, and what doesn't.", "everyone"),
    ("games/library/", "🎮", "Your games", "Your library, profile setup, favorites and wishlist.", "everyone"),
    ("games/nights/", "🎲", "Game nights", "Sessions, weekly game nights, votes and finding players.", "everyone"),
    ("fun/", "🎉", "Fun and games", "Parlor games, trivia, adventures, roasts and more.", "everyone"),
    ("stats/", "📊", "Server stats", "Who's active, busy times, voice and your own numbers.", "everyone"),
    ("speakup/", "🗣️", "Reminders and auto-replies", "Reminders, and what the bot does on its own.", "everyone"),
    ("voice/", "🔊", "Voice rooms", "Make your own temporary voice channel.", "everyone"),
    ("translate/", "🌐", "Translation", "Translate messages between languages.", "everyone"),
    ("moderation/", "🔨", "Moderation", "Warnings, mutes, kicks, bans and cleanup.", "mods"),
    ("filters/", "🛡️", "Filters and spam", "Word filters and spam protection.", "mods"),
    ("admin/", "⚙️", "Server setup", "Permissions, custom commands, welcome flow and cog settings.", "admins"),
    ("reference/", "📚", "Command reference", "Every command, generated from the bot.", "everyone"),
]
# Which handbook page covers a cog (by qualified name, lowercased). GameManager is split by command below.
COG_TOPICS = {
    "claudechat": "ai/", "geminichat": "ai/", "gamemanager": "games/library/", "parlor": "fun/",
    "trivia": "fun/", "general": "fun/", "chatchart": "stats/", "activitystats": "stats/", "speakup": "speakup/",
    "autoroom": "voice/", "easytranslate": "translate/", "mod": "moderation/", "mutes": "moderation/",
    "warnings": "moderation/", "modlog": "moderation/", "cleanup": "moderation/", "clearchannel": "moderation/",
    "filter": "filters/", "censord": "filters/", "antispam": "filters/", "permissions": "admin/", "alias": "admin/",
    "customcommands": "admin/", "buttongreeter": "admin/", "admin": "admin/",
}
# Names people know, for help cards (`[p]help <category>`). Cogs not listed here use their handbook topic's title
# when they're the only cog on that page, else their class name.
COG_NAMES = {
    "claudechat": "AI chat", "geminichat": "Image generation", "gamemanager": "Games", "parlor": "Parlor games",
    "activitystats": "Server stats", "chatchart": "Chat charts", "censord": "Word filter", "antispam": "Spam protection",
    "customcommands": "Custom commands", "buttongreeter": "Welcome flow", "modlog": "Mod log",
    "clearchannel": "Clear channel",
}
# The footer hint on help cards: one thing (the butler is the AI chat now, and the home card mentions it).
HELP_FOOTER = "`{p}help <command>` for details"
GAME_NIGHT_COMMANDS = {"session", "sessions", "join", "leave", "here", "endsession", "sessionvote", "results",
                       "endvote", "recurring", "lfg", "shared", "installed", "top"}
# Right-click options have no help text of their own: (description, handbook topic) for the reference.
CONTEXT_MENU_HELP = {
    "Summarize link": ("A three-line summary of the article linked in the message.", "speakup/"),
    "Translate": ("Translates the message into your language.", "translate/"),
}


# ==========================================
#                 HELPERS
# ==========================================

def requirement(command: commands.Command) -> Tuple[str, bool]:
    """
    (who can run it, whether it's bot-owner only), from the command's checks or the nearest parent's or cog's.
    Custom check functions can describe themselves with a `requirement` attribute (e.g. "game admin").
    Same rules as the Claude cog's bot guide.
    """
    chain = [command, *command.parents]
    if command.cog is not None:
        chain.append(command.cog)
    requires = [r for r in (getattr(obj, "requires", None) for obj in chain) if r is not None]
    if any(r.privilege_level is commands.PrivilegeLevel.BOT_OWNER for r in requires):
        return "bot owner only", True
    for obj in chain:
        r = getattr(obj, "requires", None)
        if r is not None:
            level = PRIVILEGE_NAMES.get(r.privilege_level)
            perms = [name.replace("_", " ") for name, value in (r.user_perms or discord.Permissions.none()) if value]
            if level and perms:
                return f"{level}s, or anyone with the {', '.join(perms)} permission", False
            if level:
                return f"{level}s only", False
            if perms:
                return f"anyone with the {', '.join(perms)} permission", False
        # Plain checks live on `.checks`; Red's overridable ones (permissions_check) on `.requires.checks`.
        all_checks = list(getattr(obj, "checks", None) or []) + list(getattr(r, "checks", None) or [] if r else [])
        for check in all_checks:
            label = getattr(check, "requirement", None)
            if label:
                return f"{label}s only", False
            known = known_check(check)
            if known is not None:
                return known
    return "everyone", False


def known_check(check) -> Optional[Tuple[str, bool]]:
    """Labels for Red's own check helpers that don't show up in `requires`."""
    name = getattr(check, "__qualname__", "")
    if "_can_manage_channel_deco" in name:
        try:
            level = inspect.getclosurevars(check).nonlocals.get("privilege_level")
        except (TypeError, ValueError):
            level = None
        who = PRIVILEGE_NAMES.get(level)
        return (f"{who}s, or anyone who can manage the channel" if who else "anyone who can manage the channel"), False
    if "_can_get_invite_url" in name:
        return "bot owner only (unless invites are made public)", True
    return None


def denied_by_default(obj, guild_id: int) -> bool:
    """True if a Permissions default rule denies this cog or command for everyone (globally or in this server)."""
    requires = getattr(obj, "requires", None)
    if requires is None or not hasattr(requires, "get_rule"):
        return False
    try:
        rules = (requires.get_rule(requires.DEFAULT, requires.GLOBAL), requires.get_rule(requires.DEFAULT, guild_id))
    except Exception:
        return False
    return any(getattr(rule, "name", "") == "ACTIVE_DENY" for rule in rules)


def friendly_name(cog: commands.Cog) -> str:
    """The name people know a cog by ("AI chat", not "ClaudeChat")."""
    key = cog.qualified_name.lower()
    if key in COG_NAMES:
        return COG_NAMES[key]
    topic = COG_TOPICS.get(key)
    if topic and list(COG_TOPICS.values()).count(topic) == 1:
        return next(title for path, _, title, _, _ in TOPICS if path == topic)
    return cog.qualified_name


def fit(text: str, limit: int) -> str:
    """Shorten card text at a line or word break, closing a code block the cut left open."""
    text = ui.truncate(text, limit - 4)
    return text + "\n```" if text.count("```") % 2 else text


def first_sentence(text: str, limit: int = 100) -> str:
    """The first sentence of a command's short help, without its full stop, for a row's detail line."""
    text = " ".join((text or "").split())
    text = re.split(r"(?<=[.!?])\s+(?=[A-Z`(\[])", text, maxsplit=1)[0]
    if text.endswith(".") and not text.endswith(".."):
        text = text[:-1]
    return ui.truncate(text, limit)


def who_text(who: str, aliases: List[str]) -> str:
    """A command card's detail line: who can use it, and its other names."""
    parts = [f"Who: {who[:1].upper() + who[1:]}"]
    if aliases:
        parts.append("Also: " + ", ".join(f"`{a}`" for a in aliases))
    return " · ".join(parts)


def anchor(command: commands.Command) -> str:
    return command.qualified_name.replace(" ", "-").lower()


def fill(text: Optional[str], prefix: str, bot_name: str) -> str:
    return (text or "").replace("[p]", prefix).replace("[botname]", bot_name).strip()


def usage(command: commands.Command, prefix: str) -> str:
    return f"{prefix}{command.qualified_name} {command.signature}".strip()


def visible_commands(cog_or_group) -> List[commands.Command]:
    """Top-level commands of a cog, or the subcommands of a group, without hidden ones."""
    if isinstance(cog_or_group, commands.Cog):
        cmds = cog_or_group.get_commands()
    else:
        cmds = getattr(cog_or_group, "commands", [])
    return sorted((c for c in cmds if not c.hidden), key=lambda c: c.name)


# ==========================================
#              HELP FORMATTER
# ==========================================

class HandbookHelp(HelpFormatterABC):
    """`[p]help` as short cards with handbook links."""

    def __init__(self, cog: "Handbook"):
        self.cog = cog

    async def send_help(self, ctx: commands.Context, help_for=None, *, from_help_command: bool = False):
        try:
            await self._send_help(ctx, help_for)
        except discord.HTTPException as e:
            # Usually Discord turning a card down (too long, say); a plain line may still get through.
            log.warning("Couldn't send help for %r: %s", help_for, e)
            try:
                await ctx.send("❌ Something went wrong showing help. The error was logged.")
            except discord.HTTPException:
                pass
        except Exception:
            log.exception("Help failed for %r", help_for)
            await ctx.send("❌ Something went wrong showing help. The error was logged.")

    async def _send_help(self, ctx: commands.Context, help_for):
        bot = ctx.bot
        if help_for is None or help_for is bot or isinstance(help_for, BotBase):
            return await self.cog.send_home(ctx)
        if isinstance(help_for, str):
            text = help_for.strip()
            if not text:
                return await self.cog.send_home(ctx)
            command = bot.get_command(text)
            if command is not None and (not command.hidden or await bot.is_owner(ctx.author)):
                return await self.cog.send_command_card(ctx, command)
            cog = next((c for name, c in bot.cogs.items()
                        if text.lower() in (name.lower(), friendly_name(c).lower())), None)
            if cog is not None:
                return await self.cog.send_cog_card(ctx, cog)
            return await self.cog.send_not_found(ctx, text)
        if isinstance(help_for, commands.Command):
            return await self.cog.send_command_card(ctx, help_for)
        if isinstance(help_for, commands.Cog):
            return await self.cog.send_cog_card(ctx, help_for)
        return await self.cog.send_home(ctx)


# ==========================================
#                   COG
# ==========================================

class Handbook(commands.Cog):
    """The online handbook, short help cards, and the generated command reference."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=3357204816, force_registration=True)
        self.config.register_global(url=DEFAULT_URL)
        self.formatter_active = False

    async def cog_load(self):
        try:
            self.bot.set_help_formatter(HandbookHelp(self))
            self.formatter_active = True
        except RuntimeError:
            log.warning("Another cog (probably customhelp) already replaced the help command. Unload it and reload "
                        "handbook to use the handbook's help cards.")

    async def cog_unload(self):
        if self.formatter_active:
            self.bot.reset_help_formatter()

    async def red_delete_data_for_user(self, **kwargs):
        return  # no user data

    # ---------- links ----------

    async def base_url(self) -> str:
        url = await self.config.url()
        return url if url.endswith("/") else url + "/"

    async def topic_url(self, path: str) -> str:
        return await self.base_url() + path

    def topic_for(self, command: Optional[commands.Command], cog: Optional[commands.Cog]) -> Optional[str]:
        cog = cog or (command.cog if command else None)
        if cog is None:
            return None
        name = cog.qualified_name.lower()
        if name == "gamemanager" and command is not None:
            parts = command.qualified_name.split()
            nights = parts[0] in ("session", "sessions") or (len(parts) > 1 and parts[1] in GAME_NIGHT_COMMANDS)
            return "games/nights/" if nights else "games/library/"
        return COG_TOPICS.get(name)

    async def reference_url(self, cog: Optional[commands.Cog], command: Optional[commands.Command] = None) -> str:
        slug = (cog.qualified_name.lower() if cog else "other")
        return await self.base_url() + f"reference/{slug}/" + (f"#{anchor(command)}" if command else "")

    async def guide_links(self) -> List[Tuple[str, str, str]]:
        """(title, url, description) for every topic, for the Claude cog's bot guide."""
        return [(title, await self.topic_url(path), about) for path, _, title, about, _ in TOPICS]

    def _link_buttons(self, links: List[Tuple[str, str]]) -> List[discord.ui.Button]:
        """Link buttons for inside a card (they just open the page)."""
        return [discord.ui.Button(label=label[:80], url=url) for label, url in links[:25]]

    def _bot_name(self, ctx: commands.Context) -> str:
        return ctx.me.display_name if ctx.guild else self.bot.user.name

    async def _send_card(self, ctx: commands.Context, *parts, title: str, links: List[Tuple[str, str]],
                         footer: Optional[str] = None):
        """One help card: the 📖 title, the parts, its link buttons inside, and a footer hint. Ping-free."""
        container = ui.card(*parts, self._link_buttons(links) or None, title=title, color=ui.BRAND,
                            footer=footer or HELP_FOOTER.format(p=ctx.clean_prefix))
        return await ui.send_card(ctx, ui.CardView(container))

    async def _send_board(self, ctx: commands.Context, header: Optional[str], rows: List[tuple], *, title: str,
                          links: List[Tuple[str, str]], empty: str = "No commands.", divider: bool = False):
        """
        A help card whose command rows page with ◀ ▶; the link buttons sit beside the arrows. Ping-free.
        `divider` puts a line between the header and the rows (the board's media slot, which every page repeats).
        The board keeps each page within the card's limit by itself, header included.
        """
        board = ui.Board(title, rows, color=ui.BRAND, header=header, footer=HELP_FOOTER.format(p=ctx.clean_prefix),
                         empty=empty, extra=self._link_buttons(links),
                         media=discord.ui.Separator() if divider else None)
        return await board.send(ctx)

    def _command_row(self, command: commands.Command, prefix: str, bot_name: str, who: Optional[str] = None) -> tuple:
        """A help board row: the command to type, then the first sentence of what it does (and who, if not all)."""
        detail = first_sentence(fill(command.short_doc, prefix, bot_name)) or "No description"
        if who:
            detail += f" · {who}"
        return ui.row(f"`{usage(command, prefix)}`", detail)

    # ---------- cards ----------

    async def _is_staff(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return await self.bot.is_owner(ctx.author)
        return (await self.bot.is_owner(ctx.author) or ctx.author.guild_permissions.manage_messages
                or await self.bot.is_mod(ctx.author) or await self.bot.is_admin(ctx.author))

    async def _topic_blocks(self, staff: bool) -> List[str]:
        """A block per topic (the linked title, what it covers underneath), for members or for mods and admins."""
        return [ui.two_line(f"{emoji} **[{title}]({await self.topic_url(path)})**", about)
                for path, emoji, title, about, audience in TOPICS if (audience != "everyone") == staff]

    async def send_home(self, ctx: commands.Context):
        p = ctx.clean_prefix
        intro = ui.two_line("Everything I can do, explained by task.",
                            f"Not sure what to type? Ask me: `{p}butler how do I…`")
        staff = []
        if await self._is_staff(ctx):
            staff = [ui.SEPARATOR, "**For mods and admins**", *await self._topic_blocks(staff=True)]
        await self._send_card(ctx, intro, ui.SEPARATOR, *await self._topic_blocks(staff=False), *staff,
                              title=f"📖 {self._bot_name(ctx)} handbook",
                              links=[("Open the handbook", await self.base_url()),
                                     ("Browse all commands", await self.topic_url("reference/"))])

    async def send_command_card(self, ctx: commands.Context, command: commands.Command):
        prefix, bot_name = ctx.clean_prefix, self._bot_name(ctx)
        who, owner_only = requirement(command)
        aliases = [f"{prefix}{(command.full_parent_name + ' ' + a).strip()}" for a in command.aliases]
        head = ui.two_line(f"`{usage(command, prefix)}`", who_text(who, aliases))
        text = fit(fill(command.help, prefix, bot_name), 1500) or "No description."
        links = []
        topic = self.topic_for(command, None)
        if topic:
            links.append(("Open handbook page", await self.topic_url(topic)))
        if not owner_only:
            links.append(("Open the reference", await self.reference_url(command.cog, command)))
        title = f"📖 {prefix}{command.qualified_name}"
        subs = visible_commands(command) if isinstance(command, commands.Group) else []
        if not subs:
            return await self._send_card(ctx, head, text, title=title, links=links,
                                         footer=self._related_hint(command, prefix))
        # A group's subcommands page with ◀ ▶ under the usage and description, which every page repeats. A
        # subcommand says who can use it only when that differs from the group.
        rows = []
        for sub in subs:
            sub_who = requirement(sub)[0]
            rows.append(self._command_row(sub, prefix, bot_name, None if sub_who in (who, "everyone") else sub_who))
        await self._send_board(ctx, f"{head}\n\n{text}\n\n**Subcommands**", rows, title=title, links=links)

    def _related_hint(self, command: commands.Command, prefix: str) -> str:
        """A single command's footer: where to find the commands around it."""
        if command.parent is not None:
            return f"`{prefix}help {command.parent.qualified_name}` for related commands"
        if command.cog is not None:
            return f"`{prefix}help {friendly_name(command.cog)}` for related commands"
        return HELP_FOOTER.format(p=prefix)

    async def send_cog_card(self, ctx: commands.Context, cog: commands.Cog):
        prefix, bot_name = ctx.clean_prefix, self._bot_name(ctx)
        about = fit(fill(getattr(cog, "help", None) or cog.description, prefix, bot_name), 600)
        rows = []
        for command in visible_commands(cog):
            who, owner_only = requirement(command)
            if owner_only and not await self.bot.is_owner(ctx.author):
                continue
            rows.append(self._command_row(command, prefix, bot_name, None if who == "everyone" else who))
        links = []
        topic = self.topic_for(None, cog)
        if topic:
            links.append(("Open handbook page", await self.topic_url(topic)))
        links.append(("Open the reference", await self.reference_url(cog)))
        # The commands page with ◀ ▶ under the category's description, which every page repeats.
        await self._send_board(ctx, about or None, rows, title=f"📖 {friendly_name(cog)}", links=links,
                               divider=bool(about))

    async def send_not_found(self, ctx: commands.Context, text: str):
        names = [c.qualified_name for c in self.bot.walk_commands() if not c.hidden] + list(self.bot.cogs)
        close = difflib.get_close_matches(text.lower(), [n.lower() for n in names], n=3, cutoff=0.6)
        hint = (" Did you mean " + ", ".join(f"`{ctx.clean_prefix}help {c}`" for c in close) + "?") if close else ""
        await ctx.send(ui.line(ui.ASK, f"There's no command or category called `{text[:80]}`.{hint}",
                               hint=f"Or ask me in plain English: `{ctx.clean_prefix}butler {text[:60]}`"),
                       allowed_mentions=ui.NO_PINGS)

    # ==========================================
    #                 COMMANDS
    # ==========================================

    @commands.group(name="handbook", aliases=["docs", "manual"], invoke_without_command=True)
    async def handbook(self, ctx: commands.Context, *, topic: str = None):
        """
        Links to the online handbook: every feature, explained by task.

        Name a topic for a direct link, like `[p]handbook game nights` or `[p]handbook voice`.
        """
        if not topic:
            return await self.send_home(ctx)
        wanted = topic.lower().strip()
        scored = []
        for path, emoji, title, about, _ in TOPICS:
            haystack = f"{title} {path} {about}".lower()
            score = 1.0 if wanted in haystack else difflib.SequenceMatcher(None, wanted, title.lower()).ratio()
            scored.append((score, path, emoji, title, about))
        score, path, emoji, title, about = max(scored)
        if score < 0.5:
            return await ctx.send(f"❓ No handbook topic matches **{topic[:60]}**. `{ctx.clean_prefix}handbook` lists "
                                  "them all.", allowed_mentions=ui.NO_PINGS)
        # The link is the button; the card just says what the page covers.
        await self._send_card(ctx, about, title=f"📖 {title}",
                              links=[("Open this page", await self.topic_url(path))])

    @handbook.command(name="seturl")
    @checks.is_owner()
    async def handbook_seturl(self, ctx: commands.Context, url: str):
        """Set where the handbook is published (bot owner)."""
        if not re.match(r"https?://", url):
            return await ctx.send("❌ That doesn't look like a web address.")
        await self.config.url.set(url if url.endswith("/") else url + "/")
        await ctx.send(f"✅ Handbook links now point to <{await self.base_url()}>.")

    @handbook.command(name="status")
    @checks.is_owner()
    async def handbook_status(self, ctx: commands.Context):
        """Whether the handbook's help cards are active (bot owner)."""
        if self.formatter_active:
            return await ctx.send(f"✅ `{ctx.clean_prefix}help` shows the handbook's cards. Links go to "
                                  f"<{await self.base_url()}>.")
        await ctx.send(f"⚠️ Another cog replaced the help command first. Run `{ctx.clean_prefix}unload customhelp`, "
                       f"then `{ctx.clean_prefix}reload handbook`.")

    @handbook.command(name="export")
    @checks.is_owner()
    @commands.guild_only()
    async def handbook_export(self, ctx: commands.Context):
        """
        Generate the command reference from the running bot, as Markdown files for docs/reference/ (bot owner).

        Covers every cog and command enabled in this server, except bot-owner-only ones, plus this server's custom
        commands and aliases. Re-run it after adding or updating cogs.
        """
        async with ctx.channel.typing():
            files = await self.build_reference(ctx.guild, ctx.clean_prefix)
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for path, text in files.items():
                    archive.writestr(path, text)
            buffer.seek(0)
        await ctx.send(f"✅ Generated {ui.plural(len(files), 'reference page')}. Unzip them into the repo's `docs/` "
                       "folder (they go in `docs/reference/`), commit and push.",
                       file=discord.File(buffer, filename="handbook-reference.zip"))

    # ==========================================
    #           GENERATED REFERENCE
    # ==========================================

    async def build_reference(self, guild: discord.Guild, prefix: str) -> Dict[str, str]:
        """{path: markdown} for docs/reference/: an index, one page per cog, and custom commands and aliases."""
        bot_name = guild.me.display_name
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        pages: Dict[str, str] = {}
        index_rows = []
        cogs = sorted(self.bot.cogs.values(), key=lambda c: c.qualified_name.lower())
        for order, cog in enumerate(cogs, 1):
            if await self.bot.cog_disabled_in_guild(cog, guild) or denied_by_default(cog, guild.id):
                continue
            entries = []
            for command in sorted(cog.walk_commands(), key=lambda c: c.qualified_name):
                if command.hidden or any(p.hidden for p in command.parents) or not command.enabled:
                    continue
                if any(denied_by_default(c, guild.id) for c in (command, *command.parents)):
                    continue   # locked down with a Permissions rule: not something members can use
                who, owner_only = requirement(command)
                if owner_only:
                    continue
                entries.append(self._reference_entry(command, who, prefix, bot_name))
            if not entries:
                continue
            slug = cog.qualified_name.lower()
            about = fill(getattr(cog, "help", None) or cog.description, prefix, bot_name)
            topic = self.topic_for(None, cog)
            guide = (f"\n\nFor a task-by-task guide, see [{next(t for p, _, t, _, _ in TOPICS if p == topic)}]"
                     f"({{{{ '/{topic}' | relative_url }}}}).") if topic else ""
            pages[f"reference/{slug}.md"] = "\n".join([
                "---", f"title: {cog.qualified_name}", "parent: Command reference", f"nav_order: {order}",
                f"permalink: /reference/{slug}/", "---", "",
                f"# {cog.qualified_name}", "", about + guide, "",
                "{% raw %}", *entries, "{% endraw %}", "",
            ])
            first_line = (about.splitlines() or [""])[0]
            index_rows.append(f"| [{cog.qualified_name}]({{{{ '/reference/{slug}/' | relative_url }}}}) | "
                              f"{first_line.replace('|', '/')[:150]} | {len(entries)} |")
        custom = await self._custom_commands_page(guild, prefix)
        if custom:
            pages["reference/custom-commands.md"] = custom
            index_rows.append("| [Server custom commands and aliases]({{ '/reference/custom-commands/' | relative_url }})"
                              " | Commands made by this server's admins | |")
        pages["reference/index.md"] = "\n".join([
            "---", "title: Command reference", "nav_order: 90", "has_children: true", "permalink: /reference/", "---",
            "", "# Command reference", "",
            f"Every command {bot_name} has, generated from the running bot on {generated}. Commands only the bot "
            "owner can use are left out. For explanations by task, start from the [home page]({{ '/' | relative_url }}).",
            "", f"In Discord, `{prefix}help <command>` shows the same details for one command.", "",
            *self._context_menu_section(),
            "## Commands", "",
            "| Category | What it's for | Commands |", "|---|---|---|", *index_rows, "",
        ])
        return pages

    def _context_menu_section(self) -> List[str]:
        """Right-click (Apps) options registered with the bot, for the reference index."""
        menus = sorted({c.name for kind in (discord.AppCommandType.message, discord.AppCommandType.user)
                        for c in self.bot.tree.get_commands(type=kind)})
        if not menus:
            return []
        rows = []
        for name in menus:
            about, topic = CONTEXT_MENU_HELP.get(name, ("", None))
            link = f" See [{next(t for p, _, t, _, _ in TOPICS if p == topic)}]({{{{ '/{topic}' | relative_url }}}})." \
                if topic else ""
            rows.append(f"| **{name}** | {about}{link} |")
        return ["## Right-click options", "", "Right-click a message (long-press on mobile) → **Apps**. Only you see "
                "the result.", "", "| Option | What it does |", "|---|---|", *rows, ""]

    def _reference_entry(self, command: commands.Command, who: str, prefix: str, bot_name: str) -> str:
        lines = [f'<a id="{anchor(command)}"></a>', f"### {prefix}{command.qualified_name}", "",
                 f"`{usage(command, prefix)}`", ""]
        meta = [f"**Who:** {who}"]
        if command.aliases:
            meta.append("**Also:** " + ", ".join(f"`{prefix}{(command.full_parent_name + ' ' + a).strip()}`"
                                                 for a in command.aliases))
        lines += [" · ".join(meta), ""]
        body = fill(command.help, prefix, bot_name)
        if body:
            lines += [body, ""]
        return "\n".join(lines)

    async def _custom_commands_page(self, guild: discord.Guild, prefix: str) -> Optional[str]:
        lines = []
        cc = self.bot.get_cog("CustomCommands")
        if cc is not None:
            try:
                stored = await cc.config.guild(guild).commands()
            except Exception:
                stored = {}
            rows = []
            for name, data in sorted((stored or {}).items()):
                if not data:
                    continue
                response = data.get("response") if isinstance(data, dict) else data
                if isinstance(response, list):
                    preview = f"one of {len(response)} random replies"
                else:
                    preview = str(response or "").replace("\n", " ").replace("|", "/")
                    preview = preview[:120] + ("…" if len(preview) > 120 else "")
                rows.append(f"| `{prefix}{name}` | {preview} |")
            if rows:
                lines += ["## Custom commands", "", "Made by this server's admins with the CustomCommands cog.", "",
                          "| Command | Reply |", "|---|---|", *rows, ""]
        alias = self.bot.get_cog("Alias")
        if alias is not None:
            entries = []
            for getter in ("guild", "global"):
                try:
                    conf = alias.config.guild(guild) if getter == "guild" else alias.config
                    entries += [(getter, e) for e in await conf.entries()]
                except Exception:
                    continue
            rows = [f"| `{prefix}{e.get('name')}` | `{prefix}{e.get('command')}` |" for _, e in
                    sorted(entries, key=lambda x: str(x[1].get("name"))) if isinstance(e, dict) and e.get("name")]
            if rows:
                lines += ["## Aliases", "", "Shortcuts for longer commands, made with the Alias cog.", "",
                          "| Type this | It runs |", "|---|---|", *rows, ""]
        if not lines:
            return None
        return "\n".join(["---", "title: Custom commands", "parent: Command reference", "nav_order: 999",
                          "permalink: /reference/custom-commands/", "---", "", "# Custom commands and aliases", "",
                          "{% raw %}", *lines, "{% endraw %}", ""])
