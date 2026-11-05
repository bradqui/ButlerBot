"""
Game Manager cog for Red-DiscordBot.

A per-server game library: the games people own and have installed, rankings, a
shared-game finder, scheduled play sessions with join buttons, and votes on what
to play. Buttons keep working across restarts (discord.py dynamic items) and
running votes resume after a reload.
"""

import asyncio
import difflib
import importlib.util
import logging
import random
import re
import string
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Set, Tuple, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import aiohttp
import discord
from discord.ext import tasks
from redbot.core import Config, app_commands, checks, commands
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
log = logging.getLogger("red.gamemanager")

Target = Union[commands.Context, discord.Interaction]


# ==========================================
#                CONSTANTS
# ==========================================

DEFAULT_VOTE_SECONDS = 120
MIN_VOTE_SECONDS = 15
MAX_VOTE_SECONDS = 3600
MAX_VOTE_OPTIONS = 20           # four rows of five buttons
REMINDER_MINUTES = 15           # heads-up ping before a scheduled session
SESSION_EXPIRE_HOURS = 12       # sessions end on their own this long after starting (or being created)
LFG_COOLDOWN_SECONDS = 300
PICKER_PAGE_SIZE = 25           # Discord's limit for one select menu
LIST_PAGE_SIZE = 40             # lines per embed in long lists

PING = discord.AllowedMentions(everyone=False, roles=False, users=True)   # plain-text pings: reminders, LFG, winners
# Cards that ping (vote, sale alert, install request) pass pings([...]) with exactly the people meant.
NO_PING = ui.NO_PINGS
INSTALLED = "💾"                # marks installed games in lists

TZ_ALIASES = {
    "utc": "UTC", "gmt": "UTC", "z": "UTC",
    "et": "America/New_York", "est": "America/New_York", "edt": "America/New_York", "eastern": "America/New_York",
    "ct": "America/Chicago", "cst": "America/Chicago", "cdt": "America/Chicago", "central": "America/Chicago",
    "mt": "America/Denver", "mst": "America/Denver", "mdt": "America/Denver", "mountain": "America/Denver",
    "arizona": "America/Phoenix",
    "pt": "America/Los_Angeles", "pst": "America/Los_Angeles", "pdt": "America/Los_Angeles",
    "pacific": "America/Los_Angeles",
    "akst": "America/Anchorage", "alaska": "America/Anchorage", "hst": "Pacific/Honolulu", "hawaii": "Pacific/Honolulu",
    "bst": "Europe/London", "uk": "Europe/London", "cet": "Europe/Paris", "cest": "Europe/Paris",
    "aest": "Australia/Sydney", "aedt": "Australia/Sydney",
}
WEEKDAYS = {
    "mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5, "sun": 6, "sunday": 6,
}
LIBRARY_ACTIONS = {
    # action: (changed label, unchanged label, embed color)
    "own": ("Added to your library", "Already in your library", ui.SUCCESS),
    "unown": ("Removed from your library", "Not in your library", ui.DANGER),
    "install": ("Marked installed", "Already installed", ui.SUCCESS),
    "uninstall": ("Marked uninstalled", "Wasn't marked installed", ui.DANGER),
}
MEDALS = ["🥇", "🥈", "🥉"]
NOT_IN_LIBRARY = "❌ **Not in the server's library:** "
NOTHING_TO_CHANGE = "⚠️ Nothing to change."

RECURRING_POST_HOURS = 24       # a recurring session is posted this long before it starts
MAX_RECURRING = 10              # recurring schedules per server
EVENT_LENGTH_HOURS = 3          # Discord events need an end time when they aren't in a voice channel
SALE_CHECK_HOURS = 6            # how often wishlisted games' Steam prices are checked
FREE_GAMES_KEEP = 50            # Epic free-game IDs remembered so each is announced once

COMMON_TIMEZONES = [
    ("US Eastern (New York)", "America/New_York"), ("US Central (Chicago)", "America/Chicago"),
    ("US Mountain (Denver)", "America/Denver"), ("Arizona (Phoenix)", "America/Phoenix"),
    ("US Pacific (Los Angeles)", "America/Los_Angeles"), ("Alaska (Anchorage)", "America/Anchorage"),
    ("Hawaii (Honolulu)", "Pacific/Honolulu"), ("UK (London)", "Europe/London"),
    ("Central Europe (Paris, Berlin)", "Europe/Paris"), ("Eastern Europe (Helsinki)", "Europe/Helsinki"),
    ("Australia East (Sydney)", "Australia/Sydney"), ("UTC", "UTC"),
]

# Checking new game names: library near-match -> Steam exact name -> AI web search (Claude cog).
STEAM_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
STEAM_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAM_APP_URL = "https://store.steampowered.com/app/{}"
EPIC_FREE_URL = ("https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions"
                 "?locale=en-US&country=US&allowCountries=US")
EPIC_STORE_URL = "https://store.epicgames.com/en-US/"
MAX_CHECKED_NAMES = 10          # bigger bulk adds skip the Steam and AI lookups
MAX_AI_TITLE_LOOKUPS = 5        # AI web searches per command (about 1¢ each)

# Read-only lookups the Claude cog's bot guide can call (see GameManager.guide_call_tool).
GUIDE_TOOLS = [
    {
        "name": "games_library",
        "description": "Look up a server member's game library: the games they own, which ones are installed, and "
                       "their rankings (1 = favorite).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"member": {"type": "string",
                                      "description": "Their display name, username, or mention, or \"me\" for the "
                                                     "person asking."}},
            "required": ["member"],
            "additionalProperties": False,
        },
    },
    {
        "name": "games_game",
        "description": "Look up one game: whether it's in the server library (or waiting for approval), and who owns "
                       "it or has it installed.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"game": {"type": "string", "description": "The game's name, even partial."}},
            "required": ["game"],
            "additionalProperties": False,
        },
    },
    {
        "name": "games_activity",
        "description": "List this server's active game sessions and running votes: titles, hosts, players, start "
                       "times, vote options, and current tallies.",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
]


# ==========================================
#                 HELPERS
# ==========================================

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value) -> Optional[datetime]:
    """Stored times are ISO strings. Older data was saved without a timezone, meaning UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def stamp(dt: datetime, style: str = "F") -> str:
    """Discord timestamp, shown in each reader's own timezone."""
    return f"<t:{int(dt.timestamp())}:{style}>"


def generate_id() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def user_entry(users: dict, user_id) -> dict:
    data = users.setdefault(str(user_id), {})
    data.setdefault("owned", [])
    data.setdefault("installed", [])
    data.setdefault("ranks", {})
    return data


def apply_change(data: dict, game_id: str, action: str) -> bool:
    """Apply own/unown/install/uninstall to one user's entry. Installing implies owning. Returns whether anything changed."""
    owned, installed, ranks = data["owned"], data["installed"], data["ranks"]
    if action == "own":
        if game_id in owned:
            return False
        owned.append(game_id)
        return True
    if action == "install":
        if game_id not in owned:
            owned.append(game_id)
        if game_id in installed:
            return False
        installed.append(game_id)
        return True
    if action == "unown":
        if game_id not in owned and game_id not in installed:
            return False
        for lst in (owned, installed):
            if game_id in lst:
                lst.remove(game_id)
        ranks.pop(game_id, None)
        return True
    if action == "uninstall":
        if game_id not in installed:
            return False
        installed.remove(game_id)
        return True
    raise ValueError(action)


def resolve_game(games: Dict[str, dict], name: str) -> Tuple[Optional[dict], List[dict]]:
    """
    Find a game by name: exact (ignoring case, spaces and punctuation), else a partial match
    only if exactly one game fits. Returns (game, []) or (None, close candidates).
    """
    key = normalize(name)
    if not key:
        return None, []
    wanted = name.strip().lower()
    for game in games.values():
        if game["name"].lower() == wanted:
            return game, []
    exact = [g for g in games.values() if normalize(g["name"]) == key]
    if len(exact) == 1:
        return exact[0], []
    partial = [g for g in games.values() if key in normalize(g["name"])]
    if len(partial) == 1:
        return partial[0], []
    partial.sort(key=lambda g: (not normalize(g["name"]).startswith(key), len(g["name"])))
    if exact or partial:
        return None, (exact or partial)[:5]
    # Typos ("rocket leage"): suggest close spellings, but never pick one automatically.
    by_key = {normalize(g["name"]): g for g in games.values()}
    return None, [by_key[k] for k in difflib.get_close_matches(key, list(by_key), n=3, cutoff=0.8)]


def clean_title(name: str) -> str:
    """Drop trademark symbols and extra spaces: 'HELLDIVERS™  2' -> 'HELLDIVERS 2'."""
    return re.sub(r"\s+", " ", re.sub(r"[™®©]", "", name)).strip()[:100]


async def _get_json(url: str, params: Optional[dict] = None, timeout: float = 8):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.get(url, params=params) as resp:
            return await resp.json(content_type=None)


async def steam_search(term: str) -> List[Tuple[str, int]]:
    """(title, app id) for the games Steam's store search finds, best match first."""
    try:
        data = await _get_json(STEAM_SEARCH_URL, {"term": term, "l": "english", "cc": "US"})
    except Exception as e:
        log.debug("Steam search failed for %r: %s", term, e)
        return []
    found = []
    for item in (data or {}).get("items", []):
        title = clean_title(item.get("name") or "")
        if item.get("type") == "app" and title and item.get("id"):
            found.append((title, int(item["id"])))
    return found


async def steam_exact_title(name: str) -> Optional[Tuple[str, int]]:
    """(title, app id) if Steam's store search has a game with exactly this name, ignoring case and symbols."""
    return next(((t, a) for t, a in await steam_search(name) if normalize(t) == normalize(name)), None)


async def steam_prices(appids: List[int]) -> Dict[int, Optional[dict]]:
    """
    Current US Steam prices: app id -> {"final", "initial" (cents), "discount" (%), "final_text", "initial_text"},
    or None for free or unlisted games. Apps Steam didn't answer for are left out.
    """
    prices: Dict[int, Optional[dict]] = {}
    for i in range(0, len(appids), 50):
        chunk = appids[i:i + 50]
        try:
            data = await _get_json(STEAM_DETAILS_URL, {"appids": ",".join(map(str, chunk)), "cc": "us",
                                                       "filters": "price_overview"}, timeout=15)
        except Exception as e:
            log.debug("Steam price check failed: %s", e)
            continue
        for appid in chunk:
            entry = (data or {}).get(str(appid)) or {}
            if not entry.get("success"):
                continue
            overview = entry.get("data") or {}
            overview = overview.get("price_overview") if isinstance(overview, dict) else None
            prices[appid] = None if not overview else {
                "final": overview.get("final", 0), "initial": overview.get("initial", 0),
                "discount": overview.get("discount_percent", 0),
                "final_text": overview.get("final_formatted", ""), "initial_text": overview.get("initial_formatted", ""),
            }
    return prices


async def epic_free_games() -> List[dict]:
    """Games free to keep on the Epic Games Store right now: [{"id", "title", "url", "ends"}]. Unofficial feed."""
    try:
        data = await _get_json(EPIC_FREE_URL, timeout=15)
        elements = data["data"]["Catalog"]["searchStore"]["elements"]
    except Exception as e:
        log.debug("Epic free games check failed: %s", e)
        return []
    now = utcnow()
    free = []
    for item in elements or []:
        try:
            if (item.get("price") or {}).get("totalPrice", {}).get("discountPrice") != 0:
                continue
            offers = [o for group in ((item.get("promotions") or {}).get("promotionalOffers") or [])
                      for o in group.get("promotionalOffers", [])]
            current = [o for o in offers if o.get("discountSetting", {}).get("discountPercentage") == 0
                       and parse_iso(o.get("startDate")) and parse_iso(o["startDate"]) <= now
                       < (parse_iso(o.get("endDate")) or now + timedelta(days=1))]
            if not current:
                continue
            slug = (item.get("productSlug") or next(
                (m.get("pageSlug") for m in (item.get("catalogNs") or {}).get("mappings") or [] if m.get("pageSlug")),
                None) or next((m.get("pageSlug") for m in item.get("offerMappings") or [] if m.get("pageSlug")), None))
            free.append({"id": item.get("id") or item.get("title"), "title": item.get("title", "A free game"),
                         "url": f"{EPIC_STORE_URL}p/{slug.split('/')[0]}" if slug else f"{EPIC_STORE_URL}free-games",
                         "ends": current[0].get("endDate")})
        except Exception:
            log.debug("Skipped an Epic store entry", exc_info=True)
    return free


def price_text(price: Optional[dict]) -> str:
    if not price:
        return "free or not for sale"
    if price["discount"]:
        return f"**{price['discount']}% off**: {price['final_text']} (was {price['initial_text']})"
    return price["final_text"]


def describe_unresolved(name: str, candidates: List[dict]) -> str:
    if candidates:
        return f"`{name}` could be " + ", ".join(f"**{g['name']}**" for g in candidates)
    return f"`{name}`"


# Quotes only count at word boundaries, so "Assassin's Creed, Baldur's Gate" stays two names.
QUOTED = r'(?<!\w)"([^"]+)"(?!\w)|(?<!\w)\'([^\']+)\'(?!\w)'


def parse_game_names(text: str) -> List[str]:
    """Split comma- or line-separated game names. Quotes keep a name with commas together."""
    names = []
    for match in re.findall(QUOTED, text):
        name = (match[0] or match[1]).strip()
        if name:
            names.append(name)
    for part in re.split(r"[,\n]", re.sub(QUOTED, "", text)):
        if part.strip():
            names.append(part.strip())
    return names


def parse_duration(text: str) -> Optional[int]:
    """'90', '90s', '3m', '1h' -> seconds."""
    m = re.fullmatch(r"(\d+)\s*(s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?)?", text.strip().lower())
    if not m:
        return None
    unit = (m.group(2) or "s")[0]
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[unit]


# ---------- session times ----------

def load_zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def find_timezone(name: str) -> Optional[str]:
    """Accept IANA names (America/Chicago), city names (chicago) and common abbreviations (CST)."""
    text = name.strip()
    alias = TZ_ALIASES.get(text.lower())
    if alias:
        return alias
    try:
        ZoneInfo(text)
        return text
    except (ZoneInfoNotFoundError, ValueError):
        pass
    wanted = text.lower().replace(" ", "_")
    try:
        zones = available_timezones()
    except Exception:
        zones = set()
    for zone in sorted(zones):
        lowered = zone.lower()
        if lowered == wanted or lowered.endswith("/" + wanted):
            return zone
    return None


def _parse_clock(text: str) -> Optional[Tuple[int, int]]:
    text = text.replace(" ", "").lower()
    if text == "noon":
        return 12, 0
    if text == "midnight":
        return 0, 0
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm|a|p)", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2) or 0)
        if not 1 <= hour <= 12 or minute > 59:
            return None
        return hour % 12 + (12 if m.group(3).startswith("p") else 0), minute
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return int(m.group(1)), int(m.group(2))
    return None


def _parse_day(word: Optional[str], today: date) -> Optional[Tuple[date, str]]:
    """(date, kind) where kind is 'implicit', 'fixed' or 'weekday'."""
    if word is None:
        return today, "implicit"
    word = word.lower().rstrip(",")
    if word in ("today", "tonight"):
        return today, "fixed"
    if word in ("tomorrow", "tmrw", "tmr"):
        return today + timedelta(days=1), "fixed"
    if word in WEEKDAYS:
        return today + timedelta(days=(WEEKDAYS[word] - today.weekday()) % 7), "weekday"
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", word)
    if m:
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            day = date(year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
        if not m.group(3) and day < today:
            day = day.replace(year=day.year + 1)
        return day, "fixed"
    return None


def parse_when(phrase: str, tz: tzinfo, now: datetime) -> Optional[datetime]:
    """
    Parse a start time: 'in 2h', 'in 1h30m', '9pm', '9:30 pm', '21:00', 'tonight 9pm',
    'tomorrow 8pm', 'friday 9pm', '9pm fri', '11/14 7pm', or a pasted Discord timestamp.
    """
    text = phrase.strip().lower()
    m = re.fullmatch(r"<t:(\d+)(?::[a-z])?>", text)
    if m:
        return datetime.fromtimestamp(int(m.group(1)), timezone.utc)
    m = re.fullmatch(r"in\s+((?:\d+\s*(?:h|hrs?|hours?|m|mins?|minutes?)\s*)+)", text)
    if m:
        seconds = sum(int(n) * (3600 if unit == "h" else 60) for n, unit in re.findall(r"(\d+)\s*([hm])", m.group(1)))
        return now + timedelta(seconds=seconds) if seconds else None

    tokens = text.split()
    local_now = now.astimezone(tz)
    for day_tokens, clock_tokens in ((tokens[:1], tokens[1:]), (tokens[-1:], tokens[:-1]), ([], tokens)):
        if not clock_tokens:
            continue
        clock = _parse_clock("".join(clock_tokens))
        if clock is None:
            continue
        parsed = _parse_day(day_tokens[0] if day_tokens else None, local_now.date())
        if parsed is None:
            continue
        day, kind = parsed
        when = datetime(day.year, day.month, day.day, clock[0], clock[1], tzinfo=tz)
        if when <= local_now and kind == "implicit":
            when += timedelta(days=1)
        elif when <= local_now and kind == "weekday":
            when += timedelta(days=7)
        return when.astimezone(timezone.utc)
    return None


def split_when(text: str, tz: tzinfo, now: datetime) -> Tuple[Optional[datetime], str]:
    """Pull a start time off the front of '<time> <title>'. Returns (time or None, title)."""
    tokens = text.split()
    for n in range(min(4, len(tokens)), 0, -1):
        when = parse_when(" ".join(tokens[:n]), tz, now)
        if when is not None:
            return when, " ".join(tokens[n:])
    return None, text.strip()


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def next_weekly(weekday: int, clock: Tuple[int, int], tz: tzinfo, now: datetime) -> datetime:
    """The next time it's `weekday` at `clock` in `tz`, after now (UTC)."""
    local = now.astimezone(tz)
    day = local.date() + timedelta(days=(weekday - local.weekday()) % 7)
    when = datetime(day.year, day.month, day.day, *clock, tzinfo=tz)
    if when <= local:
        day += timedelta(days=7)
        when = datetime(day.year, day.month, day.day, *clock, tzinfo=tz)
    return when.astimezone(timezone.utc)


def parse_recurring(text: str, tz: tzinfo, now: datetime) -> Optional[dict]:
    """'every friday 9pm Raid night', 'every other fri 21:00', 'weekly sat 8:30 pm' -> schedule fields, or None."""
    tokens = text.split()
    if not tokens or tokens[0].lower() not in ("every", "weekly"):
        return None
    rest, interval = tokens[1:], 7
    if rest and rest[0].lower() in ("other", "second"):
        rest, interval = rest[1:], 14
    day = rest[0].lower().rstrip(",") if rest else ""
    if day not in WEEKDAYS:
        return None
    for n in (2, 1):
        clock = _parse_clock("".join(rest[1:1 + n])) if len(rest) >= 1 + n else None
        if clock is not None:
            return {"weekday": WEEKDAYS[day], "hour": clock[0], "minute": clock[1], "interval": interval,
                    "title": " ".join(rest[1 + n:]), "first": next_weekly(WEEKDAYS[day], clock, tz, now)}
    return None


def advance_occurrence(start: datetime, schedule: dict) -> datetime:
    """The occurrence after `start`, keeping the local time across daylight saving changes."""
    tz = load_zone(schedule["tz"])
    day = start.astimezone(tz).date() + timedelta(days=schedule["interval"])
    return datetime(day.year, day.month, day.day, schedule["hour"], schedule["minute"],
                    tzinfo=tz).astimezone(timezone.utc)


def repeat_label(schedule: dict) -> str:
    clock = datetime(2000, 1, 1, schedule["hour"], schedule["minute"]).strftime("%I:%M %p").lstrip("0")
    every = "Every other" if schedule["interval"] == 14 else "Every"
    return f"{every} {DAY_NAMES[schedule['weekday']]} at {clock.replace(':00', '')} ({schedule['tz']})"


def rank_score(users: dict, voter_ids: List[str], game_id: str) -> float:
    """Average preference among the voters who own a game: rank 1 = 1.0, rank 2 = 0.5, unranked = 0.01."""
    scores = []
    for uid in voter_ids:
        data = users.get(uid, {})
        if game_id in data.get("owned", []) or game_id in data.get("installed", []):
            rank = data.get("ranks", {}).get(game_id)
            scores.append(1.0 / rank if rank else 0.01)
    return sum(scores) / len(scores) if scores else 0.0


def pings(user_ids) -> discord.AllowedMentions:
    """
    Ping exactly these people and nobody else. Mentions inside card text DO ping, so cards that should ping pass
    this (Discord accepts at most 100 users); everything else is sent with NO_PING.
    """
    ids = list(dict.fromkeys(str(u) for u in user_ids))[:100]
    return discord.AllowedMentions(everyone=False, roles=False, replied_user=False,
                                   users=[discord.Object(int(u)) for u in ids])


def mention_list(user_ids, limit: int = 40) -> str:
    """`<@1>, <@2>, <@3>` (at most `limit`, then "and N more")."""
    ids = [f"<@{u}>" for u in user_ids]
    return ", ".join(ids[:limit]) + (f" and {len(ids) - limit} more" if len(ids) > limit else "")


def store_button(url: str, label: str, emoji: Optional[str] = None) -> discord.ui.Button:
    """A link button (to a store page). Link buttons stay live when a menu expires."""
    return discord.ui.Button(label=label, url=url, emoji=emoji)


def who(target: Target) -> Tuple[discord.Guild, discord.Member, discord.abc.Messageable]:
    if isinstance(target, discord.Interaction):
        return target.guild, target.user, target.channel
    return target.guild, target.author, target.channel


def game_admin():
    """Check for game-admin commands: server admins, Red admins, the bot owner, or the configured game admin role."""
    async def predicate(ctx: commands.Context) -> bool:
        cog = ctx.bot.get_cog("GameManager")
        if ctx.guild is None or cog is None:
            return False
        if await cog.is_game_admin(ctx.author):
            return True
        raise commands.UserFeedbackCheckFailure("🔒 Only game admins can do that (server admins or the game admin role).")

    predicate.requirement = "game admin"  # read by the Claude cog's bot guide
    return commands.check(predicate)


# ==========================================
#     PERSISTENT BUTTONS (survive restarts)
# ==========================================

class SessionButton(discord.ui.DynamicItem[discord.ui.Button],
                    template=r"gm:s:(?P<action>join|leave|vote|end):(?P<sid>[a-z0-9]+)"):
    LOOKS = {   # one main action (Join); everything else grey
        "join": ("Join", "➕", discord.ButtonStyle.primary),
        "leave": ("Leave", "➖", discord.ButtonStyle.secondary),
        "vote": ("Start vote", "🗳️", discord.ButtonStyle.secondary),
        "end": ("End session", "🏁", discord.ButtonStyle.secondary),
    }

    def __init__(self, action: str, sid: str):
        label, emoji, style = self.LOOKS[action]
        super().__init__(discord.ui.Button(label=label, emoji=emoji, style=style, custom_id=f"gm:s:{action}:{sid}"))
        self.action, self.sid = action, sid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], match["sid"])

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("GameManager")
        if cog is not None and interaction.guild is not None:
            await cog.on_session_button(interaction, self.action, self.sid)


