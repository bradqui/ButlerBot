import asyncio
import base64
import contextlib
import logging
import os
import re
import time
from collections import OrderedDict
from copy import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import anthropic
import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_number, pagify

log = logging.getLogger("red.claude")


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
MAX_IMAGE_BYTES = 5 * 1024 * 1024
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
#        BOT GUIDE (plain-language help)
# ==========================================

# A cheap model answers "how do I...?" questions from a catalog of every loaded command.
DEFAULT_GUIDE_MODEL = "claude-haiku-5-5"
GUIDE_EFFORT = "low"
GUIDE_MAX_TOKENS = 4000
GUIDE_MAX_HISTORY = 10      # messages kept per guide conversation
GUIDE_IDLE_MINUTES = 15
GUIDE_HELP_CHARS = 600      # help text kept per command in the catalog
GUIDE_SILENT = "[silent]"   # the guide's answer when a reply to the bot wasn't meant for it
PRIVILEGE_NAMES = {
    commands.PrivilegeLevel.MOD: "mod",
    commands.PrivilegeLevel.ADMIN: "admin",
    commands.PrivilegeLevel.GUILD_OWNER: "server owner",
    commands.PrivilegeLevel.BOT_OWNER: "bot owner",
}

# The guide can also run commands for people. They run as the asker (same permission checks as typing
# them), and anything needing elevated rights waits for the asker to press Run.
MAX_LOOKUP_ROUNDS = 3         # rounds of read-only lookups (other cogs' guide tools) per guide answer
MAX_ACTION_COMMANDS = 5
ACTION_STEP_TIMEOUT = 20      # seconds to wait for one command before starting the next
ACTION_CONFIRM_TIMEOUT = 120
ACTION_BLOCKED_COMMANDS = {"guide", "ai", "myai", "aithread"}
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

NO_MENTIONS = discord.AllowedMentions(everyone=False, users=False, roles=False, replied_user=False)
MENTION_RULE = ("Discord mentions look like <@123> (a person), <@&123> (a role) or <#123> (a channel). A note in "
                "parentheses says who each one in a message is, so use their names. To mention someone yourself, "
                "write their <@id> exactly; it shows their name highlighted without pinging them.")
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


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def split_for_discord(text: str, limit: int = 1900) -> List[str]:
    """Pagify, closing and reopening ``` code fences that get cut across pages."""
    pages = []
    reopen = ""
    for page in pagify(text, page_length=limit):
        page = reopen + page
        open_lang = None
        for match in re.finditer(r"```(\w*)", page):
            open_lang = match.group(1) if open_lang is None else None
        if open_lang is not None:
            page += "\n```"
            reopen = f"```{open_lang}\n"
        else:
            reopen = ""
        pages.append(page)
    return pages or [text]


class ActionConfirmView(discord.ui.View):
    """Run / Cancel buttons for guide actions that need elevated permissions. Only the asker can press them."""

    def __init__(self, user_id: int):
        super().__init__(timeout=ACTION_CONFIRM_TIMEOUT)
        self.user_id = user_id
        self.approved: Optional[bool] = None
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the person who asked can confirm this.", ephemeral=True)
            return False
        return True

    async def _finish(self, interaction: discord.Interaction, approved: bool, note: str):
        self.approved = approved
        self.stop()
        await interaction.response.edit_message(content=f"{interaction.message.content}\n-# {note}", view=None)

    @discord.ui.button(label="Run", emoji="▶️", style=discord.ButtonStyle.success)
    async def run(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, True, "Running…")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, False, "Cancelled. Nothing was run.")

    async def on_timeout(self):
        if self.message is not None:
            try:
                await self.message.edit(content=f"{self.message.content}\n-# Timed out. Nothing was run.", view=None)
            except discord.HTTPException:
                pass


