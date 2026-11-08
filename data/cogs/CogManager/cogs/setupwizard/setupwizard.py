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
ROOM_TYPES = [("public", "Anyone", "Anyone can join; the room's owner can kick people out"),
              ("locked", "Owner lets them in", "Everyone can see it, but the owner allows people in"),
              ("private", "Hidden, owner lets them in", "Only people the owner allows can see it"),
              ("server", "Anyone, no owner", "Open to all, and nobody can change it")]
ROOM_NAMES = [("username", "The owner's name", "Like “Alex's Room”"),
              ("game", "The owner's game", "The game they're playing, else their name")]
ANTISPAM_PRESETS = {   # name: (commands, seconds, timeout seconds, description)
    "relaxed": (8, 10, 120, "8 commands in 10 seconds, then a 2-minute break"),
    "normal": (5, 5, 300, "5 commands in 5 seconds, then a 5-minute break"),
    "strict": (4, 10, 900, "4 commands in 10 seconds, then a 15-minute break"),
}
# (name, kind, the cog that provides it, how it's shown, what it does)
APP_COMMANDS = [
    ("games", "slash", "GameManager", "/games", "Game library and game nights as slash commands"),
    ("catchup", "slash", "ClaudeChat", "/catchup", "A private summary of what you missed in a channel"),
    ("Summarize link", "message", "SpeakUp", "Summarize link", "Right-click a message → Apps: a private summary"),
    ("Translate", "message", "EasyTranslate", "Translate", "Right-click a message → Apps: translate it privately"),
    ("translate", "slash", "EasyTranslate", "/translate", "Translate some text"),
    ("setmylanguage", "slash", "EasyTranslate", "/setmylanguage", "The language Translate turns things into"),
]
PERSONA_FORM_MAX = 4000         # Discord's limit for one text box in a form
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

class LabelModal(discord.ui.Modal, title="New group button"):
    """The label for a new welcome group button (also the [TAG] in nicknames)."""

    def __init__(self, wizard: "Wizard", role: discord.Role):
        super().__init__()
        self.wizard, self.role = wizard, role
        self.label = discord.ui.TextInput(label="Button label and nickname tag", default=role.name[:40],
                                          max_length=40, placeholder="RDR")
        self.add_item(self.label)

    async def on_submit(self, interaction: discord.Interaction):
        label = " ".join(str(self.label.value).split())
        await self.wizard.act(interaction, [f"bg addrole {self.role.id} {label}"])


class PersonaModal(discord.ui.Modal, title="ButlerBot's personality"):
    """Write the server's own personality for the AI (runs `[p]claude persona <text>`)."""

    def __init__(self, wizard: "Wizard", current: str):
        super().__init__()
        self.wizard = wizard
        self.text = discord.ui.TextInput(
            label="Who ButlerBot is and how it talks", style=discord.TextStyle.paragraph, max_length=PERSONA_FORM_MAX,
            default=current[:PERSONA_FORM_MAX] or None,
            placeholder="You are a cheerful pirate quartermaster. Keep answers short and salty.")
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        text = str(self.text.value).strip()
        await self.wizard.act(interaction, [f"claude persona {text}"] if text else [])


