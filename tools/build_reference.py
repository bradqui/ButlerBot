"""
Regenerate the command reference pages for our own cogs, offline.

Loads each custom cog (every one whitelisted in .gitignore) with a stand-in for Red, then renders its page with the
Handbook cog's own export code, so the result matches `!handbook export`. Pages for Red's built-in and third-party
cogs, and custom-commands.md, still come from `!handbook export` on the live bot: they only change when Red or a
Downloader cog is updated, or when someone adds a custom command or alias.

Setup (once):  python -m pip install --target tools/.pylibs -r tools/requirements.txt
Run:           python tools/build_reference.py           writes docs/reference/<cog>.md and updates index.md
               python tools/build_reference.py --check   only reports what's out of date (exit code 1 if anything is)

Not covered offline: Permissions rules on the server. The live export leaves out cogs and commands that a default
rule denies; none of ours is denied today. If one ever is, list it in DENIED below.
"""

import argparse
import asyncio
import enum
import importlib.util
import os
import re
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
COGS = ROOT / "data" / "cogs" / "CogManager" / "cogs"
REFERENCE = ROOT / "docs" / "reference"
LIBS = Path(__file__).resolve().parent / ".pylibs"
PREFIX = "!"
BOT_NAME = "ButlerBot"
DENIED = set()   # qualified command or cog names a server Permissions rule denies by default

if LIBS.is_dir():
    sys.path.insert(0, str(LIBS))
try:
    import discord
    import discord.ext.commands as dcommands
    from discord import app_commands
except ImportError:
    sys.exit("discord.py isn't installed. Run: python -m pip install --target tools/.pylibs -r tools/requirements.txt")


# ==========================================
#              STAND-IN FOR RED
# ==========================================

class PrivilegeLevel(enum.IntEnum):
    NONE = enum.auto()
    MOD = enum.auto()
    ADMIN = enum.auto()
    GUILD_OWNER = enum.auto()
    BOT_OWNER = enum.auto()


class Requires:
    """The parts of Red's Requires that the handbook reads: privilege level, user permissions, extra checks."""

    def __init__(self, privilege_level=None, user_perms=None, checks=()):
        self.privilege_level = privilege_level
        self.user_perms = user_perms
        self.checks = list(checks)


def _get_decorator(privilege_level, user_perms):
    """Same effect as Red's Requires.get_decorator: the last decorator applied sets the level."""
    def decorator(func):
        target = func.callback if isinstance(func, dcommands.Command) else func
        target.__requires_privilege_level__ = privilege_level
        if user_perms is None:
            target.__requires_user_perms__ = None
        else:
            if getattr(target, "__requires_user_perms__", None) is None:
                target.__requires_user_perms__ = discord.Permissions.none()
            target.__requires_user_perms__.update(**user_perms)
        return func
    return decorator


def _permissions_check(predicate):
    def decorator(func):
        target = func.callback if isinstance(func, dcommands.Command) else func
        target.__dict__.setdefault("__requires_checks__", []).append(predicate)
        return func
    return decorator


class UserFeedbackCheckFailure(dcommands.CheckFailure):
    def __init__(self, message=None, *args):
        self.message = message
        super().__init__(message, *args)


