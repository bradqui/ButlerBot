"""
Activity Stats cog for Red-DiscordBot.

Counts messages, voice time and games played as they happen and keeps hourly totals (never message text) in a
small SQLite database. Everyone can see general stats: channel activity, leaderboards, a heatmap of busy times,
voice and games, and their own numbers. Admins also get member, retention, channel-health, command-usage and
game-night reports, and an optional weekly digest. The Claude cog's bot guide and AI chat can answer stats
questions through `guide_tools`.
"""

import asyncio
import io
import json
import logging
import re
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord.ext import tasks
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path

log = logging.getLogger("red.activitystats")

ChannelArg = Union[discord.TextChannel, discord.VoiceChannel, discord.ForumChannel, discord.StageChannel,
                   discord.Thread]


# ==========================================
#                CONSTANTS
# ==========================================

DAY = 86400
FLUSH_SECONDS = 60
MIN_VOICE_SECONDS = 60          # shorter voice visits aren't recorded
MIN_GAME_SECONDS = 300          # shorter game sessions aren't recorded
MAX_DAYS = 365
BACKFILL_MAX_DAYS = 90
TOP_COUNT = 10
ATTENDANCE_EARLY_MINUTES = 15   # joining voice this long before a session starts counts as showing up
ATTENDANCE_WINDOW_HOURS = 3     # ...and up to this long after it starts
QUIET_MIN_MESSAGES = 10         # "went quiet": at least this many messages 31-90 days ago and none since
MAX_NAMES = 25                  # names listed in one report line

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAY_INPUT = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2,
                 "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4, "friday": 4,
                 "sat": 5, "saturday": 5, "sun": 6, "sunday": 6}
MEDALS = ["🥇", "🥈", "🥉"]
MEMBER_COLOR = discord.Color.blurple()
ADMIN_COLOR = discord.Color.dark_teal()

CHART_BG = "#313338"
CHART_FG = "#dbdee1"
CHART_GRID = "#4e5058"
CHART_COLORS = ["#5865f2", "#57f287", "#fee75c", "#eb459e", "#ed4245", "#3ba55c"]

MEMBER_REPORTS = ("overview", "channels", "channel", "top", "heatmap", "voice", "me", "games")
ADMIN_REPORTS = ("active", "retention", "quiet", "joins", "dead_channels", "attendance", "commands", "unmet",
                 "libraries")

# The read-only lookup the Claude cog's bot guide and AI chat can call (see ActivityStats.guide_call_tool).
STATS_TOOL = {
    "name": "stats_report",
    "description": (
        "Look up this server's activity stats. Reports for everyone: overview (the last week at a glance), "
        "channels (messages per channel), channel (one channel's activity and top posters), top (who posted the "
        "most), heatmap (busiest days and hours), voice (voice channel time), me (one member's own stats), games "
        "(most-played games). Admin-only reports: active (daily/weekly/monthly active members), retention (do new "
        "members stick around), quiet (lurkers and members who went quiet), joins (joins and leaves), "
        "dead_channels, attendance (game sessions: who joined vs. who showed up), commands (bot command usage), "
        "unmet (guide questions no command could answer), libraries (who has a game library). Admin reports are "
        "refused for other people."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "report": {"type": "string", "enum": list(MEMBER_REPORTS + ADMIN_REPORTS)},
            "target": {"type": "string",
                       "description": "A channel name for channel, top or heatmap; a member's name or \"me\" for "
                                      "me; otherwise an empty string."},
            "days": {"type": "integer",
                     "description": "How many days back to look, or 0 for the report's default (for top, 0 means "
                                    "all time)."},
        },
        "required": ["report", "target", "days"],
        "additionalProperties": False,
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    guild INTEGER NOT NULL, channel INTEGER NOT NULL, user INTEGER NOT NULL, hour INTEGER NOT NULL,
    count INTEGER NOT NULL, PRIMARY KEY (guild, channel, user, hour));
