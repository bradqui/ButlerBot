"""Test harness: real discord.py, stubbed Red, in-memory Config, fake guild objects."""
import copy as _copy
import enum
import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
# Libraries installed with `pip install --target tests/pylibs` (local use); CI installs them normally instead.
# TESTS_NO_PYLIBS=1 skips the folder, e.g. to run under a different Python than it was built for.
if os.path.isdir(os.path.join(HERE, "pylibs")) and not os.environ.get("TESTS_NO_PYLIBS"):
    sys.path.insert(0, os.path.join(HERE, "pylibs"))

import discord  # noqa: E402
import discord.ext.commands as dcommands  # noqa: E402
from discord import app_commands as d_app_commands  # noqa: E402

COGS = os.path.join(os.path.dirname(HERE), "data", "cogs", "CogManager", "cogs")


# ---------------- in-memory Config ----------------

class _Access:
    def __init__(self, value):
        self.value = value

    def __await__(self):
        async def get():
            return _copy.deepcopy(self.value.get())
        return get().__await__()

    async def __aenter__(self):
        self.obj = self.value.live()
        return self.obj

    async def __aexit__(self, *exc):
        self.value.store[self.value.name] = self.obj


class _Value:
    def __init__(self, store, name, default):
        self.store, self.name, self.default = store, name, default

    def get(self):
        return self.store.get(self.name, _copy.deepcopy(self.default))

    def live(self):
        return self.store.setdefault(self.name, _copy.deepcopy(self.default))

    def __call__(self):
        return _Access(self)

    async def set(self, value):
        self.store[self.name] = _copy.deepcopy(value)

    async def clear(self):
        self.store.pop(self.name, None)


class _Scope:
    def __init__(self, store, defaults):
        object.__setattr__(self, "_store", store)
        object.__setattr__(self, "_defaults", defaults)

    def __getattr__(self, name):
        if name not in self._defaults:
            raise AttributeError(f"unregistered config key {name}")
        return _Value(self._store, name, self._defaults[name])

    async def all(self):
        return {**_copy.deepcopy(self._defaults), **_copy.deepcopy(self._store)}

    async def clear(self):
        self._store.clear()


class FakeConfig:
    def __init__(self):
        self._defaults = {k: {} for k in ("global", "guild", "channel", "user", "member")}
        self._data = {k: {} for k in self._defaults}

    def register_global(self, **kw): self._defaults["global"].update(kw)
    def register_guild(self, **kw): self._defaults["guild"].update(kw)
    def register_channel(self, **kw): self._defaults["channel"].update(kw)
    def register_user(self, **kw): self._defaults["user"].update(kw)
    def register_member(self, **kw): self._defaults["member"].update(kw)

    def _scope(self, kind, key):
        return _Scope(self._data[kind].setdefault(key, {}), self._defaults[kind])

    def guild(self, g): return self._scope("guild", g.id)
    def guild_from_id(self, gid): return self._scope("guild", gid)
    def channel(self, c): return self._scope("channel", c.id)
    def user(self, u): return self._scope("user", u.id)
    def user_from_id(self, uid): return self._scope("user", uid)
    def member(self, m): return self._scope("member", (m.guild.id, m.id))

    async def all_guilds(self):
        return {gid: {**_copy.deepcopy(self._defaults["guild"]), **_copy.deepcopy(d)}
                for gid, d in self._data["guild"].items()}

    async def all_members(self, guild=None):
        out = {}
        for (gid, uid), d in self._data["member"].items():
            out.setdefault(gid, {})[uid] = {**_copy.deepcopy(self._defaults["member"]), **_copy.deepcopy(d)}
        return out.get(guild.id, {}) if guild is not None else out

    def member_from_ids(self, gid, uid): return self._scope("member", (gid, uid))

    async def all_channels(self):
        return {cid: {**_copy.deepcopy(self._defaults["channel"]), **_copy.deepcopy(d)}
                for cid, d in self._data["channel"].items()}

    async def all_users(self):
        return {uid: {**_copy.deepcopy(self._defaults["user"]), **_copy.deepcopy(d)}
                for uid, d in self._data["user"].items()}

    def __getattr__(self, name):
        if name.startswith("_") or name not in self._defaults["global"]:
            raise AttributeError(name)
        return _Value(self._data["global"].setdefault("g", {}), name, self._defaults["global"][name])


# ---------------- stub Red ----------------

