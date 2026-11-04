"""
SpeakUp cog for Red-DiscordBot.

The bot joining conversations, gently: it reacts when it spots something it can help with and answers only when
someone clicks, or posts a small card for things that are clearly useful. Everything can be silenced per channel
(`[p]speakup off`), per person (`[p]speakup me off`) and per feature (admins).

- Times in chat ("let's play at 9"): a clock reaction; clicking shows the time in everyone's timezone and offers to
  schedule a GameManager session.
- Steam store links: a card with the price, any sale, who in the server owns it, and Add / Want buttons.
- Article and video links: a page reaction; clicking posts a short summary (Claude's web fetch reads the page).
- Command mistakes: "Did you mean `!games own Barony`?" with a Run button.
- Reminders: `[p]remindme 2h check the oven`.
"""

import asyncio
import copy
import difflib
import logging
import re
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Dict, List, Optional, Tuple

import aiohttp
import discord
from discord.ext import tasks
from redbot.core import Config, app_commands, checks, commands
from redbot.core.bot import Red

log = logging.getLogger("red.speakup")


# ==========================================
#                CONSTANTS
# ==========================================

FEATURES = {
    "times": "Clock reaction on times in chat",
    "steam": "Cards for Steam store links",
    "links": "Summary offer on article and video links",
    "mistakes": "\"Did you mean…\" for mistyped commands",
}
TIME_EMOJI = "🕘"
LINK_EMOJI = "📄"
TRACK_SECONDS = 24 * 3600        # reactions can be clicked for this long
MAX_TRACKED = 2000
TIME_COOLDOWN = 5 * 60           # one clock reaction per channel per 5 minutes
STEAM_COOLDOWN = 6 * 3600        # one card per game per channel per 6 hours
MISTAKE_COOLDOWN = 30            # per person
SUMMARIES_PER_HOUR = 10          # per person
SUMMARY_CACHE_SECONDS = 3600     # a link's summary is reused for an hour
MAX_REMINDERS = 25               # per person
MAX_REMINDER_DAYS = 365

STEAM_APP_RE = re.compile(r"https?://store\.steampowered\.com/app/(\d+)", re.I)
URL_RE = re.compile(r"https?://[^\s<>()\"']+", re.I)
SKIP_LINK_HOSTS = ("discord.com", "discord.gg", "discordapp.com", "discordapp.net", "tenor.com", "giphy.com",
                   "imgur.com", "steampowered.com", "steamcommunity.com", "twitch.tv", "clips.twitch.tv",
                   "spotify.com", "medal.tv", "streamable.com", "reddit.com/media", "x.com", "twitter.com",
                   "twimg.com", "klipy.com", "gfycat.com", "imgflip.com", "i.redd.it", "v.redd.it", "gyazo.com",
                   "prnt.sc", "lightshot.com", "pinimg.com", "fxtwitter.com", "vxtwitter.com")
EMBED_WAIT = 3                   # seconds to let Discord attach link previews before deciding what a link is
MEDIA_EMBED_TYPES = ("image", "gifv")   # previews Discord shows as a picture or GIF: nothing to summarize
MEDIA_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".webm", ".mov", ".mp3", ".wav", ".ogg",
                    ".zip", ".exe", ".pdf")
STEAM_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAM_APP_URL = "https://store.steampowered.com/app/{}"

DAY_WORDS = {"today": 0, "tonight": 0, "tomorrow": 1, "tmrw": 1}
WEEKDAY_WORDS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
DAY_RE = re.compile(r"\b(" + "|".join([*DAY_WORDS, *WEEKDAY_WORDS]) + r")\b", re.I)
CLOCK_AMPM_RE = re.compile(r"(?<![\w:$£€#./-])(\d{1,2})(?::([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)(?![\w])", re.I)
CLOCK_24_RE = re.compile(r"(?<![\w:$£€#./-])([01]?\d|2[0-3]):([0-5]\d)(?![\w:%.]\d)", re.I)
CLOCK_AT_RE = re.compile(r"\b(?:at|@)\s*(\d{1,2})(?![\d:.,%]|\s*(?:%|min|mins|minutes|h\b|hrs|hours|kills|people|"
                         r"players|percent|dollars|bucks|games|points|pts|am\b|pm\b|a\.m|p\.m))", re.I)
STRIP_RE = re.compile(r"```.*?```|`[^`]*`|https?://\S+|<[^>]+>", re.S)
# A bare "at 9" only counts as a time when the message is about making plans.
PLANNING_RE = re.compile(r"\b(play|playing|game|games|gaming|session|raid|hop on|get on|jump on|online|join|start|"
                         r"meet|queue|lfg|on tonight|tonight|today|tomorrow|tmrw|"
                         + "|".join(WEEKDAY_WORDS) + r")\b", re.I)

RELATIVE_RE = re.compile(r"^(?:in\s+)?((?:\d+\s*(?:w|wks?|weeks?|d|days?|h|hrs?|hours?|m|mins?|minutes?)\s*"
                         r"(?:and\s+|,\s*)?)+)(?=\s|$)", re.I)
UNIT_SECONDS = {"w": 604800, "d": 86400, "h": 3600, "m": 60}


# ==========================================
#                 HELPERS
# ==========================================

def stamp(ts: float, style: str = "F") -> str:
    return f"<t:{int(ts)}:{style}>"


