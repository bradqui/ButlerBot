"""Parlor: critique, roast, the emoji game, twenty questions and the leaderboard; plus ClaudeChat.image_block."""
import asyncio
import random
from types import SimpleNamespace

from harness import card_text, FakeGuild, FakeMessage, TestBot, dcommands, discord, load

parlor_mod = load("parlor", "parlor")
gm_mod = load("gamemanager", "gamemanager")
claude_mod = load("claude", "claude")
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


class FakeClaude(dcommands.Cog, name="ClaudeChat"):
    REFUSAL = claude_mod.ClaudeChat.REFUSAL

    def __init__(self):
        self.calls, self.replies, self.images = [], [], []

    async def complete(self, member, channel, *, system, messages, **kw):
        self.calls.append({"member": member, "system": system, "messages": messages, **kw})
        reply = self.replies.pop(0) if self.replies else "Reply."
        return (None, reply) if reply.startswith(("ERR", "❌", "⏳")) else (reply, None)

    async def image_block(self, attachment):
        self.images.append(attachment.filename)
        if attachment.filename.endswith(".bmp"):
            return None, f"`{attachment.filename}` isn't an image I can read"
        return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}, None


class FakeThread(discord.Thread):
    def __init__(self, guild, tid, name):
        self.guild, self.id, self.name = guild, tid, name
        self.parent_id = guild.channel.id
        self.sent, self.edits = [], []

    async def send(self, content=None, **kw):
        msg = FakeMessage(self, content, author=self.guild.me, **kw)
        self.sent.append(msg)
        return msg

    def typing(self):
        return self.guild.channel.typing()

    async def edit(self, **kw):
        self.edits.append(kw)


def attachment(name, ctype="image/png"):
    return SimpleNamespace(filename=name, content_type=ctype)