class PrivilegeLevel(enum.IntEnum):
    NONE = 1
    MOD = 2
    ADMIN = 3
    GUILD_OWNER = 4
    BOT_OWNER = 5


class UserFeedbackCheckFailure(dcommands.CheckFailure):
    def __init__(self, message=None, *args):
        self.message = message
        super().__init__(message, *args)


_orig_can_run = dcommands.Command.can_run


async def _red_can_run(self, ctx, /, *, check_all_parents=False, change_permission_state=False):
    if check_all_parents:
        for parent in reversed(self.parents):
            if not await _orig_can_run(parent, ctx):
                return False
    return await _orig_can_run(self, ctx)


dcommands.Command.can_run = _red_can_run
dcommands.Command.is_enabled = lambda self, guild=None: self.enabled


async def _ctx_send(self, content=None, **kwargs):
    return await self.channel.send(content, **kwargs)


async def _ctx_tick(self, **kwargs):
    return True


dcommands.Context.send = _ctx_send
dcommands.Context.tick = _ctx_tick

red_commands = types.ModuleType("redbot.core.commands")
red_commands.__dict__.update({k: v for k, v in dcommands.__dict__.items() if not k.startswith("__")})
red_commands.PrivilegeLevel = PrivilegeLevel
red_commands.UserFeedbackCheckFailure = UserFeedbackCheckFailure

checks = types.ModuleType("redbot.core.checks")
for name in ("admin_or_permissions", "mod_or_permissions", "is_owner", "admin", "mod"):
    setattr(checks, name, lambda *a, **k: (lambda f: f))


class Config:
    @staticmethod
    def get_conf(*a, **k):
        return FakeConfig()


redbot = types.ModuleType("redbot")
core = types.ModuleType("redbot.core")
core.Config, core.checks, core.commands, core.app_commands = Config, checks, red_commands, d_app_commands
botmod = types.ModuleType("redbot.core.bot")
botmod.Red = object
utils = types.ModuleType("redbot.core.utils")
cf = types.ModuleType("redbot.core.utils.chat_formatting")
cf.box = lambda t, lang=None: f"```{t}```"
cf.humanize_number = str


def _pagify(text, page_length=2000):
    return [text[i:i + page_length] for i in range(0, len(text), page_length)] or [text]


cf.pagify = _pagify
red_commands.__path__ = []  # a package, so redbot.core.commands.help can be imported
help_mod = types.ModuleType("redbot.core.commands.help")


class HelpFormatterABC:
    async def send_help(self, ctx, help_for=None, *, from_help_command=False):
        raise NotImplementedError


help_mod.HelpFormatterABC = HelpFormatterABC
red_commands.help = help_mod
data_manager = types.ModuleType("redbot.core.data_manager")
import tempfile as _tempfile, pathlib as _pathlib
DATA_DIR = _pathlib.Path(_tempfile.mkdtemp(prefix="redtest_"))
data_manager.cog_data_path = lambda cog=None, raw_name=None: DATA_DIR
core.data_manager = data_manager
for name, mod in {"redbot": redbot, "redbot.core": core, "redbot.core.bot": botmod, "redbot.core.utils": utils,
                  "redbot.core.utils.chat_formatting": cf, "redbot.core.commands": red_commands,
                  "redbot.core.checks": checks,
                  "redbot.core.data_manager": data_manager, "redbot.core.commands.help": help_mod}.items():
    sys.modules[name] = mod
anthropic_stub = types.ModuleType("anthropic")


class APIError(Exception):
    def __init__(self, message="error", *a, **k):
        super().__init__(message)
        self.message = message


class APIStatusError(APIError):
    status_code = 400


for _name, _base in (("BadRequestError", APIStatusError), ("AuthenticationError", APIStatusError),
                     ("PermissionDeniedError", APIStatusError), ("NotFoundError", APIStatusError),
                     ("RateLimitError", APIStatusError), ("APITimeoutError", APIError),
                     ("APIConnectionError", APIError)):
    setattr(anthropic_stub, _name, type(_name, (_base,), {}))
anthropic_stub.APIError, anthropic_stub.APIStatusError = APIError, APIStatusError
anthropic_stub.AsyncAnthropic = MagicMock
sys.modules["anthropic"] = anthropic_stub


