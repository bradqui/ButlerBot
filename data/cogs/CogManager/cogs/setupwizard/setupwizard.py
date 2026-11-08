"""
Setup wizard cog for Red-DiscordBot.

`[p]setup` posts a small launcher card; its **Open setup** button opens a private wizard for the server's admins.
Each step shows what's set now and changes it with Discord's own pickers. Changes are made by running the server's
own commands as the admin (`run`), with their replies captured into the wizard instead of the channel, so every
command keeps its own checks, validation and caches. Voice rooms are the exception: AutoRoom's `create` asks its
questions in chat, so the wizard saves an AutoRoom source the way that command does.

Steps read the other cogs' settings to show their state, and skip themselves when their cog isn't loaded.
"""

import importlib.util
import logging
import sys
from copy import copy
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red


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
log = logging.getLogger("red.setupwizard")

# ==========================================
#                CONSTANTS
# ==========================================

TOPIC = "⚙️"
WIZARD_TIMEOUT = 840            # private menus die with their 15-minute interaction token; stop a little sooner

# (key, title, the cog it needs or None)
STEPS = [
    ("perms", "Permissions", None),
    ("staff", "Staff roles", None),
    ("welcome", "Welcome flow", "ButtonGreeter"),
    ("games", "Game nights", "GameManager"),
    ("ai", "AI chat", "ClaudeChat"),
    ("voice", "Voice rooms", "AutoRoom"),
    ("replies", "Auto-replies", "SpeakUp"),
    ("stats", "Stats", "ActivityStats"),
    ("moderation", "Moderation", None),
    ("fun", "Weekly games", "Parlor"),
    ("apps", "Slash commands", None),
]

# What each server permission is for. The first group is needed everywhere.
PERMISSIONS = [
    (("view_channel", "send_messages", "embed_links", "attach_files", "read_message_history", "add_reactions"),
     "everything: replies, cards, charts, calendar files and reactions"),
    (("create_public_threads", "send_messages_in_threads"), "game threads (guessing games, adventures, mysteries)"),
    (("manage_events",), "Discord events for game nights"),
    (("manage_roles", "manage_nicknames"), "the welcome flow's roles and [TAG] nicknames"),
    (("manage_messages",), "the word filter and cleanup"),
    (("kick_members", "ban_members"), "moderation and the word filter's kick and ban"),
    (("manage_channels", "move_members"), "voice rooms"),
]
PERMISSION_NAMES = {
    "view_channel": "View Channels", "send_messages": "Send Messages", "embed_links": "Embed Links",
    "attach_files": "Attach Files", "read_message_history": "Read Message History", "add_reactions": "Add Reactions",
    "create_public_threads": "Create Public Threads", "send_messages_in_threads": "Send Messages in Threads",
    "manage_events": "Manage Events", "manage_roles": "Manage Roles", "manage_nicknames": "Manage Nicknames",
    "manage_messages": "Manage Messages", "kick_members": "Kick Members", "ban_members": "Ban Members",
    "manage_channels": "Manage Channels", "move_members": "Move Members",
}

FALLBACK_TIMEZONES = [
    ("US Eastern (New York)", "America/New_York"), ("US Central (Chicago)", "America/Chicago"),
    ("US Mountain (Denver)", "America/Denver"), ("US Pacific (Los Angeles)", "America/Los_Angeles"),
    ("UK (London)", "Europe/London"), ("Central Europe (Paris, Berlin)", "Europe/Paris"),
    ("Australia East (Sydney)", "Australia/Sydney"), ("UTC", "UTC"),
]
DAILY_LIMITS = [0, 10, 20, 30, 50, 100]
SPEAKUP_FEATURES = [("times", "Times"), ("steam", "Steam cards"), ("links", "Link summaries"),
                    ("mistakes", "Typo help")]
ROOM_TYPES = [("public", "Public", "Anyone can see and join; the owner can kick people."),
              ("locked", "Locked", "Visible, but the owner lets people in."),
              ("private", "Private", "Hidden; the owner lets people in."),
              ("server", "Server", "Public, with no owner and no changes.")]
ROOM_NAMES = [("username", "Owner's name", "“Alex's Room”"),
              ("game", "Owner's game", "The game they're playing, else their name")]
ANTISPAM_PRESETS = {   # name: (commands, seconds, timeout seconds, description)
    "relaxed": (8, 10, 120, "8 commands in 10 seconds, then a 2-minute break"),
    "normal": (5, 5, 300, "5 commands in 5 seconds, then a 5-minute break"),
    "strict": (4, 10, 900, "4 commands in 10 seconds, then a 15-minute break"),
}
# (name, kind, the cog that provides it, how it's shown)
APP_COMMANDS = [
    ("games", "slash", "GameManager", "/games"),
    ("catchup", "slash", "ClaudeChat", "/catchup"),
    ("Summarize link", "message", "SpeakUp", "Summarize link (right-click)"),
    ("Translate", "message", "EasyTranslate", "Translate (right-click)"),
    ("translate", "slash", "EasyTranslate", "/translate"),
    ("setmylanguage", "slash", "EasyTranslate", "/setmylanguage"),
]
VOICE_CATEGORY = "Voice rooms"
VOICE_SOURCE = "➕ Join to create"


# ==========================================
#           RUNNING COMMANDS PRIVATELY
# ==========================================

class QuietMessage(discord.Message):
    """The admin's message, re-sent as a command: reactions (`ctx.tick()`) go nowhere, so nothing shows in the channel."""
    __slots__ = ()

    async def add_reaction(self, emoji):
        return None


class CapturedMessage:
    """What a captured `ctx.send` returns: commands that edit their reply later (progress lines) edit this instead."""

    def __init__(self, captured: "Captured", index: int):
        self.captured, self.index, self.id = captured, index, 0
        self.jump_url = ""

    async def edit(self, *, content=None, **kwargs):
        text = self.captured.text_of(content, kwargs)
        if text and self.index < len(self.captured.lines):
            self.captured.lines[self.index] = text

    async def delete(self, **kwargs):
        return None

    async def add_reaction(self, emoji):
        return None


