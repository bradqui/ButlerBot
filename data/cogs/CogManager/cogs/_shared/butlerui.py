"""
ButlerBot's shared look: colors, status symbols and message helpers for all of our own cogs.

This isn't a cog. It lives in CogManager/cogs/_shared/, a folder without an __init__.py so Red doesn't list it as
one. Red doesn't put the cogs folder on sys.path, so each cog loads it with this snippet, which re-reads the file
whenever it changes, so `[p]reload <cog>` picks up edits without a restart:

    def _load_butlerui():
        \"\"\"The shared style module (../_shared/butlerui.py), re-read when the file changes.\"\"\"
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

The style, in short (the full guide is the "Message style" section of CLAUDE.md):
- Six colors, one meaning each. Six status symbols, one meaning each, only at the start of a line.
- Three message sizes: a line (one sentence, private where Discord allows), a card (one thing with its buttons
  inside it) and a board (a card that pages). AI answers and narration stay plain text.
- Buttons: a verb label, blurple for the one main action, grey for the rest, red only to confirm something
  destructive. Menus that expire grey out and say so.
- Pings only on purpose: every helper here defaults to no pings.
"""

import re
from typing import List, Optional, Union

import discord

# ==========================================
#                 COLORS
# ==========================================

BRAND = discord.Color(0x5865F2)      # info, lists, settings, help
SUCCESS = discord.Color(0x57F287)    # done, joined, approved, live
HIGHLIGHT = discord.Color(0xF1C40F)  # winners, results, sales
ATTENTION = discord.Color(0xF0B232)  # needs someone to act
DANGER = discord.Color(0xED4245)     # denied, removed, failed
MUTED = discord.Color(0x80848E)      # ended, cancelled, expired

# ==========================================
#              STATUS SYMBOLS
# ==========================================

DONE = "✅"     # it's done
FAIL = "❌"     # couldn't do it: say what went wrong and how to fix it
WARN = "⚠️"     # heads-up, or something needs setting up
WAIT = "⏳"     # working, busy, try later, or a limit was reached
LOCKED = "🔒"   # not allowed for this person
ASK = "❓"      # didn't understand / not found / did you mean
TICK, UNTICK = "☑️", "⬜"   # picker checkboxes (✅ only ever means "done")

NO_PINGS = discord.AllowedMentions.none()
MESSAGE_LIMIT = 2000


# ==========================================
#                  TEXT
# ==========================================

def line(symbol: Optional[str], text: str, hint: Optional[str] = None) -> str:
    """One status line: `✅ text`, with an optional small grey hint underneath."""
    out = f"{symbol} {text}" if symbol else text
    return out + (f"\n-# {hint}" if hint else "")


def hint(text: str) -> str:
    """Small grey text (Discord's `-#` subtext) for notes under the main line."""
    return "\n".join(f"-# {part}" if part.strip() else part for part in text.split("\n"))


def plural(count: int, word: str, many: Optional[str] = None) -> str:
    """`1 reminder`, `3 reminders`, `1,204 messages`."""
    return f"{count:,} {word if count == 1 else (many or word + 's')}"


def truncate(text: str, limit: int, marker: str = "…") -> str:
    """Shorten text to at most `limit` characters, at a line or word break where possible."""
    if len(text) <= limit:
        return text
    cut = text[:limit - len(marker)]
    for sep in ("\n", " "):
        at = cut.rfind(sep)
        if at > limit // 2:
            cut = cut[:at]
            break
    return cut.rstrip() + marker


def split_text(text: str, limit: int = 1900) -> List[str]:
    """
    Split long text into messages: at line breaks, then spaces, never mid-word unless a word is longer than a page.
    Code blocks cut across pages are closed and reopened, with their language.
    """
    pages: List[str] = []
    reopen = ""
    rest = text
    while rest:
        room = limit - len(reopen) - 4   # leave space to close a code fence
        if len(rest) <= room:
            chunk, rest = rest, ""
        else:
            window = rest[:room]
            at = window.rfind("\n")
            if at < room // 3:
                at = window.rfind(" ")
            if at < room // 3:
                at = room
            chunk, rest = rest[:at], rest[at:].lstrip("\n")
            if rest.startswith(" "):
                rest = rest[1:]
        page = reopen + chunk
        open_lang = None
        for match in re.finditer(r"```(\w*)", page):
            open_lang = match.group(1) if open_lang is None else None
        if open_lang is not None and rest:
            page += "\n```"
            reopen = f"```{open_lang}\n"
        else:
            reopen = ""
        if page.strip():
            pages.append(page)
    return pages or [text]


# ==========================================
#                  VIEWS
# ==========================================

Target = Union[discord.Message, discord.InteractionMessage, discord.Interaction]


class ExpiringView(discord.ui.View):
    """
    A short-lived menu for one person.

    Anyone else who clicks gets a private notice. When it times out, every button and menu greys out and the message
    gets a small "expired" note, so nobody clicks something that no longer works. Set `view.message` (a message, or
    the interaction whose response it is) after sending, so the view can edit it.
    """

    expired_note = "Expired."
    not_yours = f"{LOCKED} This menu isn't yours. Run the command yourself to get one."

    def __init__(self, owner_id: Optional[int], *, timeout: Optional[float] = 180):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.message: Optional[Target] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner_id is None or interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(self.not_yours, ephemeral=True)
        return False

    def disable_all(self):
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True

    async def on_timeout(self):
        if self.message is None:
            return
        self.disable_all()
        await edit_quietly(self.message, add_note=self.expired_note, view=self)


async def edit_quietly(target: Target, *, add_note: Optional[str] = None, **kwargs):
    """Edit a message (or an interaction's response), adding a hint line; ignore it if it's gone or too old."""
    try:
        if isinstance(target, discord.Interaction):
            message = await target.original_response()
        else:
            message = target
        if add_note:
            content = (message.content or "").rstrip()
            note = hint(add_note)
            if note not in content:
                kwargs["content"] = f"{content}\n{note}" if content else note
        await message.edit(**kwargs)
    except (discord.HTTPException, AttributeError):
        pass


async def respond(interaction: discord.Interaction, content: str, *, ephemeral: bool = True, **kwargs):
    """Answer an interaction whether or not it was already answered or deferred; private and ping-free by default."""
    kwargs.setdefault("allowed_mentions", NO_PINGS)
    if interaction.response.is_done():
        return await interaction.followup.send(content, ephemeral=ephemeral, **kwargs)
    return await interaction.response.send_message(content, ephemeral=ephemeral, **kwargs)
