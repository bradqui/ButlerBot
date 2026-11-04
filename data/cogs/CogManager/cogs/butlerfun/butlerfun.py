"""
ButlerFun cog for Red-DiscordBot.

AI-powered extras built on the Claude cog (and Gemini and GameManager where noted):

- `/catchup` (or `[p]catchup`, sent by DM): a summary of the channel since you last spoke, only for you.
- `[p]judge`: ButlerBot reads the recent argument and delivers a ruling in character.
- `[p]adventure <setting>`: a group text adventure in its own thread, narrated by ButlerBot.
- `[p]maketrivia <topic>`: writes a trivia list for Red's trivia cog (`our games` uses the server's library).
- `[p]guessgame`: Gemini paints a game from the server's library in an odd style; first correct guess wins.
"""

import asyncio
import difflib
import json
import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import discord
import yaml
from redbot.core import Config, app_commands, checks, commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path

log = logging.getLogger("red.butlerfun")


# ==========================================
#                CONSTANTS
# ==========================================

CATCHUP_SCAN = 400              # messages looked back through
CATCHUP_MAX_CHARS = 24000       # transcript size sent to Claude (newest kept)
CATCHUP_CAUGHT_UP = 8           # if you spoke within this many messages, there's nothing to catch up on
JUDGE_DEFAULT, JUDGE_MAX = 20, 60
ADVENTURE_DEBOUNCE = 8          # seconds to gather everyone's moves before narrating
ADVENTURE_HISTORY = 40          # messages of story kept in context
MAX_ADVENTURES = 3              # running at once per server
TRIVIA_MIN, TRIVIA_MAX = 10, 30
GUESS_SECONDS = 180
GUESS_HINTS = (60, 120)         # seconds in, when hints appear

ART_STYLES = [
    "a Renaissance oil painting", "a child's crayon drawing", "a stained-glass window", "a 1950s pulp magazine cover",
    "an ancient Egyptian wall mural", "a LEGO diorama", "a Japanese woodblock print", "a medieval tapestry",
    "8-bit pixel art", "a claymation film still", "a watercolor postcard", "a vintage travel poster",
    "a Soviet propaganda poster", "a cross-stitch sampler", "a cave painting", "a Victorian botanical illustration",
]

ADVENTURE_RULES = (
    "You are the narrator of a group text adventure in a Discord thread. Setting: {setting}\n\n"
    "How to run it:\n"
    "- Several players take turns. Each user message lists one or more players' moves as \"Name: action\". "
    "Resolve every move in the order given, address players by name, and keep the world consistent.\n"
    "- Write 80-180 words per turn, vivid but brisk. Use Discord markdown sparingly. Narrate in your own voice and "
    "personality, as the one telling the story.\n"
    "- Let actions have real consequences, including failure, but keep it fun. Never act or speak for a player.\n"
    "- End every turn with a short prompt for what happens next, like \"What do you do?\".\n"
    "- Keep it suitable for a general audience. If a move is out of bounds, steer the story elsewhere in character.\n"
    "- When a message says the adventure is ending, wrap the story up in a satisfying final scene of up to 200 words."
)


# ==========================================
#                 HELPERS
# ==========================================