def load(package, module):
    spec = importlib.util.spec_from_file_location(f"{package}_{module}", os.path.join(COGS, package, f"{module}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # Red's loader registers cog modules too
    spec.loader.exec_module(mod)
    if package == "gamemanager":
        # No network in tests, and names count as confirmed by Steam unless a test installs its own lookup
        # (test_titles does), so the "couldn't confirm" prompt doesn't wait on made-up games.
        async def steam_confirms(name):
            return (mod.clean_title(name), None)
        mod.steam_exact_title = steam_confirms
    return mod


# ---------------- cards (Components V2) ----------------

def is_layout(view) -> bool:
    return view is not None and getattr(view, "has_components_v2", lambda: False)()


LAYOUT_PROBLEMS = []   # every Discord-limit violation seen in a sent or edited card, across a test run


def validate_layout(view, content=None, embeds=None) -> list:
    """Problems Discord would reject in a Components V2 message (limits from the component reference)."""
    problems = []
    if content not in (None, ""):
        problems.append("content with a card")
    if embeds:
        problems.append("embeds with a card")
    if view.total_children_count > 40:
        problems.append(f"{view.total_children_count} components (max 40)")
    texts = [i for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay)]
    if sum(len(t.content) for t in texts) > 4000:
        problems.append(f"{sum(len(t.content) for t in texts)} characters of text (max 4000)")
    for t in texts:
        if not t.content.strip():
            problems.append("empty text block")
    for item in view.walk_children():
        item = item.item if isinstance(item, discord.ui.DynamicItem) else item
        if isinstance(item, discord.ui.Container) and not item.children:
            problems.append("empty container")
        if isinstance(item, discord.ui.Section):
            n = len([c for c in item.children if isinstance(c, discord.ui.TextDisplay)])
            if not 1 <= n <= 3 or item.accessory is None:
                problems.append(f"section with {n} texts / accessory {item.accessory!r}")
        if isinstance(item, discord.ui.ActionRow):
            kids = list(item.children)
            selects = [k for k in kids if isinstance(getattr(k, "item", k), discord.ui.Select)]
            if not kids or len(kids) > 5 or (selects and len(kids) > 1):
                problems.append(f"action row with {len(kids)} items")
        if isinstance(item, discord.ui.Button):
            if item.label and len(item.label) > 80:
                problems.append(f"button label too long: {item.label[:30]}…")
            if not item.label and not item.emoji:
                problems.append("button with no label or emoji")
            if item.url is None and (not item.custom_id or len(item.custom_id) > 100):
                problems.append(f"bad custom_id {item.custom_id!r}")
        if isinstance(item, discord.ui.Select):
            if len(item.options) > 25 or (item.placeholder and len(item.placeholder) > 150):
                problems.append("select over limits")
            for o in item.options:
                if len(o.label) > 100 or (o.description and len(o.description) > 100):
                    problems.append(f"select option too long: {o.label[:30]}…")
        if isinstance(item, discord.ui.Thumbnail):
            url = getattr(item.media, "url", str(item.media))
            if not str(url).startswith(("http://", "https://", "attachment://")):
                problems.append(f"thumbnail url {url!r}")
    try:
        view.to_components()
    except Exception as e:  # noqa: BLE001
        problems.append(f"to_components failed: {e}")
    return problems


def _check_layout(view, content=None, embeds=None):
    if is_layout(view):
        LAYOUT_PROBLEMS.extend(validate_layout(view, content, embeds))


import atexit as _atexit


@_atexit.register
def _report_layout_problems():
    if LAYOUT_PROBLEMS:
        print(f"LAYOUT PROBLEMS ({len(LAYOUT_PROBLEMS)}):", sorted(set(LAYOUT_PROBLEMS))[:20])


def card_text(target) -> str:
    """All text in a card message or LayoutView (titles, body, footers), joined with newlines."""
    view = getattr(target, "view", target)
    if view is None or not hasattr(view, "walk_children"):
        return ""
    return "\n".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))


def card_buttons(target) -> list:
    """Every button in a card message or LayoutView, in order (DynamicItems unwrapped)."""
    view = getattr(target, "view", target)
    if view is None or not hasattr(view, "walk_children"):
        return []
    out = []
    for i in view.walk_children():
        inner = i.item if isinstance(i, discord.ui.DynamicItem) else i
        if isinstance(inner, discord.ui.Button) and inner not in out:
            out.append(inner)
    return out


