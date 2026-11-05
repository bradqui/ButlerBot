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


# ==========================================
#                  CARDS
# ==========================================
# A card is one Components V2 container: a colored edge, a short title, the details, its buttons inside, and a
# small footer hint. Messages that carry a card can't have content or embeds, and that can never be undone for a
# message, so a feature switches to cards for new messages only (check `is_card()` before editing an old one).
# Mentions inside card text DO ping (unlike embeds), so every send helper here defaults to NO_PINGS.

SEPARATOR = "---"   # in card(): a divider line


def card(*parts, title: Optional[str] = None, color: discord.Color = BRAND, footer: Optional[str] = None,
         thumbnail: Optional[str] = None) -> discord.ui.Container:
    """
    Build a card. Each part can be:
    - a string: a block of text (empty strings are skipped)
    - SEPARATOR: a divider
    - a list or tuple of buttons/selects: an action row (five buttons per row; a select gets a row of its own)
    - any discord.ui item (Section, ActionRow, TextDisplay, MediaGallery, Separator): added as is
    - None: skipped
    `thumbnail` (an image URL) sits beside the title and the first block of text.
    """
    items: List[discord.ui.Item] = []
    first_text = None
    for part in parts:
        if part is None or part == "":
            continue
        if part == SEPARATOR:
            items.append(discord.ui.Separator())
        elif isinstance(part, str):
            if thumbnail and first_text is None and not items:
                first_text = part
                continue
            items.append(discord.ui.TextDisplay(part))
        elif isinstance(part, (list, tuple)):
            items.extend(action_rows(part))
        else:
            items.append(part)
    head = [f"### {title}"] if title else []
    if thumbnail:
        texts = [discord.ui.TextDisplay(t) for t in head + ([first_text] if first_text else [])]
        if not texts:
            texts = [discord.ui.TextDisplay("​")]
        items.insert(0, discord.ui.Section(*texts, accessory=discord.ui.Thumbnail(thumbnail)))
    elif head:
        items.insert(0, discord.ui.TextDisplay(head[0]))
    if footer:
        items.append(discord.ui.TextDisplay(hint(footer)))
    return discord.ui.Container(*items, accent_color=color)


def action_rows(items) -> List[discord.ui.ActionRow]:
    """Buttons five to a row; each select menu on its own row."""
    rows: List[discord.ui.ActionRow] = []
    current: List[discord.ui.Item] = []
    for item in items:
        if item is None:
            continue
        inner = getattr(item, "item", item)   # a DynamicItem wraps its button
        if isinstance(inner, discord.ui.Select) or isinstance(item, discord.ui.Select):
            if current:
                rows.append(discord.ui.ActionRow(*current))
                current = []
            rows.append(discord.ui.ActionRow(item))
            continue
        current.append(item)
        if len(current) == 5:
            rows.append(discord.ui.ActionRow(*current))
            current = []
    if current:
        rows.append(discord.ui.ActionRow(*current))
    return rows


def settings_text(rows) -> str:
    """`**Name** · value` lines for a settings card. Booleans become On/Off; None becomes "not set"."""
    out = []
    for name, value in rows:
        if isinstance(value, bool):
            value = "On" if value else "Off"
        elif value is None or value == "":
            value = "not set"
        out.append(f"**{name}** · {value}")
    return "\n".join(out)


class CardView(discord.ui.LayoutView):
    """A message made of cards. `CardView(card(...))`, or subclass and override `build()` to redraw on changes."""

    def __init__(self, *cards: discord.ui.Item, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        for item in cards:
            self.add_item(item)

    def build(self) -> Optional[discord.ui.Container]:
        return None

    def redraw(self):
        """Replace the contents with a fresh `build()`."""
        built = self.build()
        if built is not None:
            self.clear_items()
            self.add_item(built)
        return self


class ExpiringCard(CardView):
    """
    A short-lived card menu for one person (the card version of ExpiringView). Anyone else gets a private notice.
    When it times out, its buttons and menus grey out and the card gets an "Expired." line. Set `view.message`
    after sending (a message, or the interaction whose response it is).
    """

    expired_note = "Expired."
    not_yours = ExpiringView.not_yours

    def __init__(self, owner_id: Optional[int], *cards: discord.ui.Item, timeout: Optional[float] = 180):
        super().__init__(*cards, timeout=timeout)
        self.owner_id = owner_id
        self.message: Optional[Target] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner_id is None or interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(self.not_yours, ephemeral=True)
        return False

    def disable_all(self):
        for item in self.walk_children():
            if hasattr(item, "disabled") and not getattr(item, "url", None):
                item.disabled = True

    def add_note(self, note: str):
        """Add a small grey line at the bottom of the (first) card."""
        container = next((c for c in self.children if isinstance(c, discord.ui.Container)), None)
        target = container or self
        text = hint(note)
        if not any(isinstance(i, discord.ui.TextDisplay) and i.content == text for i in target.children):
            target.add_item(discord.ui.TextDisplay(text))

    async def on_timeout(self):
        if self.message is None:
            return
        self.disable_all()
        self.add_note(self.expired_note)
        await edit_quietly(self.message, view=self)


def is_card(message: Optional[discord.Message]) -> bool:
    """True if a message was sent as a card (Components V2). Old embed messages must be edited the old way."""
    flags = getattr(message, "flags", None)
    return bool(getattr(flags, "components_v2", False))


async def send_card(target, view: discord.ui.LayoutView, *, ephemeral: bool = False, reply_to=None, **kwargs):
    """
    Send a card to a Context, channel, user or interaction. Ping-free unless `allowed_mentions` is given.
    Returns the message (for interactions, the response message).
    """
    kwargs.setdefault("allowed_mentions", NO_PINGS)
    if isinstance(target, discord.Interaction):
        if target.response.is_done():
            return await target.followup.send(view=view, ephemeral=ephemeral, wait=True, **kwargs)
        await target.response.send_message(view=view, ephemeral=ephemeral, **kwargs)
        try:
            return await target.original_response()
        except discord.HTTPException:
            return None
    if reply_to is not None:
        kwargs.setdefault("mention_author", False)
        return await reply_to.reply(view=view, **kwargs)
    return await target.send(view=view, **kwargs)
