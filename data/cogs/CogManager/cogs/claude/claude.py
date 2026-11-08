import asyncio
import base64
import importlib.util
import io
import contextlib
import logging
import os
import re
import sys
import time
from collections import OrderedDict
from copy import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import anthropic
import discord
from redbot.core import Config, app_commands, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_number, pagify

log = logging.getLogger("red.claude")


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
#              MODELS & PRICING
# ==========================================

@dataclass(frozen=True)
class ModelInfo:
    name: str
    input: float        # $ per 1M input tokens
    output: float       # $ per 1M output tokens
    cache_read: float   # $ per 1M cached input tokens read
    cache_write: float  # $ per 1M input tokens written to cache (5 min TTL)
    web_search: bool    # supports the web_search_20260209 server tool
    fallback: bool      # supports server-side `fallbacks: "default"` on refusals


MODELS: Dict[str, ModelInfo] = {
    "claude-sonnet-5-5": ModelInfo("Sonnet 5.5", 2.00, 10.00, 0.20, 2.50, True, True),
    "claude-opus-5-5": ModelInfo("Opus 5.5", 4.00, 20.00, 0.20, 5.00, True, True),
    "claude-haiku-5-5": ModelInfo("Haiku 5.5", 0.10, 0.50, 0.01, 0.125, False, False),
}
MODEL_ALIASES = {
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
    "haiku": "claude-haiku-5-5",
}
DEFAULT_MODEL = "claude-sonnet-5-5"
WEB_SEARCH_COST = 0.01  # $10 per 1,000 searches
EFFORT_LEVELS = ("low", "medium", "high")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000  # covers thinking + reply; non-streaming safe
MAX_PAUSE_CONTINUATIONS = 3

DEFAULT_PERSONA = "You are friendly, helpful, and to the point."
MAX_PERSONA_CHARS = 3000

# ==========================================
#               ATTACHMENTS
# ==========================================

IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".log", ".yaml", ".yml", ".ini",
    ".cfg", ".toml", ".html", ".css", ".xml", ".sql", ".sh", ".lua", ".java", ".c", ".cpp",
    ".h", ".cs", ".go", ".rs",
}
MAX_IMAGE_BYTES = 3_750_000          # raw bytes; base64 makes it ~5 MB, the API's limit per image
MAX_IMAGE_DOWNLOAD = 25 * 1024 * 1024  # bigger uploads aren't worth downloading to shrink
IMAGE_MAX_SIDE = 1568                 # Claude scales larger images down to this anyway
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_TEXT_BYTES = 100 * 1024
MAX_ATTACHMENTS = 5

# ==========================================
#         IMAGE REQUESTS (Gemini draws)
# ==========================================

# Fast path: obvious requests go straight to Gemini without spending Claude tokens.
# Anchored at the start of the prompt so "help me draw conclusions..." stays with Claude.
POLITE = r"^((please|can you|could you|would you|will you)\s+)?"
IMAGE_NEW_TRIGGERS = [
    re.compile(POLITE + r"(draw|paint|sketch|illustrate)\s+(?!conclusion)"),
    re.compile(POLITE + r"(generate|create|make)\s+(me\s+)?an?\s+(image|picture|drawing|illustration|photo)\b"),
    re.compile(r"^(an?\s+)?(image|picture|photo|drawing)\s+of\s+"),
]
# Only checked right after an image was made in the same conversation.
IMAGE_UPDATE_TRIGGERS = [
    re.compile(r"^(update|edit|change|modify)\s+(the\s+)?(image|picture|drawing)\b"),
    re.compile(r"^(now\s+)?(make|change)\s+it\s+"),
    re.compile(r"^(now\s+)?add\s+.+\s+to\s+(the\s+)?(image|picture|drawing)\b"),
]

# Fallback: image requests the patterns miss reach Claude, which can hand them off with this tool.
MAX_IMAGES_PER_TURN = 2
IMAGE_TOOL = {
    "name": "generate_image",
    "description": (
        "Create a new image, or change the most recently generated image, and post it in the chat. "
        "Call this whenever someone wants a picture, drawing, painting, illustration, logo, meme, or other "
        "visual made or changed, however they phrase it. Do not call it to describe or analyze an image, or "
        "when people are only talking about images. This is the only way you can produce images."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "A complete, vivid image-generation prompt describing the final image: subject, style, "
                    "composition, colors, mood, and any relevant details from the conversation. When editing, "
                    "describe the whole desired result including the change (e.g. 'the same dragon, but blue')."
                ),
            },
            "edit": {
                "type": "boolean",
                "description": "true to change the most recently generated image in this conversation; false for a new image.",
            },
        },
        "required": ["prompt", "edit"],
        "additionalProperties": False,
    },
}

# ==========================================
#     THE BOT ITSELF (commands and actions)
# ==========================================

# The AI chat is also the guide to the bot (`[p]butler` is the same conversation as `[p]ai`). Its system prompt
# lists what the bot can do; the bot_commands tool returns the exact commands when a question needs them.
DEFAULT_GUIDE_MODEL = "claude-haiku-5-5"   # the quick model: typo suggestions and other cogs' fast calls
GUIDE_HELP_CHARS = 600      # help text kept per command in the reference
GUIDE_SILENT = "[silent]"   # the answer when a reply to one of the bot's messages wasn't meant for it
GUIDE_NO_COMMAND = "[no-command]"   # the flag when no command does what was asked (logged for admins)
COMMANDS_TOOL_NAME = "bot_commands"
MAX_COMMAND_MATCHES = 15    # search matches added from outside the requested sections
MAX_COMMAND_RESULT_CHARS = 40000
SEARCH_STOP_WORDS = {"the", "and", "for", "how", "can", "you", "what", "with", "does", "bot", "command", "commands",
                     "use", "want", "please", "this", "that", "there", "make"}
PRIVILEGE_NAMES = {
    commands.PrivilegeLevel.MOD: "mod",
    commands.PrivilegeLevel.ADMIN: "admin",
    commands.PrivilegeLevel.GUILD_OWNER: "server owner",
    commands.PrivilegeLevel.BOT_OWNER: "bot owner",
}

# The AI can also run commands for people. They run as the asker (same permission checks as typing
# them), and anything needing elevated rights waits for the asker to press Run.
MAX_LOOKUP_ROUNDS = 3         # rounds of lookups (bot_commands and other cogs' guide tools) per answer
MAX_ACTION_COMMANDS = 5
ACTION_STEP_TIMEOUT = 20      # seconds to wait for one command before starting the next
ACTION_CONFIRM_TIMEOUT = 120
ACTION_BLOCKED_COMMANDS = {"butler", "ai", "aithread"}
GUIDE_ACTION_TOOL = {
    "name": "run_commands",
    "description": (
        "Run bot commands for the asker, in order, exactly as if they had typed them. Use this when the asker "
        "wants the bot to do something, not when they ask how to do it."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "One or two short sentences for the asker: what you're doing, and anything left "
                               "for them or others to do afterwards.",
            },
            "commands": {
                "type": "array",
                "items": {"type": "string"},
                "description": f"1-{MAX_ACTION_COMMANDS} commands from the reference, in the order to run them, "
                               "without the prefix and with every argument filled in, e.g. "
                               "\"games install Rocket League\".",
            },
        },
        "required": ["message", "commands"],
        "additionalProperties": False,
    },
}

# ==========================================
#     GAME TITLE LOOKUP (for other cogs)
# ==========================================

# Tried in order until one accepts the web search tool; the first that works is remembered.
TITLE_SEARCHERS = [
    ("claude-haiku-5-5", {"type": "web_search_20260209", "name": "web_search", "max_uses": 2}),
    ("claude-haiku-5-5", {"type": "web_search_20250305", "name": "web_search", "max_uses": 2}),
    ("claude-sonnet-5-5", {"type": "web_search_20260209", "name": "web_search", "max_uses": 2}),
]
TITLE_TOOL = {
    "name": "report_title",
    "description": "Report the game you identified. Call this exactly once, after searching.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "found": {"type": "boolean",
                      "description": "true only if you're confident which real game they mean"},
            "title": {"type": "string",
                      "description": "The official title exactly as the publisher styles it, without ™ or ®. "
                                     "Empty if not found."},
            "steam_appid": {"type": "integer",
                            "description": "The Steam app ID from its store.steampowered.com/app/<id> URL, or 0 if "
                                           "it isn't on Steam or you aren't sure."},
        },
        "required": ["found", "title", "steam_appid"],
        "additionalProperties": False,
    },
}

# Link summaries (SpeakUp): Anthropic's web fetch reads the page, so the bot never requests user-posted URLs itself.
# Tried in order until one is accepted, like TITLE_SEARCHERS.
LINK_READERS = [
    ("claude-haiku-5-5", {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 2,
                          "max_content_tokens": 12000}),
    ("claude-haiku-5-5", {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 2,
                          "max_content_tokens": 12000}),
    ("claude-sonnet-5-5", {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 2,
                           "max_content_tokens": 12000}),
    ("claude-sonnet-5-5", {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 2}),
    # Last resort: no page fetch, but a web search usually finds the page and what it says.
    ("claude-haiku-5-5", {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}),
]
LINK_UNAVAILABLE = "UNAVAILABLE"


# ==========================================
#                 CATCH-UP
# ==========================================

CATCHUP_SCAN = 400              # messages looked back through
CATCHUP_MAX_CHARS = 24000       # transcript size sent to Claude (newest kept)
CATCHUP_CAUGHT_UP = 8           # if you spoke within this many messages, there's nothing to catch up on


def transcript(messages: List[discord.Message], bot_id: int, max_chars: int) -> str:
    """Oldest-first 'Name: text' lines, dropping the oldest lines past max_chars."""
    lines = []
    for m in messages:
        text = m.clean_content.strip()
        if m.attachments:
            text += " " + " ".join(f"[{a.content_type.split('/')[0] if a.content_type else 'file'}]"
                                   for a in m.attachments)
        if not text.strip():
            continue
        if m.author.bot:
            text = text[:300]
        name = "You (the bot)" if m.author.id == bot_id else m.author.display_name
        lines.append(f"{name}: {text}")
    out, total = [], 0
    for line in reversed(lines):
        total += len(line) + 1
        if total > max_chars:
            break
        out.append(line)
    return "\n".join(reversed(out))

NO_MENTIONS = discord.AllowedMentions(everyone=False, users=False, roles=False, replied_user=False)
MENTION_RULE = ("Discord mentions look like <@123> (a person), <@&123> (a role) or <#123> (a channel). Each message "
                "has a \"Who's who\" note saying who the speaker and every mention in it are. When you talk about "
                "someone from the conversation, mention them by writing their <@id> exactly, the first time you "
                "name them in a reply; it shows their name highlighted without pinging them. Don't mention the "
                "person you're replying to (your reply already goes to them), and never make up an ID.")
EMPTY_USAGE = {"requests": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "searches": 0, "cost": 0.0}


@dataclass
class Session:
    """In-memory conversation. History holds plain user/assistant turns only (no thinking blocks)."""
    messages: List[dict] = field(default_factory=list)
    last_active: float = 0.0
    generation: int = 0          # bumped on every reset; lets stale reply-chains be detected
    last_was_image: bool = False # enables the "make it blue" fast path
    seeded: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def reset(self):
        self.messages.clear()
        self.generation += 1
        self.last_was_image = False


@dataclass
class Turn:
    """What one Claude turn produced. Tool calls are acted on by the caller; history only gets text."""
    text: str = ""
    sources: str = ""            # the "Sources:" footer from web search citations
    stop_reason: str = ""
    images: List[dict] = field(default_factory=list)    # generate_image calls
    action: Optional[dict] = None   # a run_commands call: {"message", "commands"}
    about_bot: bool = False      # the turn looked up commands or ran them (doesn't count toward the daily limit)


def one_line(command: str) -> str:
    """A command as shown in inline code, which can't span lines: its first line, then … for the rest."""
    first, _, rest = command.partition("\n")
    return first + (" …" if rest.strip() else "")


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class ActionConfirmView(ui.ExpiringView):
    """Run / Cancel buttons for guide actions that need elevated permissions. Only the asker can press them."""

    not_yours = f"{ui.LOCKED} Only the person who asked can confirm this."
    expired_note = "Expired. Nothing was run."

    def __init__(self, user_id: int):
        super().__init__(user_id, timeout=ACTION_CONFIRM_TIMEOUT)
        self.user_id = user_id
        self.approved: Optional[bool] = None
        self.final_content: Optional[str] = None

    async def _finish(self, interaction: discord.Interaction, approved: bool, note: str):
        self.approved = approved
        self.stop()
        self.message = interaction.message
        self.final_content = f"{interaction.message.content}\n{ui.hint(note)}"
        await interaction.response.edit_message(content=self.final_content, view=None)

    @discord.ui.button(label="Run", style=discord.ButtonStyle.primary)
    async def run(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, True, "Running…")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, False, "Cancelled. Nothing was run.")

    async def mark_done(self):
        """After the commands ran: "Running…" becomes "Done." (their own output follows in the channel)."""
        if self.message is not None and self.final_content:
            await ui.edit_quietly(self.message, content=self.final_content.replace("Running…", "Done."))