async def main():
    # ---- pure helpers ----
    ok = parlor_mod.clean_emoji
    check(ok("🧟 🔫🚁🏝️") == "🧟 🔫🚁🏝️", ok("🧟 🔫🚁🏝️"))
    check(ok("Here you go:\n🧟🔫") is None and ok("🅰️🧟🔫") is None and ok("🇭🇱🔫") is None and ok("1️⃣🔫🧟") is None
          and ok(":zombie: 🔫") is None and ok("🔫") is None and ok("") is None and ok("🆕🧟🔫") is None,
          "emoji puzzles that spell things out are rejected")
    check(ok("`🚀🌌`\n(space!)") == "🚀🌌", "code ticks stripped, first line kept")
    check(parlor_mod.guess_in("Is it Barony?") == "Barony" and parlor_mod.guess_in("it's deep rock galactic!")
          == "deep rock galactic" and parlor_mod.guess_in("Does it have zombies?") == "Does it have zombies",
          "guesses phrased as questions")
    check(parlor_mod.clean_title('"Hades".\nGreat game') == "Hades" and parlor_mod.clean_title("**Portal 2**") == "Portal 2",
          "titles cleaned")
    check(parlor_mod.strip_html("A <b>rogue</b>&amp;like") == "A rogue &like", parlor_mod.strip_html("A <b>rogue</b>&amp;like"))

    # ---- setup ----
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex = guild.add(2, "Alex")
    chris = guild.add(3, "Chris")
    mira = guild.add(4, "Mira")
    channel = guild.channel
    threads = {}
    guild.get_thread = lambda tid: threads.get(tid)
    guild.get_member_named = lambda name: next((m for m in guild.members if m.name == name), None)

    async def convert_member(self, ctx, argument):   # the real converter needs a gateway connection
        digits = "".join(c for c in argument if c.isdigit())
        found = ctx.guild.get_member_named(argument) or (ctx.guild.get_member(int(digits)) if digits else None)
        if found is None:
            raise dcommands.MemberNotFound(argument)
        return found
    dcommands.MemberConverter.convert = convert_member
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    errors = []

    async def on_command_error(ctx, error):
        errors.append(f"{ctx.message.content}: {error!r}")
    bot.on_command_error = on_command_error
    claude = FakeClaude()
    await bot.add_cog(claude)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    # ButlerFun's saved data is copied over once, on the first load
    from harness import FakeConfig
    old = FakeConfig()
    old._data["member"][(guild.id, alex.id)] = {"guess_wins": 4, "adventure_bio": "a dwarf with a bad knee"}
    old._data["member"][(guild.id, chris.id)] = {"guess_wins": 0}
    old._data["guild"][guild.id] = {"adventures": {"777": {"setting": "a cave", "started_by": 2, "started_at": 0,
                                                           "players": [2]}}}
    parlor_mod.Parlor._butlerfun_config = lambda self: old
    pc = parlor_mod.Parlor(bot)
    await bot.add_cog(pc)
    check(await pc.config.member(alex).wins() == {"guess": 4}
          and await pc.config.member(alex).adventure_bio() == "a dwarf with a bad knee"
          and await pc.config.member(chris).wins() == {}
          and (await pc.config.guild(guild).adventures())["777"]["setting"] == "a cave"
          and await pc.config.migrated_butlerfun(), "ButlerFun's wins, bios and adventures copied over")
    await pc._migrate_butlerfun()
    check(await pc.config.member(alex).wins() == {"guess": 4}, "copied only once")
    await pc.config.member(alex).wins.set({})
    await pc.config.guild(guild).adventures.set({})
    facts_for = []

    async def steam_facts(appid):
        facts_for.append(appid)
        return "Genres: Action, RPG" if appid else ""
    pc._steam_facts = steam_facts

    async def run(author, content, ch=None, **attrs):
        msg = FakeMessage(ch or channel, content, author=author)
        for k, v in attrs.items():
            setattr(msg, k, v)
        ctx = await bot.get_context(msg)
        await bot.invoke(ctx)
        await asyncio.sleep(0.05)
        return ctx

    def last(ch=None):
        return (ch or channel).sent[-1]

    # ---- the parlor card ----
    await run(alex, "!parlor")
    text = card_text(last())
    check("🃏 The parlor" in text and "`!guessgame`" in text and "`!adventure <setting>`" in text and "`!emojigame`" in text and "`!twentyq`" in text and "`!critique`" in text
          and "`!roast`" in text and "`!parlor top` shows the leaderboard" in text, text)

    # ---- critique ----
    await run(alex, "!critique")
    check(last().content.startswith("❓ I need a picture to critique.") and "reply to a message" in last().content,
          last().content)
    claude.replies.append("A bold hangar. 7/10.")
    pc.critique.reset_cooldown(await bot.get_context(FakeMessage(channel, "!critique", author=alex)))
    await run(alex, "!critique my new hangar", attachments=[attachment("hangar.png")])
    call = claude.calls[-1]
    blocks = call["messages"][0]["content"]
    check(blocks[0]["type"] == "image" and "Alex asks for your critique. They say it's: my new hangar" == blocks[1]["text"]
          and call["system"] == parlor_mod.CRITIQUE_SYSTEM and call.get("persona", True) and not call.get("fast"),
          blocks[1])
    check(last().content == "🖼️ **The critique**\nA bold hangar. 7/10." and last().kw.get("mention_author") is False,
          last().content)
    # as a reply to someone else's screenshot
    shot = FakeMessage(channel, "look at my base", author=chris)
    shot.attachments = [attachment("base.jpg", "image/jpeg")]
    claude.replies.append("Rustic. 6/10.")
    pc.critique.reset_cooldown(await bot.get_context(FakeMessage(channel, "!critique", author=alex)))
    await run(alex, "!critique", reference=SimpleNamespace(resolved=shot, message_id=shot.id))
    check("of this picture Chris posted." in claude.calls[-1]["messages"][0]["content"][1]["text"]
          and claude.images[-1] == "base.jpg" and last().kw.get("reference") is shot, claude.calls[-1]["messages"][0])
    # a file that isn't an image it can read
    pc.critique.reset_cooldown(await bot.get_context(FakeMessage(channel, "!critique", author=alex)))
    n = len(claude.calls)
    await run(alex, "!critique", attachments=[attachment("old.bmp", "image/bmp")])
    check(last().content.startswith("❌ I can't look at that picture:") and len(claude.calls) == n, last().content)
    # a text file is ignored as a picture
    pc.critique.reset_cooldown(await bot.get_context(FakeMessage(channel, "!critique", author=alex)))
    await run(alex, "!critique", attachments=[attachment("notes.txt", "text/plain")])
    check(last().content.startswith("❓ I need a picture"), "non-images don't count")

    # ---- the game library ----
    games = {"g1": {"name": "Barony", "steam_appid": 371970}, "g2": {"name": "Deep Rock Galactic", "steam_appid": 548430},
             "g3": {"name": "Helldivers 2"}, "g4": {"name": "Rocket League"}}
    await gm.config.guild(guild).games.set(games)
    await gm.config.guild(guild).users.set({
        "2": {"owned": ["g1", "g2", "g4"], "installed": ["g1"], "ranks": {"g1": 1, "g4": 2}},
        "3": {"owned": ["g2", "g3"], "installed": ["g2", "g3"], "ranks": {}},
        "4": {"owned": ["g2", "g3"], "installed": ["g3"], "ranks": {}},
    })
    await gm.config.guild(guild).wishlist.set({"1": {"appid": 1, "name": "Hades II", "users": ["2"]}})

    # ---- roast ----
    await run(brad, "!roast")
    check(last().content.startswith("❓ You have no game library to roast yet.") and "`!games newprofile`" in last().content,
          last().content)
    pc.roast.reset_cooldown(await bot.get_context(FakeMessage(channel, "!roast", author=brad)))
    await run(brad, "!roast Alex")
    check(last().content.startswith("🔒 Alex hasn't opted in to roasts.") and "`!roast optin`" in last().content,
          last().content)
    await run(alex, "!roast optin")
    check(last().content.startswith("✅ You're open to roasts") and await pc.config.member(alex).roastable(), "opted in")
    claude.replies.append("Alex owns Rocket League and still can't drive.")
    pc.roast.reset_cooldown(await bot.get_context(FakeMessage(channel, "!roast", author=brad)))
    await run(brad, "!roast Alex")
    notes = claude.calls[-1]["messages"][0]["content"]
    if not isinstance(notes, str):
        print("ERRORS:", errors, [m.content for m in channel.sent[-4:]])
    check(notes.startswith("Brad asks you to roast Alex.") and "Owns (3): Barony, Deep Rock Galactic, Rocket League" in notes
          and "Installed right now (1): Barony" in notes and "Owns but hasn't installed (2): Deep Rock Galactic, Rocket League"
          in notes and "Ranked favorites: 1. Barony, 2. Rocket League" in notes and "Wishlist (1): Hades II" in notes
          and "Popular here that they don't own: Helldivers 2" in notes, notes)
    check(last().content == "🔥 **Roasting Alex**\nAlex owns Rocket League and still can't drive."
          and claude.calls[-1]["system"] == parlor_mod.ROAST_SYSTEM, last().content)
    claude.replies.append("Chris installs everything.")
    pc.roast.reset_cooldown(await bot.get_context(FakeMessage(channel, "!roast", author=chris)))
    await run(chris, "!roast me")
    check("roast themselves" in claude.calls[-1]["messages"][0]["content"], "self-roast")
    pc.roast.reset_cooldown(await bot.get_context(FakeMessage(channel, "!roast", author=chris)))
    await run(chris, "!roast Nobody")
    check(last().content.startswith("❓ I can't find a member called Nobody."), last().content)
    await run(alex, "!roast optout")
    check(not await pc.config.member(alex).roastable(), "opted out")
    guild.members.append(guild.me)
    guild.me.bot = True
    pc.roast.reset_cooldown(await bot.get_context(FakeMessage(channel, "!roast", author=brad)))
    await run(brad, "!roast Quillbot")
    check(last().content.startswith("🔒 I don't roast fellow staff."), last().content)
    guild.members.remove(guild.me)

    # ---- emoji game ----
    parlor_mod.EMOJI_SECONDS, parlor_mod.EMOJI_HINTS = 1.0, (0.3, 0.6)
    real_wait_for = bot.wait_for

    async def silent_wait_for(event, timeout=None, check=None):
        await asyncio.sleep(timeout)
        raise asyncio.TimeoutError
    bot.wait_for = silent_wait_for
    random.seed(5)
    claude.replies[:] = ["Here: 🅱️arony", "🛡️⚔️🏰💀"]   # the first try spells something out, so it retries
    await run(alex, "!emojigame")
    answer = pc._emoji_rounds[channel.id]["answer"]
    check(answer in [g["name"] for g in games.values()], answer)
    check(last().content.startswith("🃏 **Guess the game!**\n# 🛡️⚔️🏰💀\n-# First to type its name wins.")
          and claude.calls[-1]["fast"] and claude.calls[-1]["count_toward_limit"] is False
          and "(Your last try used letters" in claude.calls[-1]["messages"][0]["content"], last().content)
    pc.emojigame.reset_cooldown(await bot.get_context(FakeMessage(channel, "!emojigame", author=chris)))
    await run(chris, "!emojigame")
    check(last().content.startswith("⏳ A round is already running here."), "one round per channel")
    await asyncio.sleep(1.3)
    texts = [m.content for m in channel.sent[-4:]]
    check(any(t.startswith("💡 Hint") for t in texts) and texts[-1] == f"⌛ Time's up! It was **{answer}**.", texts)
    check(channel.id not in pc._emoji_rounds, "round cleaned up")
    check(answer in pc._recent[guild.id], "the answer is remembered so it doesn't repeat right away")

    async def win_wait_for(event, timeout=None, check=None):
        guess = FakeMessage(channel, f"is it {pc._emoji_rounds[channel.id]['answer'].lower()}?", author=chris)

        async def reply(content, **kw):
            return await channel.send(content, **kw)
        guess.reply = reply
        assert check(guess)
        return guess
    bot.wait_for = win_wait_for
    claude.replies[:] = ["Hades", "🔥💀🗡️"]
    pc.emojigame.reset_cooldown(await bot.get_context(FakeMessage(channel, "!emojigame", author=alex)))
    await run(alex, "!emojigame any")
    await asyncio.sleep(0.1)
    check(claude.calls[-2]["system"] == parlor_mod.PICK_SYSTEM and "Don't pick any of these:" in
          claude.calls[-2]["messages"][0]["content"], claude.calls[-2]["messages"][0]["content"])
    check(last().content == "🏆 <@3> got it: **Hades**! (1 emoji game won)" and not last().kw["allowed_mentions"].users,
          last().content)
    check((await pc.config.member(chris).wins()) == {"emoji": 1}, "win counted")
    pc.emojigame.reset_cooldown(await bot.get_context(FakeMessage(channel, "!emojigame", author=alex)))
    await run(alex, "!emojigame everything")
    check(last().content.startswith("❓ I don't know `everything`."), last().content)
    bot.wait_for = real_wait_for

    # ---- twenty questions ----
    async def create_thread(self, name, auto_archive_duration=None):
        t = FakeThread(guild, 900 + len(threads), name)
        threads[t.id] = t
        return t
    FakeMessage.create_thread = create_thread

    async def say(author, text, thread, asked=True, reply_to=None):
        """A message in a round's thread: addressed to the bot (an @mention, or a reply) unless asked=False."""
        msg = FakeMessage(thread, f"<@{guild.me.id}> {text}" if asked and reply_to is None else text, author=author)
        if asked and reply_to is None:
            msg.mentions = [guild.me]
            msg.clean_content = f"@Quillbot {text}"
        if reply_to is not None:
            msg.reference = SimpleNamespace(resolved=reply_to, message_id=reply_to.id)

        async def reply(content, **kw):
            return await thread.send(content, **kw)
        msg.reply = reply
        await pc.on_message_without_command(msg)
        return thread.sent[-1] if thread.sent else None

    pc._recent.clear()
    random.seed(1)
    await run(alex, "!twentyq")
    thread = threads[900]
    round_ = pc._twentyq[thread.id]
    secret = round_["answer"]
    check(thread.name == "🃏 Twenty questions" and "a game from this server's library" in thread.sent[0].content
          and "`!twentyq stop` gives up" in thread.sent[0].content, thread.sent[0].content)
    appid = next(g.get("steam_appid") for g in games.values() if g["name"] == secret)
    check(facts_for[-1] == appid and round_["facts"] == ("Genres: Action, RPG" if appid else ""), "Steam facts fetched")
    claude.replies.append("Yes, and loudly so.")
    reply = await say(chris, "Is it multiplayer?", thread)
    call = claude.calls[-1]
    check(reply.content == "**1.** Yes, and loudly so." and f'"{secret}"' in call["system"]
          and call["messages"][0]["content"] == "New question from Chris: Is it multiplayer?" and call["fast"]
          and call["count_toward_limit"] is False, reply.content)
    guild.self_role = SimpleNamespace(id=4321)   # the bot's own role, picked from Discord's @ menu
    claude.replies.append("No.")
    by_role = FakeMessage(thread, "<@&4321> Is it a racing game?", author=chris)

    async def role_reply(content, **kw):
        return await thread.send(content, **kw)
    by_role.reply = role_reply
    await pc.on_message_without_command(by_role)
    check(claude.calls[-1]["messages"][0]["content"].endswith("Chris: Is it a racing game?")
          and thread.sent[-1].content == "**2.** No.", "a question addressed to the bot's role counts")
    del guild.self_role
    round_["qa"].pop()   # keep the numbering the rest of this test expects
    n = len(claude.calls)
    await say(chris, "this is fun", thread, asked=False)
    await say(chris, "did anyone check if it's on Steam?", thread, asked=False)
    check(len(claude.calls) == n, "chatter without a question mark is ignored")
    claude.replies.append(f"No, {secret} has no dragons.")
    reply = await say(mira, "Are there dragons?", thread)
    check(reply.content == "**2.** No." and "1. Is it multiplayer?\n   Yes, and loudly so." in claude.calls[-1]["messages"][0]["content"],
          f"an answer that names the game is cut to its verdict: {reply.content}")
    await say(mira, "!twentyq hint?", thread, asked=False)
    check(len(claude.calls) == n + 1, "text starting with the prefix isn't a question")
    claude.replies.append("Yes, in a way.")
    reply = await say(mira, "does it have co-op", thread, reply_to=thread.sent[-1])
    check(reply.content == "**3.** Yes, in a way." and claude.calls[-1]["messages"][0]["content"].endswith(
          "New question from Mira: does it have co-op"), "a reply to an answer is a question, no ? needed")
    claude.replies.append("No.")
    msg = FakeMessage(thread, "!butler is it a sports game?", author=chris)

    async def butler_reply(content, **kw):
        return await thread.send(content, **kw)
    msg.reply = butler_reply
    took = await pc.game_takes_message(msg, "is it a sports game?", command=True)
    check(took and thread.sent[-1].content == "**4.** No.", "!butler in the thread asks the question")
    check(await pc.game_takes_message(FakeMessage(thread, "hi", author=chris), "hi", command=False)
          and not await pc.game_takes_message(FakeMessage(channel, "hi", author=chris), "hi", command=False),
          "the AI chat steps aside in the round's thread only")
    await say(mira, f"is it {secret.lower()}?", thread, asked=False)
    check(f"got it after 4 questions: **{secret}**! (1 round won)" in thread.sent[-2].content
          and thread.sent[-1].content == "🏁 Thanks for playing!" and thread.edits == [{"archived": True}]
          and thread.id not in pc._twentyq, [m.content for m in thread.sent[-2:]])
    check((await pc.config.member(mira).wins()) == {"twentyq": 1}, "twenty questions win counted")

    # CORRECT from Claude (a title variant), the 20-question limit, and the timeout
    pc.twentyq.reset_cooldown(await bot.get_context(FakeMessage(channel, "!twentyq", author=alex)))
    claude.replies.append("Portal 2")
    await run(alex, "!twentyq any")
    thread = threads[901]
    check("a well-known video game" in thread.sent[0].content and pc._twentyq[thread.id]["answer"] == "Portal 2",
          thread.sent[0].content)
    claude.replies.append("CORRECT")
    await say(chris, "Is it the second Portal game?", thread)
    check("got it after 0 questions: **Portal 2**" in thread.sent[-2].content, thread.sent[-2].content)

    pc.twentyq.reset_cooldown(await bot.get_context(FakeMessage(channel, "!twentyq", author=alex)))
    claude.replies.append("Tetris")
    await run(alex, "!twentyq any")
    thread = threads[902]
    round_ = pc._twentyq[thread.id]
    round_["qa"] = [(f"q{i}?", "No.") for i in range(19)]
    claude.replies.append("Yes.")
    parlor_mod.TWENTYQ_FINAL = 0.3
    await say(chris, "Is it a puzzle game?", thread)
    check(thread.sent[-2].content == "**20.** Yes." and thread.sent[-1].content.startswith("That was question 20!")
          and round_["final"], [m.content for m in thread.sent[-2:]])
    n = len(claude.calls)
    await say(chris, "Is it Columns?", thread)
    check(len(claude.calls) == n, "no more questions after 20")
    await asyncio.sleep(0.5)
    check(thread.sent[-1].content == "⌛ Nobody got it. It was **Tetris**." and thread.id not in pc._twentyq,
          thread.sent[-1].content)

    # giving up, outside the thread, and the per-server cap
    pc.twentyq.reset_cooldown(await bot.get_context(FakeMessage(channel, "!twentyq", author=alex)))
    claude.replies.append("Doom")
    await run(alex, "!twentyq any")
    thread = threads[903]
    await run(chris, "!twentyq stop")
    check(last().content.startswith("❓ There's no twenty questions round in this channel."), last().content)
    await run(chris, "!twentyq stop", ch=thread)
    check(thread.sent[-1].content == "🏳️ Chris gave up. It was **Doom**.", thread.sent[-1].content)
    await run(alex, "!twentyq", ch=thread)
    check("Start twenty questions from a regular channel" in thread.sent[-1].content, thread.sent[-1].content)
    parlor_mod.MAX_TWENTYQ = 1
    pc.twentyq.reset_cooldown(await bot.get_context(FakeMessage(channel, "!twentyq", author=alex)))
    claude.replies.append("Myst")
    await run(alex, "!twentyq any")
    open_thread = threads[904]
    pc.twentyq.reset_cooldown(await bot.get_context(FakeMessage(channel, "!twentyq", author=alex)))
    await run(alex, "!twentyq any")
    check(last().content.startswith("⏳ Too many rounds are running (the limit is 1)."), last().content)

    # ---- game threads: the emoji game in a thread under its puzzle ----
    from harness import Perms
    Perms.create_public_threads = Perms.send_messages_in_threads = True

    async def thread_win(event, timeout=None, check=None):
        round_thread = pc._emoji_rounds[channel.id]["where"]
        guess = FakeMessage(round_thread, pc._emoji_rounds[channel.id]["answer"], author=mira)

        async def reply(content, **kw):
            return await round_thread.send(content, **kw)
        guess.reply = reply
        assert check(guess)
        return guess
    bot.wait_for = thread_win
    claude.replies[:] = ["Myst", "🏝️📕🔮"]
    pc.emojigame.reset_cooldown(await bot.get_context(FakeMessage(channel, "!emojigame", author=alex)))
    before = len(threads)
    await run(alex, "!emojigame any")
    await asyncio.sleep(0.1)
    puzzle = next(m for m in reversed(channel.sent) if m.content.startswith("🃏 **Guess the game!**"))
    gthread = threads[max(threads)]
    check(len(threads) == before + 1 and gthread.name == "🃏 Guess the game"
          and "\n-# Guess in the thread below. You have " in puzzle.content, "the puzzle starts a thread")
    check(gthread.sent[-1].content.startswith("🏆 <@4> got it: **Myst**!") and puzzle.content.endswith(
          "\n🏆 Mira got it: **Myst**.") and gthread.edits[-1] == {"archived": True} and channel.id not in pc._emoji_rounds,
          [puzzle.content, [m.content for m in gthread.sent]])
    # an admin turns threads off here: the round runs in the channel
    await run(brad, "!parlor threads off")
    check(last().content.startswith(f"✅ Games in {channel.mention} run right in the channel.")
          and not await pc.config.channel(channel).threads(), last().content)
    claude.replies[:] = ["Riven", "🏝️🌀🔮"]
    pc.emojigame.reset_cooldown(await bot.get_context(FakeMessage(channel, "!emojigame", author=alex)))
    before = len(threads)
    bot.wait_for = silent_wait_for
    parlor_mod.EMOJI_SECONDS = 0.2
    await run(alex, "!emojigame any")
    await asyncio.sleep(0.4)
    check(len(threads) == before and channel.sent[-1].content == "⌛ Time's up! It was **Riven**.", "no thread when off")
    await run(brad, "!parlor threads on")
    check(last().content.startswith(f"✅ Games in {channel.mention} get their own threads."), last().content)
    await run(brad, "!parlor threads")
    check(last().content.startswith(f"Games in {channel.mention} get their own threads."), "shows the setting")
    del Perms.create_public_threads, Perms.send_messages_in_threads
    await run(brad, "!parlor threads")
    check("I can't make threads here" in last().content, "says when it can't make threads")
    bot.wait_for = real_wait_for

    # ---- leaderboard ----
    await run(alex, "!parlor top")
    top = card_text(last())
    check("**1. Chris** 🥇\n-# 2 wins · 1 emoji game · 1 twenty questions" in top
          and "**2. Mira** 🥈\n-# 2 wins · 1 emoji game · 1 twenty questions" in top and "<@" not in top, top)

    # ---- unloading ends running rounds with the answer ----
    await bot.remove_cog("Parlor")
    check(open_thread.sent[-1].content == "⌛ This round ended because I'm restarting. It was **Myst**.",
          open_thread.sent[-1].content)

    # ---- ClaudeChat.image_block refuses files that aren't images ----
    real = claude_mod.ClaudeChat.__new__(claude_mod.ClaudeChat)
    block, why = await real.image_block(attachment("notes.txt", "text/plain"))
    check(block is None and "isn't an image" in why, why)

    check(not errors, f"command errors: {errors}")
    passed = sum(1 for ok_, _ in results if ok_)
    print(f"{passed}/{len(results)} checks passed")


asyncio.run(main())