def simplify(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def is_correct_guess(guess: str, answer: str) -> bool:
    """Exact (ignoring case and symbols), or a near miss on a long enough name ("rocket leage")."""
    g, a = simplify(guess), simplify(answer)
    if not g:
        return False
    if g == a:
        return True
    return len(a) >= 6 and len(g) >= 0.7 * len(a) and difflib.SequenceMatcher(None, g, a).ratio() >= 0.85


def hint_for(answer: str, level: int) -> str:
    """Level 1: first letter of each word and the letter count. Level 2: every other letter shown."""
    words = answer.split()
    if level == 1:
        return " ".join(w[0] + "·" * (len(w) - 1) for w in words) + f"  ({len(words)} word{'s' if len(words) > 1 else ''})"
    return " ".join("".join(c if i % 2 == 0 or not c.isalnum() else "·" for i, c in enumerate(w)) for w in words)


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


def parse_trivia_json(text: str) -> List[Tuple[str, List[str]]]:
    """[(question, [answers…]), …] from Claude's JSON reply (a code fence around it is fine)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("["), text.rfind("]")
    data = json.loads(text[start:end + 1]) if start != -1 and end > start else []
    questions = []
    for item in data:
        if not isinstance(item, dict):
            continue
        question = str(item.get("q") or item.get("question") or "").strip()
        answers = [str(a).strip() for a in (item.get("a") or item.get("answers") or []) if str(a).strip()]
        if question and answers and question not in ("AUTHOR", "CONFIG", "DESCRIPTION", "$schema"):
            questions.append((question[:300], answers[:6]))
    return questions


def trivia_slug(topic: str) -> str:
    return "bb_" + (re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")[:30] or "trivia")


# ==========================================
#                   COG
# ==========================================

class ButlerFun(commands.Cog):
    """AI extras: catch-up summaries, ButlerBot's judgments, text adventures, trivia writing and guess the game."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=4418350927, force_registration=True)
        self.config.register_guild(adventures={})     # thread ID -> {setting, started_by, started_at}
        self.config.register_member(guess_wins=0)
        self._stories: Dict[int, List[dict]] = {}       # thread ID -> story so far (text turns)
        self._pending: Dict[int, List[Tuple[discord.Member, str]]] = {}
        self._timers: Dict[int, asyncio.Task] = {}
        self._locks: Dict[int, asyncio.Lock] = {}
        self._guessing: Dict[int, dict] = {}            # channel ID -> running guess-the-game round

    async def cog_unload(self):
        for task in self._timers.values():
            task.cancel()
        for round_ in self._guessing.values():
            round_["task"].cancel()

    async def red_delete_data_for_user(self, *, requester, user_id: int):
        for guild_id, members in (await self.config.all_members()).items():
            if user_id in members:
                await self.config.member_from_ids(guild_id, user_id).clear()

    def _claude(self):
        claude = self.bot.get_cog("ClaudeChat")
        return claude if claude is not None and hasattr(claude, "complete") else None

    async def _ask(self, member: discord.Member, channel, system: str, messages: List[dict], **kwargs
                   ) -> Tuple[Optional[str], Optional[str]]:
        claude = self._claude()
        if claude is None:
            return None, "⚠️ The AI features need the Claude cog loaded."
        return await claude.complete(member, channel, system=system, messages=messages, **kwargs)

    # ==========================================
    #                 CATCH-UP
    # ==========================================

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
            return None, "Nothing to catch up on."
        system = (f"Summarize a Discord conversation for {member.display_name}, who missed it. Use at most 8 short "
                  "bullet points (\"- \"), most important first. Say who said what, and call out plans, times, "
                  f"decisions, and anything asked of or about {member.display_name}. Plain and factual; no intro.")
        summary, error = await self._ask(member, channel, system, [{"role": "user", "content": text}],
                                         fast=True, max_tokens=700, persona=False)
        if summary is None:
            return None, error
        header = (f"📰 **Catch-up for #{channel.name}**: {len(history)} messages since "
                  f"<t:{int(since.timestamp())}:R>")
        return f"{header}\n{summary}"[:1950], None

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
            await ctx.author.send(text or error)
            await ctx.tick()
        except discord.HTTPException:
            await ctx.send("❌ I couldn't DM you. Use `/catchup` instead, which only you can see.", delete_after=20)

    @app_commands.command(name="catchup", description="A summary of this channel since you last spoke (only you see it)")
    @app_commands.guild_only()
    async def slash_catchup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        text, error = await self.build_catchup(interaction.user, interaction.channel)
        await interaction.followup.send(text or error, ephemeral=True)

    # ==========================================
    #                   JUDGE
    # ==========================================

    @commands.command(name="judge", aliases=["verdict"])
    @commands.guild_only()
    @commands.cooldown(1, 60, commands.BucketType.channel)
    async def judge(self, ctx: commands.Context, messages: int = JUDGE_DEFAULT):
        """
        Have ButlerBot settle the argument in this channel.

        It reads the recent messages (20 by default, up to 60) and delivers a ruling, in character.

        **Example:** `[p]judge` or `[p]judge 40`
        """
        count = max(5, min(messages, JUDGE_MAX))
        history = [m async for m in ctx.channel.history(limit=count + 1, before=ctx.message)
                   if not m.author.bot and m.content and not m.content.startswith(ctx.prefix)]
        history.reverse()
        if len({m.author.id for m in history}) < 2:
            return await ctx.send("⚖️ I need at least two people disagreeing before I can rule on anything.")
        system = ("Several people in this Discord channel are arguing, and someone has asked you to judge. Read the "
                  "conversation, then deliver a ruling in your own voice and personality:\n"
                  "1. Sum up each side in one sentence, naming who holds it.\n"
                  "2. Rule on who is right (or more right), with your reasoning. Be fair, decisive and witty.\n"
                  "3. Close with a one-line sentence or remedy for the losing side.\n"
                  "Stay under 170 words. If there's no real disagreement, say so in character. Never pick on "
                  "anyone's identity; judge the arguments.")
        async with ctx.channel.typing():
            ruling, error = await self._ask(ctx.author, ctx.channel, system, [
                {"role": "user", "content": f"{ctx.author.display_name} asks you to judge this:\n\n"
                                            + transcript(history, self.bot.user.id, 12000)}], max_tokens=600)
        await ctx.send(f"⚖️ **The ruling**\n{ruling}"[:2000] if ruling else error,
                       allowed_mentions=discord.AllowedMentions.none())

    # ==========================================
    #               TEXT ADVENTURES
    # ==========================================

    @commands.group(name="adventure", invoke_without_command=True)
    @commands.guild_only()
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def adventure(self, ctx: commands.Context, *, setting: str):
        """
        Start a group text adventure in a new thread, narrated by ButlerBot.

        Everyone in the thread plays by just typing what they do. ButlerBot waits a few seconds to gather everyone's
        moves, then narrates what happens. End it with `[p]adventure stop` inside the thread.

        **Example:** `[p]adventure a haunted space station where the AI has gone quiet`
        """
        if isinstance(ctx.channel, discord.Thread):
            return await ctx.send("Start adventures from a regular channel; I'll make a thread for it.")
        adventures = await self.config.guild(ctx.guild).adventures()
        live = {tid: a for tid, a in adventures.items() if ctx.guild.get_thread(int(tid))}
        if len(live) >= MAX_ADVENTURES:
            return await ctx.send(f"⚠️ {MAX_ADVENTURES} adventures are already running. Finish one with "
                                  f"`{ctx.clean_prefix}adventure stop` in its thread.")
        setting = setting.strip()[:500]
        try:
            thread = await ctx.message.create_thread(name=f"🗺️ {setting[:90]}", auto_archive_duration=1440)
        except discord.HTTPException as e:
            return await ctx.send(f"❌ I couldn't create a thread here: {e.text or e}")
        async with self.config.guild(ctx.guild).adventures() as adventures:
            for stale in [tid for tid in adventures if tid not in live]:
                adventures.pop(stale)   # threads that were deleted or archived
            adventures[str(thread.id)] = {"setting": setting, "started_by": ctx.author.id,
                                          "started_at": int(time.time())}
        self._stories[thread.id] = []
        await thread.send(f"🗺️ **A new adventure begins.** Everyone here can play: just type what you do. "
                          f"I'll gather moves for a few seconds before narrating.\n-# `{ctx.clean_prefix}adventure "
                          "stop` ends it.")
        await self._narrate(thread, ctx.author, [(ctx.author, "(The adventure begins. Set the opening scene and "
                                                              "introduce the situation.)")])

    @adventure.command(name="stop", aliases=["end"])
    async def adventure_stop(self, ctx: commands.Context):
        """End the adventure in this thread with a final scene (whoever started it, or a mod)."""
        info = (await self.config.guild(ctx.guild).adventures()).get(str(ctx.channel.id))
        if info is None:
            return await ctx.send("There's no adventure running in this channel.")
        mod = ctx.channel.permissions_for(ctx.author).manage_threads or await self.bot.is_mod(ctx.author)
        if ctx.author.id != info["started_by"] and not mod:
            return await ctx.send("Only whoever started the adventure, or a mod, can end it.")
        async with self.config.guild(ctx.guild).adventures() as adventures:
            adventures.pop(str(ctx.channel.id), None)
        if (task := self._timers.pop(ctx.channel.id, None)) is not None:
            task.cancel()
        await self._narrate(ctx.channel, ctx.author, [(ctx.author, "(The adventure is ending now. Wrap up the "
                                                                   "story with a final scene.)")], setting=info["setting"])
        self._stories.pop(ctx.channel.id, None)
        await ctx.send("🏁 **The End.** Thanks for playing!")
        try:
            await ctx.channel.edit(archived=True)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message_without_command(self, message: discord.Message):
        if message.guild is None or message.author.bot or not isinstance(message.channel, discord.Thread):
            return
        if not message.content.strip():
            return
        info = (await self.config.guild(message.guild).adventures()).get(str(message.channel.id))
        if info is None or not await self.bot.ignored_channel_or_guild(message):
            return
        thread_id = message.channel.id
        self._pending.setdefault(thread_id, []).append((message.author, message.clean_content.strip()[:500]))
        if (task := self._timers.get(thread_id)) is not None:
            task.cancel()   # wait for everyone to finish typing
        self._timers[thread_id] = asyncio.create_task(self._narrate_later(message.channel, info["setting"]))

    async def _narrate_later(self, thread: discord.Thread, setting: str):
        await asyncio.sleep(ADVENTURE_DEBOUNCE)
        self._timers.pop(thread.id, None)
        moves = self._pending.pop(thread.id, [])
        if moves:
            await self._narrate(thread, moves[0][0], moves, setting=setting)

    async def _seed_story(self, thread: discord.Thread) -> List[dict]:
        """After a restart, rebuild the story from the thread."""
        story: List[dict] = []
        async for m in thread.history(limit=ADVENTURE_HISTORY, oldest_first=False):
            if not m.content:
                continue
            if m.author.id == self.bot.user.id:
                if m.content.startswith(("🗺️ **A new adventure", "🏁")):
                    continue
                story.append({"role": "assistant", "content": m.content})
            elif not m.author.bot and not m.content.startswith("!"):
                story.append({"role": "user", "content": f"{m.author.display_name}: {m.clean_content}"})
        story.reverse()
        merged: List[dict] = []
        for turn in story:   # the API needs alternating roles
            if merged and merged[-1]["role"] == turn["role"]:
                merged[-1]["content"] += "\n" + turn["content"]
            else:
                merged.append(dict(turn))
        while merged and merged[0]["role"] != "user":
            merged.pop(0)
        return merged

    async def _narrate(self, thread: discord.Thread, member: discord.Member,
                       moves: List[Tuple[discord.Member, str]], setting: Optional[str] = None):
        lock = self._locks.setdefault(thread.id, asyncio.Lock())
        async with lock:
            if setting is None:
                info = (await self.config.guild(thread.guild).adventures()).get(str(thread.id), {})
                setting = info.get("setting", "an adventure")
            if thread.id not in self._stories:
                self._stories[thread.id] = await self._seed_story(thread)
            story = self._stories[thread.id]
            turn = "\n".join(f"{player.display_name}: {action}" for player, action in moves)
            if story and story[-1]["role"] == "user":
                story[-1]["content"] += "\n" + turn
            else:
                story.append({"role": "user", "content": turn})
            del story[:max(0, len(story) - ADVENTURE_HISTORY)]
            while story and story[0]["role"] != "user":
                story.pop(0)
            async with thread.typing():
                text, error = await self._ask(member, thread, ADVENTURE_RULES.format(setting=setting), story,
                                              max_tokens=700)
            if text is None:
                story.pop()
                await thread.send(error)
                return
            story.append({"role": "assistant", "content": text})
            for i in range(0, len(text), 1990):
                await thread.send(text[i:i + 1990], allowed_mentions=discord.AllowedMentions.none())

    # ==========================================
    #               TRIVIA WRITER
    # ==========================================

    @commands.command(name="maketrivia", aliases=["trivia-make", "writetrivia"])
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def maketrivia(self, ctx: commands.Context, count: Optional[int] = 20, *, topic: str):
        """
        Have Claude write a trivia list, ready to play with Red's trivia game (mods).

        Use `our games` as the topic for questions about the games in this server's library. The list is saved
        for the `trivia` cog, so you can start it right away.

        **Examples:**
        - `[p]maketrivia our games`
        - `[p]maketrivia 15 1990s video game consoles`
        """
        count = max(TRIVIA_MIN, min(count or 20, TRIVIA_MAX))
        subject = topic.strip()[:200]
        if simplify(subject) in ("ourgames", "servergames", "ourlibrary", "library"):
            gm = self.bot.get_cog("GameManager")
            games = sorted(g["name"] for g in (await gm.config.guild(ctx.guild).games()).values()) if gm else []
            if not games:
                return await ctx.send("❌ The server's game library is empty (or GameManager isn't loaded).")
            subject = "these video games (mix questions across them): " + ", ".join(games[:80])
        system = ("You write trivia questions for a Discord quiz game. Facts must be accurate and well established; "
                  "skip anything you're unsure of. Each question has one clear answer that a player can type in a "
                  "few words. List the main answer first, then common alternate spellings or short forms players "
                  "might type (no more than 5). Vary difficulty, mostly medium. Reply with only a JSON array: "
                  '[{"q": "question?", "a": ["answer", "alternate"]}, …]')
        async with ctx.channel.typing():
            text, error = await self._ask(ctx.author, ctx.channel, system,
                                          [{"role": "user", "content": f"Write {count} questions about {subject}."}],
                                          max_tokens=6000, persona=False)
        if text is None:
            return await ctx.send(error)
        try:
            questions = parse_trivia_json(text)
        except (ValueError, TypeError):
            questions = []
        if len(questions) < 5:
            return await ctx.send("😶 That didn't come out as a usable trivia list. Try again or reword the topic.")
        name = trivia_slug(topic)
        trivia_cog = self.bot.get_cog("Trivia")
        if trivia_cog is not None and name in getattr(getattr(trivia_cog, "trivia", None), "all_commands", {}):
            name += "_list"
        data = {"AUTHOR": f"{ctx.guild.me.display_name} (written by Claude for {ctx.author.display_name})",
                "DESCRIPTION": f"{len(questions)} questions about {topic.strip()[:100]}"}
        data.update({q: a for q, a in questions})
        path = cog_data_path(raw_name="Trivia") / f"{name}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        loaded = trivia_cog is not None
        await ctx.send(f"🧠 Wrote **{len(questions)}** questions about **{topic.strip()[:100]}**.\n"
                       + (f"Start the quiz with `{ctx.clean_prefix}trivia {name}`." if loaded else
                          f"Load Red's trivia cog (`{ctx.clean_prefix}load trivia`), then `{ctx.clean_prefix}trivia {name}`.")
                       + f"\n-# Saved as `{name}`; writing the same topic again replaces it.")

    # ==========================================
    #              GUESS THE GAME
    # ==========================================

    @commands.group(name="guessgame", aliases=["guessthegame"], invoke_without_command=True)
    @commands.guild_only()
    @commands.cooldown(1, 60, commands.BucketType.channel)
    async def guessgame(self, ctx: commands.Context):
        """
        Gemini paints a game from the server's library in an unusual art style. First to type its name wins.

        Hints appear after a minute. `[p]guessgame top` shows the leaderboard.
        """
        if ctx.channel.id in self._guessing:
            return await ctx.send("A round is already running here!")
        gm, gemini = self.bot.get_cog("GameManager"), self.bot.get_cog("GeminiChat")
        if gm is None or gemini is None or not hasattr(gemini, "generate_image"):
            return await ctx.send("❌ This needs the GameManager and Gemini cogs loaded.")
        games = await gm.config.guild(ctx.guild).games()
        users = await gm.config.guild(ctx.guild).users()
        if len(games) < 3:
            return await ctx.send("❌ The server's game library needs at least 3 games first.")
        # Favor games people here actually own.
        weights = {gid: 1 + sum(gid in set(u.get("owned", [])) | set(u.get("installed", [])) for u in users.values())
                   for gid in games}
        gid = random.choices(list(weights), weights=list(weights.values()))[0]
        answer = games[gid]["name"]
        style = random.choice(ART_STYLES)
        self._guessing[ctx.channel.id] = {"answer": answer, "task": None}
        async with ctx.channel.typing():
            scene, error = await self._ask(ctx.author, ctx.channel, (
                "Describe, in one or two sentences, a scene that clearly evokes a specific video game through its "
                "setting, look, creatures, vehicles or objects, so fans could recognize it. Never write the game's "
                "title, its characters' names, the studio, or any trademarked or made-up proper names."),
                [{"role": "user", "content": f"The game: {answer}"}], fast=True, max_tokens=200, persona=False,
                count_toward_limit=False)
            if scene is None or simplify(answer) in simplify(scene):
                self._guessing.pop(ctx.channel.id, None)
                return await ctx.send(error or "😶 I couldn't come up with a picture for that one. Try again.")
            prompt = f"{scene.strip()} Rendered as {style}. No text, letters, logos or titles anywhere in the image."
            posted = await gemini.generate_image(prompt, f"GUESS_{ctx.channel.id}", ctx.message, channel=ctx.channel,
                                                 user=ctx.author, new=True)
        if posted is None:
            self._guessing.pop(ctx.channel.id, None)
            return
        await ctx.send(f"🎨 **Guess the game!** First to type its name wins. You have {GUESS_SECONDS // 60} minutes.")
        task = asyncio.create_task(self._run_round(ctx.channel, answer))
        self._guessing[ctx.channel.id]["task"] = task

    async def _run_round(self, channel, answer: str):
        start = time.monotonic()
        hints = list(GUESS_HINTS)
        try:
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= GUESS_SECONDS:
                    await channel.send(f"⌛ Time's up! It was **{answer}**.")
                    return
                next_stop = min([h for h in hints if h > elapsed] + [GUESS_SECONDS])
                try:
                    message = await self.bot.wait_for(
                        "message", timeout=next_stop - elapsed,
                        check=lambda m: m.channel.id == channel.id and not m.author.bot
                        and is_correct_guess(m.content, answer))
                except asyncio.TimeoutError:
                    if hints and next_stop == hints[0]:
                        level = len(GUESS_HINTS) - len(hints) + 1
                        hints.pop(0)
                        await channel.send(f"💡 Hint: `{hint_for(answer, level)}`")
                    continue
                wins = await self.config.member(message.author).guess_wins() + 1
                await self.config.member(message.author).guess_wins.set(wins)
                await message.reply(f"🏆 {message.author.mention} got it: **{answer}**! ({wins} win"
                                    f"{'s' if wins != 1 else ''})", mention_author=False)
                return
        finally:
            self._guessing.pop(channel.id, None)

    @guessgame.command(name="top", aliases=["leaderboard"])
    async def guessgame_top(self, ctx: commands.Context):
        """The guess-the-game leaderboard."""
        members = await self.config.all_members(ctx.guild)
        ranked = sorted(((d["guess_wins"], uid) for uid, d in members.items()
                         if d.get("guess_wins") and ctx.guild.get_member(uid)), reverse=True)[:15]
        if not ranked:
            return await ctx.send(f"No winners yet. Start a round with `{ctx.clean_prefix}guessgame`.")
        medals = ["🥇", "🥈", "🥉"]
        lines = [f"{medals[i] if i < 3 else f'`{i + 1}.`'} <@{uid}>: **{wins}**" for i, (wins, uid) in enumerate(ranked)]
        await ctx.send(embed=discord.Embed(title="🎨 Guess the game: top players", description="\n".join(lines),
                                           color=discord.Color.gold()))

    @guessgame.command(name="stop")
    @checks.mod_or_permissions(manage_messages=True)
    async def guessgame_stop(self, ctx: commands.Context):
        """End the running round here and reveal the answer (mods)."""
        round_ = self._guessing.pop(ctx.channel.id, None)
        if round_ is None:
            return await ctx.send("No round is running here.")
        if round_["task"] is not None:
            round_["task"].cancel()
        await ctx.send(f"🛑 Round stopped. It was **{round_['answer']}**.")