def sniff_image_type(data: bytes) -> Optional[str]:
    """The real image format from the file's first bytes. Discord's content type can be wrong (a PNG labeled webp)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def prepare_image(data: bytes) -> Optional[Tuple[bytes, str]]:
    """
    (bytes, media type) ready for the API, or None if it isn't a supported image. Images that are too big in bytes
    or pixels are re-encoded as JPEG with the long side at most IMAGE_MAX_SIDE (Pillow, if installed).
    """
    media_type = sniff_image_type(data)
    if media_type is None:
        return None
    try:
        from PIL import Image
    except ImportError:
        return (data, media_type) if len(data) <= MAX_IMAGE_BYTES else None
    try:
        with Image.open(io.BytesIO(data)) as img:
            if len(data) <= MAX_IMAGE_BYTES and max(img.size) <= IMAGE_MAX_SIDE:
                return data, media_type
            img.seek(0)   # first frame of an animation
            rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        flat.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
        out = io.BytesIO()
        flat.save(out, "JPEG", quality=85, optimize=True)
        shrunk = out.getvalue()
        return (shrunk, "image/jpeg") if len(shrunk) <= MAX_IMAGE_BYTES else None
    except Exception:
        log.warning("Couldn't shrink an image", exc_info=True)
        return (data, media_type) if len(data) <= MAX_IMAGE_BYTES else None


class ClaudeChat(commands.Cog):
    """
    Chat with Anthropic's Claude, which also answers questions about the bot and runs commands for you.

    `[p]ai` talks in this channel's shared conversation, and `[p]aithread` starts a dedicated thread.
    Reply to any of my answers to keep that conversation going.

    Ask about the bot itself too ("how do I start a game vote?"), or ask it to do something.
    `[p]butler` is the same as `[p]ai`.
    """

    # What complete() and the AI chat say when Claude refuses. Other cogs compare errors against this exact text
    # (Parlor deflects a refused adventure move in character), so keep it a class attribute.
    REFUSAL = "❌ I can't help with that one."
    NO_REPLY = "❌ I didn't come up with a reply. Try rephrasing?"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=5528341907, force_registration=True)
        self.config.register_global(
            default_model=DEFAULT_MODEL,
            allowed_models=list(MODELS.keys()),
            effort="low",
            max_history=30,      # messages (user + assistant) kept per conversation
            idle_minutes=60,     # conversation resets after this much inactivity
            registered_threads=[],
            guide_model=DEFAULT_GUIDE_MODEL,
        )
        self.config.register_guild(
            persona=None,        # None = use default_persona
            default_persona=None,  # what `persona reset` returns to; None = DEFAULT_PERSONA
            web_search=True,
            guide_mentions=True, # @mentions and replies to the bot's other messages reach the AI chat
            guide_actions=True,  # the AI may run commands on the asker's behalf
            daily_limit=0,      # AI messages per user per day; 0 = unlimited
            usage=dict(EMPTY_USAGE),
            usage_since=None,
        )
        self.config.register_channel(model=None)
        self.config.register_user(model=None)   # unused since !myai was removed (2026-11-05); old values are cleared on data deletion
        self.config.register_member(usage=dict(EMPTY_USAGE), daily={"date": "", "count": 0})

        self._client: Optional[anthropic.AsyncAnthropic] = None
        self._client_key: Optional[str] = None
        self._sessions: Dict[str, Session] = {}
        # bot answer message id -> (session_key, owner_id or None, session generation)
        self._answers: "OrderedDict[int, Tuple[str, Optional[int], int]]" = OrderedDict()
        self._threads: set = set()
        self._tasks: set = set()
        self._reply_cooldown = commands.CooldownMapping.from_cooldown(1, 4, commands.BucketType.user)
        self._title_searcher = 0  # index into TITLE_SEARCHERS of the first option that worked
        self._link_reader = 0     # same for LINK_READERS

    async def cog_load(self):
        self._threads = set(await self.config.registered_threads())

    async def cog_unload(self):
        for task in self._tasks:
            task.cancel()
        if self._client is not None:
            await self._client.close()

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        await self.config.user_from_id(user_id).clear()
        for guild_id, members in (await self.config.all_members()).items():
            if user_id in members:
                await self.config.member_from_ids(guild_id, user_id).clear()

    # ==========================================
    #                 HELPERS
    # ==========================================

    async def _get_client(self) -> Optional[anthropic.AsyncAnthropic]:
        tokens = await self.bot.get_shared_api_tokens("anthropic")
        key = tokens.get("api_key")
        if not key:
            return None
        if self._client is None or key != self._client_key:
            if self._client is not None:
                await self._client.close()
            self._client = anthropic.AsyncAnthropic(api_key=key, timeout=300.0, max_retries=2)
            self._client_key = key
        return self._client

    async def _prefix(self, guild: Optional[discord.Guild]) -> str:
        for prefix in await self.bot.get_valid_prefixes(guild):
            if not prefix.startswith("<@"):
                return prefix
        return "!"

    def _resolve_model(self, name: str) -> Optional[str]:
        name = name.lower().strip()
        model = MODEL_ALIASES.get(name, name)
        return model if model in MODELS else None

    def _model_label(self, model: Optional[str]) -> str:
        info = MODELS.get(model)
        return f"{info.name} (`{model}`)" if info else f"`{model}`"

    def _session_key(self, ctx: commands.Context) -> str:
        return self._channel_key(ctx.channel)

    def _channel_key(self, channel) -> str:
        """The shared conversation `[p]ai` uses in this channel (or AI thread)."""
        return f"THREAD_{channel.id}" if channel.id in self._threads else f"CHANNEL_{channel.id}"

    def _get_session(self, key: str) -> Session:
        if key not in self._sessions:
            self._sessions[key] = Session()
        return self._sessions[key]

    def _remember_answers(self, sent: List[discord.Message], key: str, owner_id: Optional[int], generation: int):
        for msg in sent:
            self._answers[msg.id] = (key, owner_id, generation)
        while len(self._answers) > 5000:
            self._answers.popitem(last=False)

    async def _register_thread(self, thread_id: int):
        self._threads.add(thread_id)
        async with self.config.registered_threads() as threads:
            if thread_id not in threads:
                threads.append(thread_id)
            del threads[:-500]

    async def _persona(self, guild: discord.Guild) -> str:
        """The server's persona, else its saved default, else the built-in one."""
        conf = self.config.guild(guild)
        return await conf.persona() or await conf.default_persona() or DEFAULT_PERSONA

    async def _model_for(self, key: str, author: discord.Member, channel) -> str:
        if isinstance(channel, discord.Thread) and channel.parent is not None:
            channel = channel.parent
        model = await self.config.channel(channel).model() or await self.config.default_model()
        return model if model in MODELS else DEFAULT_MODEL

    async def _is_exempt(self, member: discord.Member) -> bool:
        return (
            await self.bot.is_owner(member)
            or member.guild_permissions.administrator
            or await self.bot.is_mod(member)
        )

    async def _not_set_up(self, member: discord.Member) -> str:
        """The missing-API-key notice. Only the bot owner is shown how to set it up."""
        if await self.bot.is_owner(member):
            prefix = await self._prefix(member.guild)
            return ui.line(ui.WARN, "AI chat isn't set up yet.",
                           hint=f"Add an Anthropic API key with `{prefix}set api anthropic api_key,<key>`.")
        return ui.line(ui.WARN, "AI chat isn't set up yet.", hint="Ask the bot owner to add an API key.")

    @staticmethod
    def limit_text(limit: int) -> str:
        """The one wording for a reached daily limit, with the reset time (midnight UTC) as a Discord timestamp."""
        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return ui.line(ui.WAIT, f"You've used all {ui.plural(limit, 'AI message')} for today.",
                       hint=f"The limit resets <t:{int(midnight.timestamp())}:R>.")

    async def limit_reached(self, member: discord.Member) -> Optional[int]:
        """For other cogs: the daily AI limit `member` has reached, or None (no limit, exempt, or not reached)."""
        return await self._limit_reached(member)

    async def _limit_reached(self, member: discord.Member) -> Optional[int]:
        limit = await self.config.guild(member.guild).daily_limit()
        if not limit or await self._is_exempt(member):
            return None
        daily = await self.config.member(member).daily()
        if daily["date"] == utc_today() and daily["count"] >= limit:
            return limit
        return None

    async def _count_request(self, member: discord.Member):
        async with self.config.member(member).daily() as daily:
            if daily["date"] != utc_today():
                daily["date"] = utc_today()
                daily["count"] = 0
            daily["count"] += 1

    def _usage_from(self, response, requested_model: str) -> dict:
        usage = response.usage
        info = MODELS.get(response.model) or MODELS[requested_model]
        inp = usage.input_tokens or 0
        out = usage.output_tokens or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        server_tools = getattr(usage, "server_tool_use", None)
        searches = (getattr(server_tools, "web_search_requests", 0) or 0) if server_tools else 0
        cost = (
            inp * info.input + out * info.output + cache_read * info.cache_read + cache_write * info.cache_write
        ) / 1_000_000 + searches * WEB_SEARCH_COST
        return {
            "requests": 1, "input": inp, "output": out, "cache_read": cache_read,
            "cache_write": cache_write, "searches": searches, "cost": cost,
        }

    async def _record_usage(self, member: discord.Member, usage: dict):
        guild_conf = self.config.guild(member.guild)
        if await guild_conf.usage_since() is None:
            await guild_conf.usage_since.set(utc_today())
        for scope in (guild_conf, self.config.member(member)):
            async with scope.usage() as totals:
                for k, v in usage.items():
                    totals[k] = totals.get(k, 0) + v

    def _image_generator(self):
        """The Gemini cog if it's loaded and exposes the image API, else None."""
        gemini = self.bot.get_cog("GeminiChat")
        return gemini if gemini is not None and hasattr(gemini, "generate_image") else None

    async def _system_prompt(self, guild: discord.Guild, web_search: bool, images: bool, lookups: bool = False,
                             actions: bool = False) -> str:
        persona = await self._persona(guild)
        today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
        lines = [
            f'You are {guild.me.display_name}, an AI assistant chatting in the Discord server "{guild.name}".',
            persona,
            "",
            "How to write for Discord:",
            "- Use Discord markdown: **bold**, *italics*, `inline code`, ```code blocks``` with a language tag, "
            "> quotes, - bullet lists, and # headers sparingly. Discord does not render tables, so use lists instead.",
            "- Keep replies conversational and reasonably short (a few short paragraphs at most) unless someone "
            "asks for detail or the task needs it.",
            "- Each user message starts with the speaker's display name and a colon. In shared conversations "
            "several people may be talking, so keep track of who said what and use names when it helps. "
            "Don't start your own replies with a name.",
            f"- {MENTION_RULE}",
            "- Never ping @everyone or @here.",
        ]
        if images:
            lines.append("- When someone wants an image made or changed, use the generate_image tool rather than "
                         "describing the image in text. You don't need to add a caption; the image is posted for you.")
        else:
            lines.append("- You can't create images right now. If someone asks for one, say image generation "
                         "is currently unavailable.")
        if web_search:
            lines.append("- You can search the web when you need current or specialized information. "
                         "Don't search for things you already know well.")
        if lookups:
            lines.append("- You can look up this server's data with the lookup tools (for example people's game "
                         "libraries, who owns a game, active sessions and votes, and activity stats); \"me\" means "
                         "the person talking to you.")
        lines += await self._bot_prompt_lines(guild, actions, lookups)
        lines += ["", f"Today's date is {today} (UTC)."]   # last, so the date changing keeps the rest cached
        return "\n".join(lines)

    async def _bot_prompt_lines(self, guild: discord.Guild, actions: bool, lookups: bool = False) -> List[str]:
        """The system prompt's part about the bot itself: what it can do, and how to answer questions about it."""
        prefix = await self._prefix(guild)
        lines = [
            "",
            "About this bot:",
            f"You are also the guide to {guild.me.display_name} itself, the Discord bot you speak through (command "
            f"prefix `{prefix}`). People ask in plain language what it can do and how to use it, or ask you to do "
            "things with it. What it can do, by section (main commands in brackets):",
            *await self._command_index(guild, prefix),
            "",
            "When a message is about using the bot:",
            f"- Call {COMMANDS_TOOL_NAME} first, in the same turn, and answer only from what it returns, even if "
            "you answered something similar earlier. Pick the sections above that fit, and add search words to "
            "find commands elsewhere. Never name or run a command, subcommand, argument or setting you haven't "
            "seen in its result this turn.",
            f"- If nothing fits, say so plainly and end your answer with {GUIDE_NO_COMMAND} on its own line (it's "
            "removed before posting).",
            "- Give the exact command to type in `inline code`, with a short example using realistic values when "
            "it helps. In usages, <angle brackets> are required and [square brackets] are optional; people don't "
            "type the brackets.",
            "- Keep it short: a sentence or two plus the commands, or a brief numbered list for multi-step setups.",
            "- The lookup says who's asking and their permission level. Notes like \"admin only\" or \"needs manage "
            "messages permission\" say who can run a command. Lead with what the asker can do themselves. If it "
            "needs more permission, say who can do it (a mod, an admin, the bot owner).",
            "- In commands, a <@id> mention works wherever a member is expected.",
            f"- For every detail of one command, they can run `{prefix}help <command>`.",
            "- Your personality never changes command names, arguments, game names or steps: those stay exact.",
            "",
            "Server data (who owns or has installed which games, libraries, wishlists, sessions, votes, stats):",
            "- Never state server data unless a lookup or command in this same turn returned it. Your earlier "
            "replies may be out of date or wrong, so look it up again instead of repeating them, even for a "
            "follow-up about the same thing.",
        ]
        if actions:
            lines.append("- When one command shows exactly what was asked (who owns or has installed a game, "
                         "someone's library, top or most-wanted games, active sessions, a stats report), run it with "
                         "run_commands so its real card is posted, and say at most one short sentence yourself. "
                         "Look it up with bot_commands first, like any command.")
        if lookups:
            lines.append("- When the question needs reasoning over the data (what a group can play together, who "
                         "owns a game but hasn't installed it), use the lookup tools and answer in your own words, "
                         "using only what they returned.")
        lines.append("- If you can't check something, say so and give the command that shows it, without guessing.")
        if actions:
            lines += [
                "",
                "Doing things for people:",
                "- When someone wants the bot to do something (\"add Rocket League to my games\"), look the commands "
                "up, then call run_commands with the exact commands. When they ask how to do something (\"how do I "
                "add a game?\"), explain the commands instead of running them.",
                "- Commands run as the asker, with the asker's own permissions, as if they typed them.",
                "- Use only commands from the lookup, without the prefix, with every argument filled in. Never run "
                "a command without arguments when that opens an interactive menu; fill in the arguments. The "
                "exception is a command that exists to walk someone through a menu, like games newprofile.",
                "- Prefer commands the asker can run. If something needs a permission they clearly don't have, say "
                "who can do it instead of calling the tool. Server roles can grant extra access, and the bot checks "
                "permissions again before running anything.",
                f"- Up to {MAX_ACTION_COMMANDS} commands, run in order, each finishing before the next starts. You "
                "won't see their output, so order dependent steps correctly (add a game to the server library "
                "before marking it installed).",
                "- If part of the request can't happen yet (a vote needs at least two players, so others must join "
                "the session first), do what you can and say in your message what's left.",
                "- Commands that need mod, admin, or game admin rights wait for the asker to press Run.",
                "- Only ban, kick, mute, warn, or delete messages when the asker explicitly asks for exactly that. "
                "If a request is ambiguous, ask a short question instead of guessing.",
                "- Never run the AI chat commands (ai, aithread, butler).",
            ]
        else:
            lines.append("- You can't run commands for people; tell them what to type.")
        return lines + await self._handbook_lines()

    # ==========================================
    #           BUILDING THE USER TURN
    # ==========================================

    async def _referenced_message(self, message: discord.Message) -> Optional[discord.Message]:
        ref = message.reference
        if ref is None or ref.message_id is None:
            return None
        if isinstance(ref.resolved, discord.Message):
            return ref.resolved
        try:
            return await message.channel.fetch_message(ref.message_id)
        except discord.HTTPException:
            return None

    async def _attachment_block(self, att: discord.Attachment) -> Tuple[Optional[dict], Optional[str]]:
        ctype = (att.content_type or "").split(";")[0].strip().lower()
        ext = os.path.splitext(att.filename)[1].lower()
        try:
            if ctype in IMAGE_TYPES or ext in IMAGE_EXTENSIONS:
                if att.size > MAX_IMAGE_DOWNLOAD:
                    return None, f"`{att.filename}` is too large (images up to 25 MB)"
                prepared = await asyncio.to_thread(prepare_image, await att.read())
                if prepared is None:
                    return None, f"`{att.filename}` isn't an image I can read, or is too large to shrink"
                raw, media_type = prepared
                data = base64.standard_b64encode(raw).decode("utf-8")
                return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}, None
            if ctype == "application/pdf" or ext == ".pdf":
                if att.size > MAX_PDF_BYTES:
                    return None, f"`{att.filename}` is too large (PDFs up to 20 MB)"
                data = base64.standard_b64encode(await att.read()).decode("utf-8")
                return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}, None
            if ctype.startswith("text/") or ext in TEXT_EXTENSIONS:
                if att.size > MAX_TEXT_BYTES:
                    return None, f"`{att.filename}` is too large (text files up to 100 KB)"
                text = (await att.read()).decode("utf-8", errors="replace")
                return {"type": "text", "text": f"Contents of attached file {att.filename}:\n```\n{text}\n```"}, None
        except discord.HTTPException:
            return None, f"couldn't download `{att.filename}`"
        return None, f"`{att.filename}` isn't a file type I can read"

    def _mention_note(self, message: discord.Message, ref: Optional[discord.Message] = None) -> str:
        """Who's who: the speaker, the replied-to author, and each <@id>, <@&id> and <#id> in both messages.
        Claude needs the IDs to mention people itself."""
        seen, parts = {("u", message.author.id)}, [f"<@{message.author.id}> is {message.author.display_name} (speaking)"]

        def person(m: discord.abc.User):
            if ("u", m.id) not in seen:
                seen.add(("u", m.id))
                parts.append(f"<@{m.id}> is you" if m.id == self.bot.user.id else f"<@{m.id}> is {m.display_name}")

        if ref is not None:
            person(ref.author)
        for msg in filter(None, (message, ref)):
            for m in msg.mentions:
                person(m)
            for r in msg.role_mentions:
                if ("r", r.id) not in seen:
                    seen.add(("r", r.id))
                    parts.append(f"<@&{r.id}> is the role @{r.name}")
            for c in msg.channel_mentions:
                if ("c", c.id) not in seen:
                    seen.add(("c", c.id))
                    parts.append(f"<#{c.id}> is the channel #{c.name}")
        return f"(Who's who: {'; '.join(parts)})"

    @staticmethod
    def _readable(text: str, message: discord.Message) -> str:
        """`text` with the message's user, role and channel mentions replaced by plain names."""
        for m in message.mentions:
            text = re.sub(rf"<@!?{m.id}>", f"@{m.display_name}", text)
        for r in message.role_mentions:
            text = text.replace(f"<@&{r.id}>", f"@{r.name}")
        for c in message.channel_mentions:
            text = text.replace(f"<#{c.id}>", f"#{c.name}")
        return text

    async def _build_user_turn(self, message: discord.Message, prompt: str, key: str, session: Session,
                               speaker: Optional[str] = None,
                               may_stay_silent: bool = False) -> Tuple[List[dict], List[str]]:
        context_lines = []
        attachments = list(message.attachments)

        ref = await self._referenced_message(message)
        if ref is not None:
            entry = self._answers.get(ref.id)
            already_in_history = entry is not None and entry[0] == key and entry[2] == session.generation
            if not already_in_history:
                quoted = ui.message_text(ref).strip()
                if len(quoted) > 1500:
                    quoted = quoted[:1500] + "…"
                if quoted:
                    context_lines.append(f'(Replying to {ref.author.display_name}: "{quoted}")')
                else:
                    context_lines.append(f"(Replying to a message from {ref.author.display_name})")
                attachments.extend(ref.attachments)
        context_lines.append(self._mention_note(message, ref))
        if may_stay_silent:
            context_lines.append(f"(This replies to one of the bot's own messages. If it's meant for other people "
                                 f"or needs no answer from you, like \"I'm in!\", \"nice\" or \"thanks\", reply with "
                                 f"exactly {GUIDE_SILENT} and nothing else.)")

        blocks, notes = [], []
        for att in attachments[:MAX_ATTACHMENTS]:
            block, note = await self._attachment_block(att)
            if block:
                blocks.append(block)
            if note:
                notes.append(note)
        if len(attachments) > MAX_ATTACHMENTS:
            notes.append(f"only the first {MAX_ATTACHMENTS} attachments were read")

        text = prompt or "(no message text; see the attachments)"
        speaker = speaker or message.author.display_name
        blocks.append({"type": "text", "text": f"{speaker}: " + "\n".join(context_lines + [text])})
        return blocks, notes

    async def _seed_thread_history(self, thread: discord.Thread, session: Session, before: discord.Message):
        """After a restart, rebuild an AI thread's context from its recent messages."""
        session.seeded = True
        try:
            history = [m async for m in thread.history(limit=20, before=before)]
        except discord.HTTPException:
            return
        for msg in reversed(history):
            if not msg.content:
                continue
            if msg.author == self.bot.user:
                session.messages.append({"role": "assistant", "content": msg.content})
            elif not msg.author.bot:
                session.messages.append({"role": "user", "content": f"{msg.author.display_name}: {msg.clean_content}"})
        while session.messages and session.messages[0]["role"] != "user":
            session.messages.pop(0)

    # ==========================================
    #               CORE PIPELINE
    # ==========================================

    async def _respond(self, message: discord.Message, prompt: str, key: str, *,
                       owner_id: Optional[int] = None, channel=None, may_stay_silent: bool = False):
        """
        Answer `message` in conversation `key`: chat, questions about the bot, and things to do with it.
        `channel` overrides where the answer goes (used by aithread). With `may_stay_silent` (replies to the bot's
        announcements), Claude may decide the message wasn't for it, and nothing is posted.
        """
        channel = channel or message.channel
        guild = message.guild
        prefix = await self._prefix(guild)

        client = await self._get_client()
        if client is None:
            if not may_stay_silent:
                await self._send(message, channel, await self._not_set_up(message.author))
            return

        # Over the daily limit, only questions about the bot are answered (they never counted toward it).
        limit = await self._limit_reached(message.author)
        session = self._get_session(key)
        pending: Optional[Tuple[List[str], Optional[ActionConfirmView]]] = None
        async with session.lock:
            idle = await self.config.idle_minutes()
            if session.messages and time.monotonic() - session.last_active > idle * 60:
                session.reset()
            if isinstance(channel, discord.Thread) and key.startswith("THREAD_") and not session.seeded:
                await self._seed_thread_history(channel, session, message)

            if not limit and not may_stay_silent and await self._fast_path_image(message, prompt, key, session,
                                                                                 owner_id, channel):
                return

            content, notes = await self._build_user_turn(message, prompt, key, session, may_stay_silent=may_stay_silent)
            user_turn = {"role": "user", "content": content}
            session.messages.append(user_turn)
            model = await self._model_for(key, message.author, channel)
            actions = await self.config.guild(guild).guide_actions()

            try:
                # No "typing…" for replies we might ignore; it would look like an answer that never came.
                async with (contextlib.nullcontext() if may_stay_silent else channel.typing()):
                    turn = await self._call_claude(client, model, session, message.author, actions=actions)
            except Exception as e:
                if session.messages and session.messages[-1] is user_turn:
                    session.messages.pop()
                reply, reset = self._describe_error(e, prefix)
                if reset:
                    session.reset()
                if not may_stay_silent:
                    await self._send(message, channel, reply)
                return

            text = turn.text
            if GUIDE_NO_COMMAND in text:
                text = text.replace(GUIDE_NO_COMMAND, "").strip()
                await self._record_unmet(message, prompt)
            nothing = not (text or turn.images or turn.action)
            if (text == GUIDE_SILENT and not (turn.images or turn.action)) or (may_stay_silent and nothing):
                session.messages.pop()   # a reply that wasn't for us: leave no trace
                if not may_stay_silent:
                    await self._send(message, channel, self.NO_REPLY)
                return
            if limit and not turn.about_bot:
                session.messages.pop()
                await self._send(message, channel, self.limit_text(limit))
                return
            if turn.stop_reason == "refusal" or nothing:
                session.messages.pop()
                await self._send(message, channel, self.REFUSAL if turn.stop_reason == "refusal" else self.NO_REPLY)
                return

            view, record = None, [text] if text else []
            if turn.action is not None:
                # Like image calls, no tool_result goes back: the commands post their own output, and history
                # records a plain-text note instead.
                planned, problems, confirm = await self._plan_actions(message, turn.action["commands"], prefix)
                summary = turn.action["message"] or text or "Here's what I can do."
                lines = [summary]
                if planned and confirm:
                    lines.append("These need extra permissions, so press **Run** to go ahead:")
                    lines.extend(f"`{one_line(c)}`" for c in planned)
                    view = ActionConfirmView(message.author.id)
                elif planned:
                    lines.append("-# Running: " + " · ".join(f"`{one_line(c)}`" for c in planned))
                if problems:
                    lines.append("-# Skipped: " + "; ".join(problems))
                reply = "\n".join(lines)
                record = [summary]
                if planned:
                    record.append(f"[{'Asked the user to confirm' if confirm else 'Ran'}: {'; '.join(planned)}]")
                if problems:
                    record.append(f"[Skipped: {'; '.join(problems)}]")
                pending = (planned, view) if planned else None
            else:
                reply = text + turn.sources
                if turn.stop_reason == "max_tokens":
                    reply += "\n" + ui.hint("My reply was cut off. Ask me to continue.")
            if notes:
                reply += "\n-# Skipped: " + "; ".join(notes)

            sent = []
            if reply.strip():
                # Answers about the bot often end with a handbook link; don't let Discord add a preview card.
                sent += await self._send(message, channel, reply.strip(), view=view, suppress_embeds=turn.about_bot)
                if view is not None:
                    view.message = sent[-1]

            # History stays plain text: image calls are recorded as a note Claude can refer back to.
            for call in turn.images:
                image_msg = await self._generate_image(message, channel, key, call)
                if image_msg is not None:
                    sent.append(image_msg)
                    record.append(f'[Generated an image: "{call["prompt"]}"]')
                else:
                    record.append("[Tried to generate an image, but it failed.]")

            session.messages.append({"role": "assistant", "content": "\n".join(record)})
            session.last_was_image = any(r.startswith("[Generated") for r in record)
            session.last_active = time.monotonic()
            self._trim(session, await self.config.max_history())
            self._remember_answers(sent, key, owner_id, session.generation)
            if not turn.about_bot:
                await self._count_request(message.author)

        # Outside the lock, so waiting for a confirmation doesn't hold up the conversation.
        if pending is not None:
            planned, view = pending
            if view is not None:
                await view.wait()
                if not view.approved:
                    return
            await self._run_actions(message, planned)
            if view is not None:
                await view.mark_done()

    async def _record_unmet(self, message: discord.Message, question: str):
        """Tell ActivityStats about a request no command covers, so admins can see what people look for."""
        stats = self.bot.get_cog("ActivityStats")
        if stats is not None and hasattr(stats, "record_unmet"):
            try:
                await stats.record_unmet(message.guild, message.author, question)
            except Exception:
                log.exception("Couldn't record an unanswered question about the bot")

    async def _call_claude(self, client: anthropic.AsyncAnthropic, model: str, session: Session,
                           member: discord.Member, *, actions: bool = False) -> Turn:
        info = MODELS[model]
        web_search = info.web_search and await self.config.guild(member.guild).web_search()
        images = self._image_generator() is not None
        lookups = self._lookup_tools()
        commands_tool = await self._commands_tool(member.guild)
        kwargs = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            # Its own cache breakpoint, so every conversation (and every new one after an idle reset) reads the
            # system prompt from cache instead of writing it again. Top-level caching covers the conversation.
            "system": [{"type": "text", "cache_control": {"type": "ephemeral"},
                        "text": await self._system_prompt(member.guild, web_search, images, lookups=bool(lookups),
                                                          actions=actions)}],
            "output_config": {"effort": await self.config.effort()},
            # Top-level cache_control caches the conversation prefix automatically.
            "extra_body": {"cache_control": {"type": "ephemeral"}},
        }
        tools = [commands_tool]
        if actions:
            tools.append(GUIDE_ACTION_TOOL)
        if images:
            tools.append(IMAGE_TOOL)
        if web_search:
            tools.append({"type": "web_search_20260209", "name": "web_search", "max_uses": 3})
        tools.extend(tool for tool, _ in lookups.values())
        kwargs["tools"] = tools
        if info.fallback:
            # On a safety-classifier refusal, Anthropic re-runs the request on a recommended model.
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["extra_body"]["fallbacks"] = "default"

        # Lookups get real results within this turn only; session history keeps just the final text.
        answered_here = set(lookups) | {COMMANDS_TOOL_NAME}
        messages = list(session.messages)
        blocks = []
        totals = dict(EMPTY_USAGE)
        response = None
        lookup_rounds = 0
        for _ in range(MAX_PAUSE_CONTINUATIONS + MAX_LOOKUP_ROUNDS + 1):
            response = await client.beta.messages.create(messages=messages, **kwargs)
            for k, v in self._usage_from(response, model).items():
                totals[k] += v
            blocks.extend(response.content)
            if response.stop_reason == "pause_turn":
                # A long web search paused the turn; send it back so Claude can finish.
                messages = messages + [{"role": "assistant", "content": response.content}]
                continue
            calls = [b for b in response.content if b.type == "tool_use"]
            if (response.stop_reason == "tool_use" and calls and lookup_rounds < MAX_LOOKUP_ROUNDS
                    and all(c.name in answered_here for c in calls)):
                lookup_rounds += 1
                results = await self._run_lookups(calls, lookups, member)
                messages = messages + [{"role": "assistant", "content": response.content},
                                       {"role": "user", "content": results}]
                continue
            break
        totals["requests"] = 1
        await self._record_usage(member, totals)

        turn = Turn(stop_reason=response.stop_reason)
        if response.stop_reason == "refusal":
            return turn
        # Looking up commands or server data, or running commands, makes it a question about the bot.
        turn.about_bot = any(b.type == "tool_use" and (b.name in answered_here or b.name == GUIDE_ACTION_TOOL["name"])
                             for b in blocks)

        # Image requests and commands to run are acted on instead of sending tool results back, which saves a
        # second API call. A max_tokens stop can truncate a tool input, so don't act on calls from a cut-off turn.
        if response.stop_reason == "tool_use":
            for b in response.content:
                if b.type != "tool_use" or not isinstance(b.input, dict):
                    continue
                if b.name == "generate_image":
                    prompt = b.input.get("prompt")
                    if isinstance(prompt, str) and prompt.strip():
                        turn.images.append({"prompt": prompt.strip(), "edit": bool(b.input.get("edit"))})
                elif b.name == GUIDE_ACTION_TOOL["name"] and actions and turn.action is None:
                    lines = [c for c in b.input.get("commands", []) if isinstance(c, str) and c.strip()]
                    if lines:
                        turn.action = {"message": str(b.input.get("message", "")).strip(), "commands": lines}
            turn.images = turn.images[:MAX_IMAGES_PER_TURN]

        # Drop "let me search/check that" preamble: keep the text written after the last search result or lookup.
        last_result = max((i for i, b in enumerate(blocks)
                           if b.type == "web_search_tool_result" or (b.type == "tool_use" and b.name in answered_here)),
                          default=-1)
        text_blocks = [b for b in blocks[last_result + 1:] if b.type == "text"] or [b for b in blocks if b.type == "text"]
        turn.text = "".join(b.text for b in text_blocks).strip()

        sources = OrderedDict()
        for b in text_blocks:
            for citation in getattr(b, "citations", None) or []:
                url = getattr(citation, "url", None)
                if url and url not in sources:
                    title = (getattr(citation, "title", None) or url).replace("[", "").replace("]", "")
                    sources[url] = title[:60]
        if sources:
            links = [f"[{title}](<{url}>)" for url, title in list(sources.items())[:5]]
            turn.sources = "\n\n**Sources:** " + " · ".join(links)
        return turn

    async def _fast_path_image(self, message: discord.Message, prompt: str, key: str, session: Session,
                               owner_id: Optional[int], channel) -> bool:
        """Send obvious image requests straight to Gemini, skipping Claude. Returns True if handled."""
        gemini = self._image_generator()
        if gemini is None:
            return False  # Claude will explain that images are unavailable
        lowered = prompt.strip().lower()
        is_new = any(p.match(lowered) for p in IMAGE_NEW_TRIGGERS)
        is_update = session.last_was_image and any(p.match(lowered) for p in IMAGE_UPDATE_TRIGGERS)
        if not (is_new or is_update):
            return False

        prompt = self._readable(prompt, message)  # Gemini can't resolve <@id> mentions
        async with channel.typing():
            sent = await gemini.generate_image(prompt, key, message, channel=channel, user=message.author, new=is_new)
        if sent is None:
            return True  # Gemini already posted the error

        # Note the image in Claude's history so later questions about it make sense.
        session.messages.append({"role": "user", "content": f"{message.author.display_name}: {prompt}"})
        session.messages.append({"role": "assistant", "content": f'[Generated an image: "{prompt}"]'})
        session.last_was_image = True
        session.last_active = time.monotonic()
        self._trim(session, await self.config.max_history())
        self._remember_answers([sent], key, owner_id, session.generation)
        await self._count_request(message.author)
        return True

    async def _generate_image(self, message: discord.Message, channel, key: str, call: dict) -> Optional[discord.Message]:
        """Run one generate_image tool call through the Gemini cog. Gemini posts its own errors."""
        gemini = self._image_generator()
        if gemini is None:
            return None
        # Without a live Gemini session there is nothing to edit, so start fresh from the full prompt.
        new = not (call["edit"] and key in getattr(gemini, "image_sessions", {}))
        async with channel.typing():
            return await gemini.generate_image(call["prompt"], key, message, channel=channel, user=message.author, new=new)

    def _trim(self, session: Session, max_messages: int):
        if len(session.messages) > max_messages:
            del session.messages[: len(session.messages) - max_messages]
        while session.messages and session.messages[0]["role"] != "user":
            session.messages.pop(0)

    def _describe_error(self, e: Exception, prefix: str) -> Tuple[str, bool]:
        """
        Map an exception to (user-facing message, whether to reset the conversation). The API's own error text is
        logged, never posted: it can be long, technical, or quote the request back.
        """
        if isinstance(e, anthropic.AuthenticationError):
            log.warning("Anthropic rejected the API key: %s", e)
            return ui.line(ui.WARN, "The AI's API key was rejected, so the bot owner needs to update it."), False
        if isinstance(e, anthropic.PermissionDeniedError):
            log.warning("Anthropic denied a request: %s", e)
            return (ui.line(ui.WARN, "The AI's API key isn't allowed to use this model.",
                            hint=f"A mod can pick another with `{prefix}claude channelmodel`."), False)
        if isinstance(e, anthropic.NotFoundError):
            log.warning("Anthropic model not found: %s", e)
            return (ui.line(ui.FAIL, "That model wasn't found.",
                            hint=f"Pick another with `{prefix}claude channelmodel`."), False)
        if isinstance(e, anthropic.RateLimitError):
            return ui.line(ui.WAIT, "Claude is getting too many requests right now.", "Try again in a minute."), False
        if isinstance(e, anthropic.BadRequestError):
            msg = e.message or ""
            if "credit balance" in msg.lower():
                log.warning("Anthropic account is out of credits")
                return ui.line(ui.WARN, "The AI account is out of credits, so the bot owner needs to top it up."), False
            if "too long" in msg.lower():
                return ui.line(ui.WARN, "This conversation got too long, so I started a fresh one.", "Ask again."), True
            log.warning("Claude rejected a request: %s", msg)
            return ui.line(ui.FAIL, "Claude couldn't process that request.",
                           "Try rewording it, or leave out the attachments."), False
        if isinstance(e, anthropic.APIStatusError):
            log.warning("Anthropic API error %s: %s", e.status_code, e.message)
            if e.status_code >= 500:
                return ui.line(ui.WAIT, "Claude is overloaded or having trouble right now.",
                               "Try again in a minute."), False
            return ui.line(ui.FAIL, "The AI service returned an error.",
                           "Try again shortly; the error was logged."), False
        if isinstance(e, anthropic.APITimeoutError):
            return ui.line(ui.WAIT, "Claude took too long to answer.", "Try again."), False
        if isinstance(e, anthropic.APIConnectionError):
            log.warning("Couldn't reach the Anthropic API: %s", e)
            return ui.line(ui.FAIL, "I couldn't reach Claude.", "Try again shortly."), False
        log.exception("Unexpected error in Claude cog", exc_info=e)
        return ui.line(ui.FAIL, "Something went wrong while talking to Claude.", "The error was logged."), False

    async def _send(self, message: discord.Message, channel, text: str,
                    view: Optional[discord.ui.View] = None, *, suppress_embeds: bool = False) -> List[discord.Message]:
        """Send a possibly long reply. `view` goes on the last page. `suppress_embeds` hides link previews."""
        sent = []
        pages = ui.split_text(text, 1900)
        for i, page in enumerate(pages):
            kwargs = {"allowed_mentions": NO_MENTIONS}
            if suppress_embeds:
                kwargs["suppress_embeds"] = True
            if view is not None and i == len(pages) - 1:
                kwargs["view"] = view
            if i == 0 and channel == message.channel:
                kwargs.update(reference=message.to_reference(fail_if_not_exists=False), mention_author=False)
            sent.append(await channel.send(page, **kwargs))
        return sent

    async def _retitle_thread(self, thread: discord.Thread, prompt: str, model: str, member: discord.Member):
        client = await self._get_client()
        if client is None:
            return
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=1000,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": (
                    "Write a short title (3-6 words) for a conversation that starts with the message below. "
                    "Reply with only the title.\n\n" + prompt[:1000]
                )}],
            )
            usage = self._usage_from(response, model)
            usage["requests"] = 0
            await self._record_usage(member, usage)
            title = "".join(b.text for b in response.content if b.type == "text").strip().strip('"*').strip()
            if response.stop_reason == "end_turn" and title:
                await thread.edit(name=f"🤖 {title}"[:100])
        except (anthropic.APIError, discord.HTTPException) as e:
            log.debug("Couldn't retitle thread %s: %s", thread.id, e)

    # ==========================================
    #                BOT GUIDE
    # ==========================================

    async def _permission_level(self, member: discord.Member) -> str:
        if await self.bot.is_owner(member):
            level = "bot owner"
        elif member.id == member.guild.owner_id:
            level = "server owner"
        elif await self.bot.is_admin(member):
            level = "admin"
        elif member.guild_permissions.administrator:
            level = "has Administrator permission"
        elif await self.bot.is_mod(member):
            level = "mod"
        else:
            level = "member"
        # Cogs with their own roles (e.g. GameManager's game admin) can report them via guide_member_roles().
        extra = []
        for cog in self.bot.cogs.values():
            hook = getattr(cog, "guide_member_roles", None)
            if hook is not None:
                try:
                    extra.extend(await hook(member))
                except Exception:
                    log.debug("guide_member_roles failed in %s", cog.qualified_name, exc_info=True)
        return ", ".join([level, *extra])

    async def _member_notes(self, member: discord.Member) -> List[str]:
        """Facts other cogs report about the asker via guide_member_notes() (e.g. GameManager's saved timezone)."""
        notes = []
        for cog in self.bot.cogs.values():
            hook = getattr(cog, "guide_member_notes", None)
            if hook is not None:
                try:
                    notes.extend(await hook(member))
                except Exception:
                    log.debug("guide_member_notes failed in %s", cog.qualified_name, exc_info=True)
        return notes

    def _requirement(self, command: commands.Command) -> Tuple[str, bool]:
        """
        (who can run it, whether it's bot-owner only), from the command's checks or the nearest parent's or cog's.
        Custom check functions can describe themselves with a `requirement` attribute (e.g. "game admin").
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
                    return f"{level} or {', '.join(perms)} permission", False
                if level:
                    return f"{level} only", False
                if perms:
                    return f"needs {', '.join(perms)} permission", False
            for check in getattr(obj, "checks", None) or []:
                label = getattr(check, "requirement", None)
                if label:
                    return f"{label} only", False
        return "", False

    async def _catalog_sections(self, guild: discord.Guild, prefix: str,
                                include_owner: bool) -> List[Tuple[str, List[str], List[Tuple[commands.Command, str]]]]:
        """
        Every command usable in this server, by cog: (section name, about lines, [(command, reference entry)]).
        Built fresh each time (it's cheap) and sorted, so identical bot state gives identical, cacheable text.
        """
        bot_name = guild.me.display_name

        def fill(text: str, limit: int) -> List[str]:
            text = (text or "").replace("[p]", prefix).replace("[botname]", bot_name).strip()
            if len(text) > limit:
                text = text[:limit].rstrip() + "…"
            return [line.strip() for line in text.splitlines() if line.strip()]

        def entries(cmds) -> List[Tuple[commands.Command, str]]:
            out = []
            for command in sorted(cmds, key=lambda c: c.qualified_name):
                if command.hidden or any(p.hidden for p in command.parents) or not command.is_enabled(guild):
                    continue
                requirement, owner_only = self._requirement(command)
                if owner_only and not include_owner:
                    continue
                usage = f"{prefix}{command.qualified_name} {command.signature}".strip()
                notes = []
                if command.aliases:
                    notes.append("aliases: " + ", ".join(command.aliases))
                if requirement:
                    notes.append(requirement)
                head = f"- `{usage}`" + (f" ({'; '.join(notes)})" if notes else "")
                out.append((command, "\n  ".join([head] + fill(command.help, GUIDE_HELP_CHARS))))
            return out

        sections = []
        for cog in sorted(self.bot.cogs.values(), key=lambda c: c.qualified_name.lower()):
            if await self.bot.cog_disabled_in_guild(cog, guild):
                continue
            found = entries(cog.walk_commands())
            if found:
                sections.append((cog.qualified_name, fill(getattr(cog, "help", None) or cog.description, 400), found))
        loose = entries(c for c in self.bot.walk_commands() if c.cog is None)
        if loose:
            sections.append(("Other", [], loose))
        return sections

    async def _command_catalog(self, guild: discord.Guild, prefix: str, include_owner: bool) -> str:
        """The whole command reference as plain text (for typo suggestions)."""
        return "\n\n".join("\n".join([f"## {name}", *about, *(text for _, text in found)])
                           for name, about, found in await self._catalog_sections(guild, prefix, include_owner))

    async def _command_index(self, guild: discord.Guild, prefix: str) -> List[str]:
        """One line per section for the system prompt: what it's for and its main commands."""
        lines = []
        for name, about, found in await self._catalog_sections(guild, prefix, include_owner=False):
            summary = re.split(r"(?<=[.!?])\s", " ".join(about), maxsplit=1)[0] if about else ""
            # Top-level commands, each group with its direct subcommands: "games: own, install, session…"
            groups: Dict[str, List[str]] = {}
            for command, _ in found:
                root = command.root_parent or command
                children = groups.setdefault(root.qualified_name, [])
                if command.parent is root:
                    children.append(command.name)
            shown = "; ".join(f"{root}: {', '.join(subs)}" if subs else root for root, subs in sorted(groups.items()))
            lines.append(f"- {name}: {ui.truncate(summary, 150)} [{ui.truncate(shown, 600)}]".replace(":  [", ": ["))
        return lines

    async def _commands_tool(self, guild: discord.Guild) -> dict:
        """The bot_commands lookup, with this server's section names to choose from."""
        names = [name for name, _, _ in await self._catalog_sections(guild, await self._prefix(guild), False)]
        return {
            "name": COMMANDS_TOOL_NAME,
            "description": (
                "Look up this bot's commands: exact usage, aliases, who may run each one, and what it does. Call it "
                "before answering any question about using the bot, and before run_commands. Returns the asker's "
                "permission level too."
            ),
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "array",
                        "items": {"type": "string", "enum": names or ["Other"]},
                        "description": "Sections to read in full, from the list in your instructions. Usually one "
                                       "or two.",
                    },
                    "search": {
                        "type": "string",
                        "description": "Words to find matching commands in any section, like \"remind later\". "
                                       "Empty for none.",
                    },
                },
                "required": ["sections", "search"],
                "additionalProperties": False,
            },
        }

    async def _commands_result(self, member: discord.Member, args: dict) -> str:
        """Answer a bot_commands call: the asked-for sections in full, plus search matches from the others."""
        guild = member.guild
        prefix = await self._prefix(guild)
        level = await self._permission_level(member)
        sections = await self._catalog_sections(guild, prefix, include_owner=level.startswith("bot owner"))
        wanted = {str(s).lower() for s in args.get("sections") or [] if isinstance(s, str)}
        words = [w for w in re.findall(r"[a-z0-9]+", str(args.get("search") or "").lower())
                 if len(w) >= 3 and w not in SEARCH_STOP_WORDS]

        parts = [" ".join([f"Asker: {member.display_name} ({level}). Command prefix: `{prefix}`.",
                           *await self._member_notes(member)])]
        matches = []
        for name, about, found in sections:
            if name.lower() in wanted:
                parts.append("\n".join([f"## {name}", *about, *(text for _, text in found)]))
                continue
            for command, text in found:
                names = " ".join([command.qualified_name, *command.aliases]).lower()
                score = sum(3 if w in names else 1 if w in text.lower() else 0 for w in words)
                if score:
                    matches.append((-score, command.qualified_name, text))
        if matches:
            parts.append("\n".join(["## Search matches from other sections",
                                    *(text for _, _, text in sorted(matches)[:MAX_COMMAND_MATCHES])]))
        if len(parts) == 1:
            parts.append("Nothing matched. Try other sections or search words.")
        result = "\n\n".join(parts)
        if len(result) > MAX_COMMAND_RESULT_CHARS:
            result = result[:MAX_COMMAND_RESULT_CHARS] + "\n…(cut off: ask for fewer sections)"
        return result

    async def _handbook_lines(self) -> List[str]:
        """The online handbook's pages, if the Handbook cog is loaded, so answers can link the right one."""
        handbook = self.bot.get_cog("Handbook")
        if handbook is None or not hasattr(handbook, "guide_links"):
            return []
        try:
            links = await handbook.guide_links()
        except Exception:
            log.debug("Couldn't read handbook links", exc_info=True)
            return []
        return ["", "Handbook pages (online guides, by task). When one covers a question about the bot, end your "
                    "answer with \"More: <its URL>\" on its own line:",
                *(f"- {title}: {url} ({about})" for title, url, about in links)]

    def _butler_intro(self, prefix: str, actions: bool) -> str:
        lines = [
            "🤵 Ask me anything, in plain English: how to use this bot, or anything else. For example:",
            f"- `{prefix}butler how do I find a game everyone owns?`",
            f"- `{prefix}butler how do I start a vote on what to play?`",
        ]
        if actions:
            lines.append(f"- `{prefix}butler add Rocket League to my games and mark it installed`")
            lines.append("I can run commands for you too. Anything that needs extra permissions waits for you to press Run.")
        lines.append(f"`{prefix}ai` works the same way. Reply to my answers to follow up.")
        return "\n".join(lines)

    # ---------- acting on the asker's behalf ----------

    def _find_command(self, text: str) -> Optional[commands.Command]:
        """The most specific command at the start of `text` (e.g. "games admin add Halo" -> games admin add)."""
        tokens = text.split()
        for n in range(min(len(tokens), 4), 0, -1):
            command = self.bot.get_command(" ".join(tokens[:n]))
            if command is not None:
                return command
        return None

    async def _action_context(self, message: discord.Message, content: str) -> commands.Context:
        """A context for `content` as if the asker had typed it (same author, channel, and permissions)."""
        fake = copy(message)
        fake.content = content
        return await self.bot.get_context(fake)

    async def _plan_actions(self, message: discord.Message, raw_commands: List[str],
                            prefix: str) -> Tuple[List[str], List[str], bool]:
        """Check each proposed command. Returns (runnable command lines, problems, whether to ask first)."""
        prefixes = sorted(await self.bot.get_valid_prefixes(message.guild), key=len, reverse=True)
        planned, problems, confirm = [], [], False
        for raw in raw_commands[:MAX_ACTION_COMMANDS]:
            text = raw.strip().strip("`").strip()
            for p in prefixes:
                if text.startswith(p):
                    text = text[len(p):].strip()
                    break
            text = text.lstrip("/").strip()
            if not text:
                continue
            command = self._find_command(text)
            if command is None or command.hidden:
                problems.append(f"`{prefix}{text}` isn't a command")
                continue
            if (command.root_parent or command).qualified_name in ACTION_BLOCKED_COMMANDS:
                problems.append(f"I don't run `{prefix}{command.qualified_name}` for people")
                continue
            requirement, owner_only = self._requirement(command)
            if owner_only:
                problems.append(f"`{prefix}{command.qualified_name}` is for the bot owner to run themselves")
                continue
            ctx = await self._action_context(message, prefix + text)
            try:
                allowed = await command.can_run(ctx, check_all_parents=True)
            except commands.CommandError:
                allowed = False
            if not allowed:
                problems.append(f"you don't have permission for `{prefix}{command.qualified_name}`")
                continue
            confirm = confirm or bool(requirement)
            planned.append(prefix + text)
        if len(raw_commands) > MAX_ACTION_COMMANDS:
            problems.append(f"I only run {MAX_ACTION_COMMANDS} commands at a time")
        return planned, problems, confirm

    async def _run_actions(self, message: discord.Message, lines: List[str]):
        """Invoke each command as the asker, in order. Their output and errors appear as usual."""
        for content in lines:
            ctx = await self._action_context(message, content)
            if not ctx.valid:
                continue
            task = asyncio.create_task(self.bot.invoke(ctx))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            # Interactive commands (menus, confirmations) can wait on people; don't hold up the rest forever.
            await asyncio.wait({task}, timeout=ACTION_STEP_TIMEOUT)

    # ---------- public API: official game titles ----------

    async def find_game_title(self, name: str, member: discord.Member) -> Optional[dict]:
        """
        For other cogs (GameManager): find the official title of the game someone typed, with a web search.
        Returns {"title": str, "steam_appid": int or None}, or None if it isn't a game we can identify, the
        API key is missing, or the lookup failed. Usage counts toward `member`'s server.
        """
        client = await self._get_client()
        if client is None:
            return None
        prompt = (
            "Someone in a Discord server typed the name of a video game, possibly misspelled or with the wrong "
            f"capitalization: \"{name[:150]}\"\n\n"
            "Search the web to work out which game they mean, then call report_title with its official title, "
            "written exactly as the publisher styles it (keep its capitalization and punctuation; leave out ™ and "
            "®). Include its Steam app ID if it's on Steam. If you can't tell which real game they mean, report "
            "found as false."
        )
        for index in range(self._title_searcher, len(TITLE_SEARCHERS)):
            model, search = TITLE_SEARCHERS[index]
            try:
                result = await self._search_title(client, model, search, prompt, member)
            except anthropic.BadRequestError as e:
                log.info("Game title search with %s/%s was rejected (%s); trying the next option.",
                         model, search["type"], e.message)
                continue
            except anthropic.APIError as e:
                log.warning("Game title search failed: %s", e)
                return None
            self._title_searcher = index
            return result
        return None

    async def _search_title(self, client: anthropic.AsyncAnthropic, model: str, search: dict, prompt: str,
                            member: discord.Member) -> Optional[dict]:
        messages = [{"role": "user", "content": prompt}]
        totals = dict(EMPTY_USAGE)
        response = None
        for _ in range(MAX_PAUSE_CONTINUATIONS + 1):
            response = await client.messages.create(
                model=model, max_tokens=4000, output_config={"effort": "low"},
                tools=[search, TITLE_TOOL], messages=messages,
            )
            for k, v in self._usage_from(response, model).items():
                totals[k] += v
            if response.stop_reason != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": response.content}]
        totals["requests"] = 1
        await self._record_usage(member, totals)
        for block in response.content:
            if block.type == "tool_use" and block.name == TITLE_TOOL["name"] and isinstance(block.input, dict):
                title = str(block.input.get("title") or "").strip()
                if not block.input.get("found") or not title:
                    return None
                appid = block.input.get("steam_appid")
                return {"title": title[:100], "steam_appid": appid if isinstance(appid, int) and appid > 0 else None}
        return None

    # ---------- public API: one-off Claude calls for other cogs (Parlor) ----------

    async def complete(self, member: discord.Member, channel, *, system: str, messages: List[dict],
                       fast: bool = False, max_tokens: int = 1500, persona: bool = True,
                       count_toward_limit: bool = True) -> Tuple[Optional[str], Optional[str]]:
        """
        For other cogs: one Claude call. Returns (text, None), or (None, a message to show the user).

        `fast` uses the guide model (Haiku); otherwise the channel's model. With `persona`, the server persona leads
        the system prompt. Usage counts toward `member`; with `count_toward_limit` the call also counts against
        (and respects) the server's daily AI limit. Long `messages` lists benefit from top-level prompt caching.
        """
        guild = member.guild
        prefix = await self._prefix(guild)
        client = await self._get_client()
        if client is None:
            return None, await self._not_set_up(member)
        if count_toward_limit:
            limit = await self._limit_reached(member)
            if limit:
                return None, self.limit_text(limit)
        if fast:
            model = await self.config.guide_model()
        else:
            model = await self._model_for(f"CHANNEL_{channel.id}", member, channel)
        model = model if model in MODELS else DEFAULT_MODEL
        if persona:
            system = (f'You are {guild.me.display_name}, a bot in the Discord server "{guild.name}".\n'
                      f"Your personality (set by the server's admins):\n{await self._persona(guild)}\n\n{system}")
        kwargs = dict(model=model, max_tokens=max_tokens, system=system, messages=messages,
                      output_config={"effort": await self.config.effort()},
                      extra_body={"cache_control": {"type": "ephemeral"}})
        try:
            if MODELS[model].fallback:
                # On a safety-classifier refusal, Anthropic re-runs the request on a recommended model.
                kwargs["extra_body"]["fallbacks"] = "default"
                response = await client.beta.messages.create(betas=[FALLBACK_BETA], **kwargs)
            else:
                response = await client.messages.create(**kwargs)
        except Exception as e:
            return None, self._describe_error(e, prefix)[0]
        await self._record_usage(member, self._usage_from(response, model))
        if count_toward_limit:
            await self._count_request(member)
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if response.stop_reason == "refusal":
            return None, self.REFUSAL
        if not text:
            return None, self.NO_REPLY
        return text, None

    async def image_block(self, attachment) -> Tuple[Optional[dict], Optional[str]]:
        """
        For other cogs (Parlor's critique and caption contest): an image attachment, or raw image bytes, as an API
        image block for `complete()`'s messages, checked by its real bytes and shrunk if it's too big.
        Returns (block, None), or (None, a short reason).
        """
        if isinstance(attachment, (bytes, bytearray)):
            prepared = await asyncio.to_thread(prepare_image, bytes(attachment))
            if prepared is None:
                return None, "that picture isn't one I can read"
            raw, media_type = prepared
            data = base64.standard_b64encode(raw).decode("utf-8")
            return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}, None
        ctype = (attachment.content_type or "").split(";")[0].strip().lower()
        if ctype not in IMAGE_TYPES and os.path.splitext(attachment.filename)[1].lower() not in IMAGE_EXTENSIONS:
            return None, f"`{attachment.filename}` isn't an image I can read"
        return await self._attachment_block(attachment)

    # ---------- public API: link summaries and command suggestions (SpeakUp) ----------

    async def summarize_link(self, url: str, member: discord.Member) -> Optional[str]:
        """
        For other cogs (SpeakUp): a short summary of the page at `url`, fetched by Anthropic's web fetch tool (so the
        bot never requests the URL itself). Returns None if there's no key, the page couldn't be read, or every
        option failed. Usage counts toward `member`.
        """
        client = await self._get_client()
        if client is None:
            return None
        prompt = (
            f"Read this page (fetch it, or search for it if you can't) and summarize it for a Discord chat: {url}\n\n"
            "Reply with at most three short bullet points (\"- \"), plain and factual, under 80 words in total. For "
            "a video, summarize what its title and description say it's about. No introduction and no closing line. "
            f"If the page can't be fetched or has no readable content, reply with exactly {LINK_UNAVAILABLE}."
        )
        for index in range(self._link_reader, len(LINK_READERS)):
            model, fetch = LINK_READERS[index]
            try:
                text = await self._read_link(client, model, fetch, prompt, member)
            except anthropic.BadRequestError as e:
                log.warning("Link summary with %s/%s was rejected (%s); trying the next option.",
                            model, fetch["type"], e.message)
                continue
            except anthropic.APIError as e:
                log.warning("Link summary failed: %s", e)
                return None
            self._link_reader = index
            if not text or LINK_UNAVAILABLE in text:
                log.info("Link summary: %s couldn't read %s", model, url)
                return None
            return text[:900]
        log.warning("Link summary: every reader option was rejected for %s", url)
        return None

    async def _read_link(self, client: anthropic.AsyncAnthropic, model: str, fetch: dict, prompt: str,
                         member: discord.Member) -> str:
        messages = [{"role": "user", "content": prompt}]
        totals = dict(EMPTY_USAGE)
        response = None
        for _ in range(MAX_PAUSE_CONTINUATIONS + 1):
            response = await client.messages.create(model=model, max_tokens=1000, output_config={"effort": "low"},
                                                    tools=[fetch], messages=messages)
            for k, v in self._usage_from(response, model).items():
                totals[k] += v
            if response.stop_reason != "pause_turn":
                break
            messages = messages + [{"role": "assistant", "content": response.content}]
        totals["requests"] = 1
        await self._record_usage(member, totals)
        # Only the text after the last fetch is the summary ("Let me fetch that…" comes before it).
        blocks = list(response.content)
        last_tool = max((i for i, b in enumerate(blocks) if b.type not in ("text",)), default=-1)
        return "".join(b.text for b in blocks[last_tool + 1:] if b.type == "text").strip()

    async def suggest_command(self, message: discord.Message, typed: str) -> Optional[str]:
        """
        For other cogs (SpeakUp): the command someone most likely meant when they typed one that doesn't exist,
        written as they should type it, or None. The quick model reads the whole command reference (cached).
        """
        client = await self._get_client()
        if client is None or message.guild is None:
            return None
        guild, member = message.guild, message.author
        prefix = await self._prefix(guild)
        level = await self._permission_level(member)
        model = await self.config.guide_model()
        if model not in MODELS:
            model = DEFAULT_GUIDE_MODEL
        catalog = await self._command_catalog(guild, prefix, include_owner=level.startswith("bot owner"))
        system = (f"You help people who mistype commands for {guild.me.display_name}, a Discord bot. In usages, "
                  "<angle brackets> are required and [square brackets] are optional.\n\n# Command reference\n\n"
                  + catalog)
        prompt = (f"{member.display_name} ({level}) typed `{typed[:300]}`, which isn't a command. If one command in the "
                  "reference clearly matches what they meant, reply with only that command, written exactly as they "
                  f"should type it (with the {prefix} prefix and their arguments, corrected if needed). If you aren't "
                  "sure, reply with only: none")
        try:
            response = await client.messages.create(
                model=model, max_tokens=150, output_config={"effort": "low"},
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}])
        except anthropic.APIError as e:
            log.info("Command suggestion failed: %s", e)
            return None
        totals = self._usage_from(response, model)
        await self._record_usage(member, totals)
        text = "".join(b.text for b in response.content if b.type == "text").strip().strip("`").strip()
        if not text.startswith(prefix) or "\n" in text or len(text) > 300:
            return None
        command = self.bot.get_command(text[len(prefix):].split(" ")[0])
        return text if command is not None and not command.hidden else None

    # ---------- read-only lookups offered by other cogs ----------

    def _lookup_tools(self) -> Dict[str, Tuple[dict, commands.Cog]]:
        """
        Tools other cogs offer the AI for looking things up. A cog provides `guide_tools()`, which returns
        Anthropic tool definitions, and `async guide_call_tool(name, args, asker) -> str` to answer them.
        """
        found = {}
        for cog in sorted(self.bot.cogs.values(), key=lambda c: c.qualified_name):
            if not (hasattr(cog, "guide_tools") and hasattr(cog, "guide_call_tool")):
                continue
            try:
                tools = cog.guide_tools()
            except Exception:
                log.exception("guide_tools failed in %s", cog.qualified_name)
                continue
            for tool in tools:
                name = tool.get("name")
                if name and name not in (GUIDE_ACTION_TOOL["name"], COMMANDS_TOOL_NAME) and name not in found:
                    found[name] = (tool, cog)
        return found

    async def _run_lookups(self, calls, lookups: Dict[str, Tuple[dict, commands.Cog]],
                           member: discord.Member) -> List[dict]:
        """Answer lookup tool calls: bot_commands, and other cogs' guide tools. Returns tool_result blocks."""
        results = []
        for call in calls:
            args = call.input if isinstance(call.input, dict) else {}
            try:
                if call.name == COMMANDS_TOOL_NAME:
                    output = await self._commands_result(member, args)
                else:
                    _, cog = lookups[call.name]
                    output = str(await cog.guide_call_tool(call.name, args, member))[:8000]
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": output})
            except Exception:
                log.exception("Lookup %s failed", call.name)
                results.append({"type": "tool_result", "tool_use_id": call.id, "is_error": True,
                                "content": "The lookup failed."})
        return results

    # ==========================================
    #              CHAT COMMANDS
    # ==========================================

    @commands.group(name="ai", aliases=["chat", "ask", "g"], invoke_without_command=True)
    @commands.guild_only()
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def ai(self, ctx: commands.Context, *, prompt: str = ""):
        """
        Talk to Claude in this channel's shared conversation.

        Everyone in the channel shares one conversation, so Claude can follow along
        with multiple people. Attach images, PDFs, or text files and Claude will read them.
        Reply to any of Claude's answers to keep going without typing the command.

        Ask how to use the bot, or ask it to do something, and Claude looks up the
        commands and can run them for you, with your own permissions. `[p]butler` is the same.

        Start with "draw", "paint", or "image of" to go straight to the image generator
        (Gemini). Other ways of asking for a picture work too; Claude hands them off.
        Reply "make it blue" or similar to change the last image.

        **Examples:**
        - `[p]ai what's a good name for a guild?`
        - `[p]ai how do I start a vote on what to play?`
        - `[p]ai summarize this` (with a PDF attached)
        - `[p]ai could you make us a banner with a dragon guarding a castle?`
        """
        if not prompt and not ctx.message.attachments:
            return await ctx.send_help()
        await self._respond(ctx.message, prompt, self._session_key(ctx))

    @ai.command(name="reset")
    @checks.mod_or_permissions(manage_channels=True)
    async def ai_reset(self, ctx: commands.Context):
        """Wipe this channel's shared conversation memory."""
        self._get_session(self._session_key(ctx)).reset()
        await ctx.send("✅ This channel's shared AI conversation is cleared, so the next message starts fresh.")

    @commands.command(name="aithread")
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def aithread(self, ctx: commands.Context, *, prompt: str):
        """
        Start a new thread for a conversation with Claude.

        Inside the thread, @mention me or reply to my messages to keep talking.
        """
        if isinstance(ctx.channel, discord.Thread):
            return await ctx.send(ui.line(ui.FAIL, "We're already in a thread.",
                                          "@mention me or reply to my messages to keep talking here."))
        name = "🤖 " + (prompt[:80] + "…" if len(prompt) > 80 else prompt)
        try:
            thread = await ctx.message.create_thread(name=name, auto_archive_duration=1440)
        except discord.HTTPException as e:
            log.warning("Couldn't create an AI thread in %s: %s", ctx.channel.id, e)
            return await ctx.send(ui.line(ui.FAIL, "I couldn't create a thread here.",
                                          "Check that I'm allowed to create public threads in this channel."))
        await self._register_thread(thread.id)

        model = await self._model_for(f"THREAD_{thread.id}", ctx.author, ctx.channel)
        task = asyncio.create_task(self._retitle_thread(thread, prompt, model, ctx.author))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        await self._respond(ctx.message, prompt, f"THREAD_{thread.id}", channel=thread)

    @commands.command(name="butler", aliases=["guide"])
    @commands.guild_only()
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def butler(self, ctx: commands.Context, *, request: str = ""):
        """
        Ask how to use this bot, ask it to do something, or ask anything else, in plain English.

        The same as `[p]ai`: it continues this channel's shared AI conversation. Ask "how do I…" and it
        tells you what to type; ask it to do something and it runs the commands for you, with your own
        permissions. Anything that needs mod, admin, or game admin rights waits for you to press Run.
        Reply to its answers to follow up. You can also just @mention me.

        **Examples:**
        - `[p]butler how do I start a vote on what to play?`
        - `[p]butler add Rocket League to my games and mark it installed`
        - `[p]butler set up my gaming profile`
        """
        if not request and not ctx.message.attachments:
            actions = await self.config.guild(ctx.guild).guide_actions()
            await self._send(ctx.message, ctx.channel, self._butler_intro(await self._prefix(ctx.guild), actions))
            return
        await self._respond(ctx.message, request, self._session_key(ctx))

    @commands.Cog.listener()
    async def on_message_without_command(self, message: discord.Message):
        """Reply-to-continue, @mentions, and replies to the bot's other messages."""
        if message.author.bot or message.guild is None:
            return
        if not message.content and not message.attachments:
            return

        ref = message.reference
        entry = self._answers.get(ref.message_id) if ref is not None and ref.message_id else None
        in_ai_thread = message.channel.id in self._threads
        mention = rf"<@!?{self.bot.user.id}>"
        # Replies count as mentions too, so only a typed @mention in a fresh message counts here.
        asked = ref is None and not in_ai_thread and re.search(mention, message.content) is not None
        # Replies to the bot's other messages (game announcements, results...) go to the channel's conversation,
        # which stays silent when the reply is meant for other people.
        reply_to_bot = (entry is None and not in_ai_thread and ref is not None
                        and isinstance(ref.resolved, discord.Message) and ref.resolved.author.id == self.bot.user.id)
        if entry is None and not (in_ai_thread and self.bot.user in message.mentions) and not asked and not reply_to_bot:
            return

        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        if not await self.bot.ignored_channel_or_guild(message):
            return
        if not await self.bot.allowed_by_whitelist_blacklist(message.author):
            return

        if entry is not None:
            key, owner_id, _ = entry
            command = self.ai
        elif in_ai_thread:
            key, owner_id, command = f"THREAD_{message.channel.id}", None, self.ai
        else:
            if not await self.config.guild(message.guild).guide_mentions():
                return
            key, owner_id, command = self._channel_key(message.channel), None, self.butler

        # Respect the same permission rules (Permissions cog, cog checks) as the commands.
        ctx = await self.bot.get_context(message)
        try:
            if not await command.can_run(ctx):
                return
        except commands.CommandError:
            return

        if self._reply_cooldown.get_bucket(message).update_rate_limit():
            return

        prompt = re.sub(mention, "", message.content).strip()
        await self._respond(message, prompt, key, owner_id=owner_id, may_stay_silent=reply_to_bot)

    # ==========================================
    #                 CATCH-UP
    # ==========================================
    # Moved here from the retired ButlerFun cog on 2026-11-07: it's an AI utility, not a game.

    async def build_catchup(self, member: discord.Member, channel, before: Optional[discord.Message] = None
                            ) -> Tuple[Optional[str], Optional[str]]:
        """(summary, None), or (None, a message explaining why not). `before` skips the command message itself."""
        history = []
        async for message in channel.history(limit=CATCHUP_SCAN, before=before):
            if message.author.id == member.id:
                break
            history.append(message)
        if len(history) <= CATCHUP_CAUGHT_UP:
            return None, "✅ You're caught up: you spoke here just a few messages ago."
        history.reverse()
        since = history[0].created_at
        text = transcript(history, self.bot.user.id, CATCHUP_MAX_CHARS)
        if not text:
            return None, "✅ You're caught up: there's nothing here to summarize."
        system = (f"Summarize a Discord conversation for {member.display_name}, who missed it. Use at most 8 short "
                  "bullet points (\"- \"), most important first. Say who said what, and call out plans, times, "
                  f"decisions, and anything asked of or about {member.display_name}. Plain and factual; no intro.")
        summary, error = await self.complete(member, channel, system=system,
                                             messages=[{"role": "user", "content": text}],
                                             fast=True, max_tokens=700, persona=False)
        if summary is None:
            return None, error
        header = ui.two_line(f"📰 **Catch-up for {channel.mention}**",
                             f"{ui.plural(len(history), 'message')} since <t:{int(since.timestamp())}:R>")
        return f"{header}\n{summary}", None

    @commands.command(name="catchup")
    @commands.guild_only()
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def catchup(self, ctx: commands.Context):
        """
        Get a summary of this channel since you last spoke, sent to you privately.

        The text command sends it by DM; the `/catchup` slash command shows it only to you, right here.
        """
        async with ctx.channel.typing():
            text, error = await self.build_catchup(ctx.author, ctx.channel, ctx.message)
        try:
            for page in ui.split_text(text or error):
                await ctx.author.send(page)
            await ctx.tick()
        except discord.HTTPException:
            await ctx.send("❌ I couldn't DM you. Use `/catchup` instead, which only you can see.")

    @app_commands.command(name="catchup", description="A summary of this channel since you last spoke (only you see it)")
    @app_commands.guild_only()
    async def slash_catchup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        text, error = await self.build_catchup(interaction.user, interaction.channel)
        for page in ui.split_text(text or error):
            await interaction.followup.send(page, ephemeral=True)

    # ==========================================
    #              SETTINGS COMMANDS
    # ==========================================

    @commands.group(name="claude")
    @commands.guild_only()
    async def claude(self, ctx: commands.Context):
        """Claude AI settings and usage."""

    @claude.command(name="settings")
    async def claude_settings(self, ctx: commands.Context):
        """Show the current Claude settings for you, this channel, and this server."""
        p = ctx.clean_prefix
        g = await self.config.guild(ctx.guild).all()
        # A one-line preview: the whole persona is `[p]claude persona`.
        persona = " ".join((g["persona"] or g["default_persona"] or DEFAULT_PERSONA).split())
        persona = ui.truncate(persona, 200) + ("" if g["persona"] else " *(default)*")
        channel = ctx.channel.parent if isinstance(ctx.channel, discord.Thread) and ctx.channel.parent else ctx.channel
        models = ui.settings_text([
            ("This channel", self._model_label(await self._model_for("CHANNEL", ctx.author, channel))),
            ("Bot default", self._model_label(await self.config.default_model())),
        ])
        server = ui.settings_text([
            ("Web search", g["web_search"]),
            ("@mentions and replies to my posts reach the AI", g["guide_mentions"]),
            ("AI runs commands for people", g["guide_actions"]),
            ("Daily limit", f"{ui.plural(g['daily_limit'], 'message')} per person" if g["daily_limit"]
             else "Unlimited"),
            ("Persona", persona),
        ])
        bot_wide = ui.settings_text([
            ("Effort", await self.config.effort()),
            ("Memory", f"last {await self.config.max_history()} messages, resets after "
                       f"{await self.config.idle_minutes()} idle minutes"),
            ("Quick model (typo help, summaries)", self._model_label(await self.config.guide_model())),
        ])
        container = ui.card(
            "**Models**\n" + models, "**This server**\n" + server, "**Bot-wide**\n" + bot_wide, ui.SEPARATOR,
            title="🤖 AI chat settings", color=ui.BRAND,
            footer=f"{p}help claude shows how to change these")
        await ui.send_card(ctx, ui.CardView(container))

    @claude.command(name="models")
    async def claude_models(self, ctx: commands.Context):
        """List the available Claude models and their prices."""
        allowed = await self.config.allowed_models()
        default = await self.config.default_model()
        alias_for = {v: k for k, v in MODEL_ALIASES.items()}
        rows = []
        for model, info in MODELS.items():
            # The model, then its alias, prices and status underneath.
            detail = [f"`{alias_for.get(model, model)}`",
                      f"${info.input:g} in, ${info.output:g} out per 1M tokens",
                      "allowed" if model in allowed else "not allowed"]
            if model == default:
                detail.append("default")
            if not info.web_search:
                detail.append("no web search")
            rows.append(ui.row(f"**{info.name}**", " · ".join(detail)))
        await ui.Board("🤖 AI models", rows, color=ui.BRAND,
                       footer=f"Channel managers pick from the allowed ones with {ctx.clean_prefix}claude channelmodel").send(ctx)

    @claude.command(name="channelmodel")
    @checks.mod_or_permissions(manage_channels=True)
    async def claude_channelmodel(self, ctx: commands.Context, model: str):
        """Pick the model for this channel's shared conversation and its AI threads. Use `reset` for the default."""
        channel = ctx.channel.parent if isinstance(ctx.channel, discord.Thread) and ctx.channel.parent else ctx.channel
        if model.lower() == "reset":
            await self.config.channel(channel).model.set(None)
            return await ctx.send(f"✅ {channel.mention} now uses the default model.")
        resolved = self._resolve_model(model)
        if resolved is None or resolved not in await self.config.allowed_models():
            return await ctx.send(ui.line(ui.FAIL, "That model isn't available.",
                                          f"`{ctx.clean_prefix}claude models` lists the allowed ones."))
        await self.config.channel(channel).model.set(resolved)
        await ctx.send(f"✅ {channel.mention} now uses {self._model_label(resolved)}.")

    @claude.command(name="defaultmodel")
    @checks.is_owner()
    async def claude_defaultmodel(self, ctx: commands.Context, model: str):
        """Set the bot-wide default model."""
        resolved = self._resolve_model(model)
        if resolved is None:
            return await ctx.send(f"❌ Unknown model. See `{ctx.clean_prefix}claude models`.")
        await self.config.default_model.set(resolved)
        await ctx.send(f"✅ Default model is now {self._model_label(resolved)}.")

    @claude.command(name="allowmodel")
    @checks.is_owner()
    async def claude_allowmodel(self, ctx: commands.Context, model: str):
        """Let channel managers choose a model for their channels."""
        resolved = self._resolve_model(model)
        if resolved is None:
            return await ctx.send(f"❌ Unknown model. See `{ctx.clean_prefix}claude models`.")
        async with self.config.allowed_models() as allowed:
            if resolved not in allowed:
                allowed.append(resolved)
        await ctx.send(f"✅ {self._model_label(resolved)} can now be chosen.")

    @claude.command(name="disallowmodel")
    @checks.is_owner()
    async def claude_disallowmodel(self, ctx: commands.Context, model: str):
        """
        Stop a model from being chosen.

        Channels that had picked it keep it until a channel manager changes it.
        """
        resolved = self._resolve_model(model)
        if resolved is None:
            names = ", ".join(f"`{alias}`" for alias in MODEL_ALIASES)
            return await ctx.send(ui.line(ui.ASK, f"There's no model called `{model[:60]}`.",
                                          hint=f"Use one of {names}, or a full model ID from "
                                               f"`{ctx.clean_prefix}claude models`."))
        async with self.config.allowed_models() as allowed:
            was_allowed = resolved in allowed
            if was_allowed:
                allowed.remove(resolved)
        if not was_allowed:
            return await ctx.send(ui.line(ui.WARN, f"{self._model_label(resolved)} already can't be chosen."))
        await ctx.send(ui.line(ui.DONE, f"{self._model_label(resolved)} can no longer be chosen.",
                               "Channels already using it keep it until someone changes it."))

    @claude.command(name="effort")
    @checks.is_owner()
    async def claude_effort(self, ctx: commands.Context, level: str):
        """
        Set how hard Claude thinks before answering: `low`, `medium`, or `high`.

        Higher effort gives better answers to hard questions but is slower and costs more.
        `low` suits casual chat.
        """
        level = level.lower()
        if level not in EFFORT_LEVELS:
            return await ctx.send(ui.line(ui.ASK, "Effort can be `low`, `medium` or `high`."))
        await self.config.effort.set(level)
        await ctx.send(f"✅ Effort set to **{level}**.")

    @claude.command(name="memory")
    @checks.is_owner()
    async def claude_memory(self, ctx: commands.Context, max_messages: int, idle_minutes: int):
        """
        Set how much Claude remembers.

        `max_messages`: how many recent messages (yours and Claude's) to keep (4-100).
        `idle_minutes`: start fresh after this long without activity (5-1440).
        """
        if not 4 <= max_messages <= 100 or not 5 <= idle_minutes <= 1440:
            return await ctx.send(ui.line(ui.ASK, "Use 4–100 messages and 5–1440 idle minutes."))
        await self.config.max_history.set(max_messages)
        await self.config.idle_minutes.set(idle_minutes)
        await ctx.send(ui.line(ui.DONE, f"Claude now remembers the last {ui.plural(max_messages, 'message')} and "
                                        f"resets after {ui.plural(idle_minutes, 'idle minute')}."))

    @claude.command(name="websearch")
    @checks.admin_or_permissions(manage_guild=True)
    async def claude_websearch(self, ctx: commands.Context, enabled: bool):
        """Turn web search on or off for this server (searches cost $10 per 1,000)."""
        await self.config.guild(ctx.guild).web_search.set(enabled)
        await ctx.send(f"✅ Web search {'enabled' if enabled else 'disabled'}.")

    @claude.command(name="guidementions", aliases=["butlermentions"])
    @checks.admin_or_permissions(manage_guild=True)
    async def claude_guidementions(self, ctx: commands.Context, enabled: bool):
        """
        Turn on or off answering @mentions of the bot, and replies to its other messages, in the AI chat.

        Applies outside AI threads, and uses the channel's shared AI conversation. Replies to AI chat answers
        always continue that chat. The AI stays quiet when a reply is meant for other people ("I'm in!").
        """
        await self.config.guild(ctx.guild).guide_mentions.set(enabled)
        await ctx.send(ui.line(ui.DONE, f"@mentioning me {'now asks' if enabled else 'no longer asks'} the AI chat.",
                               f"`{ctx.clean_prefix}ai` and `{ctx.clean_prefix}butler` always work."))

    @claude.command(name="guideactions", aliases=["butleractions"])
    @checks.admin_or_permissions(manage_guild=True)
    async def claude_guideactions(self, ctx: commands.Context, enabled: bool):
        """
        Let the AI chat run commands for people when they ask it to do something.

        Commands always run with the asker's own permissions. Ones that need mod, admin, or
        game admin rights wait for the asker to press Run. When off, it only explains.
        """
        await self.config.guild(ctx.guild).guide_actions.set(enabled)
        await ctx.send("✅ The AI chat can now run commands for people." if enabled
                       else "✅ The AI chat now only explains commands.")

    @claude.command(name="quickmodel", aliases=["guidemodel", "butlermodel"])
    @checks.is_owner()
    async def claude_guidemodel(self, ctx: commands.Context, model: str):
        """
        Set the quick model, used for small jobs: suggesting the right command after a typo, and other features'
        quick calls (catch-up summaries, trivia and adventure checks). Haiku is cheap and plenty for these.
        """
        resolved = self._resolve_model(model)
        if resolved is None:
            return await ctx.send(f"❌ Unknown model. See `{ctx.clean_prefix}claude models`.")
        await self.config.guide_model.set(resolved)
        await ctx.send(f"✅ Quick jobs now use {self._model_label(resolved)}.")

    @claude.command(name="persona")
    @checks.admin_or_permissions(manage_guild=True)
    async def claude_persona(self, ctx: commands.Context, *, persona: str = None):
        """
        Set Claude's personality and instructions for this server.

        Applies to the AI chat and, as a speaking style, to the bot guide (whose command help stays exact).
        Up to 3,000 characters. Discord messages stop at 2,000, so for a long persona attach it as a
        `.txt` file to `[p]claude persona` instead of typing it.

        Run with no text to see the current persona, or `reset` to go back to the server's default
        persona (set with `[p]claude defaultpersona`).

        **Example:** `[p]claude persona You are a grizzled pirate quartermaster. Keep answers short and salty.`
        """
        conf = self.config.guild(ctx.guild)
        persona, error = await self._persona_input(ctx, persona)
        if error:
            return await ctx.send(error)
        if persona is None:
            current = await conf.persona()
            return await self._send_persona(ctx, "**Current persona:**",
                                            current or f"(default) {await self._persona(ctx.guild)}")
        if persona.lower() == "reset":
            await conf.persona.set(None)
            return await self._send_persona(ctx, "✅ Persona reset to the default:", await self._persona(ctx.guild))
        await conf.persona.set(persona)
        await ctx.send(ui.line(ui.DONE, f"Persona updated ({len(persona):,} characters).",
                               "It applies to the next message."))

    async def _persona_input(self, ctx: commands.Context, typed: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """(persona text from the command or an attached text file, error message)."""
        text = typed
        if ctx.message.attachments:
            att = ctx.message.attachments[0]
            if att.size > 50_000:
                return None, "❌ That file is too big for a persona."
            try:
                text = (await att.read()).decode("utf-8", errors="replace").strip()
            except discord.HTTPException:
                return None, ui.line(ui.FAIL, "I couldn't download that file.", "Try again?")
            if not text:
                return None, "❌ That file is empty."
        if text is not None and len(text) > MAX_PERSONA_CHARS:
            return None, f"❌ Keep the persona under {MAX_PERSONA_CHARS:,} characters (that's {len(text):,})."
        return text, None

    async def _send_persona(self, ctx: commands.Context, heading: str, text: str):
        """Show a persona in code blocks, split to fit Discord's 2,000-character message limit."""
        for i, page in enumerate(pagify(text, page_length=1800)):
            await ctx.send((heading if i == 0 else "") + box(page))

    @claude.command(name="defaultpersona")
    @checks.admin_or_permissions(manage_guild=True)
    async def claude_defaultpersona(self, ctx: commands.Context, *, persona: str = None):
        """
        Set the persona that `[p]claude persona reset` goes back to.

        - `[p]claude defaultpersona <text>` saves new text as the default (or attach it as a `.txt` file).
        - `[p]claude defaultpersona current` saves the persona in use right now.
        - `[p]claude defaultpersona clear` goes back to the built-in default.
        - Run with nothing to see the saved default.
        """
        conf = self.config.guild(ctx.guild)
        persona, error = await self._persona_input(ctx, persona)
        if error:
            return await ctx.send(error)
        if persona is None:
            saved = await conf.default_persona()
            return await self._send_persona(ctx, "**Default persona:**", saved or f"(built-in) {DEFAULT_PERSONA}")
        lowered = persona.lower()
        if lowered == "clear":
            await conf.default_persona.set(None)
            return await ctx.send("✅ The default persona is the built-in one again.")
        if lowered == "current":
            persona = await self._persona(ctx.guild)
        await conf.default_persona.set(persona)
        await ctx.send(ui.line(ui.DONE, f"Saved as the default persona ({len(persona):,} characters).",
                               f"`{ctx.clean_prefix}claude persona reset` returns to it."))

    @claude.command(name="limit")
    @checks.admin_or_permissions(manage_guild=True)
    async def claude_limit(self, ctx: commands.Context, messages_per_day: int):
        """
        Limit how many AI messages each user can send per day (0 = unlimited).

        Mods, admins, and the bot owner are exempt. Resets at midnight UTC.
        """
        if messages_per_day < 0:
            return await ctx.send(ui.line(ui.ASK, "Use 0 or more (0 means no limit)."))
        await self.config.guild(ctx.guild).daily_limit.set(messages_per_day)
        await ctx.send("✅ Daily limit removed." if messages_per_day == 0
                       else f"✅ Members can now send {ui.plural(messages_per_day, 'AI message')} a day.")

    @claude.command(name="usage")
    async def claude_usage(self, ctx: commands.Context, member: discord.Member = None):
        """
        Show AI usage and estimated cost.

        Your own usage is sent to you by DM, with a ✅ on your command. Admins see the server's totals and each
        member's usage, or name a member to see theirs, right where they ask.
        """
        is_admin = await self._is_exempt(ctx.author) or ctx.author.guild_permissions.manage_guild
        if member is not None and member != ctx.author and not is_admin:
            return await ctx.send("🔒 You can only view your own usage.")

        def describe(u: dict) -> List[Tuple[str, str]]:
            return [
                ("Requests", humanize_number(u["requests"])),
                ("Web searches", humanize_number(u["searches"])),
                ("Tokens", f"{humanize_number(u['input'])} in · {humanize_number(u['output'])} out · "
                           f"{humanize_number(u['cache_read'])} cache read · "
                           f"{humanize_number(u['cache_write'])} cache write"),
                ("Estimated cost", f"${u['cost']:.2f}"),
            ]

        # Costs are labeled "Estimated" (from published API prices), so footers keep to one thing each.
        if member is not None or not is_admin:
            target = member or ctx.author
            usage = await self.config.member(target).usage()
            daily = await self.config.member(target).daily()
            today = daily["count"] if daily["date"] == utc_today() else 0
            rows = ui.settings_text(describe(usage) + [("Messages today", humanize_number(today))])
            title = f"🤖 AI usage: {target.display_name}"
            if target != ctx.author:
                container = ui.card(rows, ui.SEPARATOR, title=title, color=ui.BRAND, footer="Staff only")
                return await ui.send_card(ctx, ui.CardView(container))
            # Your own numbers go to your DMs. If those are closed, post them here after all, saying why.
            return await ui.send_private(ctx, lambda in_dm: ui.CardView(ui.card(
                rows, ui.SEPARATOR, title=title, color=ui.BRAND,
                footer=f"From {ctx.guild.name}" if in_dm else ui.DM_FALLBACK)))

        # The server's totals on top, then one row per member who has used it, highest cost first.
        g = await self.config.guild(ctx.guild).all()
        since = g["usage_since"]
        try:
            since = f"<t:{int(datetime.strptime(since, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())}:D>"
        except (TypeError, ValueError):
            since = since or "the start"
        members = await self.config.all_members(ctx.guild)
        ranked = sorted(members.items(), key=lambda kv: kv[1]["usage"]["cost"], reverse=True)
        rows = []
        for user_id, data in ranked:
            if data["usage"]["requests"] == 0:
                continue
            m = ctx.guild.get_member(user_id)
            name = discord.utils.escape_markdown(m.display_name) if m else "Someone who left"
            rows.append(ui.row(f"**{name}**", f"{ui.plural(data['usage']['requests'], 'request')} · "
                                              f"${data['usage']['cost']:.2f}"))
        header = ui.settings_text(describe(g["usage"]) + [("Counting since", since)])
        await ui.Board(f"🤖 AI usage: {ctx.guild.name}", rows, color=ui.BRAND,
                       header=header + ("\n\n**Members**" if rows else ""), footer="Staff only",
                       empty="No one has used the AI chat yet.").send(ctx)

    @claude.command(name="resetusage")
    @checks.admin_or_permissions(manage_guild=True)
    async def claude_resetusage(self, ctx: commands.Context):
        """Reset this server's usage statistics and daily counts."""
        await self.config.guild(ctx.guild).usage.set(dict(EMPTY_USAGE))
        await self.config.guild(ctx.guild).usage_since.set(utc_today())
        await self.config.clear_all_members(ctx.guild)
        await ctx.send("✅ Usage statistics reset.")

    @claude.command(name="key")
    @checks.is_owner()
    async def claude_key(self, ctx: commands.Context):
        """Show how to set the Anthropic API key."""
        is_set = bool((await self.bot.get_shared_api_tokens("anthropic")).get("api_key"))
        await ctx.send(ui.line(
            ui.DONE if is_set else ui.WARN,
            "The Anthropic API key is set." if is_set else "The Anthropic API key isn't set yet.",
            hint=f"Set it with `{ctx.clean_prefix}set api anthropic api_key,<your key>` (get one at "
                 "<https://console.anthropic.com/settings/keys>), then delete your message."))
