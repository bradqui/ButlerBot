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
import io
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
from redbot.core.data_manager import cog_data_path


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
REMINDER_MINUTES = 15           # the usual heads-up before a scheduled session (servers can change it)
REMINDER_CHOICES = [(2880, "2 days"), (2160, "36 hours"), (1440, "1 day"), (60, "1 hour"), (15, "15 min")]
MIN_REMINDER, MAX_REMINDER = 5, 7 * 24 * 60   # minutes before the start a reminder can be
MAX_REMINDERS = 4
MAX_NOTE = 300                  # a reminder note ("Update your drivers…") shown on the card
REPLACE_WINDOW_HOURS = 12       # sessions starting this close together are "the same night"
PLAN_CHOICES = 8                # dates offered by Plan next
MAX_AHEAD_DAYS = 60             # how far ahead a session can be
SESSION_EXPIRE_HOURS = 12       # sessions end on their own this long after starting (or being created)
BURIED_AFTER = 10               # messages below a session card before it counts as scrolled away (and moves down)
HERE_COOLDOWN = 60              # seconds between `games here` moves in one channel
MAX_BANNER_BYTES = 10 * 1024 * 1024   # Discord's limit for an event's cover image
EVENT_MIN_MINUTES, EVENT_MAX_MINUTES = 15, 24 * 60
LFG_COOLDOWN_SECONDS = 300
PICKER_PAGE_SIZE = 25           # Discord's limit for one select menu
LIST_TIMEOUT = 900              # seconds a list board can be paged before its buttons grey out
LIST_PRIVATE_TIMEOUT = 840      # private boards expire before their 15-minute interaction token does

PING = discord.AllowedMentions(everyone=False, roles=False, users=True)   # the LFG ping (everyone it names)
# Cards that ping (sale alert, install request, votes on old embed sessions) pass pings([...]) with exactly the
# people meant. A game night pings with short ping_line() messages that link to its card; their IDs are kept on
# the session ("pings") or the vote ("ping_id") and deleted when the session or the vote ends.
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

RECURRING_POST_HOURS = 24       # an upcoming session's card is posted this long before it starts (earlier when
                                # it has an earlier reminder: the card going up is that reminder)
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
MAX_CHECKED_NAMES = 25          # bigger bulk adds skip the Steam and AI lookups (and say so)
MAX_AI_TITLE_LOOKUPS = 10       # AI web searches per command (about 1¢ each)
LOOKUP_CONCURRENCY = 4          # Steam and AI title lookups run this many at a time
BATCH_ROWS_SHOWN = 30           # games listed on a batch request card
# Why a name couldn't be confirmed (suggest_titles' "where it came from" when there's no title).
NOT_FOUND, NOT_SEARCHED, NOT_LOOKED_UP = "not found", "not searched", "not looked up"
UNCONFIRMED_REASONS = {
    NOT_FOUND: "Not found on Steam or by web search",
    NOT_SEARCHED: "Not on Steam under that name, and not searched for on the web",
}

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
# A comma separates names unless it's a thousands comma: "Warhammer 40,000: Darktide" is one name.
NAME_COMMA = r"(?<!\d),|,(?!\d{3}(?!\d))"


def parse_game_names(text: str) -> List[str]:
    """
    Split game names: one per line, or separated by commas on a single line. Names on separate lines keep their
    commas ("Papers, Please"), and so do quoted names and thousands commas (40,000).
    """
    names = []
    for match in re.findall(QUOTED, text):
        name = (match[0] or match[1]).strip()
        if name:
            names.append(name)
    rest = re.sub(QUOTED, "", text)
    lines = [line for line in rest.split("\n") if line.strip()]
    for part in lines if len(lines) > 1 else re.split(NAME_COMMA, rest):
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


LENGTH_LINE_RE = re.compile(r"\s*(?:length|duration)\b\s*(:?)\s*(.+?)\s*$", re.I)   # "Length: 3h" under a session


def parse_length(text: str) -> Optional[int]:
    """An event's length in minutes: '2h', '90m', '1h30m', '1.5h'. None if it can't be read."""
    m = re.fullmatch(r"\s*(?:(\d+(?:\.\d+)?)\s*h(?:ours?|rs?)?)?\s*(?:(\d+)\s*m(?:in(?:ute)?s?)?)?\s*", text.lower())
    if not m or not (m.group(1) or m.group(2)):
        return None
    return round(float(m.group(1) or 0) * 60) + int(m.group(2) or 0)


def fmt_minutes(minutes: Optional[int]) -> str:
    """90 -> '1h30m', 120 -> '2h', 45 -> '45m'."""
    if not minutes:
        return ""
    hours, mins = divmod(int(minutes), 60)
    return (f"{hours}h" if hours else "") + (f"{mins}m" if mins else "")


# "Game: Star Citizen", "Reminders: 36h, 15m", "Reminder note: Update your drivers", "Replaces: Friday games"
SETTING_LINE_RE = re.compile(r"\s*(game|reminder note|reminders?|replaces)\s*:\s*(.*?)\s*$", re.I)
NO_WORDS = ("none", "no", "off", "nothing", "-")
# A session's (and its schedule's) settings besides its time and event details
SETTING_KEYS = ("game", "reminders", "reminder_note", "replaces", "replaces_titles")


def parse_lead(text: str) -> Optional[int]:
    """How long before the start, in minutes: '36h', '2 days', '1d 12h', '90m', '15 min'. None if unreadable."""
    text = re.sub(r"\s*(before|ahead|early)$", "", text.strip().lower())
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*d(?:ays?)?)?\s*(?:(\d+(?:\.\d+)?)\s*h(?:ours?|rs?)?)?\s*"
                     r"(?:(\d+)\s*m(?:in(?:ute)?s?)?)?", text)
    if not m or not any(m.groups()):
        return None
    return round(float(m.group(1) or 0) * 1440 + float(m.group(2) or 0) * 60) + int(m.group(3) or 0)


def parse_reminders(text: str) -> Optional[List[int]]:
    """'36h, 15m' -> [2160, 15] (latest first); 'none' -> [] (just the start ping). None if any part is unreadable."""
    if text.strip().lower() in NO_WORDS:
        return []
    leads = []
    for part in re.split(r"\s*(?:,|;|\band\b)\s*", text.strip()):
        if not part:
            continue
        lead = parse_lead(part)
        if lead is None or not MIN_REMINDER <= lead <= MAX_REMINDER:
            return None
        leads.append(lead)
    leads = sorted(set(leads), reverse=True)
    return leads[:MAX_REMINDERS] if leads else None


def fmt_lead(minutes: int) -> str:
    """2160 -> '36 hours', 2880 -> '2 days', 15 -> '15 min', 90 -> '1h30m'."""
    if minutes % 1440 == 0:
        return ui.plural(minutes // 1440, "day")
    if minutes % 60 == 0:
        return ui.plural(minutes // 60, "hour")
    return f"{minutes} min" if minutes < 60 else fmt_minutes(minutes)


def leads_text(leads: List[int]) -> str:
    """'36 hours and 15 min before', or 'none: just the start ping'."""
    if not leads:
        return "None: players are pinged when it starts"
    return name_list([fmt_lead(m) for m in sorted(leads, reverse=True)], limit=MAX_REMINDERS) + " before"


def post_lead(leads: List[int]) -> timedelta:
    """How long before the start an upcoming session's card goes up: a day, or its earliest reminder if sooner."""
    return timedelta(minutes=max([RECURRING_POST_HOURS * 60, *leads]))


def cover_url(event) -> Optional[str]:
    """The URL of a Discord event's cover image (Discord keeps it, so a card can show it), or None."""
    cover = getattr(event, "cover_image", None)
    return cover.url if cover is not None else None


def image_ext(data: bytes) -> Optional[str]:
    """The file type of an image Discord takes as an event banner, from its first bytes, else None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


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


NTH_WORDS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "last": -1}
NTH_NAMES = {1: "First", 2: "Second", 3: "Third", 4: "Fourth", -1: "Last"}


def nth_weekday(year: int, month: int, weekday: int, nth: int) -> Optional[date]:
    """The `nth` (1-4, or -1 for the last) `weekday` of a month."""
    if nth == -1:
        last = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1))
        return last - timedelta(days=(last.weekday() - weekday) % 7)
    first = date(year, month, 1)
    day = first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))
    return day if day.month == month else None


def next_monthly(nth: int, weekday: int, clock: Tuple[int, int], tz: tzinfo, after: datetime) -> datetime:
    """The first `nth` `weekday` of a month at `clock` in `tz` that's later than `after` (UTC)."""
    local = after.astimezone(tz)
    year, month = local.year, local.month
    for _ in range(14):
        day = nth_weekday(year, month, weekday, nth)
        if day is not None:
            when = datetime(day.year, day.month, day.day, *clock, tzinfo=tz)
            if when > local:
                return when.astimezone(timezone.utc)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    raise ValueError("no such day")


def parse_recurring(text: str, tz: tzinfo, now: datetime) -> Optional[dict]:
    """
    'every friday 9pm Raid night', 'every other fri 21:00', 'weekly sat 8:30 pm', 'every first friday 8pm' (monthly:
    first, second, third, fourth or last) -> schedule fields, or None.
    """
    tokens = text.split()
    if not tokens or tokens[0].lower() not in ("every", "weekly", "monthly"):
        return None
    rest, interval, nth = tokens[1:], 7, None
    if rest and rest[0].lower() in NTH_WORDS:
        rest, nth, interval = rest[1:], NTH_WORDS[rest[0].lower()], None
    elif rest and rest[0].lower() == "other":
        rest, interval = rest[1:], 14
    elif tokens[0].lower() == "monthly":
        return None   # which Friday of the month?
    day = rest[0].lower().rstrip(",") if rest else ""
    if day not in WEEKDAYS:
        return None
    if [w.lower() for w in rest[1:4]] in (["of", "the", "month"], ["of", "every", "month"]):
        rest = rest[:1] + rest[4:]
    for n in (2, 1):
        clock = _parse_clock("".join(rest[1:1 + n])) if len(rest) >= 1 + n else None
        if clock is not None:
            first = (next_monthly(nth, WEEKDAYS[day], clock, tz, now) if nth
                     else next_weekly(WEEKDAYS[day], clock, tz, now))
            return {"weekday": WEEKDAYS[day], "hour": clock[0], "minute": clock[1], "interval": interval, "nth": nth,
                    "title": " ".join(rest[1 + n:]), "first": first}
    return None


def advance_occurrence(start: datetime, schedule: dict) -> datetime:
    """The occurrence after `start`, keeping the local time across daylight saving changes."""
    tz = load_zone(schedule["tz"])
    if schedule.get("nth"):
        return next_monthly(schedule["nth"], schedule["weekday"], (schedule["hour"], schedule["minute"]), tz,
                            start + timedelta(hours=1))
    day = start.astimezone(tz).date() + timedelta(days=schedule["interval"])
    return datetime(day.year, day.month, day.day, schedule["hour"], schedule["minute"],
                    tzinfo=tz).astimezone(timezone.utc)


def first_occurrence(schedule: dict, after: datetime) -> datetime:
    """A schedule's first time later than `after`, by its rule (weekly ones count from their next start)."""
    clock = (schedule["hour"], schedule["minute"])
    tz = load_zone(schedule["tz"])
    if schedule.get("nth"):
        return next_monthly(schedule["nth"], schedule["weekday"], clock, tz, after)
    anchor = (parse_iso(schedule.get("next_start")) or after).astimezone(tz).date()
    day = after.astimezone(tz).date()
    day -= timedelta(days=(day - anchor).days % schedule["interval"])   # a day on the schedule, at or before `after`
    for _ in range(3):
        when = datetime(day.year, day.month, day.day, *clock, tzinfo=tz).astimezone(timezone.utc)
        if when > after:
            return when
        day += timedelta(days=schedule["interval"])
    return when


def plan_date(text: str, schedule: dict, now: datetime) -> Optional[datetime]:
    """A date for Plan next: '11/20', 'friday', 'tomorrow' (at the schedule's usual time), or '11/20 9pm'."""
    tz = load_zone(schedule["tz"])
    when = parse_when(text, tz, now)
    if when is not None or len(text.split()) != 1:
        return when
    parsed = _parse_day(text.strip(), now.astimezone(tz).date())
    if parsed is None:
        return None
    day, kind = parsed
    when = datetime(day.year, day.month, day.day, schedule["hour"], schedule["minute"], tzinfo=tz)
    if when <= now and kind == "weekday":
        when += timedelta(days=7)
    return when.astimezone(timezone.utc)


def find_schedule(schedules: List[dict], name: str) -> Optional[dict]:
    """A schedule by ID or title (exact, else the only one whose title contains it)."""
    key = name.strip().lower()
    exact = [s for s in schedules if s["id"] == key or s["title"].lower() == key]
    partial = [s for s in schedules if key in s["title"].lower()]
    found = exact or partial
    return found[0] if len(found) == 1 else None


def repeat_label(schedule: dict) -> str:
    clock = datetime(2000, 1, 1, schedule["hour"], schedule["minute"]).strftime("%I:%M %p").lstrip("0")
    clock = f"{clock.replace(':00', '')} ({schedule['tz']})"
    day = DAY_NAMES[schedule["weekday"]]
    if schedule.get("nth"):
        return f"{NTH_NAMES[schedule['nth']]} {day} of every month at {clock}"
    every = "Every other" if schedule["interval"] == 14 else "Every"
    return f"{every} {day} at {clock}"


def session_leads(session: dict) -> List[int]:
    """A session's reminders, in minutes before the start (sessions from before they could be set have 15)."""
    return list(session["reminders"]) if "reminders" in session else [REMINDER_MINUTES]


def sent_leads(session: dict) -> Set[int]:
    """The reminders already sent (or skipped because the session was set up too late for them)."""
    if "reminders_sent" in session:
        return set(session["reminders_sent"])
    return set(session_leads(session)) if session.get("reminded") else set()


def passed_leads(leads: List[int], starts: Optional[datetime], now: datetime) -> List[int]:
    """The reminders whose time has come (a session set up or moved late skips them rather than sending them)."""
    if starts is None:
        return list(leads)
    return [lead for lead in leads if starts - timedelta(minutes=lead) <= now]


def is_pending(session: dict) -> bool:
    """An upcoming session that exists (with its Discord event) but whose card isn't posted yet."""
    return bool(session.get("pending")) and not session.get("message_id")


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


def message_link(guild_id: int, channel_id, message_id) -> str:
    """A message's jump URL (what message.jump_url gives), built from a record's IDs. Empty without a message."""
    if not channel_id or not message_id:
        return ""
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def ping_line(emoji: str, user_ids, text: str, link: str = "") -> str:
    """
    One short ping that points at a card: `🎮 <@1> <@2> **Raid night** is starting: <link>`. Mentions come first
    (at most 100, as pings() allows), cut further only if the line would pass Discord's 2,000 characters.
    """
    ids = list(dict.fromkeys(str(u) for u in user_ids))[:100]
    tail = f" {text}" + (f": {link}" if link else ".")
    mentions = [f"<@{u}>" for u in ids]
    while mentions and len(emoji) + len(" ".join(mentions)) + len(tail) + 20 > ui.MESSAGE_LIMIT:
        mentions.pop()
    more = len(ids) - len(mentions)
    return f"{emoji} " + " ".join(mentions) + (f" and {more} more" if more else "") + tail


def mention_list(user_ids, limit: int = 40) -> str:
    """`<@1>, <@2>, <@3>` (at most `limit`, then "and N more")."""
    ids = [f"<@{u}>" for u in user_ids]
    return ", ".join(ids[:limit]) + (f" and {len(ids) - limit} more" if len(ids) > limit else "")


def name_list(names: List[str], limit: int = 5) -> str:
    """`Ash, Bex and Cole` (at most `limit` names, then "and N more")."""
    if len(names) > limit:
        return ", ".join(names[:limit]) + f" and {len(names) - limit} more"
    return ", ".join(names[:-1]) + f" and {names[-1]}" if len(names) > 1 else "".join(names)


def details(*parts: Optional[str]) -> str:
    """A row's or block's detail line: the parts that aren't empty, joined with " · ", starting with a capital."""
    text = " · ".join(p for p in parts if p)
    return text[:1].upper() + text[1:]


def played_text(winners: List[str]) -> str:
    """Vote winners in order, a game that won several votes in a row counted once: `Deep Rock Galactic (won
    twice), then Helldivers 2`."""
    runs: List[List] = []
    for name in winners:
        if runs and runs[-1][0] == name:
            runs[-1][1] += 1
        else:
            runs.append([name, 1])
    return ", then ".join(name if n == 1 else f"{name} (won {'twice' if n == 2 else f'{n} times'})"
                          for name, n in runs)


def repeat_short(label: str) -> str:
    """`Every other Friday at 9 PM (UTC)` (a session's "repeat") as `every other Friday`."""
    head = label.split(" at ")[0]
    return head[:1].lower() + head[1:]


def tz_note_parts(note: str) -> Tuple[Optional[str], str]:
    """
    A session's stored timezone note ("Time read as **UTC**: … set one with `!games timezone <zone>` …") as
    (the zone, for the card's time line, and a one-line footer hint for the host). Unreadable notes stay whole.
    """
    zone = re.search(r"\*\*(.+?)\*\*", note)
    command = re.search(r"`[^`]*timezone[^`]*`", note)
    if zone is None or command is None:
        return None, note
    return zone.group(1), f"Wrong time? The host can set a timezone with {command.group(0)}, then post it again"


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
                    template=r"gm:s:(?P<action>join|leave|vote|cal|event|plan|end):(?P<sid>[a-z0-9]+)"):
    LOOKS = {   # one main action (Join); everything else grey
        "join": ("Join", "➕", discord.ButtonStyle.primary),
        "leave": ("Leave", "➖", discord.ButtonStyle.secondary),
        "vote": ("Start vote", "🗳️", discord.ButtonStyle.secondary),
        "cal": ("Add to calendar", "🗓️", discord.ButtonStyle.secondary),
        "event": ("Edit", "✏️", discord.ButtonStyle.secondary),   # (the ID says "event": it began as Edit event)
        "plan": ("Plan next", "📅", discord.ButtonStyle.secondary),
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


class RequestBatchButton(discord.ui.DynamicItem[discord.ui.Button],
                         template=r"gm:rb:(?P<action>approve|deny|review):(?P<bid>[a-z0-9]+)"):
    """The buttons on a batch request card (several games requested at once): approve all, review, deny all."""

    def __init__(self, action: str, bid: str, partly: bool = False):
        label = {"approve": "Approve the rest" if partly else "Approve all", "review": "Review",
                 "deny": "Deny the rest" if partly else "Deny all"}[action]
        super().__init__(discord.ui.Button(
            label=label, custom_id=f"gm:rb:{action}:{bid}",
            style=discord.ButtonStyle.primary if action == "approve" else discord.ButtonStyle.secondary,
        ))
        self.action, self.bid = action, bid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], match["bid"])

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("GameManager")
        if cog is not None and interaction.guild is not None:
            await cog.on_batch_button(interaction, self.action, self.bid)


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


def session_buttons(sid: str, scheduled: bool = False, *, vote: bool = True,
                    plan: bool = False) -> List[discord.ui.Item]:
    """
    Join, Leave, Start vote (not when the game is set ahead), Add to calendar and Edit (scheduled sessions: an .ics
    file, and their settings and Discord event), Plan next (special nights from a schedule), End session.
    """
    actions = ["join", "leave"] + (["vote"] if vote else []) + (["cal", "event"] if scheduled else [])
    actions += (["plan"] if plan else []) + ["end"]
    return [SessionButton(action, sid) for action in actions]


ICS_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def ics_escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_fold(line: str) -> str:
    """Lines longer than 75 bytes continue on the next line after a space (RFC 5545)."""
    out, current = [], ""
    for char in line:
        if len((current + char).encode("utf-8")) > 75:
            out.append(current)
            current = " " + char
        else:
            current += char
    return "\r\n".join(out + [current])


def schedule_rrule(schedule: dict) -> str:
    """The repeat rule for a schedule: weekly, every other week, or the nth (or last) weekday of each month."""
    day = ICS_DAYS[schedule["weekday"]]
    if schedule.get("nth"):
        return f"FREQ=MONTHLY;BYDAY={schedule['nth']}{day}"
    interval = max(1, int(schedule.get("interval") or 7) // 7)
    return f"FREQ=WEEKLY;BYDAY={day}" + (f";INTERVAL={interval}" if interval > 1 else "")


def ics_calendar(uid: str, title: str, start: datetime, end: datetime, *, description: str = "", location: str = "",
                 url: str = "", rrule: Optional[str] = None, tz_name: Optional[str] = None) -> bytes:
    """
    An .ics file with one event. A repeating one is written in its own timezone (TZID, which Google, Apple and Outlook
    all read) so the local time holds across daylight saving changes; a single one is written in UTC.
    """
    def stamp(when: datetime) -> str:
        if rrule and tz_name:
            return f";TZID={tz_name}:" + when.astimezone(load_zone(tz_name)).strftime("%Y%m%dT%H%M%S")
        return ":" + when.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ButlerBot//Game nights//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "BEGIN:VEVENT", f"UID:{uid}@butlerbot",
             "DTSTAMP:" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
             "DTSTART" + stamp(start), "DTEND" + stamp(end)]
    if rrule:
        lines.append(f"RRULE:{rrule}")
    lines.append(f"SUMMARY:{ics_escape(title)}")
    if description:
        lines.append(f"DESCRIPTION:{ics_escape(description)}")
    if location:
        lines.append(f"LOCATION:{ics_escape(location)}")
    if url:
        lines.append(f"URL:{url}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return ("\r\n".join(ics_fold(line) for line in lines) + "\r\n").encode("utf-8")


def ics_filename(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "game night").lower()).strip("-")[:40]
    return f"{slug or 'game-night'}.ics"


def plans_next(session: dict) -> bool:
    """Whether a session's card offers Plan next: a special night from a schedule (monthly, or one that replaces
    another night). Plain weekly nights already come every week."""
    return bool(session.get("recurring_id")) and bool(
        session.get("replaces") or "of every month" in (session.get("repeat") or ""))