CREATE INDEX IF NOT EXISTS messages_by_hour ON messages (guild, hour);
CREATE TABLE IF NOT EXISTS voice (
    guild INTEGER NOT NULL, channel INTEGER NOT NULL, user INTEGER NOT NULL, start INTEGER NOT NULL,
    end INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS voice_by_end ON voice (guild, end);
CREATE TABLE IF NOT EXISTS games (
    guild INTEGER NOT NULL, user INTEGER NOT NULL, game TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS games_by_end ON games (guild, end);
CREATE TABLE IF NOT EXISTS member_events (
    guild INTEGER NOT NULL, user INTEGER NOT NULL, event TEXT NOT NULL, ts INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS member_events_by_ts ON member_events (guild, ts);
CREATE TABLE IF NOT EXISTS command_uses (
    guild INTEGER NOT NULL, user INTEGER NOT NULL, command TEXT NOT NULL, ok INTEGER NOT NULL, ts INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS command_uses_by_ts ON command_uses (guild, ts);
CREATE TABLE IF NOT EXISTS unmet_questions (
    guild INTEGER NOT NULL, user INTEGER NOT NULL, question TEXT NOT NULL, ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS game_sessions (
    guild INTEGER NOT NULL, sid TEXT NOT NULL, title TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
    joined TEXT NOT NULL, showed TEXT NOT NULL, PRIMARY KEY (guild, sid));
"""
USER_TABLES = ("messages", "voice", "games", "member_events", "command_uses", "unmet_questions")


# ==========================================
#                 HELPERS
# ==========================================

def hour_of(ts: float) -> int:
    return int(ts // 3600 * 3600)


def load_zone(name: Optional[str]) -> tzinfo:
    try:
        return ZoneInfo(name) if name else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def local_day(ts: float, tz: tzinfo) -> date:
    return datetime.fromtimestamp(ts, tz).date()


def day_range(since: float, until: float, tz: tzinfo) -> List[date]:
    first, last = local_day(since, tz), local_day(until, tz)
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def split_by_day(start: float, end: float, tz: tzinfo) -> Iterable[Tuple[date, float]]:
    """(local day, seconds) pieces of a time span that may cross midnight."""
    while start < end:
        local = datetime.fromtimestamp(start, tz)
        midnight = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), tz).timestamp()
        piece_end = min(end, midnight)
        yield local.date(), piece_end - start
        start = piece_end


def hour_label(hour: int) -> str:
    return f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"


def fmt_hours(seconds: float) -> str:
    hours = seconds / 3600
    return f"{hours:.1f} h" if hours < 10 else f"{hours:,.0f} h"


def pct(part: float, whole: float) -> str:
    return f"{part / whole:.0%}" if whole else "n/a"


def change(current: float, previous: float) -> str:
    if not previous:
        return ""
    delta = (current - previous) / previous
    return f" ({'+' if delta >= 0 else ''}{delta:.0%} vs. the period before)"


def period_label(days: int) -> str:
    return {0: "all time", 1: "today", 7: "this week", 30: "this month", 365: "this year"}.get(
        days, f"last {days} days")


def parse_period(text: str) -> Optional[int]:
    """Days for "week", "month", "all", "14d", "2 weeks", "90"... 0 = all time."""
    text = text.strip().lower()
    words = {"all": 0, "alltime": 0, "all-time": 0, "ever": 0, "today": 1, "day": 1, "week": 7, "weekly": 7,
             "month": 30, "monthly": 30, "year": 365, "yearly": 365}
    if text in words:
        return words[text]
    match = re.fullmatch(r"(\d+)\s*(d|days?|w|weeks?|m|months?|y|years?)?", text)
    if not match:
        return None
    unit = (match.group(2) or "d")[0]
    days = int(match.group(1)) * {"d": 1, "w": 7, "m": 30, "y": 365}[unit]
    return max(1, min(days, MAX_DAYS))


def playing(member: discord.Member) -> Set[str]:
    return {a.name[:100] for a in member.activities if a.type == discord.ActivityType.playing and a.name}


def simplify(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


class Period(commands.Converter):
    async def convert(self, ctx: commands.Context, argument: str) -> int:
        days = parse_period(argument)
        if days is None:
            raise commands.BadArgument(f"`{argument}` isn't a time period. Try `week`, `month`, `90d` or `all`.")
        return days


@dataclass
class Report:
    title: str
    lines: List[str] = field(default_factory=list)
    chart: Optional[Callable[[], bytes]] = None   # draws a PNG; runs in a worker thread
    admin: bool = False


# ==========================================
#                 STORAGE
# ==========================================

class StatsDB:
    """SQLite in the cog's data folder. Calls run in a worker thread so the bot never blocks on disk."""

    def __init__(self, path):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.lock = threading.Lock()

    def _run(self, sql: str, params, many: bool) -> list:
        with self.lock:
            cursor = self.conn.executemany(sql, params) if many else self.conn.execute(sql, params)
            rows = cursor.fetchall()
            self.conn.commit()
            return rows

    async def query(self, sql: str, params=()) -> list:
        return await asyncio.to_thread(self._run, sql, tuple(params), False)

    async def execute_many(self, sql: str, rows: list):
        if rows:
            await asyncio.to_thread(self._run, sql, rows, True)

    def close(self):
        with self.lock:
            self.conn.close()


# ==========================================
#                  CHARTS
# ==========================================

_chart_lock = threading.Lock()


def _figure(width: float = 8, height: float = 3.6):
    from matplotlib.figure import Figure   # imported lazily: only charts need it
    fig = Figure(figsize=(width, height), dpi=110, facecolor=CHART_BG)
    ax = fig.add_subplot(111)
    ax.set_facecolor(CHART_BG)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(CHART_GRID)
    ax.tick_params(colors=CHART_FG, labelsize=8)
    return fig, ax


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    return buf.getvalue()


def daily_chart(days: List[date], series: Dict[str, List[float]], ylabel: str) -> bytes:
    """One line per series over days. The first series is drawn thickest (usually the total)."""
    from matplotlib.dates import AutoDateLocator, DateFormatter
    with _chart_lock:
        fig, ax = _figure()
        ax.grid(axis="y", color=CHART_GRID, linewidth=0.5, alpha=0.6)
        for i, (name, values) in enumerate(series.items()):
            ax.plot(days, values, label=name, color=CHART_COLORS[i % len(CHART_COLORS)],
                    linewidth=2.4 if i == 0 else 1.4, marker="o" if len(days) <= 14 else None, markersize=3)
        ax.set_ylabel(ylabel, color=CHART_FG, fontsize=9)
        ax.set_ylim(bottom=0)
        ax.xaxis.set_major_locator(AutoDateLocator(maxticks=8))
        ax.xaxis.set_major_formatter(DateFormatter("%b %d"))
        if len(series) > 1:
            ax.legend(fontsize=8, facecolor=CHART_BG, edgecolor=CHART_GRID, labelcolor=CHART_FG, loc="upper left")
        return _png(fig)


def heatmap_chart(grid: List[List[float]], tz_name: str) -> bytes:
    with _chart_lock:
        fig, ax = _figure(8, 3.2)
        image = ax.imshow(grid, aspect="auto", cmap="magma", interpolation="nearest")
        ax.set_yticks(range(7), WEEKDAYS)
        ax.set_xticks(range(0, 24, 3), [hour_label(h) for h in range(0, 24, 3)])
        ax.set_xlabel(f"Hour of the day ({tz_name})", color=CHART_FG, fontsize=9)
        bar = fig.colorbar(image, ax=ax, pad=0.02)
        bar.ax.tick_params(colors=CHART_FG, labelsize=7)
        bar.set_label("messages", color=CHART_FG, fontsize=8)
        return _png(fig)


# ==========================================
#                   COG
# ==========================================

class ActivityStats(commands.Cog):
    """Server activity stats: channels, leaderboards, busy times, voice and games, plus admin reports."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=7734152096, force_registration=True)
        self.config.register_guild(
            started_at=None,        # when live tracking began here (unix seconds)
            backfilled_from=None,   # the earliest time a backfill has covered
            excluded_channels=[],
            track_games=True,
            digest_enabled=False,
            digest_channel=None,
            digest_day=0,           # Monday
            digest_hour=9,          # in the server's GameManager timezone, else UTC
            digest_last=None,       # date of the last digest sent
        )
        self.config.register_user(ignored=False)
        self.db: Optional[StatsDB] = None
        self._pending: Counter = Counter()                          # (guild, channel, user, hour) -> messages
        self._voice_open: Dict[Tuple[int, int], Tuple[int, float]] = {}   # (guild, user) -> (channel, start)
        self._games_open: Dict[Tuple[int, int, str], float] = {}         # (guild, user, game) -> start
        self._ignored: Set[int] = set()
        self._excluded: Dict[int, Set[int]] = {}
        self._track_games: Dict[int, bool] = {}
        self._startup_task: Optional[asyncio.Task] = None
        self._backfills: Dict[int, asyncio.Task] = {}

    async def cog_load(self):
        self.db = StatsDB(cog_data_path(self) / "stats.db")
        self._ignored = {uid for uid, data in (await self.config.all_users()).items() if data.get("ignored")}
        for gid, data in (await self.config.all_guilds()).items():
            self._excluded[gid] = set(data.get("excluded_channels", []))
            self._track_games[gid] = data.get("track_games", True)
        self.flush_loop.start()
        self.digest_loop.start()
        self._startup_task = asyncio.create_task(self._startup())

    async def cog_unload(self):
        self.flush_loop.cancel()
        self.digest_loop.cancel()
        for task in [self._startup_task, *self._backfills.values()]:
            if task is not None:
                task.cancel()
        now = time.time()
        for gid, uid in list(self._voice_open):
            await self._close_voice(gid, uid, now)
        for key in list(self._games_open):
            await self._close_game(*key, now)
        await self.flush()
        self.db.close()

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        await self._forget_user(user_id)
        await self.config.user_from_id(user_id).clear()

    async def _forget_user(self, user_id: int):
        self._pending = Counter({k: v for k, v in self._pending.items() if k[2] != user_id})
        for key in [k for k in self._voice_open if k[1] == user_id]:
            self._voice_open.pop(key)
        for key in [k for k in self._games_open if k[1] == user_id]:
            self._games_open.pop(key)
        for table in USER_TABLES:
            await self.db.query(f"DELETE FROM {table} WHERE user = ?", (user_id,))

    async def _startup(self):
        await self.bot.wait_until_red_ready()
        now = time.time()
        for guild in self.bot.guilds:
            await self._ensure_started(guild)
            for channel in [*guild.voice_channels, *guild.stage_channels]:
                for member in channel.members:
                    if self._tracks_voice(member, channel):
                        self._voice_open.setdefault((guild.id, member.id), (channel.id, now))
            if self._track_games.get(guild.id, True):
                for member in guild.members:
                    if not member.bot and member.id not in self._ignored:
                        for game in playing(member):
                            self._games_open.setdefault((guild.id, member.id, game), now)

    async def _ensure_started(self, guild: discord.Guild):
        if await self.config.guild(guild).started_at() is None:
            await self.config.guild(guild).started_at.set(int(time.time()))

    async def _data_start(self, guild: discord.Guild) -> float:
        conf = self.config.guild(guild)
        started = await conf.started_at() or time.time()
        backfilled = await conf.backfilled_from()
        return min(started, backfilled) if backfilled else started

    # ==========================================
    #                 TRACKING
    # ==========================================

    @staticmethod
    def _channel_key(channel) -> int:
        """Threads (and forum posts) count toward their parent channel."""
        return channel.parent_id if isinstance(channel, discord.Thread) and channel.parent_id else channel.id

    def _tracks_voice(self, member: discord.Member, channel) -> bool:
        return (not member.bot and member.id not in self._ignored and channel != member.guild.afk_channel
                and channel.id not in self._excluded.get(member.guild.id, ()))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None or message.author.bot or message.webhook_id or message.author.id in self._ignored:
            return
        channel_id = self._channel_key(message.channel)
        if channel_id in self._excluded.get(message.guild.id, ()):
            return
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        self._pending[(message.guild.id, channel_id, message.author.id, hour_of(time.time()))] += 1

    async def flush(self):
        if not self._pending:
            return
        rows, self._pending = [(*key, n) for key, n in self._pending.items()], Counter()
        await self.db.execute_many(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?) ON CONFLICT (guild, channel, user, hour) "
            "DO UPDATE SET count = count + excluded.count", rows)

    @tasks.loop(seconds=FLUSH_SECONDS)
    async def flush_loop(self):
        try:
            await self.flush()
        except Exception:
            log.exception("Couldn't save message counts")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState):
        if member.bot or before.channel == after.channel:
            return
        now = time.time()
        await self._close_voice(member.guild.id, member.id, now)
        if after.channel is not None and self._tracks_voice(member, after.channel):
            self._voice_open[(member.guild.id, member.id)] = (after.channel.id, now)

    async def _close_voice(self, guild_id: int, user_id: int, now: float):
        entry = self._voice_open.pop((guild_id, user_id), None)
        if entry and now - entry[1] >= MIN_VOICE_SECONDS:
            await self.db.query("INSERT INTO voice VALUES (?, ?, ?, ?, ?)",
                                (guild_id, entry[0], user_id, int(entry[1]), int(now)))

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.bot or after.id in self._ignored or not self._track_games.get(after.guild.id, True):
            return
        old, new = playing(before), playing(after)
        if old == new:
            return
        now = time.time()
        for game in old - new:
            await self._close_game(after.guild.id, after.id, game, now)
        for game in new - old:
            self._games_open.setdefault((after.guild.id, after.id, game), now)

    async def _close_game(self, guild_id: int, user_id: int, game: str, now: float):
        start = self._games_open.pop((guild_id, user_id, game), None)
        if start and now - start >= MIN_GAME_SECONDS:
            await self.db.query("INSERT INTO games VALUES (?, ?, ?, ?, ?)",
                                (guild_id, user_id, game, int(start), int(now)))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.bot:
            await self.db.query("INSERT INTO member_events VALUES (?, ?, 'join', ?)",
                                (member.guild.id, member.id, int(time.time())))

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        now = time.time()
        await self._close_voice(member.guild.id, member.id, now)
        for key in [k for k in self._games_open if k[:2] == (member.guild.id, member.id)]:
            await self._close_game(*key, now)
        await self.db.query("INSERT INTO member_events VALUES (?, ?, 'leave', ?)",
                            (member.guild.id, member.id, int(now)))

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._ensure_started(guild)

    async def _record_command(self, guild: Optional[discord.Guild], user, command: str, ok: bool):
        if guild is None or user.bot or user.id in self._ignored:
            return
        await self.db.query("INSERT INTO command_uses VALUES (?, ?, ?, ?, ?)",
                            (guild.id, user.id, command[:80], int(ok), int(time.time())))

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        await self._record_command(ctx.guild, ctx.author, ctx.command.qualified_name, True)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.CommandNotFound):
            await self._record_command(ctx.guild, ctx.author, f"?{ctx.invoked_with or ''}", False)
        elif ctx.command is not None:
            await self._record_command(ctx.guild, ctx.author, ctx.command.qualified_name, False)

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction, command):
        await self._record_command(interaction.guild, interaction.user, f"/{command.qualified_name}", True)

    @commands.Cog.listener()
    async def on_gm_session_ended(self, guild: discord.Guild, session: dict):
        """GameManager dispatches this when a play session ends. Record who joined and who showed up in voice."""
        try:
            created = datetime.fromisoformat(session["created_at"])
            start = datetime.fromisoformat(session["starts_at"]) if session.get("starts_at") else created
        except (KeyError, TypeError, ValueError):
            return
        start_ts, now = (start if start.tzinfo else start.replace(tzinfo=timezone.utc)).timestamp(), time.time()
        if start_ts > now:
            return  # ended before it began
        window = (start_ts - ATTENDANCE_EARLY_MINUTES * 60, min(now, start_ts + ATTENDANCE_WINDOW_HOURS * 3600))
        showed = {uid for _, uid, s, e in await self._voice_rows(guild, *window) if e - s >= MIN_VOICE_SECONDS}
        joined = [int(u) for u in session.get("participants", [])]
        await self.db.query(
            "INSERT OR REPLACE INTO game_sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild.id, str(session.get("id")), str(session.get("title", ""))[:200], int(start_ts), int(now),
             json.dumps(joined), json.dumps(sorted(showed))))

    async def record_unmet(self, guild: discord.Guild, user: discord.abc.User, question: str):
        """Called by the Claude cog when the bot guide finds no command for a question."""
        if user.id not in self._ignored and question.strip():
            await self.db.query("INSERT INTO unmet_questions VALUES (?, ?, ?, ?)",
                                (guild.id, user.id, question.strip()[:500], int(time.time())))

    # ==========================================
    #                DATA ACCESS
    # ==========================================

    async def _message_rows(self, guild: discord.Guild, since: float, until: Optional[float] = None,
                            channel_id: Optional[int] = None) -> List[Tuple[int, int, int, int]]:
        """(channel, user, hour, count) rows from `since`, counting messages not saved yet too."""
        await self.flush()
        sql, params = "SELECT channel, user, hour, count FROM messages WHERE guild = ? AND hour >= ?", [
            guild.id, hour_of(since)]
        if until is not None:
            sql += " AND hour < ?"
            params.append(hour_of(until))
        if channel_id is not None:
            sql += " AND channel = ?"
            params.append(channel_id)
        return await self.db.query(sql, params)

    async def _voice_rows(self, guild: discord.Guild, since: float, until: float) -> List[Tuple[int, int, float, float]]:
        """(channel, user, start, end) voice visits clipped to [since, until], including ones still going."""
        rows = await self.db.query("SELECT channel, user, start, end FROM voice WHERE guild = ? AND end > ? AND start < ?",
                                   (guild.id, since, until))
        rows += [(cid, uid, start, time.time()) for (gid, uid), (cid, start) in self._voice_open.items()
                 if gid == guild.id]
        return [(c, u, max(s, since), min(e, until)) for c, u, s, e in rows if min(e, until) > max(s, since)]

    async def _game_rows(self, guild: discord.Guild, since: float, until: float) -> List[Tuple[int, str, float, float]]:
        rows = await self.db.query("SELECT user, game, start, end FROM games WHERE guild = ? AND end > ? AND start < ?",
                                   (guild.id, since, until))
        rows += [(uid, game, start, time.time()) for (gid, uid, game), start in self._games_open.items()
                 if gid == guild.id]
        return [(u, g, max(s, since), min(e, until)) for u, g, s, e in rows if min(e, until) > max(s, since)]

    async def _tz(self, member: discord.Member) -> Tuple[tzinfo, str]:
        """The member's GameManager timezone, else the server's, else UTC."""
        gm = self.bot.get_cog("GameManager")
        if gm is not None and hasattr(gm, "timezone_for"):
            try:
                tz, name, _ = await gm.timezone_for(member)
                return tz, name
            except Exception:
                log.debug("GameManager timezone lookup failed", exc_info=True)
        return timezone.utc, "UTC"

    async def _guild_tz(self, guild: discord.Guild) -> Tuple[tzinfo, str]:
        gm = self.bot.get_cog("GameManager")
        name = await gm.config.guild(guild).timezone() if gm is not None else None
        return load_zone(name), name or "UTC"

    async def _is_admin(self, member: discord.Member) -> bool:
        return (await self.bot.is_owner(member) or member.guild_permissions.administrator
                or member.guild_permissions.manage_guild or await self.bot.is_admin(member))

    @staticmethod
    def _can_see(viewer: Optional[discord.Member], guild: discord.Guild, channel_id: int) -> bool:
        """Members see stats only for channels they can open. `viewer` None means an admin report: everything."""
        if viewer is None:
            return True
        channel = guild.get_channel(channel_id)
        return channel is not None and channel.permissions_for(viewer).view_channel

    @staticmethod
    def _channel_name(guild: discord.Guild, channel_id: int) -> str:
        return f"<#{channel_id}>" if guild.get_channel(channel_id) else "#deleted-channel"

    async def _prefix(self, guild: Optional[discord.Guild]) -> str:
        for prefix in await self.bot.get_valid_prefixes(guild):
            if not prefix.startswith("<@"):
                return prefix
        return "!"

    async def _coverage_note(self, guild: discord.Guild, since: float) -> Optional[str]:
        start = await self._data_start(guild)
        if start > since:
            return f"-# Tracking started <t:{int(start)}:R>, so earlier days are empty."
        return None

    # ==========================================
    #          REPORTS FOR EVERYONE
    # ==========================================

    async def report_overview(self, viewer: discord.Member, days: int = 7) -> Report:
        guild, now = viewer.guild, time.time()
        days = days or 7
        tz, tz_name = await self._tz(viewer)
        since = now - days * DAY
        total = previous = 0
        per_channel, slots, daily, users = Counter(), Counter(), Counter(), set()
        for cid, uid, hour, n in await self._message_rows(guild, since - days * DAY):
            if not self._can_see(viewer, guild, cid):
                continue
            if hour < hour_of(since):
                previous += n
                continue
            total += n
            per_channel[cid] += n
            users.add(uid)
            local = datetime.fromtimestamp(hour, tz)
            daily[local.date()] += n
            slots[(local.weekday(), local.hour)] += n
        report = Report(f"📊 {guild.name}: {period_label(days)}")
        report.lines.append(f"💬 **{total:,}** messages from **{len(users)}** members{change(total, previous)}")
        if per_channel:
            report.lines.append("🔥 Busiest channels: " + ", ".join(
                f"{self._channel_name(guild, c)} ({n:,})" for c, n in per_channel.most_common(3)))
        if slots:
            (weekday, hour), _ = slots.most_common(1)[0]
            report.lines.append(f"🕘 Busiest hour: **{WEEKDAYS[weekday]} {hour_label(hour)}** ({tz_name})")
        voice = sum(e - s for c, _, s, e in await self._voice_rows(guild, since, now) if self._can_see(viewer, guild, c))
        if voice:
            report.lines.append(f"🔊 **{fmt_hours(voice)}** in voice")
        games = Counter()
        for _, game, s, e in await self._game_rows(guild, since, now):
            games[game] += e - s
        if games:
            game, seconds = games.most_common(1)[0]
            report.lines.append(f"🎮 Most played: **{game}** ({fmt_hours(seconds)})")
        if note := await self._coverage_note(guild, since):
            report.lines.append(note)
        days_list = day_range(since, now, tz)
        report.chart = lambda: daily_chart(days_list, {"Messages": [daily[d] for d in days_list]}, "messages")
        return report

    async def report_channels(self, viewer: Optional[discord.Member], guild: discord.Guild, days: int = 30) -> Report:
        days, now = days or 30, time.time()
        tz, _ = await self._tz(viewer) if viewer else await self._guild_tz(guild)
        since = now - days * DAY
        per_channel, per_day = Counter(), defaultdict(Counter)
        for cid, _, hour, n in await self._message_rows(guild, since):
            if self._can_see(viewer, guild, cid):
                per_channel[cid] += n
                per_day[cid][local_day(hour, tz)] += n
        report = Report(f"💬 Messages per channel: {period_label(days)}")
        total = sum(per_channel.values())
        report.lines.append(f"**{total:,}** messages in **{len(per_channel)}** channels, "
                            f"about **{total / days:,.0f}** a day.")
        for cid, n in per_channel.most_common(15):
            report.lines.append(f"{self._channel_name(guild, cid)}: **{n:,}** ({n / days:,.1f}/day)")
        if note := await self._coverage_note(guild, since):
            report.lines.append(note)
        days_list = day_range(since, now, tz)
        series = {"All channels": [sum(per_day[c][d] for c in per_day) for d in days_list]}
        for cid, _ in per_channel.most_common(5):
            channel = guild.get_channel(cid)
            series[f"#{channel.name}" if channel else "#deleted"] = [per_day[cid][d] for d in days_list]
        report.chart = lambda: daily_chart(days_list, series, "messages per day")
        return report

    async def report_channel(self, viewer: discord.Member, channel_id: int, days: int = 30) -> Report:
        guild, now = viewer.guild, time.time()
        days = days or 30
        tz, tz_name = await self._tz(viewer)
        since = now - days * DAY
        daily, posters, hours = Counter(), Counter(), Counter()
        for _, uid, hour, n in await self._message_rows(guild, since, channel_id=channel_id):
            daily[local_day(hour, tz)] += n
            posters[uid] += n
            hours[datetime.fromtimestamp(hour, tz).hour] += n
        total = sum(daily.values())
        name = self._channel_name(guild, channel_id)
        report = Report(f"💬 #{getattr(guild.get_channel(channel_id), 'name', 'deleted')}: {period_label(days)}")
        report.lines.append(f"{name}: **{total:,}** messages from **{len(posters)}** members, "
                            f"about **{total / days:,.1f}** a day.")
        if daily:
            best_day, best = daily.most_common(1)[0]
            report.lines.append(f"📅 Busiest day: **{best_day:%a %b %d}** ({best:,})")
            report.lines.append(f"🕘 Busiest hour: **{hour_label(hours.most_common(1)[0][0])}** ({tz_name})")
            report.lines.append("🏆 Top posters: " + ", ".join(
                f"<@{u}> ({n:,})" for u, n in posters.most_common(5) if guild.get_member(u)))
        if note := await self._coverage_note(guild, since):
            report.lines.append(note)
        days_list = day_range(since, now, tz)
        report.chart = lambda: daily_chart(days_list, {"Messages": [daily[d] for d in days_list]}, "messages per day")
        return report

    async def report_top(self, viewer: discord.Member, channel_id: Optional[int] = None, days: int = 30) -> Report:
        guild = viewer.guild
        since = 0 if days == 0 else time.time() - days * DAY
        counts = Counter()
        for cid, uid, _, n in await self._message_rows(guild, since, channel_id=channel_id):
            if self._can_see(viewer, guild, cid):
                counts[uid] += n
        ranked = [(uid, n) for uid, n in counts.most_common() if guild.get_member(uid)]
        where = f" in #{getattr(guild.get_channel(channel_id), 'name', 'deleted')}" if channel_id else ""
        report = Report(f"🏆 Top posters{where}: {period_label(days)}")
        for i, (uid, n) in enumerate(ranked[:TOP_COUNT]):
            report.lines.append(f"{MEDALS[i] if i < 3 else f'`{i + 1}.`'} <@{uid}>: **{n:,}**")
        mine = next((i for i, (uid, _) in enumerate(ranked) if uid == viewer.id), None)
        if mine is not None and mine >= TOP_COUNT:
            report.lines.append(f"…\n`{mine + 1}.` You: **{ranked[mine][1]:,}**")
        if not ranked:
            report.lines.append("No messages counted yet.")
        if days and (note := await self._coverage_note(guild, since)):
            report.lines.append(note)
        return report

    async def report_heatmap(self, viewer: discord.Member, channel_id: Optional[int] = None, days: int = 30) -> Report:
        guild, now = viewer.guild, time.time()
        days = days or 30
        tz, tz_name = await self._tz(viewer)
        since = now - days * DAY
        grid = [[0] * 24 for _ in range(7)]
        for cid, _, hour, n in await self._message_rows(guild, since, channel_id=channel_id):
            if self._can_see(viewer, guild, cid):
                local = datetime.fromtimestamp(hour, tz)
                grid[local.weekday()][local.hour] += n
        where = f"#{getattr(guild.get_channel(channel_id), 'name', 'deleted')}" if channel_id else guild.name
        report = Report(f"🗓️ When {where} is busiest: {period_label(days)}")
        slots = sorted(((grid[d][h], d, h) for d in range(7) for h in range(24)), reverse=True)
        if not slots[0][0]:
            report.lines.append("No messages counted yet.")
            return report
        report.lines.append("🔥 Busiest hours: " + ", ".join(
            f"**{WEEKDAYS[d]} {hour_label(h)}**" for n, d, h in slots[:3] if n))
        by_day = [sum(row) for row in grid]
        by_hour = [sum(grid[d][h] for d in range(7)) for h in range(24)]
        report.lines.append(f"📅 Busiest day: **{WEEKDAYS[by_day.index(max(by_day))]}** · quietest: "
                            f"**{WEEKDAYS[by_day.index(min(by_day))]}**")
        report.lines.append(f"🕘 Busiest time of day: **{hour_label(by_hour.index(max(by_hour)))}**")
        report.lines.append(f"-# Times are in {tz_name}.")
        if note := await self._coverage_note(guild, since):
            report.lines.append(note)
        report.chart = lambda: heatmap_chart(grid, tz_name)
        return report

    async def report_voice(self, viewer: discord.Member, days: int = 30) -> Report:
        guild, now = viewer.guild, time.time()
        days = days or 30
        tz, _ = await self._tz(viewer)
        since = now - days * DAY
        rows = [r for r in await self._voice_rows(guild, since, now) if self._can_see(viewer, guild, r[0])]
        per_channel, per_user, daily = Counter(), Counter(), Counter()
        for cid, uid, start, end in rows:
            per_channel[cid] += end - start
            per_user[uid] += end - start
            for day, seconds in split_by_day(start, end, tz):
                daily[day] += seconds / 3600
        report = Report(f"🔊 Voice: {period_label(days)}")
        if not rows:
            report.lines.append("No voice time recorded yet.")
            return report
        report.lines.append(f"**{fmt_hours(sum(per_channel.values()))}** in voice from **{len(per_user)}** members.")
        report.lines.append("📢 Channels: " + ", ".join(
            f"{self._channel_name(guild, c)} ({fmt_hours(s)})" for c, s in per_channel.most_common(5)))
        report.lines.append("🏆 Most time: " + ", ".join(
            f"<@{u}> ({fmt_hours(s)})" for u, s in per_user.most_common(5) if guild.get_member(u)))
        events = sorted([(s, 1) for _, _, s, _ in rows] + [(e, -1) for _, _, _, e in rows], key=lambda x: (x[0], x[1]))
        current = peak = 0
        peak_at = since
        for ts, delta in events:
            current += delta
            if current > peak:
                peak, peak_at = current, ts
        report.lines.append(f"👥 Most at once: **{peak}** (<t:{int(peak_at)}:f>)")
        if note := await self._coverage_note(guild, since):
            report.lines.append(note)
        days_list = day_range(since, now, tz)
        report.chart = lambda: daily_chart(days_list, {"Voice hours": [round(daily[d], 1) for d in days_list]},
                                           "hours in voice")
        return report

    async def report_me(self, viewer: discord.Member, member: discord.Member, days: int = 30) -> Report:
        guild, now = viewer.guild, time.time()
        days = days or 30
        tz, tz_name = await self._tz(member)
        since = now - days * DAY
        period_counts, channels, hours = Counter(), Counter(), Counter()
        for cid, uid, hour, n in await self._message_rows(guild, since):
            if self._can_see(viewer, guild, cid):
                period_counts[uid] += n
                if uid == member.id:
                    channels[cid] += n
                    hours[datetime.fromtimestamp(hour, tz).hour] += n
        all_time = sum(n for cid, n in await self.db.query(
            "SELECT channel, SUM(count) FROM messages WHERE guild = ? AND user = ? GROUP BY channel",
            (guild.id, member.id)) if self._can_see(viewer, guild, cid))
        mine = period_counts[member.id]
        ranked = [u for u, _ in period_counts.most_common() if guild.get_member(u)]
        who = "Your" if member == viewer else f"{member.display_name}'s"
        report = Report(f"🙋 {who} stats: {period_label(days)}")
        rank = f", **#{ranked.index(member.id) + 1}** in the server" if member.id in ranked else ""
        report.lines.append(f"💬 **{mine:,}** messages{rank} · **{all_time:,}** all time")
        if channels:
            report.lines.append("📍 Most active in: " + ", ".join(
                f"{self._channel_name(guild, c)} ({n:,})" for c, n in channels.most_common(3)))
            report.lines.append("🕘 Usually around: " + ", ".join(
                f"**{hour_label(h)}**" for h, _ in hours.most_common(3)) + f" ({tz_name})")
        voice = Counter()
        for cid, uid, start, end in await self._voice_rows(guild, since, now):
            if uid == member.id and self._can_see(viewer, guild, cid):
                voice[cid] += end - start
        if voice:
            top_channel = voice.most_common(1)[0][0]
            report.lines.append(f"🔊 **{fmt_hours(sum(voice.values()))}** in voice, mostly in "
                                f"{self._channel_name(guild, top_channel)}")
        games = Counter()
        for uid, game, start, end in await self._game_rows(guild, since, now):
            if uid == member.id:
                games[game] += end - start
        if games:
            report.lines.append("🎮 Played: " + ", ".join(
                f"**{g}** ({fmt_hours(s)})" for g, s in games.most_common(5)))
        sessions = await self.db.query("SELECT joined, showed FROM game_sessions WHERE guild = ? AND start >= ?",
                                       (guild.id, int(since)))
        joined = [json.loads(s) for j, s in sessions if member.id in json.loads(j)]
        if joined:
            showed = sum(member.id in s for s in joined)
            report.lines.append(f"🎲 Game nights: joined **{len(joined)}**, showed up for **{showed}**")
        report.lines.extend(await self._library_suggestions(guild, member, games))
        if note := await self._coverage_note(guild, since):
            report.lines.append(note)
        return report

    async def _library_suggestions(self, guild: discord.Guild, member: discord.Member, games: Counter) -> List[str]:
        """Games the member played for 2+ hours that aren't in their GameManager library."""
        gm = self.bot.get_cog("GameManager")
        if gm is None or not games:
            return []
        library = await gm.config.guild(guild).games()
        mine = (await gm.config.guild(guild).users()).get(str(member.id), {})
        owned = {simplify(library[g]["name"]) for g in mine.get("owned", []) + mine.get("installed", []) if g in library}
        names = {simplify(g["name"]): g["name"] for g in library.values()}
        prefix = await self._prefix(guild)
        tips = []
        for game, seconds in games.most_common():
            key = simplify(game)
            if seconds < 2 * 3600 or key in owned:
                continue
            if key in names:
                tips.append(f"`{prefix}games own {names[key]}`")
            else:
                tips.append(f"`{prefix}games request {game}`")
        return ["💡 Played but not in your library: " + " · ".join(tips[:3])] if tips else []

    async def report_games(self, viewer: discord.Member, days: int = 30) -> Report:
        guild, now = viewer.guild, time.time()
        days = days or 30
        since = now - days * DAY
        seconds, players = Counter(), defaultdict(set)
        for uid, game, start, end in await self._game_rows(guild, since, now):
            seconds[game] += end - start
            players[game].add(uid)
        report = Report(f"🎮 Most-played games: {period_label(days)}")
        if not await self.config.guild(guild).track_games():
            report.lines.append("Game tracking is turned off on this server.")
        elif not seconds:
            report.lines.append("No games recorded yet. Games show up when members share their activity status "
                                "(\"Playing …\") in Discord.")
        for i, (game, total) in enumerate(seconds.most_common(15)):
            count = len(players[game])
            report.lines.append(f"{MEDALS[i] if i < 3 else f'`{i + 1}.`'} **{game}**: {fmt_hours(total)}, "
                                f"{count} player{'s' if count != 1 else ''}")
        if note := await self._coverage_note(guild, since):
            report.lines.append(note)
        return report

    # ==========================================
    #               ADMIN REPORTS
    # ==========================================

    async def _active_user_days(self, guild: discord.Guild, since: float, tz: tzinfo) -> Dict[date, Set[int]]:
        """Who was active (posted or in voice) on each local day."""
        active = defaultdict(set)
        for _, uid, hour, _ in await self._message_rows(guild, since):
            active[local_day(hour, tz)].add(uid)
        for _, uid, start, end in await self._voice_rows(guild, since, time.time()):
            for day, _ in split_by_day(start, end, tz):
                active[day].add(uid)
        return active

    async def report_active(self, guild: discord.Guild, days: int = 90) -> Report:
        days, now = days or 90, time.time()
        tz, _ = await self._guild_tz(guild)
        since = now - days * DAY
        active = await self._active_user_days(guild, since - 29 * DAY, tz)
        days_list = day_range(since, now, tz)

        def window(day: date, length: int) -> int:
            return len(set().union(*(active.get(day - timedelta(days=i), set()) for i in range(length))))

        dau = [len(active.get(d, ())) for d in days_list]
        wau = [window(d, 7) for d in days_list]
        mau = [window(d, 30) for d in days_list]
        report = Report(f"📈 Active members: last {days} days", admin=True)
        report.lines.append(f"Active means they posted or joined voice. Right now: **{sum(dau[-7:]) / 7:.1f}** a day "
                            f"(7-day average), **{wau[-1]}** this week, **{mau[-1]}** this month.")
        if len(days_list) > 30:
            report.lines.append(f"A month earlier: **{wau[-31]}** weekly, **{mau[-31]}** monthly.")
        humans = sum(not m.bot for m in guild.members)
        report.lines.append(f"Out of **{humans}** members, **{pct(mau[-1], humans)}** were active this month.")
        if note := await self._coverage_note(guild, since - 29 * DAY):
            report.lines.append(note)
        report.chart = lambda: daily_chart(days_list, {"Monthly": mau, "Weekly": wau, "Daily": dau}, "members")
        return report

    async def report_retention(self, guild: discord.Guild, days: int = 90) -> Report:
        days, now = days or 90, time.time()
        start = max(now - days * DAY, await self._data_start(guild))
        end = now - 7 * DAY
        report = Report(f"🌱 New-member retention: last {days} days", admin=True)
        joins: Dict[int, float] = {}
        for uid, ts in await self.db.query(
                "SELECT user, ts FROM member_events WHERE guild = ? AND event = 'join' AND ts >= ? AND ts < ?",
                (guild.id, int(start), int(end))):
            joins.setdefault(uid, ts)
        for member in guild.members:
            if not member.bot and member.joined_at and start <= member.joined_at.timestamp() < end:
                joins.setdefault(member.id, member.joined_at.timestamp())
        if not joins:
            report.lines.append("Nobody joined in this window (people who joined in the last week aren't counted "
                                "yet).")
            if note := await self._coverage_note(guild, now - days * DAY):
                report.lines.append(note)
            return report
        posts = defaultdict(list)
        for _, uid, hour, _ in await self._message_rows(guild, start):
            posts[uid].append(hour)
        recent_voice = {uid for _, uid, _, _ in await self._voice_rows(guild, now - 30 * DAY, now)}
        posted = sum(any(ts - 3600 <= h < ts + 7 * DAY for h in posts[uid]) for uid, ts in joins.items())
        stayed = [uid for uid in joins if guild.get_member(uid)]
        active = sum(any(h >= now - 30 * DAY for h in posts[uid]) or uid in recent_voice for uid in stayed)
        n = len(joins)
        report.lines.append(f"**{n}** people joined between <t:{int(start)}:d> and a week ago.")
        report.lines.append(f"✍️ Posted in their first week: **{posted}** ({pct(posted, n)})")
        report.lines.append(f"🏠 Still in the server: **{len(stayed)}** ({pct(len(stayed), n)})")
        report.lines.append(f"🔥 Active in the last 30 days: **{active}** ({pct(active, n)})")
        if note := await self._coverage_note(guild, now - days * DAY):
            report.lines.append(note)
        return report

    async def report_quiet(self, guild: discord.Guild) -> Report:
        now = time.time()
        recent, earlier = Counter(), Counter()
        for _, uid, hour, n in await self._message_rows(guild, now - 90 * DAY):
            (recent if hour >= now - 30 * DAY else earlier)[uid] += n
        in_voice = {uid for _, uid, _, _ in await self._voice_rows(guild, now - 30 * DAY, now)}
        humans = [m for m in guild.members if not m.bot and m.id not in self._ignored]
        went_quiet = sorted((m for m in humans if earlier[m.id] >= QUIET_MIN_MESSAGES and not recent[m.id]),
                            key=lambda m: -earlier[m.id])
        lurkers = [m for m in humans if not recent[m.id] and m.id not in in_voice]
        report = Report("🤫 Quiet members", admin=True)
        report.lines.append(f"**Went quiet** ({len(went_quiet)}): {QUIET_MIN_MESSAGES}+ messages 1–3 months ago, "
                            "none in the last 30 days.")
        report.lines.append(self._names(m.mention for m in went_quiet) or "-# Nobody.")
        report.lines.append(f"**No messages or voice in 30 days** ({len(lurkers)} of {len(humans)} members):")
        report.lines.append(self._names(m.mention for m in lurkers) or "-# Nobody.")
        if note := await self._coverage_note(guild, now - 90 * DAY):
            report.lines.append(note + " These lists are reliable once 30 days are covered.")
        return report

    @staticmethod
    def _names(mentions: Iterable[str]) -> str:
        mentions = list(mentions)
        more = f" and {len(mentions) - MAX_NAMES} more" if len(mentions) > MAX_NAMES else ""
        return ", ".join(mentions[:MAX_NAMES]) + more

    async def report_joins(self, guild: discord.Guild, days: int = 90) -> Report:
        days, now = days or 90, time.time()
        tz, _ = await self._guild_tz(guild)
        since = now - days * DAY
        joins, leaves = Counter(), Counter()
        for event, ts in await self.db.query(
                "SELECT event, ts FROM member_events WHERE guild = ? AND ts >= ?", (guild.id, int(since))):
            (joins if event == "join" else leaves)[local_day(ts, tz)] += 1
        report = Report(f"🚪 Joins and leaves: last {days} days", admin=True)
        j, l = sum(joins.values()), sum(leaves.values())
        report.lines.append(f"➕ **{j}** joined · ➖ **{l}** left · net **{j - l:+d}**")
        report.lines.append(f"👥 **{sum(not m.bot for m in guild.members)}** members now.")
        if note := await self._coverage_note(guild, since):
            report.lines.append(note)
        days_list = day_range(since, now, tz)
        report.chart = lambda: daily_chart(days_list, {"Joined": [joins[d] for d in days_list],
                                                       "Left": [leaves[d] for d in days_list]}, "members")
        return report

    async def report_dead_channels(self, guild: discord.Guild, days: int = 30) -> Report:
        days, now = days or 30, time.time()
        await self.flush()
        last = {cid: hour for cid, hour in await self.db.query(
            "SELECT channel, MAX(hour) FROM messages WHERE guild = ? GROUP BY channel", (guild.id,))}
        dead = []
        for channel in [*guild.text_channels, *guild.forums]:
            ts = last.get(channel.id, 0)
            if channel.last_message_id:
                ts = max(ts, discord.utils.snowflake_time(channel.last_message_id).timestamp())
            if ts < now - days * DAY:
                dead.append((ts, channel))
        report = Report(f"🕸️ Channels with no posts in {days} days", admin=True)
        if not dead:
            report.lines.append("Every channel has had a post recently.")
        for ts, channel in sorted(dead, key=lambda x: x[0])[:30]:
            report.lines.append(f"{channel.mention}: " + (f"last post <t:{int(ts)}:R>" if ts else "no posts seen"))
        return report

    async def report_attendance(self, guild: discord.Guild, count: int = 10) -> Report:
        rows = await self.db.query(
            "SELECT title, start, joined, showed FROM game_sessions WHERE guild = ? ORDER BY start DESC LIMIT ?",
            (guild.id, max(1, min(count, 25))))
        report = Report("🎲 Game night attendance", admin=True)
        if not rows:
            report.lines.append("No game sessions recorded yet. Sessions are recorded when they end.")
            return report
        for title, start, joined, showed in rows:
            joined, showed = set(json.loads(joined)), set(json.loads(showed))
            no_shows = joined - showed
            line = f"**{title}** · <t:{start}:d>: **{len(joined & showed)}/{len(joined)}** showed up"
            if walk_ins := len(showed - joined):
                line += f", plus {walk_ins} who didn't click Join"
            if no_shows:
                line += f"\n-# Didn't show: {self._names(f'<@{u}>' for u in no_shows)}"
            report.lines.append(line)
        reliability = defaultdict(lambda: [0, 0])
        for _, _, joined, showed in await self.db.query(
                "SELECT title, start, joined, showed FROM game_sessions WHERE guild = ? AND start >= ?",
                (guild.id, int(time.time() - 90 * DAY))):
            showed = set(json.loads(showed))
            for uid in json.loads(joined):
                reliability[uid][0] += 1
                reliability[uid][1] += uid in showed
        regulars = sorted(((s / j, j, uid) for uid, (j, s) in reliability.items() if j >= 2), reverse=True)
        if regulars:
            report.lines.append("**Show-up rate** (90 days, 2+ sessions joined): " + ", ".join(
                f"<@{uid}> {rate:.0%} of {j}" for rate, j, uid in regulars[:15]))
        return report

    async def report_commands(self, guild: discord.Guild, days: int = 30) -> Report:
        days, now = days or 30, time.time()
        since = now - days * DAY
        prefix = await self._prefix(guild)
        uses, failures, unknown = Counter(), Counter(), Counter()
        for command, ok, n in await self.db.query(
                "SELECT command, ok, COUNT(*) FROM command_uses WHERE guild = ? AND ts >= ? GROUP BY command, ok",
                (guild.id, int(since))):
            if command.startswith("?"):
                unknown[command[1:]] += n
                continue
            uses[command] += n
            if not ok:
                failures[command] += n
        report = Report(f"🛠️ Command usage: last {days} days", admin=True)
        report.lines.append(f"**{sum(uses.values()):,}** commands run by members.")
        for command, n in uses.most_common(15):
            name = command if command.startswith("/") else f"{prefix}{command}"
            report.lines.append(f"`{name}`: **{n:,}**" + (f" ({failures[command]} failed)" if failures[command] else ""))
        if unknown:
            report.lines.append("❓ Typed but don't exist: " + ", ".join(
                f"`{prefix}{c}` ({n})" for c, n in unknown.most_common(8)))
        if await self._data_start(guild) <= since:
            used_roots = {c.lstrip("/").split()[0] for c in uses}
            unused = sorted(
                name for name, cog in self.bot.cogs.items()
                if (roots := {c.name for c in cog.get_commands() if not c.hidden}) and not roots & used_roots)
            if unused:
                report.lines.append("💤 No uses: " + ", ".join(unused))
        claude = self.bot.get_cog("ClaudeChat")
        if claude is not None:
            try:
                usage = await claude.config.guild(guild).usage()
                report.lines.append(f"🤖 AI: **{usage.get('requests', 0):,}** requests, about "
                                    f"**${usage.get('cost', 0):,.2f}** all time")
            except Exception:
                log.debug("Couldn't read Claude usage", exc_info=True)
        if note := await self._coverage_note(guild, since):
            report.lines.append(note)
        return report

    async def report_unmet(self, guild: discord.Guild, days: int = 30) -> Report:
        days = days or 30
        rows = await self.db.query(
            "SELECT user, question, ts FROM unmet_questions WHERE guild = ? AND ts >= ? ORDER BY ts DESC LIMIT 25",
            (guild.id, int(time.time() - days * DAY)))
        report = Report(f"🔎 Guide questions with no matching command: last {days} days", admin=True)
        if not rows:
            report.lines.append("None. The guide found a command for every question.")
        for uid, question, ts in rows:
            question = question.replace("\n", " ")
            report.lines.append(f"<t:{ts}:d> <@{uid}>: “{question[:150]}{'…' if len(question) > 150 else ''}”")
        return report

    async def report_libraries(self, guild: discord.Guild) -> Report:
        report = Report("📚 Game library coverage", admin=True)
        gm = self.bot.get_cog("GameManager")
        if gm is None:
            report.lines.append("GameManager isn't loaded.")
            return report
        users = await gm.config.guild(guild).users()
        humans = [m for m in guild.members if not m.bot]
        sizes = {m.id: len(set(users.get(str(m.id), {}).get("owned", []))
                           | set(users.get(str(m.id), {}).get("installed", []))) for m in humans}
        with_library = [uid for uid, n in sizes.items() if n]
        report.lines.append(f"**{len(with_library)}** of **{len(humans)}** members have a game library "
                            f"({pct(len(with_library), len(humans))}).")
        if with_library:
            report.lines.append(f"Average library: **{sum(sizes[u] for u in with_library) / len(with_library):.0f}** "
                                "games.")
        missing = [m.mention for m in humans if not sizes[m.id]]
        if missing:
            report.lines.append(f"**No library yet:** {self._names(missing)}")
        return report

    async def report_digest(self, guild: discord.Guild) -> Report:
        """The weekly admin digest: this week against last week."""
        now = time.time()
        week, last_week = now - 7 * DAY, now - 14 * DAY
        tz, _ = await self._guild_tz(guild)
        this, before, channels, posters, prev_posters, daily = 0, 0, Counter(), set(), set(), Counter()
        for cid, uid, hour, n in await self._message_rows(guild, last_week):
            if hour >= hour_of(week):
                this += n
                channels[cid] += n
                posters.add(uid)
                daily[local_day(hour, tz)] += n
            else:
                before += n
                prev_posters.add(uid)
        report = Report(f"📰 Weekly digest: <t:{int(week)}:d> to <t:{int(now)}:d>", admin=True)
        report.lines.append(f"💬 **{this:,}** messages{change(this, before)} from **{len(posters)}** members "
                            f"(last week: {len(prev_posters)})")
        if channels:
            report.lines.append("🔥 Busiest: " + ", ".join(
                f"{self._channel_name(guild, c)} ({n:,})" for c, n in channels.most_common(3)))
        active = await self._active_user_days(guild, week, tz)
        report.lines.append(f"👥 **{len(set().union(*active.values()))}** active members this week")
        events = Counter(e for e, in await self.db.query(
            "SELECT event FROM member_events WHERE guild = ? AND ts >= ?", (guild.id, int(week))))
        report.lines.append(f"🚪 **{events['join']}** joined, **{events['leave']}** left")
        voice = sum(e - s for _, _, s, e in await self._voice_rows(guild, week, now))
        if voice:
            report.lines.append(f"🔊 **{fmt_hours(voice)}** in voice")
        games = Counter()
        for _, game, s, e in await self._game_rows(guild, week, now):
            games[game] += e - s
        if games:
            report.lines.append("🎮 Most played: " + ", ".join(f"**{g}**" for g, _ in games.most_common(3)))
        sessions = await self.db.query("SELECT joined, showed FROM game_sessions WHERE guild = ? AND start >= ?",
                                       (guild.id, int(week)))
        if sessions:
            joined = sum(len(json.loads(j)) for j, _ in sessions)
            showed = sum(len(set(json.loads(j)) & set(json.loads(s))) for j, s in sessions)
            report.lines.append(f"🎲 **{len(sessions)}** game sessions, **{pct(showed, joined)}** of sign-ups showed up")
        top = await self.db.query(
            "SELECT command, COUNT(*) FROM command_uses WHERE guild = ? AND ts >= ? AND command NOT LIKE '?%' "
            "GROUP BY command ORDER BY 2 DESC LIMIT 3", (guild.id, int(week)))
        if top:
            prefix = await self._prefix(guild)
            report.lines.append("🛠️ Top commands: " + ", ".join(
                f"`{c if c.startswith('/') else prefix + c}` ({n})" for c, n in top))
        unmet = (await self.db.query("SELECT COUNT(*) FROM unmet_questions WHERE guild = ? AND ts >= ?",
                                     (guild.id, int(week))))[0][0]
        if unmet:
            report.lines.append(f"🔎 **{unmet}** guide questions had no matching command")
        dead = await self.report_dead_channels(guild, 30)
        if dead.lines and not dead.lines[0].startswith("Every"):
            report.lines.append(f"🕸️ **{len(dead.lines)}** channels with no posts in 30 days")
        days_list = day_range(week, now, tz)
        report.chart = lambda: daily_chart(days_list, {"Messages": [daily[d] for d in days_list]}, "messages")
        return report

    # ==========================================
    #           LOOKUPS FOR THE CLAUDE COG
    # ==========================================

    def guide_tools(self) -> List[dict]:
        return [STATS_TOOL]

    async def guide_call_tool(self, name: str, args: dict, asker: discord.Member) -> str:
        """Answer the stats_report lookup as plain text. Read-only."""
        if name != "stats_report":
            return f"Unknown lookup: {name}"
        kind = str(args.get("report") or "overview")
        target = str(args.get("target") or "").strip()
        try:
            days = max(0, min(int(args.get("days") or 0), MAX_DAYS))
        except (TypeError, ValueError):
            days = 0
        admin = await self._is_admin(asker)
        if kind in ADMIN_REPORTS and not admin:
            return "That report is for server admins only."
        try:
            report = await self._build(kind, asker, target, days, admin)
        except LookupError as e:
            return str(e)
        return self._plain(asker.guild, report)

    async def _build(self, kind: str, asker: discord.Member, target: str, days: int, admin: bool) -> Report:
        guild = asker.guild
        if kind in ("channel", "top", "heatmap") and target:
            channel = self._find_channel(guild, target)
            if channel is None or not self._can_see(asker, guild, channel.id):
                raise LookupError(f"No channel matches \"{target}\".")
            cid = self._channel_key(channel)
        else:
            cid = None
        if kind == "overview":
            return await self.report_overview(asker, days or 7)
        if kind == "channels":
            return await self.report_channels(asker, guild, days)
        if kind == "channel":
            if cid is None:
                raise LookupError("Name a channel for the channel report.")
            return await self.report_channel(asker, cid, days)
        if kind == "top":
            return await self.report_top(asker, cid, days)
        if kind == "heatmap":
            return await self.report_heatmap(asker, cid, days)
        if kind == "voice":
            return await self.report_voice(asker, days)
        if kind == "games":
            return await self.report_games(asker, days)
        if kind == "me":
            member = self._find_member(guild, target, asker)
            if member is None:
                raise LookupError(f"No member matches \"{target}\".")
            if member != asker and not admin:
                raise LookupError("Members can only look up their own stats. Leaderboards (top) are public.")
            return await self.report_me(asker, member, days)
        reports = {
            "active": lambda: self.report_active(guild, days),
            "retention": lambda: self.report_retention(guild, days),
            "quiet": lambda: self.report_quiet(guild),
            "joins": lambda: self.report_joins(guild, days),
            "dead_channels": lambda: self.report_dead_channels(guild, days),
            "attendance": lambda: self.report_attendance(guild),
            "commands": lambda: self.report_commands(guild, days),
            "unmet": lambda: self.report_unmet(guild, days),
            "libraries": lambda: self.report_libraries(guild),
        }
        if kind not in reports:
            raise LookupError(f"Unknown report: {kind}")
        return await reports[kind]()

    @staticmethod
    def _find_channel(guild: discord.Guild, text: str):
        text = text.strip()
        if match := re.fullmatch(r"<#(\d+)>|(\d{15,20})", text):
            return guild.get_channel_or_thread(int(match.group(1) or match.group(2)))
        name = text.lstrip("#").lower().replace(" ", "-")
        channels = [*guild.channels, *guild.threads]
        exact = [c for c in channels if c.name.lower() == name]
        if exact:
            return exact[0]
        partial = [c for c in channels if name in c.name.lower()]
        return partial[0] if len(partial) == 1 else None

    @staticmethod
    def _find_member(guild: discord.Guild, text: str, asker: discord.Member) -> Optional[discord.Member]:
        text = text.strip()
        if text.lower() in ("", "me", "myself", "i", "self"):
            return asker
        if match := re.fullmatch(r"<@!?(\d+)>|(\d{15,20})", text):
            return guild.get_member(int(match.group(1) or match.group(2)))
        lowered = text.lstrip("@").lower()
        for attr in ("display_name", "name", "global_name"):
            found = [m for m in guild.members if (getattr(m, attr, None) or "").lower() == lowered]
            if found:
                return found[0]
        partial = [m for m in guild.members if lowered in m.display_name.lower()]
        return partial[0] if len(partial) == 1 else None

    @staticmethod
    def _plain(guild: discord.Guild, report: Report) -> str:
        """A report as text for Claude: mentions become names, timestamps become dates."""
        text = "\n".join([report.title, *report.lines])

        def channel(match):
            found = guild.get_channel_or_thread(int(match.group(1)))
            return f"#{found.name}" if found else "#deleted-channel"

        def member(match):
            found = guild.get_member(int(match.group(1)))
            return found.display_name if found else "a former member"

        def stamp(match):
            return datetime.fromtimestamp(int(match.group(1)), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        text = re.sub(r"<#(\d+)>", channel, text)
        text = re.sub(r"<@!?(\d+)>", member, text)
        text = re.sub(r"<t:(\d+)(?::\w)?>", stamp, text)
        return text.replace("-# ", "")

    # ==========================================
    #                  OUTPUT
    # ==========================================

    async def _report_embed(self, report: Report, footer: Optional[str] = None
                            ) -> Tuple[discord.Embed, Optional[discord.File]]:
        description = "\n".join(report.lines) or "Nothing to show yet."
        embed = discord.Embed(title=report.title, description=description[:4000],
                              color=ADMIN_COLOR if report.admin else MEMBER_COLOR)
        if footer:
            embed.set_footer(text=footer)
        file = None
        if report.chart is not None:
            try:
                data = await asyncio.to_thread(report.chart)
                file = discord.File(io.BytesIO(data), filename="stats.png")
                embed.set_image(url="attachment://stats.png")
            except Exception:
                log.exception("Couldn't draw a stats chart")
        return embed, file

    async def _send(self, ctx: commands.Context, report: Report, footer: Optional[str] = None):
        embed, file = await self._report_embed(report, footer)
        kwargs = {"embed": embed}
        if file is not None:
            kwargs["file"] = file
        await ctx.send(**kwargs)

    async def _channel_id(self, ctx: commands.Context, channel) -> Optional[int]:
        """The tracked channel ID for a channel argument, or None after telling the user it's unavailable."""
        if not channel.permissions_for(ctx.author).view_channel:
            await ctx.send("❌ You can't see that channel.")
            return None
        return self._channel_key(channel)

    # ==========================================
    #            COMMANDS FOR EVERYONE
    # ==========================================

    @commands.group(name="stats", invoke_without_command=True)
    @commands.guild_only()
    async def stats(self, ctx: commands.Context, period: Optional[Period] = None):
        """
        Server activity stats.

        With no subcommand, shows the last week at a glance. Periods look like `week`, `month`, `90d` or `all`.
        """
        p = ctx.clean_prefix
        await self._send(ctx, await self.report_overview(ctx.author, period or 7),
                         footer=f"More: {p}stats channels · {p}stats top · {p}stats heatmap · {p}stats voice · "
                                f"{p}stats games · {p}stats me")

    @stats.command(name="channels")
    async def stats_channels(self, ctx: commands.Context, period: Optional[Period] = None):
        """Messages per day in each channel. Default: the last month."""
        await self._send(ctx, await self.report_channels(ctx.author, ctx.guild, period or 30))

    @stats.command(name="channel")
    async def stats_channel(self, ctx: commands.Context, channel: Optional[ChannelArg] = None,
                            period: Optional[Period] = None):
        """One channel's activity and top posters. Default: this channel, the last month."""
        cid = await self._channel_id(ctx, channel or ctx.channel)
        if cid is not None:
            await self._send(ctx, await self.report_channel(ctx.author, cid, period or 30))

    @stats.command(name="top", aliases=["leaderboard", "lb"])
    async def stats_top(self, ctx: commands.Context, channel: Optional[ChannelArg] = None,
                        period: Optional[Period] = None):
        """
        Who posted the most, server-wide or in one channel.

        Examples: `[p]stats top`, `[p]stats top week`, `[p]stats top #general all`. Default: the last month.
        """
        cid = await self._channel_id(ctx, channel) if channel else None
        if channel is None or cid is not None:
            await self._send(ctx, await self.report_top(ctx.author, cid, 30 if period is None else period))

    @stats.command(name="heatmap", aliases=["busy", "when"])
    async def stats_heatmap(self, ctx: commands.Context, channel: Optional[ChannelArg] = None,
                            period: Optional[Period] = None):
        """When the server (or one channel) is busiest, by day and hour, in your timezone."""
        cid = await self._channel_id(ctx, channel) if channel else None
        if channel is None or cid is not None:
            await self._send(ctx, await self.report_heatmap(ctx.author, cid, period or 30))

    @stats.command(name="voice")
    async def stats_voice(self, ctx: commands.Context, period: Optional[Period] = None):
        """Time in each voice channel, who spends the most time there, and the most people at once."""
        await self._send(ctx, await self.report_voice(ctx.author, period or 30))

    @stats.command(name="games")
    async def stats_games(self, ctx: commands.Context, period: Optional[Period] = None):
        """The server's most-played games, from Discord's "Playing" status."""
        await self._send(ctx, await self.report_games(ctx.author, period or 30))

    @stats.command(name="me")
    async def stats_me(self, ctx: commands.Context, member: Optional[discord.Member] = None,
                       period: Optional[Period] = None):
        """Your own stats: messages, channels, usual hours, voice, games and game nights. Admins can name a member."""
        member = member or ctx.author
        if member != ctx.author and not await self._is_admin(ctx.author):
            return await ctx.send("❌ You can only see your own stats. Leaderboards are in "
                                  f"`{ctx.clean_prefix}stats top`.")
        await self._send(ctx, await self.report_me(ctx.author, member, period or 30))

    @stats.command(name="ignoreme", aliases=["optout"])
    async def stats_ignoreme(self, ctx: commands.Context):
        """Stop tracking your activity, everywhere, and delete what's been recorded about you."""
        await self.config.user(ctx.author).ignored.set(True)
        self._ignored.add(ctx.author.id)
        await self._forget_user(ctx.author.id)
        await ctx.send(f"✅ I've stopped tracking you and deleted your stats. `{ctx.clean_prefix}stats trackme` "
                       "turns tracking back on.")

    @stats.command(name="trackme", aliases=["optin"])
    async def stats_trackme(self, ctx: commands.Context):
        """Turn activity tracking back on for yourself."""
        await self.config.user(ctx.author).ignored.set(False)
        self._ignored.discard(ctx.author.id)
        await ctx.send("✅ Tracking is back on for you.")

    # ==========================================
    #               ADMIN COMMANDS
    # ==========================================

    @stats.group(name="admin", invoke_without_command=True)
    @checks.admin_or_permissions(manage_guild=True)
    async def stats_admin(self, ctx: commands.Context):
        """Admin-only reports and stats settings."""
        p = f"{ctx.clean_prefix}stats admin"
        embed = discord.Embed(title="📋 Admin stats", color=ADMIN_COLOR, description="\n".join([
            f"`{p} active [period]`: daily, weekly and monthly active members",
            f"`{p} retention [period]`: do new members post and stick around?",
            f"`{p} quiet`: lurkers and members who went quiet",
            f"`{p} joins [period]`: joins and leaves",
            f"`{p} deadchannels [period]`: channels with no recent posts",
            f"`{p} attendance [count]`: game sessions, who joined vs. who showed up",
            f"`{p} commands [period]`: what's used, what isn't, and commands that don't exist",
            f"`{p} unmet [period]`: guide questions no command could answer",
            f"`{p} libraries`: who has a game library",
            "",
            f"`{p} digest`: the weekly digest settings",
            f"`{p} settings` · `exclude` · `include` · `gametracking` · `backfill`",
        ]))
        await ctx.send(embed=embed)

    @stats_admin.command(name="active")
    async def admin_active(self, ctx: commands.Context, period: Optional[Period] = None):
        """Daily, weekly and monthly active members over time. Default: 90 days."""
        await self._send(ctx, await self.report_active(ctx.guild, period or 90))

    @stats_admin.command(name="retention")
    async def admin_retention(self, ctx: commands.Context, period: Optional[Period] = None):
        """Of the people who joined, how many posted in their first week and are still around. Default: 90 days."""
        await self._send(ctx, await self.report_retention(ctx.guild, period or 90))

    @stats_admin.command(name="quiet", aliases=["lurkers"])
    async def admin_quiet(self, ctx: commands.Context):
        """Members who went quiet, and members with no messages or voice in 30 days."""
        await self._send(ctx, await self.report_quiet(ctx.guild))

    @stats_admin.command(name="joins")
    async def admin_joins(self, ctx: commands.Context, period: Optional[Period] = None):
        """Joins and leaves over time. Default: 90 days."""
        await self._send(ctx, await self.report_joins(ctx.guild, period or 90))

    @stats_admin.command(name="deadchannels", aliases=["dead"])
    async def admin_dead(self, ctx: commands.Context, period: Optional[Period] = None):
        """Channels with no posts in a while. Default: 30 days."""
        await self._send(ctx, await self.report_dead_channels(ctx.guild, period or 30))

    @stats_admin.command(name="attendance")
    async def admin_attendance(self, ctx: commands.Context, count: int = 10):
        """Recent game sessions: who clicked Join and who showed up in voice."""
        await self._send(ctx, await self.report_attendance(ctx.guild, count))

    @stats_admin.command(name="commands")
    async def admin_commands(self, ctx: commands.Context, period: Optional[Period] = None):
        """Command usage, unused cogs, and commands people typed that don't exist. Default: 30 days."""
        await self._send(ctx, await self.report_commands(ctx.guild, period or 30))

    @stats_admin.command(name="unmet")
    async def admin_unmet(self, ctx: commands.Context, period: Optional[Period] = None):
        """Questions the bot guide couldn't match to any command. Default: 30 days."""
        await self._send(ctx, await self.report_unmet(ctx.guild, period or 30))

    @stats_admin.command(name="libraries")
    async def admin_libraries(self, ctx: commands.Context):
        """How many members have set up a game library."""
        await self._send(ctx, await self.report_libraries(ctx.guild))

    @stats_admin.command(name="settings")
    async def admin_settings(self, ctx: commands.Context):
        """Show the stats settings."""
        data = await self.config.guild(ctx.guild).all()
        excluded = ", ".join(self._channel_name(ctx.guild, c) for c in data["excluded_channels"]) or "None"
        digest_channel = self._channel_name(ctx.guild, data["digest_channel"]) if data["digest_channel"] else "not set"
        _, tz_name = await self._guild_tz(ctx.guild)
        embed = discord.Embed(title="⚙️ Stats settings", color=ADMIN_COLOR)
        embed.add_field(name="Tracking since", value=f"<t:{int(await self._data_start(ctx.guild))}:D>")
        embed.add_field(name="Game tracking", value="On" if data["track_games"] else "Off")
        embed.add_field(name="Excluded channels", value=excluded, inline=False)
        embed.add_field(name="Weekly digest", inline=False, value=(
            f"{'On' if data['digest_enabled'] else 'Off'} · {digest_channel} · "
            f"{WEEKDAYS[data['digest_day']]} {hour_label(data['digest_hour'])} ({tz_name})"))
        await ctx.send(embed=embed)

    @stats_admin.command(name="exclude")
    async def admin_exclude(self, ctx: commands.Context, channel: ChannelArg):
        """Stop tracking a channel (and its threads). Existing counts are deleted."""
        cid = self._channel_key(channel)
        async with self.config.guild(ctx.guild).excluded_channels() as excluded:
            if cid not in excluded:
                excluded.append(cid)
        self._excluded.setdefault(ctx.guild.id, set()).add(cid)
        self._pending = Counter({k: v for k, v in self._pending.items() if k[:2] != (ctx.guild.id, cid)})
        for table in ("messages", "voice"):
            await self.db.query(f"DELETE FROM {table} WHERE guild = ? AND channel = ?", (ctx.guild.id, cid))
        await ctx.send(f"✅ {self._channel_name(ctx.guild, cid)} is no longer tracked, and its stats are deleted.")

    @stats_admin.command(name="include")
    async def admin_include(self, ctx: commands.Context, channel: ChannelArg):
        """Start tracking an excluded channel again."""
        cid = self._channel_key(channel)
        async with self.config.guild(ctx.guild).excluded_channels() as excluded:
            if cid in excluded:
                excluded.remove(cid)
        self._excluded.setdefault(ctx.guild.id, set()).discard(cid)
        await ctx.send(f"✅ {self._channel_name(ctx.guild, cid)} is tracked again.")

    @stats_admin.command(name="gametracking")
    async def admin_gametracking(self, ctx: commands.Context, enabled: bool):
        """Turn recording of games played (from Discord's "Playing" status) on or off."""
        await self.config.guild(ctx.guild).track_games.set(enabled)
        self._track_games[ctx.guild.id] = enabled
        if not enabled:
            for key in [k for k in self._games_open if k[0] == ctx.guild.id]:
                self._games_open.pop(key)
        await ctx.send(f"✅ Game tracking is {'on' if enabled else 'off'}.")

    @stats_admin.command(name="backfill")
    async def admin_backfill(self, ctx: commands.Context, days: int = 30):
        """
        Count messages from before tracking started by reading channel history (up to 90 days back).

        Only message counts can be backfilled; voice time and games can't. This can take a while on busy servers.
        """
        if ctx.guild.id in self._backfills and not self._backfills[ctx.guild.id].done():
            return await ctx.send("⏳ A backfill is already running here.")
        days = max(1, min(days, BACKFILL_MAX_DAYS))
        conf = self.config.guild(ctx.guild)
        until = await conf.backfilled_from() or await conf.started_at() or time.time()
        since = time.time() - days * DAY
        if since >= until:
            return await ctx.send(f"✅ Messages back to <t:{int(until)}:D> are already counted.")
        status = await ctx.send(f"⏳ Counting messages from <t:{int(since)}:D> to <t:{int(until)}:D>…")
        self._backfills[ctx.guild.id] = asyncio.create_task(self._backfill(ctx.guild, since, until, status))

    async def _backfill(self, guild: discord.Guild, since: float, until: float, status: discord.Message):
        counts, done = Counter(), 0
        excluded = self._excluded.get(guild.id, set())
        channels = [c for c in [*guild.text_channels, *guild.voice_channels, *guild.threads]
                    if c.permissions_for(guild.me).read_message_history and self._channel_key(c) not in excluded]
        after, before = datetime.fromtimestamp(since, timezone.utc), datetime.fromtimestamp(until, timezone.utc)
        try:
            for i, channel in enumerate(channels, 1):
                try:
                    async for message in channel.history(limit=None, after=after, before=before):
                        if message.author.bot or message.webhook_id or message.author.id in self._ignored:
                            continue
                        counts[(guild.id, self._channel_key(channel), message.author.id,
                                hour_of(message.created_at.timestamp()))] += 1
                        done += 1
                except discord.HTTPException as e:
                    log.debug("Skipped #%s during backfill: %s", channel, e)
                if i % 5 == 0:
                    await status.edit(content=f"⏳ Counting messages… {i}/{len(channels)} channels, {done:,} so far")
            await self.db.execute_many(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?) ON CONFLICT (guild, channel, user, hour) "
                "DO UPDATE SET count = count + excluded.count", [(*k, n) for k, n in counts.items()])
            await self.config.guild(guild).backfilled_from.set(int(since))
            await status.edit(content=f"✅ Backfill done: **{done:,}** messages in {len(channels)} channels, "
                                      f"from <t:{int(since)}:D>.")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Backfill failed in %s", guild)
            await status.edit(content="❌ The backfill failed. The error was logged; nothing was saved.")

    # ---------- weekly digest ----------

    @stats_admin.group(name="digest", invoke_without_command=True)
    async def admin_digest(self, ctx: commands.Context):
        """The weekly digest for admins. Turn it on, pick the channel and time, or preview it."""
        p = f"{ctx.clean_prefix}stats admin digest"
        await ctx.send(f"`{p} on` / `{p} off` · `{p} channel #channel` · `{p} time <day> <hour>` "
                       f"(for example `{p} time monday 9am`) · `{p} preview`")

    @admin_digest.command(name="on")
    async def digest_on(self, ctx: commands.Context):
        """Turn the weekly digest on."""
        conf = self.config.guild(ctx.guild)
        if await conf.digest_channel() is None:
            return await ctx.send(f"⚠️ Pick a channel first: `{ctx.clean_prefix}stats admin digest channel #channel`")
        await conf.digest_enabled.set(True)
        await ctx.send("✅ The weekly digest is on.")

    @admin_digest.command(name="off")
    async def digest_off(self, ctx: commands.Context):
        """Turn the weekly digest off."""
        await self.config.guild(ctx.guild).digest_enabled.set(False)
        await ctx.send("✅ The weekly digest is off.")

    @admin_digest.command(name="channel")
    async def digest_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Choose where the digest is posted. Pick an admin-only channel."""
        perms = channel.permissions_for(ctx.guild.me)
        if not (perms.send_messages and perms.embed_links and perms.attach_files):
            return await ctx.send(f"❌ I need to send messages, embeds and files in {channel.mention}.")
        await self.config.guild(ctx.guild).digest_channel.set(channel.id)
        note = "" if not channel.permissions_for(ctx.guild.default_role).view_channel else (
            "\n⚠️ Everyone can see that channel, and the digest includes admin-only stats.")
        await ctx.send(f"✅ The digest will be posted in {channel.mention}.{note}")

    @admin_digest.command(name="time")
    async def digest_time(self, ctx: commands.Context, day: str, hour: str):
        """Choose the day and hour, in the server's GameManager timezone. Example: `monday 9am`."""
        weekday = WEEKDAY_INPUT.get(day.lower())
        match = re.fullmatch(r"(\d{1,2})(?::00)?\s*(am|pm)?", hour.lower())
        if weekday is None or not match:
            return await ctx.send("❌ Use a day and hour, like `monday 9am` or `fri 18`.")
        value = int(match.group(1)) % 12 + (12 if match.group(2) == "pm" else 0) if match.group(2) else int(match.group(1))
        if not 0 <= value <= 23:
            return await ctx.send("❌ The hour must be 0–23, or 1–12 with am/pm.")
        await self.config.guild(ctx.guild).digest_day.set(weekday)
        await self.config.guild(ctx.guild).digest_hour.set(value)
        _, tz_name = await self._guild_tz(ctx.guild)
        await ctx.send(f"✅ The digest will go out on **{WEEKDAYS[weekday]}** at **{hour_label(value)}** ({tz_name}).")

    @admin_digest.command(name="preview", aliases=["now"])
    async def digest_preview(self, ctx: commands.Context):
        """Show this week's digest here."""
        await self._send(ctx, await self.report_digest(ctx.guild))

    @tasks.loop(minutes=10)
    async def digest_loop(self):
        for gid, data in (await self.config.all_guilds()).items():
            guild = self.bot.get_guild(gid)
            if guild is None or not data.get("digest_enabled") or not data.get("digest_channel"):
                continue
            try:
                await self._maybe_send_digest(guild, data)
            except Exception:
                log.exception("Weekly digest failed in %s", guild)

    @digest_loop.before_loop
    async def _before_digest(self):
        await self.bot.wait_until_red_ready()

    async def _maybe_send_digest(self, guild: discord.Guild, data: dict, now: Optional[datetime] = None):
        tz, _ = await self._guild_tz(guild)
        now = now or datetime.now(tz)
        local = now.astimezone(tz)
        due_day = local.date() - timedelta(days=(local.weekday() - data.get("digest_day", 0)) % 7)
        due = datetime.combine(due_day, datetime.min.time(), tz).replace(hour=data.get("digest_hour", 9))
        # Send once per week, any time in the 24 hours after it's due (covers the bot being down at that hour).
        if not (due <= local < due + timedelta(days=1)) or data.get("digest_last") == due_day.isoformat():
            return
        channel = guild.get_channel(data["digest_channel"])
        if channel is None:
            return
        await self.config.guild(guild).digest_last.set(due_day.isoformat())
        embed, file = await self._report_embed(await self.report_digest(guild))
        await channel.send(embed=embed, **({"file": file} if file else {}))
