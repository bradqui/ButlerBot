"""
Estate cog for Red-DiscordBot: the bot owner's view of every server the bot is in.

Owner only, and it works in DMs:
- `[p]estate`: every server with its members and this month's AI spend, the month's total against the budget, and
  a health summary. `[p]estate server <name or ID>` shows one server, including servers the owner isn't in.
- `[p]estate budget` sets a monthly cap for the whole bot (it's one bill); `[p]estate cap` sets one for a server.
  The owner gets a DM at 50%, 80% and 100%, and AI pauses when a cap is reached.
- `[p]estate ai <server> off` switches AI off in a server remotely.
- New servers: a DM when the bot joins one, with a Leave button.
- `[p]estate health`: background tasks, recent errors, cogs that aren't loaded, missing permissions.

Numbers only: it never shows message content from other servers. The Claude and Gemini cogs ask `ai_blocked(guild)`
before every AI call; with this cog unloaded there are no caps and no remote switch.
"""

import contextlib
import importlib.util
import logging
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

import discord
from discord.ext import tasks
from redbot.core import Config, checks, commands
from redbot.core.bot import Red

log = logging.getLogger("red.estate")


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


# ==========================================
#                CONSTANTS
# ==========================================

TOPIC = "🏰"
IMAGE_COST = 0.039              # estimated US$ per Gemini image (Gemini's API doesn't report costs)
ALERT_STEPS = (50, 80, 100)     # percent of a budget at which the owner gets a DM
SPEND_CACHE_SECONDS = 60        # how long a spend total is reused before it's added up again
ERROR_WINDOW = 24 * 3600
OUR_COGS = {   # package -> cog class name: ours, so the health check can say which aren't loaded
    "activitystats": "ActivityStats", "buttongreeter": "ButtonGreeter", "censord": "Censord", "claude": "ClaudeChat",
    "estate": "Estate", "gamemanager": "GameManager", "gemini": "GeminiChat", "handbook": "Handbook",
    "parlor": "Parlor", "speakup": "SpeakUp",
}
NEEDED_PERMISSIONS = [   # (permission, how Discord labels it): what our features need
    ("send_messages", "Send Messages"), ("embed_links", "Embed Links"), ("attach_files", "Attach Files"),
    ("add_reactions", "Add Reactions"), ("read_message_history", "Read Message History"),
    ("manage_events", "Manage Events"), ("create_public_threads", "Create Public Threads"),
    ("send_messages_in_threads", "Send Messages in Threads"),
]


# ==========================================
#                 HELPERS
# ==========================================

def this_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def next_month_start() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime(now.year + (now.month == 12), now.month % 12 + 1, 1, tzinfo=timezone.utc)


def money(amount: float) -> str:
    return f"${amount:,.2f}"


def parse_amount(text: str) -> Tuple[bool, Optional[float]]:
    """(ok, amount) from "$50", "12.5" or "off" (None). ok is False when it isn't either."""
    text = (text or "").strip().lower().lstrip("$").replace(",", "")
    if text in ("off", "none", "no", "0", "0.00"):
        return True, None
    try:
        amount = float(text)
    except ValueError:
        return False, None
    return (amount > 0, round(amount, 2) if amount > 0 else None)