def find_time(text: str, tz: tzinfo, now: datetime) -> Optional[Tuple[datetime, str]]:
    """
    The first time mentioned in casual chat ("9pm", "at 9", "21:30", "friday 8:30 pm", "tonight at 9"), as a UTC
    datetime and the phrase as written, or None. Bare hours ("at 9") are read as evening unless the message says
    morning. Times without a day are the next time it's that time.
    """
    clean = STRIP_RE.sub(" ", text)
    hour = minute = None
    phrase = ""
    match = CLOCK_AMPM_RE.search(clean)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2) or 0)
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if match.group(3).lower().startswith("p") else 0)
        phrase = match.group(0).strip()
    else:
        match = CLOCK_24_RE.search(clean) or CLOCK_AT_RE.search(clean)
        if not match or (match.re is CLOCK_AT_RE and not PLANNING_RE.search(clean)):
            return None
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.re is CLOCK_24_RE else 0
        phrase = match.group(0).strip()
        if hour > 23 or (match.re is CLOCK_AT_RE and not 1 <= hour <= 12):
            return None
        if 1 <= hour <= 11 and "morning" not in clean.lower():
            hour += 12          # "at 9" in chat almost always means the evening
    day_match = DAY_RE.search(clean)
    local_now = now.astimezone(tz)
    day = local_now.date()
    if day_match:
        word = day_match.group(1).lower()
        if word in DAY_WORDS:
            day += timedelta(days=DAY_WORDS[word])
        else:
            day += timedelta(days=(WEEKDAY_WORDS[word] - local_now.weekday()) % 7)
        phrase = f"{day_match.group(1)} {phrase}"
    when = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
    if when <= local_now:
        if day_match and day_match.group(1).lower() in WEEKDAY_WORDS:
            when += timedelta(days=7)
        elif day_match:
            return None          # "today at 9am" said at noon: in the past
        else:
            day += timedelta(days=1)
            when = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
    if when - local_now > timedelta(days=8):
        return None
    return when.astimezone(timezone.utc), phrase


def summary_links(text: str) -> List[str]:
    """Links worth offering a summary for: not media, Discord, GIFs or Steam (Steam gets a card)."""
    links = []
    for url in URL_RE.findall(text):
        url = url.rstrip(".,!?;:)")
        lowered = url.lower()
        host = re.sub(r"^https?://(www\.)?", "", lowered).split("/")[0]
        if any(host == h or host.endswith("." + h) or lowered.split("://", 1)[-1].startswith(h)
               for h in SKIP_LINK_HOSTS):
            continue
        if lowered.split("?")[0].endswith(MEDIA_EXTENSIONS):
            continue
        links.append(url)
    return links


def parse_relative(text: str) -> Optional[Tuple[int, str]]:
    """'2h check the oven' / 'in 1d 3h to call mom' -> (seconds, rest)."""
    match = RELATIVE_RE.match(text.strip())
    if not match:
        return None
    seconds = sum(int(n) * UNIT_SECONDS[unit[0].lower()]
                  for n, unit in re.findall(r"(\d+)\s*([a-z]+)", match.group(1), re.I))
    return seconds, text.strip()[match.end():].strip()


def tidy_reminder(text: str) -> str:
    return re.sub(r"^(to|that|about|:|-)\s+", "", text.strip(), flags=re.I).strip()


async def steam_details(appid: int) -> Optional[dict]:
    """{"name", "price" (price_overview or None), "free"} for a Steam app, or None."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
            async with session.get(STEAM_DETAILS_URL, params={"appids": str(appid), "cc": "us", "l": "english"}) as r:
                data = await r.json(content_type=None)
        entry = (data or {}).get(str(appid)) or {}
        if not entry.get("success"):
            return None
        info = entry["data"]
        return {"name": info.get("name") or f"Steam app {appid}", "price": info.get("price_overview"),
                "free": bool(info.get("is_free"))}
    except Exception as e:
        log.debug("Steam details failed for %s: %s", appid, e)
        return None


def price_line(details: dict) -> str:
    price = details.get("price")
    if details.get("free"):
        return "🆓 Free to play"
    if not price:
        return "Not for sale right now"
    if price.get("discount_percent"):
        return (f"💸 **{price['discount_percent']}% off**: {price.get('final_formatted')} "
                f"(was {price.get('initial_formatted')})")
    return f"💲 {price.get('final_formatted')}"


def speakup_cog(interaction: discord.Interaction) -> Optional["SpeakUp"]:
    return interaction.client.get_cog("SpeakUp")


# ==========================================
#     PERSISTENT BUTTONS (survive restarts)
# ==========================================

class DismissButton(discord.ui.DynamicItem[discord.ui.Button], template=r"sp:x:(?P<uid>\d+)"):
    """Deletes the bot's message. Usable by the person it was for, or anyone who can manage messages."""

    def __init__(self, uid: int):
        super().__init__(discord.ui.Button(label="Dismiss", style=discord.ButtonStyle.secondary,
                                           custom_id=f"sp:x:{uid}"))
        self.uid = uid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["uid"]))

    async def callback(self, interaction: discord.Interaction):
        perms = interaction.channel.permissions_for(interaction.user)
        if interaction.user.id != self.uid and not perms.manage_messages:
            return await interaction.response.send_message(
                f"Only <@{self.uid}> or a moderator can dismiss this.", ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
        await interaction.response.defer()
        try:
            await interaction.message.delete()
        except discord.HTTPException:
            pass


class ScheduleButton(discord.ui.DynamicItem[discord.ui.Button], template=r"sp:sched:(?P<ts>\d+)"):
    """Schedule a GameManager session at the time someone mentioned."""

    def __init__(self, ts: int):
        super().__init__(discord.ui.Button(label="Schedule a session", emoji="🎮", style=discord.ButtonStyle.primary,
                                           custom_id=f"sp:sched:{ts}"))
        self.ts = ts

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["ts"]))

    async def callback(self, interaction: discord.Interaction):
        cog = speakup_cog(interaction)
        if cog is not None:
            await cog.schedule_from_time(interaction, self.ts)