class VoteButton(discord.ui.DynamicItem[discord.ui.Button],
                 template=r"gm:v:(?P<vid>[a-z0-9]+):(?P<gid>[a-z0-9]+)"):
    def __init__(self, vid: str, gid: str, label: str = "Vote"):
        # Every option weighs the same, so none of them is the blurple "main" button.
        super().__init__(discord.ui.Button(label=label[:80], style=discord.ButtonStyle.secondary,
                                           custom_id=f"gm:v:{vid}:{gid}"))
        self.vid, self.gid = vid, gid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["vid"], match["gid"], getattr(item, "label", None) or "Vote")

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("GameManager")
        if cog is not None and interaction.guild is not None:
            await cog.on_vote_button(interaction, self.vid, self.gid)


class RequestButton(discord.ui.DynamicItem[discord.ui.Button],
                    template=r"gm:r:(?P<action>approve|deny):(?P<rid>[a-z0-9]+)"):
    def __init__(self, action: str, rid: str):
        approve = action == "approve"
        super().__init__(discord.ui.Button(
            label="Approve" if approve else "Deny",
            style=discord.ButtonStyle.primary if approve else discord.ButtonStyle.secondary,
            custom_id=f"gm:r:{action}:{rid}",
        ))
        self.action, self.rid = action, rid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], match["rid"])

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("GameManager")
        if cog is not None and interaction.guild is not None:
            await cog.on_request_button(interaction, self.action, self.rid)


class InstallButton(discord.ui.DynamicItem[discord.ui.Button], template=r"gm:i:(?P<rid>[a-z0-9]+)"):
    def __init__(self, rid: str):
        super().__init__(discord.ui.Button(label="I've installed it", emoji="💾", style=discord.ButtonStyle.primary,
                                           custom_id=f"gm:i:{rid}"))
        self.rid = rid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["rid"])

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("GameManager")
        if cog is not None and interaction.guild is not None:
            await cog.on_install_button(interaction, self.rid)


def session_buttons(sid: str) -> List[discord.ui.Item]:
    return [SessionButton(action, sid) for action in ("join", "leave", "vote", "end")]


# Classic views: only for session, vote and request messages posted as embeds before the switch to cards
# (2026-11-05). New messages are cards with the same persistent buttons inside them; the custom IDs didn't change.