class Captured:
    """Stands in for a command's replies so they show inside the wizard (as text) instead of in the channel."""

    def __init__(self):
        self.lines: List[str] = []

    @staticmethod
    def text_of(content, kwargs) -> str:
        text = str(content) if content else ""
        embed = kwargs.get("embed") or next(iter(kwargs.get("embeds") or []), None)
        if not text and embed is not None:
            text = embed.description or embed.title or ""
        view = kwargs.get("view")
        if not text and view is not None and hasattr(view, "walk_children"):
            text = "\n".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))
        return text.strip()

    async def send(self, content=None, **kwargs):
        text = self.text_of(content, kwargs)
        if text:
            self.lines.append(text)
        return CapturedMessage(self, len(self.lines) - 1)

    async def reply(self, content=None, **kwargs):
        return await self.send(content, **kwargs)


def channel_value(value: Optional[int]) -> str:
    return f"<#{value}>" if value else "not set"


def role_value(value: Optional[int]) -> str:
    return f"<@&{value}>" if value else "not set"


# ==========================================
#            PERSISTENT LAUNCHER
# ==========================================

class OpenButton(discord.ui.DynamicItem[discord.ui.Button], template=r"sw:open"):
    """The launcher card's button: opens the private wizard for whoever presses it (admins only)."""

    def __init__(self):
        super().__init__(discord.ui.Button(label="Open setup", emoji=TOPIC, style=discord.ButtonStyle.primary,
                                           custom_id="sw:open"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("SetupWizard")
        if cog is not None and interaction.guild is not None:
            await cog.open_wizard(interaction)


# ==========================================
#                THE WIZARD
# ==========================================

class LabelModal(discord.ui.Modal, title="Group button"):
    """The label for a new welcome group button (also the [TAG] in nicknames)."""

    def __init__(self, wizard: "Wizard", role: discord.Role):
        super().__init__()
        self.wizard, self.role = wizard, role
        self.label = discord.ui.TextInput(label="Button label (the nickname tag)", default=role.name[:40],
                                          max_length=40)
        self.add_item(self.label)

    async def on_submit(self, interaction: discord.Interaction):
        label = " ".join(str(self.label.value).split())
        await self.wizard.act(interaction, [f"bg addrole {self.role.id} {label}"])


class Wizard(ui.ExpiringCard):
    """
    The private setup menu: a home card listing every step with its status, and one card per step with pickers.
    Every change runs the server's own command as the admin; its reply shows at the top of the card.
    """

    expired_note = "Expired. Run the setup command again to carry on."

    def __init__(self, cog: "SetupWizard", member: discord.Member, base: discord.Message):
        super().__init__(member.id, timeout=WIZARD_TIMEOUT)
        self.cog, self.member, self.guild, self.base = cog, member, member.guild, base
        self.page: Optional[str] = None   # None = the overview
        self.note: Optional[str] = None   # the last change's result
        self.voice: Dict[str, Optional[object]] = {"source": None, "category": None, "type": "public",
                                                   "names": "username"}

    # ---------- navigation ----------

    def steps(self) -> List[Tuple[str, str]]:
        return [(key, title) for key, title, needs in STEPS if needs is None or self.cog.bot.get_cog(needs)]

    async def show(self, interaction: discord.Interaction, *, edit: bool = True):
        """Draw the current page; edit the message the interaction came from (or answer it with the wizard)."""
        if self.page is not None:
            await self.cog.mark_visited(self.guild, self.page)
        self.clear_items()
        self.add_item(await self.render())
        if not edit:
            await interaction.response.send_message(view=self, ephemeral=True, allowed_mentions=ui.NO_PINGS)
            self.message = interaction
        elif interaction.response.is_done():
            await interaction.edit_original_response(view=self, allowed_mentions=ui.NO_PINGS)
        else:
            await interaction.response.edit_message(view=self, allowed_mentions=ui.NO_PINGS)

    def go(self, page: Optional[str]) -> Callable[[discord.Interaction], Awaitable[None]]:
        async def callback(interaction: discord.Interaction):
            self.page, self.note = page, None
            await self.show(interaction)
        return callback

    async def act(self, interaction: discord.Interaction, lines: List[str]):
        """Run commands as the admin and show what they said."""
        if not interaction.response.is_done():
            await interaction.response.defer()
        self.note = await self.cog.run(self.member, self.base, lines) if lines else None
        await self.show(interaction)

    def button(self, label: str, callback, *, emoji=None, style=discord.ButtonStyle.secondary,
               disabled: bool = False) -> discord.ui.Button:
        b = discord.ui.Button(label=label, emoji=emoji, style=style, disabled=disabled)
        b.callback = callback
        return b

    def nav(self) -> List[discord.ui.Button]:
        keys = [k for k, _ in self.steps()]
        at = keys.index(self.page) if self.page in keys else -1
        back = keys[at - 1] if at > 0 else None
        nxt = keys[at + 1] if 0 <= at < len(keys) - 1 else None
        return [self.button("Back", self.go(back)),
                self.button("Next", self.go(nxt), style=discord.ButtonStyle.primary) if nxt
                else self.button("Finish", self.go(None), style=discord.ButtonStyle.primary),
                self.button("All steps", self.go(None))]

    @staticmethod
    def values(interaction: discord.Interaction) -> List[int]:
        """The IDs picked in a select menu (read from the interaction, so it works however the menu was built)."""
        return [int(v) for v in ((getattr(interaction, "data", None) or {}).get("values") or []) if str(v).isdigit()]

    def channel_select(self, placeholder: str, callback, *, current=(), kinds=(discord.ChannelType.text,),
                       optional: bool = False, many: bool = False) -> discord.ui.ChannelSelect:
        defaults = [discord.Object(id=c) for c in current if c]
        select = discord.ui.ChannelSelect(placeholder=placeholder, channel_types=list(kinds),
                                          min_values=0 if optional else 1, max_values=25 if many else 1,
                                          default_values=defaults[:25 if many else 1])
        select.callback = callback
        return select

    def role_select(self, placeholder: str, callback, *, current=(), optional: bool = False,
                    many: bool = False) -> discord.ui.RoleSelect:
        defaults = [discord.Object(id=r) for r in current if r]
        select = discord.ui.RoleSelect(placeholder=placeholder, min_values=0 if optional else 1,
                                       max_values=10 if many else 1, default_values=defaults[:10 if many else 1])
        select.callback = callback
        return select

    def choice_select(self, placeholder: str, options: List[Tuple[str, str, Optional[str]]], current: Optional[str],
                      callback) -> discord.ui.Select:
        select = discord.ui.Select(placeholder=placeholder, options=[
            discord.SelectOption(label=label[:100], value=value, description=(desc or None) and desc[:100],
                                 default=value == current) for value, label, desc in options][:25])

        async def chosen(interaction: discord.Interaction):
            picked = ((getattr(interaction, "data", None) or {}).get("values") or [None])[0]
            await callback(interaction, picked)
        select.callback = chosen
        return select

    @staticmethod
    def toggle(on: bool) -> str:
        return "☑️" if on else "⬜"

    # ---------- pages ----------

    async def render(self) -> discord.ui.Container:
        if self.page is None:
            return await self.overview()
        title = dict((k, t) for k, t, _ in STEPS)[self.page]
        keys = [k for k, _ in self.steps()]
        number = f" ({keys.index(self.page) + 1} of {len(keys)})" if self.page in keys else ""
        parts = [ui.hint(self.note)] if self.note else []
        parts += await getattr(self, f"page_{self.page}")()
        parts += [ui.SEPARATOR, self.nav()]
        return ui.card(*parts, title=f"{TOPIC} Setup: {title}{number}", footer="Only you can see this")

    async def overview(self) -> discord.ui.Container:
        rows = []
        for key, title in self.steps():
            symbol, detail = await self.cog.status(self.guild, key)
            rows.append(ui.two_line(f"**{title}**" + (f" {symbol}" if symbol else ""), detail))
        start = await self.cog.next_step(self.guild, [k for k, _ in self.steps()])
        begun = bool(await self.cog.config.guild(self.guild).visited())
        menu = self.choice_select("Go to a step…", [(k, t, None) for k, t in self.steps()], None,
                                  lambda i, key: self.go(key)(i))
        return ui.card("Set ButlerBot up for this server. Every step is optional, and you can come back any time.",
                       *rows, ui.SEPARATOR, [menu],
                       [self.button("Carry on" if begun else "Start", self.go(start),
                                    style=discord.ButtonStyle.primary)],
                       title=f"{TOPIC} Server setup", footer="✅ set up · ⚠️ needs a look · Only you can see this")

    async def page_perms(self) -> list:
        missing = self.cog.missing_permissions(self.guild)
        if not missing:
            body = ui.line(ui.DONE, "ButlerBot has every permission it uses.")
        else:
            body = "\n".join(ui.two_line(f"**{', '.join(PERMISSION_NAMES[p] for p in perms)}**", f"For {what}")
                             for perms, what in missing)
            body = (ui.line(ui.WARN, "ButlerBot's role is missing some permissions:") + "\n\n" + body + "\n\n"
                    + ui.hint("Give them to ButlerBot's role in Server Settings → Roles, then check again."))
        warnings = await self.cog.role_order_problems(self.guild)
        return [body, *(ui.line(ui.WARN, w) for w in warnings),
                [self.button("Check again", self.go("perms"))]]

    async def page_staff(self) -> list:
        bot, guild = self.cog.bot, self.guild
        mods = [r.id for r in await bot.get_mod_roles(guild)] if hasattr(bot, "get_mod_roles") else []
        admins = [r.id for r in await bot.get_admin_roles(guild)] if hasattr(bot, "get_admin_roles") else []
        owner = guild.owner_id == self.member.id or await bot.is_owner(self.member)
        gm = bot.get_cog("GameManager")
        game_admin = await gm.config.guild(guild).admin_role() if gm else None
        rows = [("Mod roles", ", ".join(f"<@&{r}>" for r in mods) or "none"),
                ("Admin roles", ", ".join(f"<@&{r}>" for r in admins) or "none")]
        if gm:
            rows.append(("Game admin role", role_value(game_admin)))

        async def set_roles(interaction, kind: str, current: List[int]):
            picked = self.values(interaction)
            lines = [f"set roles add{kind}role {r}" for r in picked if r not in current]
            lines += [f"set roles remove{kind}role {r}" for r in current if r not in picked]
            await self.act(interaction, lines)

        async def mods_picked(interaction):
            await set_roles(interaction, "mod", mods)

        async def admins_picked(interaction):
            await set_roles(interaction, "admin", admins)

        async def game_admin_picked(interaction):
            picked = self.values(interaction)
            await self.act(interaction, [f"games admin setrole {picked[0]}" if picked else "games admin setrole"])

        parts = [ui.settings_text(rows),
                 ui.hint("Mods can moderate and run mod commands; admins can do that and change settings. "
                         "Game admins approve games and run any game night.")]
        if owner:
            parts += [[self.role_select("Mod roles…", mods_picked, current=mods, optional=True, many=True)],
                      [self.role_select("Admin roles…", admins_picked, current=admins, optional=True, many=True)]]
        else:
            parts.append(ui.line(ui.LOCKED, "Only the server owner can change mod and admin roles."))
        if gm:
            parts.append([self.role_select("Game admin role…", game_admin_picked, current=[game_admin],
                                           optional=True)])
        return parts

    async def page_welcome(self) -> list:
        conf = await self.cog.bot.get_cog("ButtonGreeter").config.guild(self.guild).all()
        groups = ", ".join(f"{label} (<@&{rid}>)" for label, rid in conf["roles"].items()) or "none yet"
        rows = [("Greeting channel", channel_value(conf["welcome_channel"])),
                ("Group buttons", groups),
                ("Rules channel", channel_value(conf["rules_channel"])),
                ("Rules role", role_value(conf["rules_role"])),
                ("Problems reported in", channel_value(conf["admin_channel"]))]

        def one(command: str):
            async def callback(interaction):
                picked = self.values(interaction)
                await self.act(interaction, [f"{command} {picked[0]}"] if picked else [])
            return callback

        async def group_picked(interaction):
            picked = self.values(interaction)
            role = self.guild.get_role(picked[0]) if picked else None
            if role is None:
                return await self.act(interaction, [])
            await interaction.response.send_modal(LabelModal(self, role))

        return [ui.settings_text(rows),
                ui.hint("Newcomers pick a group (its role, and a [TAG] nickname), then agree to the rules. "
                        "Remove a group with the bg removerole command."),
                [self.channel_select("Greeting channel…", one("bg setchannel"),
                                     current=[conf["welcome_channel"]])],
                [self.role_select("Add a group button…", group_picked)],
                [self.channel_select("Rules channel…", one("bg setruleschannel"), current=[conf["rules_channel"]])],
                [self.role_select("Rules role…", one("bg setrulesrole"), current=[conf["rules_role"]])],
                [self.channel_select("Report problems in…", one("bg setadminchannel"),
                                     current=[conf["admin_channel"]])]]

    async def page_games(self) -> list:
        gm = self.cog.bot.get_cog("GameManager")
        conf = await gm.config.guild(self.guild).all()
        module = sys.modules.get(type(gm).__module__)
        zones = list(getattr(module, "COMMON_TIMEZONES", FALLBACK_TIMEZONES))
        if conf["timezone"] and conf["timezone"] not in [z for _, z in zones]:
            zones.insert(0, (conf["timezone"], conf["timezone"]))
        rows = [("Timezone", conf["timezone"] or "UTC (not set)"),
                ("Sale alerts", channel_value(conf["sale_channel"]) if conf["sale_channel"] else "off"),
                ("Discord events", conf["events"]),
                ("Events in voice channel", channel_value(conf["event_channel"]) if conf["event_channel"]
                 else "no (external events)"),
                ("Free Epic games", conf["free_games"]),
                ("Members add games", conf["member_add"])]

        async def zone_picked(interaction, zone):
            await self.act(interaction, [f"games admin timezone {zone}"] if zone else [])

        async def sales_picked(interaction):
            picked = self.values(interaction)
            await self.act(interaction, [f"games admin sales {picked[0]}" if picked else "games admin sales"])

        async def voice_picked(interaction):
            picked = self.values(interaction)
            await self.act(interaction, [f"games admin eventchannel {picked[0]}" if picked
                                         else "games admin eventchannel"])

        def flip(command: str, on: bool):
            async def callback(interaction):
                await self.act(interaction, [f"{command} {'false' if on else 'true'}"])
            return callback

        return [ui.settings_text(rows),
                ui.hint("Session times people type are read in their own timezone, else this one. Sale alerts "
                        "ping people when a game on their wishlist goes on sale."),
                [self.choice_select("Server timezone…", [(z, label, z) for label, z in zones], conf["timezone"],
                                    zone_picked)],
                [self.channel_select("Sale alerts channel (clear to turn off)…", sales_picked,
                                     current=[conf["sale_channel"]], optional=True)],
                [self.channel_select("Voice channel for events (optional)…", voice_picked,
                                     current=[conf["event_channel"]], kinds=(discord.ChannelType.voice,),
                                     optional=True)],
                [self.button("Discord events", flip("games admin events", conf["events"]),
                             emoji=self.toggle(conf["events"])),
                 self.button("Free Epic games", flip("games admin freegames", conf["free_games"]),
                             emoji=self.toggle(conf["free_games"]), disabled=not conf["sale_channel"]),
                 self.button("Members add games", flip("games admin memberadd", conf["member_add"]),
                             emoji=self.toggle(conf["member_add"]))]]

    async def page_ai(self) -> list:
        cc = self.cog.bot.get_cog("ClaudeChat")
        conf = await cc.config.guild(self.guild).all()
        persona = ("the server's own" if conf["persona"] else "the server's saved default" if conf["default_persona"]
                   else "ButlerBot's own")
        rows = [("@mentions reach the AI", conf["guide_mentions"]),
                ("AI can run commands for people", conf["guide_actions"]),
                ("Web search", conf["web_search"]),
                ("Daily limit per member", f"{conf['daily_limit']} AI messages" if conf["daily_limit"] else "none"),
                ("Personality", persona)]

        def flip(command: str, on: bool):
            async def callback(interaction):
                await self.act(interaction, [f"{command} {'off' if on else 'on'}"])
            return callback

        async def limit_picked(interaction, value):
            await self.act(interaction, [f"claude limit {value}"] if value is not None else [])

        async def persona_reset(interaction):
            await self.act(interaction, ["claude persona reset"])

        limits = [(str(n), f"{n} a day" if n else "No limit", "Mods and admins aren't limited" if n else None)
                  for n in DAILY_LIMITS]
        parts = [ui.settings_text(rows),
                 ui.hint("Change the personality with the claude persona command; the bot owner can set a "
                         "monthly budget."),
                 [self.button("@mentions", flip("claude guidementions", conf["guide_mentions"]),
                              emoji=self.toggle(conf["guide_mentions"])),
                  self.button("Runs commands", flip("claude guideactions", conf["guide_actions"]),
                              emoji=self.toggle(conf["guide_actions"])),
                  self.button("Web search", flip("claude websearch", conf["web_search"]),
                              emoji=self.toggle(conf["web_search"]))],
                 [self.choice_select("Daily limit per member…", limits, str(conf["daily_limit"]), limit_picked)]]
        if conf["persona"]:
            parts.append([self.button("Use the default personality", persona_reset)])
        return parts

    async def page_voice(self) -> list:
        ar = self.cog.bot.get_cog("AutoRoom")
        sources = await self.cog.autoroom_sources(self.guild)
        listed = "\n".join(ui.two_line(f"<#{cid}>", f"Rooms go in <#{data.get('dest_category_id')}> · "
                                                    f"{data.get('room_type', 'public')}")
                           for cid, data in sources.items()) or "None yet."
        draft = self.voice
        source = self.guild.get_channel(draft["source"] or 0)
        category = self.guild.get_channel(draft["category"] or 0)

        def pick(key: str):
            async def callback(interaction):
                picked = self.values(interaction)
                draft[key] = picked[0] if picked else None
                await self.act(interaction, [])
            return callback

        async def kind_picked(interaction, value):
            draft["type"] = value or draft["type"]
            await self.act(interaction, [])

        async def names_picked(interaction, value):
            draft["names"] = value or draft["names"]
            await self.act(interaction, [])

        async def make(interaction):
            await interaction.response.defer()
            self.note = await self.cog.make_voice_channels(self.guild, draft)
            await self.show(interaction)

        async def save(interaction):
            await interaction.response.defer()
            self.note = await self.cog.save_autoroom(self.guild, draft)
            await self.show(interaction)

        return [ui.two_line("**Voice rooms now**", None), listed,
                ui.hint("Joining a “join to create” channel makes a temporary voice room for that person, which "
                        "goes away when it's empty. Pick the channel and a category, or let me make both."),
                [self.channel_select("“Join to create” channel…", pick("source"), current=[draft["source"]],
                                     kinds=(discord.ChannelType.voice,))],
                [self.channel_select("Category for the rooms…", pick("category"), current=[draft["category"]],
                                     kinds=(discord.ChannelType.category,))],
                [self.choice_select("Room type…", [(v, l, d) for v, l, d in ROOM_TYPES], draft["type"], kind_picked)],
                [self.choice_select("Room names…", [(v, l, d) for v, l, d in ROOM_NAMES], draft["names"],
                                    names_picked)],
                [self.button("Make them for me", make, disabled=bool(source and category)),
                 self.button("Save", save, style=discord.ButtonStyle.primary, disabled=not (source and category))],
                ui.hint(f"More options: the autoroomset command ({'loaded' if ar else 'not loaded'}).")]

    async def page_replies(self) -> list:
        conf = await self.cog.bot.get_cog("SpeakUp").config.guild(self.guild).all()
        quiet = conf["quiet_channels"]

        def flip(feature: str, on: bool):
            async def callback(interaction):
                await self.act(interaction, [f"speakup feature {feature} {'off' if on else 'on'}"])
            return callback

        async def quiet_picked(interaction):
            picked = self.values(interaction)
            lines = [f"speakup off {c}" for c in picked if c not in quiet]
            lines += [f"speakup on {c}" for c in quiet if c not in picked]
            await self.act(interaction, lines)

        features = conf["features"]
        return [ui.settings_text([(label, features.get(key, True)) for key, label in SPEAKUP_FEATURES]
                                 + [("Quiet channels", ", ".join(f"<#{c}>" for c in quiet) or "none")]),
                ui.hint("ButlerBot chimes in on its own: 🕘 on times, cards for Steam links, 📄 on article links, "
                        "and help with mistyped commands. Members can opt out with the speakup me command."),
                [self.button(label, flip(key, features.get(key, True)), emoji=self.toggle(features.get(key, True)))
                 for key, label in SPEAKUP_FEATURES],
                [self.channel_select("Quiet channels…", quiet_picked, current=quiet, optional=True, many=True)]]

    async def page_stats(self) -> list:
        conf = await self.cog.bot.get_cog("ActivityStats").config.guild(self.guild).all()
        excluded = [c for c in conf["excluded_channels"] if isinstance(c, int)]

        async def excluded_picked(interaction):
            picked = self.values(interaction)
            lines = [f"stats admin exclude {c}" for c in picked if c not in excluded]
            lines += [f"stats admin include {c}" for c in excluded if c not in picked]
            await self.act(interaction, lines)

        async def digest_picked(interaction):
            picked = self.values(interaction)
            await self.act(interaction, [f"stats admin digest channel {picked[0]}"] if picked else [])

        async def digest_flip(interaction):
            await self.act(interaction, [f"stats admin digest {'off' if conf['digest_enabled'] else 'on'}"])

        async def backfill(interaction):
            await self.act(interaction, ["stats admin backfill 30"])

        rows = [("Left out of stats", ", ".join(f"<#{c}>" for c in excluded) or "nothing"),
                ("Weekly digest", (f"on, in {channel_value(conf['digest_channel'])}" if conf["digest_enabled"]
                                   else "off")),
                ("Counted since", f"<t:{int(conf['backfilled_from'] or conf['started_at'])}:D>"
                 if conf["backfilled_from"] or conf["started_at"] else "not started")]
        return [ui.settings_text(rows),
                ui.hint("Stats count messages, voice time and games per hour; they never store what anyone wrote."),
                [self.channel_select("Leave out of stats…", excluded_picked, current=excluded,
                                     kinds=(discord.ChannelType.text, discord.ChannelType.voice,
                                            discord.ChannelType.category), optional=True, many=True)],
                [self.channel_select("Weekly digest channel…", digest_picked, current=[conf["digest_channel"]])],
                [self.button("Weekly digest", digest_flip, emoji=self.toggle(conf["digest_enabled"]),
                             disabled=not conf["digest_channel"]),
                 self.button("Count last 30 days", backfill, emoji="📊")]]

    async def page_moderation(self) -> list:
        bot, guild = self.cog.bot, self.guild
        parts, rows = [], []
        modlog = await self.cog.modlog_channel(guild)
        rows.append(("Mod log channel", channel_value(modlog)))
        warnings = bot.get_cog("Warnings")
        warn = await warnings.config.guild(guild).all() if warnings else None
        if warn:
            rows += [("Warnings sent by DM", warn["toggle_dm"]),
                     ("Warnings posted in", channel_value(warn["warn_channel"]) if warn["toggle_channel"]
                      else "the channel they're given in")]
        censor = bot.get_cog("Censord")
        filt = await censor.config.guild(guild).all() if censor else None
        if filt:
            rows += [("Word filter", filt["global_level"]), ("Word filter action", filt["action"])]
        spam = bot.get_cog("AntiSpam")
        spam_conf = await spam.config.all() if spam else None
        preset = None
        if spam_conf:
            preset = next((name for name, (amount, per, length, _) in ANTISPAM_PRESETS.items()
                           if (spam_conf["amount"], spam_conf["per"], spam_conf["mute_length"]) == (amount, per, length)),
                          None)
            rows.append(("Command spam limit", ANTISPAM_PRESETS[preset][3] if preset else "custom"))

        async def modlog_picked(interaction):
            picked = self.values(interaction)
            await self.act(interaction, [f"modlogset modlog {picked[0]}" if picked else "modlogset modlog"])

        async def warn_picked(interaction):
            picked = self.values(interaction)
            await self.act(interaction, [f"warningset warnchannel {picked[0]}", "warningset usewarnchannel true"]
                           if picked else ["warningset usewarnchannel false"])

        async def dm_flip(interaction):
            await self.act(interaction, [f"warningset senddm {'false' if warn['toggle_dm'] else 'true'}"])

        async def level_picked(interaction, value):
            await self.act(interaction, [f"censor level {value}"] if value else [])

        async def action_picked(interaction, value):
            await self.act(interaction, [f"censor action {value}"] if value else [])

        async def spam_picked(interaction, value):
            if value not in ANTISPAM_PRESETS:
                return await self.act(interaction, [])
            amount, per, length, _ = ANTISPAM_PRESETS[value]
            await self.act(interaction, [f"antispamset amount {amount}", f"antispamset per {per} seconds",
                                         f"antispamset length {length} seconds"])

        parts += [ui.settings_text(rows),
                  [self.channel_select("Mod log channel (clear to turn off)…", modlog_picked, current=[modlog],
                                       optional=True)]]
        if warn:
            parts += [[self.channel_select("Post warnings in (clear for where they're given)…", warn_picked,
                                           current=[warn["warn_channel"] if warn["toggle_channel"] else None],
                                           optional=True)],
                      [self.button("Warnings by DM", dm_flip, emoji=self.toggle(warn["toggle_dm"]))]]
        if filt:
            parts += [[self.choice_select("Word filter…", [("off", "Off", None),
                                                           ("low", "Low", "Slurs only"),
                                                           ("high", "High", "Slurs and swearing")],
                                          filt["global_level"], level_picked)],
                      [self.choice_select("When the filter catches someone often…",
                                          [("delete", "Delete", "Just delete the messages"),
                                           ("kick", "Kick", "Kick them"), ("ban", "Ban", "Ban them")],
                                          filt["action"], action_picked)]]
        if spam_conf:
            if await bot.is_owner(self.member):
                parts.append([self.choice_select("Command spam limit (every server)…",
                                                 [(k, k.title(), d) for k, (_, _, _, d) in ANTISPAM_PRESETS.items()],
                                                 preset, spam_picked)])
            else:
                parts.append(ui.hint("The command spam limit covers every server, so only the bot owner sets it."))
        return parts

    async def page_fun(self) -> list:
        conf = await self.cog.bot.get_cog("Parlor").config.guild(self.guild).all()
        caption, mystery = conf["caption_weekly"].get("channel"), conf["mystery_weekly"].get("channel")

        def weekly(command: str):
            async def callback(interaction):
                picked = self.values(interaction)
                await self.act(interaction, [f"{command} {picked[0]}" if picked else f"{command} off"])
            return callback

        return [ui.settings_text([("Weekly caption contest", channel_value(caption) if caption else "off"),
                                  ("Weekly murder mystery", channel_value(mystery) if mystery else "off")]),
                ui.hint("Each runs once a week in its channel, starting right away. Games make their own threads; "
                        "turn that off in a channel with the parlor threads command."),
                [self.channel_select("Weekly caption contest (clear to turn off)…", weekly("caption weekly"),
                                     current=[caption], optional=True)],
                [self.channel_select("Weekly murder mystery (clear to turn off)…", weekly("mystery weekly"),
                                     current=[mystery], optional=True)]]

    async def page_apps(self) -> list:
        bot = self.cog.bot
        enabled = await self.cog.enabled_apps()
        available = [a for a in APP_COMMANDS if bot.get_cog(a[2])]
        rows = [ui.two_line(f"**{shown}**" + (" ✅" if name in enabled.get(kind, {}) else ""),
                            None if name in enabled.get(kind, {}) else "Off")
                for name, kind, _, shown in available]
        off = [(name, kind) for name, kind, _, _ in available if name not in enabled.get(kind, {})]

        async def turn_on(interaction):
            lines = [f'slash enable "{name}" {kind}' for name, kind in off] + ["slash sync"]
            await self.act(interaction, lines)

        parts = [ui.hint("Slash and right-click commands belong to the bot, so they're switched on once for every "
                         "server."), *rows]
        if not available:
            parts.append("None of the cogs with slash commands are loaded.")
        elif await bot.is_owner(self.member):
            parts.append([self.button("Turn them all on", turn_on, style=discord.ButtonStyle.primary,
                                      disabled=not off)])
        elif off:
            parts.append(ui.line(ui.LOCKED, "Only the bot owner can switch these on. Ask them to run the setup "
                                            "wizard's last step."))
        return parts


# ==========================================
#                  THE COG
# ==========================================

class SetupWizard(commands.Cog):
    """A guided setup for new servers: `[p]setup` walks admins through every part of ButlerBot."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=4720913856, force_registration=True)
        self.config.register_guild(visited=[])

    async def cog_load(self):
        self.bot.add_dynamic_items(OpenButton)

    async def cog_unload(self):
        self.bot.remove_dynamic_items(OpenButton)

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        return   # nothing about users is stored

    # ---------- who can use it ----------

    async def can_setup(self, member: discord.Member) -> bool:
        if await self.bot.is_owner(member) or member.guild_permissions.administrator:
            return True
        return await self.bot.is_admin(member)

    async def _prefix(self, guild: Optional[discord.Guild]) -> str:
        for prefix in await self.bot.get_valid_prefixes(guild):
            if not prefix.startswith("<@"):
                return prefix
        return "!"

    # ---------- running commands ----------

    async def run(self, member: discord.Member, base: discord.Message, lines: List[str]) -> str:
        """
        Run each command as `member` (who opened the wizard), as if they'd typed it where `base` was sent.
        Replies are captured and returned as text, so nothing is posted in the channel. Each command keeps its own
        checks: one the member can't run says so.
        """
        prefix = await self._prefix(member.guild)
        out: List[str] = []
        for line in lines:
            fake = copy(base)
            if isinstance(fake, discord.Message):
                try:
                    fake.__class__ = QuietMessage
                except TypeError:
                    pass
            fake.author = member
            fake.content = prefix + line
            ctx = await self.bot.get_context(fake)
            command = self._find_command(line)   # the subcommand that will run, not just its group
            if not ctx.valid or command is None:
                out.append(ui.line(ui.FAIL, f"`{prefix}{line.split(' ')[0]}` isn't available here. Is its cog loaded?"))
                continue
            try:
                allowed = await command.can_run(ctx, check_all_parents=True)
            except commands.CommandError:
                allowed = False
            if not allowed:
                out.append(ui.line(ui.LOCKED, f"You can't run `{prefix}{command.qualified_name}`."))
                continue
            captured = Captured()
            ctx.send, ctx.reply = captured.send, captured.reply
            try:
                await self.bot.invoke(ctx)
            except Exception:
                log.exception("Setup command failed: %s", line)
                captured.lines.append(ui.line(ui.FAIL, f"`{prefix}{command.qualified_name}` didn't work."))
            out += captured.lines or [ui.line(ui.DONE, f"Ran `{prefix}{command.qualified_name}`.")]
        return ui.truncate("\n".join(out), 1500) if out else None

    def _find_command(self, line: str) -> Optional[commands.Command]:
        """The command a line runs: the longest run of its first words that names one ("set roles addmodrole")."""
        words = line.split()
        for n in range(len(words), 0, -1):
            command = self.bot.get_command(" ".join(words[:n]))
            if command is not None:
                return command
        return None

    # ---------- reading other cogs ----------

    def missing_permissions(self, guild: discord.Guild) -> List[Tuple[Tuple[str, ...], str]]:
        perms = guild.me.guild_permissions
        found = []
        for names, what in PERMISSIONS:
            lacking = tuple(n for n in names if not getattr(perms, n, False))
            if lacking:
                found.append((lacking, what))
        return found

    async def role_order_problems(self, guild: discord.Guild) -> List[str]:
        """Welcome roles that sit above ButlerBot's own role (it can't hand those out)."""
        greeter = self.bot.get_cog("ButtonGreeter")
        if greeter is None:
            return []
        conf = await greeter.config.guild(guild).all()
        top = getattr(guild.me, "top_role", None)
        if top is None:
            return []
        problems = []
        for role_id in [*conf["roles"].values(), conf["rules_role"]]:
            role = guild.get_role(role_id or 0)
            if role is not None and role >= top:
                problems.append(f"Move ButlerBot's role above {role.mention}, or it can't give that role out.")
        return problems

    async def modlog_channel(self, guild: discord.Guild) -> Optional[int]:
        try:
            from redbot.core import modlog
            return (await modlog.get_modlog_channel(guild)).id
        except Exception:
            return None

    async def autoroom_sources(self, guild: discord.Guild) -> Dict[str, dict]:
        cog = self.bot.get_cog("AutoRoom")
        if cog is None:
            return {}
        try:
            sources = await cog.config.custom("AUTOROOM_SOURCE", str(guild.id)).all()
        except Exception:
            log.debug("Couldn't read AutoRoom sources", exc_info=True)
            return {}
        return {cid: data for cid, data in sources.items() if data.get("dest_category_id")}

    async def enabled_apps(self) -> Dict[str, Dict[str, Optional[int]]]:
        try:
            return await self.bot.list_enabled_app_commands()
        except Exception:
            return {}

    async def status(self, guild: discord.Guild, key: str) -> Tuple[str, Optional[str]]:
        """(✅, ⚠️ or "", a short detail) for one step on the overview."""
        bot = self.bot
        try:
            if key == "perms":
                missing = self.missing_permissions(guild)
                if missing:
                    names = [PERMISSION_NAMES[p] for perms, _ in missing for p in perms]
                    return "⚠️", ("Missing " + ", ".join(names)) if len(names) <= 3                         else f"Missing {len(names)} permissions"
                return "✅", None
            if key == "staff":
                mods = await bot.get_mod_roles(guild) if hasattr(bot, "get_mod_roles") else []
                admins = await bot.get_admin_roles(guild) if hasattr(bot, "get_admin_roles") else []
                return ("✅", None) if mods or admins else ("", "No mod or admin roles yet")
            if key == "welcome":
                conf = await bot.get_cog("ButtonGreeter").config.guild(guild).all()
                if conf["welcome_channel"] and conf["roles"]:
                    return ("✅", None) if conf["rules_role"] else ("⚠️", "No rules role, so the rules step is skipped")
                return ("⚠️", "Partly set up") if conf["welcome_channel"] or conf["roles"] else ("", "Not set up")
            if key == "games":
                conf = await bot.get_cog("GameManager").config.guild(guild).all()
                if conf["events"] and not guild.me.guild_permissions.manage_events:
                    return "⚠️", "Discord events need Manage Events"
                return ("✅", None) if conf["timezone"] else ("", "No server timezone yet")
            if key == "ai":
                return "✅", None
            if key == "voice":
                count = len(await self.autoroom_sources(guild))
                return ("✅", ui.plural(count, "join-to-create channel")) if count else ("", "Not set up")
            if key == "replies":
                conf = await bot.get_cog("SpeakUp").config.guild(guild).all()
                off = [label for k, label in SPEAKUP_FEATURES if not conf["features"].get(k, True)]
                return "✅", ("Off: " + ", ".join(off)) if off else None
            if key == "stats":
                conf = await bot.get_cog("ActivityStats").config.guild(guild).all()
                return "✅", "Weekly digest on" if conf["digest_enabled"] else None
            if key == "moderation":
                return ("✅", None) if await self.modlog_channel(guild) else ("", "No mod log channel")
            if key == "fun":
                conf = await bot.get_cog("Parlor").config.guild(guild).all()
                on = [n for n, k in (("captions", "caption_weekly"), ("mysteries", "mystery_weekly"))
                      if conf[k].get("channel")]
                return ("✅", "Weekly " + " and ".join(on)) if on else ("", "No weekly games")
            if key == "apps":
                enabled = await self.enabled_apps()
                available = [a for a in APP_COMMANDS if bot.get_cog(a[2])]
                off = [a for a in available if a[0] not in enabled.get(a[1], {})]
                return ("⚠️", f"{ui.plural(len(off), 'command')} off (the bot owner turns them on)") if off \
                    else ("✅", None)
        except Exception:
            log.debug("Status check failed for %s", key, exc_info=True)
        return "", None

    # ---------- progress ----------

    async def mark_visited(self, guild: discord.Guild, key: str):
        async with self.config.guild(guild).visited() as visited:
            if key not in visited:
                visited.append(key)

    async def next_step(self, guild: discord.Guild, keys: List[str]) -> str:
        visited = await self.config.guild(guild).visited()
        return next((k for k in keys if k not in visited), keys[0])

    # ---------- voice rooms (AutoRoom) ----------

    async def make_voice_channels(self, guild: discord.Guild, draft: dict) -> str:
        """Create a category and a join-to-create voice channel for voice rooms (fills in whichever is missing)."""
        if not guild.me.guild_permissions.manage_channels:
            return ui.line(ui.FAIL, "I need Manage Channels to make them.")
        try:
            category = guild.get_channel(draft.get("category") or 0)
            if category is None:
                category = await guild.create_category(VOICE_CATEGORY, reason="Setup wizard: voice rooms")
                draft["category"] = category.id
            if guild.get_channel(draft.get("source") or 0) is None:
                source = await guild.create_voice_channel(VOICE_SOURCE, category=category,
                                                          reason="Setup wizard: voice rooms")
                draft["source"] = source.id
        except discord.HTTPException as e:
            log.info("Couldn't make voice room channels in %s: %s", guild, e)
            return ui.line(ui.FAIL, "Discord didn't let me make the channels. Check my permissions and try again.")
        return ui.line(ui.DONE, f"Made <#{draft['source']}> in <#{draft['category']}>. Check the room type, "
                                "then press Save.")

    async def save_autoroom(self, guild: discord.Guild, draft: dict) -> str:
        """Save a join-to-create channel the way AutoRoom's own `create` command does, after the same checks."""
        cog = self.bot.get_cog("AutoRoom")
        source = guild.get_channel(draft.get("source") or 0)
        category = guild.get_channel(draft.get("category") or 0)
        if cog is None:
            return ui.line(ui.FAIL, "The voice rooms cog isn't loaded.")
        if not isinstance(source, discord.VoiceChannel) or not isinstance(category, discord.CategoryChannel):
            return ui.line(ui.ASK, "Pick a voice channel and a category first.")
        try:
            required, optional, details = cog.check_perms_source_dest(
                source, category, with_manage_roles_guild=draft["type"] != "server", detailed=True)
        except Exception:
            log.exception("AutoRoom's permission check failed")
            return ui.line(ui.FAIL, "I couldn't check the voice rooms cog's permissions.",
                           hint="Set it up with the autoroomset create command instead.")
        if not required or not optional:
            return ui.line(ui.FAIL, "I'm missing permissions in that channel or category:") + "\n" + \
                ui.truncate(str(details or ""), 800)
        await cog.config.custom("AUTOROOM_SOURCE", str(guild.id), str(source.id)).set(
            {"dest_category_id": category.id, "room_type": draft["type"], "channel_name_type": draft["names"]})
        return ui.line(ui.DONE, f"Voice rooms are on: joining {source.mention} makes a room in {category.mention}.")

    # ==========================================
    #                 COMMANDS
    # ==========================================

    @commands.command(name="setup", aliases=["setupwizard"])
    @commands.guild_only()
    @checks.admin_or_permissions(administrator=True)
    async def setup_command(self, ctx: commands.Context):
        """
        A guided setup for this server: permissions, staff roles, the welcome flow, game nights, AI chat, voice
        rooms, auto-replies, stats, moderation, weekly games and slash commands (admins).

        Press **Open setup** for a private wizard. Each step shows what's set now and changes it with pickers,
        by running the server's own commands for you. Every step is optional, and it remembers where you got to.
        """
        p = await self._prefix(ctx.guild)
        view = ui.CardView(ui.card(
            ui.two_line("**Set ButlerBot up for this server**",
                        "A private, step-by-step wizard for admins. Every step is optional."),
            [OpenButton()], title=f"{TOPIC} Server setup", footer=f"Staff only · {p}help setup for details"))
        await ui.send_card(ctx, view)

    async def open_wizard(self, interaction: discord.Interaction):
        member = interaction.user
        if getattr(member, "guild", None) is None or not await self.can_setup(member):
            return await ui.respond(interaction, ui.line(ui.LOCKED, "Only the server's admins can run setup."))
        wizard = Wizard(self, member, interaction.message)
        await wizard.show(interaction, edit=False)
