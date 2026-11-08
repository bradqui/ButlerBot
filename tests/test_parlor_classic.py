"""Parlor's games from the retired ButlerFun cog (judge, adventures, trivia writer, guess the game);
plus ClaudeChat.complete and catch-up, which moved to the Claude cog."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from harness import DATA_DIR, card_buttons, card_text, FakeChannel, FakeGuild, FakeInteraction, FakeMessage, TestBot, dcommands, discord, enable_dms, load
enable_dms()

import yaml  # noqa: E402  (after harness puts pylibs on the path)

bf_mod = load("parlor", "parlor")
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
        self.calls, self.replies = [], []
        self.limited = {}   # member id -> daily limit they've reached

    async def complete(self, member, channel, *, system, messages, **kw):
        self.calls.append({"member": member, "system": system, "messages": [dict(m) for m in messages], **kw})
        reply = self.replies.pop(0) if self.replies else "Narration."
        if reply == "REFUSED":
            return None, self.REFUSAL
        return (reply, None) if not reply.startswith(("ERR", "⏳")) else (None, reply)

    async def limit_reached(self, member):
        return self.limited.get(member.id)


class FakeGemini(dcommands.Cog, name="GeminiChat"):
    def __init__(self):
        self.prompts = []

    async def generate_image(self, prompt, key, reply_target, *, channel, user, new=True, quiet=False):
        self.prompts.append(prompt)
        self.quiet = quiet
        return await channel.send(f"🎨 {prompt[:80]}")


class FakeThread(discord.Thread):
    def __init__(self, guild, tid, name):
        self.guild, self.id, self.name = guild, tid, name
        self.parent_id = guild.channel.id
        self.sent, self.history_messages, self.edits = [], [], []

    async def send(self, content=None, **kw):
        msg = FakeMessage(self, content, author=self.guild.me, **kw)
        self.sent.append(msg)
        return msg

    def typing(self):
        return self.guild.channel.typing()

    async def edit(self, **kw):
        self.edits.append(kw)

    def history(self, limit=None, oldest_first=False, **kw):
        async def gen():
            for m in (self.history_messages if oldest_first else list(reversed(self.history_messages)))[:limit]:
                yield m
        return gen()

    def permissions_for(self, member):
        return guild_perms(member)


def guild_perms(member):
    from harness import Perms
    p = Perms(getattr(member.guild_permissions, "administrator", False))
    p.manage_threads = p.administrator
    return p


def msg_at(channel, author, text, minutes_ago):
    m = FakeMessage(channel, text, author=author)
    m.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    m.clean_content = text
    return m


async def main():
    # ---- pure helpers ----
    check(bf_mod.is_correct_guess("rocket league", "Rocket League") and bf_mod.is_correct_guess("Rocket Leage!", "Rocket League")
          and not bf_mod.is_correct_guess("rocket", "Rocket League") and not bf_mod.is_correct_guess("Halo", "Halo 2")
          and bf_mod.is_correct_guess("halo 2", "Halo 2"), "guess matching")
    check(bf_mod.hint_for("Rocket League", 1) == "R····· L·····  (2 words)", bf_mod.hint_for("Rocket League", 1))
    check(bf_mod.hint_for("Deadlock", 2) == "D·a·l·c·", bf_mod.hint_for("Deadlock", 2))
    parsed = bf_mod.parse_trivia_json('```json\n[{"q": "Capital of France?", "a": ["Paris"]}, {"q": "", "a": []}, '
                                      '{"question": "2+2?", "answers": [4, "four"]}]\n```')
    check(parsed == [("Capital of France?", ["Paris"]), ("2+2?", ["4", "four"])], parsed)
    check(bf_mod.trivia_slug("Our Games!") == "bb_our_games", bf_mod.trivia_slug("Our Games!"))

    # ---- setup ----
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex = guild.add(2, "Alex")
    chris = guild.add(3, "Chris")
    channel = guild.channel
    channel.name = "general"
    threads = {}
    guild.get_thread = lambda tid: threads.get(tid)
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    claude = FakeClaude()
    await bot.add_cog(claude)
    gemini = FakeGemini()
    await bot.add_cog(gemini)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    bf = bf_mod.Parlor(bot)
    await bot.add_cog(bf)

    history = []

    def chan_history(limit=None, before=None, **kw):
        async def gen():
            items = list(reversed(history))
            if before is not None:
                items = [m for m in items if m.id != before.id]
            for m in items[:limit]:
                yield m
        return gen()
    channel.history = chan_history

    # ---- judge ----
    async def run(author, content, ch=None):
        ch = ch or channel
        ctx = await bot.get_context(FakeMessage(ch, content, author=author))
        await bot.invoke(ctx)
        await asyncio.sleep(0.05)
        return ctx

    history.clear()
    history += [msg_at(channel, alex, "pineapple belongs on pizza", 5), msg_at(channel, chris, "absolutely not", 4),
                msg_at(channel, alex, "it's sweet and salty", 3)]
    claude.replies.append("Alex is correct, regrettably.")
    await run(brad, "!judge")
    check(channel.sent[-1].content.startswith("⚖️ **The ruling**") and claude.calls[-1].get("persona", True)
          and "Alex: pineapple" in claude.calls[-1]["messages"][0]["content"], channel.sent[-1].content)
    long_ruling = " ".join(f"word{i}" for i in range(700))   # ~5,500 characters
    claude.replies[:] = [long_ruling]
    bf.judge.reset_cooldown(await bot.get_context(FakeMessage(channel, "!judge", author=brad)))
    before = len(channel.sent)
    await run(brad, "!judge")
    pages = [m.content for m in channel.sent[before:]]
    check(len(pages) >= 3 and all(len(pg) <= 2000 for pg in pages)
          and " ".join(pg for pg in pages).replace("⚖️ **The ruling**\n", "").split() == long_ruling.split(),
          f"long ruling split into {len(pages)} whole-word pages: {[pg[:60] for pg in pages]}")
    history[:] = [msg_at(channel, alex, "hello", 2)]
    bf.judge.reset_cooldown(await bot.get_context(FakeMessage(channel, "!judge", author=brad)))
    await run(brad, "!judge")
    check("at least two people" in channel.sent[-1].content, "needs two people")

    # ---- adventure bios ----
    async def bio(author, text=""):
        bf.adventure_bio.reset_cooldown(await bot.get_context(FakeMessage(channel, "!adventure bio", author=author)))
        await run(author, f"!adventure bio {text}".strip())
        return channel.sent[-1].content

    claude.replies.clear()
    check("haven't set an adventure bio" in await bio(alex), "no bio yet")
    claude.replies.append("OK")
    reply = await bio(alex, "a  red-haired dwarf\nengineer with a bad knee")
    check("Saved" in reply and await bf.config.member(alex).adventure_bio() == "a red-haired dwarf engineer with a bad knee",
          reply)
    check(claude.calls[-1]["system"] == bf_mod.BIO_CHECK and claude.calls[-1]["fast"]
          and claude.calls[-1]["count_toward_limit"] is False, "bio checked by Haiku, not counted")
    claude.replies.append("NO: Characters can't be invincible.")
    reply = await bio(chris, "an invincible god who always wins")
    check("can't be used: Characters can't be invincible." in reply and not await bf.config.member(chris).adventure_bio(),
          reply)
    calls = len(claude.calls)
    check("bios can be up to 200" in await bio(chris, "x" * 201) and len(claude.calls) == calls, "length cap, no call")
    check("Leave mentions out" in await bio(chris, "friend of <@1>"), "no mentions")
    claude.replies.append("REFUSED")
    check("can't be used" in await bio(chris, "something awful"), "refused check means rejected")
    claude.replies.append("ERR⚠️ No Anthropic API key is set.")
    check("couldn't check your bio" in await bio(chris, "a quiet monk"), "check failure doesn't save")
    claude.replies.append("OK")
    await bio(chris, "a nervous ship's cook who talks to pans")
    check("red-haired dwarf" in await bio(chris, "<@2>"), "show someone else's")
    check("Only mods" in await bio(chris, "clear <@2>") and await bf.config.member(alex).adventure_bio(), "non-mod can't clear")
    check("Cleared Alex" in await bio(brad, "clear <@2>") and not await bf.config.member(alex).adventure_bio(),
          "mod clears")
    claude.replies.append("OK")
    await bio(alex, "a red-haired dwarf engineer with a bad knee")
    r = await bio(brad, "clear")
    check("cleared" in r, r)

    # ---- adventures ----
    async def create_thread(self, name, auto_archive_duration=None):
        t = FakeThread(guild, 900 + len(threads), name)
        threads[t.id] = t
        return t
    FakeMessage.create_thread = create_thread
    claude.replies.clear()
    claude.replies.append("You wake on a cold deck. What do you do?")
    await run(alex, "!adventure a haunted space station")
    thread = next(iter(threads.values()))
    adventures = await bf.config.guild(guild).adventures()
    check(str(thread.id) in adventures and "A new adventure begins" in thread.sent[0].content
          and "adventure bio" in thread.sent[0].content
          and "cold deck" in thread.sent[-1].content, [m.content for m in thread.sent])
    check("haunted space station" in claude.calls[-1]["system"], "setting in the narrator prompt")
    check("- Alex: a red-haired dwarf engineer" in claude.calls[-1]["system"] and "Chris:" not in claude.calls[-1]["system"],
          "starter's bio in the prompt")
    bf_mod.ADVENTURE_DEBOUNCE = 0.1
    claude.replies.append("Alex finds a keycard; Chris hears a hum. What do you do?")
    await bf.on_message_without_command(FakeMessage(thread, "I search the room", author=alex))
    await bf.on_message_without_command(FakeMessage(thread, "I listen at the door", author=chris))
    await asyncio.sleep(0.3)
    last = claude.calls[-1]["messages"]
    check(last[-1]["content"] == "Alex: I search the room\nChris: I listen at the door" and len(last) == 3,
          f"moves batched into one turn: {last}")
    check("keycard" in thread.sent[-1].content, "narrated")
    check((await bf.config.guild(guild).adventures())[str(thread.id)]["players"] == [2, 3], "players tracked")
    check("- Chris: a nervous ship's cook" in claude.calls[-1]["system"], "joining player's bio added")
    # a refused turn: deflect in character, drop the move, keep going
    claude.replies.append("REFUSED")
    await bf.on_message_without_command(FakeMessage(thread, "something unprintable", author=chris))
    await asyncio.sleep(0.3)
    check(thread.sent[-1].content == bf_mod.ADVENTURE_DEFLECT, thread.sent[-1].content)
    # someone else's error text that merely looks like a refusal isn't treated as one
    check(bf._is_refusal(claude.REFUSAL) and not bf._is_refusal("🚫 I can't help with that one.")
          and not bf._is_refusal(None), "refusal is the Claude cog's exact REFUSAL text")
    # a daily-limit failure names whose limit it was
    claude.limited[chris.id] = 5
    claude.replies.append("⏳ You've used all 5 AI messages for today. The limit resets at midnight UTC.")
    await bf.on_message_without_command(FakeMessage(thread, "I sneak past", author=chris))
    await asyncio.sleep(0.3)
    check(thread.sent[-1].content.startswith("⏳ Chris has used all 5 AI messages")
          and thread.sent[-1].kw.get("allowed_mentions") is not None, thread.sent[-1].content)
    claude.limited.clear()
    claude.replies.append("The hum grows louder. What do you do?")
    await bf.on_message_without_command(FakeMessage(thread, "I open the door", author=chris))
    await asyncio.sleep(0.3)
    sent_story = claude.calls[-1]["messages"]
    check(sent_story[-1]["content"] == "Chris: I open the door" and len(sent_story) == 5
          and not any("sneak" in m["content"] for m in sent_story)
          and not any("unprintable" in m["content"] for m in sent_story), f"refused move dropped: {sent_story}")
    # the Catch me up button on the first message, and the hidden story notes
    intro = thread.sent[0]
    buttons = [getattr(i, "item", i) for i in intro.kw["view"].children]
    check([b.label for b in buttons] == ["Catch me up"] and buttons[0].custom_id == f"pl:adv:recap:{thread.id}"
          and "**Catch me up** sums up the story, just for you." in intro.content, "recap button on the intro")
    claude.replies.append("- The crew is in the reactor room\n- Alex has a keycard")
    await bf._update_notes(thread, alex)
    notes_call = claude.calls[-1]
    check(notes_call["system"] == bf_mod.STORY_NOTES_SYSTEM and notes_call["fast"]
          and notes_call["count_toward_limit"] is False and "The hum grows louder" in notes_call["messages"][0]["content"]
          and (await bf.config.guild(guild).adventures())[str(thread.id)]["notes"].startswith("- The crew is in"),
          notes_call["messages"][0]["content"][-200:])
    claude.replies.append("- Chris opened a door\nNow: a hum fills the room")
    i = FakeInteraction(bot, guild, chris, thread)
    await bf_mod.AdventureRecapButton(thread.id).callback(i)
    recap_call = claude.calls[-1]
    check(i.followup.calls and i.followup.calls[-1][1].get("ephemeral")
          and i.followup.calls[-1][0].startswith("🗺️ **The story so far**\n- Chris opened a door")
          and "Alex has a keycard" in recap_call["messages"][0]["content"] and "Chris" in recap_call["system"],
          i.followup.calls)
    claude.replies.append("Sparks fly. What do you do?")
    await bf.on_message_without_command(FakeMessage(thread, "I check the reactor", author=alex))
    await asyncio.sleep(0.3)
    check("Story notes" in claude.calls[-1]["system"] and "Alex has a keycard" in claude.calls[-1]["system"],
          "the narrator sees its notes")
    i = FakeInteraction(bot, guild, chris, channel)
    await bf_mod.AdventureRecapButton(thread.id).callback(i)
    check(i.followup.calls[-1][0].startswith("❓ There's no adventure running here."), "recap outside the thread")
    claude.replies.append("- Lots happened")
    await run(chris, "!adventure recap", ch=thread)
    check(chris.dms and chris.dms[-1].content.startswith("🗺️ **The story so far**"), "recap command sends a DM")
    await run(chris, "!adventure stop", ch=thread)
    check("Only whoever started" in thread.sent[-1].content, "only the starter or a mod can stop")
    claude.replies.append("And so the station fell silent. The end.")
    claude.replies.append("Two weary crew members in a quiet reactor room, painterly sci-fi.")
    gemini.prompts.clear()
    await run(alex, "!adventure stop", ch=thread)
    check("The End" in thread.sent[-1].content and thread.edits and str(thread.id) not in
          await bf.config.guild(guild).adventures(), "stopped and archived")
    scene = claude.calls[-1]
    check(scene["system"] == bf_mod.FINAL_SCENE_PROMPT and scene["fast"] and scene["count_toward_limit"] is False
          and "station fell silent" in scene["messages"][0]["content"]
          and "Alex: a red-haired dwarf" in scene["messages"][0]["content"]
          and "The hum grows louder" in scene["messages"][0]["content"], scene["messages"][0]["content"][:300])
    check(gemini.prompts == ["Two weary crew members in a quiet reactor room, painterly sci-fi."] and gemini.quiet
          and thread.sent[-2].content.startswith("🎨") and "station fell silent" in thread.sent[-3].content,
          [m.content[:30] for m in thread.sent[-3:]])
    # a refused ending: no picture, still ends
    bf.adventure.reset_cooldown(await bot.get_context(FakeMessage(channel, "!adventure x", author=alex)))
    claude.replies.append("Ahoy. What do you do?")
    await run(alex, "!adventure a pirate ship")
    t3 = list(threads.values())[-1]
    claude.replies.append("REFUSED")
    gemini.prompts.clear()
    await run(alex, "!adventure stop", ch=t3)
    check(not gemini.prompts and "The End" in t3.sent[-1].content and t3.sent[-2].content == bf_mod.ADVENTURE_DEFLECT,
          [m.content[:30] for m in t3.sent])
    threads.pop(t3.id)
    # restart: story rebuilt from the thread
    t2 = FakeThread(guild, 950, "🗺️ again")
    threads[t2.id] = t2
    async with bf.config.guild(guild).adventures() as adv:
        adv[str(t2.id)] = {"setting": "a pirate cove", "started_by": 2, "started_at": 0}
    t2.history_messages = [FakeMessage(t2, "I raise the flag", author=alex),
                           FakeMessage(t2, "The flag snaps in the wind. What now?", author=guild.me)]
    for m in t2.history_messages:
        m.clean_content = m.content
    claude.replies.append("Cannons boom.")
    await bf.on_message_without_command(FakeMessage(t2, "I fire the cannon", author=chris))
    await asyncio.sleep(0.3)
    msgs = claude.calls[-1]["messages"]
    check([m["role"] for m in msgs] == ["user", "assistant", "user"] and "Alex: I raise the flag" in msgs[0]["content"],
          f"re-seeded after restart: {msgs}")

    # ---- trivia writer ----
    def qs(start, n, prefix="Question"):
        return json.dumps([{"q": f"{prefix} {k}?", "a": [f"Answer {k}"]} for k in range(start, start + n)])

    async def fresh(cmd):
        for c in (bf.maketrivia, bf.maketrivia_redo):
            c.reset_cooldown(await bot.get_context(FakeMessage(channel, "!maketrivia x", author=brad)))

    await gm.add_games(guild, brad, ["Rocket League", "Deadlock", "Barony"])
    claude.replies.append(qs(0, 12))
    await run(brad, "!maketrivia our games")
    path = DATA_DIR / "bb_our_games.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    check(path.exists() and data["Question 3?"] == ["Answer 3"] and "AUTHOR" in data and
          "Wrote 12 questions" in channel.sent[-1].content, channel.sent[-1].content)
    check("Rocket League" in claude.calls[-1]["messages"][0]["content"], "our games uses the library")
    check(claude.calls[-2]["messages"][0]["content"].startswith("Write 25 questions")
          and claude.calls[-1]["messages"][0]["content"].startswith("Write 18 questions"), "default 30, in batches")
    check("Only 12 of the 30" in channel.sent[-1].content, "short batch noted")

    # adding: sees existing questions, skips duplicates, keeps old ones
    await fresh(None)
    calls_before = len(claude.calls)
    claude.replies.append(json.dumps([{"q": "Question 3?", "a": ["dup"]}, {"q": "New one?", "a": ["Yes"]}]))
    await run(brad, "!maketrivia 10 our games")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    prompt = claude.calls[calls_before]["messages"][0]["content"]
    check("- Question 11?" in prompt and "Write different ones" in prompt, "existing questions sent to Claude")
    check(len([k for k in data if k not in ("AUTHOR", "DESCRIPTION")]) == 13 and data["Question 3?"] == ["Answer 3"]
          and data["New one?"] == ["Yes"] and data["DESCRIPTION"].startswith("13 questions"), data)
    check("Added 1 question to" in channel.sent[-1].content and "now has 13" in channel.sent[-1].content,
          channel.sent[-1].content)

    # big request: batches of 25 with a progress message edited into the result
    await fresh(None)
    calls_before, sent_before = len(claude.calls), len(channel.sent)
    claude.replies += [qs(100, 25, "Big"), qs(125, 25, "Big"), qs(150, 25, "Big"), qs(175, 25, "Big")]
    await run(brad, "!maketrivia 150 volcanoes")
    batch_prompts = [c["messages"][0]["content"] for c in claude.calls[calls_before:]]
    check(len(batch_prompts) == 4 and all(b.startswith("Write 25 questions") for b in batch_prompts)
          and "- Big 149?" in batch_prompts[3], [b[:40] for b in batch_prompts])
    status = channel.sent[sent_before]
    check(len(channel.sent) == sent_before + 1 and "Wrote 100" in status.content
          and any("25/100" in (e.get("content") or "") for e in status.edits), status.content)
    vdata = yaml.safe_load((DATA_DIR / "bb_volcanoes.yaml").read_text(encoding="utf-8"))
    check(len(vdata) == 102, len(vdata))

    # redo replaces; a failed redo leaves the old list
    await fresh(None)
    claude.replies.append("not json")
    await run(brad, "!maketrivia redo 15 volcanoes")
    check("didn't come out" in channel.sent[-1].content and "old list is unchanged" in channel.sent[-1].content
          and len(yaml.safe_load((DATA_DIR / "bb_volcanoes.yaml").read_text(encoding="utf-8"))) == 102,
          channel.sent[-1].content)
    await fresh(None)
    claude.replies.append(qs(0, 10, "Redo"))
    await run(brad, "!maketrivia redo 10 volcanoes")
    vdata = yaml.safe_load((DATA_DIR / "bb_volcanoes.yaml").read_text(encoding="utf-8"))
    check(len(vdata) == 12 and "Redo 0?" in vdata and "Big 100?" not in vdata, list(vdata)[:4])
    check("- " not in claude.calls[-1]["messages"][0]["content"], "redo doesn't send old questions")

    # list size cap
    bf_mod.TRIVIA_LIST_MAX = 10
    await fresh(None)
    calls_before = len(claude.calls)
    await run(brad, "!maketrivia volcanoes")
    check("most one list can hold" in channel.sent[-1].content and len(claude.calls) == calls_before,
          channel.sent[-1].content)
    bf_mod.TRIVIA_LIST_MAX = 300

    # show
    await run(brad, "!maketrivia show")
    check("**`bb_our_games`**\n-# 13 questions" in card_text(channel.sent[-1])
          and "**`bb_volcanoes`**\n-# 10 questions" in card_text(channel.sent[-1])
          and card_text(channel.sent[-1]).endswith("\n-# `!maketrivia show <name>` shows one"), card_text(channel.sent[-1]))
    await run(brad, "!maketrivia show our games")
    check("**1.** Question 0?\n-# ||Answer 0||" in card_text(brad.dms[-1])
          and "**8.** Question 7?\n-# ||Answer 7||" in card_text(brad.dms[-1]), card_text(brad.dms[-1]))
    check(card_text(brad.dms[-1]).endswith("-# Page 1 of 2 · 13 questions · `!maketrivia remove bb_our_games <numbers>` "
                                           "drops some"), card_text(brad.dms[-1])[-200:])
    row = bf_mod.trivia_row(300, "Line one\nline two || " + "long " * 200, ["A|B " * 100])
    text = bf_mod.ui.row_text(row)
    check(len(text) < 600 and text.count("||") == 2 and text.endswith("||") and text.count("\n") == 1
          and text.split("\n")[1].startswith("-# ||"), "trivia row: one-line question, whole spoiler, under 600")
    await run(brad, "!maketrivia show bb_nothing")
    check("don't have a trivia list called `bb_nothing`" in channel.sent[-1].content, channel.sent[-1].content)
    long_q = {f"A rather long question number {k} about something?": [f"Answer {k}"] for k in range(80)}
    bf_mod.write_trivia(DATA_DIR / "bb_long.yaml", {"AUTHOR": "x"}, long_q)
    await run(brad, "!maketrivia show bb_long")
    board = brad.dms[-1]
    check(board.kw.get("file") is None and "80 questions" in card_text(board) and "Page 1 of 10" in card_text(board)
          and [b.emoji.name for b in card_buttons(board)] == ["◀️", "▶️"], "long list pages as a board")

    # remove by number, by text, ambiguous, out of range
    await run(brad, "!maketrivia remove our_games 1 13")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    check("Question 0?" not in data and "New one?" not in data and data["DESCRIPTION"].startswith("11 questions")
          and "Removed 2" in channel.sent[-1].content and "11 left" in channel.sent[-1].content, channel.sent[-1].content)
    await run(brad, "!maketrivia remove bb_our_games 40")
    check("questions 1-11" in channel.sent[-1].content and "no 40" in channel.sent[-1].content, channel.sent[-1].content)
    await run(brad, "!maketrivia remove our_games question")
    check("matches 11 questions" in channel.sent[-1].content and len(yaml.safe_load(path.read_text(encoding="utf-8"))) == 13,
          channel.sent[-1].content)
    await run(brad, '!maketrivia remove "our games" question 5')
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    check("Question 5?" not in data and "Removed 1" in channel.sent[-1].content, channel.sent[-1].content)
    await run(brad, "!maketrivia remove our_games zebra")
    check("No question in `bb_our_games` matches" in channel.sent[-1].content, channel.sent[-1].content)
    bf_mod.write_trivia(DATA_DIR / "bb_tiny.yaml", {}, {"Only?": ["Yes"]})
    await run(brad, "!maketrivia remove tiny 1")
    check(not (DATA_DIR / "bb_tiny.yaml").exists() and "is gone" in channel.sent[-1].content, channel.sent[-1].content)

    # bad output, mods only
    await fresh(None)
    claude.replies.append("not json")
    await run(brad, "!maketrivia 15 lighthouses")
    check("didn't come out" in channel.sent[-1].content and not (DATA_DIR / "bb_lighthouses.yaml").exists(),
          "bad output handled")
    import inspect, re as _re
    src = inspect.getsource(bf_mod)
    blocks = _re.findall(r"((?:    @[^\n]+\n)+)    async def (maketrivia\w*)", src)
    check(len(blocks) == 4 and all("@checks.mod_or_permissions(manage_messages=True)" in b for b, _ in blocks),
          [n for _, n in blocks])

    # ---- guess the game ----
    bf_mod.GUESS_SECONDS, bf_mod.GUESS_HINTS = 1.0, (0.3, 0.6)
    claude.replies.append("A boxy car flies through the air to strike a giant ball in a stadium.")
    async def wait_for(event, timeout=None, check=None):
        await asyncio.sleep(timeout)
        raise asyncio.TimeoutError
    real_wait_for = bot.wait_for
    bot.wait_for = wait_for
    import random
    bf._recent.clear()
    random.seed(3)
    await run(alex, "!guessgame")
    answer = bf._guessing[channel.id]["answer"]
    check(gemini.prompts and answer.lower() not in gemini.prompts[-1].lower() and "No text" in gemini.prompts[-1],
          gemini.prompts)
    check(not claude.calls[-1]["count_toward_limit"], "the scene description doesn't count toward limits")
    await asyncio.sleep(1.3)
    texts = [m.content for m in channel.sent[-4:]]
    check(any(t.startswith("💡 Hint") for t in texts) and f"It was **{answer}**" in texts[-1], texts)
    check(channel.id not in bf._guessing, "round cleaned up")
    # a winner
    claude.replies.append("Some scene without the name.")

    async def win_wait_for(event, timeout=None, check=None):
        guess = FakeMessage(channel, answer.lower(), author=chris)
        async def reply(content, **kw):
            return await channel.send(content, **kw)
        guess.reply = reply
        assert check(guess)
        return guess
    bot.wait_for = win_wait_for
    bf.guessgame.reset_cooldown(await bot.get_context(FakeMessage(channel, "!guessgame", author=alex)))
    bf._recent.clear()
    random.seed(3)
    await run(alex, "!guessgame")
    await asyncio.sleep(0.1)
    check(f"got it: **{answer}**" in channel.sent[-1].content and await bf.config.member(chris).wins() == {"guess": 1},
          channel.sent[-1].content)
    am = channel.sent[-1].kw.get("allowed_mentions")
    check(am is not None and not am.users and not am.everyone and not am.roles and "(1 picture game won)" in channel.sent[-1].content,
          "winner announced without a ping")
    await run(alex, "!guessgame top")
    top = card_text(channel.sent[-1])
    check("**1. Chris** 🥇\n-# 1 win · 1 picture game" in top and "<@" not in top, top)
    # a scene that leaks the name is rejected
    claude.replies.append(f"The world of {answer} at dusk.")
    bf.guessgame.reset_cooldown(await bot.get_context(FakeMessage(channel, "!guessgame", author=alex)))
    bf._recent.clear()
    random.seed(3)
    n_prompts = len(gemini.prompts)
    await run(alex, "!guessgame")
    check(len(gemini.prompts) == n_prompts and "couldn't come up" in channel.sent[-1].content, "leak guarded")
    bot.wait_for = real_wait_for

    for name in ("Parlor", "GameManager", "GeminiChat", "ClaudeChat"):
        await bot.remove_cog(name)

    # ---- ClaudeChat.complete ----
    guild2 = FakeGuild(2)
    member = guild2.add(5, "Dana")
    bot2 = TestBot(guild2)
    cc = claude_mod.ClaudeChat(bot2)
    await bot2.add_cog(cc)
    seen = []

    class Client:
        class messages:
            @staticmethod
            async def create(**kw):
                kw.setdefault("betas", None)
                seen.append(kw)
                r = MagicMock()
                r.model, r.stop_reason = kw["model"], "end_turn"
                r.content = [MagicMock(type="text", text="Hello there")]
                r.usage = MagicMock(input_tokens=100, output_tokens=10, cache_read_input_tokens=0,
                                    cache_creation_input_tokens=0, server_tool_use=None)
                return r

    Client.beta = Client

    async def get_client():
        return Client()
    cc._get_client = get_client
    text, err = await cc.complete(member, guild2.channel, system="Do the thing.", messages=[{"role": "user", "content": "hi"}])
    check(text == "Hello there" and err is None and seen[-1]["model"] == "claude-sonnet-5-5"
          and "personality" in seen[-1]["system"] and seen[-1]["system"].endswith("Do the thing."), seen[-1]["system"][:80])
    text, err = await cc.complete(member, guild2.channel, system="x", messages=[{"role": "user", "content": "hi"}],
                                  fast=True, persona=False)
    check(seen[-1]["model"] == "claude-haiku-5-5" and seen[-1]["system"] == "x", "fast, no persona")
    check(seen[-2]["betas"] == [claude_mod.FALLBACK_BETA] and seen[-2]["extra_body"].get("fallbacks") == "default"
          and seen[-1]["betas"] is None and "fallbacks" not in seen[-1]["extra_body"], "refusal fallback on Sonnet only")
    stop = {"reason": "refusal", "text": ""}
    real_create = Client.messages.create

    async def refusing_create(**kw):
        r = await real_create(**kw)
        r.stop_reason = stop["reason"]
        r.content = [MagicMock(type="text", text=stop["text"])] if stop["text"] else []
        return r
    Client.messages.create = staticmethod(refusing_create)
    text, err = await cc.complete(member, guild2.channel, system="x", messages=[{"role": "user", "content": "hi"}])
    check(text is None and err == claude_mod.ClaudeChat.REFUSAL == cc.REFUSAL and err.startswith("❌"),
          f"refusal returns REFUSAL: {err}")
    stop.update(reason="end_turn", text="")
    text, err = await cc.complete(member, guild2.channel, system="x", messages=[{"role": "user", "content": "hi"}])
    check(text is None and err != cc.REFUSAL and err.startswith("❌"), f"empty reply isn't a refusal: {err}")
    Client.messages.create = staticmethod(real_create)
    await cc.config.guild(guild2).daily_limit.set(2)
    text, err = await cc.complete(member, guild2.channel, system="x", messages=[{"role": "user", "content": "hi"}])
    check(text is None and "2 AI messages" in err and err.startswith("⏳") and err == cc.limit_text(2),
          f"daily limit respected: {err}")
    check(await cc.limit_reached(member) == 2, "limit_reached is public")
    await cc.config.guild(guild2).daily_limit.set(0)

    # ---- catch-up (in the Claude cog since 2026-11-07) ----
    history = []

    def chan_history(limit=None, before=None, **kw):
        async def gen():
            items = list(reversed(history))
            if before is not None:
                items = [m for m in items if m.id != before.id]
            for m in items[:limit]:
                yield m
        return gen()
    channel2 = guild2.channel
    channel2.history = chan_history
    calls = []

    async def fake_complete(member, channel, *, system, messages, **kw):
        calls.append({"system": system, "messages": messages, **kw})
        return "- Brad and Chris planned a raid for Friday 9pm", None
    cc.complete = fake_complete
    erin, finn, gus = guild2.add(6, "Erin"), guild2.add(7, "Finn"), guild2.add(8, "Gus")
    history += [msg_at(channel2, erin, "I'm out for the night", 120)]
    history += [msg_at(channel2, finn if i % 2 else gus, f"message {i} about friday 9pm raid", 100 - i) for i in range(12)]
    text, error = await cc.build_catchup(erin, channel2)
    check(text and text.startswith(f"📰 **Catch-up for {channel2.mention}**\n-# 12 messages since <t:")
          and "Friday 9pm" in text, text)
    check(calls[-1]["fast"] and not calls[-1]["persona"] and "message 0 about" in calls[-1]["messages"][0]["content"]
          and "I'm out" not in calls[-1]["messages"][0]["content"], "transcript is only since they last spoke")
    history.append(msg_at(channel2, erin, "back!", 1))
    text, error = await cc.build_catchup(erin, channel2)
    check(text is None and "caught up" in error, error)
    i = FakeInteraction(bot2, guild2, finn, channel2)
    await cc.slash_catchup.callback(cc, i)
    check(i.followup.calls and i.followup.calls[-1][1].get("ephemeral"), "slash catch-up is ephemeral")
    # ---- the AI chat steps aside in game threads ----
    responded = []

    async def fake_respond(message, prompt, key, **kw):
        responded.append(prompt)
    cc._respond = fake_respond

    class Game(dcommands.Cog, name="FakeGame"):
        def __init__(self):
            self.calls = []

        async def game_takes_message(self, message, text, *, command):
            self.calls.append((text, command))
            return message.channel.id == 4242
    game = Game()
    await bot2.add_cog(game)
    from harness import FakeChannel
    game_thread = FakeChannel(guild2, 4242)
    msg = FakeMessage(game_thread, f"<@{guild2.me.id}> is it co-op?", author=member)
    msg.mentions = [guild2.me]
    await cc.on_message_without_command(msg)
    check(not responded and game.calls[-1] == ("is it co-op?", False), f"mention in a game thread: {game.calls}")
    msg = FakeMessage(channel2, f"<@{guild2.me.id}> hello", author=member)
    msg.mentions = [guild2.me]
    await cc.on_message_without_command(msg)
    check(responded == ["hello"], f"elsewhere the AI chat answers: {responded}")
    ctx = await bot2.get_context(FakeMessage(game_thread, "!butler is it co-op?", author=member))
    await bot2.invoke(ctx)
    ctx = await bot2.get_context(FakeMessage(game_thread, "!ai is it co-op?", author=member))
    await bot2.invoke(ctx)
    check(game.calls[-2:] == [("is it co-op?", True)] * 2 and responded == ["hello"], "!butler and !ai hand over too")
    await bot2.remove_cog("FakeGame")
    await bot2.remove_cog("ClaudeChat")


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