class _Anything(types.ModuleType):
    """A module whose every attribute is a fresh class, for SDKs the cogs only use at run time."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = type(name, (Exception,), {})
        setattr(self, name, value)
        return value


class HelpFormatterABC:
    async def send_help(self, ctx, help_for=None, *, from_help_command=False):
        raise NotImplementedError


def install_stubs():
    red_commands = types.ModuleType("redbot.core.commands")
    red_commands.__dict__.update({k: v for k, v in dcommands.__dict__.items() if not k.startswith("__")})
    red_commands.__path__ = []
    red_commands.PrivilegeLevel = PrivilegeLevel
    red_commands.Requires = Requires
    red_commands.UserFeedbackCheckFailure = UserFeedbackCheckFailure
    red_commands.permissions_check = _permissions_check
    checks = types.ModuleType("redbot.core.checks")
    for module in (red_commands, checks):
        module.is_owner = lambda: _get_decorator(PrivilegeLevel.BOT_OWNER, {})
        module.guildowner_or_permissions = lambda **p: _get_decorator(PrivilegeLevel.GUILD_OWNER, p)
        module.guildowner = lambda: _get_decorator(PrivilegeLevel.GUILD_OWNER, {})
        module.admin_or_permissions = lambda **p: _get_decorator(PrivilegeLevel.ADMIN, p)
        module.admin = lambda: _get_decorator(PrivilegeLevel.ADMIN, {})
        module.mod_or_permissions = lambda **p: _get_decorator(PrivilegeLevel.MOD, p)
        module.mod = lambda: _get_decorator(PrivilegeLevel.MOD, {})
        module.has_permissions = lambda **p: _get_decorator(None, p)
    help_mod = types.ModuleType("redbot.core.commands.help")
    help_mod.HelpFormatterABC = HelpFormatterABC
    red_commands.help = help_mod

    data_dir = Path(tempfile.mkdtemp(prefix="build_reference_"))
    data_manager = types.ModuleType("redbot.core.data_manager")
    data_manager.cog_data_path = lambda cog=None, raw_name=None: data_dir

    chat_formatting = types.ModuleType("redbot.core.utils.chat_formatting")
    chat_formatting.box = lambda text, lang=None: f"```{text}```"
    chat_formatting.humanize_number = str
    chat_formatting.pagify = lambda text, *a, **k: [text]

    core = types.ModuleType("redbot.core")
    core.Config = MagicMock()
    core.checks, core.commands, core.app_commands, core.data_manager = checks, red_commands, app_commands, data_manager
    bot_mod = types.ModuleType("redbot.core.bot")
    bot_mod.Red = object
    google = types.ModuleType("google")
    google.genai = _Anything("google.genai")
    google.genai.types = _Anything("google.genai.types")
    sys.modules.update({
        "redbot": types.ModuleType("redbot"), "redbot.core": core, "redbot.core.bot": bot_mod,
        "redbot.core.commands": red_commands, "redbot.core.commands.help": help_mod, "redbot.core.checks": checks,
        "redbot.core.data_manager": data_manager, "redbot.core.utils": types.ModuleType("redbot.core.utils"),
        "redbot.core.utils.chat_formatting": chat_formatting,
        "anthropic": _Anything("anthropic"), "google": google, "google.genai": google.genai,
        "google.genai.types": google.genai.types,
    })


class StubBot(dcommands.Bot):
    """Just enough of Red's bot for Handbook.build_reference. Cogs are instantiated, never added or started."""

    def __init__(self):
        super().__init__(command_prefix=PREFIX, intents=discord.Intents.none())
        self.loaded = {}

    @property
    def cogs(self):
        return types.MappingProxyType(self.loaded)

    def get_cog(self, name):
        return self.loaded.get(name)

    async def cog_disabled_in_guild(self, cog, guild):
        return False


# ==========================================
#                 LOADING
# ==========================================

def custom_cogs():
    """Package names of our cogs: the ones .gitignore tracks (folders without __init__.py, like _shared, aren't cogs)."""
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    names = re.findall(r"^!/data/cogs/CogManager/cogs/([\w-]+)/$", text, re.MULTILINE)
    return sorted(name for name in names if (COGS / name / "__init__.py").exists())