def card_color(target):
    view = getattr(target, "view", target)
    container = next((c for c in getattr(view, "children", []) if isinstance(c, discord.ui.Container)), None)
    return container.accent_color if container else None


# ---------------- fake Discord objects ----------------

class Perms:
    def __init__(self, administrator=False):
        self.administrator = administrator
        self.manage_guild = administrator
        self.manage_events = False
        self.read_messages = self.view_channel = self.read_message_history = True
        self.send_messages = self.embed_links = self.attach_files = self.add_reactions = True
        self.manage_messages = administrator


class FakeMember:
    def __init__(self, guild, uid, name, admin=False):
        self.guild, self.id, self.name, self.display_name, self.global_name = guild, uid, name, name, None
        self.mention = f"<@{uid}>"
        self.bot = False
        self.roles = []
        self.guild_permissions = Perms(admin)

    def __eq__(self, other):
        return getattr(other, "id", None) == self.id

    def __hash__(self):
        return hash(self.id)


class FakeMessage:
    _next = 1000

    def __init__(self, channel, content=None, author=None, **kw):
        FakeMessage._next += 1
        self.id = FakeMessage._next
        self.channel, self.guild = channel, channel.guild
        self.content, self.author = content or "", author
        self.kw = kw
        self.embeds = [kw["embed"]] if kw.get("embed") else []
        self.view = kw.get("view")
        self.edits = []
        self.attachments, self.mentions, self.reference = [], [], None
        self.webhook_id = None
        import datetime as _dt
        self.created_at, self.edited_at = _dt.datetime.now(_dt.timezone.utc), None
        self.role_mentions, self.channel_mentions = [], []
        self.flags = discord.MessageFlags()
        if is_layout(self.view):
            self.flags.components_v2 = True
            _check_layout(self.view, content, self.embeds)

    @property
    def clean_content(self):
        return self.__dict__.get("_clean", self.content)

    @clean_content.setter
    def clean_content(self, value):
        self.__dict__["_clean"] = value

    async def edit(self, **kw):
        self.edits.append(kw)
        if "view" in kw:
            self.view = kw["view"]
            if is_layout(self.view):
                self.flags.components_v2 = True
                _check_layout(self.view, kw.get("content"), kw.get("embeds") or ([kw["embed"]] if kw.get("embed") else None))
        if kw.get("embed"):
            self.embeds = [kw["embed"]]
        if "content" in kw:
            self.content = kw["content"]
        return self

    def to_reference(self, **kw):
        return None

    async def delete(self, **kw):
        """Remove it from its channel and note the ID in channel.deleted."""
        self.deleted = True
        self.channel.messages.pop(self.id, None)
        self.channel.__dict__.setdefault("deleted", []).append(self.id)


class FakeChannel:
    def __init__(self, guild, cid=500):
        self.guild, self.id = guild, cid
        self.sent = []
        self.messages = {}
        self.mention = f"<#{cid}>"

    async def send(self, content=None, **kw):
        msg = FakeMessage(self, content, author=self.guild.me, **kw)
        self.sent.append(msg)
        self.messages[msg.id] = msg
        return msg

    def history(self, *, after=None, limit=100, **_):
        """The channel's messages (what the bot sent, plus any a test appended to `sent`), oldest first."""
        deleted = set(getattr(self, "deleted", []))

        async def gen():
            count = 0
            for m in sorted(self.sent, key=lambda m: m.id):
                if (after is None or m.id > after.id) and m.id not in deleted:
                    yield m
                    count += 1
                    if limit is not None and count >= limit:
                        return
        return gen()

    def get_partial_message(self, mid):
        return self.messages.get(mid) or FakeMessage(self)

    def permissions_for(self, member):
        return Perms(getattr(getattr(member, "guild_permissions", None), "administrator", False))

    def typing(self):
        class T:
            async def __aenter__(s): pass
            async def __aexit__(s, *a): pass
        return T()


class FakeGuild:
    def __init__(self, gid=1):
        self.id, self.name, self.owner_id = gid, "Test Server", 1
        self.members = []
        self.me = FakeMember(self, 999, "Quillbot")
        self.channel = FakeChannel(self)
        self.channel.name = "general"
        self.text_channels, self.voice_channels, self.stage_channels, self.forums, self.threads = [self.channel], [], [], [], []
        self.afk_channel = None
        self.default_role = FakeMember(self, gid, "@everyone")

    def add(self, uid, name, admin=False):
        m = FakeMember(self, uid, name, admin)
        self.members.append(m)
        return m

    def get_member(self, uid):
        return next((m for m in self.members if m.id == uid), None)

    def get_channel_or_thread(self, cid):
        return next((c for c in self.channels if c.id == cid), None)

    get_channel = get_channel_or_thread

    @property
    def channels(self):
        return [*self.text_channels, *self.voice_channels, *self.stage_channels, *self.forums]

    def get_role(self, rid):
        return None