class Wizard(ui.ExpiringCard):
    """
    The private setup menu: an overview listing every step with its status, one page per step, and a finish page.
    Every setting is a labelled field (a bold name and a line saying what it does) with its menu under it, or a
    switch (the name and On/Off, with a Turn on/off button beside it). Changes run the server's own commands as the
    admin; what they said shows under the page title.
    """

    def __init__(self, cog: "SetupWizard", member: discord.Member, base: discord.Message, prefix: str = "!"):
        super().__init__(member.id, timeout=WIZARD_TIMEOUT)
        self.expired_note = f"Expired. Run `{prefix}setup` to carry on."
        self.cog, self.member, self.guild, self.base, self.p = cog, member, member.guild, base, prefix
        self.page: Optional[str] = None   # None = the overview; "done" = the finish page
        self.note: Optional[str] = None   # the last change's result
        self.voice: Dict[str, object] = {"source": None, "category": None, "type": "public", "names": "username",
                                         "loaded": False}

    # ---------- navigation ----------

    def steps(self) -> List[Tuple[str, str]]:
        return [(key, title) for key, title, needs in STEPS if needs is None or self.cog.bot.get_cog(needs)]

    async def show(self, interaction: discord.Interaction, *, edit: bool = True):
        """Draw the current page; edit the message the interaction came from (or answer it with the wizard)."""
        if self.page not in (None, "done"):
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

    async def close(self, interaction: discord.Interaction):
        """Remove the wizard (it's a private message, so deleting it only affects this admin)."""
        self.stop()
        await interaction.response.defer()
        try:
            await interaction.delete_original_response()
        except discord.HTTPException:
            self.clear_items()
            self.add_item(ui.card(ui.line(ui.DONE, f"Setup closed. Run `{self.p}setup` any time to come back."),
                                  title=f"{TOPIC} Server setup"))
            await interaction.edit_original_response(view=self)

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
        nxt = keys[at + 1] if 0 <= at < len(keys) - 1 else "done"
        return [self.button("Back", self.go(back), disabled=at <= 0),
                self.button("Next" if nxt != "done" else "Finish", self.go(nxt), style=discord.ButtonStyle.primary),
                self.button("Overview", self.go(None)),
                self.button("Close", self.close)]

    @staticmethod
    def values(interaction: discord.Interaction) -> List[int]:
        """The IDs picked in a select menu (read from the interaction, so it works however the menu was built)."""
        return [int(v) for v in ((getattr(interaction, "data", None) or {}).get("values") or []) if str(v).isdigit()]

    # ---------- fields ----------

    @staticmethod
    def field(label: str, explain: str, control) -> list:
        """A setting: its name in bold and what it does in small text, with its menu right under it."""
        return [ui.two_line(f"**{label}**", explain), [control]]

    def switch(self, label: str, on: bool, explain: str, callback, *, disabled: bool = False) -> discord.ui.Section:
        """An on/off setting: `**Name** · On` and what it does, with a Turn off / Turn on button beside it."""
        text = ui.two_line(f"**{label}** · {'On' if on else 'Off'}", explain)
        return discord.ui.Section(discord.ui.TextDisplay(text), accessory=self.button(
            "Turn off" if on else "Turn on", callback, disabled=disabled))

    def action(self, label: str, explain: str, button_label: str, callback, *, disabled: bool = False,
               style=discord.ButtonStyle.secondary) -> discord.ui.Section:
        """A one-off action: what it does, with its button beside it."""
        return discord.ui.Section(discord.ui.TextDisplay(ui.two_line(f"**{label}**", explain)),
                                  accessory=self.button(button_label, callback, disabled=disabled, style=style))

    def channel_select(self, callback, *, current=(), kinds=(discord.ChannelType.text,), optional: bool = False,
                       many: bool = False, placeholder: str = "Pick a channel…") -> discord.ui.ChannelSelect:
        defaults = [discord.Object(id=c) for c in current if c]
        select = discord.ui.ChannelSelect(placeholder=placeholder, channel_types=list(kinds),
                                          min_values=0 if optional else 1, max_values=25 if many else 1,
                                          default_values=defaults[:25 if many else 1])
        select.callback = callback
        return select

    def role_select(self, callback, *, current=(), optional: bool = False, many: bool = False,
                    placeholder: str = "Pick a role…") -> discord.ui.RoleSelect:
        defaults = [discord.Object(id=r) for r in current if r]
        select = discord.ui.RoleSelect(placeholder=placeholder, min_values=0 if optional else 1,
                                       max_values=10 if many else 1, default_values=defaults[:10 if many else 1])
        select.callback = callback
        return select

    def choice_select(self, options: List[Tuple[str, str, Optional[str]]], current: Optional[str], callback,
                      placeholder: str = "Pick one…") -> discord.ui.Select:
        select = discord.ui.Select(placeholder=placeholder, options=[
            discord.SelectOption(label=label[:100], value=value, description=(desc or None) and desc[:100],
                                 default=value == current) for value, label, desc in options][:25])

        async def chosen(interaction: discord.Interaction):
            picked = ((getattr(interaction, "data", None) or {}).get("values") or [None])[0]
            await callback(interaction, picked)
        select.callback = chosen
        return select

    def picked_one(self, command: str, off: Optional[str] = None):
        """A select callback that runs `command <id>`, or `off` when the menu is cleared."""
        async def callback(interaction):
            picked = self.values(interaction)
            await self.act(interaction, [f"{command} {picked[0]}"] if picked else [off] if off else [])
        return callback

    def flips(self, command: str, on: bool, words=("on", "off")):
        async def callback(interaction):
            await self.act(interaction, [f"{command} {words[1] if on else words[0]}"])
        return callback

    # ---------- pages ----------

    async def render(self) -> discord.ui.Container:
        if self.page is None:
            return await self.overview()
        if self.page == "done":
            return await self.finished()
        title = dict((k, t) for k, t, _ in STEPS)[self.page]
        keys = [k for k, _ in self.steps()]
        number = f" ({keys.index(self.page) + 1} of {len(keys)})" if self.page in keys else ""
        parts = [self.note] if self.note else []
        parts += await getattr(self, f"page_{self.page}")()
        parts += [ui.SEPARATOR, self.nav()]
        return ui.card(*parts, title=f"{TOPIC} Setup: {title}{number}",
                       footer="Changes save as soon as you make them")

    async def overview(self) -> discord.ui.Container:
        rows = []
        for key, title in self.steps():
            symbol, detail = await self.cog.status(self.guild, key)
            rows.append(ui.two_line(f"**{title}**" + (f" {symbol}" if symbol else ""), detail))
        keys = [k for k, _ in self.steps()]
        start = await self.cog.next_step(self.guild, keys)
        begun = bool(await self.cog.config.guild(self.guild).visited())
        menu = self.choice_select([(k, t, None) for k, t in self.steps()], None, lambda i, key: self.go(key)(i),
                                  placeholder="Go to a step…")
        return ui.card("A step-by-step setup for ButlerBot in this server. Every step is optional, changes save as "
                       "you make them, and you can come back any time.",
                       *rows, ui.SEPARATOR, [menu],
                       [self.button("Carry on" if begun else "Start", self.go(start), style=discord.ButtonStyle.primary),
                        self.button("Close", self.close)],
                       title=f"{TOPIC} Server setup", footer="✅ set up · ⚠️ needs a look")

    async def finished(self) -> discord.ui.Container:
        attention = []
        for key, title in self.steps():
            symbol, detail = await self.cog.status(self.guild, key)
            if symbol == "⚠️":
                attention.append(ui.two_line(f"**{title}** ⚠️", detail))
        handbook = self.cog.bot.get_cog("Handbook")
        base = await handbook.base_url() if handbook is not None and hasattr(handbook, "base_url") else None
        parts = [ui.line(ui.DONE, "That's every step.")]
        if attention:
            parts += ["These could still use a look:", *attention]
        else:
            parts.append("Nothing needs a look.")
        parts += [ui.SEPARATOR,
                  ui.two_line("**What's next**", f"Point members to the handbook's Getting started page, so they set "
                                                 f"up their game profile. Run `{self.p}setup` any time to change "
                                                 "things.")]
        buttons = [self.button("Close", self.close, style=discord.ButtonStyle.primary),
                   self.button("Back to overview", self.go(None))]
        if base:
            buttons.append(discord.ui.Button(label="Getting started", url=f"{base}start/"))
        parts.append(buttons)
        return ui.card(*parts, title=f"{TOPIC} Setup finished")

    async def page_perms(self) -> list:
        missing = self.cog.missing_permissions(self.guild)
        parts = ["ButlerBot's role needs these permissions server-wide. Each line says what breaks without it."]
        if not missing:
            parts.append(ui.line(ui.DONE, "ButlerBot has every permission it uses."))
        else:
            parts += [ui.two_line(f"**{', '.join(PERMISSION_NAMES[p] for p in perms)}** ⚠️", f"For {what}")
                      for perms, what in missing]
            parts.append(ui.hint("Add them to ButlerBot's role in Server Settings → Roles, then check again."))
        parts += [ui.line(ui.WARN, w) for w in await self.cog.role_order_problems(self.guild)]
        parts.append([self.button("Check again", self.go("perms"))])
        return parts

    async def page_staff(self) -> list:
        bot, guild = self.cog.bot, self.guild
        mods = [r.id for r in await bot.get_mod_roles(guild)] if hasattr(bot, "get_mod_roles") else []
        admins = [r.id for r in await bot.get_admin_roles(guild)] if hasattr(bot, "get_admin_roles") else []
        owner = guild.owner_id == self.member.id or await bot.is_owner(self.member)
        gm = bot.get_cog("GameManager")

        def roles_picked(kind: str, current: List[int]):
            async def callback(interaction):
                picked = self.values(interaction)
                lines = [f"set roles add{kind}role {r}" for r in picked if r not in current]
                lines += [f"set roles remove{kind}role {r}" for r in current if r not in picked]
                await self.act(interaction, lines)
            return callback

        parts = ["Staff roles decide who can use ButlerBot's mod and admin commands."]
        mod_help = "Can warn, mute and clean up. Pick every role that should count; removing one here takes it away."
        admin_help = "Everything mods can do, plus changing ButlerBot's settings."
        if owner:
            parts += self.field("Mod roles", mod_help, self.role_select(
                roles_picked("mod", mods), current=mods, optional=True, many=True, placeholder="No mod roles"))
            parts += self.field("Admin roles", admin_help, self.role_select(
                roles_picked("admin", admins), current=admins, optional=True, many=True,
                placeholder="No admin roles"))
        else:
            parts += [ui.two_line("**Mod roles**", ", ".join(f"<@&{r}>" for r in mods) or "None"),
                      ui.two_line("**Admin roles**", ", ".join(f"<@&{r}>" for r in admins) or "None"),
                      ui.line(ui.LOCKED, "Only the server owner can change mod and admin roles.")]
        if gm:
            game_admin = await gm.config.guild(guild).admin_role()
            parts += self.field("Game admin role", "Approves game requests and can run any game night. Server admins "
                                                   "can always do this too.",
                                self.role_select(self.picked_one("games admin setrole", "games admin setrole"),
                                                 current=[game_admin], optional=True, placeholder="No game admin role"))
        return parts

    async def page_welcome(self) -> list:
        conf = await self.cog.bot.get_cog("ButtonGreeter").config.guild(self.guild).all()
        groups = ", ".join(f"{label} (<@&{rid}>)" for label, rid in conf["roles"].items())

        async def group_picked(interaction):
            picked = self.values(interaction)
            role = self.guild.get_role(picked[0]) if picked else None
            if role is None:
                return await self.act(interaction, [])
            await interaction.response.send_modal(LabelModal(self, role))

        return ["New members get a greeting with buttons: they pick a group, which gives them its role and a "
                "[TAG] in front of their nickname, then agree to the rules to unlock the server.",
                *self.field("Greeting channel", "Where newcomers are greeted.",
                            self.channel_select(self.picked_one("bg setchannel"), current=[conf["welcome_channel"]])),
                *self.field("Group buttons", (f"Now: {groups}. " if groups else "None yet. ")
                            + f"Pick a role to add it as a button; you'll name its tag next. Remove one with "
                              f"`{self.p}bg removerole <label>`.",
                            self.role_select(group_picked, placeholder="Add a group…")),
                *self.field("Rules channel", "Where your rules are; the greeting points to it.",
                            self.channel_select(self.picked_one("bg setruleschannel"),
                                                current=[conf["rules_channel"]])),
                *self.field("Rules role", "Given when someone agrees to the rules. Without one, the rules step is "
                                          "skipped.",
                            self.role_select(self.picked_one("bg setrulesrole"), current=[conf["rules_role"]])),
                *self.field("Report problems in", "Where ButlerBot tells staff when it couldn't give a role or change "
                                                  "a nickname.",
                            self.channel_select(self.picked_one("bg setadminchannel"),
                                                current=[conf["admin_channel"]]))]

    async def page_games(self) -> list:
        gm = self.cog.bot.get_cog("GameManager")
        conf = await gm.config.guild(self.guild).all()
        module = sys.modules.get(type(gm).__module__)
        zones = list(getattr(module, "COMMON_TIMEZONES", FALLBACK_TIMEZONES))
        if conf["timezone"] and conf["timezone"] not in [z for _, z in zones]:
            zones.insert(0, (conf["timezone"], conf["timezone"]))
        can_events = self.guild.me.guild_permissions.manage_events

        async def zone_picked(interaction, zone):
            await self.act(interaction, [f"games admin timezone {zone}"] if zone else [])

        return ["Game nights, the game library and sale alerts.",
                *self.field("Server timezone", "Session times people type are read in their own timezone if they've "
                                               "set one, otherwise in this one.",
                            self.choice_select([(z, label, z) for label, z in zones], conf["timezone"], zone_picked,
                                               placeholder="UTC (not set)")),
                *self.field("Sale alerts channel", "When a game on someone's wishlist goes on sale, they're pinged "
                                                   "here. Clear it to turn sale alerts off.",
                            self.channel_select(self.picked_one("games admin sales", "games admin sales"),
                                                current=[conf["sale_channel"]], optional=True,
                                                placeholder="Sale alerts are off")),
                self.switch("Free Epic games", conf["free_games"],
                            "Also posts games that are free to keep on the Epic Games Store in the sale alerts channel."
                            + ("" if conf["sale_channel"] else " Needs a sale alerts channel first."),
                            self.flips("games admin freegames", conf["free_games"], ("true", "false")),
                            disabled=not conf["sale_channel"] and not conf["free_games"]),
                self.switch("Discord events", conf["events"],
                            "Scheduled game nights also show in the server's Events list."
                            + ("" if can_events else " ⚠️ Needs the Manage Events permission."),
                            self.flips("games admin events", conf["events"], ("true", "false"))),
                *self.field("Event voice channel", "Optional: events point people to this voice channel instead of "
                                                   "the text channel the game night was posted in.",
                            self.channel_select(self.picked_one("games admin eventchannel", "games admin eventchannel"),
                                                current=[conf["event_channel"]], kinds=(discord.ChannelType.voice,),
                                                optional=True, placeholder="No voice channel")),
                self.switch("Members add games", conf["member_add"],
                            "Members can add new games to the server library themselves, instead of requesting them "
                            "for a game admin to approve.",
                            self.flips("games admin memberadd", conf["member_add"], ("true", "false")))]

    async def page_ai(self) -> list:
        cc = self.cog.bot.get_cog("ClaudeChat")
        conf = await cc.config.guild(self.guild).all()
        if conf["persona"]:
            which, text = "This server's own", conf["persona"]
        elif conf["default_persona"]:
            which, text = "This server's saved default", conf["default_persona"]
        else:
            module = sys.modules.get(type(cc).__module__)
            which = "ButlerBot's own"
            text = module.default_persona() if hasattr(module, "default_persona") else ""
        preview = ui.truncate(" ".join(text.split()), 160) if text else "Not set"

        async def limit_picked(interaction, value):
            await self.act(interaction, [f"claude limit {value}"] if value is not None else [])

        async def write_persona(interaction):
            await interaction.response.send_modal(PersonaModal(self, conf["persona"] or ""))

        async def reset_persona(interaction):
            await self.act(interaction, ["claude persona reset"])

        limits = [(str(n), f"{n} a day" if n else "No limit", None) for n in DAILY_LIMITS]
        return [f"The AI chat: `{self.p}ai`, `{self.p}butler`, and mentioning ButlerBot.",
                self.switch("@mentions go to the AI", conf["guide_mentions"],
                            "Mentioning ButlerBot, or replying to one of its messages, gets an AI answer.",
                            self.flips("claude guidementions", conf["guide_mentions"])),
                self.switch("AI runs commands", conf["guide_actions"],
                            "The AI can run commands for the person asking. Staff commands still need them to press "
                            "Run first.", self.flips("claude guideactions", conf["guide_actions"])),
                self.switch("Web search", conf["web_search"], "The AI can search the web for current information.",
                            self.flips("claude websearch", conf["web_search"])),
                *self.field("Daily limit per member", "AI messages each member can send a day. Mods and admins aren't "
                                                      "limited, and questions about the bot don't count.",
                            self.choice_select(limits, str(conf["daily_limit"]), limit_picked)),
                ui.two_line(f"**Personality** · {which}", preview),
                [self.button("Write your own", write_persona),
                 self.button("Use ButlerBot's own", reset_persona, disabled=not conf["persona"])],
                ui.hint(f"The form holds up to {PERSONA_FORM_MAX:,} characters; for a longer one, attach a .txt file "
                        f"to `{self.p}claude persona`.")]

    async def page_voice(self) -> list:
        sources = await self.cog.autoroom_sources(self.guild)
        draft = self.voice
        if not draft["loaded"]:   # start from the first existing setup, so the menus show what's there
            draft["loaded"] = True
            if sources:
                cid, data = next(iter(sources.items()))
                draft.update(source=int(cid), category=data.get("dest_category_id"),
                             type=data.get("room_type") or "public", names=data.get("channel_name_type") or "username")
        editing = str(draft["source"]) in sources if draft["source"] else False
        source = self.guild.get_channel(draft["source"] or 0)
        category = self.guild.get_channel(draft["category"] or 0)

        def pick(key: str):
            async def callback(interaction):
                picked = self.values(interaction)
                draft[key] = picked[0] if picked else None
                await self.act(interaction, [])
            return callback

        def choose(key: str):
            async def callback(interaction, value):
                draft[key] = value or draft[key]
                await self.act(interaction, [])
            return callback

        async def make(interaction):
            await interaction.response.defer()
            self.note = await self.cog.make_voice_channels(self.guild, draft)
            await self.show(interaction)

        async def save(interaction):
            await interaction.response.defer()
            self.note = await self.cog.save_autoroom(self.guild, draft)
            await self.show(interaction)

        async def add_another(interaction):
            draft.update(source=None, category=None, type="public", names="username")
            self.note = None
            await self.show(interaction)

        async def remove(interaction):
            sid = draft["source"]
            draft.update(source=None, category=None, loaded=False)
            await self.act(interaction, [f"autoroomset remove {sid}"])

        others = [f"<#{cid}>" for cid in sources if cid != str(draft["source"])]
        parts = ["Voice rooms give each person their own voice channel: they join a “join to create” channel, get "
                 "moved into a new room, and the room is deleted when everyone leaves.",
                 ui.two_line(f"**{'Editing' if editing else 'New'}: " + (source.mention if source else "a join-to-create "
                                                                                                       "channel") + "**",
                             ("Also set up: " + ", ".join(others)) if others else None),
                 *self.field("Join-to-create channel", "The voice channel people join to get a room.",
                             self.channel_select(pick("source"), current=[draft["source"]],
                                                 kinds=(discord.ChannelType.voice,),
                                                 placeholder="Pick a voice channel…")),
                 *self.field("Where new rooms go", "The category the temporary rooms are made in. A category of their "
                                                   "own keeps the channel list tidy.",
                             self.channel_select(pick("category"), current=[draft["category"]],
                                                 kinds=(discord.ChannelType.category,),
                                                 placeholder="Pick a category…")),
                 *self.field("Who can get in", "The person who makes a room is its owner.",
                             self.choice_select([(v, l, d) for v, l, d in ROOM_TYPES], draft["type"],
                                                choose("type"))),
                 *self.field("Room names", "What new rooms are called.",
                             self.choice_select([(v, l, d) for v, l, d in ROOM_NAMES], draft["names"],
                                                choose("names")))]
        buttons = [self.button("Save", save, style=discord.ButtonStyle.primary, disabled=not (source and category))]
        if not (source and category):
            buttons.append(self.button("Make the channels", make))
        if editing:
            buttons += [self.button("Add another", add_another), self.button("Turn off", remove)]
        parts.append(buttons)
        if not (source and category):
            parts.append(ui.hint("Make the channels creates a “Voice rooms” category and a “➕ Join to create” "
                                 "channel in it for you."))
        parts.append(ui.hint(f"More options, like letting room owners rename them: `{self.p}autoroomset modify`."))
        return parts

    async def page_replies(self) -> list:
        conf = await self.cog.bot.get_cog("SpeakUp").config.guild(self.guild).all()
        quiet, features = conf["quiet_channels"], conf["features"]

        async def quiet_picked(interaction):
            picked = self.values(interaction)
            lines = [f"speakup off {c}" for c in picked if c not in quiet]
            lines += [f"speakup on {c}" for c in quiet if c not in picked]
            await self.act(interaction, lines)

        explain = {
            "times": "Adds 🕘 to messages with a time in them; clicking it shows the time in everyone's timezone.",
            "steam": "Replies to Steam store links with the price and who here owns the game.",
            "links": "Adds 📄 to article links; clicking it posts a short summary (this uses AI).",
            "mistakes": "Suggests the right command when someone mistypes one.",
        }
        return ["ButlerBot can chime in on its own in chat. Switch each kind off for the whole server here; members "
                f"can also opt themselves out with `{self.p}speakup me off`.",
                *[self.switch(label, features.get(key, True), explain[key],
                              self.flips(f"speakup feature {key}", features.get(key, True)))
                  for key, label in SPEAKUP_FEATURES],
                *self.field("Quiet channels", "Channels where ButlerBot never chimes in on its own (no 🕘, 📄, Steam "
                                              "cards or typo help). Commands still work there.",
                            self.channel_select(quiet_picked, current=quiet, optional=True, many=True,
                                                placeholder="No quiet channels"))]

    async def page_stats(self) -> list:
        conf = await self.cog.bot.get_cog("ActivityStats").config.guild(self.guild).all()
        excluded = [c for c in conf["excluded_channels"] if isinstance(c, int)]
        since = conf["backfilled_from"] or conf["started_at"]

        async def excluded_picked(interaction):
            picked = self.values(interaction)
            lines = [f"stats admin exclude {c}" for c in picked if c not in excluded]
            lines += [f"stats admin include {c}" for c in excluded if c not in picked]
            await self.act(interaction, lines)

        async def backfill(interaction):
            await self.act(interaction, ["stats admin backfill 30"])

        return ["Server stats count messages, voice time and games per hour. They never store what anyone wrote.",
                *self.field("Left out of stats", "Nothing in these channels or categories is counted, such as staff "
                                                 "or bot channels.",
                            self.channel_select(excluded_picked, current=excluded, optional=True, many=True,
                                                kinds=(discord.ChannelType.text, discord.ChannelType.voice,
                                                       discord.ChannelType.category),
                                                placeholder="Everything is counted")),
                *self.field("Weekly digest channel", "Where the weekly summary of the server's activity goes.",
                            self.channel_select(self.picked_one("stats admin digest channel"),
                                                current=[conf["digest_channel"]], placeholder="Not set")),
                self.switch("Weekly digest", conf["digest_enabled"],
                            "A weekly summary of the server's activity, with charts."
                            + ("" if conf["digest_channel"] else " Needs a digest channel first."),
                            self.flips("stats admin digest", conf["digest_enabled"]),
                            disabled=not conf["digest_channel"] and not conf["digest_enabled"]),
                self.action("Count past messages", "Stats start when ButlerBot arrives. This counts the last 30 days "
                                                   "of messages so the charts aren't empty"
                            + (f" (counted since <t:{int(since)}:D>)." if since else "."), "Count 30 days", backfill)]

    async def page_moderation(self) -> list:
        bot, guild = self.cog.bot, self.guild
        parts = ["Records and limits for staff."]
        modlog = await self.cog.modlog_channel(guild)
        parts += self.field("Mod log channel", "Where bans, kicks, mutes and warnings are recorded. Clear it to turn "
                                               "the log off.",
                            self.channel_select(self.picked_one("modlogset modlog", "modlogset modlog"),
                                                current=[modlog], optional=True, placeholder="No mod log"))
        warnings = bot.get_cog("Warnings")
        if warnings:
            warn = await warnings.config.guild(guild).all()

            async def warn_picked(interaction):
                picked = self.values(interaction)
                await self.act(interaction, [f"warningset warnchannel {picked[0]}", "warningset usewarnchannel true"]
                               if picked else ["warningset usewarnchannel false"])

            parts += self.field("Warnings channel", "Where warnings are announced. Clear it to announce them in the "
                                                    "channel where they're given.",
                                self.channel_select(warn_picked, optional=True, placeholder="Where they're given",
                                                    current=[warn["warn_channel"] if warn["toggle_channel"] else None]))
            parts.append(self.switch("Warnings by DM", warn["toggle_dm"], "Members get a DM when they're warned.",
                                     self.flips("warningset senddm", warn["toggle_dm"], ("true", "false"))))
        censor = bot.get_cog("Censord")
        if censor:
            filt = await censor.config.guild(guild).all()

            async def level_picked(interaction, value):
                await self.act(interaction, [f"censor level {value}"] if value else [])

            async def action_picked(interaction, value):
                await self.act(interaction, [f"censor action {value}"] if value else [])

            parts += self.field("Word filter", "Deletes messages with blocked words. Mods and admins aren't filtered.",
                                self.choice_select([("off", "Off", None), ("low", "Low", "Slurs only"),
                                                    ("high", "High", "Slurs and swearing")],
                                                   filt["global_level"], level_picked))
            parts += self.field("Repeat offenders", f"What happens when someone trips the filter "
                                                    f"{filt['threshold_count']} times within "
                                                    f"{filt['threshold_time']} seconds.",
                                self.choice_select([("delete", "Just delete", None), ("kick", "Kick them", None),
                                                    ("ban", "Ban them", None)], filt["action"], action_picked))
        spam = bot.get_cog("AntiSpam")
        if spam:
            conf = await spam.config.all()
            preset = next((name for name, (amount, per, length, _) in ANTISPAM_PRESETS.items()
                           if (conf["amount"], conf["per"], conf["mute_length"]) == (amount, per, length)), None)

            async def spam_picked(interaction, value):
                if value not in ANTISPAM_PRESETS:
                    return await self.act(interaction, [])
                amount, per, length, _ = ANTISPAM_PRESETS[value]
                await self.act(interaction, [f"antispamset amount {amount}", f"antispamset per {per} seconds",
                                             f"antispamset length {length} seconds"])

            explain = "Stops people flooding commands. It covers every server ButlerBot is in."
            if await bot.is_owner(self.member):
                parts += self.field("Command spam limit", explain, self.choice_select(
                    [(k, k.title(), d) for k, (_, _, _, d) in ANTISPAM_PRESETS.items()], preset, spam_picked,
                    placeholder="Custom"))
            else:
                parts.append(ui.two_line(f"**Command spam limit** · "
                                         f"{ANTISPAM_PRESETS[preset][3] if preset else 'custom'}",
                                         explain + " Only the bot owner can change it."))
        return parts

    async def page_fun(self) -> list:
        conf = await self.cog.bot.get_cog("Parlor").config.guild(self.guild).all()
        caption, mystery = conf["caption_weekly"].get("channel"), conf["mystery_weekly"].get("channel")
        return ["Weekly games run on their own once a week in the channel you pick. The first one starts right "
                "away.",
                *self.field("Weekly caption contest", "A picture goes up, members write captions and vote, and "
                                                      "ButlerBot gives its own award. Clear it to turn it off.",
                            self.channel_select(self.picked_one("caption weekly", "caption weekly off"),
                                                current=[caption], optional=True, placeholder="Off")),
                *self.field("Weekly murder mystery", f"A days-long mystery: members question suspects with "
                                                     f"`{self.p}interrogate` and name the culprit with "
                                                     f"`{self.p}accuse`. Clear it to turn it off.",
                            self.channel_select(self.picked_one("mystery weekly", "mystery weekly off"),
                                                current=[mystery], optional=True, placeholder="Off")),
                ui.hint(f"Games make their own threads. To keep them in a channel instead, run "
                        f"`{self.p}parlor threads off` there.")]

    async def page_apps(self) -> list:
        bot = self.cog.bot
        enabled = await self.cog.enabled_apps()
        available = [a for a in APP_COMMANDS if bot.get_cog(a[2])]
        rows = [ui.two_line(f"**{shown}** · " + ("On" if name in enabled.get(kind, {}) else "Off"), what)
                for name, kind, _, shown, what in available]
        off = [(name, kind) for name, kind, _, _, _ in available if name not in enabled.get(kind, {})]

        async def turn_on(interaction):
            await self.act(interaction, [f'slash enable "{name}" {kind}' for name, kind in off] + ["slash sync"])

        parts = ["Slash commands and right-click menus (Apps). They belong to the bot as a whole, so they're "
                 "switched on once for every server.", *rows]
        if not available:
            parts.append("None of the cogs with slash commands are loaded.")
        elif await bot.is_owner(self.member):
            if off:
                parts.append(self.action("Switch them on", "Turns on everything above that's off, then updates "
                                                           "Discord. They can take a few minutes to appear.",
                                         "Turn them on", turn_on, style=discord.ButtonStyle.primary))
        elif off:
            parts.append(ui.line(ui.LOCKED, "Only the bot owner can switch these on. Ask them to run this step."))
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
        group = cog.config.custom("AUTOROOM_SOURCE", str(guild.id), str(source.id))
        current = dict(await group.all())   # keeps settings made with autoroomset modify
        current.update(dest_category_id=category.id, room_type=draft["type"], channel_name_type=draft["names"])
        await group.set(current)
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
        wizard = Wizard(self, member, interaction.message, await self._prefix(interaction.guild))
        await wizard.show(interaction, edit=False)