class SteamButton(discord.ui.DynamicItem[discord.ui.Button], template=r"sp:(?P<action>own|want):(?P<appid>\d+)"):
    LOOKS = {"own": ("I own this", "🎮", discord.ButtonStyle.success),
             "want": ("I want this", "⭐", discord.ButtonStyle.primary)}

    def __init__(self, action: str, appid: int):
        label, emoji, style = self.LOOKS[action]
        super().__init__(discord.ui.Button(label=label, emoji=emoji, style=style, custom_id=f"sp:{action}:{appid}"))
        self.action, self.appid = action, appid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], int(match["appid"]))

    async def callback(self, interaction: discord.Interaction):
        cog = speakup_cog(interaction)
        if cog is not None:
            await cog.steam_button(interaction, self.action, self.appid)


class TitleModal(discord.ui.Modal, title="Schedule a session"):
    name = discord.ui.TextInput(label="What are you playing? (optional)", required=False, max_length=200,
                                placeholder="Raid night")

    def __init__(self, on_submit):
        super().__init__()
        self._on_submit = on_submit

    async def on_submit(self, interaction: discord.Interaction):
        await self._on_submit(interaction, self.name.value.strip())


class RunSuggestionView(discord.ui.View):
    """Run the suggested command as the person who mistyped it."""

    def __init__(self, cog: "SpeakUp", message: discord.Message, suggestion: str):
        super().__init__(timeout=300)
        self.cog, self.original, self.suggestion = cog, message, suggestion
        self.message: Optional[discord.Message] = None
        run = discord.ui.Button(label="Run it", emoji="▶️", style=discord.ButtonStyle.success)
        run.callback = self._run
        self.add_item(run)
        self.add_item(DismissButton(message.author.id))

    async def _run(self, interaction: discord.Interaction):
        if interaction.user.id != self.original.author.id:
            return await interaction.response.send_message("Only the person who typed it can run it.", ephemeral=True)
        self.stop()
        await interaction.response.edit_message(content=f"▶️ Running `{self.suggestion}`", view=None)
        fake = copy.copy(self.original)
        fake.content = self.suggestion
        ctx = await self.cog.bot.get_context(fake)
        if ctx.valid:
            await self.cog.bot.invoke(ctx)

    async def on_timeout(self):
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


# ==========================================
#                   COG
# ==========================================