def load_cog(package, bot):
    init = (COGS / package / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r"^from \.(\w+) import (\w+)", init, re.MULTILINE)
    if not match:
        raise RuntimeError(f"{package}/__init__.py doesn't import its cog class")
    module_name, class_name = match.groups()
    spec = importlib.util.spec_from_file_location(f"{package}.{module_name}", COGS / package / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, getattr(module, class_name)(bot)


def attach_requires(cog):
    """Red builds `command.requires` from what its check decorators left on the callback."""
    for command in cog.walk_commands():
        callback = command.callback
        command.requires = Requires(getattr(callback, "__requires_privilege_level__", None),
                                    getattr(callback, "__requires_user_perms__", None) or discord.Permissions.none(),
                                    getattr(callback, "__requires_checks__", []))
        if command.qualified_name in DENIED:
            command.hidden = True
        command.cog = cog


# ==========================================
#                 WRITING
# ==========================================

def front_matter_value(text, key):
    match = re.search(rf"^{key}: (.+)$", text, re.MULTILINE)
    return match.group(1) if match else None


def set_front_matter(text, key, value):
    return re.sub(rf"^{key}: .+$", f"{key}: {value}", text, count=1, flags=re.MULTILINE)


def merge_index(index, rows):
    """Replace or insert our cogs' rows in the index's command table, keeping it sorted by name."""
    lines = index.split("\n")
    start = lines.index("|---|---|---|") + 1
    end = start
    while end < len(lines) and lines[end].startswith("| ["):
        end += 1
    table = {re.search(r"'/reference/([^/]+)/'", line).group(1): line for line in lines[start:end]}
    table.update(rows)
    custom = table.pop("custom-commands", None)
    ordered = [table[slug] for slug in sorted(table, key=lambda s: re.search(r"\| \[([^\]]+)\]", table[s])
                                               .group(1).lower())]
    if custom:
        ordered.append(custom)
    return "\n".join(lines[:start] + ordered + lines[end:])


async def build():
    install_stubs()
    bot = StubBot()
    handbook_module = None
    for package in custom_cogs():
        module, cog = load_cog(package, bot)
        if package == "handbook":
            handbook_module, handbook = module, cog
        attach_requires(cog)
        bot.loaded[cog.qualified_name] = cog
    if handbook_module is None:
        raise RuntimeError("the handbook cog isn't tracked")

    me = types.SimpleNamespace(display_name=BOT_NAME)
    guild = types.SimpleNamespace(id=0, me=me)
    pages = await handbook.build_reference(guild, PREFIX)
    denied_cogs = {name for name in DENIED if name in bot.loaded}
    generated = {path: text for path, text in pages.items()
                 if path not in ("reference/index.md", "reference/custom-commands.md")
                 and front_matter_value(text, "title") not in denied_cogs}
    rows = {}
    for line in pages["reference/index.md"].split("\n"):
        match = re.match(r"\| \[[^\]]+\]\(\{\{ '/reference/([^/]+)/'", line)
        if match and match.group(1) != "custom-commands":
            rows[match.group(1)] = line
    return generated, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    parser.add_argument("--check", action="store_true", help="report out-of-date pages without writing")
    args = parser.parse_args()
    generated, rows = asyncio.run(build())

    changes = {}
    renumber = False
    for path, text in generated.items():
        file = REFERENCE / Path(path).name
        if file.exists():
            old = file.read_text(encoding="utf-8")
            text = set_front_matter(text, "nav_order", front_matter_value(old, "nav_order"))
        else:
            old, renumber = None, True
        if text != old:
            changes[file] = text
    index_file = REFERENCE / "index.md"
    index = index_file.read_text(encoding="utf-8")
    new_index = merge_index(index, {slug: row for slug, row in rows.items()
                                    if f"reference/{slug}.md" in generated})
    if new_index != index:
        changes[index_file] = new_index
    if renumber:   # a new cog: number every page alphabetically, as the export does
        names = sorted(({p.stem for p in REFERENCE.glob("*.md")} | {Path(p).stem for p in generated})
                       - {"index", "custom-commands"})
        for order, slug in enumerate(names, 1):
            file = REFERENCE / f"{slug}.md"
            text = changes.get(file) or file.read_text(encoding="utf-8")
            new = set_front_matter(text, "nav_order", order)
            if new != (file.read_text(encoding="utf-8") if file.exists() else None):
                changes[file] = new

    if not changes:
        print("Reference is up to date.")
        return 0
    for file in sorted(changes):
        print(("out of date: " if args.check else "wrote ") + str(file.relative_to(ROOT)).replace(os.sep, "/"))
        if not args.check:
            file.write_text(changes[file], encoding="utf-8", newline="\n")
    return 1 if args.check else 0


if __name__ == "__main__":
    sys.exit(main())