def vote_buttons(vote: dict) -> List[discord.ui.Item]:
    """A running vote's option buttons, each showing its tally once it has one: `Deep Rock Galactic · 2`."""
    labels = vote.get("labels") or vote.get("names") or {}
    tallies = vote.get("tallies") or {}
    buttons = []
    for gid in vote["games"][:MAX_VOTE_OPTIONS]:
        label = ui.truncate(labels.get(gid) or "Vote", 72)
        count = tallies.get(gid, 0)
        buttons.append(VoteButton(vote["id"], gid, f"{label} · {count}" if count > 0 else label))
    return buttons


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
    """
    Accept the corrected game names, keep what was typed, or cancel. Without corrections (only names nobody could
    confirm), the main button keeps them. `skippable` adds a button that drops the unconfirmed names.
    """

    expired_note = "Expired. Nothing was added or requested."

    def __init__(self, user_id: int, plural: bool, text: str = "", *, corrections: bool = True,
                 skippable: bool = False):
        super().__init__(user_id, timeout=180)
        self.choice: Optional[str] = None
        self.text, self.plural, self.corrections = text, plural, corrections
        self.title = "🎮 Check the names" if plural else "🎮 Check the name"
        if corrections:
            buttons = [make_button("Use suggestions" if plural else "Use suggestion", self._choose("suggested"),
                                   style=discord.ButtonStyle.primary),
                       make_button("Keep my spelling", self._choose("typed"))]
        else:   # "suggested" still carries the silent capitalization fixes
            buttons = [make_button("Keep them" if plural else "Keep it", self._choose("suggested"),
                                   style=discord.ButtonStyle.primary)]
        if skippable:
            buttons.append(make_button("Skip unconfirmed" if corrections else "Skip them" if plural else "Skip it",
                                       self._choose("skip")))
        buttons.append(make_button("Cancel", self._choose("cancel")))
        self.add_item(ui.card(text, buttons, title=self.title))

    def _choose(self, value: str):
        async def callback(interaction: discord.Interaction):
            self.choice = value
            self.stop()
            names = "names" if self.plural else "name"
            note = {"suggested": f"Using the suggested {names}." if self.corrections else f"Using the {names} as is.",
                    "typed": f"Using the {names} as typed.", "skip": f"Skipping the {names} I couldn't confirm.",
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
        go = make_button("Add to library" if can_add else f"Request {them}", self._go,
                         emoji="➕" if can_add else "📨", style=discord.ButtonStyle.primary)
        footer = (f"Adds {them} to the server library and to yours" if can_add
                  else f"A game admin needs to add {them}: the button sends a request")
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
                view=final_card("Skipped. Nothing was added for that name.", title=self.TITLE, color=ui.MUTED),
                allowed_mentions=NO_PING)

        select.callback = on_select
        question = f"Which game on Steam did you mean by **{name}**?" if name else "Which game on Steam did you mean?"
        self.add_item(ui.card(question, [select], [make_button("Skip it", on_cancel)], title=self.TITLE))


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


class EventDetailsModal(discord.ui.Modal):
    """
    The Edit event form: description, length, voice channel and banner for a session's Discord event, plus (when
    there's something to choose) removing the banner and using the details for a repeating session's future ones.
    """

    def __init__(self, cog: "GameManager", session: dict, schedule: Optional[dict]):
        super().__init__(title="Event details")
        self.cog, self.sid = cog, session["id"]
        details = session.get("event") or {}
        self.description = discord.ui.TextInput(style=discord.TextStyle.paragraph, required=False, max_length=800,
                                                default=details.get("description") or None,
                                                placeholder="What's planned, what to bring…")
        self.add_item(discord.ui.Label(text="Description", component=self.description))
        self.length = discord.ui.TextInput(required=False, max_length=12, default=fmt_minutes(details.get("minutes")) or None,
                                           placeholder="2h, 90m")
        self.add_item(discord.ui.Label(text="Length", component=self.length,
                                       description=f"Leave empty for {EVENT_LENGTH_HOURS} hours outside voice, open-ended in voice"))
        voice_id = details.get("voice_id")
        self.voice = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.voice, discord.ChannelType.stage_voice], min_values=0, max_values=1,
            required=False, placeholder="No voice channel",
            default_values=[discord.SelectDefaultValue(id=voice_id, type=discord.SelectDefaultValueType.channel)]
            if voice_id else [])
        self.add_item(discord.ui.Label(text="Voice channel", component=self.voice,
                                       description="Where it happens. Empty uses the server's usual one, if set"))
        self.banner = discord.ui.FileUpload(required=False, max_values=1)
        self.add_item(discord.ui.Label(text="Banner image", component=self.banner,
                                       description="PNG, JPG, GIF or WebP, up to 10 MB. Empty keeps the current one"))
        options = []
        if details.get("banner"):
            options.append(discord.CheckboxGroupOption(label="Remove the banner", value="remove"))
        if schedule is not None:
            options.append(discord.CheckboxGroupOption(
                label="Also use for future sessions", value="future",
                description=ui.truncate(repeat_label(schedule), 100)))
        self.options = None
        if options:
            self.options = discord.ui.CheckboxGroup(options=options, required=False, min_values=0,
                                                    max_values=len(options))
            self.add_item(discord.ui.Label(text="Options", component=self.options))

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.apply_event_details(
            interaction, self.sid, description=self.description.value or "", length=self.length.value or "",
            voice_ids=[c.id for c in self.voice.values], banners=list(self.banner.values),
            options=list(self.options.values) if self.options else [], menu=self.menu)

    menu: Optional["SessionEditMenu"] = None


def future_option(schedule: Optional[dict]) -> Optional[discord.ui.CheckboxGroup]:
    """The "Also use for future sessions" tick box of a repeating session's forms (None for one-off sessions)."""
    if schedule is None:
        return None
    return discord.ui.CheckboxGroup(required=False, min_values=0, max_values=1, options=[discord.CheckboxGroupOption(
        label="Also use for future sessions", value="future", description=ui.truncate(repeat_label(schedule), 100))])


class SettingsModal(discord.ui.Modal):
    """One of the Edit menu's short forms. Subclasses add their fields and say how to save them (`save`)."""

    def __init__(self, menu: "SessionEditMenu", title: str):
        super().__init__(title=title)
        self.menu = menu
        self.future = future_option(menu.schedule)

    def add_future(self):
        if self.future is not None:
            self.add_item(discord.ui.Label(text="Repeating session", component=self.future))

    @property
    def for_future(self) -> bool:
        return self.future is not None and "future" in self.future.values

    async def save(self, interaction: discord.Interaction) -> str:
        raise NotImplementedError

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()   # the menu's message is redrawn below
        await self.menu.saved(interaction, await self.save(interaction))


class TitleTimeModal(SettingsModal):
    def __init__(self, menu: "SessionEditMenu"):
        super().__init__(menu, "Title and time")
        session = menu.session
        self.name = discord.ui.TextInput(max_length=100, default=session["title"][:100])
        self.add_item(discord.ui.Label(text="Title", component=self.name))
        starts = parse_iso(session.get("starts_at"))
        self.when = discord.ui.TextInput(required=False, max_length=40, placeholder="friday 9pm, 11/20 8pm",
                                         default=clock_text(starts, menu.tz) if starts else None)
        self.add_item(discord.ui.Label(text="Starts", component=self.when,
                                       description=f"In your timezone ({menu.tz_name})"))
        self.add_future()

    async def save(self, interaction: discord.Interaction) -> str:
        return await self.menu.cog.save_title_time(interaction.guild, interaction.user, self.menu.sid,
                                                   self.name.value, self.when.value or "", self.for_future)


class GameModal(SettingsModal):
    def __init__(self, menu: "SessionEditMenu"):
        super().__init__(menu, "Game")
        game = menu.session.get("game")
        self.game = discord.ui.TextInput(required=False, max_length=100, default=game["name"] if game else None,
                                         placeholder="Empty: vote on it as usual")
        self.add_item(discord.ui.Label(text="Game", component=self.game,
                                       description="Set the game ahead (no vote), from the server library"))
        self.add_future()

    async def save(self, interaction: discord.Interaction) -> str:
        return await self.menu.cog.save_game(interaction.guild, interaction.user, self.menu.sid,
                                             self.game.value or "", self.for_future)


class BannerModal(SettingsModal):
    """Draw banner: Gemini paints the event's banner from the title and game, plus an optional idea."""

    def __init__(self, menu: "SessionEditMenu"):
        super().__init__(menu, "Draw a banner")
        self.idea = discord.ui.TextInput(required=False, max_length=300, style=discord.TextStyle.paragraph,
                                         placeholder="A space battle at dusk, a cozy tavern…")
        self.add_item(discord.ui.Label(text="What it should show", component=self.idea,
                                       description="Optional: leave it empty to go by the title and game"))
        self.add_future()

    async def save(self, interaction: discord.Interaction) -> str:
        return await self.menu.cog.draw_banner(interaction.guild, interaction.user, self.menu.sid,
                                               self.idea.value or "", self.for_future)


class RemindersModal(SettingsModal):
    def __init__(self, menu: "SessionEditMenu"):
        super().__init__(menu, "Reminders")
        leads = session_leads(menu.session)
        presets = [minutes for minutes, _ in REMINDER_CHOICES]
        self.choices = discord.ui.CheckboxGroup(required=False, min_values=0, max_values=len(REMINDER_CHOICES),
                                                options=[discord.CheckboxGroupOption(label=f"{label} before",
                                                                                     value=str(minutes),
                                                                                     default=minutes in leads)
                                                         for minutes, label in REMINDER_CHOICES])
        self.add_item(discord.ui.Label(text="Remind players", component=self.choices,
                                       description="None ticked: they're pinged when it starts"))
        other = [lead for lead in leads if lead not in presets]
        self.other = discord.ui.TextInput(required=False, max_length=40, placeholder="3h, 2 days",
                                          default=", ".join(fmt_lead(m) for m in other) or None)
        self.add_item(discord.ui.Label(text="Other times", component=self.other,
                                       description="How long before the start, separated by commas"))
        self.note = discord.ui.TextInput(style=discord.TextStyle.paragraph, required=False, max_length=MAX_NOTE,
                                         default=menu.session.get("reminder_note") or None,
                                         placeholder="Update your drivers, patch the game…")
        self.add_item(discord.ui.Label(text="Reminder note", component=self.note,
                                       description="Shown on the card, so every reminder carries it"))
        self.add_future()

    async def save(self, interaction: discord.Interaction) -> str:
        leads = [int(value) for value in self.choices.values]
        if (self.other.value or "").strip():
            extra = parse_reminders(self.other.value)
            if extra is None:
                return ui.line(ui.ASK, f"I couldn't use **{ui.truncate(self.other.value, 30)}** as reminder times.",
                               hint="Try 3h or 2 days, from 5 minutes to 7 days before.")
            leads += extra
        leads = sorted(set(leads), reverse=True)
        if len(leads) > MAX_REMINDERS:
            return ui.line(ui.ASK, f"That's {len(leads)} reminders.", hint=f"Pick up to {MAX_REMINDERS}.")
        return await self.menu.cog.save_settings(interaction.guild, interaction.user, self.menu.sid,
                                                 {"reminders": leads,
                                                  "reminder_note": (self.note.value or "").strip() or None},
                                                 self.for_future, "Reminders saved.")


class ReplacesModal(SettingsModal):
    def __init__(self, menu: "SessionEditMenu", schedules: List[dict]):
        super().__init__(menu, "Replaces")
        current = menu.session.get("replaces") or []
        self.choices = discord.ui.CheckboxGroup(
            required=False, min_values=0, max_values=len(schedules),
            options=[discord.CheckboxGroupOption(label=ui.truncate(s["title"], 100), value=s["id"],
                                                 description=ui.truncate(repeat_label(s), 100),
                                                 default=s["id"] in current) for s in schedules])
        self.add_item(discord.ui.Label(text="Replaces these on the same night", component=self.choices,
                                       description="Their session that night is off (and comes back if this is "
                                                   "cancelled)"))
        self.add_future()

    async def save(self, interaction: discord.Interaction) -> str:
        return await self.menu.cog.save_replaces(interaction.guild, interaction.user, self.menu.sid,
                                                 list(self.choices.values), self.for_future)


def clock_text(when: datetime, tz: tzinfo) -> str:
    """A time as the Edit menu's form shows it, and parse_when reads it back: `11/20 8:00pm`."""
    local = when.astimezone(tz)
    return f"{local.month}/{local.day} " + local.strftime("%I:%M%p").lstrip("0").lower()


class SessionEditMenu(OwnerOnlyCard):
    """
    The card's Edit button: everything about a session in one private card (its settings and Discord event),
    with a short form for each group. On a repeating session each form can also change future ones.
    """

    expired_note = "Expired. Press Edit on the card again."

    def __init__(self, cog: "GameManager", user_id: int, session: dict, schedule: Optional[dict],
                 tz: tzinfo, tz_name: str):
        super().__init__(user_id, timeout=LIST_PRIVATE_TIMEOUT)
        self.cog, self.sid, self.session, self.schedule = cog, session["id"], session, schedule
        self.tz, self.tz_name = tz, tz_name
        self.note: Optional[str] = None
        self.redraw()

    def build(self) -> discord.ui.Container:
        s, event = self.session, self.session.get("event") or {}
        starts = parse_iso(s.get("starts_at"))
        rows = [
            ("Title", s["title"]),
            ("Starts", stamp(starts) if starts else "No set time"),
            ("Repeats", s.get("repeat") or "No"),
            ("Game", s["game"]["name"] if s.get("game") else "Picked by vote"),
            ("Reminders", leads_text(session_leads(s))),
            ("Reminder note", ui.truncate(s["reminder_note"], 80) if s.get("reminder_note") else "None"),
            ("Replaces", name_list(s["replaces_titles"]) if s.get("replaces_titles") else "Nothing"),
            ("Description", ui.truncate(event["description"], 80) if event.get("description") else "None"),
            ("Length", fmt_minutes(event.get("minutes")) or "The usual"),
            ("Voice channel", f"<#{event['voice_id']}>" if event.get("voice_id") else "The server's usual one"),
            ("Banner", bool(event.get("banner"))),
        ]
        buttons = [make_button("Title & time", self._open(TitleTimeModal)),
                   make_button("Event details", self._event), make_button("Game", self._open(GameModal)),
                   make_button("Reminders", self._open(RemindersModal)), make_button("Replaces", self._replaces)]
        more = ([make_button("Plan next", self._plan)] if s.get("recurring_id") else []) + \
            [make_button("Draw banner", self._open(BannerModal))]
        footer = ("Each form can also change future sessions · " if self.schedule else "") + \
            "Changes show on the card and the Discord event"
        return ui.card(self.note, ui.settings_text(rows), ui.SEPARATOR, buttons, more,
                       title=f"🎮 {ui.truncate(s['title'], 80)} settings", color=ui.BRAND, footer=footer)

    async def saved(self, interaction: discord.Interaction, line: str):
        """After a form: show what happened above the (re-read) settings."""
        self.session = (await self.cog.config.guild(interaction.guild).play_sessions()).get(self.sid, self.session)
        if self.session.get("recurring_id"):
            self.schedule = (await self.cog.config.guild(interaction.guild).recurring()).get(
                self.session["recurring_id"])
        self.note = line
        self.redraw()
        try:
            await interaction.edit_original_response(view=self, allowed_mentions=NO_PING)
        except discord.HTTPException:
            await interaction.followup.send(line, ephemeral=True)

    def _open(self, modal_type):
        async def callback(interaction: discord.Interaction):
            await interaction.response.send_modal(modal_type(self))
        return callback

    async def _event(self, interaction: discord.Interaction):
        modal = EventDetailsModal(self.cog, self.session, self.schedule)
        modal.menu = self
        await interaction.response.send_modal(modal)

    async def _replaces(self, interaction: discord.Interaction):
        schedules = [s for s in (await self.cog.config.guild(interaction.guild).recurring()).values()
                     if s["id"] != self.session.get("recurring_id")]
        if not schedules:
            return await ui.respond(interaction, ui.line(ui.ASK, "There are no other repeating sessions to replace."))
        await interaction.response.send_modal(ReplacesModal(self, schedules[:10]))

    async def _plan(self, interaction: discord.Interaction):
        await self.cog.open_plan_next(interaction, self.session)


class ReplaceAskView(OwnerOnlyCard):
    """A new session or schedule falls on another schedule's night: should it replace that night?"""

    expired_note = "Expired. Both stay on; change it with the card's Edit button."

    def __init__(self, cog: "GameManager", user_id: int, text: str, rids: List[str], *,
                 sid: Optional[str] = None, rid: Optional[str] = None):
        super().__init__(user_id, timeout=600)
        self.cog, self.text, self.rids, self.sid, self.rid = cog, text, rids, sid, rid
        self.add_item(ui.card(ui.line(ui.WARN, text),
                              [make_button("Replace it", self._replace, style=discord.ButtonStyle.primary),
                               make_button("Keep both", self._keep)],
                              title="🎮 Same night", color=ui.ATTENTION))

    async def _replace(self, interaction: discord.Interaction):
        self.stop()
        await interaction.response.defer()
        titles = await self.cog.set_replaces(interaction.guild, self.rids, sid=self.sid, rid=self.rid)
        await interaction.edit_original_response(view=final_card(
            ui.line(ui.DONE, f"It replaces {name_list([f'**{t}**' for t in titles])} that night.",
                    hint="If it's cancelled, the regular night comes back."), title="🎮 Same night"),
            allowed_mentions=NO_PING)

    async def _keep(self, interaction: discord.Interaction):
        self.stop()
        await interaction.response.edit_message(view=final_card(
            ui.line(ui.DONE, "Both stay on.", hint="Change it any time with the card's Edit button."),
            title="🎮 Same night"), allowed_mentions=NO_PING)


class PlanNextView(OwnerOnlyCard):
    """Plan next: pick a date for another of this schedule's nights (the card and event follow as usual)."""

    expired_note = "Expired. Nothing was planned."

    def __init__(self, cog: "GameManager", user_id: int, schedule: dict, dates: List[datetime]):
        super().__init__(user_id, timeout=LIST_PRIVATE_TIMEOUT)
        self.cog, self.schedule = cog, schedule
        tz = load_zone(schedule["tz"])
        select = discord.ui.Select(placeholder="Pick a date", options=[
            discord.SelectOption(label=d.astimezone(tz).strftime("%A, %B ") + str(d.astimezone(tz).day),
                                 value=d.isoformat(),
                                 description=clock_text(d, tz).split(" ")[1] + f" ({schedule['tz']})")
            for d in dates])
        select.callback = self._picked
        self.select = select
        self.add_item(ui.card(f"Another **{schedule['title']}** night. Its Discord event shows right away, and the "
                              "card is posted before it like the others.", [select],
                              title="🎮 Plan next", color=ui.BRAND))

    async def _picked(self, interaction: discord.Interaction):
        self.stop()
        await interaction.response.defer()
        line = await self.cog.book_night(interaction.guild, interaction.user, self.schedule["id"],
                                         parse_iso(self.select.values[0]))
        await interaction.edit_original_response(view=final_card(line, title="🎮 Plan next"),
                                                 allowed_mentions=NO_PING)