def split_last(text: str) -> Tuple[str, str]:
    """("server name", "last word") from "My Server 25"."""
    parts = (text or "").strip().rsplit(maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else ("", parts[0] if parts else "")


def missing_permissions(guild: discord.Guild) -> List[str]:
    perms = guild.me.guild_permissions if guild.me is not None else None
    return [label for name, label in NEEDED_PERMISSIONS if perms is None or not getattr(perms, name, False)]


class ErrorLog(logging.Handler):
    """Keeps the last errors logged by the bot (time, logger, first line), for the health check."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records: Deque[Tuple[float, str, str]] = deque(maxlen=200)

    def emit(self, record: logging.LogRecord):
        try:
            first = (record.getMessage() or "").strip().splitlines()[:1]
            self.records.append((record.created, record.name, (first[0] if first else "")[:200]))
        except Exception:
            pass

    def recent(self, seconds: float = ERROR_WINDOW) -> List[Tuple[float, str, str]]:
        since = time.time() - seconds
        return [r for r in self.records if r[0] >= since]


class LeaveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"est:leave:(?P<gid>\d+)"):
    """On the new-server DM: leave that server (owner only, after a confirmation)."""

    def __init__(self, gid: int):
        super().__init__(discord.ui.Button(label="Leave server", emoji="🚪", style=discord.ButtonStyle.secondary,
                                           custom_id=f"est:leave:{gid}"))
        self.gid = gid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["gid"]))

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Estate")
        if cog is not None:
            await cog.on_leave_button(interaction, self.gid)


class ConfirmLeave(ui.ExpiringView):
    expired_note = "Expired. Nothing was done."

    def __init__(self, cog: "Estate", owner_id: int, guild: discord.Guild):
        super().__init__(owner_id, timeout=120)
        self.cog, self.guild = cog, guild

    @discord.ui.button(label="Leave it", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        try:
            await self.guild.leave()
        except discord.HTTPException as e:
            log.warning("Couldn't leave %s: %s", self.guild.id, e)
            return await interaction.response.edit_message(content=ui.line(ui.FAIL, "Discord wouldn't let me leave."),
                                                           view=None)
        await interaction.response.edit_message(
            content=ui.line(ui.DONE, f"Left **{discord.utils.escape_markdown(self.guild.name)}**."), view=None)

    @discord.ui.button(label="Stay", style=discord.ButtonStyle.secondary)
    async def stay(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content=ui.line(None, "Staying."), view=None)


# ==========================================
#                   COG
# ==========================================

class Estate(commands.Cog):
    """The bot owner's view of every server: spend, budget caps, remote AI switch, new servers and health."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8301729465, force_registration=True)
        self.config.register_global(budget=None, alerted={}, join_alerts=True)
        self.config.register_guild(budget=None, ai_off=False)
        self.errors = ErrorLog()
        self._spend_cache: Tuple[float, str, Dict] = (0.0, "", {})
        self._started = time.time()

    async def cog_load(self):
        for name in ("red", "discord"):
            logging.getLogger(name).addHandler(self.errors)
        self.bot.add_dynamic_items(LeaveButton)
        self.alert_loop.start()

    async def cog_unload(self):
        self.alert_loop.cancel()
        self.bot.remove_dynamic_items(LeaveButton)
        for name in ("red", "discord"):
            logging.getLogger(name).removeHandler(self.errors)

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        return   # nothing about users is stored

    # ==========================================
    #               SPEND AND CAPS
    # ==========================================

    async def spend(self, month: Optional[str] = None, *, fresh: bool = False) -> Dict:
        """
        This month's spend: {"total", "claude", "images", "image_cost", "guilds": {id: {claude, images, cost}}}.
        Servers the bot has left still count toward the total; it's the same bill.
        """
        month = month or this_month()
        cached_at, cached_month, data = self._spend_cache
        if not fresh and cached_month == month and time.time() - cached_at < SPEND_CACHE_SECONDS:
            return data
        claude, gemini = self.bot.get_cog("ClaudeChat"), self.bot.get_cog("GeminiChat")
        usage = await claude.monthly_usage(month) if hasattr(claude, "monthly_usage") else {}
        images = await gemini.monthly_images(month) if hasattr(gemini, "monthly_images") else {}
        guilds: Dict[int, Dict] = {}
        for gid in set(usage) | set(images):
            c = float((usage.get(gid) or {}).get("cost", 0.0))
            n = int(images.get(gid, 0))
            guilds[gid] = {"claude": c, "images": n, "cost": c + n * IMAGE_COST}
        data = {"claude": sum(g["claude"] for g in guilds.values()), "images": sum(g["images"] for g in guilds.values()),
                "guilds": guilds}
        data["image_cost"] = data["images"] * IMAGE_COST
        data["total"] = data["claude"] + data["image_cost"]
        self._spend_cache = (time.time(), month, data)
        return data

    async def ai_blocked(self, guild: discord.Guild) -> Optional[str]:
        """For the Claude and Gemini cogs: why AI is off for this server right now, or None. No AI involved."""
        if await self.config.guild(guild).ai_off():
            return ui.line(ui.WARN, "AI features are switched off in this server for now.")
        data = None
        cap = await self.config.budget()
        if cap:
            data = await self.spend()
            if data["total"] >= cap:
                return ui.line(ui.WAIT, "The bot has used this month's AI budget, so AI features are paused.",
                               hint=f"They come back <t:{int(next_month_start().timestamp())}:R>.")
        guild_cap = await self.config.guild(guild).budget()
        if guild_cap:
            data = data or await self.spend()
            if (data["guilds"].get(guild.id) or {}).get("cost", 0.0) >= guild_cap:
                return ui.line(ui.WAIT, "This server has used its AI budget for the month, so AI features are paused.",
                               hint=f"They come back <t:{int(next_month_start().timestamp())}:R>.")
        return None

    @tasks.loop(minutes=5)
    async def alert_loop(self):
        """DM the owner when spend crosses 50%, 80% and 100% of the bot's budget or a server's."""
        month = this_month()
        data = await self.spend(fresh=True)
        checks_ = []
        cap = await self.config.budget()
        if cap:
            checks_.append(("all", "The bot", data["total"], cap))
        for gid, conf in (await self.config.all_guilds()).items():
            if conf.get("budget"):
                guild = self.bot.get_guild(gid)
                name = f"**{discord.utils.escape_markdown(guild.name)}**" if guild else f"Server {gid}"
                checks_.append((str(gid), name, (data["guilds"].get(gid) or {}).get("cost", 0.0), conf["budget"]))
        messages = []
        async with self.config.alerted() as alerted:
            for old in [m for m in alerted if m != month]:
                alerted.pop(old)
            seen = alerted.setdefault(month, {})
            for key, name, spent, limit in checks_:
                crossed = [step for step in ALERT_STEPS if spent >= limit * step / 100 and step not in seen.get(key, [])]
                if not crossed:
                    continue
                seen[key] = sorted(set(seen.get(key, [])) | set(crossed))
                step = max(crossed)
                text = (f"{name} has used {step}% of its {money(limit)} AI budget this month ({money(spent)})."
                        if step < 100 else f"{name} has reached its {money(limit)} AI budget for the month "
                                           f"({money(spent)}). AI features are paused until the month ends.")
                messages.append(ui.line(ui.WAIT if step == 100 else ui.WARN, text,
                                        hint="`estate budget` and `estate cap` change the limits."))
        for text in messages:
            with contextlib.suppress(Exception):
                await self.bot.send_to_owners(text, allowed_mentions=ui.NO_PINGS)

    @alert_loop.before_loop
    async def _before_alerts(self):
        await self.bot.wait_until_red_ready()

    # ==========================================
    #               NEW SERVERS
    # ==========================================

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        if not await self.config.join_alerts():
            return
        owner = guild.owner or (await self._fetch_owner(guild))
        view = discord.ui.View(timeout=None)
        view.add_item(LeaveButton(guild.id))
        text = ui.line(None, f"{TOPIC} I joined **{discord.utils.escape_markdown(guild.name)}**: "
                             f"{ui.plural(guild.member_count or 0, 'member')}, owned by "
                             f"{discord.utils.escape_markdown(owner.display_name) if owner else 'someone unknown'}.",
                       hint=f"Server ID {guild.id} · `estate server {guild.id}` shows more")
        if self.bot.get_cog("SetupWizard") is not None:
            text += "\n" + ui.hint("Its admins can run `setup` there for a guided setup.")
        with contextlib.suppress(Exception):
            await self.bot.send_to_owners(text, view=view, allowed_mentions=ui.NO_PINGS)

    async def _fetch_owner(self, guild: discord.Guild):
        if not guild.owner_id:
            return None
        with contextlib.suppress(discord.HTTPException):
            return await self.bot.fetch_user(guild.owner_id)
        return None

    async def on_leave_button(self, interaction: discord.Interaction, gid: int):
        if not await self.bot.is_owner(interaction.user):
            return await ui.respond(interaction, ui.line(ui.LOCKED, "Only the bot's owner can do that."))
        guild = self.bot.get_guild(gid)
        if guild is None:
            return await ui.respond(interaction, ui.line(ui.ASK, "I'm not in that server any more."))
        view = ConfirmLeave(self, interaction.user.id, guild)
        await interaction.response.send_message(
            ui.line(ui.WARN, f"Leave **{discord.utils.escape_markdown(guild.name)}**?",
                    hint="Its settings stay saved if I'm invited back."), view=view)
        view.message = interaction

    # ==========================================
    #                 COMMANDS
    # ==========================================

    def _find_guild(self, text: str) -> Tuple[Optional[discord.Guild], Optional[str]]:
        """A server by ID or name (exact, else a unique partial match), or (None, a line saying why not)."""
        text = (text or "").strip()
        if not text:
            return None, ui.line(ui.ASK, "Which server? Give its name or ID.")
        if text.isdigit():
            guild = self.bot.get_guild(int(text))
            return (guild, None) if guild else (None, ui.line(ui.ASK, f"I'm not in a server with ID {text}."))
        folded = text.casefold()
        exact = [g for g in self.bot.guilds if g.name.casefold() == folded]
        if len(exact) == 1:
            return exact[0], None
        partial = [g for g in self.bot.guilds if folded in g.name.casefold()]
        if len(partial) == 1:
            return partial[0], None
        if partial:
            names = ", ".join(f"{g.name} ({g.id})" for g in partial[:5])
            return None, ui.line(ui.ASK, f"More than one server matches. Use its ID: {names}.")
        return None, ui.line(ui.ASK, f"I'm not in a server called {text[:60]}.")

    async def _health(self) -> Dict:
        loops, stopped = 0, []
        for cog in list(self.bot.cogs.values()):
            for name in dir(type(cog)):
                if isinstance(getattr(type(cog), name, None), tasks.Loop):
                    loops += 1
                    if not getattr(cog, name).is_running():
                        stopped.append(f"{cog.qualified_name}.{name}")
        loaded = {type(c).__name__ for c in self.bot.cogs.values()}
        not_loaded = sorted(pkg for pkg, cls in OUR_COGS.items() if cls not in loaded)
        uptime = getattr(self.bot, "uptime", None)
        missing = {g.id: missing_permissions(g) for g in self.bot.guilds}
        return {"loops": loops, "stopped": stopped, "not_loaded": not_loaded, "errors": self.errors.recent(),
                "uptime": uptime, "missing": {gid: m for gid, m in missing.items() if m}}

    def _health_line(self, health: Dict) -> Tuple[str, str]:
        main = ("**Everything's running**" if not health["stopped"] and not health["errors"] else
                f"**{ui.plural(len(health['stopped']), 'background task')} stopped**" if health["stopped"] else
                f"**{ui.plural(len(health['errors']), 'error')} in the last day**")
        parts = [f"{health['loops'] - len(health['stopped'])} of {ui.plural(health['loops'], 'background task')} running"]
        if health["errors"] and health["stopped"]:
            parts.append(f"{ui.plural(len(health['errors']), 'error')} in the last day")
        if health["not_loaded"]:
            parts.append("not loaded: " + ", ".join(health["not_loaded"]))
        if health["missing"]:
            parts.append(f"{ui.plural(len(health['missing']), 'server')} missing permissions")
        if health["uptime"]:
            parts.append(f"up since <t:{int(health['uptime'].replace(tzinfo=timezone.utc).timestamp())}:R>")
        return main, " · ".join(parts)

    @commands.group(name="estate", invoke_without_command=True)
    @checks.is_owner()
    async def estate(self, ctx: commands.Context):
        """
        Every server the bot is in: members, this month's AI spend, the budget and the bot's health (owner).

        Works in DMs. Spend is Claude's reported cost plus an estimate for Gemini images. It shows numbers only,
        never anything people wrote.
        """
        p = ctx.clean_prefix
        data = await self.spend(fresh=True)
        cap = await self.config.budget()
        caps = {gid: c["budget"] for gid, c in (await self.config.all_guilds()).items() if c.get("budget")}
        off = {gid for gid, c in (await self.config.all_guilds()).items() if c.get("ai_off")}
        health = await self._health()
        detail = f"Claude {money(data['claude'])} · images ~{money(data['image_cost'])} ({data['images']})"
        detail += (f" · budget {money(cap)}, {data['total'] / cap:.0%} used" if cap else " · no monthly budget")
        rows, markers = [], set()
        for guild in sorted(self.bot.guilds, key=lambda g: -(data["guilds"].get(g.id) or {}).get("cost", 0.0)):
            spent = data["guilds"].get(guild.id) or {"cost": 0.0, "images": 0}
            marker = " 🔇" if guild.id in off else (" ⚠️" if guild.id in health["missing"] else "")
            markers.add(marker.strip())
            parts = [ui.plural(guild.member_count or 0, "member"), f"{money(spent['cost'])} this month"]
            if spent.get("images"):
                parts.append(ui.plural(spent["images"], "image"))
            if guild.id in caps:
                parts.append(f"cap {money(caps[guild.id])}")
            rows.append(ui.row(f"**{discord.utils.escape_markdown(guild.name)}**{marker}", " · ".join(parts)))
        legend = [text for mark, text in (("🔇", "🔇 AI switched off"), ("⚠️", "⚠️ missing permissions"))
                  if mark in markers]
        header = "\n".join([ui.two_line(f"**This month: {money(data['total'])}**", detail),
                            ui.two_line(*self._health_line(health))] + ([ui.hint(" · ".join(legend))] if legend else []))
        board = ui.Board(f"{TOPIC} The estate: {ui.plural(len(self.bot.guilds), 'server')}", rows, header=header,
                         footer=f"Owner only · `{p}estate server <name>` shows one", empty="I'm not in any servers.")
        await board.send(ctx)

    @estate.command(name="server")
    @checks.is_owner()
    async def estate_server(self, ctx: commands.Context, *, server: str = ""):
        """One server in detail: owner, members, spend, AI switch and budget, missing permissions (owner)."""
        guild, problem = self._find_guild(server)
        if guild is None:
            return await ctx.send(problem, allowed_mentions=ui.NO_PINGS)
        data = await self.spend(fresh=True)
        spent = data["guilds"].get(guild.id) or {"claude": 0.0, "images": 0, "cost": 0.0}
        conf = await self.config.guild(guild).all()
        claude = self.bot.get_cog("ClaudeChat")
        all_time = None
        if claude is not None and hasattr(claude, "config"):
            all_time = (await claude.config.guild(guild).usage()).get("cost")
        owner = guild.owner or await self._fetch_owner(guild)
        joined = guild.me.joined_at if guild.me is not None else None
        missing = missing_permissions(guild)
        rows = [("Members", f"{guild.member_count or 0:,}"),
                ("Owner", discord.utils.escape_markdown(owner.display_name) if owner else "unknown"),
                ("Bot joined", f"<t:{int(joined.timestamp())}:D>" if joined else "unknown"),
                ("AI", "Switched off by you" if conf["ai_off"] else "On"),
                ("Budget", money(conf["budget"]) if conf["budget"] else "None (the bot's budget applies)"),
                ("This month", f"{money(spent['cost'])}: Claude {money(spent['claude'])} · "
                               f"{ui.plural(spent['images'], 'image')} ~{money(spent['images'] * IMAGE_COST)}"),
                ("Claude, all time", money(all_time) if all_time is not None else "unknown"),
                ("Missing permissions", ", ".join(missing) if missing else "None")]
        p = ctx.clean_prefix
        view = ui.CardView(ui.card(ui.settings_text(rows), ui.SEPARATOR,
                                   title=f"{TOPIC} {ui.truncate(guild.name, 80)}", color=ui.BRAND,
                                   footer=f"Owner only · `{p}estate ai`, `{p}estate cap` and Red's `{p}servers` change "
                                          "these"))
        await ui.send_card(ctx, view)

    @estate.command(name="budget")
    @checks.is_owner()
    async def estate_budget(self, ctx: commands.Context, amount: str = ""):
        """
        The bot's monthly AI budget across every server, in US dollars (owner).

        You get a DM at 50%, 80% and 100%; at 100% AI features pause everywhere until the month ends.

        **Examples:** `[p]estate budget` (show it), `[p]estate budget 25`, `[p]estate budget off`
        """
        p = ctx.clean_prefix
        if not amount:
            cap = await self.config.budget()
            data = await self.spend(fresh=True)
            if not cap:
                return await ctx.send(ui.line(None, f"No monthly budget. This month so far: {money(data['total'])}.",
                                              hint=f"`{p}estate budget 25` sets one."))
            return await ctx.send(ui.line(None, f"The monthly budget is {money(cap)}; {money(data['total'])} "
                                                f"({data['total'] / cap:.0%}) is used so far.",
                                          hint=f"`{p}estate budget off` removes it."))
        ok, value = parse_amount(amount)
        if not ok:
            return await ctx.send(ui.line(ui.ASK, f"I couldn't read `{amount[:20]}` as an amount.",
                                          hint=f"Try `{p}estate budget 25` or `{p}estate budget off`."))
        await self.config.budget.set(value)
        self._spend_cache = (0.0, "", {})
        await ctx.send(ui.line(ui.DONE, f"The bot's monthly AI budget is {money(value)}." if value else
                               "The bot has no monthly AI budget now."))

    @estate.command(name="cap")
    @checks.is_owner()
    async def estate_cap(self, ctx: commands.Context, *, text: str = ""):
        """
        One server's monthly AI budget, in US dollars, on top of the bot's (owner).

        **Examples:** `[p]estate cap Gaming Hall 10`, `[p]estate cap 123456789012345678 off`
        """
        p = ctx.clean_prefix
        server, amount = split_last(text)
        ok, value = parse_amount(amount)
        if not server or not ok:
            return await ctx.send(ui.line(ui.ASK, "Give the server and an amount (or `off`).",
                                          hint=f"`{p}estate cap Gaming Hall 10`"))
        guild, problem = self._find_guild(server)
        if guild is None:
            return await ctx.send(problem, allowed_mentions=ui.NO_PINGS)
        await self.config.guild(guild).budget.set(value)
        name = discord.utils.escape_markdown(guild.name)
        await ctx.send(ui.line(ui.DONE, f"**{name}** has a monthly AI budget of {money(value)}." if value else
                               f"**{name}** has no budget of its own now."), allowed_mentions=ui.NO_PINGS)

    @estate.command(name="ai")
    @checks.is_owner()
    async def estate_ai(self, ctx: commands.Context, *, text: str = ""):
        """
        Switch AI features off (or back on) in one server, without being there (owner).

        **Examples:** `[p]estate ai Gaming Hall off`, `[p]estate ai Gaming Hall on`
        """
        p = ctx.clean_prefix
        server, setting = split_last(text)
        if not server or setting.lower() not in ("on", "off"):
            return await ctx.send(ui.line(ui.ASK, "Give the server, then `on` or `off`.",
                                          hint=f"`{p}estate ai Gaming Hall off`"))
        guild, problem = self._find_guild(server)
        if guild is None:
            return await ctx.send(problem, allowed_mentions=ui.NO_PINGS)
        await self.config.guild(guild).ai_off.set(setting.lower() == "off")
        name = discord.utils.escape_markdown(guild.name)
        await ctx.send(ui.line(ui.DONE, f"AI features are off in **{name}**." if setting.lower() == "off" else
                               f"AI features are on in **{name}** again."), allowed_mentions=ui.NO_PINGS)

    @estate.command(name="health")
    @checks.is_owner()
    async def estate_health(self, ctx: commands.Context):
        """Background tasks, recent errors, cogs that aren't loaded, and servers missing permissions (owner)."""
        health = await self._health()
        blocks = [ui.two_line(*self._health_line(health))]
        if health["stopped"]:
            blocks.append(ui.two_line("**Stopped background tasks**", ", ".join(health["stopped"])))
        if health["errors"]:
            lines = [f"<t:{int(at)}:R> · {name}: {ui.truncate(text, 120)}" for at, name, text in health["errors"][-5:]]
            blocks.append("**Latest errors**\n" + "\n".join(ui.hint(line) for line in reversed(lines)))
        for gid, missing in list(health["missing"].items())[:8]:
            guild = self.bot.get_guild(gid)
            blocks.append(ui.two_line(f"**{discord.utils.escape_markdown(guild.name) if guild else gid}** ⚠️",
                                      "Missing " + ", ".join(missing)))
        view = ui.CardView(ui.card(*blocks, title=f"{TOPIC} Health", color=ui.BRAND,
                                   footer="Owner only · errors are kept until a restart"))
        await ui.send_card(ctx, view)

    @estate.command(name="alerts")
    @checks.is_owner()
    async def estate_alerts(self, ctx: commands.Context, setting: str = ""):
        """Turn the DM about each new server the bot joins on or off (owner). Budget alerts always come."""
        setting = setting.lower().strip()
        if setting in ("on", "off"):
            await self.config.join_alerts.set(setting == "on")
        on = await self.config.join_alerts()
        await ctx.send(ui.line(ui.DONE if setting in ("on", "off") else None,
                               "You get a DM when I join a new server." if on else "No DM when I join a new server.",
                               hint=f"`{ctx.clean_prefix}estate alerts {'off' if on else 'on'}` changes it."))