class SpeakUp(commands.Cog):
    """The bot chiming in when it can help: times, Steam links, link summaries, command mistakes, and reminders."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=6029481735, force_registration=True)
        self.config.register_guild(features={name: True for name in FEATURES}, quiet_channels=[])
        self.config.register_user(opted_out=False)
        self.config.register_global(reminders={})
        self._tracked: Dict[int, dict] = {}            # message ID -> what its reaction offers
        self._cooldowns: Dict[tuple, float] = {}
        self._summaries: Dict[int, List[float]] = {}   # user ID -> recent summary times
        self._steam_names: Dict[int, str] = {}
        self._summary_cache: Dict[str, Tuple[float, str]] = {}   # URL -> (when, summary)
        # Right-click a message → Apps → Summarize link (bot owner: [p]slash enable "Summarize link" message)
        self.summarize_menu = app_commands.ContextMenu(name="Summarize link", callback=self.summarize_from_menu)

    async def cog_load(self):
        self.bot.add_dynamic_items(DismissButton, ScheduleButton, SteamButton)
        self.bot.tree.add_command(self.summarize_menu)
        self.reminder_loop.start()

    async def cog_unload(self):
        self.bot.remove_dynamic_items(DismissButton, ScheduleButton, SteamButton)
        self.bot.tree.remove_command(self.summarize_menu.name, type=self.summarize_menu.type)
        self.reminder_loop.cancel()

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        await self.config.user_from_id(user_id).clear()
        async with self.config.reminders() as reminders:
            for rid in [r for r, data in reminders.items() if data["user"] == user_id]:
                reminders.pop(rid)

    # ==========================================
    #               WHEN TO SPEAK
    # ==========================================

    async def allowed(self, guild: Optional[discord.Guild], channel, user: discord.abc.User, feature: str) -> bool:
        """Is `feature` on here, for this channel and this person?"""
        if guild is None or user.bot:
            return False
        conf = await self.config.guild(guild).all()
        channel_id = getattr(channel, "parent_id", None) if isinstance(channel, discord.Thread) else channel.id
        if not conf["features"].get(feature, True) or channel.id in conf["quiet_channels"] \
                or channel_id in conf["quiet_channels"]:
            return False
        if await self.config.user(user).opted_out():
            return False
        return not await self.bot.cog_disabled_in_guild(self, guild)

    def _cooldown(self, key: tuple, seconds: float) -> bool:
        """True (and starts the cooldown) if `key` is off cooldown."""
        now = time.monotonic()
        if now - self._cooldowns.get(key, -seconds) < seconds:
            return False
        self._cooldowns[key] = now
        return True

    def _track(self, message: discord.Message, data: dict):
        self._tracked[message.id] = {**data, "at": time.time()}
        if len(self._tracked) > MAX_TRACKED:
            cutoff = time.time() - TRACK_SECONDS
            self._tracked = {k: v for k, v in self._tracked.items() if v["at"] > cutoff}

    async def _tz(self, member: discord.Member) -> Tuple[tzinfo, str, bool]:
        gm = self.bot.get_cog("GameManager")
        if gm is not None:
            try:
                return await gm.timezone_for(member)
            except Exception:
                log.debug("GameManager timezone lookup failed", exc_info=True)
        return timezone.utc, "UTC", False

    async def _prefix(self, guild: Optional[discord.Guild]) -> str:
        for prefix in await self.bot.get_valid_prefixes(guild):
            if not prefix.startswith("<@"):
                return prefix
        return "!"

    # ==========================================
    #           WATCHING CONVERSATION
    # ==========================================

    @commands.Cog.listener()
    async def on_message_without_command(self, message: discord.Message):
        if message.guild is None or message.author.bot or message.webhook_id or not message.content:
            return
        if not await self.bot.ignored_channel_or_guild(message):
            return
        if not await self.bot.allowed_by_whitelist_blacklist(message.author):
            return
        channel = message.channel
        if not channel.permissions_for(message.guild.me).send_messages:
            return
        try:
            await self._steam_cards(message)
            if not await self._offer_summary(message):
                await self._offer_time(message)
        except discord.HTTPException as e:
            log.debug("Couldn't speak up in %s: %s", channel, e)

    async def _offer_time(self, message: discord.Message) -> bool:
        if not await self.allowed(message.guild, message.channel, message.author, "times"):
            return False
        tz, tz_name, personal = await self._tz(message.author)
        found = find_time(message.content, tz, datetime.now(timezone.utc))
        if found is None or not self._cooldown(("time", message.channel.id), TIME_COOLDOWN):
            return False
        when, phrase = found
        if not message.channel.permissions_for(message.guild.me).add_reactions:
            return False
        await message.add_reaction(TIME_EMOJI)
        self._track(message, {"kind": "time", "ts": int(when.timestamp()), "phrase": phrase, "tz": tz_name,
                              "personal": personal, "author": message.author.id})
        return True

    async def _offer_summary(self, message: discord.Message) -> bool:
        links = summary_links(message.content)
        if not links or len(links) > 3 or self.bot.get_cog("ClaudeChat") is None:
            return False
        if not await self.allowed(message.guild, message.channel, message.author, "links"):
            return False
        if not message.channel.permissions_for(message.guild.me).add_reactions:
            return False
        links = await self._article_links(message, links)
        if not links:
            return False
        await message.add_reaction(LINK_EMOJI)
        self._track(message, {"kind": "link", "url": links[0], "author": message.author.id})
        return True

    async def _article_links(self, message: discord.Message, links: List[str], wait: bool = True) -> List[str]:
        """
        Drop links Discord previews as a picture or GIF. Previews usually arrive a moment after the message, so
        for a brand-new message with none yet, wait briefly and look again.
        """
        embeds = message.embeds
        if not embeds and wait:
            await asyncio.sleep(EMBED_WAIT)
            try:
                embeds = (await message.channel.fetch_message(message.id)).embeds
            except (discord.HTTPException, AttributeError):
                embeds = []
        media = [e for e in embeds if e.type in MEDIA_EMBED_TYPES]
        if not media:
            return links
        if len(media) == len(embeds) and len(embeds) >= len(links):
            return []   # every link turned out to be a picture or GIF
        media_urls = {(e.url or "").rstrip("/") for e in media}
        return [url for url in links if url.rstrip("/") not in media_urls]

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id or str(payload.emoji) not in (TIME_EMOJI, LINK_EMOJI):
            return
        guild = self.bot.get_guild(payload.guild_id or 0)
        member = payload.member or (guild.get_member(payload.user_id) if guild else None)
        channel = guild.get_channel_or_thread(payload.channel_id) if guild else None
        if member is None or member.bot or channel is None:
            return
        entry = self._tracked.get(payload.message_id)
        if entry is None:
            entry = await self._rebuild_offer(channel, payload.message_id, str(payload.emoji))
        if entry is None or entry.get("done"):
            return
        if str(payload.emoji) != (TIME_EMOJI if entry["kind"] == "time" else LINK_EMOJI):
            return
        if time.time() - entry["at"] > TRACK_SECONDS:
            self._tracked.pop(payload.message_id, None)
            return
        entry["done"] = True
        message = channel.get_partial_message(payload.message_id)
        try:
            if entry["kind"] == "time":
                await self._answer_time(channel, message, entry, member)
            else:
                if not await self._answer_link(channel, message, entry, member):
                    entry["done"] = False   # let someone else try (e.g. after a rate limit)
        except discord.HTTPException as e:
            log.warning("Couldn't answer a reaction in %s: %s", channel, e)
        except Exception:
            # Anything else would otherwise fail silently: the click just does nothing.
            log.exception("Answering a %s reaction failed", entry["kind"])
            entry["done"] = False
            try:
                await channel.send("❌ Something went wrong there. The error was logged; try clicking again.",
                                   reference=message.to_reference(fail_if_not_exists=False), mention_author=False,
                                   delete_after=30)
            except discord.HTTPException:
                pass

    async def _rebuild_offer(self, channel, message_id: int, emoji: str) -> Optional[dict]:
        """
        Offers live in memory, so a reload or restart forgets them. When someone clicks one we don't know, re-read
        the message: if our own reaction is on it, work out the offer again from its text.
        """
        try:
            message = await channel.fetch_message(message_id)
        except discord.HTTPException:
            return None
        age = (datetime.now(timezone.utc) - message.created_at).total_seconds()
        if age > TRACK_SECONDS or not any(str(r.emoji) == emoji and r.me for r in message.reactions):
            return None
        if emoji == LINK_EMOJI:
            links = summary_links(message.content)
            if not links:
                return None
            data = {"kind": "link", "url": links[0], "author": message.author.id}
        else:
            member = message.guild.get_member(message.author.id) if message.guild else None
            if member is None:
                return None
            tz, tz_name, personal = await self._tz(member)
            found = find_time(message.content, tz, message.created_at)   # as of when it was said
            if found is None:
                return None
            data = {"kind": "time", "ts": int(found[0].timestamp()), "phrase": found[1], "tz": tz_name,
                    "personal": personal, "author": message.author.id}
        self._track(message, data)
        self._tracked[message.id]["at"] = message.created_at.timestamp()
        return self._tracked[message.id]

    # ---------- times ----------

    async def _answer_time(self, channel, message: discord.PartialMessage, entry: dict, clicker: discord.Member):
        ts, author = entry["ts"], channel.guild.get_member(entry["author"])
        name = author.display_name if author else "Someone"
        whose = f"{name}'s timezone" if entry["personal"] else "the server's default timezone"
        lines = [f"{TIME_EMOJI} **{entry['phrase']}** is {stamp(ts)} ({stamp(ts, 'R')}).",
                 f"-# Discord shows that in your own timezone. Read in {entry['tz']} ({whose})."]
        view = discord.ui.View(timeout=None)
        if self.bot.get_cog("GameManager") is not None and ts > time.time():
            view.add_item(ScheduleButton(ts))
        view.add_item(DismissButton(clicker.id))
        await channel.send("\n".join(lines), view=view, reference=message.to_reference(fail_if_not_exists=False),
                           mention_author=False, allowed_mentions=discord.AllowedMentions.none())

    async def schedule_from_time(self, interaction: discord.Interaction, ts: int):
        gm = self.bot.get_cog("GameManager")
        if gm is None:
            return await interaction.response.send_message("Game sessions aren't available right now.", ephemeral=True)
        if ts <= time.time() + 60:
            return await interaction.response.send_message("That time has already passed.", ephemeral=True)

        async def submit(modal_interaction: discord.Interaction, title: str):
            title = title or f"{modal_interaction.user.display_name}'s game session"
            await modal_interaction.response.defer(ephemeral=True)
            await gm.post_session(modal_interaction.guild, modal_interaction.channel, modal_interaction.user,
                                  title[:200], datetime.fromtimestamp(ts, timezone.utc))
            await modal_interaction.followup.send(f"✅ Posted **{title}** for {stamp(ts)}.", ephemeral=True)

        await interaction.response.send_modal(TitleModal(submit))

    # ---------- link summaries ----------

    def _summary_allowed(self, user: discord.abc.User) -> bool:
        """Per-person rate limit on summaries (they cost a little each). Counts the request when allowed."""
        recent = [t for t in self._summaries.get(user.id, []) if time.time() - t < 3600]
        if len(recent) >= SUMMARIES_PER_HOUR:
            return False
        self._summaries[user.id] = recent + [time.time()]
        return True

    async def summarize(self, url: str, member: discord.Member) -> Optional[str]:
        """A summary of `url` from the Claude cog, reusing one made in the last hour (clicks and menu share it)."""
        cached = self._summary_cache.get(url)
        if cached and time.time() - cached[0] < SUMMARY_CACHE_SECONDS:
            return cached[1]
        claude = self.bot.get_cog("ClaudeChat")
        if claude is None or not hasattr(claude, "summarize_link"):
            return None
        summary = await claude.summarize_link(url, member)
        if summary:
            self._summary_cache[url] = (time.time(), summary)
            if len(self._summary_cache) > 200:
                oldest = min(self._summary_cache, key=lambda u: self._summary_cache[u][0])
                self._summary_cache.pop(oldest)
        return summary

    async def summarize_from_menu(self, interaction: discord.Interaction, message: discord.Message):
        """Right-click a message → Apps → Summarize link: a summary only the person asking can see."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        if interaction.guild is None:
            return await interaction.followup.send("Use this on a message in a server.", ephemeral=True)
        if self.bot.get_cog("ClaudeChat") is None:
            return await interaction.followup.send("Summaries need the AI chat, which isn't running right now.",
                                                   ephemeral=True)
        links = await self._article_links(message, summary_links(message.content), wait=False)
        if not links:
            return await interaction.followup.send("There's no article or video link in that message to summarize.",
                                                   ephemeral=True)
        if not self._summary_allowed(interaction.user):
            return await interaction.followup.send(f"⏳ That's {SUMMARIES_PER_HOUR} summaries this hour. Try again "
                                                   "later.", ephemeral=True)
        summary = await self.summarize(links[0], interaction.user)
        if not summary:
            return await interaction.followup.send("😶 I couldn't read that page. It may block bots, need a login, or "
                                                   "be mostly video.", ephemeral=True)
        await interaction.followup.send(f"{LINK_EMOJI} **Summary** of <{links[0]}>\n{summary}", ephemeral=True,
                                        suppress_embeds=True)

    async def _answer_link(self, channel, message: discord.PartialMessage, entry: dict, clicker: discord.Member) -> bool:
        if not self._summary_allowed(clicker):
            await channel.send(f"⏳ {clicker.mention}, that's {SUMMARIES_PER_HOUR} summaries this hour. Try again later.",
                               delete_after=15, allowed_mentions=discord.AllowedMentions(users=[clicker]))
            return False
        if self.bot.get_cog("ClaudeChat") is None:
            return False
        async with channel.typing():
            summary = await self.summarize(entry["url"], clicker)
        reference = message.to_reference(fail_if_not_exists=False)
        if not summary:
            view = discord.ui.View(timeout=None)
            view.add_item(DismissButton(clicker.id))
            await channel.send("😶 I couldn't read that page. It may block bots, need a login, or be mostly video. "
                               f"Try `{await self._prefix(channel.guild)}ai` with what you want to know about it.",
                               view=view, reference=reference,
                               mention_author=False)
            return True
        view = discord.ui.View(timeout=None)
        view.add_item(DismissButton(clicker.id))
        await channel.send(f"{LINK_EMOJI} **Summary** of <{entry['url']}>\n{summary}\n-# Asked by {clicker.mention}",
                           view=view, reference=reference, mention_author=False,
                           allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True)
        return True

    # ---------- Steam cards ----------

    async def _steam_cards(self, message: discord.Message):
        appids = list(dict.fromkeys(int(a) for a in STEAM_APP_RE.findall(message.content)))[:2]
        if not appids or not await self.allowed(message.guild, message.channel, message.author, "steam"):
            return
        for appid in appids:
            if not self._cooldown(("steam", message.channel.id, appid), STEAM_COOLDOWN):
                continue
            details = await steam_details(appid)
            if details is None:
                continue
            self._steam_names[appid] = details["name"]
            embed = await self.steam_embed(message.guild, appid, details)
            view = discord.ui.View(timeout=None)
            if self.bot.get_cog("GameManager") is not None:
                view.add_item(SteamButton("own", appid))
                view.add_item(SteamButton("want", appid))
            view.add_item(DismissButton(message.author.id))
            await message.channel.send(embed=embed, view=view, reference=message.to_reference(fail_if_not_exists=False),
                                       mention_author=False, allowed_mentions=discord.AllowedMentions.none())

    async def steam_embed(self, guild: discord.Guild, appid: int, details: dict) -> discord.Embed:
        lines = [price_line(details)]
        gm = self.bot.get_cog("GameManager")
        if gm is not None:
            games = await gm.config.guild(guild).games()
            users = await gm.config.guild(guild).users()
            key = re.sub(r"[^a-z0-9]", "", details["name"].lower())
            game = next((g for g in games.values() if g.get("steam_appid") == appid), None) or next(
                (g for g in games.values() if re.sub(r"[^a-z0-9]", "", g["name"].lower()) == key), None)
            if game is None:
                lines.append("📚 Not in the server's game library yet.")
            else:
                owners, installed = [], 0
                for uid, data in users.items():
                    member = guild.get_member(int(uid))
                    if member is None:
                        continue
                    if game["id"] in data.get("installed", []):
                        owners.append(member.display_name)
                        installed += 1
                    elif game["id"] in data.get("owned", []):
                        owners.append(member.display_name)
                if owners:
                    names = ", ".join(sorted(owners, key=str.lower)[:8]) + (" …" if len(owners) > 8 else "")
                    lines.append(f"👥 Owned here by **{len(owners)}** ({names}), installed by **{installed}**")
                else:
                    lines.append("👥 In the library, but nobody has it yet.")
            entry = (await gm.config.guild(guild).wishlist()).get(str(appid))
            fans = [u for u in (entry or {}).get("users", []) if guild.get_member(int(u))]
            if fans:
                lines.append(f"⭐ Wanted by **{len(fans)}**")
        embed = discord.Embed(title=details["name"], url=STEAM_APP_URL.format(appid), description="\n".join(lines),
                              color=discord.Color.from_rgb(27, 40, 56))
        embed.set_footer(text="Steam")
        return embed

    async def steam_button(self, interaction: discord.Interaction, action: str, appid: int):
        gm = self.bot.get_cog("GameManager")
        if gm is None:
            return await interaction.response.send_message("The game library isn't available right now.",
                                                           ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild, member = interaction.guild, interaction.user
        name = self._steam_names.get(appid)
        if name is None:
            details = await steam_details(appid)
            name = details["name"] if details else None
        if name is None:
            return await interaction.followup.send("❌ I couldn't look that game up on Steam.", ephemeral=True)
        self._steam_names[appid] = name
        if action == "want":
            added, already, have = await gm.add_wants(guild, member, [(name, appid)])
            text = (f"⭐ Added **{name}** to your wishlist. You'll get a ping when it goes on sale." if added
                    else f"You already own **{name}**." if have else f"**{name}** is already on your wishlist.")
            return await interaction.followup.send(text, ephemeral=True)
        games = await gm.config.guild(guild).games()
        game = next((g for g in games.values() if g.get("steam_appid") == appid), None)
        if game is not None:
            embed, _ = await gm.change_library(guild, member, [game["name"]], "own")
        elif await gm.can_add_games(member):
            await gm.add_games(guild, member, [name], {name: appid})
            embed, _ = await gm.change_library(guild, member, [name], "own")
            embed.description = f"➕ **Added to the server library:** {name}\n" + (embed.description or "")
        else:
            embed = await gm.request_games(guild, interaction.channel, member, [name], "own", appids={name: appid})
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ---------- command mistakes ----------

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.CommandNotFound):
            await self._suggest(ctx)

    @staticmethod
    def unknown_subcommand(ctx: commands.Context) -> Optional[str]:
        """
        The word after a group that isn't one of its subcommands ("!games owns Barony" -> "owns"), else None.
        discord.py clears ctx.subcommand_passed before a group's own callback runs, so this reads the leftover
        text. Groups that take arguments of their own ("!stats week") never count: there the word is an argument.
        """
        if not isinstance(ctx.command, commands.Group) or ctx.invoked_subcommand is not None \
                or ctx.command.clean_params:
            return None
        rest = ctx.view.buffer[ctx.view.index:].strip()
        return rest.split()[0] if rest else None

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        if self.unknown_subcommand(ctx):
            await self._suggest(ctx)

    async def handles_mistakes(self, ctx: commands.Context) -> bool:
        """Other cogs' groups can stay quiet about an unknown subcommand when this will suggest one."""
        return bool(self.unknown_subcommand(ctx)) and await self.allowed(ctx.guild, ctx.channel, ctx.author,
                                                                          "mistakes")

    async def _suggest(self, ctx: commands.Context):
        if ctx.guild is None or not ctx.prefix or ctx.prefix.startswith("<@"):
            return
        typed = ctx.message.content[len(ctx.prefix):].strip()
        first = typed.split(" ")[0] if typed else ""
        if not re.fullmatch(r"[A-Za-z][\w-]{1,30}", first):
            return   # "!!!", "!?" and the like
        if not await self.allowed(ctx.guild, ctx.channel, ctx.author, "mistakes"):
            return
        if not self._cooldown(("mistake", ctx.author.id), MISTAKE_COOLDOWN):
            return
        suggestion = await self.fuzzy_suggestion(ctx, typed)
        if suggestion is None:
            claude = self.bot.get_cog("ClaudeChat")
            if claude is not None and hasattr(claude, "suggest_command"):
                async with ctx.channel.typing():
                    suggestion = await claude.suggest_command(ctx.message, f"{ctx.prefix}{typed}")
        if suggestion is None or suggestion.strip() == f"{ctx.prefix}{typed}":
            return
        view = RunSuggestionView(self, ctx.message, suggestion)
        shown = typed if len(typed) <= 60 else typed[:60] + "…"
        view.message = await ctx.send(f"❓ `{ctx.prefix}{shown}` isn't a command. Did you mean `{suggestion}`?",
                                      view=view, reference=ctx.message.to_reference(fail_if_not_exists=False),
                                      mention_author=False, allowed_mentions=discord.AllowedMentions.none())

    async def fuzzy_suggestion(self, ctx: commands.Context, typed: str) -> Optional[str]:
        """A close spelling match for the first one to three words, keeping the rest ("game owns X" -> "games own X")."""
        names: Dict[str, commands.Command] = {}
        for command in self.bot.walk_commands():
            if command.hidden:
                continue
            parent = command.full_parent_name
            for name in [command.name, *command.aliases]:
                names[f"{parent} {name}".strip().lower()] = command
        tokens = typed.split()
        for n in (3, 2, 1):
            if len(tokens) < n:
                continue
            head = " ".join(tokens[:n]).lower()
            if head in names:
                continue   # spelled right; the problem is elsewhere
            match = difflib.get_close_matches(head, list(names), n=1, cutoff=0.8)
            if not match:
                continue
            command = names[match[0]]
            try:
                if not await command.can_run(ctx, check_all_parents=True):
                    continue
            except commands.CommandError:
                continue
            rest = " ".join(tokens[n:])
            return f"{ctx.prefix}{command.qualified_name}" + (f" {rest}" if rest else "")
        return None

    # ==========================================
    #                 REMINDERS
    # ==========================================

    async def parse_reminder(self, user: discord.abc.User, guild: Optional[discord.Guild], text: str
                             ) -> Optional[Tuple[datetime, str, str]]:
        """(when, what, timezone name) for '2h check the oven', 'friday 9pm buy Helldivers', 'tomorrow 8am …'."""
        now = datetime.now(timezone.utc)
        relative = parse_relative(text)
        if relative is not None and relative[0] > 0:
            return now + timedelta(seconds=relative[0]), tidy_reminder(relative[1]), "UTC"
        gm = self.bot.get_cog("GameManager")
        module = sys.modules.get(type(gm).__module__) if gm is not None else None
        if module is None or not hasattr(module, "split_when"):
            return None
        member = guild.get_member(user.id) if guild else None
        if member is not None:
            tz, tz_name, _ = await gm.timezone_for(member)
        else:
            tz_name = await gm.config.user(user).timezone() or "UTC"
            tz = module.load_zone(tz_name)
        words = text.split()
        for skip in (0, 1):   # allow "at 9pm …" / "on friday …"
            when, rest = module.split_when(" ".join(words[skip:]), tz, now)
            if when is not None and (skip == 0 or words[0].lower() in ("at", "on")):
                return when, tidy_reminder(rest), tz_name
        return None

    @commands.command(name="remindme", aliases=["remind"])
    async def remindme(self, ctx: commands.Context, *, when_and_what: str):
        """
        Get a reminder later. Start with when, then what.

        Times can be relative (`10m`, `2h`, `1d 3h`, `2 weeks`) or, with GameManager loaded, a time in your
        timezone (`9pm`, `tomorrow 8am`, `friday 6pm`, `11/14 7pm`). The reminder pings you here, or in DMs if
        this channel is gone.

        **Examples:**
        - `[p]remindme 2h check the oven`
        - `[p]remindme friday 6pm buy Helldivers`
        - `[p]remindme tomorrow 9am to call the dentist`
        """
        parsed = await self.parse_reminder(ctx.author, ctx.guild, when_and_what)
        if parsed is None:
            return await ctx.send("❓ Start with when: `2h`, `in 30m`, `tomorrow 8am` or `friday 6pm`. For example "
                                  f"`{ctx.clean_prefix}remindme 2h check the oven`.")
        when, what, tz_name = parsed
        now = datetime.now(timezone.utc)
        if when <= now + timedelta(seconds=30):
            return await ctx.send("⚠️ That time has already passed.")
        if when > now + timedelta(days=MAX_REMINDER_DAYS):
            return await ctx.send(f"⚠️ Reminders can be up to {MAX_REMINDER_DAYS} days ahead.")
        if not what:
            return await ctx.send(f"❓ What should I remind you about? `{ctx.clean_prefix}remindme 2h check the oven`")
        async with self.config.reminders() as reminders:
            if sum(r["user"] == ctx.author.id for r in reminders.values()) >= MAX_REMINDERS:
                return await ctx.send(f"⚠️ You have {MAX_REMINDERS} reminders already. Cancel one with "
                                      f"`{ctx.clean_prefix}reminders cancel <id>`.")
            rid = secrets.token_hex(3)
            reminders[rid] = {"id": rid, "user": ctx.author.id, "guild": ctx.guild.id if ctx.guild else None,
                              "channel": ctx.channel.id, "text": what[:1000], "due": when.timestamp(),
                              "created": now.timestamp(), "jump": ctx.message.jump_url}
        await ctx.send(f"⏰ I'll remind you {stamp(when.timestamp())} ({stamp(when.timestamp(), 'R')}): **{what[:200]}**"
                       f"\n-# ID `{rid}` · `{ctx.clean_prefix}reminders` lists yours",
                       allowed_mentions=discord.AllowedMentions.none())

    @commands.group(name="reminders", invoke_without_command=True)
    async def reminders(self, ctx: commands.Context):
        """List your reminders. `cancel <id>` or `clear` removes them."""
        mine = sorted((r for r in (await self.config.reminders()).values() if r["user"] == ctx.author.id),
                      key=lambda r: r["due"])
        if not mine:
            return await ctx.send(f"You have no reminders. Set one with `{ctx.clean_prefix}remindme 2h check the oven`.")
        lines = [f"`{r['id']}` · {stamp(r['due'])} ({stamp(r['due'], 'R')}): {r['text'][:100]}" for r in mine]
        embed = discord.Embed(title="⏰ Your reminders", description="\n".join(lines)[:4000],
                              color=discord.Color.blurple())
        embed.set_footer(text=f"{ctx.clean_prefix}reminders cancel <id> · {ctx.clean_prefix}reminders clear")
        await ctx.send(embed=embed)

    @reminders.command(name="cancel", aliases=["delete", "remove"])
    async def reminders_cancel(self, ctx: commands.Context, reminder_id: str):
        """Cancel one of your reminders by its ID."""
        async with self.config.reminders() as reminders:
            reminder = reminders.get(reminder_id.strip("`"))
            if reminder is None or reminder["user"] != ctx.author.id:
                return await ctx.send(f"❌ You have no reminder `{reminder_id}`.")
            reminders.pop(reminder["id"])
        await ctx.send(f"🗑️ Cancelled: {reminder['text'][:200]}", allowed_mentions=discord.AllowedMentions.none())

    @reminders.command(name="clear")
    async def reminders_clear(self, ctx: commands.Context):
        """Cancel all of your reminders."""
        async with self.config.reminders() as reminders:
            mine = [rid for rid, r in reminders.items() if r["user"] == ctx.author.id]
            for rid in mine:
                reminders.pop(rid)
        await ctx.send(f"🗑️ Cancelled {len(mine)} reminder(s).")

    @tasks.loop(seconds=30)
    async def reminder_loop(self):
        now = time.time()
        due = [r for r in (await self.config.reminders()).values() if r["due"] <= now]
        for reminder in due:
            try:
                await self._deliver(reminder)
            except Exception:
                log.exception("Couldn't deliver reminder %s", reminder["id"])
            async with self.config.reminders() as reminders:
                reminders.pop(reminder["id"], None)

    @reminder_loop.before_loop
    async def _before_reminders(self):
        await self.bot.wait_until_red_ready()

    async def _deliver(self, reminder: dict):
        user = self.bot.get_user(reminder["user"])
        late = time.time() - reminder["due"] > 600
        text = (f"⏰ <@{reminder['user']}>, you asked me to remind you: **{reminder['text']}**\n"
                f"-# Set {stamp(reminder['created'], 'R')}" + (" (sorry it's late, I was offline)" if late else "")
                + f" · [original message]({reminder['jump']})")
        guild = self.bot.get_guild(reminder["guild"]) if reminder.get("guild") else None
        channel = guild.get_channel_or_thread(reminder["channel"]) if guild else None
        if channel is not None and (guild.get_member(reminder["user"]) is not None):
            try:
                await channel.send(text, allowed_mentions=discord.AllowedMentions(users=[discord.Object(reminder["user"])]))
                return
            except discord.HTTPException:
                pass
        if user is not None:
            try:
                await user.send(text)
            except discord.HTTPException:
                log.info("Couldn't deliver reminder %s to %s", reminder["id"], user)

    # ==========================================
    #                 SETTINGS
    # ==========================================

    @commands.group(name="speakup", invoke_without_command=True)
    @commands.guild_only()
    async def speakup(self, ctx: commands.Context):
        """
        When the bot chimes in on its own, and how to quiet it.

        The bot reacts to times in chat (click the clock to see the time in everyone's timezone), posts a card for
        Steam store links, offers a summary of article and video links (click the page icon), and suggests the
        right command when one is mistyped. It never pings anyone for these.
        """
        conf = await self.config.guild(ctx.guild).all()
        p = ctx.clean_prefix
        quiet = ctx.channel.id in conf["quiet_channels"]
        lines = [f"{'✅' if conf['features'].get(k, True) else '❌'} {label}" for k, label in FEATURES.items()]
        lines += ["", f"**This channel:** {'quiet' if quiet else 'on'} · **You:** "
                      f"{'opted out' if await self.config.user(ctx.author).opted_out() else 'on'}", "",
                  f"`{p}speakup me off` stops it for your messages · `{p}speakup off` quiets this channel (mods)",
                  f"`{p}speakup feature <{'|'.join(FEATURES)}> <on|off>` (admins)"]
        await ctx.send(embed=discord.Embed(title="🗣️ Speaking up", description="\n".join(lines),
                                           color=discord.Color.blurple()))

    @speakup.command(name="off")
    @checks.mod_or_permissions(manage_channels=True)
    async def speakup_off(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Quiet the bot in a channel (this one by default). Commands and reminders still work."""
        channel = channel or ctx.channel
        async with self.config.guild(ctx.guild).quiet_channels() as quiet:
            if channel.id not in quiet:
                quiet.append(channel.id)
        await ctx.send(f"🤫 I won't chime in on my own in {channel.mention}.")

    @speakup.command(name="on")
    @checks.mod_or_permissions(manage_channels=True)
    async def speakup_on(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Let the bot chime in again in a channel (this one by default)."""
        channel = channel or ctx.channel
        async with self.config.guild(ctx.guild).quiet_channels() as quiet:
            if channel.id in quiet:
                quiet.remove(channel.id)
        await ctx.send(f"🗣️ I'll chime in again in {channel.mention}.")

    @speakup.command(name="me")
    async def speakup_me(self, ctx: commands.Context, enabled: bool):
        """Turn it off (or back on) for your own messages: no reactions, cards or suggestions on them."""
        await self.config.user(ctx.author).opted_out.set(not enabled)
        await ctx.send("✅ I'll chime in on your messages again." if enabled
                       else "✅ I won't react to or answer your messages on my own any more.")

    @speakup.command(name="feature")
    @checks.admin_or_permissions(manage_guild=True)
    async def speakup_feature(self, ctx: commands.Context, feature: str, enabled: bool):
        """Turn one feature on or off server-wide: times, steam, links or mistakes."""
        feature = feature.lower()
        if feature not in FEATURES:
            return await ctx.send(f"❌ Features: {', '.join(f'`{f}`' for f in FEATURES)}")
        async with self.config.guild(ctx.guild).features() as features:
            features[feature] = enabled
        await ctx.send(f"✅ {FEATURES[feature]}: {'on' if enabled else 'off'}.")