class FakeResponse:
    def __init__(self, interaction):
        self.i = interaction
        self.done = False
        self.calls = []

    def is_done(self):
        return self.done

    async def send_message(self, content=None, **kw):
        self.done = True
        self.calls.append(("send", content, kw))
        self.i.sent_message = FakeMessage(self.i.channel, content, **kw)

    async def edit_message(self, **kw):
        self.done = True
        self.calls.append(("edit", kw))
        if self.i.message is not None:
            await self.i.message.edit(**kw)

    async def defer(self, **kw):
        self.done = True
        self.calls.append(("defer", kw))

    async def send_modal(self, modal):
        self.done = True
        self.calls.append(("modal", modal))


class FakeFollowup:
    def __init__(self):
        self.calls = []

    async def send(self, content=None, **kw):
        self.calls.append((content, kw))
        return FakeMessage(FakeChannel(FakeGuild()), content, **kw)


class FakeInteraction(discord.Interaction):
    def __init__(self, client, guild, user, channel, message=None):
        self._client, self._guild, self._user, self._channel = client, guild, user, channel
        self.message = message
        self._resp = FakeResponse(self)
        self._follow = FakeFollowup()
        self.sent_message = None

    guild = property(lambda s: s._guild)
    user = property(lambda s: s._user)
    channel = property(lambda s: s._channel)
    response = property(lambda s: s._resp)
    followup = property(lambda s: s._follow)
    client = property(lambda s: s._client)

    async def original_response(self):
        return self.sent_message

    async def edit_original_response(self, **kw):
        self._resp.calls.append(("edit_original", kw))
        if self.message is not None:
            await self.message.edit(**kw)
        return self.message


class TestBot(dcommands.Bot):
    """discord.py Bot plus the Red-only methods the cogs call."""

    def __init__(self, guild, owner_id=1):
        super().__init__(command_prefix="!", intents=discord.Intents.none(), owner_ids={owner_id})
        self.test_guild = guild
        self._connection.user = guild.me

    async def is_owner(self, user):
        return user.id in self.owner_ids

    async def is_admin(self, member):
        return False

    async def is_mod(self, member):
        return False

    async def get_valid_prefixes(self, guild=None):
        return ["!"]

    async def cog_disabled_in_guild(self, cog, guild):
        return False

    async def get_shared_api_tokens(self, name):
        return {"api_key": "test"}

    async def wait_until_red_ready(self):
        return

    async def ignored_channel_or_guild(self, message):
        return True

    async def allowed_by_whitelist_blacklist(self, user):
        return True

    def get_guild(self, gid):
        return self.test_guild if gid == self.test_guild.id else None


# ---------------- DMs (opt-in: call enable_dms() in a test) ----------------

class FakeDMChannel:
    """A member's DM channel. Messages land in `member.dms`; set `member.dms_closed = True` to make sends fail."""

    def __init__(self, member):
        self.recipient, self.id, self.guild = member, 9_000_000 + member.id, None
        self.sent, self.messages = [], {}
        self.mention = f"<@{member.id}>"

    async def send(self, content=None, **kw):
        if getattr(self.recipient, "dms_closed", False):
            raise discord.Forbidden(types.SimpleNamespace(status=403, reason="Forbidden"),
                                    "Cannot send messages to this user")
        msg = FakeMessage(self, content, author=None, **kw)
        self.sent.append(msg)
        self.messages[msg.id] = msg
        return msg


def enable_dms():
    """Give FakeMember a working send() (a DM). Off by default so tests that never DM are unaffected."""
    def dm_channel(self):
        if "_dm" not in self.__dict__:
            self._dm = FakeDMChannel(self)
        return self._dm

    async def send(self, content=None, **kw):
        return await dm_channel(self).send(content, **kw)

    FakeMember.dm_channel = property(dm_channel)
    FakeMember.dms = property(lambda self: dm_channel(self).sent)
    FakeMember.send = send