class ClaudeChat(commands.Cog):
    """
    Chat with Anthropic's Claude.

    `[p]ai` talks in this channel's shared conversation, `[p]myai` keeps a private
    conversation that follows you around, and `[p]aithread` starts a dedicated thread.
    Reply to any of my answers to keep that conversation going.

    `[p]guide` answers questions about the bot itself, like "how do I start a game vote?"
    """

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
            guide_mentions=True, # a plain @mention outside AI threads asks the bot guide
            guide_actions=True,  # the guide may run commands on the asker's behalf
            daily_limit=0,       # AI messages per user per day; 0 = unlimited
            usage=dict(EMPTY_USAGE),
            usage_since=None,
        )
        self.config.register_channel(model=None)
        self.config.register_user(model=None)
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
        self._sessions.pop(f"USER_{user_id}", None)
        self._sessions.pop(f"GUIDE_{user_id}", None)

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

    def _session_key(self, ctx: commands.Context, private: bool) -> str:
        if private:
            return f"USER_{ctx.author.id}"
        if ctx.channel.id in self._threads:
            return f"THREAD_{ctx.channel.id}"
        return f"CHANNEL_{ctx.channel.id}"

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
        if key.startswith("USER_"):
            model = await self.config.user(author).model()
            # A personal choice only counts while that model is still allowed.
            if model not in await self.config.allowed_models():
                model = None
        else:
            if isinstance(channel, discord.Thread) and channel.parent is not None:
                channel = channel.parent
            model = await self.config.channel(channel).model()
        model = model or await self.config.default_model()
        return model if model in MODELS else DEFAULT_MODEL

    async def _is_exempt(self, member: discord.Member) -> bool:
        return (
            await self.bot.is_owner(member)
            or member.guild_permissions.administrator
            or await self.bot.is_mod(member)
        )

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

    async def _system_prompt(self, guild: discord.Guild, web_search: bool, images: bool, lookups: bool = False) -> str:
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
                         "libraries, who owns a game, and active sessions and votes). Use them instead of guessing "
                         "or asking people to check for themselves; \"me\" means the person talking to you.")
        lines.append(f"- You don't know this bot's commands. If someone asks how to use the bot or its commands, "
                     f"point them to `{await self._prefix(guild)}guide <question>`.")
        lines.append(f"Today's date is {today} (UTC).")
        return "\n".join(lines)

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
            if ctype in IMAGE_TYPES:
                if att.size > MAX_IMAGE_BYTES:
                    return None, f"`{att.filename}` is too large (images up to 5 MB)"
                data = base64.standard_b64encode(await att.read()).decode("utf-8")
                return {"type": "image", "source": {"type": "base64", "media_type": ctype, "data": data}}, None
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

    def _mention_note(self, message: discord.Message, ref: Optional[discord.Message] = None) -> Optional[str]:
        """Say who each raw <@id>, <@&id> and <#id> in the message (and the one it replies to) refers to."""
        seen, parts = set(), []
        for msg in filter(None, (message, ref)):
            for m in msg.mentions:
                if ("u", m.id) not in seen:
                    seen.add(("u", m.id))
                    parts.append(f"<@{m.id}> is you" if m.id == self.bot.user.id else f"<@{m.id}> is {m.display_name}")
            for r in msg.role_mentions:
                if ("r", r.id) not in seen:
                    seen.add(("r", r.id))
                    parts.append(f"<@&{r.id}> is the role @{r.name}")
            for c in msg.channel_mentions:
                if ("c", c.id) not in seen:
                    seen.add(("c", c.id))
                    parts.append(f"<#{c.id}> is the channel #{c.name}")
        return f"(Mentions: {'; '.join(parts)})" if parts else None

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
                               speaker: Optional[str] = None) -> Tuple[List[dict], List[str]]:
        context_lines = []
        attachments = list(message.attachments)

        ref = await self._referenced_message(message)
        if ref is not None:
            entry = self._answers.get(ref.id)
            already_in_history = entry is not None and entry[0] == key and entry[2] == session.generation
            if not already_in_history:
                quoted = ref.content.strip()
                if len(quoted) > 1500:
                    quoted = quoted[:1500] + "…"
                if quoted:
                    context_lines.append(f'(Replying to {ref.author.display_name}: "{quoted}")')
                else:
                    context_lines.append(f"(Replying to a message from {ref.author.display_name})")
                attachments.extend(ref.attachments)
        mentions = self._mention_note(message, ref)
        if mentions:
            context_lines.append(mentions)

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
                       owner_id: Optional[int] = None, channel=None):
        """Answer `message` in conversation `key`. `channel` overrides where the answer goes (used by aithread)."""
        channel = channel or message.channel
        guild = message.guild
        prefix = await self._prefix(guild)

        client = await self._get_client()
        if client is None:
            await self._send(message, channel, f"⚠️ No Anthropic API key is set. The bot owner can add one with "
                                               f"`{prefix}set api anthropic api_key,<key>`.")
            return

        limit = await self._limit_reached(message.author)
        if limit:
            await self._send(message, channel, f"⏳ You've used all {limit} of today's AI messages. "
                                               "The limit resets at midnight UTC.")
            return

        session = self._get_session(key)
        async with session.lock:
            idle = await self.config.idle_minutes()
            if session.messages and time.monotonic() - session.last_active > idle * 60:
                session.reset()
            if isinstance(channel, discord.Thread) and key.startswith("THREAD_") and not session.seeded:
                await self._seed_thread_history(channel, session, message)

            if await self._fast_path_image(message, prompt, key, session, owner_id, channel):
                return

            content, notes = await self._build_user_turn(message, prompt, key, session)
            user_turn = {"role": "user", "content": content}
            session.messages.append(user_turn)
            model = await self._model_for(key, message.author, channel)

            try:
                async with channel.typing():
                    text, sources, stop_reason, image_calls = await self._call_claude(client, model, session, message.author)
            except Exception as e:
                if session.messages and session.messages[-1] is user_turn:
                    session.messages.pop()
                reply, reset = self._describe_error(e, prefix)
                if reset:
                    session.reset()
                await self._send(message, channel, reply)
                return

            if stop_reason == "refusal" or not (text or image_calls):
                session.messages.pop()
                reply = ("🚫 I can't help with that one." if stop_reason == "refusal"
                         else "😶 I didn't come up with a reply. Try rephrasing?")
                await self._send(message, channel, reply)
                return

            sent = []
            if text or notes:
                reply = text + sources
                if stop_reason == "max_tokens":
                    reply += "\n\n*(My reply was cut off. Ask me to continue.)*"
                if notes:
                    reply += "\n-# Skipped: " + "; ".join(notes)
                sent += await self._send(message, channel, reply.strip())

            # History stays plain text: image calls are recorded as a note Claude can refer back to.
            record = [text] if text else []
            for call in image_calls:
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
            await self._count_request(message.author)

    async def _call_claude(self, client: anthropic.AsyncAnthropic, model: str, session: Session,
                           member: discord.Member) -> Tuple[str, str, str, List[dict]]:
        """Returns (reply text, sources footer, stop_reason, generate_image calls)."""
        info = MODELS[model]
        web_search = info.web_search and await self.config.guild(member.guild).web_search()
        images = self._image_generator() is not None
        lookups = self._lookup_tools()
        kwargs = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "system": await self._system_prompt(member.guild, web_search, images, lookups=bool(lookups)),
            "output_config": {"effort": await self.config.effort()},
            # Top-level cache_control caches the conversation prefix automatically.
            "extra_body": {"cache_control": {"type": "ephemeral"}},
        }
        tools = []
        if images:
            tools.append(IMAGE_TOOL)
        if web_search:
            tools.append({"type": "web_search_20260209", "name": "web_search", "max_uses": 3})
        tools.extend(tool for tool, _ in lookups.values())
        if tools:
            kwargs["tools"] = tools
        if info.fallback:
            # On a safety-classifier refusal, Anthropic re-runs the request on a recommended model.
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["extra_body"]["fallbacks"] = "default"

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
                    and all(c.name in lookups for c in calls)):
                # Lookups (other cogs' read-only tools) get real results within this turn only;
                # session history keeps just the final text.
                lookup_rounds += 1
                results = await self._run_lookups(calls, lookups, member)
                messages = messages + [{"role": "assistant", "content": response.content},
                                       {"role": "user", "content": results}]
                continue
            break
        totals["requests"] = 1
        await self._record_usage(member, totals)

        if response.stop_reason == "refusal":
            return "", "", "refusal", []

        # Image requests: run them instead of sending tool results back, which saves a second API call.
        # A max_tokens stop can truncate a tool input, so don't act on calls from a cut-off turn.
        image_calls = []
        if response.stop_reason == "tool_use":
            for b in blocks:
                if b.type == "tool_use" and b.name == "generate_image":
                    args = b.input if isinstance(b.input, dict) else {}
                    prompt = args.get("prompt")
                    if isinstance(prompt, str) and prompt.strip():
                        image_calls.append({"prompt": prompt.strip(), "edit": bool(args.get("edit"))})
            image_calls = image_calls[:MAX_IMAGES_PER_TURN]

        # Drop "let me search/check that" preamble: keep the text written after the last search result or lookup.
        last_result = max((i for i, b in enumerate(blocks)
                           if b.type == "web_search_tool_result" or (b.type == "tool_use" and b.name in lookups)),
                          default=-1)
        text_blocks = [b for b in blocks[last_result + 1:] if b.type == "text"] or [b for b in blocks if b.type == "text"]
        text = "".join(b.text for b in text_blocks).strip()

        sources = OrderedDict()
        for b in text_blocks:
            for citation in getattr(b, "citations", None) or []:
                url = getattr(citation, "url", None)
                if url and url not in sources:
                    title = (getattr(citation, "title", None) or url).replace("[", "").replace("]", "")
                    sources[url] = title[:60]
        footer = ""
        if sources:
            links = [f"[{title}](<{url}>)" for url, title in list(sources.items())[:5]]
            footer = "\n\n**Sources:** " + " · ".join(links)
        return text, footer, response.stop_reason, image_calls

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
        """Map an exception to (user-facing message, whether to reset the conversation)."""
        if isinstance(e, anthropic.AuthenticationError):
            return f"🔑 The Anthropic API key was rejected. The bot owner can update it with `{prefix}set api anthropic api_key,<key>`.", False
        if isinstance(e, anthropic.PermissionDeniedError):
            return "🔒 The Anthropic API key isn't allowed to use this model.", False
        if isinstance(e, anthropic.NotFoundError):
            return f"❓ That model wasn't found. Pick another with `{prefix}claude channelmodel` or `{prefix}claude mymodel`.", False
        if isinstance(e, anthropic.RateLimitError):
            return "⏳ Claude is getting too many requests right now. Try again in a minute.", False
        if isinstance(e, anthropic.BadRequestError):
            msg = e.message or ""
            if "credit balance" in msg.lower():
                return "💳 The Anthropic account is out of credits. The bot owner needs to top it up.", False
            if "too long" in msg.lower():
                return "🧹 This conversation got too long, so I've started a fresh one. Please ask again.", True
            log.warning("Claude rejected a request: %s", msg)
            return f"⚠️ Claude couldn't process that request:{box(msg[:500])}", False
        if isinstance(e, anthropic.APIStatusError):
            if e.status_code >= 500:
                return "🛑 Claude is overloaded or having trouble right now. Try again shortly.", False
            log.warning("Anthropic API error %s: %s", e.status_code, e.message)
            return f"⚠️ Anthropic API error ({e.status_code}).", False
        if isinstance(e, anthropic.APITimeoutError):
            return "⌛ Claude took too long to respond. Try again.", False
        if isinstance(e, anthropic.APIConnectionError):
            return "📡 I couldn't reach the Anthropic API. Try again shortly.", False
        log.exception("Unexpected error in Claude cog", exc_info=e)
        return "❌ Something went wrong while talking to Claude. The error was logged.", False

    async def _send(self, message: discord.Message, channel, text: str,
                    view: Optional[discord.ui.View] = None) -> List[discord.Message]:
        """Send a possibly long reply. `view` goes on the last page."""
        sent = []
        pages = split_for_discord(text)
        for i, page in enumerate(pages):
            kwargs = {"allowed_mentions": NO_MENTIONS}
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

    async def _command_catalog(self, guild: discord.Guild, prefix: str, include_owner: bool) -> str:
        """Every command usable in this server, grouped by cog, as plain-text reference for the guide model.
        Built fresh each time (it's cheap) and sorted so identical bot state gives identical, cacheable text."""
        bot_name = guild.me.display_name

        def fill(text: str, limit: int) -> List[str]:
            text = (text or "").replace("[p]", prefix).replace("[botname]", bot_name).strip()
            if len(text) > limit:
                text = text[:limit].rstrip() + "…"
            return [line.strip() for line in text.splitlines() if line.strip()]

        def entries(cmds) -> List[str]:
            lines = []
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
                lines.append("\n  ".join([head] + fill(command.help, GUIDE_HELP_CHARS)))
            return lines

        sections = []
        for cog in sorted(self.bot.cogs.values(), key=lambda c: c.qualified_name.lower()):
            if await self.bot.cog_disabled_in_guild(cog, guild):
                continue
            lines = entries(cog.walk_commands())
            if lines:
                about = fill(getattr(cog, "help", None) or cog.description, 400)
                sections.append("\n".join([f"## {cog.qualified_name}", *about, *lines]))
        loose = entries(c for c in self.bot.walk_commands() if c.cog is None)
        if loose:
            sections.append("\n".join(["## Other", *loose]))
        return "\n\n".join(sections)

    async def _guide_system_prompt(self, guild: discord.Guild, prefix: str, include_owner: bool, actions: bool,
                                   lookups: bool = False) -> str:
        catalog = await self._command_catalog(guild, prefix, include_owner)
        if actions:
            action_rules = [
                "",
                "Doing things for people:",
                "- When the asker wants the bot to do something (\"add Rocket League to my games\"), call run_commands "
                "with the exact commands. When they ask how to do something (\"how do I add a game?\"), explain the "
                "commands instead of running them.",
                "- Commands run as the asker, with the asker's own permissions, as if they typed them.",
                "- Use only commands from the reference, without the prefix, with every argument filled in. Never run "
                "a command without arguments when that opens an interactive menu; fill in the arguments.",
                "- Prefer commands the asker can run. If something needs a permission they clearly don't have, say "
                "who can do it instead of calling the tool. Server roles can grant extra access, and the bot checks "
                "permissions again before running anything.",
                f"- Up to {MAX_ACTION_COMMANDS} commands, run in order, each finishing before the next starts. You "
                "won't see their output, so order dependent steps correctly (add a game to the server library before "
                "marking it installed).",
                "- If part of the request can't happen yet (a vote needs at least two players, so others must join "
                "the session first), do what you can and say in your message what's left.",
                "- Commands that need mod, admin, or game admin rights wait for the asker to press Run.",
                "- Only ban, kick, mute, warn, or delete messages when the asker explicitly asks for exactly that. "
                "If a request is ambiguous, ask a short question instead of guessing.",
                "- Never run guide or AI chat commands (guide, ai, myai, aithread).",
            ]
        else:
            action_rules = ["- You can't run commands for people; tell them what to type."]
        persona = await self._persona(guild)
        return "\n".join([
            f'You are the built-in guide for {guild.me.display_name}, a Discord bot in the server "{guild.name}". '
            "People ask you in plain language what the bot can do and how to use it.",
            "",
            "Your personality (set by the server's admins):",
            persona,
            "Speak in this personality's voice, but clarity comes first: command names, arguments, game names, and "
            "steps must stay exact and easy to follow. Where the personality conflicts with the rules below, the "
            "rules win.",
            "",
            "How to answer:",
            f"- Base every answer on the command reference below (prefix `{prefix}`). Never invent commands, "
            "subcommands, arguments, or features that aren't in it. If nothing fits, say so plainly.",
            "- Give the exact command to type in `inline code`, with a short example using realistic values when it "
            "helps. In usages, <angle brackets> are required and [square brackets] are optional; people don't type "
            "the brackets.",
            "- Keep it short: a sentence or two plus the commands, or a brief numbered list for multi-step setups. "
            "Use Discord markdown; Discord doesn't render tables.",
            "- Each question starts with the asker's name and, in parentheses, their permission level. Notes like "
            "\"admin only\" or \"needs manage messages permission\" say who can run a command. Lead with what the "
            "asker can do themselves. If it needs more permission, say who can do it (a mod, an admin, the bot owner).",
            f"- {MENTION_RULE} In commands, a <@id> mention works wherever a member is expected.",
            f"- For every detail of one command, they can run `{prefix}help <command>`.",
            f"- If the question isn't about this bot (general knowledge, chit-chat, homework), say you only answer "
            f"questions about the bot and suggest `{prefix}ai <question>` instead.",
            "- Never ping @everyone or @here.",
            "- Some messages are replies to the bot's own announcements (shown as \"Replying to …\"). Answer them "
            "when they're meant for the bot, like a question about what it did. When they're meant for other people "
            f"or need no answer (\"I'm in!\", \"nice\", \"thanks\"), reply with exactly {GUIDE_SILENT} and nothing else.",
            *(["- Use the lookup tools to check facts (someone's games, who owns a game, running sessions and votes) "
               "instead of guessing. The asker doesn't see lookups, so answer in your own words."] if lookups else []),
            *action_rules,
            "",
            "# Command reference",
            "",
            catalog,
        ])

    def _guide_intro(self, prefix: str, actions: bool) -> str:
        lines = [
            "📖 Ask me how to do anything with this bot, in plain English. For example:",
            f"- `{prefix}guide how do I find a game everyone owns?`",
            f"- `{prefix}guide how do I start a vote on what to play?`",
        ]
        if actions:
            lines.append(f"- `{prefix}guide add Rocket League to my games and mark it installed`")
            lines.append("I can run commands for you too. Anything that needs extra permissions waits for you to press Run.")
        lines.append("Reply to my answers to follow up.")
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

    # ---------- read-only lookups offered by other cogs ----------

    def _lookup_tools(self) -> Dict[str, Tuple[dict, commands.Cog]]:
        """
        Tools other cogs offer the guide for looking things up. A cog provides `guide_tools()`, which returns
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
                if name and name != GUIDE_ACTION_TOOL["name"] and name not in found:
                    found[name] = (tool, cog)
        return found

    async def _run_lookups(self, calls, lookups: Dict[str, Tuple[dict, commands.Cog]],
                           member: discord.Member) -> List[dict]:
        """Answer lookup tool calls (used by the guide and the AI chat). Returns tool_result blocks."""
        results = []
        for call in calls:
            _, cog = lookups[call.name]
            try:
                output = await cog.guide_call_tool(call.name, call.input if isinstance(call.input, dict) else {},
                                                   member)
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": str(output)[:8000]})
            except Exception:
                log.exception("Lookup %s failed", call.name)
                results.append({"type": "tool_result", "tool_use_id": call.id, "is_error": True,
                                "content": "The lookup failed."})
        return results

    async def _guide_call(self, client: anthropic.AsyncAnthropic, member: discord.Member,
                          lookups: Dict[str, Tuple[dict, commands.Cog]], *, messages: List[dict], **kwargs):
        """
        One guide turn. The model may call lookup tools for up to MAX_LOOKUP_ROUNDS rounds; their results go back
        within this turn only. Returns the final response. A run_commands call ends the loop (it's handled by
        the caller without a tool_result), so session history stays plain text.
        """
        messages = list(messages)
        totals = dict(EMPTY_USAGE)
        response = None
        for round_number in range(MAX_LOOKUP_ROUNDS + 1):
            response = await client.messages.create(messages=messages, **kwargs)
            for k, v in self._usage_from(response, kwargs["model"]).items():
                totals[k] += v
            calls = [b for b in response.content if b.type == "tool_use"]
            if (response.stop_reason != "tool_use" or not calls or round_number == MAX_LOOKUP_ROUNDS
                    or any(b.name not in lookups for b in calls)):
                break
            results = await self._run_lookups(calls, lookups, member)
            messages += [{"role": "assistant", "content": response.content}, {"role": "user", "content": results}]
        totals["requests"] = 1
        await self._record_usage(member, totals)
        return response

    @staticmethod
    def _action_call(response) -> Optional[dict]:
        if response.stop_reason != "tool_use":
            return None
        for block in response.content:
            if block.type == "tool_use" and block.name == GUIDE_ACTION_TOOL["name"] and isinstance(block.input, dict):
                lines = [c for c in block.input.get("commands", []) if isinstance(c, str) and c.strip()]
                if lines:
                    return {"message": str(block.input.get("message", "")).strip(), "commands": lines}
        return None

    async def _guide_respond(self, message: discord.Message, prompt: str, may_stay_silent: bool = False):
        """Answer a question about the bot, or do what was asked, in the asker's own short guide conversation."""
        channel = message.channel
        guild = message.guild
        prefix = await self._prefix(guild)
        actions = await self.config.guild(guild).guide_actions()
        if not prompt and not message.attachments:
            await self._send(message, channel, self._guide_intro(prefix, actions))
            return

        client = await self._get_client()
        if client is None:
            await self._send(message, channel, f"⚠️ No Anthropic API key is set. The bot owner can add one with "
                                               f"`{prefix}set api anthropic api_key,<key>`.")
            return

        key = f"GUIDE_{message.author.id}"
        session = self._get_session(key)
        pending: Optional[Tuple[List[str], Optional[ActionConfirmView]]] = None
        async with session.lock:
            if session.messages and time.monotonic() - session.last_active > GUIDE_IDLE_MINUTES * 60:
                session.reset()

            level = await self._permission_level(message.author)
            content, notes = await self._build_user_turn(
                message, prompt, key, session, speaker=f"{message.author.display_name} ({level})"
            )
            user_turn = {"role": "user", "content": content}
            session.messages.append(user_turn)
            model = await self.config.guide_model()
            if model not in MODELS:
                model = DEFAULT_GUIDE_MODEL

            lookups = self._lookup_tools()
            try:
                # No "typing…" for replies we might ignore; it would look like an answer that never came.
                async with (contextlib.nullcontext() if may_stay_silent else channel.typing()):
                    system = await self._guide_system_prompt(guild, prefix, include_owner=level.startswith("bot owner"),
                                                             actions=actions, lookups=bool(lookups))
                    tools = [tool for tool, _ in lookups.values()] + ([GUIDE_ACTION_TOOL] if actions else [])
                    kwargs = {"tools": tools} if tools else {}
                    response = await self._guide_call(
                        client, message.author, lookups,
                        model=model,
                        max_tokens=GUIDE_MAX_TOKENS,
                        # The catalog is the big, shared part: give it its own cache breakpoint so every
                        # new guide conversation reads it from cache. Top-level caching covers the chat itself.
                        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                        output_config={"effort": GUIDE_EFFORT},
                        messages=session.messages,
                        extra_body={"cache_control": {"type": "ephemeral"}},
                        **kwargs,
                    )
            except Exception as e:
                if session.messages and session.messages[-1] is user_turn:
                    session.messages.pop()
                reply, reset = self._describe_error(e, prefix)
                if reset:
                    session.reset()
                await self._send(message, channel, reply)
                return

            text = "".join(b.text for b in response.content if b.type == "text").strip()
            action = self._action_call(response) if actions else None
            if text == GUIDE_SILENT and action is None:
                session.messages.pop()  # a reply that wasn't for us: leave no trace
                if not may_stay_silent:
                    await self._send(message, channel, "😶 I didn't come up with an answer. Try rephrasing?")
                return
            if response.stop_reason == "refusal" or not (text or action):
                session.messages.pop()
                await self._send(message, channel, "🚫 I can't help with that one." if response.stop_reason == "refusal"
                                 else "😶 I didn't come up with an answer. Try rephrasing?")
                return

            view = None
            if action is not None:
                # Like image calls in the main chat, no tool_result goes back: the commands post their own output,
                # and history records a plain-text note instead.
                planned, problems, confirm = await self._plan_actions(message, action["commands"], prefix)
                summary = action["message"] or text or "Here's what I can do."
                lines = [f"🛠️ {summary}" if planned else summary]
                if planned and confirm:
                    lines.append("These need extra permissions, so press **Run** to go ahead:")
                    lines.extend(f"`{c}`" for c in planned)
                    view = ActionConfirmView(message.author.id)
                elif planned:
                    lines.append("-# Running: " + " · ".join(f"`{c}`" for c in planned))
                if problems:
                    lines.append("-# Skipped: " + "; ".join(problems))
                reply = "\n".join(lines)
                record = summary
                if planned:
                    record += f"\n[{'Asked the user to confirm' if confirm else 'Ran'}: {'; '.join(planned)}]"
                if problems:
                    record += f"\n[Skipped: {'; '.join(problems)}]"
                pending = (planned, view) if planned else None
            else:
                reply = record = text
                if response.stop_reason == "max_tokens":
                    reply += "\n\n*(My answer was cut off. Ask me to continue.)*"
            if notes:
                reply += "\n-# Skipped attachments: " + "; ".join(notes)
            sent = await self._send(message, channel, reply, view=view)
            if view is not None:
                view.message = sent[-1]

            session.messages.append({"role": "assistant", "content": record})
            session.last_active = time.monotonic()
            self._trim(session, GUIDE_MAX_HISTORY)
            self._remember_answers(sent, key, message.author.id, session.generation)

        # Outside the lock, so waiting for a confirmation doesn't block the asker's next question.
        if pending is not None:
            planned, view = pending
            if view is not None:
                await view.wait()
                if not view.approved:
                    return
            await self._run_actions(message, planned)

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

        Start with "draw", "paint", or "image of" to go straight to the image generator
        (Gemini). Other ways of asking for a picture work too; Claude hands them off.
        Reply "make it blue" or similar to change the last image.

        **Examples:**
        - `[p]ai what's a good name for a guild?`
        - `[p]ai summarize this` (with a PDF attached)
        - `[p]ai could you make us a banner with a dragon guarding a castle?`
        """
        if not prompt and not ctx.message.attachments:
            return await ctx.send_help()
        await self._respond(ctx.message, prompt, self._session_key(ctx, private=False))

    @ai.command(name="reset")
    @checks.mod_or_permissions(manage_channels=True)
    async def ai_reset(self, ctx: commands.Context):
        """Wipe this channel's shared conversation memory."""
        self._get_session(self._session_key(ctx, private=False)).reset()
        await ctx.send("🧹 Shared conversation for this channel wiped.")

    @commands.group(name="myai", invoke_without_command=True)
    @commands.guild_only()
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def myai(self, ctx: commands.Context, *, prompt: str = ""):
        """
        Talk to Claude in your own private conversation.

        Your private conversation follows you across channels and only you can
        continue it (by command or by replying to its answers). It uses the bot's
        default model; admins can pick their own with `[p]claude mymodel`.
        """
        if not prompt and not ctx.message.attachments:
            return await ctx.send_help()
        await self._respond(ctx.message, prompt, self._session_key(ctx, private=True), owner_id=ctx.author.id)

    @myai.command(name="reset")
    async def myai_reset(self, ctx: commands.Context):
        """Wipe your private conversation memory."""
        self._get_session(self._session_key(ctx, private=True)).reset()
        await ctx.send("🧹 Your private conversation wiped.")

    @commands.command(name="aithread")
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def aithread(self, ctx: commands.Context, *, prompt: str):
        """
        Start a new thread for a conversation with Claude.

        Inside the thread, @mention me or reply to my messages to keep talking.
        """
        if isinstance(ctx.channel, discord.Thread):
            return await ctx.send("We're already in a thread. Just @mention me or reply to my messages here.")
        name = "🤖 " + (prompt[:80] + "…" if len(prompt) > 80 else prompt)
        try:
            thread = await ctx.message.create_thread(name=name, auto_archive_duration=1440)
        except discord.HTTPException as e:
            return await ctx.send(f"❌ I couldn't create a thread here: {e.text or e}")
        await self._register_thread(thread.id)

        model = await self._model_for(f"THREAD_{thread.id}", ctx.author, ctx.channel)
        task = asyncio.create_task(self._retitle_thread(thread, prompt, model, ctx.author))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        await self._respond(ctx.message, prompt, f"THREAD_{thread.id}", channel=thread)

    @commands.command(name="guide")
    @commands.guild_only()
    @commands.cooldown(1, 4, commands.BucketType.user)
    async def guide(self, ctx: commands.Context, *, request: str = ""):
        """
        Ask how to use this bot, or ask it to do something, in plain English.

        The guide knows every command enabled in this server. Ask "how do I…" and it tells you
        what to type; ask it to do something and it runs the commands for you, with your own
        permissions. Anything that needs mod, admin, or game admin rights waits for you to press Run.
        Reply to its answers to follow up. You can also just @mention me.

        **Examples:**
        - `[p]guide how do I start a vote on what to play?`
        - `[p]guide add Rocket League to my games and mark it installed`
        - `[p]guide what can mods do with the word filter?`
        """
        await self._guide_respond(ctx.message, request)

    @commands.Cog.listener()
    async def on_message_without_command(self, message: discord.Message):
        """Reply-to-continue, @mentions inside AI threads, and @mention questions for the bot guide."""
        if message.author.bot or message.guild is None:
            return
        if not message.content and not message.attachments:
            return

        ref = message.reference
        entry = self._answers.get(ref.message_id) if ref is not None and ref.message_id else None
        in_ai_thread = message.channel.id in self._threads
        mention = rf"<@!?{self.bot.user.id}>"
        # Replies count as mentions too, so only a typed @mention in a fresh message asks the guide.
        guide_mention = ref is None and not in_ai_thread and re.search(mention, message.content) is not None
        # Replies to the bot's other messages (game announcements, results...) also go to the guide,
        # which stays silent when the reply is meant for other people.
        reply_to_bot = (entry is None and not in_ai_thread and ref is not None
                        and isinstance(ref.resolved, discord.Message) and ref.resolved.author.id == self.bot.user.id)
        if (entry is None and not (in_ai_thread and self.bot.user in message.mentions)
                and not guide_mention and not reply_to_bot):
            return

        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        if not await self.bot.ignored_channel_or_guild(message):
            return
        if not await self.bot.allowed_by_whitelist_blacklist(message.author):
            return

        if entry is not None:
            key, owner_id, _ = entry
            # Anyone can follow up on a guide answer (it continues their own guide chat), but private
            # conversations belong to their owner.
            if owner_id is not None and owner_id != message.author.id and not key.startswith("GUIDE_"):
                return
        elif in_ai_thread:
            key, owner_id = f"THREAD_{message.channel.id}", None
        else:
            if not await self.config.guild(message.guild).guide_mentions():
                return
            key, owner_id = f"GUIDE_{message.author.id}", message.author.id

        # Respect the same permission rules (Permissions cog, cog checks) as the commands.
        if key.startswith("GUIDE_"):
            command = self.guide
        else:
            command = self.myai if key.startswith("USER_") else self.ai
        ctx = await self.bot.get_context(message)
        try:
            if not await command.can_run(ctx):
                return
        except commands.CommandError:
            return

        if self._reply_cooldown.get_bucket(message).update_rate_limit():
            return

        prompt = re.sub(mention, "", message.content).strip()
        if key.startswith("GUIDE_"):
            await self._guide_respond(message, prompt, may_stay_silent=reply_to_bot)
        else:
            await self._respond(message, prompt, key, owner_id=owner_id)

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
        g = await self.config.guild(ctx.guild).all()
        persona = g["persona"] or f"*Default:* {g['default_persona'] or DEFAULT_PERSONA}"
        if len(persona) > 300:
            persona = persona[:300] + "…"
        channel = ctx.channel.parent if isinstance(ctx.channel, discord.Thread) and ctx.channel.parent else ctx.channel
        embed = discord.Embed(title="🤖 Claude Settings", color=discord.Color.orange())
        embed.add_field(name="Models", value=(
            f"**Your private chats:** {self._model_label(await self._model_for(f'USER_{ctx.author.id}', ctx.author, ctx.channel))}\n"
            f"**This channel:** {self._model_label(await self._model_for('CHANNEL', ctx.author, channel))}\n"
            f"**Bot default:** {self._model_label(await self.config.default_model())}"
        ), inline=False)
        embed.add_field(name="Server", value=(
            f"**Web search:** {'On' if g['web_search'] else 'Off'}\n"
            f"**@mention asks the guide:** {'On' if g['guide_mentions'] else 'Off'}\n"
            f"**Guide runs commands for people:** {'On' if g['guide_actions'] else 'Off'}\n"
            f"**Daily limit:** {g['daily_limit'] or 'Unlimited'} messages per user\n"
            f"**Persona:** {persona}"
        ), inline=False)
        embed.add_field(name="Bot-wide", value=(
            f"**Effort:** {await self.config.effort()}\n"
            f"**Memory:** last {await self.config.max_history()} messages, "
            f"resets after {await self.config.idle_minutes()} idle minutes\n"
            f"**Bot guide (`{ctx.clean_prefix}guide`):** {self._model_label(await self.config.guide_model())}"
        ), inline=False)
        await ctx.send(embed=embed)

    @claude.command(name="models")
    async def claude_models(self, ctx: commands.Context):
        """List the available Claude models and their prices."""
        allowed = await self.config.allowed_models()
        alias_for = {v: k for k, v in MODEL_ALIASES.items()}
        lines = []
        for model, info in MODELS.items():
            status = "✅" if model in allowed else "🚫"
            lines.append(
                f"{status} **{info.name}** (`{alias_for.get(model, model)}`): ${info.input:g} in / ${info.output:g} out "
                f"per 1M tokens{'' if info.web_search else ', no web search'}"
            )
        lines.append("\n✅ = admins (for their private chats) and channel managers can choose it. "
                     "The bot owner manages the list.")
        await ctx.send("\n".join(lines))

    @claude.command(name="mymodel")
    @checks.admin_or_permissions(manage_guild=True)
    async def claude_mymodel(self, ctx: commands.Context, model: str):
        """
        Pick the model for your private conversations (`[p]myai`). Admins only. Use `reset` for the default.

        Only models the bot owner allows can be picked (see `[p]claude models`).
        """
        if model.lower() == "reset":
            await self.config.user(ctx.author).model.set(None)
            self._get_session(f"USER_{ctx.author.id}").reset()
            return await ctx.send("✅ Your private chats now use the default model.")
        resolved = self._resolve_model(model)
        if resolved is None or resolved not in await self.config.allowed_models():
            return await ctx.send(f"❌ That model isn't available. See `{ctx.clean_prefix}claude models`.")
        await self.config.user(ctx.author).model.set(resolved)
        self._get_session(f"USER_{ctx.author.id}").reset()
        await ctx.send(f"✅ Your private chats now use {self._model_label(resolved)}.")

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
            return await ctx.send(f"❌ That model isn't available. See `{ctx.clean_prefix}claude models`.")
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
        """Let admins (for their private chats) and channel managers choose a model."""
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

        Private chats that had picked it switch to the default model. Channels that had picked it keep it
        until a channel manager changes it.
        """
        resolved = self._resolve_model(model)
        async with self.config.allowed_models() as allowed:
            if resolved in allowed:
                allowed.remove(resolved)
        await ctx.send(f"✅ {self._model_label(resolved or model)} can no longer be chosen. Private chats using it "
                       "now use the default model.")

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
            return await ctx.send("❌ Effort must be `low`, `medium`, or `high`.")
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
            return await ctx.send("❌ Use 4-100 messages and 5-1440 idle minutes.")
        await self.config.max_history.set(max_messages)
        await self.config.idle_minutes.set(idle_minutes)
        await ctx.send(f"✅ Claude now remembers the last {max_messages} messages and resets after {idle_minutes} idle minutes.")

    @claude.command(name="websearch")
    @checks.admin_or_permissions(manage_guild=True)
    async def claude_websearch(self, ctx: commands.Context, enabled: bool):
        """Turn web search on or off for this server (searches cost $10 per 1,000)."""
        await self.config.guild(ctx.guild).web_search.set(enabled)
        await ctx.send(f"✅ Web search {'enabled' if enabled else 'disabled'}.")

    @claude.command(name="guidementions")
    @checks.admin_or_permissions(manage_guild=True)
    async def claude_guidementions(self, ctx: commands.Context, enabled: bool):
        """
        Turn on or off sending @mentions of the bot, and replies to its messages, to the bot guide.

        Applies outside AI threads. Replies to AI chat answers always continue that chat.
        The guide stays quiet when a reply is meant for other people ("I'm in!").
        """
        await self.config.guild(ctx.guild).guide_mentions.set(enabled)
        await ctx.send(f"✅ @mentioning me {'now asks' if enabled else 'no longer asks'} the bot guide. "
                       f"`{ctx.clean_prefix}guide` always works.")

    @claude.command(name="guideactions")
    @checks.admin_or_permissions(manage_guild=True)
    async def claude_guideactions(self, ctx: commands.Context, enabled: bool):
        """
        Let the bot guide run commands for people when they ask it to do something.

        Commands always run with the asker's own permissions. Ones that need mod, admin, or
        game admin rights wait for the asker to press Run. When off, the guide only explains.
        """
        await self.config.guild(ctx.guild).guide_actions.set(enabled)
        await ctx.send("✅ The guide can now run commands for people." if enabled
                       else "✅ The guide now only explains commands.")

    @claude.command(name="guidemodel")
    @checks.is_owner()
    async def claude_guidemodel(self, ctx: commands.Context, model: str):
        """Set the model the bot guide (`[p]guide`) uses. Haiku is cheap and plenty for command help."""
        resolved = self._resolve_model(model)
        if resolved is None:
            return await ctx.send(f"❌ Unknown model. See `{ctx.clean_prefix}claude models`.")
        await self.config.guide_model.set(resolved)
        await ctx.send(f"✅ The bot guide now uses {self._model_label(resolved)}.")

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
        await ctx.send(f"✅ Persona updated ({len(persona):,} characters). It applies to the next message.")

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
                return None, "❌ I couldn't download that file. Try again?"
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
        await ctx.send(f"✅ Saved as the default persona ({len(persona):,} characters). "
                       f"`{ctx.clean_prefix}claude persona reset` returns to it.")

    @claude.command(name="limit")
    @checks.admin_or_permissions(manage_guild=True)
    async def claude_limit(self, ctx: commands.Context, messages_per_day: int):
        """
        Limit how many AI messages each user can send per day (0 = unlimited).

        Mods, admins, and the bot owner are exempt. Resets at midnight UTC.
        """
        if messages_per_day < 0:
            return await ctx.send("❌ Use 0 or more.")
        await self.config.guild(ctx.guild).daily_limit.set(messages_per_day)
        await ctx.send("✅ Daily limit removed." if messages_per_day == 0
                       else f"✅ Users can now send {messages_per_day} AI messages per day.")

    @claude.command(name="usage")
    async def claude_usage(self, ctx: commands.Context, member: discord.Member = None):
        """
        Show Claude usage and estimated cost.

        Admins see the server's totals and top users (or a specific member's).
        Everyone else sees their own.
        """
        is_admin = await self._is_exempt(ctx.author) or ctx.author.guild_permissions.manage_guild
        if member is not None and member != ctx.author and not is_admin:
            return await ctx.send("❌ You can only view your own usage.")

        def describe(u: dict) -> str:
            return (
                f"**Requests:** {humanize_number(u['requests'])} · **Web searches:** {humanize_number(u['searches'])}\n"
                f"**Tokens:** {humanize_number(u['input'])} in · {humanize_number(u['output'])} out · "
                f"{humanize_number(u['cache_read'])} cache read · {humanize_number(u['cache_write'])} cache write\n"
                f"**Estimated cost:** ${u['cost']:.2f}"
            )

        if member is not None or not is_admin:
            target = member or ctx.author
            usage = await self.config.member(target).usage()
            daily = await self.config.member(target).daily()
            today = daily["count"] if daily["date"] == utc_today() else 0
            embed = discord.Embed(title=f"Claude usage: {target.display_name}", color=discord.Color.orange())
            embed.description = describe(usage) + f"\n**Messages today:** {today}"
            return await ctx.send(embed=embed)

        g = await self.config.guild(ctx.guild).all()
        embed = discord.Embed(title=f"Claude usage: {ctx.guild.name}", color=discord.Color.orange())
        embed.description = describe(g["usage"])
        members = await self.config.all_members(ctx.guild)
        top = sorted(members.items(), key=lambda kv: kv[1]["usage"]["cost"], reverse=True)[:10]
        lines = []
        for user_id, data in top:
            if data["usage"]["requests"] == 0:
                continue
            m = ctx.guild.get_member(user_id)
            name = m.display_name if m else f"User {user_id}"
            lines.append(f"{name}: ${data['usage']['cost']:.2f} ({data['usage']['requests']} requests)")
        if lines:
            embed.add_field(name="Top users", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"Since {g['usage_since'] or 'n/a'} · Estimates from published API prices")
        await ctx.send(embed=embed)

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
        await ctx.send(
            f"API key is **{'set' if is_set else 'not set'}**.\n"
            f"Set it with `{ctx.clean_prefix}set api anthropic api_key,<your key>` "
            "(get one at <https://console.anthropic.com/settings/keys>). Delete your message afterwards."
        )