class BatchReviewView(OwnerOnlyCard):
    """Review on a batch request card: a game admin picks some of the games, then approves or denies them."""

    expired_note = "Expired. The rest are still waiting on the request card."
    TITLE = "🎮 Review the requests"

    def __init__(self, cog: "GameManager", user_id: int, bid: str, pending: List[dict], note: Optional[str] = None):
        super().__init__(user_id, timeout=LIST_PRIVATE_TIMEOUT)
        self.cog, self.bid = cog, bid
        shown = pending[:25]
        self.select = discord.ui.Select(
            placeholder="Pick games…", min_values=1, max_values=len(shown),
            options=[discord.SelectOption(label=item["name"][:100], value=item["rid"],
                                          description="Couldn't confirm this name" if item.get("unconfirmed") else None)
                     for item in shown])
        self.select.callback = self._picked
        lines = [note, "Pick games, then approve or deny them. The rest stay waiting."]
        if len(pending) > len(shown):
            lines.append(ui.hint(f"Showing the first 25 of {len(pending)}. The rest come up next."))
        self.add_item(ui.card("\n".join(l for l in lines if l), [self.select],
                              [make_button("Approve picked", self._decide(True), style=discord.ButtonStyle.primary),
                               make_button("Deny picked", self._decide(False))],
                              title=self.TITLE))

    async def _picked(self, interaction: discord.Interaction):
        await interaction.response.defer()   # the choice is read when a button is pressed

    def _decide(self, approve: bool):
        async def callback(interaction: discord.Interaction):
            if not self.select.values:
                return await ui.respond(interaction, ui.line(ui.ASK, "Pick at least one game first."))
            self.stop()
            await interaction.response.defer()
            guild = interaction.guild
            line = await self.cog.resolve_batch(guild, self.bid, interaction.user,
                                                {rid: approve for rid in self.select.values})
            pending = await self.cog.batch_pending(guild, self.bid)
            if pending:
                view = BatchReviewView(self.cog, self.user_id, self.bid, pending, note=line)
                view.message = interaction
            else:
                view = final_card(ui.line(ui.DONE, "All of them are decided.", hint=line), title=self.TITLE)
            await interaction.edit_original_response(view=view, allowed_mentions=NO_PING)
        return callback


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
            buttons.append(make_button("Type a timezone", self._other_timezone, emoji="🌐"))
        elif name == "owned":
            lines += [f"You have **{ui.plural(len(owned), 'game')}** in your library.",
                      "Tick them from the server's list, or type their names. Games the server doesn't have yet can "
                      "be requested (or added) from there."]
            buttons.append(make_button("Pick games", self._picker("owned"), emoji="🎮",
                                       style=discord.ButtonStyle.primary, disabled=not games))
            buttons.append(make_button("Type names", self._type_owned, emoji="⌨️"))
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
            names = ", ".join(e["name"] for e in wanted[:20]) + (f" and {len(wanted) - 20} more" if len(wanted) > 20 else "")
            lines += ["Games you want but don't own yet. When one goes on sale on Steam, you'll get a ping.", "",
                      ui.two_line(f"**{ui.plural(len(wanted), 'game')} on your wishlist**", names or None)]
            if not channel_id:
                lines.append("-# Sale alerts aren't turned on in this server yet, but your wishlist is saved.")
            buttons.append(make_button("Add wanted games", self._type_wanted, emoji="⭐",
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
            footer="Every step can be skipped"))   # anyone else who presses is told it isn't theirs

    async def _summary(self, games: dict, data: dict, owned: List[str]) -> discord.ui.Container:
        guild, member = self.state["guild"], self.state["member"]
        _, tz_name, _ = await self.cog.timezone_for(member)
        ranks = sorted(((r, g) for g, r in data.get("ranks", {}).items() if g in games and r <= 3))
        installed = [g for g in data.get("installed", []) if g in games]
        wanted = await self.cog.wanted_by(guild, member)
        # Key-value pairs, so the settings-card layout (Message style's exception), without per-line emoji.
        rows = ui.settings_text([
            ("Timezone", tz_name),
            ("Library", f"{ui.plural(len(owned), 'game')}, {len(installed)} installed"),
            ("Favorites", ", ".join(f"#{r} {games[g]['name']}" for r, g in ranks) or "none"),
            ("Wishlist", ui.plural(len(wanted), "game")),
        ])
        footer = f"Run {await self.cog.cmd(guild, 'games newprofile')} again to change anything"
        return ui.card(rows, title="🎮 Your profile is set up", color=ui.SUCCESS, footer=footer)

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

        await interaction.response.send_modal(TextModal("Games you own", "Game names, one per line",
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

        await interaction.response.send_modal(TextModal("Games you want", "Game names, one per line",
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
            request_batches={},   # one card for several games requested at once (see batch_card)
            play_sessions={},
            votes={},
            install_requests={},
            admin_role=None,
            member_add=False,   # members may add new games to the library without a request
            timezone=None,      # default timezone for session times
            reminders=[REMINDER_MINUTES],   # default reminders for new sessions (minutes before the start)
            recurring={},       # weekly and monthly schedules that make sessions ahead of time
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
        self._move_locks: Dict[str, asyncio.Lock] = {}   # session ID -> lock, so a card never moves twice at once
        self._here_last: Dict[int, float] = {}            # channel ID -> when `games here` last moved a card
        self._resume_task: Optional[asyncio.Task] = None

    async def cog_load(self):
        self.bot.add_dynamic_items(SessionButton, VoteButton, RequestButton, RequestBatchButton, InstallButton)
        self._resume_task = asyncio.create_task(self._resume_votes())
        self.session_loop.start()
        self.sale_loop.start()

    async def cog_unload(self):
        self.bot.remove_dynamic_items(SessionButton, VoteButton, RequestButton, RequestBatchButton, InstallButton)
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

    async def guide_member_notes(self, member: discord.Member) -> List[str]:
        """Facts about the asker the bot guide needs to run commands for them (here: the timezone times are read in)."""
        _, name, personal = await self.timezone_for(member)
        if personal:
            return [f"Their saved timezone is {name}; times they give for sessions and reminders are read in it, so "
                    "don't run games timezone unless they ask to change it."]
        return [f"They have no saved timezone, so their session times are read in the server's ({name}). If they "
                "name a different zone, set it with games timezone first."]

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

    async def send_list(self, target: Target, items: List[ui.Row], title: str, footer: Optional[str] = None,
                        ephemeral: bool = False, *, header: Optional[str] = None,
                        empty: Optional[str] = None) -> Optional[ui.Board]:
        """
        Post a list as a board: one card that pages 8 rows at a time with ◀ ▶ (anyone can page it), plus a Jump to
        menu on long lists. Rows are two-line `ui.row(main, detail)` tuples: the game or person in **bold**, with
        markers like 💾 at the end, and their counts and details on a small line underneath. `footer` follows
        "Page x of y" (a count plus at most one hint); `header` sits above the rows on every page. Mentions in rows
        never ping. With no rows it's a ❓ line, unless `empty` is given (then the board shows that text instead).
        """
        if not items and empty is None:
            await self.reply(target, content=ui.line(ui.ASK, "Nothing to show."), ephemeral=ephemeral)
            return None
        # A private reply can only be edited while its interaction token lasts (15 minutes), so it expires a bit sooner.
        private = ephemeral and isinstance(target, discord.Interaction)
        board = ui.Board(ui.truncate(title, 100), items, header=header, footer=footer,
                         empty=empty or "Nothing to show yet.",
                         timeout=LIST_PRIVATE_TIMEOUT if private else LIST_TIMEOUT)
        await board.send(target, ephemeral=ephemeral, allowed_mentions=NO_PING)
        return board

    async def library_rows(self, guild: discord.Guild, viewer: discord.abc.User, games: List[dict]) -> List[tuple]:
        """Board rows for server games: **Name** 💾 over `4 own · 3 installed` (💾 = the viewer has it installed)."""
        users = await self.config.guild(guild).users()
        owners, installers = Counter(), Counter()
        for uid, data in users.items():
            if guild.get_member(int(uid)) is None:
                continue   # people who left aren't counted
            installed = set(data.get("installed", []))
            installers.update(installed)
            owners.update(set(data.get("owned", [])) | installed)   # installing implies owning
        mine = set(users.get(str(viewer.id), {}).get("installed", []))
        rows = []
        for g in games:
            installed = installers[g["id"]]
            rows.append(ui.row(f"**{g['name']}**" + (f" {INSTALLED}" if g["id"] in mine else ""),
                               details(f"{owners[g['id']]} own", f"{installed} installed" if installed else None)))
        return rows

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

    async def _ping(self, guild: discord.Guild, channel_id, emoji: str, user_ids, text: str,
                    link: str = "") -> Optional[int]:
        """Send a one-line ping (ping_line) that pings exactly `user_ids`. Returns its message ID, or None."""
        channel = guild.get_channel_or_thread(channel_id or 0)
        ids = list(dict.fromkeys(str(u) for u in user_ids))[:100]
        if channel is None or not ids:
            return None
        try:
            message = await channel.send(ping_line(emoji, ids, text, link), allowed_mentions=pings(ids))
        except discord.HTTPException as e:
            log.debug("Couldn't send a ping in %s: %s", channel_id, e)
            return None
        return message.id

    async def _delete_messages(self, guild: discord.Guild, channel_id, message_ids):
        """Delete ping lines that are done with. Messages already gone, or missing permissions, are skipped."""
        channel = guild.get_channel_or_thread(channel_id or 0)
        if channel is None:
            return
        for mid in dict.fromkeys(m for m in message_ids or [] if m):
            try:
                await channel.get_partial_message(int(mid)).delete()
            except discord.HTTPException as e:   # NotFound (someone deleted it) or Forbidden
                log.debug("Couldn't delete ping %s: %s", mid, e)

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
        names, appids, unconfirmed = checked
        if not add:
            return await self.request_games_text(guild, channel, member, names, action, appids=appids,
                                                 unconfirmed=unconfirmed)
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
        cog is loaded) an AI web search for the official title. Lookups run a few at a time. Without a title,
        "where" says why: NOT_FOUND, NOT_SEARCHED (no AI search left, or no Claude cog) or NOT_LOOKED_UP (too
        many names at once).
        """
        games = await self.config.guild(member.guild).games()
        by_key = {normalize(g["name"]): g for g in games.values()}
        finder = getattr(self.bot.get_cog("ClaudeChat"), "find_game_title", None)
        lookups_allowed = len(names) <= MAX_CHECKED_NAMES
        results: List[Optional[Tuple[str, Optional[str], Optional[int], str]]] = [None] * len(names)
        pending = []   # (index, name) still to look up
        for i, typed in enumerate(names):
            name = clean_title(typed)
            key = normalize(name)
            match = by_key.get(key)
            if match is None and key:
                close = difflib.get_close_matches(key, list(by_key), n=1, cutoff=0.85)
                match = by_key[close[0]] if close else None
            if match is not None:
                results[i] = (name, match["name"], match.get("steam_appid"), "already in the library")
            elif not key:
                results[i] = (name, None, None, "")
            elif not lookups_allowed:
                results[i] = (name, None, None, NOT_LOOKED_UP)
            else:
                pending.append((i, name))

        gate = asyncio.Semaphore(LOOKUP_CONCURRENCY)

        async def on_steam(name):
            async with gate:
                return await steam_exact_title(name)

        async def on_web(name):
            async with gate:
                try:
                    return await finder(name, member)
                except Exception:
                    log.exception("Game title lookup failed for %r", name)
                    return None

        not_on_steam = []
        for (i, name), found in zip(pending, await asyncio.gather(*(on_steam(n) for _, n in pending))):
            if found is not None:
                results[i] = (name, found[0], found[1], "Steam")
            else:
                not_on_steam.append((i, name))
        searched = not_on_steam[:MAX_AI_TITLE_LOOKUPS] if finder is not None else []
        for (i, name), found in zip(searched, await asyncio.gather(*(on_web(n) for _, n in searched))):
            results[i] = ((name, clean_title(found["title"]), found.get("steam_appid"), "web search") if found
                          else (name, None, None, NOT_FOUND))
        for i, name in not_on_steam[len(searched):]:
            results[i] = (name, None, None, NOT_SEARCHED)
        return results

    async def checked_names(self, target: Target, member: discord.Member, names: List[str],
                            ephemeral: bool = False) -> Optional[Tuple[List[str], Dict[str, int], Set[str]]]:
        """
        Look up proper titles for new game names, and let the person confirm any corrections and any name that
        couldn't be confirmed. Returns (final names, Steam app IDs by name, the final names nobody confirmed), or
        None if they cancelled or didn't answer.
        """
        channel = who(target)[2]
        async with channel.typing():
            found = await self.suggest_titles(member, names)
        suggested, typed, appids, lines = [], [], {}, []
        corrected, unsure, unchecked = set(), [], []
        for name, title, appid, source in found:
            typed.append(name)
            suggested.append(title or name)
            if appid:
                appids[title or name] = appid
            # Capitalization and symbol fixes are applied silently; only real spelling changes need a yes.
            if title and normalize(title) != normalize(name):
                corrected.add(name)
                where = {"Steam": "Steam's name for it", "web search": "found by web search"}.get(source, source)
                lines.append(ui.two_line(f"**{title}**", f"You typed `{name}` · {where}"))
            elif title is None and source in UNCONFIRMED_REASONS:
                unsure.append(ui.two_line(f"**{name}**", UNCONFIRMED_REASONS[source]))
            elif title is None and source == NOT_LOOKED_UP:
                unchecked.append(name)
        unconfirmed = {n for n, t, _, s in found if t is None and s}
        if not lines and not unconfirmed:
            return suggested, appids, set()
        parts = []
        if lines:
            parts += [f"I checked {'those names' if len(lines) > 1 else 'that name'}. Did you mean:", *lines]
        if unsure:
            parts += [f"I couldn't confirm {'these' if len(unsure) > 1 else 'this one'}. Check the spelling, or "
                      "whether a comma split a name:", *unsure]
        if unchecked:
            parts.append(ui.two_line(f"**Not looked up: more than {MAX_CHECKED_NAMES} names at once**",
                                     ", ".join(unchecked)))
        plural = len(lines) + len(unsure) + len(unchecked) > 1
        # Skipping only differs from cancelling when some names were fine.
        skippable = bool(unconfirmed) and len(unconfirmed) < len([n for n in typed if n])
        view = NameCheckView(member.id, plural, ui.truncate("\n".join(parts), 3500), corrections=bool(lines),
                             skippable=skippable)
        view.message = await self.send_card(target, view, ephemeral=ephemeral)
        await view.wait()
        if view.choice == "suggested":
            return suggested, appids, unconfirmed
        if view.choice == "typed":
            return typed, {n: a for n, a in appids.items() if n in typed}, unconfirmed | corrected
        if view.choice == "skip":
            kept = [s for s, (n, *_) in zip(suggested, found) if n not in unconfirmed]
            return kept, {n: a for n, a in appids.items() if n in kept}, set()
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
        for gid in owned:   # ranked games first, their rank inside the bold: **1. Deep Rock Galactic** 💾
            name = f"{ranks[gid]}. {games[gid]['name']}" if ranks.get(gid) else games[gid]["name"]
            items.append(ui.row(f"**{name}**" + (f" {INSTALLED}" if gid in installed else "")))
        count = len([g for g in owned if g in installed])
        await self.send_list(target, items, f"🎮 {member.display_name}'s library",
                             f"{ui.plural(len(owned), 'game')}, {count} installed · {INSTALLED} = installed", ephemeral)

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
                rank = data.get("ranks", {}).get(game["id"])   # the one real detail: how much they like it
                row = ui.row(f"**{member.display_name}**{mark}", f"Their #{rank}" if rank else None)
                rows.append((member.display_name.lower(), row, has_installed))
        if not rows:
            verb = "has it installed" if installed_only else "owns it"
            return await self.reply(target, content=f"❓ Nobody {verb} yet: **{game['name']}**.")
        rows.sort(key=lambda r: r[0])
        if installed_only:
            await self.send_list(target, [r[1] for r in rows], f"🎮 Who has {game['name']} installed",
                                 ui.plural(len(rows), "player"))
        else:
            count = len([r for r in rows if r[2]])
            await self.send_list(target, [r[1] for r in rows], f"🎮 Who owns {game['name']}",
                                 f"{ui.plural(len(rows), 'owner')}, {count} installed · {INSTALLED} = installed")

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
        items = []
        for g in common:
            if installed:   # everyone has every one of these installed: nothing more to say
                items.append(ui.row(f"**{g['name']}**"))
                continue
            ready = sum(1 for m in members if g["id"] in users.get(str(m.id), {}).get("installed", []))
            items.append(ui.row(f"**{g['name']}**" + (f" {INSTALLED}" if g["id"] in mine else ""),
                                f"{ready} of {len(members)} installed"))
        title = "🎮 Installed by everyone" if installed else "🎮 Owned by everyone"
        footer = ui.plural(len(items), "game") + ("" if installed else f" · {INSTALLED} = you have it installed")
        await self.send_list(target, items, title, footer, header=ui.truncate(f"With {names}", 200))

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
        items = [ui.row(f"**{i}. {name}**" + (f" {INSTALLED}" if is_mine else ""),
                        details(f"{owners} of {len(member_ids)} own", f"{inst} installed" if inst else None))
                 for i, (_, _, _, name, owners, inst, is_mine) in enumerate(rows, 1)]
        filters = [label for on, label in ((shared_only, "owned by everyone"),
                                           (installed_only, "installed by every owner")) if on]
        header = "Only games " + " and ".join(filters) + "." if filters else None
        await self.send_list(target, items, "🎮 Top games",
                             f"Ranked by the rankings of {ui.plural(len(members), 'player')} · "
                             f"{INSTALLED} = you have it installed", header=header)

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
                                 appids: Optional[Dict[str, int]] = None,
                                 unconfirmed: Optional[Set[str]] = None) -> str:
        """
        File requests for new games (each gets an approval card with Approve/Deny). Returns status lines.
        Names in `unconfirmed` (that the name check couldn't confirm) get a warning on their card.
        """
        text, _ = await self._request_games(guild, channel, member, names, action, appids, unconfirmed)
        return text

    async def request_games(self, guild, channel, member, names: List[str], action: Optional[str] = None,
                            appids: Optional[Dict[str, int]] = None) -> discord.Embed:
        """The same as request_games_text, as an embed: kept for other cogs (SpeakUp's Steam card buttons)."""
        text, created = await self._request_games(guild, channel, member, names, action, appids)
        return discord.Embed(description=text, color=ui.SUCCESS if created else ui.MUTED)

    def request_card(self, request: dict, approver: Optional[discord.abc.User] = None,
                     approved: Optional[bool] = None, note: Optional[str] = None) -> ui.CardView:
        """
        A game request: ATTENTION with Approve/Deny while pending, then SUCCESS (approved) or DANGER (denied), with
        an optional `note` hint (what happened to the requester's library).
        """
        name, requester = request["name"], request["requested_by"]
        link = ([store_button(STEAM_APP_URL.format(request["steam_appid"]), "View on Steam")]
                if request.get("steam_appid") else [])
        title = f"🎮 Game request: {name}"
        if approved is None:
            then = {"own": "approving also adds it to their library",
                    "install": "approving also marks it installed for them"}.get(request.get("for_action"))
            warning = (ui.line(ui.WARN, "I couldn't confirm this name on Steam or the web.",
                               hint="Check the spelling before approving.") if request.get("unconfirmed") else None)
            return ui.CardView(ui.card(
                ui.two_line(f"**{name}**", details(f"requested by <@{requester}> for the server library", then)),
                warning,
                [RequestButton("approve", request["id"]), RequestButton("deny", request["id"])] + link,
                title=title, color=ui.ATTENTION, footer="Game admins can approve or deny"))
        verb = "approved" if approved else "denied"
        detail = details(f"requested by <@{requester}>", f"{verb} by {approver.mention}" if approver else None)
        return ui.CardView(ui.card(
            ui.two_line("✅ **Approved**" if approved else "**Denied**", detail + (f"\n{note}" if note else "")),
            link or None, title=title, color=ui.SUCCESS if approved else ui.DANGER))

    async def _request_games(self, guild, channel, member, names: List[str], action: Optional[str],
                             appids: Optional[Dict[str, int]],
                             unconfirmed: Optional[Set[str]] = None) -> Tuple[str, bool]:
        appids = appids or {}
        unconfirmed = {normalize(n) for n in unconfirmed or ()}
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
                                     "card": True, "unconfirmed": key in unconfirmed}
                    requested[key] = dict(requests[rid])
                    created.append((rid, name))

        if len(created) > 1:
            await self._post_batch(guild, channel, member, created, action, unconfirmed)
        for rid, name in created if len(created) == 1 else ():
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

    async def _decide_request(self, guild: discord.Guild, rid: str, approver: discord.Member,
                              approve: bool) -> Optional[Tuple[dict, Optional[str]]]:
        """
        Close a request: on approval, add the game (and own or install it for the requester). Returns the request and
        a note about the requester's library, or None if the request is gone. Cards and pings are up to the caller.
        """
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
        note = None
        if approve and action == "own":
            note = (f"It's in their library, not marked installed. If it's installed: "
                    f"{await self.cmd(guild, 'games install ' + name)}")
        elif approve and action == "install":
            note = "It's marked installed for them."
        return request, note

    async def _post_batch(self, guild, channel, member, created: List[Tuple[str, str]], action: Optional[str],
                          unconfirmed: Set[str]):
        """Several new requests at once: one batch card for all of them (each request points at it)."""
        bid = generate_id()
        batch = {"id": bid, "requested_by": str(member.id), "for_action": action, "channel_id": channel.id,
                 "message_id": None, "card": True, "created_at": utcnow().isoformat(), "decided": {},
                 "items": [{"rid": rid, "name": name, "unconfirmed": normalize(name) in unconfirmed}
                           for rid, name in created]}
        # Saved before the card goes up, so a quick click finds it.
        async with self.config.guild(guild).request_batches() as batches:
            batches[bid] = batch
        async with self.config.guild(guild).game_requests() as requests:
            for rid, _ in created:
                if rid in requests:
                    requests[rid]["batch"] = bid
        try:
            message = await self.send_card(channel, self.batch_card(batch))
        except discord.HTTPException as e:
            log.warning("Couldn't post a batch request card in %s: %s", channel.id, e)
            return
        async with self.config.guild(guild).request_batches() as batches:
            if bid in batches:
                batches[bid]["message_id"] = message.id

    async def resolve_request(self, guild: discord.Guild, rid: str, approver: discord.Member, approve: bool) -> Optional[str]:
        """Approve or deny a request. Returns the game name, or None if the request is gone."""
        decided = await self._decide_request(guild, rid, approver, approve)
        if decided is None:
            return None
        request, note = decided
        name, requester = request["name"], request["requested_by"]
        if request.get("batch"):   # its batch card redraws, and the requester hears once the batch is settled
            await self._settle_batch(guild, request["batch"], approver, [(request, approve)])
            return name
        verb = "approved" if approve else "denied"
        embed = discord.Embed(title=f"✅ Approved: {name}" if approve else f"❌ Denied: {name}",
                              color=ui.SUCCESS if approve else ui.DANGER,
                              description=f"Requested by <@{requester}>, {verb} by {approver.mention}."
                                          + (f"\n-# {note}" if note else ""))
        await self._edit_record(guild, request, lambda: self.request_card(request, approver, approve, note),
                                embed=embed, view=None)
        # One short line that pings the requester and points at the card, which has the details.
        link = message_link(guild.id, request.get("channel_id"), request.get("message_id"))
        text = (f"**{name}** was added to the server library" if approve
                else f"your request for **{name}** was denied")
        emoji = "✅" if approve else "❌"
        channel = guild.get_channel_or_thread(request.get("channel_id") or 0)
        if channel is not None:
            # Without a card (it couldn't be posted) the line says it all, note included.
            line = f"{emoji} <@{requester}>, {text}" + (f": {link}" if link else
                                                         "." + (f"\n-# {note}" if note else ""))
            try:
                await channel.send(line, allowed_mentions=pings([requester]))
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

    # ---------- requests for several games at once ----------

    def batch_card(self, batch: dict) -> ui.CardView:
        """
        One card for a batch of game requests: a row per game (✅ approved, "Denied", ⚠️ unconfirmed), with Approve
        all / Review / Deny all while any are waiting. ATTENTION while waiting, then SUCCESS (or DANGER if none
        were approved).
        """
        items, decided, requester = batch["items"], batch.get("decided", {}), batch["requested_by"]
        pending = [i for i in items if i["rid"] not in decided]
        approved = sum(1 for d in decided.values() if d["approved"])
        rows = []
        for item in items[:BATCH_ROWS_SHOWN]:
            verdict = decided.get(item["rid"])
            if verdict is None:
                rows.append(ui.two_line(f"**{item['name']}**" + (" ⚠️" if item.get("unconfirmed") else ""),
                                        "Couldn't confirm this name on Steam or the web"
                                        if item.get("unconfirmed") else None))
            else:
                rows.append(ui.two_line(f"**{item['name']}**" + (" ✅" if verdict["approved"] else ""),
                                        None if verdict["approved"] else "Denied"))
        if len(items) > BATCH_ROWS_SHOWN:
            rows.append(ui.hint(f"And {len(items) - BATCH_ROWS_SHOWN} more."))
        then = {"own": "approving also adds them to their library",
                "install": "approving also marks them installed for them"}.get(batch.get("for_action"))
        title = f"🎮 Game requests: {ui.plural(len(items), 'game')}"
        if pending:
            head = ui.two_line(f"**{ui.plural(len(items), 'game')}** requested by <@{requester}>",
                               details("for the server library", then))
            partly = len(pending) < len(items)
            buttons = [RequestBatchButton(action, batch["id"], partly) for action in ("approve", "review", "deny")]
            return ui.CardView(ui.card(head, ui.SEPARATOR, "\n".join(rows), buttons, title=title,
                                       color=ui.ATTENTION, footer="Game admins can approve or deny"))
        head = ui.two_line(f"**{approved} approved, {len(items) - approved} denied**",
                           f"requested by <@{requester}>")
        note = {"own": "Approved games are in their library, not marked installed",
                "install": "Approved games are marked installed for them"}.get(batch.get("for_action"))
        return ui.CardView(ui.card(head, ui.SEPARATOR, "\n".join(rows), title=title,
                                   color=ui.SUCCESS if approved else ui.DANGER, footer=note if approved else None))

    async def batch_pending(self, guild: discord.Guild, bid: str) -> List[dict]:
        """A batch's games still waiting for a decision (and still requested)."""
        batch = (await self.config.guild(guild).request_batches()).get(bid)
        if batch is None:
            return []
        requests = await self.config.guild(guild).game_requests()
        return [i for i in batch["items"] if i["rid"] not in batch.get("decided", {}) and i["rid"] in requests]

    async def resolve_batch(self, guild: discord.Guild, bid: str, approver: discord.Member,
                            decisions: Dict[str, bool]) -> str:
        """Approve or deny some of a batch's games (rid -> approve), then redraw its card once. Returns a line."""
        results = []
        for rid, approve in decisions.items():
            decided = await self._decide_request(guild, rid, approver, approve)
            if decided is not None:
                results.append((decided[0], approve))
        if results:
            await self._settle_batch(guild, bid, approver, results)
        approved = sum(1 for _, a in results if a)
        parts = [f"approved {approved}" if approved else None,
                 f"denied {len(results) - approved}" if len(results) > approved else None]
        if not results:
            return ui.line(ui.WARN, "Those were already handled.")
        return ui.line(ui.DONE, details(*parts) + ".")

    async def _settle_batch(self, guild: discord.Guild, bid: str, approver: discord.Member,
                            results: List[Tuple[dict, bool]]):
        """Record decisions on a batch, redraw its card, and once every game is decided ping the requester once."""
        async with self.config.guild(guild).request_batches() as batches:
            batch = batches.get(bid)
            if batch is None:
                return
            decided = batch.setdefault("decided", {})
            for request, approve in results:
                decided[request["id"]] = {"approved": approve, "by": str(approver.id)}
            done = all(i["rid"] in decided for i in batch["items"])
            if done:
                batches.pop(bid)
            batch = dict(batch)
        await self._edit_record(guild, batch, lambda: self.batch_card(batch))
        if not done:
            return
        total = len(batch["items"])
        approved = sum(1 for d in batch["decided"].values() if d["approved"])
        if approved == total:
            text = f"all {ui.plural(total, 'game')} you requested were added to the server library"
        elif approved:
            text = f"{approved} of the {total} games you requested were added to the server library"
        else:
            text = f"your requests for {ui.plural(total, 'game')} were denied"
        link = message_link(guild.id, batch.get("channel_id"), batch.get("message_id"))
        await self._ping(guild, batch.get("channel_id"), "✅" if approved else "❌", [batch["requested_by"]], text,
                         link)

    async def on_batch_button(self, interaction: discord.Interaction, action: str, bid: str):
        if not await self.is_game_admin(interaction.user):
            return await ui.respond(interaction, "🔒 Only game admins can approve or deny requests.")
        guild = interaction.guild
        pending = await self.batch_pending(guild, bid)
        if not pending:
            return await ui.respond(interaction, "⚠️ Those requests were already handled.")
        if action == "review":
            view = BatchReviewView(self, interaction.user.id, bid, pending)
            await self.send_card(interaction, view, ephemeral=True)
            view.message = interaction
            return
        if action == "approve":
            await interaction.response.defer()
            await self.resolve_batch(guild, bid, interaction.user, {i["rid"]: True for i in pending})
            return
        title = "🎮 Deny requests"
        view = ConfirmView(interaction.user.id, ui.line(ui.WARN, f"Deny {ui.plural(len(pending), 'waiting request')}? "
                                                                 "The games won't be added."),
                           label="Deny all", title=title)
        await self.send_card(interaction, view, ephemeral=True)
        view.message = interaction
        await view.wait()
        if view.interaction is None:
            return
        if not view.value:
            return await view.interaction.response.edit_message(
                view=final_card("Cancelled. Nothing was denied.", title=title, color=ui.MUTED),
                allowed_mentions=NO_PING)
        await view.interaction.response.defer()
        line = await self.resolve_batch(guild, bid, interaction.user,
                                        {i["rid"]: False for i in await self.batch_pending(guild, bid)})
        await view.interaction.edit_original_response(view=final_card(line, title=title), allowed_mentions=NO_PING)

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
                names, appids, _ = checked
                added, _ = await self.add_games(guild, member, names, appids)
                more, _ = await self.change_library_text(guild, member, names, "own")
                if added:
                    lines.append(f"✅ **Added to the server library:** {', '.join(added)}")
                lines.append(more)
            else:
                names, appids, unconfirmed = checked
                lines.append(await self.request_games_text(guild, channel, member, names, "own", appids=appids,
                                                           unconfirmed=unconfirmed))
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
        items = [ui.row(f"**[{e['name']}]({STEAM_APP_URL.format(e['appid'])})**",
                        price_text(e["price"]) if e.get("checked_at") else None) for e in wanted]
        channel_id = await self.config.guild(guild).sale_channel()
        alerts = "Sale alerts are on" if channel_id else "Sale alerts aren't turned on in this server"
        await self.send_list(target, items, f"🎮 {member.display_name}'s wishlist",
                             f"{ui.plural(len(items), 'game')} · {alerts}", ephemeral)

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
        for _, _, entry, fans in sorted(rows, key=lambda r: r[:2]):
            names = name_list([self._display(guild, u) for u in fans], 5)
            discount = (entry.get("price") or {}).get("discount")
            items.append(ui.row(f"**[{entry['name']}]({STEAM_APP_URL.format(entry['appid'])})**",
                                details(f"wanted by {len(fans)}: {names}",
                                        f"**{discount}% off**" if discount else None)))
        await self.send_list(target, items, "🎮 Most-wanted games",
                             f"{ui.plural(len(items), 'game')} · owners aren't counted")

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
            line = ui.two_line(f"**[{entry['name']}]({STEAM_APP_URL.format(entry['appid'])})**",
                               price_text(entry["price"]))
            new_fans = [u for u in fans if u not in pinged][:100 - len(pinged)]
            size = sum(len(l) + 1 for l in lines) + len(line) + 23 * (len(pinged) + len(new_fans))
            if lines and (size > 3400 or len(new_fans) < len([u for u in fans if u not in pinged])):
                break   # a card holds about 4,000 characters, and a message pings at most 100 people
            lines.append(line)
            shown.append(entry)
            pinged += new_fans
        if not lines:
            return 0
        prefix = await self.prefix(guild)
        link = [store_button(STEAM_APP_URL.format(shown[0]["appid"]), "View on Steam")] if len(shown) == 1 else None
        # Each person is named (and pinged) once, however many of their wishes are on sale.
        wanted = ui.hint("Wanted by " + ", ".join(f"<@{u}>" for u in pinged))
        view = ui.CardView(ui.card("\n".join(lines) + "\n" + wanted, link, title="🎮 On sale on Steam",
                                   color=ui.HIGHLIGHT,
                                   footer=f"From your wishlists · {prefix}games want / {prefix}games unwant"))
        try:
            # The "Wanted by" mentions are the ping: everyone who wants a game on sale, as before.
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
            lines.append(ui.two_line(f"**[{game['title']}]({game['url']})**",
                                     f"Free until {stamp(ends, 'f')}" if ends else None))
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

    def session_card(self, session: dict, ended: bool = False, vote: Optional[dict] = None,
                     guild: Optional[discord.Guild] = None) -> ui.CardView:
        """
        A session's card, in short two-line blocks: when (and how often), who's playing, then the vote or its
        result, the buttons, and a one-hint footer. The whole game night happens in this one card: a vote started
        from it runs inside it (pass the running `vote`, a record with "in_card"; `guild` turns the people it's
        waiting on into display names), and the result stays in it ("vote_result"). SUCCESS while it's open,
        ATTENTION while voting, MUTED once it has ended (then without buttons). Player mentions in it don't ping:
        it's always sent and edited with NO_PING. The pings are short ping_line() messages that link here.
        """
        starts = parse_iso(session.get("starts_at"))
        host = session["host_id"]
        upcoming = bool(starts) and not ended and not session.get("started")
        zone, tz_hint = tz_note_parts(session["tz_note"]) if session.get("tz_note") and upcoming else (None, None)
        blocks = []
        if starts:   # Discord shows both stamps in each reader's own timezone
            voice_id = (session.get("event") or {}).get("voice_id")
            blocks.append(ui.two_line(f"**{stamp(starts)}**", details(
                stamp(starts, "R"), repeat_short(session["repeat"]) if session.get("repeat") else None,
                f"time read as {zone}" if zone else "your local time", f"in <#{voice_id}>" if voice_id else None)))
        players = [f"<@{uid}> (host)" if uid == host else f"<@{uid}>" for uid in session["participants"]]
        if len(players) > 40:
            players = players[:40] + [f"and {len(players) - 40} more"]
        count = len(session["participants"])
        who_main = f"**{count} {'played' if ended else 'playing'}**" if count else "**Nobody yet**"
        blocks.append(ui.two_line(who_main, ", ".join(players) or None))
        if session.get("game"):   # set ahead (a Star Citizen night): no vote
            blocks.append(ui.two_line(f"**{'Played' if ended else 'Playing'} {session['game']['name']}**",
                                      None if ended else "Set ahead, so there's no vote"))
        if session.get("reminder_note") and not ended:
            blocks.append(ui.two_line("**Before you play**", session["reminder_note"]))
        if session.get("replaces_titles") and upcoming:
            blocks.append(ui.two_line(f"**Replaces {name_list(session['replaces_titles'])}**",
                                      "That night's regular session is off"))
        title = f"🎮 {session['title']}"
        banner = (session.get("event") or {}).get("cover_url")   # the Discord event's banner, full width on top

        if vote is not None and vote.get("in_card") and not ended:   # voting: the options are in this card
            # How to vote is in the private reply to a vote button, so the card stays short and has no footer.
            return ui.CardView(ui.card(*blocks, ui.SEPARATOR, self.vote_status(vote, guild), vote_buttons(vote),
                                       ui.SEPARATOR, [SessionButton("end", session["id"])],
                                       title=title, color=ui.ATTENTION, banner=banner))

        # Every winner this session, in order; sessions from before the history only know the last one.
        winners = session.get("winners") or ([session["winner"]] if session.get("winner") else [])
        result = session.get("vote_result")
        result_block = None
        if result and not ended:
            if result.get("winner"):
                head = f"🏆 **{result['winner']}** won the vote."
                earlier = winners[:-1] if winners and winners[-1] == result["winner"] else winners
            else:
                head = "🗳️ **The vote ended without any votes.**"
                earlier = winners
            lines = ([result["tie"]] if result.get("tie") else []) + result.get("lines", [])
            lines += [result["footer"]] if result.get("footer") else []
            lines += [f"Earlier: {played_text(earlier)}"] if earlier else []
            result_block = ui.two_line(head, "\n".join(lines) or None)
        elif winners:
            earlier = winners[:-1]
            blocks.append(ui.two_line(f"🏆 **{winners[-1]}** won the {'last ' if earlier else ''}vote.",
                                      f"Earlier: {played_text(earlier)}" if earlier else None))
        if ended:
            footer = (f"Replaced by {session['replaced_by']} this time." if session.get("replaced_by")
                      else "This session has ended.")
            return ui.CardView(ui.card(*blocks, title=title, color=ui.MUTED, footer=footer, banner=banner))
        if session.get("vote_id"):   # a vote posted as its own card (sessions from before Phase 4 / old votes)
            blocks.append("🗳️ Voting now: pick a game on the vote below.")
        if tz_hint:   # the host's time may have been read in the wrong timezone: that's the one hint until it starts
            footer = tz_hint
        else:
            notes = []
            if upcoming:
                left = [lead for lead in session_leads(session) if lead not in sent_leads(session)]
                notes.append(f"{'reminder' if len(left) == 1 else 'reminders'} {leads_text(left)}" if left
                             else "players are pinged when it starts")
            if session.get("event_id"):
                notes.append("on the server's events")
            if not (starts or session.get("vote_id") or session.get("winner") or session.get("vote_result")
                    or session.get("game")):
                notes.append("when everyone's in, the host presses Start vote")
            footer = details(*notes) or None
        buttons = session_buttons(session["id"], bool(starts), vote=not session.get("game"), plan=plans_next(session))
        return ui.CardView(ui.card(*blocks, ui.SEPARATOR if result_block else None, result_block,
                                   ui.SEPARATOR, buttons,
                                   title=title, color=ui.SUCCESS, footer=footer, banner=banner))

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

    async def session_card_now(self, guild: discord.Guild, session: dict, ended: bool = False) -> ui.CardView:
        """session_card with the session's running vote looked up (so a vote inside the card is drawn)."""
        vote = None
        if session.get("vote_id") and not ended:
            vote = (await self.config.guild(guild).votes()).get(session["vote_id"])
        return self.session_card(session, ended, vote, guild)

    async def refresh_session_message(self, guild: discord.Guild, session: dict, ended: bool = False):
        view = await self.session_card_now(guild, session, ended) if session.get("card") else None
        await self._edit_record(guild, session, lambda: view,
                                embed=self.session_embed(session, ended),
                                view=None if ended else session_view(session["id"]))

    def session_link(self, guild: discord.Guild, session: dict) -> str:
        return message_link(guild.id, session.get("channel_id"), session.get("message_id"))

    async def calendar_files(self, guild: discord.Guild, session: dict) -> List[Tuple[str, bytes]]:
        """
        (filename, .ics) for a scheduled session, plus one that repeats when it comes from a schedule. Times, place
        and length match its Discord event.
        """
        starts = parse_iso(session.get("starts_at"))
        if starts is None:
            return []
        fields = await self._event_fields(guild, session)
        end = fields.get("end_time") or starts + timedelta(hours=EVENT_LENGTH_HOURS)
        place = fields["channel"].name if fields.get("channel") is not None else fields.get("location", "")
        link = self.session_link(guild, session)
        title = f"{session['title']} ({guild.name})"
        description = fields["description"]
        files = [(ics_filename(session["title"]),
                  ics_calendar(f"session-{session['id']}", title, starts, end, description=description,
                               location=place, url=link))]
        schedule = (await self.config.guild(guild).recurring()).get(session.get("recurring_id") or "")
        if schedule is not None:
            files.append((ics_filename(f"{schedule.get('title') or session['title']} every time"),
                          ics_calendar(f"schedule-{schedule['id']}", title, starts, end, description=description,
                                       location=place, url=link, rrule=schedule_rrule(schedule),
                                       tz_name=schedule["tz"])))
        return files

    async def send_calendar(self, interaction: discord.Interaction, session: dict):
        """Add to calendar: the session (and its schedule) as .ics files, privately."""
        files = await self.calendar_files(interaction.guild, session)
        if not files:
            return await ui.respond(interaction, ui.line(ui.ASK, "This session has no start time to add."))
        text = ui.line(None, f"🗓️ **{session['title']}** for your calendar: open the file, or import it.",
                       hint=("The second file adds every night on the schedule; nights that get skipped or replaced "
                             "still show there. " if len(files) > 1 else "")
                       + "Google Calendar imports them under Settings → Import & export.")
        await ui.respond(interaction, text, files=[discord.File(io.BytesIO(data), filename=name)
                                                   for name, data in files])

    async def create_session(self, target: Target, text: Optional[str], details: Optional[dict] = None):
        """
        Start a session from text like "friday 9pm Raid night". `details` are its Discord event's (description,
        minutes, voice_id, banner_data); from a text command, an attached image is the banner and a mentioned voice
        channel is where it happens.
        """
        guild, member, channel = who(target)
        if details is None:
            details, text = await self.details_from_message(target, text)
            if details is None:
                return
        details = dict(details)
        settings = await self.resolve_settings(target, details.pop("settings", None))
        if settings is None:
            return
        tz, tz_name, personal = await self.timezone_for(member)
        now = utcnow()
        if (text or "").strip().lower().split(" ")[0] in ("every", "weekly", "monthly"):
            return await self.create_recurring(target, text, details, settings)
        starts_at, title = split_when(text or "", tz, now)
        if starts_at is not None and starts_at < now - timedelta(minutes=1):
            return await self.reply(target, content="⚠️ That time has already passed. Try a later time.", ephemeral=True)
        if starts_at is not None and starts_at > now + timedelta(days=MAX_AHEAD_DAYS):
            return await self.reply(target, ephemeral=True,
                                    content=f"⚠️ Sessions can be scheduled up to {MAX_AHEAD_DAYS} days ahead.")
        title = (title.strip() or f"{member.display_name}'s game session")[:200]
        note = None
        if starts_at and not personal:   # a hint in the card, instead of a message of its own
            note = (f"Time read as **{tz_name}**: the host hasn't set a timezone. If that's wrong, set one with "
                    f"{await self.cmd(guild, 'games timezone <zone>')} and start the session again.")
        session = await self.post_session(guild, channel, member, title, starts_at, tz_note=note, details=details,
                                          settings=settings)
        if starts_at:
            await self.settle_replacements(target, settings, session=session)
        missed = details and not starts_at
        if missed:
            await self.reply(target, ephemeral=True, content=ui.line(
                ui.WARN, "The event details weren't used: only a session with a start time gets a Discord event."))
        elif details and not session.get("event_id"):
            await self.reply(target, ephemeral=True, content=ui.line(
                ui.WARN, "The details are saved, but I couldn't make a Discord event.",
                hint="Events need to be on (`games admin events`) and I need Manage Events."))
        elif isinstance(target, discord.Interaction):
            await self.reply(target, content="✅ Session posted.", ephemeral=True)

    async def post_session(self, guild: discord.Guild, channel, host: discord.Member, title: str,
                           starts_at: Optional[datetime], schedule: Optional[dict] = None, *,
                           tz_note: Optional[str] = None, details: Optional[dict] = None,
                           settings: Optional[dict] = None, pending: bool = False, booked: bool = False) -> dict:
        """
        Post a session card (and its Discord event when it has a start time). Returns the session. `tz_note` is a
        hint shown in the card until the session starts (the time was read in a timezone the host didn't choose).
        `details` are the event's (a repeating session's come from its schedule); new banner bytes in
        "banner_data" are saved under the session's ID. `settings` are its game, reminders, reminder note and
        what it replaces (a repeating session's come from its schedule; reminders default to the server's).
        `pending` makes the session and its event now and posts the card later (session_loop: a day ahead, or at
        its earliest reminder). `booked` marks a date added with Plan next, on top of its schedule's own.
        """
        now = utcnow()
        sid = generate_id()
        event_details = self.store_details(sid, details if details is not None
                                           else (schedule or {}).get("event"))
        settings = dict(settings or {})
        if schedule is not None:
            settings = {**{key: schedule[key] for key in SETTING_KEYS if key in schedule}, **settings}
        if "reminders" not in settings:
            settings["reminders"] = list(await self.config.guild(guild).reminders())
        session = {
            "id": sid, "title": title, "host_id": str(host.id), "participants": [str(host.id)],
            "channel_id": channel.id, "message_id": None, "created_at": now.isoformat(),
            "starts_at": starts_at.isoformat() if starts_at else None,
            "reminders": settings["reminders"],   # minutes before the start, latest first
            # A reminder whose time has already come when the session is set up is skipped, not sent.
            "reminders_sent": passed_leads(settings["reminders"], starts_at, now) if starts_at else [],
            "reminder_note": settings.get("reminder_note"),
            "game": settings.get("game"),               # {id, name} when it's set ahead: no vote
            "replaces": list(settings.get("replaces") or []),     # schedule IDs whose session that night is off
            "replaces_titles": list(settings.get("replaces_titles") or []),
            "started": False, "vote_id": None, "winner": None, "event_id": None,
            "recurring_id": schedule["id"] if schedule else None,
            "repeat": repeat_label(schedule) if schedule else None,
            "booked": booked,
            "pending": pending,   # its card isn't posted yet
            "card": True,   # posted as a card (older sessions are embeds and are still edited as embeds)
            "tz_note": tz_note,
            "pings": [],          # IDs of this session's ping lines (in its channel), deleted when it ends
            "vote_result": None,  # the last vote's result, shown in the card: {winner, tie, lines, footer}
            "winners": [],        # every vote's winner, in order (a vote can keep the current game: it's listed again)
            "event": event_details,   # the Discord event's details: {description, minutes, voice_id, banner}
        }
        async with self.config.guild(guild).play_sessions() as sessions:
            sessions[sid] = session
        if not pending:
            message = await self.send_card(channel, self.session_card(session, guild=guild))   # names the host, no ping
            session["message_id"] = message.id
        session["event_id"] = await self.create_event(guild, session, host)
        async with self.config.guild(guild).play_sessions() as sessions:
            if sid in sessions:
                sessions[sid].update(message_id=session["message_id"], event_id=session["event_id"],
                                     event=session["event"])
        if session["event_id"] and not pending:
            await self.refresh_session_message(guild, session)
        return session

    async def post_pending(self, guild: discord.Guild, session: dict, ping: bool) -> Optional[dict]:
        """
        Post the card of a session made ahead of time. With `ping`, the card is a reminder: it pings everyone who
        joined (by pressing Interested on the event, or `games join`). Its event then links to the card.
        """
        channel = guild.get_channel_or_thread(session["channel_id"])
        if channel is None:
            return None
        current = dict(session, pending=False)
        try:
            message = await self.send_card(channel, await self.session_card_now(guild, current),
                                           allowed_mentions=pings(current["participants"]) if ping else None)
        except discord.HTTPException as e:
            log.info("Couldn't post session %s: %s", session["id"], e)
            return None
        async with self.config.guild(guild).play_sessions() as sessions:
            saved = sessions.get(session["id"])
            if saved is not None:
                saved.update(message_id=message.id, pending=False)
                current = dict(saved)
        if saved is None:   # it ended meanwhile
            await self._delete_messages(guild, channel.id, [message.id])
            return None
        if current.get("event_id"):
            await self.push_event(guild, current)   # the event's description now links to the card
        return current

    # ---------- Discord events ----------

    async def create_event(self, guild: discord.Guild, session: dict, host: discord.Member) -> Optional[int]:
        """List a scheduled session in the server's Events, so Discord shows it and reminds interested people."""
        starts = parse_iso(session.get("starts_at"))
        conf = self.config.guild(guild)
        if starts is None or starts <= utcnow() + timedelta(minutes=1) or not await conf.events():
            return None
        if not guild.me.guild_permissions.manage_events:
            return None
        kwargs = await self._event_fields(guild, session)
        if kwargs.get("entity_type") == discord.EntityType.external:
            kwargs.pop("channel", None)   # (only an edit needs channel=None to move an event out of voice)
        if kwargs.get("end_time") is None:
            kwargs.pop("end_time", None)   # open-ended (voice events only)
        banner = self.banner_bytes((session.get("event") or {}).get("banner"))
        if banner:
            kwargs["image"] = banner
        try:
            event = await guild.create_scheduled_event(name=session["title"][:100], start_time=starts,
                                                       privacy_level=discord.PrivacyLevel.guild_only, **kwargs)
        except discord.HTTPException as e:
            log.info("Couldn't create a Discord event for session %s: %s", session["id"], e)
            return None
        if cover_url(event):   # the card shows Discord's copy of the banner; the caller saves the session
            session.setdefault("event", {})["cover_url"] = cover_url(event)
        return event.id

    async def _event_fields(self, guild: discord.Guild, session: dict) -> dict:
        """
        A session's Discord event description, place and end time, from its details: the host's description
        first, then how to join; its voice channel, else the server's event channel, else the text channel as an
        "external" location (which Discord requires an end time for).
        """
        starts = parse_iso(session["starts_at"])
        details = session.get("event") or {}
        host = guild.get_member(int(session["host_id"]))
        link = self.session_link(guild, session)
        note = (f"Hosted by {host.display_name if host else 'a member'}. Press Interested to join the session"
                + (f": {link}" if link else ".") + (f"\n{session['repeat']}." if session.get("repeat") else ""))
        custom = (details.get("description") or "").strip()
        description = f"{ui.truncate(custom, 1000 - len(note) - 2)}\n\n{note}" if custom else note
        minutes = details.get("minutes")
        end = starts + timedelta(minutes=minutes) if minutes else None
        voice = guild.get_channel(details.get("voice_id") or await self.config.guild(guild).event_channel() or 0)
        if isinstance(voice, (discord.VoiceChannel, discord.StageChannel)):
            return {"description": description[:1000], "channel": voice, "end_time": end}
        channel = guild.get_channel_or_thread(session["channel_id"])
        return {"description": description[:1000], "entity_type": discord.EntityType.external, "channel": None,
                "end_time": end or starts + timedelta(hours=EVENT_LENGTH_HOURS),
                "location": f"#{channel.name}" if channel else "Discord"}

    # ---------- event details ----------

    def _banner_dir(self) -> Path:
        path = cog_data_path(self) / "banners"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def store_details(self, owner: str, details: Optional[dict]) -> dict:
        """
        Clean event details for saving: new banner bytes ("banner_data") are written to banners/<owner>.<ext>,
        and the details keep the file's name. Returns {description, minutes, voice_id, banner}.
        """
        details = dict(details or {})
        data = details.pop("banner_data", None)
        if data:
            ext = image_ext(data)
            for old in self._banner_dir().glob(f"{owner}.*"):
                old.unlink(missing_ok=True)
            (self._banner_dir() / f"{owner}.{ext}").write_bytes(data)
            details["banner"] = f"{owner}.{ext}"
        return {key: details.get(key) for key in ("description", "minutes", "voice_id", "banner")
                if details.get(key)}

    def banner_bytes(self, name: Optional[str]) -> Optional[bytes]:
        if not name:
            return None
        try:
            return (self._banner_dir() / name).read_bytes()
        except OSError:
            return None

    def drop_banner(self, name: Optional[str], owner: str):
        """Delete a banner file, if it belongs to `owner` (a session can use its schedule's, which stays)."""
        if name and name.startswith(f"{owner}."):
            (self._banner_dir() / name).unlink(missing_ok=True)

    @staticmethod
    async def read_banner(attachment: discord.Attachment) -> Tuple[Optional[bytes], Optional[str]]:
        """An uploaded banner's bytes, or (None, a line saying what's wrong)."""
        if attachment.size > MAX_BANNER_BYTES:
            return None, ui.line(ui.FAIL, "That banner is too big.", hint="Event banners can be up to 10 MB.")
        try:
            data = await attachment.read()
        except discord.HTTPException:
            return None, ui.line(ui.FAIL, "I couldn't download that banner.", hint="Try uploading it again.")
        if image_ext(data) is None:
            return None, ui.line(ui.FAIL, "That banner isn't an image I can use.", hint="Use a PNG, JPG, GIF or WebP.")
        return data, None

    async def details_from_message(self, target: Target, text: Optional[str]) -> Tuple[Optional[dict], Optional[str]]:
        """
        Event details from a text command: lines after the first are the description, except a "Length: 3h" line,
        which is how long the event runs, and the setting lines "Game:", "Reminders:", "Reminder note:" and
        "Replaces:" (kept under "settings", unchecked: resolve_settings reads them). An attached image is the
        banner, and a mentioned voice channel (taken out of the text) is the place. Returns (details, the first
        line without the mention), or (None, None) after explaining a bad banner, length or reminder.
        """
        if isinstance(target, discord.Interaction):
            return {}, text
        guild = target.guild
        details: dict = {}
        first, _, rest = (text or "").strip().partition("\n")
        description, settings = [], {}
        for line in rest.split("\n"):
            setting = SETTING_LINE_RE.match(line)
            if setting is not None:
                name, value = setting.group(1).lower(), setting.group(2)
                if name in ("reminder", "reminders"):
                    leads = parse_reminders(value)
                    if leads is None:
                        await self.reply(target, content=ui.line(
                            ui.ASK, f"I couldn't use **{ui.truncate(value, 30)}** as reminders.",
                            hint="Try Reminders: 36h, 15m (up to 4, from 5 minutes to 7 days before), or none."))
                        return None, None
                    settings["reminders"] = leads
                elif name == "reminder note":
                    settings["reminder_note"] = value[:MAX_NOTE] or None
                elif name == "game":
                    settings["game_name"] = value
                else:
                    settings["replaces_names"] = value
                continue
            match = LENGTH_LINE_RE.match(line)
            minutes = parse_length(match.group(2)) if match else None
            if match is None or (minutes is None and not match.group(1)):   # "Duration of the raid…" is description
                description.append(line)
                continue
            if minutes is None or not EVENT_MIN_MINUTES <= minutes <= EVENT_MAX_MINUTES:
                await self.reply(target, content=ui.line(
                    ui.ASK, f"I couldn't use **{ui.truncate(match.group(2), 20)}** as a length.",
                    hint="Try Length: 2h, 90m or 1h30m, between 15 minutes and a day."))
                return None, None
            details["minutes"] = minutes
        if "\n".join(description).strip():
            details["description"] = "\n".join(description).strip()[:800]
        if rest.strip():
            text = first
        for match in re.finditer(r"<#(\d+)>", text or ""):
            channel = guild.get_channel(int(match.group(1)))
            if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                details["voice_id"] = channel.id
                text = " ".join((text or "").replace(match.group(0), " ").split())
                break
        message = getattr(target, "message", None)
        image = next((a for a in (message.attachments if message is not None else [])
                      if (a.content_type or "").startswith("image/")
                      or a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))), None)
        if image is not None:
            data, problem = await self.read_banner(image)
            if problem:
                await self.reply(target, content=problem)
                return None, None
            details["banner_data"] = data
        if settings:
            details["settings"] = settings
        return details, text

    async def resolve_settings(self, target: Target, raw: Optional[dict]) -> Optional[dict]:
        """
        Check typed settings: the game against the library, and what it replaces against the server's schedules
        (by name or ID; "none" for nothing, which also skips the question). Returns the settings to save
        ({game, reminders, reminder_note, replaces, replaces_titles}, only those given), or None after saying
        what's wrong.
        """
        guild = who(target)[0]
        raw = dict(raw or {})
        settings = {key: raw[key] for key in ("reminders", "reminder_note") if key in raw}
        if raw.get("game_name") is not None:
            name = raw["game_name"].strip()
            if name and name.lower() not in NO_WORDS:
                game, candidates = resolve_game(await self.config.guild(guild).games(), name)
                if game is None:
                    await self.reply(target, ephemeral=True,
                                     content=NOT_IN_LIBRARY + describe_unresolved(name, candidates))
                    return None
                settings["game"] = {"id": game["id"], "name": game["name"]}
            else:
                settings["game"] = None
        if raw.get("replaces_names") is not None:
            names = [n.strip() for n in re.split(r"\s*[,;]\s*", raw["replaces_names"]) if n.strip()]
            schedules = list((await self.config.guild(guild).recurring()).values())
            rids, titles = [], []
            for name in names:
                if name.lower() in NO_WORDS:
                    continue
                schedule = find_schedule(schedules, name)
                if schedule is None:
                    await self.reply(target, ephemeral=True, content=ui.line(
                        ui.ASK, f"There's no repeating session called **{ui.truncate(name, 60)}**.",
                        hint=f"See them with {await self.cmd(guild, 'games recurring')}."))
                    return None
                rids.append(schedule["id"])
                titles.append(schedule["title"])
            settings["replaces"], settings["replaces_titles"] = rids, titles
        return settings

    # ---------- the Edit menu ----------

    async def open_edit_menu(self, interaction: discord.Interaction, session: dict):
        """The card's Edit button: the host (or a game admin) gets every setting of the session, privately."""
        if not parse_iso(session.get("starts_at")):
            return await ui.respond(interaction, ui.line(ui.WARN, "Only a session with a start time can be edited.",
                                                         hint="Start one with a time to set reminders and an event."))
        schedule = None
        if session.get("recurring_id"):
            schedule = (await self.config.guild(interaction.guild).recurring()).get(session["recurring_id"])
        tz, tz_name, _ = await self.timezone_for(interaction.user)
        menu = SessionEditMenu(self, interaction.user.id, session, schedule, tz, tz_name)
        await self.send_card(interaction, menu, ephemeral=True)
        menu.message = interaction

    async def _editable(self, guild: discord.Guild, member: discord.Member, sid: str) -> Tuple[Optional[dict], str]:
        """(the session, "") if `member` may change it, else (None, a line saying why not)."""
        session = (await self.config.guild(guild).play_sessions()).get(sid)
        if session is None:
            return None, "⚠️ This session has ended."
        if not await self.can_manage(member, session["host_id"]):
            return None, "🔒 Only the host or a game admin can do that."
        return session, ""

    async def save_settings(self, guild: discord.Guild, member: discord.Member, sid: str, changes: dict,
                            future: bool, done: str) -> str:
        """
        Save a session's game, reminders, reminder note or what it replaces. With `future`, its schedule (so later
        sessions) and its other sessions not started yet get them too. Returns a line for the person.
        """
        session, problem = await self._editable(guild, member, sid)
        if session is None:
            return problem
        rid = session.get("recurring_id") if future else None
        now = utcnow()
        changed, dropped = [], {}
        async with self.config.guild(guild).play_sessions() as sessions:
            for s in sessions.values():
                if s["id"] == sid or (rid and s.get("recurring_id") == rid and not s.get("started")):
                    if "replaces" in changes:   # nights it no longer replaces come back
                        dropped[s["id"]] = [r for r in s.get("replaces") or [] if r not in changes["replaces"]]
                    s.update(changes)
                    if "reminders" in changes:   # reminders already due aren't sent late
                        s["reminders_sent"] = passed_leads(changes["reminders"], parse_iso(s.get("starts_at")), now)
                        s.pop("reminded", None)
                    changed.append(dict(s))
        if rid:
            async with self.config.guild(guild).recurring() as recurring:
                if rid in recurring:
                    recurring[rid].update(changes)
        for s in changed:
            if "replaces" in changes:
                await self.apply_replacements(guild, s)
                starts = parse_iso(s.get("starts_at"))
                if dropped.get(s["id"]) and not s.get("started") and starts and starts > now:
                    await self._restore_replaced(guild, {**s, "replaces": dropped[s["id"]]})
            await self.refresh_session_message(guild, s)
        return ui.line(ui.DONE, done + (" Future sessions use it too." if rid else ""))

    async def save_game(self, guild: discord.Guild, member: discord.Member, sid: str, name: str,
                        future: bool) -> str:
        """The Game form: set the game ahead (no vote), or empty to vote as usual."""
        game = None
        if name.strip():
            game, candidates = resolve_game(await self.config.guild(guild).games(), name)
            if game is None:
                return NOT_IN_LIBRARY + describe_unresolved(name, candidates)
        session = (await self.config.guild(guild).play_sessions()).get(sid) or {}
        if game is not None and session.get("vote_id"):
            return ui.line(ui.WARN, "A vote is running.", hint="Set the game after it ends.")
        return await self.save_settings(guild, member, sid, {"game": {"id": game["id"], "name": game["name"]}
                                                             if game else None}, future,
                                        f"Playing **{game['name']}**: no vote." if game else
                                        "No set game: the host starts a vote as usual.")

    async def save_replaces(self, guild: discord.Guild, member: discord.Member, sid: str, rids: List[str],
                            future: bool) -> str:
        """The Replaces form: which schedules' nights this one takes over."""
        schedules = await self.config.guild(guild).recurring()
        rids = [r for r in rids if r in schedules]
        titles = [schedules[r]["title"] for r in rids]
        line = await self.save_settings(guild, member, sid, {"replaces": rids, "replaces_titles": titles}, future,
                                        f"Replaces {name_list([f'**{t}**' for t in titles])} on the same night."
                                        if titles else "Replaces nothing.")
        return line

    async def save_title_time(self, guild: discord.Guild, member: discord.Member, sid: str, title: str,
                              when: str, future: bool) -> str:
        """The Title and time form. A new time moves the reminders and the Discord event; with `future`, the
        schedule's title and its day and time of day change too."""
        session, problem = await self._editable(guild, member, sid)
        if session is None:
            return problem
        title = (title.strip() or session["title"])[:200]
        starts = parse_iso(session.get("starts_at"))
        new_start = starts
        if when.strip():
            tz, _, _ = await self.timezone_for(member)
            new_start = parse_when(when, tz, utcnow())
            if new_start is None:
                return ui.line(ui.ASK, f"I couldn't read the time **{ui.truncate(when, 40)}**.",
                               hint="Try friday 9pm, 11/20 8pm or tomorrow 8:30pm.")
        moved = new_start is not None and starts is not None and abs((new_start - starts).total_seconds()) >= 60
        if moved and session.get("started"):
            return ui.line(ui.WARN, "This session has already started, so its time can't change.")
        if moved and not utcnow() < new_start < utcnow() + timedelta(days=MAX_AHEAD_DAYS):
            return ui.line(ui.ASK, "Pick a time in the next 60 days.")
        rid = session.get("recurring_id") if future else None
        async with self.config.guild(guild).play_sessions() as sessions:
            saved = sessions.get(sid)
            if saved is None:
                return "⚠️ This session has ended."
            saved["title"] = title
            if moved:
                saved["starts_at"] = new_start.isoformat()
                saved["reminders_sent"] = passed_leads(session_leads(saved), new_start, utcnow())
                saved.pop("reminded", None)
            session = dict(saved)
        if rid:
            async with self.config.guild(guild).recurring() as recurring:
                schedule = recurring.get(rid)
                if schedule is not None:
                    schedule["title"] = title
                    if moved:
                        local = new_start.astimezone(load_zone(schedule["tz"]))
                        schedule.update(weekday=local.weekday(), hour=local.hour, minute=local.minute)
                        schedule["next_start"] = first_occurrence(schedule, new_start + timedelta(hours=1)).isoformat()
                        session["repeat"] = repeat_label(schedule)
            async with self.config.guild(guild).play_sessions() as sessions:
                if sid in sessions:
                    sessions[sid]["repeat"] = session.get("repeat")
        problem = await self.push_event(guild, session) if session.get("event_id") else None
        await self.refresh_session_message(guild, session)
        line = ui.line(ui.DONE, "Saved." + (" Future sessions use it too." if rid else ""))
        return ui.line(ui.WARN, "Saved, but " + problem) if problem else line

    async def apply_event_details(self, interaction: discord.Interaction, sid: str, *, description: str, length: str,
                                  voice_ids: List[int], banners: List[discord.Attachment], options: List[str],
                                  menu: Optional["SessionEditMenu"] = None):
        """The Event details form: save it, then redraw the Edit menu (or answer privately)."""
        if menu is not None:
            await interaction.response.defer()
        else:
            await interaction.response.defer(ephemeral=True, thinking=True)   # banners take a moment to download
        line = await self.save_event_details(interaction.guild, interaction.user, sid, description=description,
                                             length=length, voice_ids=voice_ids, banners=banners, options=options)
        if menu is not None:
            return await menu.saved(interaction, line)
        await interaction.followup.send(line, ephemeral=True)

    async def save_event_details(self, guild: discord.Guild, member: discord.Member, sid: str, *, description: str,
                                 length: str, voice_ids: List[int], banners: List[discord.Attachment],
                                 options: List[str]) -> str:
        """Save event details, update the Discord event (or make it), and redraw the card. Returns a line."""
        session, problem = await self._editable(guild, member, sid)
        if session is None:
            return problem
        minutes = None
        if length.strip():
            minutes = parse_length(length)
            if minutes is None or not EVENT_MIN_MINUTES <= minutes <= EVENT_MAX_MINUTES:
                return ui.line(ui.ASK, f"I couldn't use **{ui.truncate(length, 20)}** as a length.",
                               hint="Try 2h, 90m or 1h30m, between 15 minutes and a day.")
        future = "future" in options and session.get("recurring_id")
        owner = session["recurring_id"] if future else sid
        old = session.get("event") or {}
        details = {"description": description.strip() or None, "minutes": minutes,
                   "voice_id": voice_ids[0] if voice_ids else None, "banner": old.get("banner")}
        image_change = False
        if banners:
            data, problem = await self.read_banner(banners[0])
            if problem:
                return problem
            details["banner_data"] = data
            image_change = True
        elif "remove" in options:
            self.drop_banner(old.get("banner"), sid)
            details["banner"] = None
            image_change = True
        details = self.store_details(owner, details)
        async with self.config.guild(guild).play_sessions() as sessions:
            if sid not in sessions:
                return "⚠️ This session has ended."
            # The banner's link stays until push_event hears from Discord what the event shows now.
            sessions[sid]["event"] = {**details, **({"cover_url": old["cover_url"]} if old.get("cover_url") else {})}
            session = dict(sessions[sid])
        if future:
            async with self.config.guild(guild).recurring() as recurring:
                if session["recurring_id"] in recurring:
                    recurring[session["recurring_id"]]["event"] = dict(details)
        problem = await self.push_event(guild, session, image_change)
        await self.refresh_session_message(guild, (await self.config.guild(guild).play_sessions()).get(sid, session))
        if problem:
            return ui.line(ui.WARN, "The details are saved, but " + problem)
        return ui.line(ui.DONE, "Event details saved." + (" Future sessions use them too." if future else ""))

    async def draw_banner(self, guild: discord.Guild, member: discord.Member, sid: str, idea: str,
                          future: bool) -> str:
        """Have Gemini draw the event's banner, then save it like an uploaded one. Returns a line."""
        session, problem = await self._editable(guild, member, sid)
        if session is None:
            return problem
        gemini = self.bot.get_cog("GeminiChat")
        if gemini is None or not hasattr(gemini, "render_image"):
            return ui.line(ui.WARN, "Drawing a banner needs image generation, which isn't running.",
                           hint="Upload your own in Event details instead.")
        game = (session.get("game") or {}).get("name")
        prompt = (f"A wide, eye-catching event banner, about two and a half times as wide as it is tall, for a game "
                  f"night called \"{session['title']}\"" + (f" playing {game}" if game else "")
                  + (f". It shows: {' '.join(idea.split())}" if idea.strip() else "")
                  + ". Bold colors and a clear focal point. No text, letters, words, logos or watermarks anywhere.")
        channel = guild.get_channel_or_thread(session["channel_id"]) or guild.text_channels[0]
        data, error = await gemini.render_image(prompt, channel=channel)
        if data is None:
            return error
        if image_ext(data) is None:
            return ui.line(ui.FAIL, "Gemini's picture wasn't one Discord takes as a banner. Try again.")
        future = future and bool(session.get("recurring_id"))
        owner = session["recurring_id"] if future else sid
        old = session.get("event") or {}
        details = self.store_details(owner, {**{k: v for k, v in old.items() if k != "cover_url"}, "banner_data": data})
        async with self.config.guild(guild).play_sessions() as sessions:
            if sid not in sessions:
                return "⚠️ This session has ended."
            sessions[sid]["event"] = details
            session = dict(sessions[sid])
        if future:
            async with self.config.guild(guild).recurring() as recurring:
                if session["recurring_id"] in recurring:
                    recurring[session["recurring_id"]]["event"] = dict(details)
        problem = await self.push_event(guild, session, True)
        await self.refresh_session_message(guild, (await self.config.guild(guild).play_sessions()).get(sid, session))
        if problem:
            return ui.line(ui.WARN, "The banner is drawn and saved, but " + problem)
        return ui.line(ui.DONE, "New banner drawn." + (" Future sessions use it too." if future else ""),
                       hint="Not quite right? Draw it again, or upload your own in Event details.")

    # ---------- Plan next ----------

    def plan_dates(self, schedule: dict, sessions: dict, now: datetime) -> List[datetime]:
        """The next PLAN_CHOICES nights on the schedule's weekday and time, without ones it already has."""
        tz = load_zone(schedule["tz"])
        start = next_weekly(schedule["weekday"], (schedule["hour"], schedule["minute"]), tz, now)
        window = timedelta(hours=REPLACE_WINDOW_HOURS)
        taken = [parse_iso(s["starts_at"]) for s in sessions.values()
                 if s.get("recurring_id") == schedule["id"] and s.get("starts_at")]
        upcoming = parse_iso(schedule.get("next_start"))
        dates = []
        while len(dates) < PLAN_CHOICES and start - now < timedelta(days=MAX_AHEAD_DAYS):
            if not any(t and abs(t - start) < window for t in taken) and not (
                    upcoming and abs(upcoming - start) < window):
                dates.append(start)
            local = start.astimezone(tz).date() + timedelta(days=7)
            start = datetime(local.year, local.month, local.day, schedule["hour"], schedule["minute"],
                             tzinfo=tz).astimezone(timezone.utc)
        return dates

    async def open_plan_next(self, interaction: discord.Interaction, session: dict):
        """Plan next (the card's button, or the Edit menu's): pick a date for another of this schedule's nights."""
        schedule = (await self.config.guild(interaction.guild).recurring()).get(session.get("recurring_id") or "")
        if schedule is None:
            return await ui.respond(interaction, ui.line(ui.ASK, "This session doesn't repeat any more."))
        if not await self.can_manage(interaction.user, schedule["host_id"]) and \
                not await self.can_manage(interaction.user, session["host_id"]):
            return await ui.respond(interaction, "🔒 Only the host or a game admin can do that.")
        dates = self.plan_dates(schedule, await self.config.guild(interaction.guild).play_sessions(), utcnow())
        if not dates:
            return await ui.respond(interaction, ui.line(ui.ASK, "There's no free date in the next 60 days."))
        view = PlanNextView(self, interaction.user.id, schedule, dates)
        await self.send_card(interaction, view, ephemeral=True)
        view.message = interaction

    async def book_night(self, guild: discord.Guild, member: discord.Member, rid: str, start: datetime) -> str:
        """Add a night to a schedule (Plan next): its session and event now, its card when it's near. A line."""
        schedule = (await self.config.guild(guild).recurring()).get(rid)
        if schedule is None:
            return ui.line(ui.ASK, "That repeating session was stopped.")
        if not await self.can_manage(member, schedule["host_id"]):
            return "🔒 Only the host or a game admin can do that."
        now = utcnow()
        if not now < start < now + timedelta(days=MAX_AHEAD_DAYS):
            return ui.line(ui.ASK, "Pick a date in the next 60 days.")
        window = timedelta(hours=REPLACE_WINDOW_HOURS)
        sessions = await self.config.guild(guild).play_sessions()
        if any(s.get("recurring_id") == rid and parse_iso(s.get("starts_at"))
               and abs(parse_iso(s["starts_at"]) - start) < window for s in sessions.values()):
            return ui.line(ui.WARN, f"**{schedule['title']}** is already on that night.")
        session = await self._create_occurrence(guild, schedule, start, booked=True)
        if session is None:
            return ui.line(ui.FAIL, "I couldn't set that up.",
                           hint="Check the schedule's channel and host are still here.")
        extra = " Its Discord event is up now." if session.get("event_id") else ""
        return ui.line(ui.DONE, f"**{schedule['title']}** is on {stamp(start)}.{extra}",
                       hint="The card is posted before it like the others.")

    async def push_event(self, guild: discord.Guild, session: dict, image_change: bool = False) -> Optional[str]:
        """
        Bring a session's Discord event in line with its details, making the event if it should have one.
        Returns what went wrong (the end of a sentence for the host), or None.
        """
        if not session.get("event_id"):
            host = guild.get_member(int(session["host_id"])) or guild.me
            event_id = await self.create_event(guild, session, host)
            if event_id is None:
                return ("there's no Discord event to update. Events need to be on (`games admin events`) and I "
                        "need Manage Events.")
            async with self.config.guild(guild).play_sessions() as sessions:
                if session["id"] in sessions:
                    sessions[session["id"]].update(event_id=event_id, event=session.get("event") or {})
            return None
        try:
            event = guild.get_scheduled_event(session["event_id"]) or await guild.fetch_scheduled_event(
                session["event_id"])
            kwargs = await self._event_fields(guild, session)
            kwargs["name"] = session["title"][:100]
            starts = parse_iso(session.get("starts_at"))
            if starts and starts > utcnow() and not session.get("started"):
                kwargs["start_time"] = starts
            if image_change:
                kwargs["image"] = self.banner_bytes((session.get("event") or {}).get("banner"))
            edited = await event.edit(**kwargs)
            async with self.config.guild(guild).play_sessions() as sessions:
                if session["id"] in sessions:   # the card shows the event's banner, wherever it came from
                    details = sessions[session["id"]].setdefault("event", {})
                    url = cover_url(edited) if edited is not None else cover_url(event)
                    if url:
                        details["cover_url"] = url
                    else:
                        details.pop("cover_url", None)
        except discord.Forbidden:
            return "I couldn't update the Discord event: I need Manage Events."
        except discord.HTTPException as e:
            log.info("Couldn't update the event for session %s: %s", session["id"], e)
            return "Discord didn't accept the change to the event. Try again in a minute."
        return None

    @commands.Cog.listener()
    async def on_scheduled_event_update(self, before: discord.ScheduledEvent, after: discord.ScheduledEvent):
        """
        Someone edited a session's event in Discord: its time, name and voice channel go to the session (that one
        session, even if it repeats), and cancelling the event ends the session.
        """
        guild = after.guild
        if guild is None:
            return
        cancel, changed, session = False, False, None
        default_voice = await self.config.guild(guild).event_channel()
        async with self.config.guild(guild).play_sessions() as sessions:
            sid = self._session_for_event(sessions, after.id)
            if sid is None:
                return
            saved = sessions[sid]
            if after.status == discord.EventStatus.cancelled:
                cancel = True
            else:
                starts = parse_iso(saved.get("starts_at"))
                if after.start_time and (starts is None or abs((after.start_time - starts).total_seconds()) >= 60):
                    saved["starts_at"] = after.start_time.isoformat()
                    now = utcnow()
                    saved["reminders_sent"] = passed_leads(session_leads(saved), after.start_time, now)
                    saved.pop("reminded", None)
                    saved["started"] = saved.get("started") and after.start_time <= now
                    changed = True
                if after.name and after.name != saved["title"][:100]:
                    saved["title"] = after.name[:200]
                    changed = True
                details = saved.setdefault("event", {})
                if cover_url(after) != details.get("cover_url"):
                    if cover_url(after):
                        details["cover_url"] = cover_url(after)
                    else:
                        details.pop("cover_url", None)
                    changed = True
                expected = details.get("voice_id") or default_voice
                if (after.channel_id or None) != (expected or None):
                    details["voice_id"] = after.channel_id or None
                    changed = True
                session = dict(saved)
        if cancel:
            await self.end_session(guild, sid)
        elif changed:
            await self.refresh_session_message(guild, session)

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

    async def create_recurring(self, target: Target, text: str, details: Optional[dict] = None,
                               settings: Optional[dict] = None):
        guild, member, channel = who(target)
        tz, tz_name, personal = await self.timezone_for(member)
        parsed = parse_recurring(text, tz, utcnow())
        if parsed is None:
            return await self.reply(target, ephemeral=True, content=(
                "❓ For a repeating session, give a day and a time: "
                f"{await self.cmd(guild, 'games session every friday 9pm Raid night')}, "
                f"{await self.cmd(guild, 'games session every other sunday 8:30pm')} or "
                f"{await self.cmd(guild, 'games session every first friday 8pm')}."))
        schedules = await self.config.guild(guild).recurring()
        if len(schedules) >= MAX_RECURRING:
            return await self.reply(target, ephemeral=True, content=(
                f"⏳ This server already has {MAX_RECURRING} repeating sessions. Stop one first with "
                f"{await self.cmd(guild, 'games recurring stop <id>')}."))
        rid = generate_id()
        settings = dict(settings or {})
        schedule = {"id": rid, "title": (parsed["title"].strip() or f"{member.display_name}'s game night")[:200],
                    "host_id": str(member.id), "channel_id": channel.id, "weekday": parsed["weekday"],
                    "hour": parsed["hour"], "minute": parsed["minute"], "interval": parsed["interval"],
                    "nth": parsed["nth"],   # monthly: the 1st-4th (or -1, last) weekday of the month
                    "tz": tz_name, "next_start": parsed["first"].isoformat(), "created_at": utcnow().isoformat(),
                    "event": self.store_details(rid, details),   # every occurrence's event uses these
                    **{key: settings[key] for key in SETTING_KEYS if key in settings}}
        async with self.config.guild(guild).recurring() as recurring:
            recurring[rid] = schedule
        session = await self._tick_recurring(guild, rid, schedule, utcnow())
        leads = schedule["reminders"] if "reminders" in schedule else await self.config.guild(guild).reminders()
        card_at = (f"{fmt_lead(max(leads))} before it starts, as its first reminder"
                   if post_lead(leads) > timedelta(hours=RECURRING_POST_HOURS) else "a day before it starts")
        if session is not None and not is_pending(session):
            nxt = "The first one is posted above."
        else:
            first = parse_iso(session["starts_at"]) if session else parsed["first"]
            nxt = (f"The first is {stamp(first)}"
                   + (": its Discord event is up now." if session and session.get("event_id") else "."))
        lines = [f"✅ **{schedule['title']}** repeats: {repeat_label(schedule)}.",
                 f"Each card is posted here {card_at}, and each Discord event as soon as the last session ends. "
                 + nxt,
                 f"-# Skip one with {await self.cmd(guild, f'games recurring skip {rid}')} or stop them with "
                 f"{await self.cmd(guild, f'games recurring stop {rid}')}."]
        if not personal:
            lines.append(f"-# I used **{tz_name}**. If that's wrong, set yours with "
                         f"{await self.cmd(guild, 'games timezone <zone>')}, stop this and set it up again.")
        await self.reply(target, content="\n".join(lines), ephemeral=isinstance(target, discord.Interaction))
        await self.settle_replacements(target, settings, schedule=schedule)

    async def settle_replacements(self, target: Target, settings: dict, *, session: Optional[dict] = None,
                                  schedule: Optional[dict] = None):
        """
        After a new session or schedule: if it said what it replaces ("Replaces:", even "none"), that's done.
        Otherwise, when it falls on the same night as another schedule's, ask the person once whether it
        replaces that night, with buttons.
        """
        guild, member, _ = who(target)
        if "replaces" in settings:
            if session is not None and settings["replaces"]:
                await self.apply_replacements(guild, session)
            return
        if schedule is not None:
            starts, start = [], parse_iso(schedule["next_start"])   # (as set up: the first night)
            for _ in range(3):   # the next few nights
                starts.append(start)
                start = advance_occurrence(start, schedule)
            exclude = schedule["id"]
        else:
            starts, exclude = [parse_iso(session["starts_at"])], session.get("recurring_id")
        clashes = await self.clashing_schedules(guild, starts, exclude=exclude)
        if schedule is not None and not schedule.get("nth"):   # a regular weekly night doesn't take over special ones
            clashes = [c for c in clashes if not (c.get("nth") or c.get("replaces"))]
        if not clashes:
            return
        names = name_list([f"**{c['title']}**" for c in clashes])
        own = (schedule or session)["title"]
        text = (f"**{own}** is on the same night as {names}. Should it replace "
                + ("those nights?" if schedule is not None else "that night?"))
        view = ReplaceAskView(self, member.id, text, [c["id"] for c in clashes],
                              sid=session["id"] if session else None, rid=schedule["id"] if schedule else None)
        view.message = await self.send_card(target, view, ephemeral=isinstance(target, discord.Interaction))

    async def set_replaces(self, guild: discord.Guild, rids: List[str], *, sid: Optional[str] = None,
                           rid: Optional[str] = None) -> List[str]:
        """
        Say what a session (`sid`) or a schedule (`rid`: and its sessions not started yet) replaces, and end the
        regular sessions that clash now. Returns the titles of the schedules it replaces.
        """
        schedules = await self.config.guild(guild).recurring()
        rids = [r for r in dict.fromkeys(rids) if r in schedules and r != rid]
        titles = [schedules[r]["title"] for r in rids]
        if rid is not None:
            async with self.config.guild(guild).recurring() as recurring:
                if rid in recurring:
                    recurring[rid].update(replaces=rids, replaces_titles=titles)
        targets = []
        async with self.config.guild(guild).play_sessions() as sessions:
            for s in sessions.values():
                if s["id"] == sid or (rid is not None and s.get("recurring_id") == rid and not s.get("started")):
                    s.update(replaces=rids, replaces_titles=titles)
                    targets.append(dict(s))
        for session in targets:
            await self.apply_replacements(guild, session)
            await self.refresh_session_message(guild, session)
        return titles

    async def _tick_recurring(self, guild: discord.Guild, rid: str, schedule: dict, now: datetime) -> Optional[dict]:
        """
        Make a schedule's next session as soon as its last one is over, so its Discord event shows early and
        Interested works from then on; the card follows a day ahead (or at the earliest reminder). Nights another
        session or schedule replaces are skipped and remembered (to come back if that one is cancelled). Returns
        the session made, if any.
        """
        sessions = await self.config.guild(guild).play_sessions()
        if any(s.get("recurring_id") == rid and not s.get("booked") for s in sessions.values()):
            return None   # one regular session at a time (Plan next dates come on top)
        start = parse_iso(schedule["next_start"])
        if start is None:
            return None
        schedules = await self.config.guild(guild).recurring()
        replaced = []
        for _ in range(60):   # past ones (downtime) and replaced nights are skipped
            if start <= now:
                start = advance_occurrence(start, schedule)
                continue
            if await self.replacer_for(guild, rid, start, sessions, schedules) is None:
                break
            replaced.append(start.isoformat())
            start = advance_occurrence(start, schedule)
        if replaced:
            await self._remember_replaced(guild, rid, replaced)
        if start - now > timedelta(days=MAX_AHEAD_DAYS):
            await self._set_next_start(guild, rid, start)
            return None
        session = await self._create_occurrence(guild, schedule, start)
        await self._set_next_start(guild, rid, advance_occurrence(start, schedule))
        return session

    async def _set_next_start(self, guild: discord.Guild, rid: str, start: datetime):
        async with self.config.guild(guild).recurring() as recurring:
            if rid in recurring:
                recurring[rid]["next_start"] = start.isoformat()

    async def _create_occurrence(self, guild: discord.Guild, schedule: dict, start: datetime,
                                 booked: bool = False) -> Optional[dict]:
        """One of a schedule's sessions: its card now if it's that close, else just the session and event."""
        channel = guild.get_channel_or_thread(schedule["channel_id"])
        host = guild.get_member(int(schedule["host_id"]))
        if channel is None or host is None:
            log.info("Recurring session %s has no channel or host any more; skipping %s", schedule["id"], start)
            return None
        leads = schedule["reminders"] if "reminders" in schedule else await self.config.guild(guild).reminders()
        pending = utcnow() < start - post_lead(leads)
        try:
            session = await self.post_session(guild, channel, host, schedule["title"], start, schedule,
                                              pending=pending, booked=booked)
        except discord.HTTPException as e:
            log.info("Couldn't post recurring session %s: %s", schedule["id"], e)
            return None
        if session.get("replaces"):
            await self.apply_replacements(guild, session)
        return session

    # ---------- special nights replacing regular ones ----------

    async def replacer_for(self, guild: discord.Guild, rid: str, start: datetime, sessions: Optional[dict] = None,
                           schedules: Optional[dict] = None) -> Optional[str]:
        """
        The title of whatever replaces schedule `rid`'s night at `start`: a session that says it does and starts
        within REPLACE_WINDOW_HOURS, or a schedule that does and has a night (not yet made) that close. Else None.
        """
        window = timedelta(hours=REPLACE_WINDOW_HOURS)
        sessions = await self.config.guild(guild).play_sessions() if sessions is None else sessions
        schedules = await self.config.guild(guild).recurring() if schedules is None else schedules
        for s in sessions.values():
            starts = parse_iso(s.get("starts_at"))
            if rid in (s.get("replaces") or []) and starts and abs(starts - start) < window:
                return s["title"]
        for other in schedules.values():
            if other["id"] == rid or rid not in (other.get("replaces") or []):
                continue
            nxt = parse_iso(other.get("next_start"))
            occurrence = first_occurrence(other, start - window)
            if nxt and occurrence >= nxt - timedelta(minutes=1) and abs(occurrence - start) < window:
                return other["title"]
        return None

    async def _remember_replaced(self, guild: discord.Guild, rid: str, starts: List[str]):
        """Note nights of schedule `rid` that were replaced, so they can come back if the replacement is cancelled."""
        cutoff = utcnow() - timedelta(days=1)
        async with self.config.guild(guild).recurring() as recurring:
            if rid in recurring:
                kept = [d for d in recurring[rid].get("replaced_dates", []) if (parse_iso(d) or cutoff) > cutoff]
                recurring[rid]["replaced_dates"] = sorted(set(kept + starts))

    async def apply_replacements(self, guild: discord.Guild, special: dict) -> List[str]:
        """
        End the regular sessions a special one replaces that night (its card says what replaced it, and its event
        is cancelled). Returns the titles of the sessions ended.
        """
        starts = parse_iso(special.get("starts_at"))
        if not starts or not special.get("replaces"):
            return []
        window = timedelta(hours=REPLACE_WINDOW_HOURS)
        sessions = await self.config.guild(guild).play_sessions()
        ended = []
        for s in list(sessions.values()):
            other = parse_iso(s.get("starts_at"))
            if (s["id"] != special["id"] and s.get("recurring_id") in special["replaces"] and other
                    and not s.get("started") and abs(other - starts) < window):
                await self.end_session(guild, s["id"], replaced_by=special["title"])
                await self._remember_replaced(guild, s["recurring_id"], [s["starts_at"]])
                ended.append(s["title"])
        return ended

    async def _restore_replaced(self, guild: discord.Guild, special: dict):
        """A special night was cancelled before it started: bring back the regular nights it replaced."""
        starts = parse_iso(special.get("starts_at"))
        if not starts or not special.get("replaces"):
            return
        window, now = timedelta(hours=REPLACE_WINDOW_HOURS), utcnow()
        schedules = await self.config.guild(guild).recurring()
        sessions = await self.config.guild(guild).play_sessions()
        for rid in special["replaces"]:
            schedule = schedules.get(rid)
            if schedule is None:
                continue
            back = [d for d in schedule.get("replaced_dates", [])
                    if (parse_iso(d) or now) > now and abs(parse_iso(d) - starts) < window]
            for day in back:
                when = parse_iso(day)
                async with self.config.guild(guild).recurring() as recurring:
                    if rid in recurring:
                        recurring[rid]["replaced_dates"] = [d for d in recurring[rid].get("replaced_dates", [])
                                                            if d != day]
                taken = any(s.get("recurring_id") == rid and parse_iso(s.get("starts_at"))
                            and abs(parse_iso(s["starts_at"]) - when) < window for s in sessions.values())
                if not taken and await self.replacer_for(guild, rid, when) is None:
                    await self._create_occurrence(guild, schedule, when)

    async def clashing_schedules(self, guild: discord.Guild, starts: List[datetime],
                                 exclude: Optional[str] = None) -> List[dict]:
        """Other schedules with a night (made or not) on the same evening as any of `starts`."""
        window = timedelta(hours=REPLACE_WINDOW_HOURS)
        sessions = await self.config.guild(guild).play_sessions()
        found = []
        for schedule in (await self.config.guild(guild).recurring()).values():
            if schedule["id"] == exclude:
                continue
            nights = [parse_iso(s["starts_at"]) for s in sessions.values()
                      if s.get("recurring_id") == schedule["id"] and s.get("starts_at")]
            for start in starts:
                occurrence = first_occurrence(schedule, start - window)
                if abs(occurrence - start) < window or any(n and abs(n - start) < window for n in nights):
                    found.append(schedule)
                    break
        return found

    async def latest_session(self, guild: discord.Guild, channel_id: int, host_id: Optional[str] = None) -> Optional[dict]:
        """The newest session in a channel whose card is up (one made ahead isn't "the" session yet)."""
        sessions = await self.config.guild(guild).play_sessions()
        candidates = [s for s in sessions.values() if s["channel_id"] == channel_id and not is_pending(s)
                      and (host_id is None or s["host_id"] == host_id)]
        return max(candidates, key=lambda s: s["created_at"]) if candidates else None

    async def end_session(self, guild: discord.Guild, sid: str, replaced_by: Optional[str] = None) -> Optional[dict]:
        """
        End a session: its card turns grey (saying what replaced it, with `replaced_by`), its pings go, and its
        Discord event ends (or is cancelled). A special night cancelled before it started brings back the regular
        nights it replaced.
        """
        async with self.config.guild(guild).play_sessions() as sessions:
            session = sessions.pop(sid, None)
        if session is None:
            return None
        if session.get("vote_id"):
            await self.cancel_vote(guild, session["vote_id"])   # also deletes the vote's ping line
        session["vote_id"] = None
        session["replaced_by"] = replaced_by
        await self.refresh_session_message(guild, session, ended=True)
        await self._delete_messages(guild, session["channel_id"], session.get("pings"))   # reminders, start, winner
        session["pings"] = []
        await self.update_event(guild, session, "finish")
        self.drop_banner((session.get("event") or {}).get("banner"), sid)   # its own banner, not its schedule's
        self.bot.dispatch("gm_session_ended", guild, session)  # ActivityStats records attendance
        starts = parse_iso(session.get("starts_at"))
        if session.get("replaces") and not session.get("started") and starts and starts > utcnow():
            await self._restore_replaced(guild, session)
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
            feedback, session = await self.set_membership(guild, sid, member, action == "join")
            if session is None:
                return await ui.respond(interaction, feedback)
            if ui.is_card(interaction.message):
                await interaction.response.edit_message(view=await self.session_card_now(guild, session),
                                                        allowed_mentions=NO_PING)
            else:   # posted before sessions became cards
                await interaction.response.edit_message(embed=self.session_embed(session), view=session_view(sid))
            return

        if action == "cal":
            return await self.send_calendar(interaction, session)
        if not await self.can_manage(member, session["host_id"]):
            return await ui.respond(interaction, "🔒 Only the host or a game admin can do that.")
        if action == "event":
            return await self.open_edit_menu(interaction, session)
        if action == "plan":
            return await self.open_plan_next(interaction, session)
        if action == "vote":
            await self.start_vote(interaction, session_id=sid)
        else:
            await interaction.response.defer()
            await self.end_session(guild, sid)

    async def set_membership(self, guild: discord.Guild, sid: str, member: discord.Member,
                             join: bool) -> Tuple[str, Optional[dict]]:
        """Join or leave a session. Returns (a line for the member, the saved session, or None if nothing changed)."""
        uid = str(member.id)
        async with self.config.guild(guild).play_sessions() as sessions:
            session = sessions.get(sid)
            if session is None:
                return "⚠️ This session has ended.", None
            players = session["participants"]
            if join:
                if uid in players:
                    return "⚠️ You're already in.", None
                players.append(uid)
            else:
                if uid == session["host_id"]:
                    return ui.line(ui.FAIL, "You're the host, so you can't leave.",
                                   hint="End the session instead."), None
                if uid not in players:
                    return "⚠️ You haven't joined.", None
                players.remove(uid)
            session = dict(session)
        title = session["title"]
        return ui.line(ui.DONE, f"You're in **{title}**." if join else f"You've left **{title}**."), session

    async def pick_session(self, target: Target, name: Optional[str], verb: str, *,
                           this_channel: bool = False) -> Optional[dict]:
        """
        The session a join, leave or here command means: one named by title or ID (as the slash commands' menu gives),
        else the only one in this channel, or in the server when this channel has none. `here` (this_channel) only
        looks in this channel and takes the latest. Says what's wrong and returns None when it isn't clear.
        """
        guild, _, channel = who(target)
        sessions = sorted((await self.config.guild(guild).play_sessions()).values(), key=lambda s: s["created_at"])
        if this_channel:   # a session made ahead has no card to bring down yet
            sessions = [s for s in sessions if not is_pending(s)]
        here = [s for s in sessions if s["channel_id"] == channel.id]
        pool = here if this_channel else here + [s for s in sessions if s not in here]
        if name:
            key = name.strip().lower()
            found = ([s for s in pool if s["id"] == key or s["title"].lower() == key]
                     or [s for s in pool if key in s["title"].lower()])
            if len(found) > 1:
                found = [s for s in found if s in here] or found   # the same name here and elsewhere: this channel's
        elif this_channel:
            found = here[-1:]
        else:   # tonight's (its card is up) before next week's, made ahead
            found = here or sessions
            found = [s for s in found if not is_pending(s)] or found
        if not found:
            start = await self.cmd(guild, "games session")
            if name:
                text = ui.line(ui.ASK, f"There's no session called **{name[:80]}**"
                                       + (" in this channel." if this_channel else "."))
            else:
                text = ui.line(ui.ASK, "There's no session in this channel." if this_channel
                               else "There's no session to join right now.", hint=f"Start one with {start}.")
            await self.reply(target, content=text, ephemeral=True)
            return None
        if len(found) > 1:
            titles = name_list([f"**{s['title']}**" for s in found])
            example = await self.cmd(guild, f"games {verb} {found[-1]['title'][:40]}")
            await self.reply(target, ephemeral=True, content=ui.line(
                ui.ASK, f"Which session? There's {titles}.", hint=f"Add its name, like {example}."))
            return None
        return found[0]

    async def join_or_leave(self, target: Target, name: Optional[str], join: bool):
        """`games join` / `games leave`: the same as the card's buttons, without having to find the card."""
        guild, member, _ = who(target)
        session = await self.pick_session(target, name, "join" if join else "leave")
        if session is None:
            return
        feedback, changed = await self.set_membership(guild, session["id"], member, join)
        if changed is not None:
            await self.refresh_session_message(guild, changed)
            link = self.session_link(guild, changed)
            if link:
                feedback += "\n" + ui.hint(f"[See the card]({link})")
        await self.reply(target, content=feedback, ephemeral=True)

    async def bring_here(self, target: Target, name: Optional[str]):
        """`games here`: move this channel's session card back to the bottom, after chatter has buried it."""
        guild, _, channel = who(target)
        session = await self.pick_session(target, name, "here", this_channel=True)
        if session is None:
            return
        last = self._here_last.get(channel.id, 0.0)
        if time.monotonic() - last < HERE_COOLDOWN:
            return await self.reply(target, ephemeral=True,
                                    content=ui.line(ui.WAIT, "The card was just moved. Try again in a minute."))
        self._here_last[channel.id] = time.monotonic()
        if await self.move_session_card(guild, session) is None:
            self._here_last.pop(channel.id, None)
            return await self.reply(target, ephemeral=True, content=ui.line(
                ui.FAIL, "I couldn't move the card.", hint="Check that I can send messages in this channel."))
        if isinstance(target, discord.Interaction):
            await self.reply(target, content="✅ Moved the card down here.", ephemeral=True)
        else:
            await target.tick()   # the card right below is the answer

    async def _buried(self, guild: discord.Guild, session: dict) -> bool:
        """Whether a session's card has scrolled out of sight: at least BURIED_AFTER messages were posted below it."""
        channel = guild.get_channel_or_thread(session.get("channel_id") or 0)
        if channel is None or not session.get("message_id"):
            return False
        count = 0
        try:
            async for _ in channel.history(after=discord.Object(int(session["message_id"])), limit=BURIED_AFTER):
                count += 1
        except discord.HTTPException:   # no Read Message History: leave the card where it is
            return False
        return count >= BURIED_AFTER

    async def move_session_card(self, guild: discord.Guild, session: dict, *,
                                ping_ids: Optional[List[str]] = None) -> Optional[dict]:
        """
        Repost a session's card at the bottom of its channel and delete the old one (Discord can't move a message).
        The buttons keep working: they're tied to the session, not the message. With `ping_ids`, the new card pings
        those people (it names them). Ping lines that linked to the old card go too. A session posted before cards
        comes back as a card. Returns the saved session, or None if it ended or the card couldn't be posted.
        """
        sid = session["id"]
        async with self._move_locks.setdefault(sid, asyncio.Lock()):
            current = (await self.config.guild(guild).play_sessions()).get(sid)
            channel = guild.get_channel_or_thread(current["channel_id"]) if current else None
            if channel is None:
                return None
            current["card"] = True
            try:
                message = await self.send_card(channel, await self.session_card_now(guild, current),
                                               allowed_mentions=pings(ping_ids) if ping_ids else None)
            except discord.HTTPException as e:
                log.info("Couldn't move session %s down: %s", sid, e)
                return None
            stale = [current.get("message_id"), *current.get("pings", [])]   # the old card, and lines linking to it
            async with self.config.guild(guild).play_sessions() as sessions:
                saved = sessions.get(sid)
                if saved is not None:
                    saved.update(message_id=message.id, card=True, pings=[])
                    current = dict(saved)
            if saved is None:   # it ended while the new card was being posted
                await self._delete_messages(guild, channel.id, [message.id])
                return None
            if current.get("vote_id"):
                async with self.config.guild(guild).votes() as votes:
                    vote = votes.get(current["vote_id"])
                    if vote is not None and vote.get("in_card"):   # the vote lives in the card: it moves with it
                        vote["message_id"] = message.id
                        stale.append(vote.get("ping_id"))
                        vote["ping_id"] = None
            await self._delete_messages(guild, channel.id, stale)
            await self._relink_event(guild, current, stale[0])
            return current

    async def _relink_event(self, guild: discord.Guild, session: dict, old_message_id: Optional[int]):
        """Point the session's Discord event description at the card's new message."""
        if not session.get("event_id") or not old_message_id:
            return
        old = message_link(guild.id, session["channel_id"], old_message_id)
        try:
            event = guild.get_scheduled_event(session["event_id"]) or await guild.fetch_scheduled_event(
                session["event_id"])
            if event.description and old in event.description:
                await event.edit(description=event.description.replace(old, self.session_link(guild, session)))
        except discord.HTTPException as e:
            log.debug("Couldn't relink the event for session %s: %s", session["id"], e)

    async def _tick_session(self, guild: discord.Guild, sid: str, session: dict, now: datetime):
        starts = parse_iso(session.get("starts_at"))
        base = starts or parse_iso(session.get("created_at")) or now
        if now - base > timedelta(hours=SESSION_EXPIRE_HOURS):
            await self.end_session(guild, sid)
            return
        if starts is None:
            return
        leads, sent = session_leads(session), sent_leads(session)
        due = [lead for lead in leads if lead not in sent and starts - timedelta(minutes=lead) <= now]
        if is_pending(session):
            if now < starts - post_lead(leads):
                return
            # The card goes up: a day ahead, or at the earliest reminder, when it's that reminder (and pings).
            if due:
                session = await self._update_session(guild, session,
                                                     {"reminders_sent": sorted(sent | set(due), reverse=True)}, [])
                if session is None:
                    return
            await self.post_pending(guild, session, ping=bool(due) and now < starts)
            return
        updates, new_pings = {}, []
        if due and now < starts:   # several due at once (after downtime) make one reminder
            new_pings.append(await self.announce(guild, session, f"**{session['title']}** starts {stamp(starts, 'R')}"))
            updates["reminders_sent"] = sorted(sent | set(due), reverse=True)
        elif not session.get("started") and now >= starts:
            if now - starts < timedelta(minutes=30):  # don't announce stale starts after downtime
                new_pings.append(await self.announce(guild, session, f"**{session['title']}** is starting"))
            await self.update_event(guild, session, "start")
            updates.update(reminders_sent=sorted(leads, reverse=True), started=True)
        if updates:
            current = await self._update_session(guild, session, updates, new_pings)
            if current is not None and current.get("card"):   # the footer names the reminders still to come
                await self.refresh_session_message(guild, current)

    async def _update_session(self, guild: discord.Guild, session: dict, updates: dict,
                              new_pings: List[Optional[int]]) -> Optional[dict]:
        """
        Save changes and new ping-line IDs on a session; returns the saved session. If it ended meanwhile, its new
        ping lines are deleted right away (nothing would clean them up later).
        """
        new_pings = [p for p in new_pings if p]
        current = None
        async with self.config.guild(guild).play_sessions() as sessions:
            if session["id"] in sessions:
                saved = sessions[session["id"]]
                saved.update(updates)
                saved["pings"] = saved.get("pings", []) + new_pings
                current = dict(saved)
        if current is None:
            await self._delete_messages(guild, session["channel_id"], new_pings)
        return current

    async def announce(self, guild: discord.Guild, session: dict, text: str, emoji: str = "🎮",
                       user_ids: Optional[List[str]] = None) -> Optional[int]:
        """
        Tell a session's players something (the reminder, the start, a vote). If its card has scrolled out of sight,
        the card itself moves to the bottom of the channel and pings them, and nothing else is posted. Otherwise one
        short ping line links to the card. Returns the ping line's message ID, if one was sent.
        """
        ids = session["participants"] if user_ids is None else user_ids
        if session.get("card") and await self._buried(guild, session):
            if await self.move_session_card(guild, session, ping_ids=ids) is not None:
                return None
        return await self._ping(guild, session["channel_id"], emoji, ids, text, self.session_link(guild, session))

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

    @staticmethod
    def vote_status(vote: dict, guild: Optional[discord.Guild] = None) -> str:
        """
        A running vote as one block: `🗳️ **Vote: what should we play?**` over `Pick up to 2 · ends in 2 minutes ·
        3 of 8 voted, waiting on Ash, Bex and Cole` (display names when `guild` is given), plus where the options
        came from when it isn't the usual "everyone has these installed". The tallies are on the buttons
        (vote_buttons), and how to vote is in the private reply to a vote button.
        """
        ends = parse_iso(vote.get("ends_at"))
        voters = vote["allowed_voters"]
        waiting = [u for u in voters if u not in vote["user_votes"]]

        def name(uid: str) -> str:
            member = guild.get_member(int(uid)) if guild is not None else None
            return member.display_name if member is not None else f"<@{uid}>"   # mentions here never ping

        picks = vote["max_choices"]
        voted = f"{len(voters) - len(waiting)} of {len(voters)} voted"
        detail = details("Pick 1" if picks == 1 else f"Pick up to {picks}",
                         f"ends {stamp(ends, 'R')}" if ends else None,   # (this replaced the "30 seconds left" ping)
                         voted + (f", waiting on {name_list([name(u) for u in waiting])}" if waiting else ""))
        basis = vote.get("basis") or ""
        if basis and not basis.startswith("everyone has"):
            detail += f"\nOptions: {basis}."
        return ui.two_line("🗳️ **Vote: what should we play?**", detail)

    @staticmethod
    def vote_lines(vote: dict) -> List[str]:
        """The older vote card's lines (vote_card). Its "Waiting on" mentions were the ping when it was posted."""
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
        return lines

    def vote_card(self, vote: dict) -> ui.CardView:
        """
        A vote as a card of its own: only for sessions posted as embeds (before cards) and votes started before
        Phase 4. Votes on card sessions run inside the session card (session_card). The "Waiting on" mentions were
        the ping when one was posted (pings(players)); every redraw is NO_PING. Kept in its older shape, apart
        from the tallies on its buttons.
        """
        return ui.CardView(ui.card("\n".join(self.vote_lines(vote)), ui.SEPARATOR, vote_buttons(vote),
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
        if session.get("game"):
            return await self.reply(target, ephemeral=True, content=ui.line(
                ui.WARN, f"This session is set to **{session['game']['name']}**, so there's no vote.",
                hint="The host can change that with the card's Edit button."))
        if is_pending(session):
            return await self.reply(target, ephemeral=True, content=ui.line(
                ui.WARN, "That session's card isn't posted yet.", hint="Votes run in the card, on the day."))
        votes = await self.config.guild(guild).votes()
        if session.get("vote_id") in votes:
            return await self.reply(target, content="⚠️ A vote is already running for this session.", ephemeral=True)
        players = session["participants"]
        if len(players) < 2:
            return await self.reply(target, content="⚠️ A vote needs at least 2 players. Others can press **Join** "
                                                    "on the session first.", ephemeral=True)
        games = await self.config.guild(guild).games()
        users = await self.config.guild(guild).users()
        candidates, basis, _ = self.vote_candidates(games, users, players)
        if not candidates:
            return await self.reply(target, content="⚠️ These players don't have any games in common yet. Everyone can "
                                                    f"mark theirs with {await self.cmd(guild, 'games install')}.",
                                    ephemeral=True)
        options = candidates[:MAX_VOTE_OPTIONS]
        if len(candidates) > MAX_VOTE_OPTIONS:
            basis += f" (top {MAX_VOTE_OPTIONS} of {len(candidates)})"
        max_choices = max(1, min(max_choices, len(options)))
        seconds = max(MIN_VOTE_SECONDS, min(seconds, MAX_VOTE_SECONDS))
        # Plain names: the buttons add each game's running tally (vote_buttons), and the card says where the
        # options came from when not everyone has them installed.
        labels = [(g, games[g]["name"][:70]) for g in options]

        vid = generate_id()
        ends_at = utcnow() + timedelta(seconds=seconds)
        # A session posted as a card holds its vote (Phase 4); an old embed session can't, so its vote is a card
        # of its own, as before.
        in_card = bool(session.get("card") and session.get("message_id"))
        vote = {
            "id": vid, "session_id": session["id"], "title": session["title"], "games": options,
            "names": {g: games[g]["name"] for g in options}, "basis": basis, "tallies": {}, "user_votes": {},
            "allowed_voters": list(players), "max_choices": max_choices, "created_at": utcnow().isoformat(),
            "created_by": str(member.id), "ends_at": ends_at.isoformat(), "timeout": seconds,
            "labels": dict(labels), "card": True,   # labels redraw the buttons; older votes are embeds
            # In the card: the vote's message is the session's, and "ping_id" is its one-line ping.
            "in_card": in_card, "ping_id": None,
            "channel_id": session["channel_id"] if in_card else channel.id,
            "message_id": session["message_id"] if in_card else None,
        }
        async with self.config.guild(guild).votes() as all_votes:
            all_votes[vid] = vote
        if not in_card:
            # Pings every player: they're all named under "Waiting on".
            message = await self.send_card(channel, self.vote_card(vote), allowed_mentions=pings(players))
            async with self.config.guild(guild).votes() as all_votes:
                if vid in all_votes:
                    all_votes[vid]["message_id"] = message.id
        async with self.config.guild(guild).play_sessions() as all_sessions:
            if session["id"] in all_sessions:
                all_sessions[session["id"]]["vote_id"] = vid
                session = dict(all_sessions[session["id"]])
        await self.refresh_session_message(guild, session)   # in the card: the options appear
        self.schedule_vote(guild.id, vid, ends_at)
        if in_card:
            ping = await self.announce(guild, session, "Vote on what to play", "🗳️", players)
            async with self.config.guild(guild).votes() as all_votes:
                if vid in all_votes:
                    all_votes[vid]["ping_id"] = ping
                    ping = None
            if ping:   # everyone voted before the line was saved: it's already done with
                await self._delete_messages(guild, session["channel_id"], [ping])
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
                feedback = ui.line(ui.LOCKED, "Only players who were in the session when the vote started can vote.")
                vote = None
            else:
                name = vote.get("names", {}).get(gid, "that game")
                mine = vote["user_votes"].setdefault(uid, [])
                tallies = vote["tallies"]
                picks = vote["max_choices"]
                if gid in mine:
                    mine.remove(gid)
                    tallies[gid] = tallies.get(gid, 1) - 1
                    if tallies[gid] <= 0:
                        del tallies[gid]
                    feedback = f"✅ Took back your vote for **{name}**."
                elif len(mine) >= picks:
                    feedback = (f"⏳ You can pick {picks}. Press one of your picks again to take it "
                                "back first.")
                else:
                    mine.append(gid)
                    tallies[gid] = tallies.get(gid, 0) + 1
                    # How voting works lives here, in the voter's private reply, instead of on the card.
                    how = ("Press it again to take your vote back, then you can pick another." if picks == 1
                           else f"Press a game again to take your vote back. You can pick up to {picks}.")
                    feedback = ui.line(ui.DONE, f"Voted for **{name}**.", how)
                if not mine:
                    del vote["user_votes"][uid]
                everyone_voted = len(vote["user_votes"]) >= len(vote["allowed_voters"])
                vote = dict(vote)
        await ui.respond(interaction, feedback)
        if vote is None:
            return
        if not everyone_voted:   # (otherwise the results replace it right away)
            try:
                if vote.get("in_card"):   # the vote is inside the session card: redraw the whole card
                    session = (await self.config.guild(guild).play_sessions()).get(vote.get("session_id"))
                    if session is not None and ui.is_card(interaction.message):
                        await interaction.message.edit(view=self.session_card(session, vote=vote, guild=guild),
                                                       allowed_mentions=NO_PING)
                elif ui.is_card(interaction.message):
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
        # No "30 seconds left" ping any more: the card's "Voting ends <t:R>" line counts down instead.
        try:
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
        footer = f"{len(vote['user_votes'])} of {len(voters)} voted" + (f" · {reason}" if reason else "")
        winner_name = names.get(winner) if winner else None
        in_card = vote.get("in_card")
        if in_card:   # the vote's ping line is done with; the result goes into the session card below
            await self._delete_messages(guild, vote["channel_id"], [vote.get("ping_id")])
        else:         # a vote card of its own (old embed sessions, votes from before Phase 4): it shows the results
            title = f"🗳️ Results: {vote.get('title', 'Vote')}"
            body = "\n".join(lines) or "No votes were cast."
            embed = discord.Embed(title=title, description=body, color=ui.HIGHLIGHT)
            embed.set_footer(text=footer)
            await self._edit_record(guild, vote,
                                    lambda: final_card(body, title=title, color=ui.HIGHLIGHT, footer=footer),
                                    embed=embed, view=None)

        async with self.config.guild(guild).play_sessions() as sessions:
            session = sessions.get(vote.get("session_id"))
            if session is not None and session.get("vote_id") == vid:
                session["vote_id"] = None
                if winner_name:
                    history = session.setdefault("winners", [session["winner"]] if session.get("winner") else [])
                    history.append(winner_name)
                    session["winner"] = winner_name
                if in_card:
                    session["vote_result"] = {"winner": winner_name, "tie": tie_note.strip(), "lines": lines,
                                              "footer": footer}
                session = dict(session)
            else:
                session = None
        if session is not None:
            await self.refresh_session_message(guild, session)

        if winner_name:
            # One short line that pings the voters (as before) and points at the result: the session card, or
            # the old vote card.
            link = message_link(guild.id, vote["channel_id"], vote.get("message_id"))
            ping = await self._ping(guild, vote["channel_id"], "🏆", voters, f"We're playing **{winner_name}**", link)
            if session is not None and ping and vote["channel_id"] == session["channel_id"]:
                await self._update_session(guild, session, {}, [ping])   # deleted when the session ends
        return winner_name

    async def cancel_vote(self, guild: discord.Guild, vid: str):
        """Stop a vote without a winner. A vote inside a session card just leaves it (the card is redrawn)."""
        async with self.config.guild(guild).votes() as votes:
            vote = votes.pop(vid, None)
        self._stop_timer(vid)
        if vote is None:
            return
        if not vote.get("in_card"):
            await self._edit_record(
                guild, vote, lambda: final_card(f"**{vote.get('title', 'Vote')}**: no game was picked.",
                                                title="🗳️ Vote cancelled", color=ui.MUTED),
                view=None, embed=discord.Embed(title="🗳️ Vote cancelled", color=ui.MUTED))
            return
        await self._delete_messages(guild, vote["channel_id"], [vote.get("ping_id")])
        async with self.config.guild(guild).play_sessions() as sessions:
            session = sessions.get(vote.get("session_id"))
            if session is not None and session.get("vote_id") == vid:
                session["vote_id"] = None
                session = dict(session)
            else:
                session = None   # ended (end_session redraws it) or already moved on
        if session is not None:
            await self.refresh_session_message(guild, session)

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
        items = await self.library_rows(ctx.guild, ctx.author, sorted(games.values(), key=lambda g: g["name"].lower()))
        await self.send_list(ctx, items, "🎮 Server library",
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
        await self.send_list(ctx, await self.library_rows(ctx.guild, ctx.author, matches),
                             f"🎮 Games matching “{ui.truncate(query, 60)}”",
                             f"{ui.plural(len(matches), 'game')} · {INSTALLED} = you have it installed")

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
            names, appids, unconfirmed = checked
            await self.reply(ctx, content=await self.request_games_text(ctx.guild, ctx.channel, ctx.author, names,
                                                                        appids=appids, unconfirmed=unconfirmed))

    @games.command(name="requests")
    async def games_requests(self, ctx: commands.Context):
        """Show pending game requests."""
        requests = await self.config.guild(ctx.guild).game_requests()
        if not requests:
            return await ctx.send("❓ No pending requests.")
        items = []
        for r in requests.values():
            when = parse_iso(r.get("requested_at"))
            items.append(ui.row(f"**{r['name']}**", details(f"requested by <@{r['requested_by']}>",
                                                             stamp(when, "R") if when else None)))
        await self.send_list(ctx, items, "🎮 Game requests",
                             f"{ui.plural(len(items), 'request')} · Game admins approve with "
                             f"{await self.prefix(ctx.guild)}games admin approve <game>")

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
        (`every other` for every two weeks, `every first friday` for monthly). For the event, attach an image
        as its banner, mention a voice channel to hold it there, and put a description on the lines after the
        first (Shift+Enter). Other lines set more:
        - `Length: 3h`: how long the event runs
        - `Game: Star Citizen`: set the game ahead, so there's no vote
        - `Reminders: 36h, 15m` (or `none`): when players are reminded before it starts
        - `Reminder note: Update your drivers`: shown on the card with every reminder
        - `Replaces: Friday Night Games`: that repeating session's night is off (or `none`)
        The host can change all of it later with the card's **Edit** button.

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
            link = self.session_link(ctx.guild, s)
            title = f"[{s['title']}]({link})" if link else s["title"]
            card_at = starts - post_lead(session_leads(s)) if starts and is_pending(s) else None
            game = s["game"]["name"] if s.get("game") else s.get("winner")
            items.append(ui.row(
                f"**{title}**" + (" 🗳️" if s.get("vote_id") else ""),   # 🗳️ = voting right now
                details(stamp(starts, "R") if starts else None, f"hosted by <@{s['host_id']}>",
                        ui.plural(len(s["participants"]), "player"), f"playing {game}" if game else None,
                        f"card posted {stamp(card_at, 'R')}" if card_at else None, f"ID `{s['id']}`")))
        voting = any(s.get("vote_id") for s in sessions.values())
        await self.send_list(ctx, items, "🎮 Active sessions",
                             ui.plural(len(items), "session") + (" · 🗳️ = voting now" if voting else ""))

    @games.command(name="join")
    async def games_join(self, ctx: commands.Context, *, session: str = None):
        """
        Join a game session without finding its card.

        With one session in this channel (or in the server), just type `[p]games join`. With more, add its name:
        `[p]games join Raid night`.
        """
        await self.join_or_leave(ctx, session, join=True)

    @games.command(name="leave")
    async def games_leave(self, ctx: commands.Context, *, session: str = None):
        """Leave a game session without finding its card. Add its name if there's more than one."""
        await self.join_or_leave(ctx, session, join=False)

    @games.command(name="here", aliases=["bump"])
    async def games_here(self, ctx: commands.Context, *, session: str = None):
        """
        Bring this channel's game session card back down to the bottom, after chatter has buried it.

        Cards also move down by themselves for the reminder, the start and a vote. Add a name if this channel has
        more than one session.
        """
        await self.bring_here(ctx, session)

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
        items = [ui.row(f"**{names.get(g) or games.get(g, {}).get('name', 'Unknown game')}**", ui.plural(c, "vote"))
                 for c, g in tallies]
        await self.send_list(ctx, items, f"🗳️ Votes so far: {vote.get('title', '')}".strip().rstrip(":"),
                             f"{len(vote['user_votes'])} of {len(vote['allowed_voters'])} voted · ID {vote['id']}",
                             empty="No votes yet.")

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
        items = [ui.row(f"**{games[r['game_id']]['name']}**",
                        details(f"{len(r['installed_by'])} of {len(r['target_users'])} installed",
                                f"asked by <@{r['requested_by']}>" if r.get("requested_by") else None))
                 for r in requests.values() if r["game_id"] in games]
        if not items:
            return await ctx.send("❓ No install requests.")
        await self.send_list(ctx, items, "🎮 Install requests", ui.plural(len(items), "request"))

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

        Start one with `[p]games session every friday 9pm Raid night` (or `every other friday`, or monthly:
        `every first friday`). Each session's Discord event shows as soon as the last one ends, and its card is
        posted a day before it starts (or at its earliest reminder). This lists them; `skip`, `stop` and `plan`
        manage them.
        """
        schedules = await self.config.guild(ctx.guild).recurring()
        if not schedules:
            return await ctx.send(f"❓ No repeating sessions. Start one with "
                                  f"{await self.cmd(ctx.guild, 'games session every friday 9pm Raid night')}.")
        sessions = await self.config.guild(ctx.guild).play_sessions()
        items = []
        for s in sorted(schedules.values(), key=lambda s: s["next_start"]):
            upcoming = sorted(parse_iso(x["starts_at"]) for x in sessions.values()
                              if x.get("recurring_id") == s["id"] and x.get("starts_at") and not x.get("started"))
            nxt = upcoming[0] if upcoming else parse_iso(s["next_start"])
            items.append(ui.row(f"**{s['title']}**",
                                details(repeat_label(s), f"next {stamp(nxt, 'R')}",
                                        f"playing {s['game']['name']}" if s.get("game") else None,
                                        f"replaces {name_list(s['replaces_titles'])}" if s.get("replaces_titles")
                                        else None, f"in <#{s['channel_id']}>", f"ID `{s['id']}`")))
        await self.send_list(ctx, items, "🎮 Repeating sessions",
                             f"{ui.plural(len(items), 'schedule')} · Manage with "
                             f"{await self.prefix(ctx.guild)}games recurring skip, stop or plan")

    async def _schedule_for(self, ctx: commands.Context, schedule_id: str) -> Optional[dict]:
        """A schedule by ID or name that the author may change, or None after saying why not."""
        schedules = await self.config.guild(ctx.guild).recurring()
        schedule = schedules.get(schedule_id) or find_schedule(list(schedules.values()), schedule_id)
        if schedule is None:
            await ctx.send(f"❓ No repeating session called `{ui.truncate(schedule_id, 60)}`. See "
                           f"{await self.cmd(ctx.guild, 'games recurring')}.", allowed_mentions=NO_PING)
            return None
        if not await self.can_manage(ctx.author, schedule["host_id"]):
            await ctx.send("🔒 Only the host or a game admin can change that.")
            return None
        return schedule

    @games_recurring.command(name="stop", aliases=["delete", "remove"])
    async def recurring_stop(self, ctx: commands.Context, *, schedule: str):
        """Stop a repeating session, by ID or name (host or game admin). Sessions whose card is up stay."""
        found = await self._schedule_for(ctx, schedule)
        if found is None:
            return
        rid = found["id"]
        async with self.config.guild(ctx.guild).recurring() as recurring:
            recurring.pop(rid, None)
        for s in list((await self.config.guild(ctx.guild).play_sessions()).values()):
            if s.get("recurring_id") == rid and is_pending(s):   # made ahead: its event goes too
                await self.end_session(ctx.guild, s["id"])
        self.drop_banner((found.get("event") or {}).get("banner"), rid)
        await ctx.send(f"✅ **{found['title']}** won't repeat any more.", allowed_mentions=NO_PING)

    @games_recurring.command(name="skip")
    async def recurring_skip(self, ctx: commands.Context, *, schedule: str):
        """Skip the next night of a repeating session, by ID or name (host or game admin)."""
        found = await self._schedule_for(ctx, schedule)
        if found is None:
            return
        rid = found["id"]
        upcoming = sorted((s for s in (await self.config.guild(ctx.guild).play_sessions()).values()
                           if s.get("recurring_id") == rid and not s.get("started") and s.get("starts_at")),
                          key=lambda s: s["starts_at"])
        if upcoming:   # already made: cancel it (its card says so, and its event goes)
            skipped = parse_iso(upcoming[0]["starts_at"])
            await self.end_session(ctx.guild, upcoming[0]["id"])
            following = None
        else:
            skipped = parse_iso(found["next_start"])
            following = advance_occurrence(skipped, found)
            await self._set_next_start(ctx.guild, rid, following)
        await ctx.send(f"✅ Skipping **{found['title']}** on {stamp(skipped, 'D')}."
                       + (f" The next one is {stamp(following, 'F')}." if following else
                          " The next one is set up shortly."), allowed_mentions=NO_PING)

    @games_recurring.command(name="plan", aliases=["book"])
    async def recurring_plan(self, ctx: commands.Context, *, schedule_and_date: str):
        """
        Add another night to a repeating session (host or game admin): the same as its card's Plan next button.

        Give the schedule's name or ID, then the date (its usual time is used, unless you give one).
        **Examples:** `[p]games recurring plan Star Citizen night 11/20`, `[p]games recurring plan k3x9 friday`
        """
        schedules = list((await self.config.guild(ctx.guild).recurring()).values())
        tokens = schedule_and_date.split()
        for cut in range(len(tokens) - 1, 0, -1):   # the longest name that's a schedule, then the date after it
            found = find_schedule(schedules, " ".join(tokens[:cut]))
            if found is not None:
                when = plan_date(" ".join(tokens[cut:]), found, utcnow())
                if when is None:
                    typed = " ".join(tokens[cut:])[:40]
                    return await ctx.send(ui.line(ui.ASK, f"I couldn't read the date **{typed}**.",
                                                  hint="Try 11/20, friday or 11/20 9pm."), allowed_mentions=NO_PING)
                if await self._schedule_for(ctx, found["id"]) is None:
                    return
                return await ctx.send(await self.book_night(ctx.guild, ctx.author, found["id"], when),
                                      allowed_mentions=NO_PING)
        example = await self.cmd(ctx.guild, "games recurring plan Star Citizen night 11/20")
        await ctx.send(ui.line(ui.ASK, "Which repeating session, and which date?",
                               hint=f"Like {example}. See them with {await self.cmd(ctx.guild, 'games recurring')}."),
                       allowed_mentions=NO_PING)

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
                ("Default reminders", leads_text(conf["reminders"])),
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
        footer = f"{prefix}help games admin shows how to change these · Staff only"
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

    @games_admin.command(name="reminders")
    async def admin_reminders(self, ctx: commands.Context, *, times: str):
        """
        Set the reminders new sessions get, before they start (each session can change its own with Edit).

        Up to 4 times from 5 minutes to 7 days, or `none` for just the ping at the start.
        **Examples:** `[p]games admin reminders 15m`, `[p]games admin reminders 1d, 1h`, `[p]games admin reminders none`
        """
        leads = parse_reminders(times)
        if leads is None:
            return await ctx.send(ui.line(ui.ASK, f"I couldn't use **{ui.truncate(times, 30)}** as reminders.",
                                          hint="Try 15m, or 1d, 1h (up to 4), or none."), allowed_mentions=NO_PING)
        await self.config.guild(ctx.guild).reminders.set(leads)
        await ctx.send(ui.line(ui.DONE, f"New sessions get reminders: {leads_text(leads).lower()}.",
                               hint="Sessions already set up keep theirs."))

    @games_admin.command(name="add", aliases=["import"])
    async def admin_add(self, ctx: commands.Context, *, game_names: str):
        """
        Add games to the server library. Separate them with commas or put one per line.

        Up to 25 names at a time are checked for their proper titles (typos and capitalization)
        before adding; you confirm any corrections, and any name that couldn't be confirmed.

        **Example:** `[p]games admin add Rocket League, Halo Infinite`
        """
        checked = await self.checked_names(ctx, ctx.author, parse_game_names(game_names))
        if checked is None:
            return
        added, existing = await self.add_games(ctx.guild, ctx.author, *checked[:2])
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
                    view=final_card("Cancelled. Nothing was removed.", title=title, color=ui.MUTED),
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
    #   SHORTCUTS: [p]session and [p]sessions
    # ==========================================
    # The same session commands without "games". Starting one needs `new`: plain `[p]session <text>` can't start
    # one, or a session called "join the raid" would read as the join command (the reason `[p]butler` has no
    # subcommands).

    @commands.group(name="session", invoke_without_command=True, usage="")   # the text is only for a hint
    @commands.guild_only()
    async def session_cmd(self, ctx: commands.Context, *, words: str = None):
        """
        Game sessions. On its own, brings this channel's session card down to you.

        - `[p]session new friday 9pm Raid night` starts one (`[p]session new every friday 9pm` repeats weekly)
        - `[p]session join` and `[p]session leave` (add its name if there's more than one)
        - `[p]session vote` and `[p]session end` (host or game admin)
        - `[p]session plan Star Citizen night 11/20` adds a night to a repeating session
        - `[p]sessions` lists them all
        """
        if words:   # an argument, so SpeakUp's "did you mean" stays out of it: this hint is more useful
            start = await self.cmd(ctx.guild, f"session new {ui.truncate(words, 60)}")
            return await ctx.send(ui.line(ui.ASK, f"`{ui.truncate(words.split()[0], 30)}` isn't a session command.",
                                          hint=f"To start a session, add `new`: {start}"),
                                  allowed_mentions=NO_PING)
        if await self.latest_session(ctx.guild, ctx.channel.id) is None:
            start = await self.cmd(ctx.guild, "session new 9pm Raid night")
            return await ctx.send(ui.line(ui.ASK, "There's no session in this channel.",
                                          hint=f"Start one with {start}."))
        await self.bring_here(ctx, None)

    @session_cmd.command(name="new", aliases=["create", "host"])
    async def session_new(self, ctx: commands.Context, *, time_and_title: str = None):
        """
        Start a game session people can join.

        Optionally start with a time (read in your timezone; everyone sees their own). Start with `every` to
        repeat weekly (`every first friday` for monthly). For the Discord event: attach an image for its banner,
        mention a voice channel to hold it there, and put a description on the lines after the first
        (Shift+Enter). Lines like `Length: 3h`, `Game: Star Citizen` (no vote), `Reminders: 36h, 15m`,
        `Reminder note: …` and `Replaces: Friday Night Games` set the rest. The same as `[p]games session`.

        **Examples:** `[p]session new`, `[p]session new friday 9pm Raid night`, `[p]session new in 2h Rocket League`,
        `[p]session new every friday 9pm`
        """
        await self.create_session(ctx, time_and_title)

    @session_cmd.command(name="join")
    async def session_join(self, ctx: commands.Context, *, session: str = None):
        """Join a game session. Add its name if there's more than one."""
        await self.join_or_leave(ctx, session, join=True)

    @session_cmd.command(name="leave")
    async def session_leave(self, ctx: commands.Context, *, session: str = None):
        """Leave a game session. Add its name if there's more than one."""
        await self.join_or_leave(ctx, session, join=False)

    @session_cmd.command(name="here", aliases=["bump"])
    async def session_here(self, ctx: commands.Context, *, session: str = None):
        """Bring a session card in this channel down to the bottom. Add its name if there's more than one."""
        await self.bring_here(ctx, session)

    @session_cmd.command(name="vote")
    async def session_vote(self, ctx: commands.Context, *options: str):
        """
        Start a vote on what to play for this channel's latest session (host or game admin).

        Optional: how many games each person can pick (up to 10) and how long it runs (`90s`, `3m`).
        **Examples:** `[p]session vote`, `[p]session vote 2 3m`
        """
        await ctx.invoke(self.games_sessionvote, *options)

    @session_cmd.command(name="plan", aliases=["book"])
    async def session_plan(self, ctx: commands.Context, *, schedule_and_date: str):
        """
        Add another night to a repeating session, like its card's Plan next button (host or game admin).

        **Example:** `[p]session plan Star Citizen night 11/20` (its usual time, unless you give one)
        """
        await ctx.invoke(self.recurring_plan, schedule_and_date=schedule_and_date)

    @session_cmd.command(name="end")
    async def session_end(self, ctx: commands.Context, *, session: str = None):
        """End your session in this channel, or one by name (host or game admin)."""
        if not session:
            return await ctx.invoke(self.games_endsession)
        picked = await self.pick_session(ctx, session, "end")
        if picked is None:
            return
        if not await self.can_manage(ctx.author, picked["host_id"]):
            return await ctx.send("🔒 Only the host or a game admin can end that session.")
        await self.end_session(ctx.guild, picked["id"])
        await ctx.send(f"✅ Ended **{picked['title']}**.", allowed_mentions=NO_PING)

    @commands.command(name="sessions")
    @commands.guild_only()
    async def sessions_cmd(self, ctx: commands.Context):
        """List the active game sessions, with links to their cards. The same as `[p]games sessions`."""
        await ctx.invoke(self.games_sessions)

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
                           weekly="Repeat every week (needs a day and time, like friday 9pm)",
                           description="For the Discord event: what's planned, what to bring",
                           banner="For the Discord event: a banner image (PNG, JPG, GIF or WebP)",
                           voice="For the Discord event: the voice channel it happens in",
                           length="For the Discord event: how long it runs, e.g. 2h or 90m",
                           game="Set the game ahead, so there's no vote",
                           reminders="When to remind players before it starts, e.g. 36h, 15m (or none)",
                           reminder_note="Shown on the card with every reminder, e.g. update your drivers",
                           replaces="A repeating session whose night this one takes over")
    async def slash_session(self, interaction: discord.Interaction, title: Optional[str] = None,
                            when: Optional[str] = None, weekly: bool = False, description: Optional[str] = None,
                            banner: Optional[discord.Attachment] = None,
                            voice: Optional[Union[discord.VoiceChannel, discord.StageChannel]] = None,
                            length: Optional[str] = None, game: Optional[str] = None,
                            reminders: Optional[str] = None, reminder_note: Optional[str] = None,
                            replaces: Optional[str] = None):
        details: dict = {}
        settings: dict = {}
        if reminders:
            leads = parse_reminders(reminders)
            if leads is None:
                return await self.reply(interaction, ephemeral=True, content=ui.line(
                    ui.ASK, f"I couldn't use **{ui.truncate(reminders, 30)}** as reminders.",
                    hint="Try 36h, 15m (up to 4, from 5 minutes to 7 days before), or none."))
            settings["reminders"] = leads
        if reminder_note:
            settings["reminder_note"] = reminder_note[:MAX_NOTE]
        if game:
            settings["game_name"] = game
        if replaces:
            settings["replaces_names"] = replaces
        if settings:
            details["settings"] = settings
        if description:
            details["description"] = description[:800]
        if voice is not None:
            details["voice_id"] = voice.id
        if length:
            minutes = parse_length(length)
            if minutes is None or not EVENT_MIN_MINUTES <= minutes <= EVENT_MAX_MINUTES:
                return await self.reply(interaction, ephemeral=True, content=ui.line(
                    ui.ASK, f"I couldn't use **{ui.truncate(length, 20)}** as a length.",
                    hint="Try 2h, 90m or 1h30m, between 15 minutes and a day."))
            details["minutes"] = minutes
        if banner is not None:
            await interaction.response.defer(ephemeral=True, thinking=True)   # downloading the banner
            data, problem = await self.read_banner(banner)
            if problem:
                return await self.reply(interaction, content=problem, ephemeral=True)
            details["banner_data"] = data
        if weekly:   # (create_session hands "every …" to create_recurring, after checking the settings)
            return await self.create_session(interaction, f"every {when or ''} {title or ''}", details)
        if when:
            guild, member, _ = who(interaction)
            tz, _, _ = await self.timezone_for(member)
            if parse_when(when, tz, utcnow()) is None:
                return await self.reply(interaction, content=f"❓ I couldn't read the time **{when}**. Try `9pm`, "
                                                             "`friday 9pm`, `in 2h`, or `tomorrow 8:30pm`.",
                                        ephemeral=True)
        await self.create_session(interaction, " ".join(p for p in (when, title) if p), details)

    @slash.command(name="vote", description="Start a vote on what to play for this channel's latest session")
    @app_commands.describe(picks="How many games each person can pick", minutes="How long the vote runs")
    async def slash_vote(self, interaction: discord.Interaction, picks: app_commands.Range[int, 1, 10] = 1,
                         minutes: app_commands.Range[int, 1, 60] = 2):
        await self.start_vote(interaction, None, picks, minutes * 60)

    @slash.command(name="join", description="Join a game session without finding its card")
    @app_commands.describe(session="Which session; leave empty for the one in this channel")
    async def slash_join(self, interaction: discord.Interaction, session: Optional[str] = None):
        await self.join_or_leave(interaction, session, join=True)

    @slash.command(name="leave", description="Leave a game session without finding its card")
    @app_commands.describe(session="Which session; leave empty for the one in this channel")
    async def slash_leave(self, interaction: discord.Interaction, session: Optional[str] = None):
        await self.join_or_leave(interaction, session, join=False)

    @slash.command(name="here", description="Bring this channel's session card back down to the bottom")
    @app_commands.describe(session="Which session; leave empty for the latest in this channel")
    async def slash_here(self, interaction: discord.Interaction, session: Optional[str] = None):
        await self.bring_here(interaction, session)

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
            names, appids, unconfirmed = checked
            await self.reply(interaction, content=await self.request_games_text(
                guild, channel, member, names, appids=appids, unconfirmed=unconfirmed), ephemeral=True)

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
    @slash_session.autocomplete("game")
    async def _ac_all_games(self, interaction: discord.Interaction, current: str):
        return await self._game_choices(interaction, current, "all")

    @slash_session.autocomplete("replaces")
    async def _ac_schedules(self, interaction: discord.Interaction, current: str):
        """The server's repeating sessions by title."""
        key = current.strip().lower()
        schedules = sorted((await self.config.guild(interaction.guild).recurring()).values(), key=lambda s: s["title"])
        return [app_commands.Choice(name=ui.truncate(s["title"], 100), value=s["title"][:100])
                for s in schedules if key in s["title"].lower()][:25]

    @slash_unown.autocomplete("game")
    async def _ac_owned_games(self, interaction: discord.Interaction, current: str):
        return await self._game_choices(interaction, current, "owned")

    @slash_uninstall.autocomplete("game")
    async def _ac_installed_games(self, interaction: discord.Interaction, current: str):
        return await self._game_choices(interaction, current, "installed")

    async def _session_choices(self, interaction: discord.Interaction, current: str, this_channel: bool):
        """Active sessions by title, this channel's first; other channels' are marked with the channel's name."""
        sessions = sorted((await self.config.guild(interaction.guild).play_sessions()).values(),
                          key=lambda s: (s["channel_id"] != interaction.channel_id, s["created_at"]))
        if this_channel:
            sessions = [s for s in sessions if s["channel_id"] == interaction.channel_id]
        key = current.strip().lower()
        choices = []
        for s in sessions:
            if key and key not in s["title"].lower():
                continue
            label = s["title"]
            if s["channel_id"] != interaction.channel_id:
                channel = interaction.guild.get_channel_or_thread(s["channel_id"])
                label += f" (#{channel.name})" if channel else ""
            choices.append(app_commands.Choice(name=label[:100], value=s["id"]))
        return choices[:25]

    @slash_join.autocomplete("session")
    @slash_leave.autocomplete("session")
    async def _ac_sessions(self, interaction: discord.Interaction, current: str):
        return await self._session_choices(interaction, current, this_channel=False)

    @slash_here.autocomplete("session")
    async def _ac_here_sessions(self, interaction: discord.Interaction, current: str):
        return await self._session_choices(interaction, current, this_channel=True)

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