def session_view(sid: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for button in session_buttons(sid):
        view.add_item(button)
    return view


def vote_view(vid: str, labels: List[Tuple[str, str]]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for gid, label in labels:
        view.add_item(VoteButton(vid, gid, label))
    return view


def request_view(rid: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(RequestButton("approve", rid))
    view.add_item(RequestButton("deny", rid))
    return view


# ==========================================
#            SHORT-LIVED MENUS
# ==========================================
# Every menu is a card (Components V2) that only the person who opened it can use. When it times out its
# buttons grey out and the card gets "Expired." plus `expired_note`'s detail. A card message can never turn back
# into a plain one, so every "after" state (saved, cancelled, chosen) is a card too: `final_card()`.

def final_card(text: str, *, title: Optional[str] = None, color: discord.Color = ui.BRAND,
               footer: Optional[str] = None) -> ui.CardView:
    """A finished menu: the same card slot, with no buttons left."""
    return ui.CardView(ui.card(text, title=title, color=color, footer=footer))


def make_button(label: str, callback, *, style=discord.ButtonStyle.secondary, emoji=None,
                disabled: bool = False) -> discord.ui.Button:
    button = discord.ui.Button(label=label, style=style, emoji=emoji, disabled=disabled)
    button.callback = callback
    return button


class OwnerOnlyCard(ui.ExpiringCard):
    """A card menu only the person who opened it can use (expiry and the 🔒 notice come from ui.ExpiringCard)."""

    expired_note = "Expired."

    def __init__(self, user_id: int, timeout: float):
        super().__init__(user_id, timeout=timeout)
        self.user_id = user_id


class ConfirmView(OwnerOnlyCard):
    """Are you sure? A red confirm button (it's destructive) and a grey Cancel."""

    expired_note = "Expired. Nothing happened."

    def __init__(self, user_id: int, text: str = "", label: str = "Confirm", timeout: float = 60,
                 title: Optional[str] = None):
        super().__init__(user_id, timeout)
        self.text, self.title = text, title
        self.value: Optional[bool] = None
        self.interaction: Optional[discord.Interaction] = None
        self.add_item(ui.card(text, [make_button(label, self._confirm, style=discord.ButtonStyle.danger),
                                     make_button("Cancel", self._cancel)],
                              title=title, color=ui.ATTENTION))

    async def _confirm(self, interaction: discord.Interaction):
        self.value, self.interaction = True, interaction
        self.stop()

    async def _cancel(self, interaction: discord.Interaction):
        self.value, self.interaction = False, interaction
        self.stop()


class NameCheckView(OwnerOnlyCard):
    """Accept the corrected game names, keep what was typed, or cancel."""

    expired_note = "Expired. Nothing was added or requested."

    def __init__(self, user_id: int, plural: bool, text: str = ""):
        super().__init__(user_id, timeout=180)
        self.choice: Optional[str] = None
        self.text = text
        self.title = "🎮 Check the names" if plural else "🎮 Check the name"
        buttons = [
            make_button("Use the suggested names" if plural else "Use the suggested name", self._choose("suggested"),
                        style=discord.ButtonStyle.primary),
            make_button("Use what I typed", self._choose("typed")),
            make_button("Cancel", self._choose("cancel")),
        ]
        self.add_item(ui.card(text, buttons, title=self.title))

    def _choose(self, value: str):
        async def callback(interaction: discord.Interaction):
            self.choice = value
            self.stop()
            note = {"suggested": "Using the suggested name.", "typed": "Using the name as typed.",
                    "cancel": "Cancelled. Nothing was added or requested."}[value]
            await interaction.response.edit_message(
                view=final_card(f"{self.text}\n{ui.hint(note)}", title=self.title,
                                color=ui.MUTED if value == "cancel" else ui.BRAND),
                allowed_mentions=NO_PING)
        return callback


class FilterModal(discord.ui.Modal, title="Find games"):
    query = discord.ui.TextInput(label="Part of the name (empty shows all)", required=False, max_length=100)

    def __init__(self, picker: "GamePickerView"):
        super().__init__()
        self.picker = picker
        self.query.default = picker.filter or None

    async def on_submit(self, interaction: discord.Interaction):
        self.picker.filter = self.query.value.strip()
        self.picker.page = 0
        await self.picker.refresh(interaction)


class GamePickerView(OwnerOnlyCard):
    """
    Tick-box editor for a set of games, 25 per page with page buttons and a search box.

    The card lists the page with ☑️/⬜ marks. The dropdown has no pre-selected options (Discord would
    draw every one as a chip and crowd the menu); choosing games toggles them. Save applies the changes.
    """

    expired_note = "Expired. Nothing was saved."

    def __init__(self, user: discord.abc.User, games: List[dict], selected: Set[str], title: str, hint: str,
                 on_save: Callable[[discord.Interaction, Set[str], Set[str]], Awaitable[None]],
                 on_cancel: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None):
        super().__init__(user.id, timeout=600)
        self.user_name = user.display_name
        self.games = sorted(games, key=lambda g: g["name"].lower())
        self.initial = set(selected)
        self.selected = set(selected)
        self.title = title
        self.hint = hint
        self.on_save = on_save
        self.on_cancel = on_cancel
        self.filter = ""
        self.page = 0
        self.redraw()

    def visible(self) -> List[dict]:
        if not self.filter:
            return self.games
        key = normalize(self.filter)
        return [g for g in self.games if key in normalize(g["name"])]

    def page_count(self) -> int:
        return max(1, -(-len(self.visible()) // PICKER_PAGE_SIZE))

    def page_games(self) -> Tuple[int, List[dict]]:
        visible = self.visible()
        self.page = min(self.page, self.page_count() - 1)
        start = self.page * PICKER_PAGE_SIZE
        return start, visible[start:start + PICKER_PAGE_SIZE]

    def text(self) -> str:
        """The card's body: the hint, this page's games with their ticks, and the unsaved changes."""
        visible = self.visible()
        _, page = self.page_games()
        lines = [self.hint, ""]
        if self.filter:
            lines.append(f"🔍 Games matching **{self.filter}** ({len(visible)})")
        for g in page:
            ticked = g["id"] in self.selected
            changed = ticked != (g["id"] in self.initial)
            name = f"**{g['name']}**" if changed else g["name"]
            lines.append(f"{ui.TICK if ticked else ui.UNTICK} {name}" + (" *(unsaved)*" if changed else ""))
        if not visible:
            lines.append("No games match. Use **Search** to try another name.")
        changes = []
        if self.selected - self.initial:
            changes.append(f"+{len(self.selected - self.initial)}")
        if self.initial - self.selected:
            changes.append(f"−{len(self.initial - self.selected)}")
        lines.append("")
        lines.append(f"**Ticked in total:** {len(self.selected)}"
                     + (f" ({', '.join(changes)} unsaved, press **Save**)" if changes else ""))
        return ui.truncate("\n".join(lines), 3500)

    def build(self) -> discord.ui.Container:
        _, page = self.page_games()
        select = None
        if page:
            select = discord.ui.Select(
                placeholder="Choose games to tick or untick…",
                min_values=1,
                max_values=len(page),
                options=[
                    discord.SelectOption(
                        label=g["name"][:100], value=g["id"],
                        emoji=ui.TICK if g["id"] in self.selected else ui.UNTICK,
                        description="Ticked · choose to untick" if g["id"] in self.selected else "Choose to tick",
                    )
                    for g in page
                ],
            )

            async def on_select(interaction: discord.Interaction):
                self.selected ^= set(select.values)  # toggle each chosen game
                await self.refresh(interaction)

            select.callback = on_select

        # One row for paging and search (all with icons), one for Save (the one main action) and Cancel.
        nav = [make_button("Prev", self._prev, emoji="◀️", disabled=self.page == 0),
               make_button("Next", self._next, emoji="▶️", disabled=self.page >= self.page_count() - 1),
               make_button("Search", self._search, emoji="🔍")]
        if self.filter:
            nav.append(make_button("Show all", self._clear, emoji="📋"))
        actions = [make_button("Save", self._save, style=discord.ButtonStyle.primary),
                   make_button("Cancel", self._cancel)]
        return ui.card(self.text(), [select] if select else None, nav, actions, title=self.title,
                       footer=f"Page {self.page + 1}/{self.page_count()} · Only {self.user_name} can use this menu")

    async def refresh(self, interaction: discord.Interaction):
        self.redraw()
        await interaction.response.edit_message(view=self, allowed_mentions=NO_PING)

    async def _prev(self, interaction):
        self.page -= 1
        await self.refresh(interaction)

    async def _next(self, interaction):
        self.page += 1
        await self.refresh(interaction)

    async def _search(self, interaction):
        await interaction.response.send_modal(FilterModal(self))

    async def _clear(self, interaction):
        self.filter, self.page = "", 0
        await self.refresh(interaction)

    async def _save(self, interaction):
        self.stop()
        await self.on_save(interaction, self.initial, self.selected)

    async def _cancel(self, interaction):
        self.stop()
        if self.on_cancel is not None:
            return await self.on_cancel(interaction)
        await interaction.response.edit_message(
            view=final_card("Cancelled. Nothing was changed.", title=self.title, color=ui.MUTED),
            allowed_mentions=NO_PING)


class UnknownGamesView(OwnerOnlyCard):
    """Offered when someone names games the server library doesn't have yet: the change's result plus one button."""

    expired_note = "Expired. Nothing was added or requested."
    TITLES = {"own": "🎮 Your library", "install": "🎮 Your installed games"}

    def __init__(self, cog: "GameManager", user_id: int, names: List[str], action: str, can_add: bool,
                 text: str = ""):
        super().__init__(user_id, timeout=300)
        self.cog, self.names, self.action, self.can_add, self.text = cog, names, action, can_add, text
        self.title = self.TITLES.get(action, "🎮 Your library")
        them = "them" if len(names) > 1 else "it"
        go = make_button(f"Add {them} to the library" if can_add else f"Request {them}", self._go,
                         emoji="➕" if can_add else "📨", style=discord.ButtonStyle.primary)
        footer = ("Adds them to the server library and to yours" if can_add
                  else "Ask a game admin to add them: the button sends a request")
        self.add_item(ui.card(text, [go], title=self.title, footer=footer))

    async def _go(self, interaction: discord.Interaction):
        self.stop()
        await interaction.response.edit_message(view=final_card(self.text, title=self.title),
                                                allowed_mentions=NO_PING)
        ephemeral = interaction.message is not None and interaction.message.flags.ephemeral
        text = await self.cog.add_unknown_games(interaction, self.names, self.action, add=self.can_add,
                                                ephemeral=ephemeral)
        if text:
            await interaction.followup.send(text, ephemeral=ephemeral, allowed_mentions=NO_PING)


class SteamPickView(OwnerOnlyCard):
    """Choose which Steam game was meant when the name isn't an exact match."""

    expired_note = "Expired. That game was skipped."
    TITLE = "🎮 Which game?"

    def __init__(self, user_id: int, options: List[Tuple[str, int]], name: str = ""):
        super().__init__(user_id, timeout=180)
        self.choice: Optional[Tuple[str, int]] = None
        select = discord.ui.Select(placeholder="Choose the game…", options=[
            discord.SelectOption(label=title[:100], value=str(appid), description=f"Steam app {appid}")
            for title, appid in options[:25]])

        async def on_select(interaction: discord.Interaction):
            appid = int(select.values[0])
            self.choice = next((t, a) for t, a in options if a == appid)
            self.stop()
            await interaction.response.edit_message(
                view=final_card(ui.line(ui.DONE, f"**{self.choice[0]}**"), title=self.TITLE, color=ui.SUCCESS),
                allowed_mentions=NO_PING)

        async def on_cancel(interaction: discord.Interaction):
            self.stop()
            await interaction.response.edit_message(
                view=final_card(ui.line(ui.DONE, "Skipped. Nothing was added for that name."), title=self.TITLE,
                                color=ui.MUTED),
                allowed_mentions=NO_PING)

        select.callback = on_select
        question = f"Which game on Steam did you mean by **{name}**?" if name else "Which game on Steam did you mean?"
        self.add_item(ui.card(question, [select], [make_button("None of these", on_cancel)], title=self.TITLE))


class TextModal(discord.ui.Modal):
    """A one-field form whose answer goes to a callback."""

    def __init__(self, title: str, label: str, placeholder: str,
                 on_submit: Callable[[discord.Interaction, str], Awaitable[None]], paragraph: bool = True):
        super().__init__(title=title)
        self.field = discord.ui.TextInput(label=label, placeholder=placeholder, max_length=1000,
                                          style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short)
        self.add_item(self.field)
        self._callback = on_submit

    async def on_submit(self, interaction: discord.Interaction):
        await self._callback(interaction, self.field.value)


PROFILE_STEPS = ("timezone", "owned", "installed", "favorites", "wishlist")
PROFILE_TITLES = {"timezone": "Your timezone", "owned": "Games you own", "installed": "Games you have installed",
                  "favorites": "Your favorites", "wishlist": "Games you want"}


class ProfileWizard(OwnerOnlyCard):
    """
    `[p]games newprofile`: timezone, library, installed games, top 3 and wishlist, one skippable step at a time.

    Every screen is a fresh card view on the same message (the previous one is stopped), and pickers temporarily
    take over the message and hand back to the wizard when they're saved or cancelled. `state` carries everything
    between screens: cog, guild, member, ephemeral, step and the note about the last change.
    """

    expired_note = "Expired. Everything you saved is kept."

    def __init__(self, state: dict):
        super().__init__(state["member"].id, timeout=900)
        self.state = state
        self.cog: "GameManager" = state["cog"]
        self.message = state.get("message")

    @staticmethod
    async def display(state: dict, interaction: Optional[discord.Interaction] = None) -> "ProfileWizard":
        view = ProfileWizard(state)
        await view.render()
        if interaction is None:
            return view
        if interaction.response.is_done():
            await interaction.edit_original_response(view=view, allowed_mentions=NO_PING)
        else:
            await interaction.response.edit_message(view=view, allowed_mentions=NO_PING)
        return view

    async def move(self, interaction: discord.Interaction, step: int, note: Optional[str] = None):
        self.stop()
        self.state.update(step=step, note=note)
        await ProfileWizard.display(self.state, interaction)

    async def render(self):
        """Draw the current step (or the summary) as this view's card."""
        state, cog = self.state, self.cog
        guild, member, step = state["guild"], state["member"], state["step"]
        games = await cog.config.guild(guild).games()
        data = (await cog.config.guild(guild).users()).get(str(member.id), {})
        owned = [g for g in dict.fromkeys(data.get("installed", []) + data.get("owned", [])) if g in games]
        self.clear_items()
        if step >= len(PROFILE_STEPS):
            self.add_item(await self._summary(games, data, owned))
            self.stop()   # nothing left to press, so nothing to expire
            return
        name = PROFILE_STEPS[step]
        lines: List[Optional[str]] = []
        selects: List[discord.ui.Select] = []
        buttons: List[discord.ui.Button] = []
        if name == "timezone":
            _, tz_name, personal = await cog.timezone_for(member)
            lines += ["Game session times are read and shown in your timezone.",
                      f"Right now it's **{tz_name}**{'' if personal else ' (the server default)'}.",
                      "Choose yours below, or press **Next** to keep it."]
            select = discord.ui.Select(placeholder="Choose your timezone…", options=[
                discord.SelectOption(label=label, value=zone, default=personal and zone == tz_name)
                for label, zone in COMMON_TIMEZONES])
            select.callback = lambda i: self._set_timezone(i, select.values[0])
            selects.append(select)
            buttons.append(make_button("Other timezone…", self._other_timezone, emoji="🌐"))
        elif name == "owned":
            lines += [f"You have **{ui.plural(len(owned), 'game')}** in your library.",
                      "Tick them from the server's list, or type their names. Games the server doesn't have yet can "
                      "be requested (or added) from there."]
            buttons.append(make_button("Pick from the server's games", self._picker("owned"), emoji="🎮",
                                       style=discord.ButtonStyle.primary, disabled=not games))
            buttons.append(make_button("Type game names", self._type_owned, emoji="⌨️"))
        elif name == "installed":
            installed = [g for g in data.get("installed", []) if g in games]
            if owned:
                lines += [f"**{len(installed)}** of your {len(owned)} games are marked installed.",
                          "Mark the ones on your computer right now, so `lfg` pings and votes know what you can play."]
                buttons.append(make_button("Pick installed games", self._picker("installed"), emoji="💾",
                                           style=discord.ButtonStyle.primary))
            else:
                lines.append("Your library is empty, so there's nothing to mark installed yet. Press **Next**.")
        elif name == "favorites":
            ranks = data.get("ranks", {})
            if owned:
                lines += ["Choose your top 3. When a vote ties, the game the players rank higher wins.",
                          "-# Only your first 25 games are listed. Rank others with "
                          f"{await cog.cmd(guild, 'games rank <number> <game>')}." if len(owned) > 25 else None]
                for rank in (1, 2, 3):
                    current = next((g for g, r in ranks.items() if r == rank), None)
                    select = discord.ui.Select(placeholder=f"Your #{rank}…", options=[
                        discord.SelectOption(label=games[g]["name"][:100], value=g, default=g == current)
                        for g in owned[:25]])
                    select.callback = self._rank_callback(select, rank)
                    selects.append(select)
            else:
                lines.append("Add some games to your library first, then rank them. Press **Next**.")
        elif name == "wishlist":
            wanted = await cog.wanted_by(guild, member)
            channel_id = await cog.config.guild(guild).sale_channel()
            lines += ["Games you want but don't own yet. When one goes on sale on Steam, you'll get a ping.",
                      f"**On your wishlist ({len(wanted)}):** " + (", ".join(e["name"] for e in wanted[:20]) or "nothing yet")]
            if not channel_id:
                lines.append("-# Sale alerts aren't turned on in this server yet, but your wishlist is saved.")
            buttons.append(make_button("Add games you want", self._type_wanted, emoji="⭐",
                                       style=discord.ButtonStyle.primary))
        if state.get("note"):
            lines += ["", state["note"]]
        last = step == len(PROFILE_STEPS) - 1
        nav = [make_button("Back", lambda i: self.move(i, step - 1), disabled=step == 0),
               make_button("Finish" if last else "Next", lambda i: self.move(i, step + 1),
                           style=discord.ButtonStyle.primary),
               make_button("Stop", self._stop)]
        self.add_item(ui.card(
            ui.truncate("\n".join(l for l in lines if l is not None), 3500), selects or None, buttons or None,
            ui.SEPARATOR, nav,
            title=f"🎮 Profile setup · {step + 1} of {len(PROFILE_STEPS)}: {PROFILE_TITLES[name]}",
            footer=f"Every step is optional · Only {member.display_name} can use this"))

    async def _summary(self, games: dict, data: dict, owned: List[str]) -> discord.ui.Container:
        guild, member = self.state["guild"], self.state["member"]
        _, tz_name, _ = await self.cog.timezone_for(member)
        ranks = sorted(((r, g) for g, r in data.get("ranks", {}).items() if g in games and r <= 3))
        installed = [g for g in data.get("installed", []) if g in games]
        wanted = await self.cog.wanted_by(guild, member)
        cmd = self.cog.cmd
        lines = [f"🕘 **Timezone:** {tz_name}",
                 f"🎮 **Library:** {len(owned)} games, {len(installed)} installed",
                 "🏅 **Favorites:** " + (", ".join(f"#{r} {games[g]['name']}" for r, g in ranks) or "none"),
                 f"⭐ **Wishlist:** {len(wanted)} games"]
        footer = (f"Change things any time with {await cmd(guild, 'games own')}, {await cmd(guild, 'games install')}, "
                  f"{await cmd(guild, 'games rank')} or {await cmd(guild, 'games want')}, or run "
                  f"{await cmd(guild, 'games newprofile')} again.")
        return ui.card("\n".join(lines), title="✅ Your profile is set up", color=ui.SUCCESS, footer=footer)

    # ---------- step actions ----------

    async def _stop(self, interaction: discord.Interaction):
        self.stop()
        await interaction.response.edit_message(
            view=final_card("Everything you saved is kept.", title="🎮 Profile setup stopped", color=ui.MUTED),
            allowed_mentions=NO_PING)

    async def _set_timezone(self, interaction: discord.Interaction, zone: str):
        await self.cog.config.user(self.state["member"]).timezone.set(zone)
        await self.move(interaction, self.state["step"] + 1, f"✅ Timezone set to **{zone}**.")

    async def _other_timezone(self, interaction: discord.Interaction):
        async def submit(modal_interaction: discord.Interaction, text: str):
            zone = find_timezone(text)
            if zone is None:
                return await self.move(modal_interaction, self.state["step"],
                                       f"❓ I don't know the timezone **{text}**. Try `America/Chicago`, `Chicago` or "
                                       "`CST`.")
            await self._set_timezone(modal_interaction, zone)

        await interaction.response.send_modal(TextModal("Your timezone", "Timezone",
                                                        "America/Chicago, Chicago, CST…", submit, paragraph=False))

    def _picker(self, kind: str):
        async def open_picker(interaction: discord.Interaction):
            state, cog = self.state, self.cog
            guild, member = state["guild"], state["member"]
            games = await cog.config.guild(guild).games()
            data = (await cog.config.guild(guild).users()).get(str(member.id), {})
            if kind == "owned":
                choices, selected = list(games.values()), set(data.get("owned", [])) | set(data.get("installed", []))
                actions = ("own", "unown")
                title, hint = "🎮 Your library", "Tick every game you own."
            else:
                owned = set(data.get("owned", [])) | set(data.get("installed", []))
                choices, selected = [games[g] for g in owned if g in games], set(data.get("installed", []))
                actions = ("install", "uninstall")
                title, hint = "🎮 Your installed games", "Tick the games you have installed right now."

            async def on_save(save_interaction: discord.Interaction, before: Set[str], after: Set[str]):
                async with cog.config.guild(guild).users() as users:
                    entry = user_entry(users, member.id)
                    for gid in after - before:
                        apply_change(entry, gid, actions[0])
                    for gid in before - after:
                        apply_change(entry, gid, actions[1])
                changes = f"+{len(after - before)} / −{len(before - after)}"
                await self.move(save_interaction, state["step"] + 1, f"✅ Saved ({changes}).")

            async def on_cancel(cancel_interaction: discord.Interaction):
                await self.move(cancel_interaction, state["step"])

            self.stop()
            picker = GamePickerView(member, choices, selected & {g["id"] for g in choices}, title, hint, on_save,
                                    on_cancel)
            picker.message = self.message
            await interaction.response.edit_message(view=picker, allowed_mentions=NO_PING)

        return open_picker

    async def _type_owned(self, interaction: discord.Interaction):
        async def submit(modal_interaction: discord.Interaction, text: str):
            await modal_interaction.response.defer()
            note = await self.cog.add_typed_games(modal_interaction, self.state["member"], text,
                                                  ephemeral=self.state["ephemeral"])
            await self.move(modal_interaction, self.state["step"], note)

        await interaction.response.send_modal(TextModal("Games you own", "Game names (one per line or commas)",
                                                        "Deadlock\nHelldivers 2\nRocket League", submit))

    def _rank_callback(self, select: discord.ui.Select, rank: int):
        async def callback(interaction: discord.Interaction):
            gid = select.values[0]
            guild, member = self.state["guild"], self.state["member"]
            async with self.cog.config.guild(guild).users() as users:
                ranks = user_entry(users, member.id)["ranks"]
                for other in [g for g, r in ranks.items() if r == rank]:
                    ranks.pop(other)
                ranks[gid] = rank
            name = (await self.cog.config.guild(guild).games()).get(gid, {}).get("name", "that game")
            await self.move(interaction, self.state["step"], ui.line(ui.DONE, f"**{name}** is your #{rank}."))
        return callback

    async def _type_wanted(self, interaction: discord.Interaction):
        async def submit(modal_interaction: discord.Interaction, text: str):
            await modal_interaction.response.defer()
            note = await self.cog.want_typed_games(self.state["guild"], self.state["member"], text)
            await self.move(modal_interaction, self.state["step"], note)

        await interaction.response.send_modal(TextModal("Games you want", "Game names (one per line or commas)",
                                                        "Elden Ring\nBaldur's Gate 3", submit))


# ==========================================
#                  THE COG
# ==========================================

class GameManager(commands.Cog):
    """
    Track the games your server owns, find something everyone can play, and vote on it.

    Mark games with `[p]games own` and `[p]games install` (with no names, they open a picker).
    Start a session with `[p]games session`, optionally with a time such as
    `[p]games session friday 9pm Raid night`, and press **Start vote** once everyone has joined.
    """

    slash = app_commands.Group(name="games", description="Your game library, play sessions, and votes",
                               guild_only=True)

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8675309420, force_registration=True)
        self.config.register_guild(
            games={},
            users={},
            game_requests={},
            play_sessions={},
            votes={},
            install_requests={},
            admin_role=None,
            member_add=False,   # members may add new games to the library without a request
            timezone=None,      # default timezone for session times
            recurring={},       # weekly schedules that post sessions ahead of time
            events=True,        # also list scheduled sessions in the server's Discord events
            event_channel=None, # voice channel for those events (else they're "external" events)
            wishlist={},        # Steam app ID -> {appid, name, users, price, alerted}
            sale_channel=None,  # where wishlist sale alerts go (None = off)
            free_games=False,   # also announce free Epic Games Store games in the sale channel
            free_games_posted=[],
        )
        self.config.register_user(timezone=None)
        self.vote_tasks: Dict[str, asyncio.Task] = {}
        self._lfg_last: Dict[Tuple[int, int], float] = {}
        self._resume_task: Optional[asyncio.Task] = None

    async def cog_load(self):
        self.bot.add_dynamic_items(SessionButton, VoteButton, RequestButton, InstallButton)
        self._resume_task = asyncio.create_task(self._resume_votes())
        self.session_loop.start()
        self.sale_loop.start()

    async def cog_unload(self):
        self.bot.remove_dynamic_items(SessionButton, VoteButton, RequestButton, InstallButton)
        self.session_loop.cancel()
        self.sale_loop.cancel()
        if self._resume_task is not None:
            self._resume_task.cancel()
        for task in self.vote_tasks.values():
            task.cancel()

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        await self.config.user_from_id(user_id).clear()
        for guild_id in await self.config.all_guilds():
            async with self.config.guild_from_id(guild_id).users() as users:
                users.pop(str(user_id), None)
            async with self.config.guild_from_id(guild_id).wishlist() as wishlist:
                for entry in wishlist.values():
                    if str(user_id) in entry["users"]:
                        entry["users"].remove(str(user_id))

    # ==========================================
    #            PERMISSIONS & REPLIES
    # ==========================================

    async def is_game_admin(self, member: discord.Member) -> bool:
        if await self.bot.is_owner(member) or member.guild_permissions.administrator:
            return True
        if await self.bot.is_admin(member):
            return True
        role_id = await self.config.guild(member.guild).admin_role()
        return bool(role_id) and any(role.id == role_id for role in member.roles)

    async def guide_member_roles(self, member: discord.Member) -> List[str]:
        """Extra roles the Claude cog's bot guide should know about (it can't see this cog's admin role)."""
        return ["game admin"] if await self.is_game_admin(member) else []

    # ==========================================
    #        LOOKUPS FOR THE CLAUDE BOT GUIDE
    # ==========================================

    def guide_tools(self) -> List[dict]:
        return GUIDE_TOOLS

    async def guide_call_tool(self, name: str, args: dict, asker: discord.Member) -> str:
        """Answer one of GUIDE_TOOLS as plain text. Read-only."""
        if name == "games_library":
            return await self._lookup_library(asker, str(args.get("member") or "me"))
        if name == "games_game":
            return await self._lookup_game(asker.guild, str(args.get("game") or ""))
        if name == "games_activity":
            return await self._lookup_activity(asker.guild)
        return f"Unknown lookup: {name}"

    def _display(self, guild: discord.Guild, user_id) -> str:
        member = guild.get_member(int(user_id))
        return member.display_name if member else f"a former member ({user_id})"

    async def _lookup_library(self, asker: discord.Member, who_text: str) -> str:
        guild = asker.guild
        if who_text.strip().lower() in ("", "me", "myself", "i", "self", asker.display_name.lower()):
            member = asker
        else:
            member, candidates = self.find_member(guild, who_text)
            if member is None:
                close = ", ".join(m.display_name for m in candidates)
                return f"No member matches \"{who_text}\"." + (f" Close matches: {close}." if close else "")
        games = await self.config.guild(guild).games()
        data = (await self.config.guild(guild).users()).get(str(member.id), {})
        installed = [g for g in data.get("installed", []) if g in games]
        owned_only = [g for g in data.get("owned", []) if g in games and g not in installed]
        ranks = data.get("ranks", {})
        if not installed and not owned_only:
            return f"{member.display_name} has no games in their library."

        def listing(ids):
            ids = sorted(ids, key=lambda g: (ranks.get(g) is None, ranks.get(g) or 0, games[g]["name"].lower()))
            names = [games[g]["name"] + (f" (rank {ranks[g]})" if ranks.get(g) else "") for g in ids[:150]]
            return ", ".join(names) + (f", and {len(ids) - 150} more" if len(ids) > 150 else "") or "none"

        wanted = ", ".join(e["name"] for e in await self.wanted_by(guild, member)) or "nothing"
        return (f"{member.display_name}'s library: {len(installed) + len(owned_only)} games, {len(installed)} installed.\n"
                f"Installed: {listing(installed)}\nOwned but not installed: {listing(owned_only)}\n"
                f"Wishlist (wants, doesn't own): {wanted}")

    async def _lookup_game(self, guild: discord.Guild, name: str) -> str:
        games = await self.config.guild(guild).games()
        game, candidates = resolve_game(games, name)
        if game is None:
            requests = await self.config.guild(guild).game_requests()
            pending = next((r for r in requests.values() if normalize(r["name"]) == normalize(name)), None)
            if pending:
                return (f"\"{pending['name']}\" isn't in the server library yet. "
                        f"{self._display(guild, pending['requested_by'])} requested it; it's waiting for a game admin.")
            close = ", ".join(g["name"] for g in candidates)
            return f"No game called \"{name}\" in the server library." + (f" Close matches: {close}." if close else "")
        users = await self.config.guild(guild).users()
        installed, owned_only = [], []
        for uid, data in users.items():
            if guild.get_member(int(uid)) is None:
                continue
            if game["id"] in data.get("installed", []):
                installed.append(self._display(guild, uid))
            elif game["id"] in data.get("owned", []):
                owned_only.append(self._display(guild, uid))
        return (f"{game['name']} is in the server library.\n"
                f"Installed by {len(installed)}: {', '.join(sorted(installed, key=str.lower)) or 'nobody'}\n"
                f"Owned but not installed by {len(owned_only)}: {', '.join(sorted(owned_only, key=str.lower)) or 'nobody'}")

    async def _lookup_activity(self, guild: discord.Guild) -> str:
        sessions = await self.config.guild(guild).play_sessions()
        votes = await self.config.guild(guild).votes()
        if not sessions and not votes:
            return "No active game sessions or votes."
        lines = []
        for s in sorted(sessions.values(), key=lambda s: s.get("starts_at") or s["created_at"]):
            starts = parse_iso(s.get("starts_at"))
            when = f"starts {stamp(starts)} (write it exactly like that; Discord shows it in each reader's timezone)" \
                if starts else "started on creation"
            players = ", ".join(self._display(guild, u) for u in s["participants"])
            extra = " A vote is running." if s.get("vote_id") in votes else ""
            extra += f" Vote winner: {s['winner']}." if s.get("winner") else ""
            lines.append(f"Session \"{s['title']}\" (ID {s['id']}), host {self._display(guild, s['host_id'])}, {when}. "
                         f"Players ({len(s['participants'])}): {players}.{extra}")
        for v in votes.values():
            names = v.get("names") or {}
            tally = ", ".join(f"{names.get(g, g)}: {v['tallies'].get(g, 0)}" for g in v.get("games", []))
            waiting = [self._display(guild, u) for u in v["allowed_voters"] if u not in v["user_votes"]]
            ends = parse_iso(v.get("ends_at"))
            lines.append(f"Vote for \"{v.get('title', 'a session')}\" (ID {v['id']})"
                         + (f", ends {stamp(ends, 'R')}" if ends else "") + f". Tally: {tally or 'no options'}. "
                         f"Still to vote: {', '.join(waiting) or 'nobody'}.")
        return "\n".join(lines)

    async def can_add_games(self, member: discord.Member) -> bool:
        return await self.config.guild(member.guild).member_add() or await self.is_game_admin(member)

    async def can_manage(self, member: discord.Member, owner_id: Optional[str]) -> bool:
        return str(member.id) == owner_id or await self.is_game_admin(member)

    async def prefix(self, guild: Optional[discord.Guild]) -> str:
        """This server's real text prefix (not a bot mention), for hints."""
        for prefix in await self.bot.get_valid_prefixes(guild):
            if not prefix.startswith("<@"):
                return prefix
        return "!"

    async def cmd(self, guild: Optional[discord.Guild], command: str) -> str:
        """A command formatted with this server's prefix, for hints: `!games own`."""
        return f"`{await self.prefix(guild)}{command}`"

    async def reply(self, target: Target, *, ephemeral: bool = False, **kwargs) -> Optional[discord.Message]:
        """Answer a command or an interaction the same way (ping-free unless `allowed_mentions` says otherwise)."""
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        kwargs.setdefault("allowed_mentions", NO_PING)
        if isinstance(target, discord.Interaction):
            if target.response.is_done():
                return await target.followup.send(ephemeral=ephemeral, wait=True, **kwargs)
            await target.response.send_message(ephemeral=ephemeral, **kwargs)
            return await target.original_response()
        return await target.send(**kwargs)

    async def send_card(self, target, view: discord.ui.LayoutView, *, ephemeral: bool = False,
                        allowed_mentions: Optional[discord.AllowedMentions] = None) -> Optional[discord.Message]:
        """Send a card to a command, an interaction or a channel. Ping-free unless `allowed_mentions` says who."""
        return await ui.send_card(target, view, ephemeral=ephemeral, allowed_mentions=allowed_mentions or NO_PING)

    async def send_list(self, target: Target, items: List[str], title: str, footer: Optional[str] = None,
                        ephemeral: bool = False):
        if not items:
            await self.reply(target, content=ui.line(ui.ASK, "Nothing to show."), ephemeral=ephemeral)
            return
        embeds = []
        for i in range(0, len(items), LIST_PAGE_SIZE):
            embed = discord.Embed(title=title if i == 0 else f"{title} (continued)",
                                  description="\n".join(items[i:i + LIST_PAGE_SIZE]), color=ui.BRAND)
            if i + LIST_PAGE_SIZE >= len(items):
                embed.set_footer(text=footer or f"Total: {len(items)}")
            embeds.append(embed)
        for i in range(0, len(embeds), 10):
            await self.reply(target, embeds=embeds[i:i + 10], ephemeral=ephemeral)

    async def find_game(self, target: Target, name: str, ephemeral: bool = False) -> Optional[dict]:
        """Resolve a game name, or explain to the user why it couldn't be."""
        games = await self.config.guild(who(target)[0]).games()
        game, candidates = resolve_game(games, name)
        if game is None:
            if candidates:
                text = "❓ Which one did you mean? " + ", ".join(f"**{g['name']}**" for g in candidates)
            else:
                text = f"❓ There's no game called **{name}** in the library."
            await self.reply(target, content=text, ephemeral=ephemeral)
        return game

    def find_member(self, guild: discord.Guild, name: str) -> Tuple[Optional[discord.Member], List[discord.Member]]:
        """By mention, ID, exact name or nickname, then a partial match only if it's unique."""
        m = re.fullmatch(r"<@!?(\d+)>|(\d{15,21})", name.strip())
        if m:
            member = guild.get_member(int(m.group(1) or m.group(2)))
            return member, []
        wanted = name.strip().lower()

        def names(member):
            return {n.lower() for n in (member.name, member.display_name, member.global_name) if n}

        exact = [mem for mem in guild.members if wanted in names(mem)]
        if len(exact) == 1:
            return exact[0], []
        partial = [mem for mem in guild.members if any(wanted in n for n in names(mem))]
        if len(partial) == 1 and not exact:
            return partial[0], []
        return None, (exact or partial)[:5]

    async def members_from_names(self, target: Target, member_names) -> Optional[List[discord.Member]]:
        guild = who(target)[0]
        found = []
        for name in member_names:
            member, candidates = self.find_member(guild, name)
            if member is None:
                hint = (" Did you mean " + ", ".join(m.display_name for m in candidates) + "?") if candidates else ""
                await self.reply(target, content=f"❓ Couldn't find a member called **{name}**.{hint}")
                return None
            if member not in found:
                found.append(member)
        return found

    async def channel_members_with_games(self, channel) -> List[discord.Member]:
        users = await self.config.guild(channel.guild).users()
        members = []
        for member in channel.guild.members:
            if member.bot or not channel.permissions_for(member).read_messages:
                continue
            data = users.get(str(member.id), {})
            if data.get("owned") or data.get("installed"):
                members.append(member)
        return members

    async def timezone_for(self, member: discord.Member) -> Tuple[tzinfo, str, bool]:
        """(timezone, its name, whether the member set it themselves)."""
        name = await self.config.user(member).timezone()
        personal = bool(name)
        name = name or await self.config.guild(member.guild).timezone() or "UTC"
        return load_zone(name), name, personal

    async def _edit_message(self, guild: discord.Guild, channel_id, message_id, **kwargs):
        if not channel_id or not message_id:
            return
        channel = guild.get_channel_or_thread(channel_id)
        if channel is None:
            return
        try:
            await channel.get_partial_message(message_id).edit(**kwargs)
        except discord.HTTPException as e:
            log.debug("Couldn't edit message %s: %s", message_id, e)

    async def _edit_record(self, guild: discord.Guild, record: dict, card: Callable[[], discord.ui.LayoutView],
                           **old_style):
        """
        Edit the message of a session, vote or request. Records posted as cards (`"card": True`) get the new card;
        older ones were posted as embeds and can't become cards, so they're edited the old way (`old_style`).
        """
        kwargs = {"view": card(), "allowed_mentions": NO_PING} if record.get("card") else old_style
        await self._edit_message(guild, record.get("channel_id"), record.get("message_id"), **kwargs)

    @staticmethod
    async def _drop_buttons(message: Optional[discord.Message]):
        """Take the buttons off an old embed message whose session, vote or request is gone. Cards are left alone:
        whatever ended them already redrew them without buttons (and a card can't be emptied)."""
        if message is None or ui.is_card(message):
            return
        try:
            await message.edit(view=None)
        except discord.HTTPException:
            pass

    # ==========================================
    #                 LIBRARY
    # ==========================================

    async def change_library_text(self, guild: discord.Guild, member: discord.Member, names: List[str],
                                  action: str) -> Tuple[str, List[str]]:
        """
        Own/unown/install/uninstall games by name. Returns (status lines, names not in the library at all).
        The lines are a plain message (✅ ⚠️ ❓ ❌), not an embed.
        """
        text, unknown, _ = await self._change_library(guild, member, names, action)
        return text, unknown

    async def change_library(self, guild: discord.Guild, member: discord.Member, names: List[str],
                             action: str) -> Tuple[discord.Embed, List[str]]:
        """The same as change_library_text, as an embed: kept for other cogs (SpeakUp's Steam card buttons)."""
        text, unknown, changed = await self._change_library(guild, member, names, action)
        return discord.Embed(description=text, color=LIBRARY_ACTIONS[action][2] if changed else ui.MUTED), unknown

    async def _change_library(self, guild: discord.Guild, member: discord.Member, names: List[str],
                              action: str) -> Tuple[str, List[str], bool]:
        games = await self.config.guild(guild).games()
        changed, unchanged, unsure, unknown = [], [], [], []
        async with self.config.guild(guild).users() as users:
            data = user_entry(users, member.id)
            for name in names:
                game, candidates = resolve_game(games, name)
                if game is None:
                    if candidates:
                        unsure.append(describe_unresolved(name, candidates))
                    else:
                        unknown.append(name)
                    continue
                if apply_change(data, game["id"], action):
                    changed.append(game["name"])
                elif game["name"] not in unchanged:
                    unchanged.append(game["name"])

        changed_label, unchanged_label, _ = LIBRARY_ACTIONS[action]
        lines = []
        if changed:
            lines.append(f"✅ **{changed_label}:** " + ", ".join(changed))
        if unchanged:
            lines.append(f"⚠️ **{unchanged_label}:** " + ", ".join(unchanged))
        if unsure:
            lines.append("❓ **Which one?** " + "; ".join(unsure) + ". Try again with the full name.")
        if unknown:
            lines.append(NOT_IN_LIBRARY + ", ".join(unknown))
        if changed and action == "install":
            lines.append("-# Installed games also count as owned.")
        return "\n".join(lines) or NOTHING_TO_CHANGE, unknown, bool(changed)

    async def library_command(self, target: Target, text: Optional[str], action: str, ephemeral: bool = False):
        guild, member, _ = who(target)
        if not text or not text.strip():
            kind = "installed" if action in ("install", "uninstall") else "owned"
            return await self.open_picker(target, kind, ephemeral)
        names = parse_game_names(text)
        if not names:
            return await self.reply(target, content=ui.line(ui.ASK, "Name at least one game."), ephemeral=ephemeral)
        result, unknown = await self.change_library_text(guild, member, names, action)
        if unknown and action in ("own", "install"):
            # The result plus a button to add (or request) the missing games: a small menu, so it's a card.
            view = UnknownGamesView(self, member.id, unknown, action, await self.can_add_games(member),
                                    ui.truncate(result, 3500))
            view.message = await self.send_card(target, view, ephemeral=ephemeral)
            return
        await self.reply(target, content=ui.truncate(result, 1900), ephemeral=ephemeral)

    async def open_picker(self, target: Target, kind: str, ephemeral: bool = False):
        guild, member, _ = who(target)
        games = await self.config.guild(guild).games()
        if not games:
            return await self.reply(target, content=f"⚠️ No games have been added yet. Request one with "
                                                    f"{await self.cmd(guild, 'games request <game>')}.",
                                    ephemeral=ephemeral)
        data = (await self.config.guild(guild).users()).get(str(member.id), {})
        if kind == "owned":
            selected = set(data.get("owned", [])) & set(games)
            title = "🎮 Your library"
            hint = "Tick every game you own. Unticking one removes it from your library."
            add_action, remove_action = "own", "unown"
        else:
            selected = set(data.get("installed", [])) & set(games)
            title = "🎮 Your installed games"
            hint = "Tick every game you have installed right now. Ticking a game also adds it to your library."
            add_action, remove_action = "install", "uninstall"

        async def on_save(interaction: discord.Interaction, before: Set[str], after: Set[str]):
            added, removed = after - before, before - after
            async with self.config.guild(guild).users() as users:
                entry = user_entry(users, member.id)
                for gid in added:
                    apply_change(entry, gid, add_action)
                for gid in removed:
                    apply_change(entry, gid, remove_action)

            def listing(ids):
                text = ", ".join(sorted((games[g]["name"] for g in ids if g in games), key=str.lower))
                return text if len(text) <= 900 else text[:900] + "…"

            lines = []
            if added:
                lines.append(f"✅ **{LIBRARY_ACTIONS[add_action][0]} ({len(added)}):** {listing(added)}")
            if removed:
                lines.append(f"➖ **{LIBRARY_ACTIONS[remove_action][0]} ({len(removed)}):** {listing(removed)}")
            card = (final_card("\n".join(lines), title=f"{title}: saved", color=ui.SUCCESS) if lines
                    else final_card("Nothing was changed.", title=title, color=ui.MUTED))
            await interaction.response.edit_message(view=card, allowed_mentions=NO_PING)

        view = GamePickerView(member, list(games.values()), selected, title, hint, on_save)
        view.message = await self.send_card(target, view, ephemeral=ephemeral)

    async def add_games(self, guild: discord.Guild, member: discord.Member, names: List[str],
                        appids: Optional[Dict[str, int]] = None) -> Tuple[List[str], List[str]]:
        """Add games to the server library (with Steam app IDs when known). Returns (added, already there)."""
        appids = appids or {}
        added, existing = [], []
        async with self.config.guild(guild).games() as games:
            known = {normalize(g["name"]): g["name"] for g in games.values()}
            for name in names:
                name = clean_title(name)
                key = normalize(name)
                if not key:
                    continue
                if key in known:
                    existing.append(known[key])
                    continue
                gid = generate_id()
                while gid in games:
                    gid = generate_id()
                games[gid] = {"id": gid, "name": name, "description": "", "added_by": str(member.id),
                              "added_at": utcnow().isoformat(), "steam_appid": appids.get(name)}
                known[key] = name
                added.append(name)
        return added, existing

    async def add_unknown_games(self, interaction: discord.Interaction, names: List[str], action: str, *,
                                add: bool, ephemeral: bool = False) -> Optional[str]:
        """
        The follow-up from UnknownGamesView: check the names, then add them (and apply the action) or request them.
        Returns status lines, or None if the person cancelled the name check.
        """
        guild, member, channel = who(interaction)
        checked = await self.checked_names(interaction, member, names, ephemeral=ephemeral)
        if checked is None:
            return None
        names, appids = checked
        if not add:
            return await self.request_games_text(guild, channel, member, names, action, appids=appids)
        added, _ = await self.add_games(guild, member, names, appids)
        text, _ = await self.change_library_text(guild, member, names, action)
        if added:
            text = f"✅ **Added to the server library:** {', '.join(added)}\n" + text
        return ui.truncate(text, 1900)

    # ---------- checking new game names ----------

    async def suggest_titles(self, member: discord.Member,
                             names: List[str]) -> List[Tuple[str, Optional[str], Optional[int], str]]:
        """
        For each typed name: (cleaned name, suggested title or None, Steam app ID or None, where it came from).
        Checks, in order: a close match already in the library, an exact Steam store name, and (if the Claude
        cog is loaded) an AI web search for the official title.
        """
        games = await self.config.guild(member.guild).games()
        by_key = {normalize(g["name"]): g for g in games.values()}
        finder = getattr(self.bot.get_cog("ClaudeChat"), "find_game_title", None)
        lookups_allowed = len(names) <= MAX_CHECKED_NAMES
        ai_left = MAX_AI_TITLE_LOOKUPS
        results = []
        for typed in names:
            name = clean_title(typed)
            key = normalize(name)
            match = by_key.get(key)
            if match is None and key:
                close = difflib.get_close_matches(key, list(by_key), n=1, cutoff=0.85)
                match = by_key[close[0]] if close else None
            if match is not None:
                results.append((name, match["name"], match.get("steam_appid"), "already in the library"))
                continue
            if not key or not lookups_allowed:
                results.append((name, None, None, ""))
                continue
            steam = await steam_exact_title(name)
            if steam is not None:
                results.append((name, steam[0], steam[1], "Steam"))
                continue
            found = None
            if finder is not None and ai_left > 0:
                ai_left -= 1
                try:
                    found = await finder(name, member)
                except Exception:
                    log.exception("Game title lookup failed for %r", name)
            if found:
                results.append((name, clean_title(found["title"]), found.get("steam_appid"), "web search"))
            else:
                results.append((name, None, None, ""))
        return results

    async def checked_names(self, target: Target, member: discord.Member, names: List[str],
                            ephemeral: bool = False) -> Optional[Tuple[List[str], Dict[str, int]]]:
        """
        Look up proper titles for new game names and let the person confirm any corrections.
        Returns (final names, Steam app IDs by name), or None if they cancelled or didn't answer.
        """
        channel = who(target)[2]
        async with channel.typing():
            found = await self.suggest_titles(member, names)
        suggested, typed, appids, lines = [], [], {}, []
        for name, title, appid, source in found:
            typed.append(name)
            suggested.append(title or name)
            if appid:
                appids[title or name] = appid
            # Capitalization and symbol fixes are applied silently; only real spelling changes need a yes.
            if title and normalize(title) != normalize(name):
                lines.append(f"- `{name}` → **{title}** ({source})")
        if not lines:
            return suggested, appids
        plural = len(lines) > 1
        text = (f"I checked {'those names' if plural else 'that name'}:\n" + "\n".join(lines)
                + f"\nUse {'these' if plural else 'it'} instead?")
        view = NameCheckView(member.id, plural, ui.truncate(text, 3500))
        view.message = await self.send_card(target, view, ephemeral=ephemeral)
        await view.wait()
        if view.choice == "suggested":
            return suggested, appids
        if view.choice == "typed":
            return typed, {n: a for n, a in appids.items() if n in typed}
        return None

    async def show_library(self, target: Target, member: discord.Member, ephemeral: bool = False):
        guild = who(target)[0]
        games = await self.config.guild(guild).games()
        data = (await self.config.guild(guild).users()).get(str(member.id), {})
        owned = [gid for gid in data.get("owned", []) if gid in games]
        installed = set(data.get("installed", []))
        ranks = data.get("ranks", {})
        if not owned:
            mine = member == who(target)[1]
            text = (f"⚠️ Your library is empty. Add games with {await self.cmd(guild, 'games own')}." if mine
                    else f"❓ {member.display_name}'s library is empty.")
            return await self.reply(target, content=text, ephemeral=ephemeral)
        owned.sort(key=lambda gid: (ranks.get(gid) is None, ranks.get(gid) or 0, games[gid]["name"].lower()))
        items = []
        for gid in owned:
            name = games[gid]["name"] + (f" {INSTALLED}" if gid in installed else "")
            items.append(f"{ranks[gid]}. {name}" if ranks.get(gid) else f"- {name}")
        count = len([g for g in owned if g in installed])
        await self.send_list(target, items, f"{member.display_name}'s library",
                             f"{len(owned)} owned · {count} installed · {INSTALLED} = installed", ephemeral)

    async def set_rank(self, target: Target, rank: int, name: str, ephemeral: bool = False):
        guild, member, _ = who(target)
        if rank < 0:
            return await self.reply(target, ephemeral=ephemeral, content=ui.line(
                ui.ASK, "Use 1 for your favorite, 2 for the next, and so on (0 clears it)."))
        game = await self.find_game(target, name, ephemeral)
        if game is None:
            return
        async with self.config.guild(guild).users() as users:
            data = user_entry(users, member.id)
            newly_owned = apply_change(data, game["id"], "own")
            if rank == 0:
                data["ranks"].pop(game["id"], None)
            else:
                data["ranks"][game["id"]] = rank
        text = (f"✅ Cleared your rank for **{game['name']}**." if rank == 0
                else f"✅ **{game['name']}** is now your #{rank}.")
        if newly_owned:
            text += " (Also added it to your library.)"
        await self.reply(target, content=text, ephemeral=ephemeral)

    async def who_has(self, target: Target, name: str, installed_only: bool):
        guild = who(target)[0]
        game = await self.find_game(target, name)
        if game is None:
            return
        users = await self.config.guild(guild).users()
        rows = []
        for uid, data in users.items():
            has_installed = game["id"] in data.get("installed", [])
            if not has_installed and (installed_only or game["id"] not in data.get("owned", [])):
                continue
            member = guild.get_member(int(uid))
            if member is not None:
                mark = f" {INSTALLED}" if has_installed and not installed_only else ""
                rows.append((member.display_name.lower(), f"- {member.display_name}{mark}"))
        if not rows:
            verb = "has it installed" if installed_only else "owns it"
            return await self.reply(target, content=f"❓ Nobody {verb} yet: **{game['name']}**.")
        rows.sort()
        if installed_only:
            await self.send_list(target, [r[1] for r in rows], f"Installed {game['name']}",
                                 ui.plural(len(rows), "player"))
        else:
            await self.send_list(target, [r[1] for r in rows], f"Own {game['name']}",
                                 f"{ui.plural(len(rows), 'owner')} · {INSTALLED} = installed")

    async def shared_games(self, target: Target, members: List[discord.Member], installed: bool):
        guild, author, channel = who(target)
        if not members:
            members = await self.channel_members_with_games(channel)
        if len(members) < 2:
            return await self.reply(target, content="❓ I need at least 2 people with games in their library. Name "
                                                    "them, e.g. " + await self.cmd(guild, "games shared Alex Sam") + ".")
        if len(members) > 25:
            return await self.reply(target, content="❌ That's too many people at once. Name up to 25.")
        games = await self.config.guild(guild).games()
        users = await self.config.guild(guild).users()
        field = "installed" if installed else "owned"
        common = None
        for member in members:
            data = users.get(str(member.id), {})
            have = set(data.get("installed", [])) if installed else set(data.get("owned", [])) | set(data.get("installed", []))
            common = have if common is None else common & have
        common = [games[g] for g in (common or set()) if g in games]
        names = ", ".join(m.display_name for m in members)
        if not common:
            return await self.reply(target, content=f"❓ No game is {field} by all of: {names}.")
        mine = set(users.get(str(author.id), {}).get("installed", []))
        common.sort(key=lambda g: g["name"].lower())
        items = [f"- {g['name']}" + (f" {INSTALLED}" if g["id"] in mine and not installed else "") for g in common]
        title = "Installed by everyone" if installed else "Owned by everyone"
        footer = f"{names}" + ("" if installed else f" · {INSTALLED} = you have it installed")
        await self.send_list(target, items, title, footer[:2000])

    async def top_games(self, target: Target, installed_only: bool, shared_only: bool):
        guild, author, channel = who(target)
        members = await self.channel_members_with_games(channel)
        if not members:
            return await self.reply(target, content="❓ Nobody who can see this channel has games in their library yet.")
        games = await self.config.guild(guild).games()
        users = await self.config.guild(guild).users()
        member_ids = [str(m.id) for m in members]
        mine = set(users.get(str(author.id), {}).get("installed", []))
        rows = []
        for gid, game in games.items():
            owners = [m for m in member_ids
                      if gid in users.get(m, {}).get("owned", []) or gid in users.get(m, {}).get("installed", [])]
            if not owners:
                continue
            installers = [m for m in owners if gid in users.get(m, {}).get("installed", [])]
            if shared_only and len(owners) < len(member_ids):
                continue
            if installed_only and len(installers) < len(owners):
                continue
            rows.append((-rank_score(users, member_ids, gid), -len(owners), game["name"].lower(),
                         game["name"], len(owners), len(installers), gid in mine))
        if not rows:
            return await self.reply(target, content="❓ No games match those filters.")
        rows.sort()
        items = [f"**{i}.** {name}{f' {INSTALLED}' if is_mine else ''} (owned by {owners}/{len(member_ids)}, "
                 f"installed by {inst})" for i, (_, _, _, name, owners, inst, is_mine) in enumerate(rows, 1)]
        title = "Top games" + (" (installed by all owners)" if installed_only else "") + (" (owned by everyone)" if shared_only else "")
        await self.send_list(target, items, title,
                             f"Ranked by the rankings of {ui.plural(len(members), 'player')} · "
                             f"{INSTALLED} = you have it installed")

    async def lfg(self, target: Target, name: str):
        guild, member, _ = who(target)
        key = (guild.id, member.id)
        wait = LFG_COOLDOWN_SECONDS - (time.monotonic() - self._lfg_last.get(key, -LFG_COOLDOWN_SECONDS))
        if wait > 0:
            return await self.reply(target, content=f"⏳ You can ping for players again in {int(wait // 60) + 1} min.",
                                    ephemeral=True)
        game = await self.find_game(target, name, ephemeral=True)
        if game is None:
            return
        users = await self.config.guild(guild).users()
        ready, owners_only = [], []
        for uid, data in users.items():
            if uid == str(member.id):
                continue
            other = guild.get_member(int(uid))
            if other is None or other.bot:
                continue
            if game["id"] in data.get("installed", []):
                ready.append(other)
            elif game["id"] in data.get("owned", []):
                owners_only.append(other)
        if not ready:
            text = f"❓ Nobody else has **{game['name']}** installed."
            if owners_only:
                text += f" These people own it: {', '.join(m.display_name for m in owners_only)}."
            return await self.reply(target, content=text, ephemeral=True)
        self._lfg_last[key] = time.monotonic()
        content = f"🎮 {member.mention} wants to play **{game['name']}**! " + " ".join(m.mention for m in ready)
        if owners_only:
            content += f"\n-# Also own it but haven't installed it: {', '.join(m.display_name for m in owners_only)}"
        content += f"\n-# Start a session with {await self.cmd(guild, 'games session ' + game['name'])}"
        await self.reply(target, content=content, allowed_mentions=PING)

    # ==========================================
    #            REQUESTS & INSTALLS
    # ==========================================

    async def request_games_text(self, guild, channel, member, names: List[str], action: Optional[str] = None,
                                 appids: Optional[Dict[str, int]] = None) -> str:
        """File requests for new games (each gets an approval card with Approve/Deny). Returns status lines."""
        text, _ = await self._request_games(guild, channel, member, names, action, appids)
        return text

    async def request_games(self, guild, channel, member, names: List[str], action: Optional[str] = None,
                            appids: Optional[Dict[str, int]] = None) -> discord.Embed:
        """The same as request_games_text, as an embed: kept for other cogs (SpeakUp's Steam card buttons)."""
        text, created = await self._request_games(guild, channel, member, names, action, appids)
        return discord.Embed(description=text, color=ui.SUCCESS if created else ui.MUTED)

    def request_card(self, request: dict, approver: Optional[discord.abc.User] = None,
                     approved: Optional[bool] = None) -> ui.CardView:
        """A game request: ATTENTION with Approve/Deny while pending, then SUCCESS (approved) or DANGER (denied)."""
        name, requester = request["name"], request["requested_by"]
        link = ([store_button(STEAM_APP_URL.format(request["steam_appid"]), "View on Steam")]
                if request.get("steam_appid") else [])
        if approved is None:
            then = {"own": " and add it to their library",
                    "install": " and mark it installed for them"}.get(request.get("for_action"), "")
            return ui.CardView(ui.card(
                f"<@{requester}> asked to add **{name}** to the server library. Approving will add it{then}.",
                [RequestButton("approve", request["id"]), RequestButton("deny", request["id"])] + link,
                title=f"🎮 Game request: {name}", color=ui.ATTENTION, footer="Game admins can approve or deny"))
        verb = "approved" if approved else "denied"
        by = f", {verb} by {approver.mention}" if approver is not None else ""
        return ui.CardView(ui.card(
            f"Requested by <@{requester}>{by}.", link or None,
            title=f"✅ Approved: {name}" if approved else f"❌ Denied: {name}",
            color=ui.SUCCESS if approved else ui.DANGER))

    async def _request_games(self, guild, channel, member, names: List[str], action: Optional[str],
                             appids: Optional[Dict[str, int]]) -> Tuple[str, bool]:
        appids = appids or {}
        games = await self.config.guild(guild).games()
        known = {normalize(g["name"]): g["name"] for g in games.values()}
        created, exists, pending = [], [], []
        async with self.config.guild(guild).game_requests() as requests:
            requested = {normalize(r["name"]): r for r in requests.values()}
            for name in names:
                name = clean_title(name)
                key = normalize(name)
                if not key:
                    continue
                if key in known:
                    exists.append(known[key])
                elif key in requested:
                    pending.append(requested[key]["name"])
                else:
                    rid = generate_id()
                    requests[rid] = {"id": rid, "name": name, "description": "", "requested_by": str(member.id),
                                     "requested_at": utcnow().isoformat(), "for_action": action,
                                     "channel_id": channel.id, "message_id": None, "steam_appid": appids.get(name),
                                     "card": True}
                    requested[key] = dict(requests[rid])
                    created.append((rid, name))

        for rid, name in created:
            try:
                message = await self.send_card(channel, self.request_card(requested[normalize(name)]))
            except discord.HTTPException:
                continue
            async with self.config.guild(guild).game_requests() as requests:
                if rid in requests:
                    requests[rid]["message_id"] = message.id

        lines = []
        if created:
            lines.append("✅ **Requested:** " + ", ".join(n for _, n in created) + ". A game admin needs to approve.")
        if pending:
            lines.append("⏳ **Already requested:** " + ", ".join(pending))
        if exists:
            lines.append("⚠️ **Already in the library:** " + ", ".join(exists))
        return ui.truncate("\n".join(lines) or "⚠️ Nothing to request.", 1900), bool(created)

    async def resolve_request(self, guild: discord.Guild, rid: str, approver: discord.Member, approve: bool) -> Optional[str]:
        """Approve or deny a request. Returns the game name, or None if the request is gone."""
        async with self.config.guild(guild).game_requests() as requests:
            request = requests.pop(rid, None)
        if request is None:
            return None
        name, requester, action = request["name"], request["requested_by"], request.get("for_action")
        if approve:
            appid = request.get("steam_appid")
            await self.add_games(guild, approver, [name], {name: appid} if appid else None)
            games = await self.config.guild(guild).games()
            game, _ = resolve_game(games, name)
            if game is not None and action in ("own", "install"):
                async with self.config.guild(guild).users() as users:
                    apply_change(user_entry(users, requester), game["id"], action)
            embed = discord.Embed(title=f"✅ Approved: {name}", color=ui.SUCCESS,
                                  description=f"Requested by <@{requester}>, approved by {approver.mention}.")
        else:
            embed = discord.Embed(title=f"❌ Denied: {name}", color=ui.DANGER,
                                  description=f"Requested by <@{requester}>, denied by {approver.mention}.")
        await self._edit_record(guild, request, lambda: self.request_card(request, approver, approve),
                                embed=embed, view=None)
        channel = guild.get_channel_or_thread(request.get("channel_id") or 0)
        if channel is not None:
            note = {
                "own": f" and it's in your library (not marked installed; if you have it installed, run "
                       f"{await self.cmd(guild, 'games install ' + name)})",
                "install": " and it's marked installed for you",
            }.get(action, "")
            text = (f"✅ <@{requester}>, **{name}** was added to the server library{note}." if approve
                    else f"❌ <@{requester}>, your request for **{name}** was denied.")
            try:
                await channel.send(text, allowed_mentions=PING)
            except discord.HTTPException:
                pass
        return name

    async def on_request_button(self, interaction: discord.Interaction, action: str, rid: str):
        if not await self.is_game_admin(interaction.user):
            return await ui.respond(interaction, "🔒 Only game admins can approve or deny requests.")
        await interaction.response.defer()
        name = await self.resolve_request(interaction.guild, rid, interaction.user, approve=action == "approve")
        if name is None:
            await self._drop_buttons(interaction.message)
            await ui.respond(interaction, "⚠️ That request was already handled.")

    async def on_install_button(self, interaction: discord.Interaction, rid: str):
        guild = interaction.guild
        request = (await self.config.guild(guild).install_requests()).get(rid)
        games = await self.config.guild(guild).games()
        if request is None or request["game_id"] not in games:
            return await ui.respond(interaction, "⚠️ This install request is closed.")
        uid = str(interaction.user.id)
        async with self.config.guild(guild).users() as users:
            apply_change(user_entry(users, uid), request["game_id"], "install")
        async with self.config.guild(guild).install_requests() as requests:
            if rid in requests and uid not in requests[rid]["installed_by"]:
                requests[rid]["installed_by"].append(uid)
        await ui.respond(interaction, f"✅ Marked **{games[request['game_id']]['name']}** installed.")

    # ==========================================
    #           WISHLIST & SALE ALERTS
    # ==========================================

    @staticmethod
    def _owned_appids(games: dict, data: dict) -> Set[int]:
        ids = set(data.get("owned", [])) | set(data.get("installed", []))
        return {int(games[g]["steam_appid"]) for g in ids if g in games and games[g].get("steam_appid")}

    async def wanted_by(self, guild: discord.Guild, member: discord.abc.User) -> List[dict]:
        wishlist = await self.config.guild(guild).wishlist()
        return sorted((e for e in wishlist.values() if str(member.id) in e["users"]), key=lambda e: e["name"].lower())

    async def steam_game_for(self, guild: discord.Guild, name: str
                             ) -> Tuple[Optional[Tuple[str, int]], List[Tuple[str, int]]]:
        """(match, candidates): a library game with a Steam ID or an exact Steam name, else Steam's top results."""
        game, _ = resolve_game(await self.config.guild(guild).games(), name)
        if game is not None and game.get("steam_appid"):
            return (game["name"], int(game["steam_appid"])), []
        results = await steam_search(clean_title(name))
        exact = next(((t, a) for t, a in results if normalize(t) == normalize(name)), None)
        return exact, [] if exact else results[:5]

    async def add_wants(self, guild: discord.Guild, member: discord.Member,
                        picks: List[Tuple[str, int]]) -> Tuple[List[str], List[str], List[str]]:
        """Add (title, Steam app ID) picks to someone's wishlist. Returns (added, already wanted, already owned)."""
        games = await self.config.guild(guild).games()
        owned = self._owned_appids(games, (await self.config.guild(guild).users()).get(str(member.id), {}))
        added, already, have, unchecked = [], [], [], []
        async with self.config.guild(guild).wishlist() as wishlist:
            for title, appid in picks:
                if appid in owned:
                    have.append(title)
                    continue
                entry = wishlist.setdefault(str(appid), {"appid": appid, "name": title, "users": [], "price": None,
                                                         "checked_at": None, "alerted": 0})
                if str(member.id) in entry["users"]:
                    already.append(entry["name"])
                    continue
                entry["users"].append(str(member.id))
                added.append(entry["name"])
                if entry["checked_at"] is None:
                    unchecked.append(appid)
        if unchecked:
            prices = await steam_prices(unchecked)
            async with self.config.guild(guild).wishlist() as wishlist:
                for appid, price in prices.items():
                    entry = wishlist.get(str(appid))
                    if entry is not None:
                        # A sale that's already on when the game is first added isn't news, so don't alert for it.
                        entry.update(price=price, checked_at=utcnow().isoformat(),
                                     alerted=(price or {}).get("discount", 0))
        return added, already, have

    async def want_games(self, target: Target, text: Optional[str], ephemeral: bool = False):
        guild, member, _ = who(target)
        names = parse_game_names(text or "")
        if not names:
            return await self.reply(target, ephemeral=ephemeral,
                                    content=f"❓ Name a game, like {await self.cmd(guild, 'games want Elden Ring')}.")
        picks, missing = [], []
        for name in names[:10]:
            match, options = await self.steam_game_for(guild, name)
            if match is None and options:
                view = SteamPickView(member.id, options, name)
                view.message = await self.send_card(target, view, ephemeral=ephemeral)
                await view.wait()
                match = view.choice
            if match is not None:
                picks.append(match)
            elif not options:
                missing.append(name)
        added, already, have = await self.add_wants(guild, member, picks)
        wishlist = await self.config.guild(guild).wishlist()
        by_name = {e["name"]: e for e in wishlist.values()}
        lines = []
        for name in added:
            entry = by_name.get(name, {})
            price = f": {price_text(entry['price'])}" if entry.get("checked_at") else ""
            lines.append(f"✅ Added **{name}** to your wishlist{price}")
        if already:
            lines.append("⚠️ Already on your wishlist: " + ", ".join(already))
        if have:
            lines.append("⚠️ You already own: " + ", ".join(have))
        if missing:
            lines.append("❓ Not found on Steam: " + ", ".join(missing) + ". Sale alerts only work for Steam games.")
        if added:
            channel_id = await self.config.guild(guild).sale_channel()
            lines.append(f"-# You'll be pinged in <#{channel_id}> when it goes on sale." if channel_id else
                         "-# Sale alerts aren't turned on in this server yet, but your wishlist is saved.")
        if lines:
            await self.reply(target, content="\n".join(lines), ephemeral=ephemeral)

    async def want_typed_games(self, guild: discord.Guild, member: discord.Member, text: str) -> str:
        """Profile setup's wishlist step: no questions asked, so a non-exact name takes Steam's top result."""
        picks, notes, missing = [], [], []
        for name in parse_game_names(text)[:10]:
            match, options = await self.steam_game_for(guild, name)
            if match is None and options:
                match = options[0]
                notes.append(f"`{name}` → **{match[0]}**")
            if match is not None:
                picks.append(match)
            else:
                missing.append(name)
        added, already, have = await self.add_wants(guild, member, picks)
        lines = [f"✅ **Added:** {', '.join(added)}" if added else None,
                 f"⚠️ Closest Steam matches: {', '.join(notes)}. Remove a wrong one with "
                 f"{await self.cmd(guild, 'games unwant <game>')}." if notes else None,
                 f"⚠️ Already on your wishlist: {', '.join(already)}" if already else None,
                 f"⚠️ You already own: {', '.join(have)}" if have else None,
                 f"❓ Not found on Steam: {', '.join(missing)}" if missing else None]
        return "\n".join(l for l in lines if l) or "⚠️ Nothing added."

    async def add_typed_games(self, interaction: discord.Interaction, member: discord.Member, text: str,
                              ephemeral: bool = False) -> str:
        """Profile setup's library step: own the named games, and add or request the ones the server lacks."""
        guild, _, channel = who(interaction)
        names = parse_game_names(text)
        if not names:
            return ui.line(ui.ASK, "Name at least one game.")
        result, unknown = await self.change_library_text(guild, member, names, "own")
        lines = [l for l in result.split("\n") if not l.startswith(NOT_IN_LIBRARY)]
        if unknown:
            checked = await self.checked_names(interaction, member, unknown, ephemeral=ephemeral)
            if checked is None:
                lines.append("⚠️ Skipped: " + ", ".join(unknown))
            elif await self.can_add_games(member):
                names, appids = checked
                added, _ = await self.add_games(guild, member, names, appids)
                more, _ = await self.change_library_text(guild, member, names, "own")
                if added:
                    lines.append(f"✅ **Added to the server library:** {', '.join(added)}")
                lines.append(more)
            else:
                names, appids = checked
                lines.append(await self.request_games_text(guild, channel, member, names, "own", appids=appids))
        return ui.truncate("\n".join(l for l in lines if l and l != NOTHING_TO_CHANGE), 1500)

    async def remove_want(self, target: Target, name: str, ephemeral: bool = False):
        guild, member, _ = who(target)
        mine = await self.wanted_by(guild, member)
        key = normalize(name)
        matches = ([e for e in mine if normalize(e["name"]) == key]
                   or [e for e in mine if key and key in normalize(e["name"])])
        if len(matches) != 1:
            text = (f"❓ Which one? " + ", ".join(f"**{e['name']}**" for e in matches) if matches
                    else f"❓ **{name}** isn't on your wishlist.")
            return await self.reply(target, content=text, ephemeral=ephemeral)
        async with self.config.guild(guild).wishlist() as wishlist:
            entry = wishlist.get(str(matches[0]["appid"]))
            if entry and str(member.id) in entry["users"]:
                entry["users"].remove(str(member.id))
                if not entry["users"]:
                    wishlist.pop(str(matches[0]["appid"]))
        await self.reply(target, content=f"✅ Removed **{matches[0]['name']}** from your wishlist.",
                         ephemeral=ephemeral)

    async def show_wishlist(self, target: Target, member: discord.Member, ephemeral: bool = False):
        guild = who(target)[0]
        wanted = await self.wanted_by(guild, member)
        if not wanted:
            mine = member == who(target)[1]
            return await self.reply(target, ephemeral=ephemeral, content=(
                f"⚠️ Your wishlist is empty. Add a game with {await self.cmd(guild, 'games want <game>')}." if mine
                else f"❓ {member.display_name}'s wishlist is empty."))
        items = [f"- [{e['name']}]({STEAM_APP_URL.format(e['appid'])})"
                 + (f": {price_text(e['price'])}" if e.get("checked_at") else "") for e in wanted]
        channel_id = await self.config.guild(guild).sale_channel()
        footer = "Sale alerts are on" if channel_id else "Sale alerts aren't turned on in this server"
        await self.send_list(target, items, f"⭐ {member.display_name}'s wishlist", footer, ephemeral)

    async def most_wanted(self, target: Target):
        guild = who(target)[0]
        wishlist = await self.config.guild(guild).wishlist()
        games = await self.config.guild(guild).games()
        users = await self.config.guild(guild).users()
        rows = []
        for entry in wishlist.values():
            fans = [u for u in entry["users"] if guild.get_member(int(u))
                    and int(entry["appid"]) not in self._owned_appids(games, users.get(u, {}))]
            if fans:
                rows.append((-len(fans), entry["name"].lower(), entry, fans))
        if not rows:
            return await self.reply(target, content=f"❓ Nobody has a wishlist yet. Add a game with "
                                                    f"{await self.cmd(guild, 'games want <game>')}.")
        items = []
        for _, _, entry, fans in sorted(rows)[:40]:
            names = ", ".join(self._display(guild, u) for u in fans[:8]) + (" …" if len(fans) > 8 else "")
            sale = f" · **{entry['price']['discount']}% off**" if (entry.get("price") or {}).get("discount") else ""
            items.append(f"**[{entry['name']}]({STEAM_APP_URL.format(entry['appid'])})**: "
                         f"{len(fans)} ({names}){sale}")
        await self.send_list(target, items, "⭐ Most-wanted games", "Number of people who want each game")

    async def check_sales(self, guild: discord.Guild) -> int:
        """Refresh wishlist prices and post one alert for games that went on sale (or got cheaper). Returns # alerted."""
        conf = self.config.guild(guild)
        wishlist = await conf.wishlist()
        if not wishlist:
            return 0
        prices = await steam_prices([int(a) for a in wishlist])
        alerts = []
        async with conf.wishlist() as wishlist:
            for appid, price in prices.items():
                entry = wishlist.get(str(appid))
                if entry is None:
                    continue
                discount = (price or {}).get("discount", 0)
                if discount > entry.get("alerted", 0):
                    alerts.append({**entry, "price": price})
                entry.update(price=price, checked_at=utcnow().isoformat(), alerted=discount)
        channel = guild.get_channel_or_thread(await conf.sale_channel() or 0)
        if not alerts or channel is None:
            return 0
        games, users = await conf.games(), await conf.users()
        lines, pinged, shown = [], [], []
        for entry in sorted(alerts, key=lambda e: -e["price"]["discount"]):
            fans = [u for u in entry["users"] if guild.get_member(int(u))
                    and int(entry["appid"]) not in self._owned_appids(games, users.get(u, {}))]
            if not fans:
                continue
            line = (f"**[{entry['name']}]({STEAM_APP_URL.format(entry['appid'])})**: {price_text(entry['price'])}"
                    f"\n-# Wanted by {', '.join(f'<@{u}>' for u in fans)}")
            if sum(len(l) + 1 for l in lines) + len(line) > 3500:
                break   # a card holds about 4,000 characters; people named in the text are the ones pinged
            lines.append(line)
            shown.append(entry)
            pinged += [u for u in fans if u not in pinged]
        if not lines:
            return 0
        prefix = await self.prefix(guild)
        link = [store_button(STEAM_APP_URL.format(shown[0]["appid"]), "View on Steam")] if len(shown) == 1 else None
        view = ui.CardView(ui.card("\n".join(lines), link, title="🎮 On sale on Steam", color=ui.HIGHLIGHT,
                                   footer=f"From your wishlists · {prefix}games want / {prefix}games unwant"))
        try:
            # The card's "Wanted by" mentions are the ping (same people as before: everyone who wants a game on sale).
            await self.send_card(channel, view, allowed_mentions=pings(pinged))
        except discord.HTTPException as e:
            log.info("Couldn't post sale alerts in %s: %s", guild, e)
            return 0
        return len(lines)

    async def check_free_games(self, guild: discord.Guild, free: List[dict]) -> int:
        conf = self.config.guild(guild)
        posted = await conf.free_games_posted()
        new = [g for g in free if g["id"] not in posted]
        channel = guild.get_channel_or_thread(await conf.sale_channel() or 0)
        if not new or channel is None:
            return 0
        lines = []
        for game in new:
            ends = parse_iso(game.get("ends"))
            lines.append(f"**[{game['title']}]({game['url']})**" + (f": free until {stamp(ends, 'f')}" if ends else ""))
        link = [store_button(new[0]["url"], "View on Epic")] if len(new) == 1 and new[0].get("url") else None
        view = ui.CardView(ui.card(ui.truncate("\n".join(lines), 3500), link,
                                   title="🎮 Free to keep on the Epic Games Store", color=ui.HIGHLIGHT))
        try:
            await self.send_card(channel, view)
        except discord.HTTPException as e:
            log.info("Couldn't post free games in %s: %s", guild, e)
            return 0
        await conf.free_games_posted.set((posted + [g["id"] for g in new])[-FREE_GAMES_KEEP:])
        return len(new)

    @tasks.loop(hours=SALE_CHECK_HOURS)
    async def sale_loop(self):
        free = None
        for guild_id, data in (await self.config.all_guilds()).items():
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            try:
                if data.get("wishlist"):
                    await self.check_sales(guild)
                if data.get("free_games") and data.get("sale_channel"):
                    free = free if free is not None else await epic_free_games()
                    await self.check_free_games(guild, free)
            except Exception:
                log.exception("Sale check failed in %s", guild)

    @sale_loop.before_loop
    async def _before_sale_loop(self):
        await self.bot.wait_until_red_ready()

    # ---------- profile setup ----------

    async def start_profile(self, target: Target, ephemeral: bool = False):
        guild, member, _ = who(target)
        state = {"cog": self, "guild": guild, "member": member, "ephemeral": ephemeral, "step": 0, "note": None}
        view = await ProfileWizard.display(state)
        state["message"] = view.message = await self.send_card(target, view, ephemeral=ephemeral)

    # ==========================================
    #                 SESSIONS
    # ==========================================

    def session_card(self, session: dict, ended: bool = False) -> ui.CardView:
        """
        A session's card: title, start time, who's playing, the buttons, and a footer with what happens next.
        SUCCESS while it's open, MUTED once it has ended (then without buttons). Player mentions in it don't ping:
        it's always sent and edited with NO_PING.
        """
        starts = parse_iso(session.get("starts_at"))
        host = session["host_id"]
        lines = []
        if starts:
            lines.append(f"{stamp(starts)} · {stamp(starts, 'R')}")
        if session.get("repeat"):
            lines.append(f"🔁 {session['repeat']}")
        players = [f"<@{uid}> (host)" if uid == host else f"<@{uid}>" for uid in session["participants"]]
        if len(players) > 40:
            players = players[:40] + [f"and {len(players) - 40} more"]
        lines.append(f"{'Played' if ended else 'Playing'}: " + (", ".join(players) or "nobody yet"))
        if session.get("winner"):
            lines.append(f"🏆 **{session['winner']}** won the vote.")
        if ended:
            lines.append("This session has ended.")
        elif session.get("vote_id"):
            lines.append("🗳️ Voting now: pick a game on the vote below.")
        notes = []
        if not ended:
            if starts and not session.get("started"):
                notes.append(f"reminder {REMINDER_MINUTES} min before" if not session.get("reminded")
                             else "starting soon")
            if session.get("event_id"):
                notes.append("on the server's events")
            if not starts and not session.get("vote_id") and not session.get("winner"):
                notes.append("when everyone's in, the host presses Start vote")
        footer = " · ".join(notes)
        footer = footer[:1].upper() + footer[1:] if footer else None
        if ended:
            return ui.CardView(ui.card("\n".join(lines), title=f"🎮 {session['title']}", color=ui.MUTED))
        return ui.CardView(ui.card("\n".join(lines), ui.SEPARATOR, session_buttons(session["id"]),
                                   title=f"🎮 {session['title']}", color=ui.SUCCESS, footer=footer))

    def session_embed(self, session: dict, ended: bool = False) -> discord.Embed:
        """The pre-card look, for session messages posted as embeds before 2026-11-05."""
        starts = parse_iso(session.get("starts_at"))
        lines = []
        if starts:
            lines.append(f"🕘 **Starts** {stamp(starts)} ({stamp(starts, 'R')})")
        if session.get("repeat"):
            lines.append(f"🔁 {session['repeat']}")
        lines.append(f"👑 **Host:** <@{session['host_id']}>")
        if session.get("event_id") and not ended:
            lines.append("📅 Also in the server's **Events**: pressing **Interested** there joins too.")
        if session.get("winner"):
            lines.append(f"🏆 **Playing:** {session['winner']}")
        if ended:
            lines.append("This session has ended.")
        elif session.get("vote_id"):
            lines.append("🗳️ **Voting now.** Pick a game on the vote below.")
        else:
            lines.append("Press **Join** to play. When everyone's in, the host presses **Start vote** to pick a game.")
        players = [f"{i}. <@{uid}>" for i, uid in enumerate(session["participants"], 1)]
        if len(players) > 25:
            players = players[:25] + [f"…and {len(players) - 25} more"]
        embed = discord.Embed(title=f"🎮 {session['title']}" + (" (ended)" if ended else ""),
                              description="\n".join(lines),
                              color=ui.MUTED if ended else ui.SUCCESS)
        embed.add_field(name=f"Players ({len(session['participants'])})", value="\n".join(players) or "Nobody yet",
                        inline=False)
        embed.set_footer(text=f"Session ID: {session['id']}")
        return embed

    async def refresh_session_message(self, guild: discord.Guild, session: dict, ended: bool = False):
        await self._edit_record(guild, session, lambda: self.session_card(session, ended),
                                embed=self.session_embed(session, ended),
                                view=None if ended else session_view(session["id"]))

    def session_link(self, guild: discord.Guild, session: dict) -> str:
        if not session.get("message_id"):
            return ""
        return f"https://discord.com/channels/{guild.id}/{session['channel_id']}/{session['message_id']}"

    async def create_session(self, target: Target, text: Optional[str]):
        guild, member, channel = who(target)
        tz, tz_name, personal = await self.timezone_for(member)
        now = utcnow()
        if (text or "").strip().lower().split(" ")[0] in ("every", "weekly"):
            return await self.create_recurring(target, text)
        starts_at, title = split_when(text or "", tz, now)
        if starts_at is not None and starts_at < now - timedelta(minutes=1):
            return await self.reply(target, content="⚠️ That time has already passed. Try a later time.", ephemeral=True)
        if starts_at is not None and starts_at > now + timedelta(days=60):
            return await self.reply(target, content="⚠️ Sessions can be scheduled up to 60 days ahead.", ephemeral=True)
        title = (title.strip() or f"{member.display_name}'s game session")[:200]
        await self.post_session(guild, channel, member, title, starts_at)
        note = None
        if starts_at and not personal:
            note = (f"⚠️ I read that time as **{tz_name}**. If that's wrong, set your timezone with "
                    f"{await self.cmd(guild, 'games timezone <zone>')} and start the session again.")
        if isinstance(target, discord.Interaction):
            await self.reply(target, content=note or "✅ Session posted.", ephemeral=True)
        elif note:
            await self.reply(target, content=note)

    async def post_session(self, guild: discord.Guild, channel, host: discord.Member, title: str,
                           starts_at: Optional[datetime], schedule: Optional[dict] = None) -> dict:
        """Post a session message (and its Discord event when it has a start time). Returns the session."""
        now = utcnow()
        sid = generate_id()
        session = {
            "id": sid, "title": title, "host_id": str(host.id), "participants": [str(host.id)],
            "channel_id": channel.id, "message_id": None, "created_at": now.isoformat(),
            "starts_at": starts_at.isoformat() if starts_at else None,
            # Skip the 15-minute heads-up when the session starts sooner than that anyway.
            "reminded": bool(starts_at and starts_at - now <= timedelta(minutes=REMINDER_MINUTES)),
            "started": False, "vote_id": None, "winner": None, "event_id": None,
            "recurring_id": schedule["id"] if schedule else None,
            "repeat": repeat_label(schedule) if schedule else None,
            "card": True,   # posted as a card (older sessions are embeds and are still edited as embeds)
        }
        async with self.config.guild(guild).play_sessions() as sessions:
            sessions[sid] = session
        message = await self.send_card(channel, self.session_card(session))   # names the host without a ping
        session["message_id"] = message.id
        session["event_id"] = await self.create_event(guild, session, host)
        async with self.config.guild(guild).play_sessions() as sessions:
            if sid in sessions:
                sessions[sid].update(message_id=message.id, event_id=session["event_id"])
        if session["event_id"]:
            await self.refresh_session_message(guild, session)
        return session

    # ---------- Discord events ----------

    async def create_event(self, guild: discord.Guild, session: dict, host: discord.Member) -> Optional[int]:
        """List a scheduled session in the server's Events, so Discord shows it and reminds interested people."""
        starts = parse_iso(session.get("starts_at"))
        conf = self.config.guild(guild)
        if starts is None or starts <= utcnow() + timedelta(minutes=1) or not await conf.events():
            return None
        if not guild.me.guild_permissions.manage_events:
            return None
        link = self.session_link(guild, session)
        kwargs = {
            "name": session["title"][:100], "start_time": starts, "privacy_level": discord.PrivacyLevel.guild_only,
            "description": (f"Hosted by {host.display_name}. Press Interested to join the session"
                            + (f": {link}" if link else ".") + (f"\n{session['repeat']}." if session.get("repeat") else ""))[:1000],
        }
        voice = guild.get_channel(await conf.event_channel() or 0)
        if isinstance(voice, (discord.VoiceChannel, discord.StageChannel)):
            kwargs["channel"] = voice
        else:
            channel = guild.get_channel_or_thread(session["channel_id"])
            kwargs.update(entity_type=discord.EntityType.external, end_time=starts + timedelta(hours=EVENT_LENGTH_HOURS),
                          location=f"#{channel.name}" if channel else "Discord")
        try:
            return (await guild.create_scheduled_event(**kwargs)).id
        except discord.HTTPException as e:
            log.info("Couldn't create a Discord event for session %s: %s", session["id"], e)
            return None

    async def update_event(self, guild: discord.Guild, session: dict, action: str):
        """`start` the session's Discord event, or `finish` it (end it if running, cancel it if not)."""
        if not session.get("event_id"):
            return
        event = guild.get_scheduled_event(session["event_id"])
        try:
            event = event or await guild.fetch_scheduled_event(session["event_id"])
            if action == "start" and event.status == discord.EventStatus.scheduled:
                await event.start()
            elif action == "finish" and event.status == discord.EventStatus.active:
                await event.end()
            elif action == "finish" and event.status == discord.EventStatus.scheduled:
                await event.cancel()
        except discord.HTTPException as e:
            log.debug("Couldn't %s the event for session %s: %s", action, session["id"], e)

    def _session_for_event(self, sessions: dict, event_id: int) -> Optional[str]:
        return next((sid for sid, s in sessions.items() if s.get("event_id") == event_id), None)

    @commands.Cog.listener()
    async def on_scheduled_event_user_add(self, event: discord.ScheduledEvent, user: discord.User):
        """Pressing Interested on a session's Discord event joins the session."""
        await self._event_interest(event, user, joined=True)

    @commands.Cog.listener()
    async def on_scheduled_event_user_remove(self, event: discord.ScheduledEvent, user: discord.User):
        await self._event_interest(event, user, joined=False)

    async def _event_interest(self, event: discord.ScheduledEvent, user: discord.User, joined: bool):
        guild = event.guild
        if guild is None or user.bot:
            return
        uid = str(user.id)
        async with self.config.guild(guild).play_sessions() as sessions:
            sid = self._session_for_event(sessions, event.id)
            if sid is None:
                return
            players = sessions[sid]["participants"]
            if joined and uid not in players:
                players.append(uid)
            elif not joined and uid in players and uid != sessions[sid]["host_id"]:
                players.remove(uid)
            else:
                return
            session = dict(sessions[sid])
        await self.refresh_session_message(guild, session)

    # ---------- recurring sessions ----------

    async def create_recurring(self, target: Target, text: str):
        guild, member, channel = who(target)
        tz, tz_name, personal = await self.timezone_for(member)
        parsed = parse_recurring(text, tz, utcnow())
        if parsed is None:
            return await self.reply(target, ephemeral=True, content=(
                "❓ For a repeating session, give a day and a time: "
                f"{await self.cmd(guild, 'games session every friday 9pm Raid night')} or "
                f"{await self.cmd(guild, 'games session every other sunday 8:30pm')}."))
        schedules = await self.config.guild(guild).recurring()
        if len(schedules) >= MAX_RECURRING:
            return await self.reply(target, ephemeral=True, content=(
                f"⏳ This server already has {MAX_RECURRING} repeating sessions. Stop one first with "
                f"{await self.cmd(guild, 'games recurring stop <id>')}."))
        rid = generate_id()
        schedule = {"id": rid, "title": (parsed["title"].strip() or f"{member.display_name}'s game night")[:200],
                    "host_id": str(member.id), "channel_id": channel.id, "weekday": parsed["weekday"],
                    "hour": parsed["hour"], "minute": parsed["minute"], "interval": parsed["interval"],
                    "tz": tz_name, "next_start": parsed["first"].isoformat(), "created_at": utcnow().isoformat()}
        async with self.config.guild(guild).recurring() as recurring:
            recurring[rid] = schedule
        posted = await self._tick_recurring(guild, rid, schedule, utcnow())
        lines = [f"✅ **{schedule['title']}** repeats: {repeat_label(schedule)}.",
                 f"Each one is posted here {RECURRING_POST_HOURS} hours before it starts, with the usual reminders."
                 + (" The first one is posted above." if posted else
                    f" The first is {stamp(parsed['first'])}."),
                 f"-# Skip one with {await self.cmd(guild, f'games recurring skip {rid}')} or stop them with "
                 f"{await self.cmd(guild, f'games recurring stop {rid}')}."]
        if not personal:
            lines.append(f"-# I used **{tz_name}**. If that's wrong, set yours with "
                         f"{await self.cmd(guild, 'games timezone <zone>')}, stop this and set it up again.")
        await self.reply(target, content="\n".join(lines), ephemeral=isinstance(target, discord.Interaction))

    async def _tick_recurring(self, guild: discord.Guild, rid: str, schedule: dict, now: datetime) -> bool:
        """Post the next occurrence once it's within RECURRING_POST_HOURS. Returns True if one was posted."""
        start = parse_iso(schedule["next_start"])
        if start is None or now < start - timedelta(hours=RECURRING_POST_HOURS):
            return False
        posted = False
        channel = guild.get_channel_or_thread(schedule["channel_id"])
        host = guild.get_member(int(schedule["host_id"]))
        if start > now and channel is not None and host is not None:
            try:
                await self.post_session(guild, channel, host, schedule["title"], start, schedule)
                posted = True
            except discord.HTTPException as e:
                log.info("Couldn't post recurring session %s: %s", rid, e)
        while start <= now + timedelta(hours=RECURRING_POST_HOURS):  # also skips any missed during downtime
            start = advance_occurrence(start, schedule)
        async with self.config.guild(guild).recurring() as recurring:
            if rid in recurring:
                recurring[rid]["next_start"] = start.isoformat()
        return posted

    async def latest_session(self, guild: discord.Guild, channel_id: int, host_id: Optional[str] = None) -> Optional[dict]:
        sessions = await self.config.guild(guild).play_sessions()
        candidates = [s for s in sessions.values()
                      if s["channel_id"] == channel_id and (host_id is None or s["host_id"] == host_id)]
        return max(candidates, key=lambda s: s["created_at"]) if candidates else None

    async def end_session(self, guild: discord.Guild, sid: str) -> Optional[dict]:
        async with self.config.guild(guild).play_sessions() as sessions:
            session = sessions.pop(sid, None)
        if session is None:
            return None
        if session.get("vote_id"):
            await self.cancel_vote(guild, session["vote_id"])
        session["vote_id"] = None
        await self.refresh_session_message(guild, session, ended=True)
        await self.update_event(guild, session, "finish")
        self.bot.dispatch("gm_session_ended", guild, session)  # ActivityStats records attendance
        return session

    async def on_session_button(self, interaction: discord.Interaction, action: str, sid: str):
        guild, member = interaction.guild, interaction.user
        uid = str(member.id)
        sessions_conf = self.config.guild(guild).play_sessions
        session = (await sessions_conf()).get(sid)
        if session is None:
            await ui.respond(interaction, "⚠️ This session has ended.")
            await self._drop_buttons(interaction.message)
            return

        if action in ("join", "leave"):
            async with sessions_conf() as sessions:
                session = sessions.get(sid)
                if session is None:
                    return await ui.respond(interaction, "⚠️ This session has ended.")
                players = session["participants"]
                if action == "join":
                    if uid in players:
                        return await ui.respond(interaction, "⚠️ You're already in.")
                    players.append(uid)
                else:
                    if uid == session["host_id"]:
                        return await ui.respond(interaction,
                                                "❌ You're the host, so you can't leave. Press **End session** instead.")
                    if uid not in players:
                        return await ui.respond(interaction, "⚠️ You haven't joined.")
                    players.remove(uid)
                session = dict(session)
            if ui.is_card(interaction.message):
                await interaction.response.edit_message(view=self.session_card(session), allowed_mentions=NO_PING)
            else:   # posted before sessions became cards
                await interaction.response.edit_message(embed=self.session_embed(session), view=session_view(sid))
            return

        if not await self.can_manage(member, session["host_id"]):
            return await ui.respond(interaction, "🔒 Only the host or a game admin can do that.")
        if action == "vote":
            await self.start_vote(interaction, session_id=sid)
        else:
            await interaction.response.defer()
            await self.end_session(guild, sid)

    async def _tick_session(self, guild: discord.Guild, sid: str, session: dict, now: datetime):
        starts = parse_iso(session.get("starts_at"))
        base = starts or parse_iso(session.get("created_at")) or now
        if now - base > timedelta(hours=SESSION_EXPIRE_HOURS):
            await self.end_session(guild, sid)
            return
        if starts is None:
            return
        updates = {}
        if not session.get("reminded") and starts - timedelta(minutes=REMINDER_MINUTES) <= now < starts:
            await self.announce(guild, session, f"⏰ **{session['title']}** starts {stamp(starts, 'R')}!")
            updates["reminded"] = True
        elif not session.get("started") and now >= starts:
            if now - starts < timedelta(minutes=30):  # don't announce stale starts after downtime
                await self.announce(guild, session, f"🎮 **{session['title']}** is starting now!")
            await self.update_event(guild, session, "start")
            updates.update(reminded=True, started=True)
        if updates:
            current = None
            async with self.config.guild(guild).play_sessions() as sessions:
                if sid in sessions:
                    sessions[sid].update(updates)
                    current = dict(sessions[sid])
            if current is not None and current.get("card"):   # the footer says "Reminder 15 min before" until then
                await self.refresh_session_message(guild, current)

    async def announce(self, guild: discord.Guild, session: dict, text: str):
        channel = guild.get_channel_or_thread(session["channel_id"])
        if channel is None:
            return
        mentions = " ".join(f"<@{uid}>" for uid in session["participants"])
        link = self.session_link(guild, session)
        try:
            await channel.send(f"{text} {mentions}" + (f"\n-# {link}" if link else ""), allowed_mentions=PING)
        except discord.HTTPException as e:
            log.debug("Couldn't announce session %s: %s", session["id"], e)

    @tasks.loop(minutes=1)
    async def session_loop(self):
        """Reminders, start pings, and ending stale sessions."""
        now = utcnow()
        for guild_id, data in (await self.config.all_guilds()).items():
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            for sid, session in list(data.get("play_sessions", {}).items()):
                try:
                    await self._tick_session(guild, sid, session, now)
                except Exception:
                    log.exception("Session check failed for %s", sid)
            for rid, schedule in list(data.get("recurring", {}).items()):
                try:
                    await self._tick_recurring(guild, rid, schedule, now)
                except Exception:
                    log.exception("Recurring session check failed for %s", rid)

    @session_loop.before_loop
    async def _before_session_loop(self):
        await self.bot.wait_until_red_ready()

    # ==========================================
    #                  VOTES
    # ==========================================

    def vote_candidates(self, games: dict, users: dict, players: List[str]) -> Tuple[List[str], str, Dict[str, int]]:
        """
        What to vote on: games everyone has installed; failing that, games everyone owns;
        failing that, games at least two players have installed. Best-ranked first.
        Returns (game ids, how they were picked, installed counts).
        """
        installed = {p: set(users.get(p, {}).get("installed", [])) & set(games) for p in players}
        owned = {p: (set(users.get(p, {}).get("owned", [])) & set(games)) | installed[p] for p in players}
        counts = Counter(g for ids in installed.values() for g in ids)

        def best_first(ids):
            return sorted(ids, key=lambda g: (-counts[g], -rank_score(users, players, g), games[g]["name"].lower()))

        everyone_installed = set.intersection(*installed.values()) if installed else set()
        if everyone_installed:
            return best_first(everyone_installed), "everyone has these installed", counts
        everyone_owned = set.intersection(*owned.values()) if owned else set()
        if everyone_owned:
            return best_first(everyone_owned), "everyone owns these, but not everyone has them installed", counts
        popular = [g for g, c in counts.items() if c >= 2]
        if popular:
            return best_first(popular), "nobody has a game in common, so these are installed by the most players", counts
        return [], "", counts

    def vote_card(self, vote: dict) -> ui.CardView:
        """
        A running vote: how to vote, who has voted and who hasn't, and the game buttons (up to 20, in rows of five).
        The "Waiting on" mentions are the ping when it's posted (pings(players)); every redraw is NO_PING.
        """
        ends = parse_iso(vote.get("ends_at"))
        lines = [f"Pick up to **{vote['max_choices']}**. Press a game again to take your vote back."]
        if ends:
            lines.append(f"Voting ends {stamp(ends, 'R')}, or as soon as everyone has voted.")
        voters = vote["allowed_voters"]
        voted = [u for u in voters if u in vote["user_votes"]]
        waiting = [u for u in voters if u not in vote["user_votes"]]
        lines.append(f"**Voted ({len(voted)}/{len(voters)}):** " + (mention_list(voted, 90) or "nobody yet"))
        if waiting:
            lines.append("**Waiting on:** " + mention_list(waiting, 90))
        if vote.get("basis"):
            lines.append(ui.hint(f"Options: {vote['basis']}."))
        labels = vote.get("labels") or vote.get("names") or {}
        buttons = [VoteButton(vote["id"], g, labels.get(g) or "Vote") for g in vote["games"][:MAX_VOTE_OPTIONS]]
        return ui.CardView(ui.card("\n".join(lines), ui.SEPARATOR, buttons,
                                   title=f"🗳️ What should we play? {vote.get('title', '')}".strip(),
                                   color=ui.BRAND, footer="Only session players can vote"))

    def vote_embed(self, vote: dict, guild: discord.Guild) -> discord.Embed:
        """The pre-card look, for votes posted as embeds before 2026-11-05."""
        ends = parse_iso(vote.get("ends_at"))
        voted = [guild.get_member(int(uid)) for uid in vote["user_votes"]]
        voted_names = ", ".join(m.display_name for m in voted if m) or "Nobody yet"
        lines = [f"Pick up to **{vote['max_choices']}**. Press a game again to take your vote back."]
        if ends:
            lines.append(f"Voting ends {stamp(ends, 'R')}, or as soon as everyone has voted.")
        if vote.get("basis"):
            lines.append(f"-# Options: {vote['basis']}.")
        embed = discord.Embed(title=f"🗳️ What should we play? {vote.get('title', '')}".strip(),
                              description="\n".join(lines), color=ui.BRAND)
        embed.add_field(name=f"Voted ({len(vote['user_votes'])}/{len(vote['allowed_voters'])})", value=voted_names,
                        inline=False)
        embed.set_footer(text=f"Vote ID: {vote['id']} · Only session players can vote")
        return embed

    async def start_vote(self, target: Target, session_id: Optional[str] = None, max_choices: int = 1,
                         seconds: int = DEFAULT_VOTE_SECONDS):
        guild, member, channel = who(target)
        sessions = await self.config.guild(guild).play_sessions()
        if session_id:
            session = sessions.get(session_id)
            if session is None:
                return await self.reply(target, content="❓ That session doesn't exist anymore.", ephemeral=True)
        else:
            session = await self.latest_session(guild, channel.id)
            if session is None:
                return await self.reply(target, content="❓ There's no session in this channel. Start one with "
                                                        f"{await self.cmd(guild, 'games session')}.", ephemeral=True)
        if not await self.can_manage(member, session["host_id"]):
            return await self.reply(target, content="🔒 Only the session host or a game admin can start the vote.",
                                    ephemeral=True)
        votes = await self.config.guild(guild).votes()
        if session.get("vote_id") in votes:
            return await self.reply(target, content="⚠️ A vote is already running for this session.", ephemeral=True)
        players = session["participants"]
        if len(players) < 2:
            return await self.reply(target, content="⚠️ A vote needs at least 2 players. Others can press **Join** "
                                                    "on the session first.", ephemeral=True)
        games = await self.config.guild(guild).games()
        users = await self.config.guild(guild).users()
        candidates, basis, counts = self.vote_candidates(games, users, players)
        if not candidates:
            return await self.reply(target, content="⚠️ These players don't have any games in common yet. Everyone can "
                                                    f"mark theirs with {await self.cmd(guild, 'games install')}.",
                                    ephemeral=True)
        options = candidates[:MAX_VOTE_OPTIONS]
        if len(candidates) > MAX_VOTE_OPTIONS:
            basis += f" (top {MAX_VOTE_OPTIONS} of {len(candidates)})"
        max_choices = max(1, min(max_choices, len(options)))
        seconds = max(MIN_VOTE_SECONDS, min(seconds, MAX_VOTE_SECONDS))
        show_counts = not basis.startswith("everyone has")
        labels = [(g, games[g]["name"][:70] + (f" ({counts[g]}/{len(players)})" if show_counts else "")) for g in options]

        vid = generate_id()
        ends_at = utcnow() + timedelta(seconds=seconds)
        vote = {
            "id": vid, "session_id": session["id"], "title": session["title"], "games": options,
            "names": {g: games[g]["name"] for g in options}, "basis": basis, "tallies": {}, "user_votes": {},
            "allowed_voters": list(players), "channel_id": channel.id, "message_id": None,
            "max_choices": max_choices, "created_at": utcnow().isoformat(), "created_by": str(member.id),
            "ends_at": ends_at.isoformat(), "timeout": seconds,
            "labels": dict(labels), "card": True,   # labels redraw the buttons; older votes are embeds
        }
        async with self.config.guild(guild).votes() as all_votes:
            all_votes[vid] = vote
        # Pings every player, as before: they're all named under "Waiting on".
        message = await self.send_card(channel, self.vote_card(vote), allowed_mentions=pings(players))
        async with self.config.guild(guild).votes() as all_votes:
            if vid in all_votes:
                all_votes[vid]["message_id"] = message.id
        async with self.config.guild(guild).play_sessions() as all_sessions:
            if session["id"] in all_sessions:
                all_sessions[session["id"]]["vote_id"] = vid
                session = dict(all_sessions[session["id"]])
        await self.refresh_session_message(guild, session)
        self.schedule_vote(guild.id, vid, ends_at)
        if isinstance(target, discord.Interaction):
            await self.reply(target, content="✅ Vote started.", ephemeral=True)

    async def on_vote_button(self, interaction: discord.Interaction, vid: str, gid: str):
        guild, uid = interaction.guild, str(interaction.user.id)
        everyone_voted = False
        async with self.config.guild(guild).votes() as votes:
            vote = votes.get(vid)
            if vote is None:
                feedback = "⚠️ This vote has ended."
            elif uid not in vote["allowed_voters"]:
                feedback = "🔒 Only players who joined the session can vote."
                vote = None
            else:
                name = vote.get("names", {}).get(gid, "that game")
                mine = vote["user_votes"].setdefault(uid, [])
                tallies = vote["tallies"]
                if gid in mine:
                    mine.remove(gid)
                    tallies[gid] = tallies.get(gid, 1) - 1
                    if tallies[gid] <= 0:
                        del tallies[gid]
                    feedback = f"✅ Took back your vote for **{name}**."
                elif len(mine) >= vote["max_choices"]:
                    feedback = (f"⏳ You can pick {vote['max_choices']}. Press one of your picks again to take it "
                                "back first.")
                else:
                    mine.append(gid)
                    tallies[gid] = tallies.get(gid, 0) + 1
                    feedback = f"✅ Voted for **{name}**."
                if not mine:
                    del vote["user_votes"][uid]
                everyone_voted = len(vote["user_votes"]) >= len(vote["allowed_voters"])
                vote = dict(vote)
        await ui.respond(interaction, feedback)
        if vote is None:
            return
        if not everyone_voted:   # (otherwise the results replace it right away)
            try:
                if ui.is_card(interaction.message):
                    await interaction.message.edit(view=self.vote_card(vote), allowed_mentions=NO_PING)
                else:   # posted before votes became cards
                    await interaction.message.edit(embed=self.vote_embed(vote, guild))
            except discord.HTTPException:
                pass
        if everyone_voted:
            await self.finish_vote(guild, vid, "Everyone voted")

    def schedule_vote(self, guild_id: int, vid: str, ends_at: datetime):
        old = self.vote_tasks.pop(vid, None)
        if old is not None:
            old.cancel()
        self.vote_tasks[vid] = asyncio.create_task(self._vote_timer(guild_id, vid, ends_at))

    async def _vote_timer(self, guild_id: int, vid: str, ends_at: datetime):
        try:
            remaining = (ends_at - utcnow()).total_seconds()
            if remaining > 45:
                await asyncio.sleep(remaining - 30)
                guild = self.bot.get_guild(guild_id)
                vote = (await self.config.guild_from_id(guild_id).votes()).get(vid)
                channel = guild.get_channel_or_thread(vote["channel_id"]) if guild and vote else None
                if channel is not None:
                    waiting = [f"<@{u}>" for u in vote["allowed_voters"] if u not in vote["user_votes"]]
                    text = "⏰ **30 seconds** left to vote!" + (f" Still waiting on {' '.join(waiting)}" if waiting else "")
                    try:
                        await channel.send(text, allowed_mentions=PING)
                    except discord.HTTPException:
                        pass
            await asyncio.sleep(max(0.0, (ends_at - utcnow()).total_seconds()))
            guild = self.bot.get_guild(guild_id)
            if guild is not None:
                await self.finish_vote(guild, vid, "Time's up")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Vote timer failed for %s", vid)

    async def _resume_votes(self):
        """After a restart or reload, pick running votes back up (or finish ones that ran out meanwhile)."""
        await self.bot.wait_until_red_ready()
        for guild_id, data in (await self.config.all_guilds()).items():
            for vid, vote in data.get("votes", {}).items():
                ends = parse_iso(vote.get("ends_at"))
                if ends is None:
                    created = parse_iso(vote.get("created_at")) or utcnow()
                    ends = created + timedelta(seconds=vote.get("timeout") or DEFAULT_VOTE_SECONDS)
                self.schedule_vote(guild_id, vid, ends)

    def _stop_timer(self, vid: str):
        task = self.vote_tasks.pop(vid, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def finish_vote(self, guild: discord.Guild, vid: str, reason: str = "") -> Optional[str]:
        """End a vote, post the results and the winner. Returns the winning game's name."""
        async with self.config.guild(guild).votes() as votes:
            vote = votes.pop(vid, None)
        self._stop_timer(vid)
        if vote is None:
            return None
        games = await self.config.guild(guild).games()
        users = await self.config.guild(guild).users()
        names = dict(vote.get("names") or {})
        for gid in vote.get("games", []):
            names.setdefault(gid, games.get(gid, {}).get("name", "Unknown game"))
        voters = vote["allowed_voters"]
        tallies = {g: c for g, c in vote["tallies"].items() if c > 0}
        results = sorted(tallies.items(), key=lambda kv: (-kv[1], -rank_score(users, voters, kv[0]), names.get(kv[0], "")))
        total = sum(tallies.values())

        winner, tie_note = None, ""
        if results:
            top = results[0][1]
            tied = [g for g, c in results if c == top]
            winner = tied[0]
            if len(tied) > 1:
                scores = {g: rank_score(users, voters, g) for g in tied}
                best = [g for g in tied if scores[g] == max(scores.values())]
                if len(best) > 1:
                    winner = random.choice(best)
                    tie_note = " It was a tie, so I picked one at random."
                else:
                    winner = best[0]
                    tie_note = " It was a tie, broken by everyone's game rankings."

        lines = []
        for i, (gid, count) in enumerate(results):
            medal = MEDALS[i] if i < len(MEDALS) else "▫️"
            lines.append(f"{medal} **{names.get(gid, 'Unknown game')}**: {ui.plural(count, 'vote')} "
                         f"({count / total * 100:.0f}%)")
        title = f"🗳️ Results: {vote.get('title', 'Vote')}"
        body = "\n".join(lines) or "No votes were cast."
        footer = f"{len(vote['user_votes'])} of {len(voters)} voted" + (f" · {reason}" if reason else "")
        embed = discord.Embed(title=title, description=body, color=ui.HIGHLIGHT)
        embed.set_footer(text=footer)
        await self._edit_record(guild, vote, lambda: final_card(body, title=title, color=ui.HIGHLIGHT, footer=footer),
                                embed=embed, view=None)

        channel = guild.get_channel_or_thread(vote["channel_id"])
        winner_name = names.get(winner) if winner else None
        if channel is not None and winner_name:
            reference = None
            if vote.get("message_id"):
                reference = channel.get_partial_message(vote["message_id"]).to_reference(fail_if_not_exists=False)
            try:
                await channel.send(f"🏆 **{winner_name}** wins!{tie_note} " + " ".join(f"<@{u}>" for u in voters),
                                   reference=reference, allowed_mentions=PING)
            except discord.HTTPException:
                pass

        async with self.config.guild(guild).play_sessions() as sessions:
            session = sessions.get(vote.get("session_id"))
            if session is not None and session.get("vote_id") == vid:
                session["vote_id"] = None
                if winner_name:
                    session["winner"] = winner_name
                session = dict(session)
            else:
                session = None
        if session is not None:
            await self.refresh_session_message(guild, session)
        return winner_name

    async def cancel_vote(self, guild: discord.Guild, vid: str):
        async with self.config.guild(guild).votes() as votes:
            vote = votes.pop(vid, None)
        self._stop_timer(vid)
        if vote is not None:
            await self._edit_record(
                guild, vote, lambda: final_card(f"**{vote.get('title', 'Vote')}**: no game was picked.",
                                                title="🗳️ Vote cancelled", color=ui.MUTED),
                view=None, embed=discord.Embed(title="🗳️ Vote cancelled", color=ui.MUTED))

    async def pick_vote(self, ctx: commands.Context, vote_id: Optional[str]) -> Optional[dict]:
        votes = await self.config.guild(ctx.guild).votes()
        if vote_id:
            vote = votes.get(vote_id)
        else:
            here = [v for v in votes.values() if v["channel_id"] == ctx.channel.id] or list(votes.values())
            vote = max(here, key=lambda v: v["created_at"]) if here else None
        if vote is None:
            await ctx.send("❓ There's no running vote" + (" with that ID." if vote_id else "."))
        return vote

    # ==========================================
    #               TEXT COMMANDS
    # ==========================================

    @commands.group(name="games", aliases=["game", "gm"], invoke_without_command=True)
    @commands.guild_only()
    async def games(self, ctx: commands.Context):
        """Your game library, play sessions, and votes on what to play."""
        speakup = self.bot.get_cog("SpeakUp")
        if speakup is not None and await speakup.handles_mistakes(ctx):
            return  # a mistyped subcommand: SpeakUp suggests the right one instead of the whole help page
        await ctx.send_help(ctx.command)

    @games.command(name="list")
    async def games_list(self, ctx: commands.Context):
        """Show every game in the server's library (💾 = you have it installed)."""
        games = await self.config.guild(ctx.guild).games()
        if not games:
            return await ctx.send(f"⚠️ No games have been added yet. Request one with "
                                  f"{await self.cmd(ctx.guild, 'games request <game>')}.")
        mine = set((await self.config.guild(ctx.guild).users()).get(str(ctx.author.id), {}).get("installed", []))
        items = [f"- {g['name']}" + (f" {INSTALLED}" if g["id"] in mine else "")
                 for g in sorted(games.values(), key=lambda g: g["name"].lower())]
        await self.send_list(ctx, items, "Server game library",
                             f"{ui.plural(len(items), 'game')} · {INSTALLED} = you have it installed")

    @games.command(name="search")
    async def games_search(self, ctx: commands.Context, *, query: str):
        """Search the server's library by name."""
        games = await self.config.guild(ctx.guild).games()
        key = normalize(query)
        matches = sorted((g for g in games.values() if key and key in normalize(g["name"])),
                         key=lambda g: g["name"].lower())
        if not matches:
            return await ctx.send(f"❓ No games match **{query}**.", allowed_mentions=NO_PING)
        mine = set((await self.config.guild(ctx.guild).users()).get(str(ctx.author.id), {}).get("installed", []))
        await self.send_list(ctx, [f"- {g['name']}" + (f" {INSTALLED}" if g["id"] in mine else "") for g in matches],
                             f"Games matching '{query}'", f"{ui.plural(len(matches), 'game')} · "
                                                          f"{INSTALLED} = you have it installed")

    @games.command(name="own", aliases=["ownadd", "addowned", "iown"])
    async def games_own(self, ctx: commands.Context, *, game_names: str = None):
        """
        Add games you own to your library. Separate several with commas.

        With no names, opens a picker where you tick the games you own (and untick ones you don't).
        Games the server doesn't have yet can be requested (or added) with one button.

        **Examples:**
        - `[p]games own Rocket League, Halo Infinite`
        - `[p]games own` (opens the picker)
        """
        await self.library_command(ctx, game_names, "own")

    @games.command(name="unown", aliases=["removeowned", "disown"])
    async def games_unown(self, ctx: commands.Context, *, game_names: str = None):
        """
        Remove games from your library (also clears their installed mark and rank).

        With no names, opens the library picker.
        """
        await self.library_command(ctx, game_names, "unown")

    @games.command(name="install")
    async def games_install(self, ctx: commands.Context, *, game_names: str = None):
        """
        Mark games as installed. Separate several with commas. Installed games also count as owned.

        With no names, opens a picker where you tick what you have installed.

        **Example:** `[p]games install Rocket League, Valorant`
        """
        await self.library_command(ctx, game_names, "install")

    @games.command(name="uninstall")
    async def games_uninstall(self, ctx: commands.Context, *, game_names: str = None):
        """Mark games as no longer installed (they stay in your library). With no names, opens the picker."""
        await self.library_command(ctx, game_names, "uninstall")

    @games.command(name="setrank", aliases=["rank"])
    async def games_setrank(self, ctx: commands.Context, rank: int, *, game_name: str):
        """
        Rank a game: 1 is your favorite. Rankings decide `[p]games top` and break vote ties.

        Use 0 to clear a rank. Ranking a game adds it to your library if needed.

        **Example:** `[p]games setrank 1 Counter-Strike 2`
        """
        await self.set_rank(ctx, rank, game_name)

    @games.command(name="mygames", aliases=["library", "mylibrary"])
    async def games_mygames(self, ctx: commands.Context):
        """Show your library, favorites first (💾 = installed)."""
        await self.show_library(ctx, ctx.author)

    @games.command(name="usergames", aliases=["userlibrary"])
    async def games_usergames(self, ctx: commands.Context, *, member: str):
        """
        Show someone else's library.

        **Example:** `[p]games usergames Alex`
        """
        members = await self.members_from_names(ctx, [member])
        if members:
            await self.show_library(ctx, members[0])

    @games.command(name="whoowns", aliases=["whohas"])
    async def games_whoowns(self, ctx: commands.Context, *, game_name: str):
        """List who owns a game (💾 = has it installed)."""
        await self.who_has(ctx, game_name, installed_only=False)

    @games.command(name="whoinstalled", aliases=["whohasinstalled"])
    async def games_whoinstalled(self, ctx: commands.Context, *, game_name: str):
        """List who has a game installed."""
        await self.who_has(ctx, game_name, installed_only=True)

    @games.command(name="lfg", aliases=["whoplays", "letsplay"])
    async def games_lfg(self, ctx: commands.Context, *, game_name: str):
        """
        Looking for group: ping everyone who has a game installed to see who wants to play.

        You can ping once every 5 minutes.

        **Example:** `[p]games lfg Rocket League`
        """
        await self.lfg(ctx, game_name)

    @games.command(name="request")
    async def games_request(self, ctx: commands.Context, *, game_names: str):
        """
        Ask for games to be added to the server library. Separate several with commas.

        The bot looks up each game's proper title (fixing typos and capitalization) and asks
        before using a corrected name. A game admin approves or denies each request with a button.
        """
        checked = await self.checked_names(ctx, ctx.author, parse_game_names(game_names))
        if checked is not None:
            names, appids = checked
            await self.reply(ctx, content=await self.request_games_text(ctx.guild, ctx.channel, ctx.author, names,
                                                                        appids=appids))

    @games.command(name="requests")
    async def games_requests(self, ctx: commands.Context):
        """Show pending game requests."""
        requests = await self.config.guild(ctx.guild).game_requests()
        if not requests:
            return await ctx.send("❓ No pending requests.")
        items = [f"- **{r['name']}** (requested by <@{r['requested_by']}>)" for r in requests.values()]
        await self.send_list(ctx, items, "Pending game requests",
                             f"Game admins: approve with {await self.prefix(ctx.guild)}games admin approve <game>")

    @games.command(name="shared")
    async def games_shared(self, ctx: commands.Context, *members: str):
        """
        Find games everyone in a group owns.

        Name the people, or leave it empty to use everyone in this channel who has a library.

        **Example:** `[p]games shared Alex Sam Jordan`
        """
        found = await self.members_from_names(ctx, members) if members else []
        if found is not None:
            await self.shared_games(ctx, found, installed=False)

    @games.command(name="installed", aliases=["sharedinstalled"])
    async def games_installed(self, ctx: commands.Context, *members: str):
        """
        Find games everyone in a group has installed, ready to play right now.

        Name the people, or leave it empty to use everyone in this channel who has a library.
        """
        found = await self.members_from_names(ctx, members) if members else []
        if found is not None:
            await self.shared_games(ctx, found, installed=True)

    @games.command(name="top")
    async def games_top(self, ctx: commands.Context, *filters: str):
        """
        Rank games by how much the players in this channel like them.

        Filters: `installed` (only games every owner has installed), `shared` (only games everyone owns).

        **Example:** `[p]games top shared installed`
        """
        lowered = [f.lower() for f in filters]
        await self.top_games(ctx, "installed" in lowered, "shared" in lowered)

    @games.command(name="session", aliases=["play"])
    async def games_session(self, ctx: commands.Context, *, time_and_title: str = None):
        """
        Start a game session people can join with a button.

        Optionally start with a time; everyone sees it in their own timezone, and players get
        a reminder 15 minutes before and a ping at the start. Times are read in your timezone
        (set it with `[p]games timezone`).

        Scheduled sessions also show up in the server's Discord events. Start with `every` to repeat weekly
        (or `every other` for every two weeks); each one is posted a day ahead.

        **Examples:**
        - `[p]games session` (starts now)
        - `[p]games session Raid night`
        - `[p]games session friday 9pm Raid night`
        - `[p]games session in 2h Rocket League`
        - `[p]games session tomorrow 8:30pm`
        - `[p]games session every friday 9pm Raid night`
        """
        await self.create_session(ctx, time_and_title)

    @games.command(name="sessionvote", aliases=["vote", "startvote"])
    async def games_sessionvote(self, ctx: commands.Context, *options: str):
        """
        Start a vote on what to play for the latest session in this channel (host or game admin).

        Optional, in any order: how many games each person can pick (a number up to 10), how long
        the vote runs (`90s`, `3m`), and a session ID. The **Start vote** button on the session does
        the same with the defaults: 1 pick, 2 minutes.

        Options are games everyone has installed; if there are none, games everyone owns; if there are
        none of those either, games most players have installed.

        **Examples:** `[p]games vote`, `[p]games vote 2 3m`
        """
        sessions = await self.config.guild(ctx.guild).play_sessions()
        session_id, choices, seconds = None, 1, DEFAULT_VOTE_SECONDS
        numbers = []
        for opt in options:
            if opt in sessions:
                session_id = opt
            elif opt.isdigit():
                numbers.append(int(opt))
            elif parse_duration(opt) is not None:
                seconds = parse_duration(opt)
            else:
                return await ctx.send(f"❓ I don't understand `{opt}`. Example: "
                                      f"{await self.cmd(ctx.guild, 'games vote 2 3m')}.")
        # Bare numbers: a small one is the number of picks; a larger one is seconds (the old syntax).
        for n in numbers:
            if n <= 10:
                choices = n
            else:
                seconds = n
        await self.start_vote(ctx, session_id, choices, seconds)

    @games.command(name="sessions")
    async def games_sessions(self, ctx: commands.Context):
        """Show active game sessions."""
        sessions = await self.config.guild(ctx.guild).play_sessions()
        if not sessions:
            return await ctx.send(f"❓ No active sessions. Start one with {await self.cmd(ctx.guild, 'games session')}.")
        items = []
        for s in sorted(sessions.values(), key=lambda s: s.get("starts_at") or s["created_at"]):
            starts = parse_iso(s.get("starts_at"))
            when = f" · {stamp(starts, 'R')}" if starts else ""
            status = " · 🗳️ voting" if s.get("vote_id") else (f" · 🏆 {s['winner']}" if s.get("winner") else "")
            link = self.session_link(ctx.guild, s)
            title = f"[{s['title']}]({link})" if link else s["title"]
            items.append(f"- **{title}**{when} · host <@{s['host_id']}> · {len(s['participants'])} players{status} "
                         f"· `{s['id']}`")
        await self.send_list(ctx, items, "Active sessions")

    @games.command(name="endsession")
    async def games_endsession(self, ctx: commands.Context, session_id: str = None):
        """End your latest session in this channel, or a session by ID (host or game admin)."""
        sessions = await self.config.guild(ctx.guild).play_sessions()
        if session_id:
            session = sessions.get(session_id)
        else:
            session = (await self.latest_session(ctx.guild, ctx.channel.id, str(ctx.author.id))
                       or (await self.latest_session(ctx.guild, ctx.channel.id)
                           if await self.is_game_admin(ctx.author) else None))
        if session is None:
            return await ctx.send("❓ No matching session found.")
        if not await self.can_manage(ctx.author, session["host_id"]):
            return await ctx.send("🔒 Only the host or a game admin can end that session.")
        await self.end_session(ctx.guild, session["id"])
        await ctx.send(f"✅ Ended **{session['title']}**.", allowed_mentions=NO_PING)

    @games.command(name="results")
    async def games_results(self, ctx: commands.Context, vote_id: str = None):
        """Show the current tally of a running vote (the latest one in this channel by default)."""
        vote = await self.pick_vote(ctx, vote_id)
        if vote is None:
            return
        names = vote.get("names") or {}
        games = await self.config.guild(ctx.guild).games()
        tallies = sorted(((c, g) for g, c in vote["tallies"].items() if c > 0), reverse=True)
        items = [f"**{names.get(g) or games.get(g, {}).get('name', 'Unknown game')}**: {c}" for c, g in tallies]
        await self.send_list(ctx, items or ["No votes yet."], f"Votes so far: {vote.get('title', '')}".strip(),
                             f"{len(vote['user_votes'])} of {len(vote['allowed_voters'])} voted · ID {vote['id']}")

    @games.command(name="endvote")
    async def games_endvote(self, ctx: commands.Context, vote_id: str = None):
        """End a vote now and announce the winner (whoever started it, the session host, or a game admin)."""
        vote = await self.pick_vote(ctx, vote_id)
        if vote is None:
            return
        session = (await self.config.guild(ctx.guild).play_sessions()).get(vote.get("session_id"), {})
        allowed = (str(ctx.author.id) in (vote["created_by"], session.get("host_id"))
                   or await self.is_game_admin(ctx.author))
        if not allowed:
            return await ctx.send("🔒 Only whoever started the vote, the session host, or a game admin can end it.")
        await self.finish_vote(ctx.guild, vote["id"], f"Ended early by {ctx.author.display_name}")

    @games.command(name="installrequests")
    async def games_installrequests(self, ctx: commands.Context):
        """Show install requests from game admins and how many people have installed each game."""
        games = await self.config.guild(ctx.guild).games()
        requests = await self.config.guild(ctx.guild).install_requests()
        items = [f"- **{games[r['game_id']]['name']}**: {len(r['installed_by'])}/{len(r['target_users'])} installed"
                 for r in requests.values() if r["game_id"] in games]
        if not items:
            return await ctx.send("❓ No install requests.")
        await self.send_list(ctx, items, "Install requests")

    @games.command(name="timezone", aliases=["tz"])
    async def games_timezone(self, ctx: commands.Context, *, zone: str = None):
        """
        Set the timezone used to read your session times.

        Accepts names like `America/Chicago`, cities like `Chicago`, or abbreviations like `CST`.
        Use `reset` to fall back to the server default. Run with nothing to see your current one.
        """
        await self.set_timezone(ctx, zone)

    async def set_timezone(self, target: Target, zone: Optional[str]):
        guild, member, _ = who(target)
        if not zone:
            _, name, personal = await self.timezone_for(member)
            now = utcnow().astimezone(load_zone(name)).strftime("%I:%M %p").lstrip("0")
            source = "yours" if personal else "the server default"
            return await self.reply(target, content=f"🕘 Session times are read in **{name}** ({source}). "
                                                    f"It's {now} there now.", ephemeral=True)
        if zone.lower() == "reset":
            await self.config.user(member).timezone.set(None)
            return await self.reply(target, content="✅ Using the server's default timezone.", ephemeral=True)
        found = find_timezone(zone)
        if found is None:
            return await self.reply(target, content=f"❓ I don't know the timezone **{zone}**. Try a name like "
                                                    "`America/Chicago`, a city like `Chicago`, or `CST`.",
                                    ephemeral=True)
        await self.config.user(member).timezone.set(found)
        now = utcnow().astimezone(load_zone(found)).strftime("%I:%M %p").lstrip("0")
        await self.reply(target, content=f"✅ Your timezone is **{found}** (it's {now} there now).", ephemeral=True)

    @games.command(name="newprofile", aliases=["setup", "profilesetup"])
    async def games_newprofile(self, ctx: commands.Context):
        """
        Set up your gaming profile step by step.

        Walks you through your timezone, the games you own and have installed, your top 3 favorites, and a
        wishlist of games you want (you get a ping when they go on sale). Every step can be skipped, and you
        can run it again any time.
        """
        await self.start_profile(ctx)

    @games.command(name="want", aliases=["wishlistadd"])
    async def games_want(self, ctx: commands.Context, *, game_names: str):
        """
        Add games you want but don't own to your wishlist. Separate several with commas.

        When a wishlisted game goes on sale on Steam, you get a ping (if sale alerts are on in this server).
        The game doesn't need to be in the server library.

        **Example:** `[p]games want Elden Ring, Baldur's Gate 3`
        """
        await self.want_games(ctx, game_names)

    @games.command(name="unwant", aliases=["wishlistremove"])
    async def games_unwant(self, ctx: commands.Context, *, game_name: str):
        """Remove a game from your wishlist."""
        await self.remove_want(ctx, game_name)

    @games.command(name="wishlist")
    async def games_wishlist(self, ctx: commands.Context, *, member: str = None):
        """Show your wishlist with current Steam prices, or someone else's."""
        target = ctx.author
        if member:
            found, candidates = self.find_member(ctx.guild, member)
            if found is None:
                hint = (" Did you mean " + ", ".join(m.display_name for m in candidates) + "?") if candidates else ""
                return await ctx.send(f"❓ Couldn't find a member called **{member}**.{hint}",
                                      allowed_mentions=NO_PING)
            target = found
        await self.show_wishlist(ctx, target)

    @games.command(name="wanted", aliases=["mostwanted"])
    async def games_wanted(self, ctx: commands.Context):
        """The server's most-wanted games: who wants each one, and which are on sale."""
        await self.most_wanted(ctx)

    @games.group(name="recurring", aliases=["repeating"], invoke_without_command=True)
    async def games_recurring(self, ctx: commands.Context):
        """
        Repeating game sessions.

        Start one with `[p]games session every friday 9pm Raid night` (or `every other friday`). Each session is
        posted a day before it starts. This lists them; `skip` and `stop` manage them.
        """
        schedules = await self.config.guild(ctx.guild).recurring()
        if not schedules:
            return await ctx.send(f"❓ No repeating sessions. Start one with "
                                  f"{await self.cmd(ctx.guild, 'games session every friday 9pm Raid night')}.")
        items = []
        for s in sorted(schedules.values(), key=lambda s: s["next_start"]):
            nxt = parse_iso(s["next_start"])
            items.append(f"- **{s['title']}** · {repeat_label(s)} · next {stamp(nxt, 'R')} · host <@{s['host_id']}> "
                         f"· <#{s['channel_id']}> · `{s['id']}`")
        await self.send_list(ctx, items, "🔁 Repeating sessions",
                             f"Manage with {await self.prefix(ctx.guild)}games recurring skip <id> or stop <id>")

    async def _schedule_for(self, ctx: commands.Context, schedule_id: str) -> Optional[dict]:
        schedule = (await self.config.guild(ctx.guild).recurring()).get(schedule_id)
        if schedule is None:
            await ctx.send(f"❓ No repeating session with ID `{schedule_id}`. See "
                           f"{await self.cmd(ctx.guild, 'games recurring')}.")
            return None
        if not await self.can_manage(ctx.author, schedule["host_id"]):
            await ctx.send("🔒 Only the host or a game admin can change that.")
            return None
        return schedule

    @games_recurring.command(name="stop", aliases=["delete", "remove"])
    async def recurring_stop(self, ctx: commands.Context, schedule_id: str):
        """Stop a repeating session (host or game admin). Sessions already posted stay up."""
        schedule = await self._schedule_for(ctx, schedule_id)
        if schedule is None:
            return
        async with self.config.guild(ctx.guild).recurring() as recurring:
            recurring.pop(schedule_id, None)
        await ctx.send(f"✅ **{schedule['title']}** won't repeat any more.", allowed_mentions=NO_PING)

    @games_recurring.command(name="skip")
    async def recurring_skip(self, ctx: commands.Context, schedule_id: str):
        """Skip the next occurrence of a repeating session (host or game admin)."""
        schedule = await self._schedule_for(ctx, schedule_id)
        if schedule is None:
            return
        skipped = parse_iso(schedule["next_start"])
        following = advance_occurrence(skipped, schedule)
        async with self.config.guild(ctx.guild).recurring() as recurring:
            if schedule_id in recurring:
                recurring[schedule_id]["next_start"] = following.isoformat()
        await ctx.send(f"✅ Skipping **{schedule['title']}** on {stamp(skipped, 'D')}. The next one is "
                       f"{stamp(following, 'F')}.\n-# If that one was already posted, end it with "
                       f"{await self.cmd(ctx.guild, 'games endsession <id>')}.", allowed_mentions=NO_PING)

    # ---------- admin ----------

    @games.group(name="admin", invoke_without_command=True)
    @game_admin()
    async def games_admin(self, ctx: commands.Context):
        """Library management for game admins (server admins, or the role set with `[p]games admin setrole`)."""
        await ctx.send_help(ctx.command)

    @games_admin.command(name="settings")
    async def admin_settings(self, ctx: commands.Context):
        """Show the game manager's settings for this server."""
        conf = await self.config.guild(ctx.guild).all()
        role = ctx.guild.get_role(conf["admin_role"]) if conf["admin_role"] else None
        event_channel = ctx.guild.get_channel(conf["event_channel"] or 0)
        prefix = await self.prefix(ctx.guild)
        parts = [
            "**Who can do what**\n" + ui.settings_text([
                ("Game admin role", role.mention if role else "none (server admins only)"),
                ("Members can add games", "On" if conf["member_add"] else "Off (they request)"),
            ]),
            "**Sessions**\n" + ui.settings_text([
                ("Default timezone", conf["timezone"] or "UTC"),
                ("Discord events", "Off" if not conf["events"] else
                 f"On · {event_channel.mention if event_channel else 'no voice channel'}"),
                ("Repeating sessions", str(len(conf["recurring"]))),
            ]),
            "**Wishlists**\n" + ui.settings_text([
                ("Sale alerts", f"<#{conf['sale_channel']}>" if conf["sale_channel"] else False),
                ("Free Epic games", bool(conf["free_games"])),
            ]),
            "**Right now**\n" + ui.settings_text([
                ("Library", f"{ui.plural(len(conf['games']), 'game')} · {ui.plural(len(conf['users']), 'player')}"),
                ("Pending", f"{ui.plural(len(conf['game_requests']), 'request')} · "
                            f"{ui.plural(len(conf['play_sessions']), 'session')} · "
                            f"{ui.plural(len(conf['votes']), 'vote')}"),
            ]),
        ]
        if conf["events"] and not ctx.guild.me.guild_permissions.manage_events:
            parts.append(ui.line(ui.WARN, "I need the **Manage Events** permission to post sessions as Discord events."))
        footer = (f"Change with {prefix}games admin setrole, memberadd, timezone, events, eventchannel, sales or "
                  "freegames · Staff only")
        await self.send_card(ctx, ui.CardView(ui.card(*parts, ui.SEPARATOR, title="🎮 Game night settings",
                                                      color=ui.BRAND, footer=footer)))

    @games_admin.command(name="events")
    async def admin_events(self, ctx: commands.Context, enabled: bool):
        """List scheduled sessions in the server's Discord events (on by default; needs Manage Events)."""
        await self.config.guild(ctx.guild).events.set(enabled)
        note = ("" if not enabled or ctx.guild.me.guild_permissions.manage_events
                else "\n⚠️ I need the **Manage Events** permission for this to work.")
        await ctx.send(f"✅ Scheduled sessions {'will' if enabled else 'won’t'} appear in Discord events.{note}")

    @games_admin.command(name="eventchannel")
    async def admin_eventchannel(self, ctx: commands.Context, channel: discord.VoiceChannel = None):
        """Set the voice channel session events point to. Run with no channel to list them without one."""
        await self.config.guild(ctx.guild).event_channel.set(channel.id if channel else None)
        await ctx.send(f"✅ Session events will be in {channel.mention}." if channel
                       else "✅ Session events won't point to a voice channel.")

    @games_admin.command(name="sales")
    async def admin_sales(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """
        Turn on wishlist sale alerts in a channel, or run with no channel to turn them off.

        Steam prices are checked every few hours. When a wishlisted game goes on sale (or gets cheaper), the
        people who want it are pinged once.
        """
        if channel is not None and not channel.permissions_for(ctx.guild.me).send_messages:
            return await ctx.send(f"❌ I can't send messages in {channel.mention}.")
        await self.config.guild(ctx.guild).sale_channel.set(channel.id if channel else None)
        await ctx.send(f"✅ Sale alerts will be posted in {channel.mention}." if channel else "✅ Sale alerts are off.")

    @games_admin.command(name="freegames")
    async def admin_freegames(self, ctx: commands.Context, enabled: bool):
        """Also announce games that are free to keep on the Epic Games Store (in the sale alerts channel)."""
        if enabled and not await self.config.guild(ctx.guild).sale_channel():
            return await ctx.send(f"⚠️ Pick a channel first: {await self.cmd(ctx.guild, 'games admin sales #channel')}")
        await self.config.guild(ctx.guild).free_games.set(enabled)
        await ctx.send(f"✅ Free Epic games announcements are {'on' if enabled else 'off'}.")

    @games_admin.command(name="setrole")
    @checks.admin_or_permissions(administrator=True)
    async def admin_setrole(self, ctx: commands.Context, role: discord.Role = None):
        """Set the game admin role (server admins only). Run with no role to clear it."""
        await self.config.guild(ctx.guild).admin_role.set(role.id if role else None)
        await ctx.send(f"✅ Game admin role: **{role.name}**." if role else "✅ Game admin role cleared.")

    @games_admin.command(name="memberadd")
    async def admin_memberadd(self, ctx: commands.Context, allowed: bool):
        """Let members add new games to the library themselves instead of requesting them."""
        await self.config.guild(ctx.guild).member_add.set(allowed)
        await ctx.send("✅ Members can now add games themselves." if allowed
                       else "✅ Members now request new games for approval.")

    @games_admin.command(name="timezone")
    async def admin_timezone(self, ctx: commands.Context, *, zone: str):
        """Set the server's default timezone for session times (members can set their own)."""
        found = find_timezone(zone)
        if found is None:
            return await ctx.send(f"❓ I don't know the timezone **{zone}**. Try `America/Chicago`, `Chicago`, or `CST`.")
        await self.config.guild(ctx.guild).timezone.set(found)
        await ctx.send(f"✅ Default timezone: **{found}**.")

    @games_admin.command(name="add", aliases=["import"])
    async def admin_add(self, ctx: commands.Context, *, game_names: str):
        """
        Add games to the server library. Separate them with commas or put one per line.

        Up to 10 names at a time are checked for their proper titles (typos and capitalization)
        before adding; you confirm any corrections. Bigger lists are added as typed.

        **Example:** `[p]games admin add Rocket League, Halo Infinite`
        """
        checked = await self.checked_names(ctx, ctx.author, parse_game_names(game_names))
        if checked is None:
            return
        added, existing = await self.add_games(ctx.guild, ctx.author, *checked)
        lines = []
        if added:
            lines.append(f"✅ **Added ({len(added)}):** " + ", ".join(added))
        if existing:
            lines.append("⚠️ **Already in the library:** " + ", ".join(existing))
        await self.reply(ctx, content=ui.truncate("\n".join(lines) or "⚠️ Nothing to add.", 1900))

    @games_admin.command(name="remove")
    async def admin_remove(self, ctx: commands.Context, *, game_names: str):
        """
        Remove games from the library, and from everyone's owned and installed lists.

        Asks for confirmation first, listing the exact games.
        """
        games = await self.config.guild(ctx.guild).games()
        targets, problems = {}, []
        for name in parse_game_names(game_names):
            game, candidates = resolve_game(games, name)
            if game is not None:
                targets[game["id"]] = game["name"]
            else:
                problems.append(describe_unresolved(name, candidates) + (" (be more specific)" if candidates else " (not found)"))
        note = ("\n-# Skipped: " + "; ".join(problems)) if problems else ""
        if not targets:
            return await ctx.send("❓ Nothing to remove." + note)
        listing = ui.truncate(", ".join(f"**{n}**" for n in targets.values()), 3000)
        title = "🎮 Remove from the library"
        view = ConfirmView(ctx.author.id, ui.line(ui.WARN, f"Remove {listing} from the library? This also removes "
                                                           f"{'it' if len(targets) == 1 else 'them'} from everyone's "
                                                           f"lists.") + note,
                           label="Remove", title=title)
        view.message = await self.send_card(ctx, view)
        await view.wait()
        if not view.value:
            if view.interaction is not None:
                await view.interaction.response.edit_message(
                    view=final_card(ui.line(ui.DONE, "Cancelled. Nothing was removed."), title=title, color=ui.MUTED),
                    allowed_mentions=NO_PING)
            return
        async with self.config.guild(ctx.guild).games() as all_games:
            for gid in targets:
                all_games.pop(gid, None)
        async with self.config.guild(ctx.guild).users() as users:
            for data in users.values():
                for gid in targets:
                    for field in ("owned", "installed"):
                        if gid in data.get(field, []):
                            data[field].remove(gid)
                    data.get("ranks", {}).pop(gid, None)
        await view.interaction.response.edit_message(
            view=final_card(ui.line(ui.DONE, f"Removed {listing}."), title=title, color=ui.DANGER),
            allowed_mentions=NO_PING)

    @games_admin.command(name="rename")
    async def admin_rename(self, ctx: commands.Context, *, names: str):
        """
        Rename a game.

        **Example:** `[p]games admin rename CS2 -> Counter-Strike 2`
        """
        parts = re.split(r"\s*(?:->|\|)\s*", names, maxsplit=1)
        if len(parts) != 2:
            m = re.fullmatch(r'\s*"([^"]+)"\s+(.+)', names)
            parts = [m.group(1), m.group(2)] if m else parts
        if len(parts) != 2 or not parts[1].strip():
            return await ctx.send(f"❓ Use {await self.cmd(ctx.guild, 'games admin rename Old name -> New name')}.")
        game = await self.find_game(ctx, parts[0])
        if game is None:
            return
        new_name = parts[1].strip()[:100]
        async with self.config.guild(ctx.guild).games() as games:
            if game["id"] in games:
                games[game["id"]]["name"] = new_name
        await ctx.send(f"✅ Renamed **{game['name']}** to **{new_name}**.", allowed_mentions=NO_PING)

    @games_admin.command(name="approve")
    async def admin_approve(self, ctx: commands.Context, *, game_name: str):
        """Approve a game request by name (or use the button on the request)."""
        await self._resolve_request_by_name(ctx, game_name, approve=True)

    @games_admin.command(name="deny")
    async def admin_deny(self, ctx: commands.Context, *, game_name: str):
        """Deny a game request by name (or use the button on the request)."""
        await self._resolve_request_by_name(ctx, game_name, approve=False)

    async def _resolve_request_by_name(self, ctx: commands.Context, name: str, approve: bool):
        requests = await self.config.guild(ctx.guild).game_requests()
        rid = next((rid for rid, r in requests.items() if normalize(r["name"]) == normalize(name)), None)
        if rid is None:
            return await ctx.send(f"❓ No pending request for **{name}**.", allowed_mentions=NO_PING)
        await self.resolve_request(ctx.guild, rid, ctx.author, approve)
        await ctx.tick()

    @games_admin.command(name="requestinstall")
    async def admin_requestinstall(self, ctx: commands.Context, game_name: str, *members: str):
        """
        Ask people to install a game; they confirm with a button.

        Quote game names with spaces. Leave out the members to ask everyone in this channel who has a library.

        **Example:** `[p]games admin requestinstall "Rocket League" Alex Sam`
        """
        game = await self.find_game(ctx, game_name)
        if game is None:
            return
        if members:
            targets = await self.members_from_names(ctx, members)
            if targets is None:
                return
        else:
            targets = await self.channel_members_with_games(ctx.channel)
        targets = [m for m in targets if not m.bot]
        if not targets:
            return await ctx.send("❓ Nobody to ask. Name the members, or run it in a channel where people have "
                                  "game libraries.")
        rid = generate_id()
        async with self.config.guild(ctx.guild).install_requests() as requests:
            requests[rid] = {"id": rid, "game_id": game["id"], "requested_by": str(ctx.author.id),
                             "target_users": [str(m.id) for m in targets], "installed_by": [],
                             "created_at": utcnow().isoformat()}
        ids = [m.id for m in targets]
        steam = game.get("steam_appid")
        view = ui.CardView(ui.card(
            f"{mention_list(ids, 90)}: please install **{game['name']}**, then press the button.",
            [InstallButton(rid)] + ([store_button(STEAM_APP_URL.format(steam), "View on Steam", "🛒")] if steam else []),
            title=f"🎮 Please install {game['name']}", color=ui.ATTENTION,
            footer=f"Asked by {ctx.author.display_name}"))
        await self.send_card(ctx, view, allowed_mentions=pings(ids))   # pings exactly the people asked

    @games_admin.command(name="clearsessions")
    async def admin_clearsessions(self, ctx: commands.Context):
        """End every active session (and its vote)."""
        sessions = await self.config.guild(ctx.guild).play_sessions()
        for sid in list(sessions):
            await self.end_session(ctx.guild, sid)
        await ctx.send(f"✅ Ended {ui.plural(len(sessions), 'session')}.")

    @games_admin.command(name="clearvotes")
    async def admin_clearvotes(self, ctx: commands.Context):
        """Cancel every running vote without picking a winner."""
        votes = await self.config.guild(ctx.guild).votes()
        for vid in list(votes):
            await self.cancel_vote(ctx.guild, vid)
        async with self.config.guild(ctx.guild).play_sessions() as sessions:
            for session in sessions.values():
                if session.get("vote_id") in votes:
                    session["vote_id"] = None
        await ctx.send(f"✅ Cancelled {ui.plural(len(votes), 'vote')}.")

    # ==========================================
    #       SLASH COMMANDS (with autocomplete)
    # ==========================================
    # The bot owner enables these once with `[p]slash enable games` and `[p]slash sync`.

    @slash.command(name="own", description="Add a game you own, or open your library picker")
    @app_commands.describe(game="Leave empty to tick games in a picker. Separate several with commas.")
    async def slash_own(self, interaction: discord.Interaction, game: Optional[str] = None):
        await self.library_command(interaction, game, "own", ephemeral=True)

    @slash.command(name="unown", description="Remove a game from your library")
    @app_commands.describe(game="Leave empty to open your library picker")
    async def slash_unown(self, interaction: discord.Interaction, game: Optional[str] = None):
        await self.library_command(interaction, game, "unown", ephemeral=True)

    @slash.command(name="install", description="Mark a game installed, or open your installed-games picker")
    @app_commands.describe(game="Leave empty to tick games in a picker. Separate several with commas.")
    async def slash_install(self, interaction: discord.Interaction, game: Optional[str] = None):
        await self.library_command(interaction, game, "install", ephemeral=True)

    @slash.command(name="uninstall", description="Mark a game as no longer installed")
    @app_commands.describe(game="Leave empty to open your installed-games picker")
    async def slash_uninstall(self, interaction: discord.Interaction, game: Optional[str] = None):
        await self.library_command(interaction, game, "uninstall", ephemeral=True)

    @slash.command(name="library", description="Show your library, or someone else's")
    async def slash_library(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await self.show_library(interaction, member or interaction.user, ephemeral=member is None)

    @slash.command(name="rank", description="Rank a game (1 = favorite, 0 clears)")
    async def slash_rank(self, interaction: discord.Interaction, game: str, rank: app_commands.Range[int, 0, 100]):
        await self.set_rank(interaction, rank, game, ephemeral=True)

    @slash.command(name="whoowns", description="See who owns a game and who has it installed")
    async def slash_whoowns(self, interaction: discord.Interaction, game: str):
        await self.who_has(interaction, game, installed_only=False)

    @slash.command(name="lfg", description="Ping everyone who has a game installed to play")
    async def slash_lfg(self, interaction: discord.Interaction, game: str):
        await self.lfg(interaction, game)

    @slash.command(name="shared", description="Games you and others all own (or all have installed)")
    @app_commands.describe(installed="Only games everyone has installed",
                           player1="Leave all players empty to use everyone in this channel")
    async def slash_shared(self, interaction: discord.Interaction, player1: Optional[discord.Member] = None,
                           player2: Optional[discord.Member] = None, player3: Optional[discord.Member] = None,
                           player4: Optional[discord.Member] = None, installed: bool = False):
        others = [m for m in (player1, player2, player3, player4) if m is not None]
        members = [interaction.user] + [m for m in others if m != interaction.user] if others else []
        await self.shared_games(interaction, members, installed)

    @slash.command(name="top", description="The channel's favorite games")
    async def slash_top(self, interaction: discord.Interaction, installed: bool = False, shared: bool = False):
        await self.top_games(interaction, installed, shared)

    @slash.command(name="session", description="Start a game session people can join")
    @app_commands.describe(title="What you're playing or the session's name",
                           when="Optional start time, e.g. 9pm, friday 9pm, in 2h, tomorrow 8:30pm",
                           weekly="Repeat every week (needs a day and time, like friday 9pm)")
    async def slash_session(self, interaction: discord.Interaction, title: Optional[str] = None,
                            when: Optional[str] = None, weekly: bool = False):
        if weekly:
            return await self.create_recurring(interaction, f"every {when or ''} {title or ''}")
        if when:
            guild, member, _ = who(interaction)
            tz, _, _ = await self.timezone_for(member)
            if parse_when(when, tz, utcnow()) is None:
                return await self.reply(interaction, content=f"❓ I couldn't read the time **{when}**. Try `9pm`, "
                                                             "`friday 9pm`, `in 2h`, or `tomorrow 8:30pm`.",
                                        ephemeral=True)
        await self.create_session(interaction, " ".join(p for p in (when, title) if p))

    @slash.command(name="vote", description="Start a vote on what to play for this channel's latest session")
    @app_commands.describe(picks="How many games each person can pick", minutes="How long the vote runs")
    async def slash_vote(self, interaction: discord.Interaction, picks: app_commands.Range[int, 1, 10] = 1,
                         minutes: app_commands.Range[int, 1, 60] = 2):
        await self.start_vote(interaction, None, picks, minutes * 60)

    @slash.command(name="endsession", description="End your latest session in this channel")
    async def slash_endsession(self, interaction: discord.Interaction):
        guild, member, channel = who(interaction)
        session = await self.latest_session(guild, channel.id, str(member.id))
        if session is None and await self.is_game_admin(member):
            session = await self.latest_session(guild, channel.id)
        if session is None:
            return await self.reply(interaction, content="❓ You don't have a session in this channel.", ephemeral=True)
        await self.end_session(guild, session["id"])
        await self.reply(interaction, content=f"✅ Ended **{session['title']}**.", ephemeral=True)

    @slash.command(name="request", description="Ask for a game to be added to the server library")
    async def slash_request(self, interaction: discord.Interaction, game: str):
        guild, member, channel = who(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)  # the name lookup can take a few seconds
        checked = await self.checked_names(interaction, member, parse_game_names(game), ephemeral=True)
        if checked is not None:
            names, appids = checked
            await self.reply(interaction, content=await self.request_games_text(guild, channel, member, names,
                                                                                appids=appids), ephemeral=True)

    @slash.command(name="newprofile", description="Set up your gaming profile step by step")
    async def slash_newprofile(self, interaction: discord.Interaction):
        await self.start_profile(interaction, ephemeral=True)

    @slash.command(name="want", description="Add a game you want to your wishlist (pings you when it's on sale)")
    @app_commands.describe(game="Any game on Steam. Separate several with commas.")
    async def slash_want(self, interaction: discord.Interaction, game: str):
        await interaction.response.defer(ephemeral=True, thinking=True)  # Steam lookups can take a few seconds
        await self.want_games(interaction, game, ephemeral=True)

    @slash.command(name="wishlist", description="Show your wishlist with current Steam prices")
    async def slash_wishlist(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await self.show_wishlist(interaction, member or interaction.user, ephemeral=member is None)

    @slash.command(name="timezone", description="Set the timezone your session times are read in")
    @app_commands.describe(zone="e.g. America/Chicago, Chicago, or CST. Leave empty to see yours.")
    async def slash_timezone(self, interaction: discord.Interaction, zone: Optional[str] = None):
        await self.set_timezone(interaction, zone)

    # ---------- autocomplete ----------

    async def _game_choices(self, interaction: discord.Interaction, current: str, scope: str):
        games = await self.config.guild(interaction.guild).games()
        ids = set(games)
        if scope != "all":
            data = (await self.config.guild(interaction.guild).users()).get(str(interaction.user.id), {})
            ids &= set(data.get(scope, [])) | (set(data.get("installed", [])) if scope == "owned" else set())
        # Comma-separated lists: complete the last name and keep the earlier ones.
        earlier, _, last = current.rpartition(",")
        key = normalize(last)
        names = sorted((games[g]["name"] for g in ids), key=str.lower)
        if key:
            starts = [n for n in names if normalize(n).startswith(key)]
            names = starts + [n for n in names if key in normalize(n) and n not in starts]
        lead = f"{earlier.strip()}, " if earlier.strip() else ""
        return [app_commands.Choice(name=(lead + n)[:100], value=(lead + n)[:100]) for n in names[:25]]

    @slash_own.autocomplete("game")
    @slash_install.autocomplete("game")
    @slash_rank.autocomplete("game")
    @slash_whoowns.autocomplete("game")
    @slash_lfg.autocomplete("game")
    async def _ac_all_games(self, interaction: discord.Interaction, current: str):
        return await self._game_choices(interaction, current, "all")

    @slash_unown.autocomplete("game")
    async def _ac_owned_games(self, interaction: discord.Interaction, current: str):
        return await self._game_choices(interaction, current, "owned")

    @slash_uninstall.autocomplete("game")
    async def _ac_installed_games(self, interaction: discord.Interaction, current: str):
        return await self._game_choices(interaction, current, "installed")

    @slash_timezone.autocomplete("zone")
    async def _ac_timezone(self, interaction: discord.Interaction, current: str):
        key = current.strip().lower().replace(" ", "_")
        try:
            zones = sorted(available_timezones())
        except Exception:
            zones = []
        matches = [z for z in zones if key in z.lower()] if key else ["America/New_York", "America/Chicago",
                                                                      "America/Denver", "America/Los_Angeles",
                                                                      "Europe/London", "UTC"]
        return [app_commands.Choice(name=z, value=z) for z in matches[:25]]
