import csv
import importlib.util
import logging
import os
import re
import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import List, Optional

import discord
from redbot.core import commands, checks, Config, data_manager


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
log = logging.getLogger("red.censord")

LEVELS = ("off", "low", "high")
ACTIONS = ("delete", "kick", "ban")
STRATEGIES = ("include", "exclude")

class Censord(commands.Cog):
    """
    Censor chat using CSV-based lists with specific levels and threshold punishments.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8473829201, force_registration=True)

        # Default Configs
        default_guild = {
            "global_level": "off",          # off, low, high
            "action": "delete",             # delete, kick, ban
            "threshold_count": 3,           # X messages
            "threshold_time": 60,           # within Y seconds
            "excluded_channels": [],        # Channel IDs to ignore
            "included_channels": [],        # Channel IDs to force check (overrides global off)
            "strategy": "exclude",          # 'exclude' or 'include'
            "admin_role": None              # Role ID allowed to edit settings
        }
        
        default_channel = {
            "override_level": None,         # None, 'off', 'low', 'high'
            "override_action": None         # None, 'delete', 'kick', 'ban'
        }

        self.config.register_guild(**default_guild)
        self.config.register_channel(**default_channel)

        self.violations = defaultdict(lambda: defaultdict(deque))
        self.word_lists = {"low": [], "high": []} 
        
        self.data_path = data_manager.cog_data_path(self)
        self._initialize_csvs()
        self._load_words()

    # --------------------------------------------------------------------------
    # UTILITIES & LOGIC
    # --------------------------------------------------------------------------

    def _initialize_csvs(self):
        """Creates default CSV files if they don't exist."""
        if not os.path.exists(self.data_path):
            os.makedirs(self.data_path)

        # Initialize with horizontal lists
        low_file = self.data_path / "low.csv"
        if not low_file.exists():
            with open(low_file, "w", newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["*nigger*", "*faggot*", "*retard*", "*chink*", "*kike*"])

        high_file = self.data_path / "high.csv"
        if not high_file.exists():
            with open(high_file, "w", newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["*fuck*", "*shit*", "*bitch*", "*cunt*", "*whore*"])

    def _load_words(self):
        """Loads CSV words into memory. Robustly handles single-line comma lists."""
        self.word_lists = {"low": [], "high": []}
        count = 0
        
        for level in ["low", "high"]:
            file_path = self.data_path / f"{level}.csv"
            if file_path.exists():
                with open(file_path, "r", encoding='utf-8') as f:
                    # skipinitialspace=True handles "word1, word2" (space after comma)
                    reader = csv.reader(f, skipinitialspace=True)
                    for row in reader:
                        for cell in row:
                            if not cell or not cell.strip(): 
                                continue
                            
                            pattern_str = cell.strip()
                            clean_pattern = re.escape(pattern_str).replace(r"\*", ".*")
                            
                            try:
                                # Add word boundaries if no wildcard is present
                                if ".*" not in clean_pattern:
                                    clean_pattern = fr"\b{clean_pattern}\b"
                                    
                                regex = re.compile(clean_pattern, re.IGNORECASE)
                                self.word_lists[level].append(regex)
                                count += 1
                            except re.error:
                                log.error(f"Failed to compile regex for: {pattern_str}")
        return count

    def _update_csv(self, level: str, word: str, add: bool = True) -> bool:
        """
        Add or remove one entry, keeping the single-line format. Returns whether the list changed (False when the
        word was already on it, or wasn't there to remove).
        """
        word = word.strip()
        file_path = self.data_path / f"{level}.csv"
        all_words = []

        # 1. Read existing words into a simple list
        if file_path.exists():
            with open(file_path, "r", encoding='utf-8') as f:
                reader = csv.reader(f, skipinitialspace=True)
                for row in reader:
                    for cell in row:
                        if cell.strip():
                            all_words.append(cell.strip())

        # 2. Modify list
        if add == (word in all_words):
            return False
        if add:
            all_words.append(word)
        else:
            all_words.remove(word)

        # 3. Write back as ONE horizontal row
        with open(file_path, "w", newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if all_words:
                writer.writerow(all_words)
        
        # 4. Reload memory
        self._load_words()
        return True

    async def _check_content(self, text: str, level: str) -> bool:
        patterns_to_check = []
        if level in ["low", "high"]:
            patterns_to_check.extend(self.word_lists["low"])
        if level == "high":
            patterns_to_check.extend(self.word_lists["high"])

        for pattern in patterns_to_check:
            if pattern.search(text):
                return True
        return False

    async def _execute_punishment(self, message: discord.Message, action: str):
        guild = message.guild
        user = message.author
        reason = "Censord Bot: Chat Threshold Exceeded"
        
        try:
            if action == "kick":
                await guild.kick(user, reason=reason)
                await message.channel.send(f"👢 **{user.display_name}** was kicked for repeated offensive language.",
                                           allowed_mentions=ui.NO_PINGS)
            elif action == "ban":
                await guild.ban(user, reason=reason, delete_message_days=1)
                await message.channel.send(f"🔨 **{user.display_name}** was banned for repeated offensive language.",
                                           allowed_mentions=ui.NO_PINGS)
        except discord.Forbidden:
            log.warning(f"Failed to execute {action} on {user} in {guild}.")

    # --------------------------------------------------------------------------
    # PERMISSIONS CHECK
    # --------------------------------------------------------------------------

    async def _has_permission(self, ctx):
        """
        Custom check: 
        Returns True if user has Manage Guild permissions OR the configured Censor Admin Role.
        """
        if await self.bot.is_owner(ctx.author):
            return True
        
        if ctx.author.guild_permissions.manage_guild:
            return True
        
        admin_role_id = await self.config.guild(ctx.guild).admin_role()
        if admin_role_id:
            role = ctx.guild.get_role(admin_role_id)
            if role and role in ctx.author.roles:
                return True
                
        return False

    # --------------------------------------------------------------------------
    # LISTENERS
    # --------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return

        # Immunity check: Admins and Mods are always immune
        if await self.bot.is_admin(message.author) or await self.bot.is_mod(message.author):
            return

        settings = await self.config.guild(message.guild).all()
        chan_settings = await self.config.channel(message.channel).all()

        level = chan_settings["override_level"]
        if level is None:
            chan_id = message.channel.id
            if settings["strategy"] == "include" and chan_id not in settings["included_channels"]:
                return
            if settings["strategy"] == "exclude" and chan_id in settings["excluded_channels"]:
                return
            level = settings["global_level"]

        if level == "off":
            return

        if await self._check_content(message.content, level):
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

            action = chan_settings["override_action"] or settings["action"]
            user_history = self.violations[message.guild.id][message.author.id]
            now = time.time()
            user_history.append(now)

            cutoff = now - settings["threshold_time"]
            while user_history and user_history[0] < cutoff:
                user_history.popleft()

            if len(user_history) >= settings["threshold_count"]:
                await self._execute_punishment(message, action)
                self.violations[message.guild.id][message.author.id].clear()
            else:
                # Mention without a ping: the warning disappears after 3 seconds, so a ping would leave a ghost.
                await message.channel.send(f"⚠️ {message.author.mention}, watch your language.", delete_after=3,
                                           allowed_mentions=ui.NO_PINGS)

    # --------------------------------------------------------------------------
    # COMMANDS
    # --------------------------------------------------------------------------

    @commands.group(aliases=["censor"])
    @commands.guild_only()
    async def censord(self, ctx):
        """
        Main configuration command for the Censord bot.
        """
        if ctx.invoked_subcommand is None:
            # If no subcommand invoke, show help
            await ctx.send_help()

    @censord.command()
    async def setrole(self, ctx, role: discord.Role = None):
        """
        Set a Discord Role that is allowed to edit censorship settings.
        
        If no role is provided, the setting is cleared (restricted to Manage Server only).
        """
        # Only someone with Manage Guild can assign the Censor Role initially
        if not ctx.author.guild_permissions.manage_guild and not await self.bot.is_owner(ctx.author):
            return await ctx.send("🔒 You need the Manage Server permission to change the filter admin role.")

        if role:
            await self.config.guild(ctx.guild).admin_role.set(role.id)
            await ctx.send(f"✅ **{role.name}** can now change the word filter settings.")
        else:
            await self.config.guild(ctx.guild).admin_role.set(None)
            await ctx.send("✅ Filter admin role cleared. Only people with Manage Server can change the settings.")

    async def cog_check(self, ctx):
        """Global check for the cog's commands (except setrole which has its own logic)."""
        if ctx.command.name == "setrole":
            return True
        if await self._has_permission(ctx):
            return True
        raise commands.UserFeedbackCheckFailure(
            "🔒 Only people with Manage Server or the filter admin role can change the word filter.")

    @censord.command()
    async def reload(self, ctx):
        """
        Reloads the CSV word lists from the data folder.
        
        Use this command after manually editing the CSV files on the disk
        to apply changes immediately without reloading the entire cog.
        """
        count = self._load_words()
        await ctx.send(f"✅ Reloaded {ui.plural(count, 'pattern')} from the word lists.")

    @censord.command()
    async def config(self, ctx):
        """
        Displays a dashboard of the current censorship configuration.

        Shows:
        - Current global level (Off/Low/High)
        - Current punishment action
        - Threshold settings
        - Channel strategies (Include/Exclude counts)
        - Word list counts
        - Configured Admin Role
        """
        settings = await self.config.guild(ctx.guild).all()

        embed = discord.Embed(title="🛡️ Censord settings", color=ui.BRAND)

        embed.add_field(name="Server level", value=settings["global_level"].capitalize(), inline=True)
        embed.add_field(name="Action", value=settings["action"].capitalize(), inline=True)
        embed.add_field(name="Strategy", value=settings["strategy"].capitalize(), inline=True)

        embed.add_field(name="Threshold", inline=False,
                        value=f"{ui.plural(settings['threshold_count'], 'message')} in "
                              f"{ui.plural(settings['threshold_time'], 'second')}")

        inc = len(settings["included_channels"])
        exc = len(settings["excluded_channels"])
        embed.add_field(name="Channels", value=f"Included: {inc}\nExcluded: {exc}", inline=True)

        embed.add_field(name="Word lists", inline=True,
                        value=f"Low: {len(self.word_lists['low'])}\nHigh: {len(self.word_lists['high'])}")

        role_id = settings["admin_role"]
        role_name = ctx.guild.get_role(role_id).mention if role_id and ctx.guild.get_role(role_id) else "None"
        embed.add_field(name="Admin role", value=role_name, inline=False)

        await ctx.send(embed=embed, allowed_mentions=ui.NO_PINGS)

    @censord.command()
    async def level(self, ctx, level: str, channel: discord.TextChannel = None):
        """
        Sets the censorship level to Off, Low, or High.

        Arguments:
        - level: 'off', 'low', or 'high'.
        - channel (optional): If specified, the level applies ONLY to that channel.
                              If omitted, it sets the global server level.
        """
        level = level.lower()
        if level not in LEVELS:
            return await ctx.send("❓ The level can be `off`, `low` or `high`.")

        if channel:
            await self.config.channel(channel).override_level.set(level)
            await ctx.send(f"✅ The level in {channel.mention} is now **{level}**.")
        else:
            await self.config.guild(ctx.guild).global_level.set(level)
            await ctx.send(f"✅ The server level is now **{level}**.")

    @censord.command()
    async def action(self, ctx, action: str, channel: discord.TextChannel = None):
        """
        Sets the punishment action for violations.

        Arguments:
        - action: 'delete', 'kick', or 'ban'.
        - channel (optional): If specified, the action applies ONLY to that channel.
                              If omitted, it sets the global server action.
        """
        action = action.lower()
        if action not in ACTIONS:
            return await ctx.send("❓ The action can be `delete`, `kick` or `ban`.")

        if channel:
            await self.config.channel(channel).override_action.set(action)
            await ctx.send(f"✅ The action in {channel.mention} is now **{action}**.")
        else:
            await self.config.guild(ctx.guild).action.set(action)
            await ctx.send(f"✅ The server action is now **{action}**.")

    @censord.command()
    async def threshold(self, ctx, count: int, seconds: int):
        """
        Sets the violation threshold for punishments.

        The bot punishes a user if they send [count] violating messages within [seconds].
        Both numbers must be at least 1.

        Example: [p]censor threshold 5 10
        (Punishes if 5 bad messages are sent in 10 seconds).
        """
        if count < 1 or seconds < 1:
            return await ctx.send("❓ Both numbers need to be at least 1, like "
                                  f"`{await self._prefix(ctx)}censor threshold 3 60`.")
        await self.config.guild(ctx.guild).threshold_count.set(count)
        await self.config.guild(ctx.guild).threshold_time.set(seconds)
        await ctx.send(f"✅ The punishment now comes after {ui.plural(count, 'violation')} within "
                       f"{ui.plural(seconds, 'second')}.")

    @censord.command()
    async def strategy(self, ctx, mode: str):
        """
        Sets the global channel monitoring strategy.

        Options:
        - include: Whitelist mode. The bot ONLY monitors channels added via `[p]censor includechan`.
        - exclude: Blacklist mode. The bot monitors ALL channels EXCEPT those added via `[p]censor exceptchan`.
        """
        mode = mode.lower()
        if mode not in STRATEGIES:
            return await ctx.send("❓ The strategy can be `include` or `exclude`.")

        await self.config.guild(ctx.guild).strategy.set(mode)
        await ctx.send(f"✅ The strategy is now **{mode}**.")

    @censord.command()
    async def exceptchan(self, ctx, channel: discord.TextChannel):
        """
        Toggles a channel for the 'Exclude' strategy.

        If the strategy is 'exclude', adding a channel here stops the bot from monitoring it.
        Running the command again removes it from the list.
        """
        async with self.config.guild(ctx.guild).excluded_channels() as chans:
            if channel.id in chans:
                chans.remove(channel.id)
                await ctx.send(f"✅ {channel.mention} is off the exceptions list, so it's watched again.")
            else:
                chans.append(channel.id)
                await ctx.send(f"✅ {channel.mention} is on the exceptions list, so it's ignored.")

    @censord.command()
    async def includechan(self, ctx, channel: discord.TextChannel):
        """
        Toggles a channel for the 'Include' strategy.

        If the strategy is 'include', adding a channel here makes the bot monitor it.
        Running the command again removes it from the list.
        """
        async with self.config.guild(ctx.guild).included_channels() as chans:
            if channel.id in chans:
                chans.remove(channel.id)
                await ctx.send(f"✅ {channel.mention} is off the include list, so it's ignored.")
            else:
                chans.append(channel.id)
                await ctx.send(f"✅ {channel.mention} is on the include list, so it's watched.")

    # ---------- word lists ----------

    async def _prefix(self, ctx) -> str:
        """The server's real text prefix (not a bot mention), for hints."""
        for prefix in await self.bot.get_valid_prefixes(ctx.guild):
            if not prefix.startswith("<@"):
                return prefix
        return "!"

    async def _hide_command(self, ctx) -> bool:
        """Delete the command message so the word isn't left in chat. Returns whether that worked."""
        try:
            await ctx.message.delete()
            return True
        except (discord.HTTPException, AttributeError):
            return False

    async def _change_word(self, ctx, level: str, word: str, add: bool):
        """addword/delword. The replies are public, so they never repeat the word."""
        hidden = await self._hide_command(ctx)
        note = "I deleted your command so the word isn't left in chat." if hidden else None
        level = level.lower()
        if level not in ("low", "high"):
            return await ctx.send(ui.line(ui.ASK, "The list can be `low` or `high`.", note))
        if not word.strip():
            return await ctx.send(ui.line(ui.ASK, "Give a word or phrase.", note))
        changed = self._update_csv(level, word, add=add)
        if add:
            text = (ui.line(ui.DONE, f"Added that word to the **{level}** list.", note) if changed
                    else ui.line(ui.WARN, f"That word is already on the **{level}** list.", note))
        else:
            text = (ui.line(ui.DONE, f"Removed that word from the **{level}** list.", note) if changed
                    else ui.line(ui.ASK, f"That word wasn't on the **{level}** list. It has to match the entry "
                                         "exactly.", note))
        await ctx.send(text)

    @censord.command()
    async def addword(self, ctx, level: str, *, word: str):
        """
        Adds a word or phrase to the censorship list.

        Your command message is deleted (when I can), and the reply doesn't repeat the word.

        Arguments:
        - level: 'low' or 'high'.
        - word: The word to censor. Supports wildcards (e.g. *bad*).
        """
        await self._change_word(ctx, level, word, add=True)

    @censord.command()
    async def delword(self, ctx, level: str, *, word: str):
        """
        Removes a word or phrase from the censorship list.

        Your command message is deleted (when I can), and the reply doesn't repeat the word.

        Arguments:
        - level: 'low' or 'high'.
        - word: The word to remove. Must match the existing entry exactly.
        """
        await self._change_word(ctx, level, word, add=False)
