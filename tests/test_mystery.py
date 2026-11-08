"""Parlor's Murder at the Manor: writing the case, questioning, clues, accusations, endings, weekly, settings."""
import asyncio
import json
import time

from harness import card_color, card_text, FakeGuild, FakeMessage, TestBot, dcommands, discord, load

parlor_mod = load("parlor", "parlor")
claude_mod = load("claude", "claude")
ui = parlor_mod.ui
FakeMessage._state = None
results = []

CASE = {
    "title": "Death at the Gala",
    "setting": "A charity gala at the manor. Lord Vane was found in the library at ten.",
    "victim": "Lord Vane, the host, who owed everyone money.",
    "suspects": [
        {"name": "Colonel Ashby", "role": "Old army friend", "manner": "gruff", "alibi": "In the billiard room",
         "truth": "Was in the library arguing", "secret": "Gambling debts", "guilty": True},
        {"name": "Mrs. Finch", "role": "The housekeeper", "manner": "prim", "alibi": "In the kitchen",
         "truth": "In the kitchen", "secret": "Reads his letters", "guilty": False},
        {"name": "Dr. Okafor", "role": "The family doctor", "manner": "calm", "alibi": "Treating a guest",
         "truth": "Treating a guest", "secret": "", "guilty": False},
        {"name": "Lady Pell", "role": "The rival", "manner": "sharp", "alibi": "On the terrace",
         "truth": "On the terrace, smoking", "secret": "Wants his land", "guilty": False},
    ],
    "clues": ["Chalk dust on the library rug.", "A torn IOU in the fireplace.", "The billiard room was dark at nine.",
              "A colonel's cufflink under the desk.", "The terrace door was locked from inside."],
    "solution": "Colonel Ashby killed Lord Vane over a gambling debt. The chalk, the IOU and the cufflink give him away.",
}


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


class FakeClaude(dcommands.Cog, name="ClaudeChat"):
    REFUSAL = claude_mod.ClaudeChat.REFUSAL

    def __init__(self):
        self.calls, self.replies = [], []

    async def complete(self, member, channel, *, system, messages, **kw):
        self.calls.append({"member": member, "system": system, "messages": messages, **kw})
        reply = self.replies.pop(0) if self.replies else "Reply."
        return (None, reply) if reply.startswith(("ERR", "❌")) else (reply, None)


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

    def permissions_for(self, member):
        return self.guild.channel.permissions_for(member)


async def main():
    # ---- helpers ----
    case = parlor_mod.parse_case("```json\n" + json.dumps(CASE) + "\n```")
    check(case and case["title"] == "Death at the Gala" and len(case["suspects"]) == 4 and len(case["clues"]) == 5
          and case["suspects"][0]["guilty"] is True and case["suspects"][2]["secret"] == "", "a case parses")
    two_guilty = json.loads(json.dumps(CASE))
    two_guilty["suspects"][1]["guilty"] = True
    check(parlor_mod.parse_case(json.dumps(two_guilty)) is None and parlor_mod.parse_case("not json") is None
          and parlor_mod.parse_case(json.dumps({**CASE, "clues": ["one"]})) is None, "bad cases are rejected")
    sus = case["suspects"]
    m = parlor_mod.match_suspect
    check(m(sus, "Colonel, where were you at nine?") == (0, "where were you at nine?")
          and m(sus, "Ashby where were you?") == (0, "where were you?")
          and m(sus, "Mrs. Finch: did you hear it?") == (1, "did you hear it?")
          and m(sus, "the colonel did you do it") == (0, "did you do it")
          and m(sus, "Lady Pell") == (3, "") and m(sus, "the butler did it")[0] is None, "matching suspects")

    # ---- setup ----
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex, chris, mira = guild.add(2, "Alex"), guild.add(3, "Chris"), guild.add(4, "Mira")
    channel = guild.channel
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    errors = []

    async def on_command_error(ctx, error):
        errors.append(f"{ctx.message.content}: {error!r}")
    bot.on_command_error = on_command_error
    claude = FakeClaude()
    await bot.add_cog(claude)
    pc = parlor_mod.Parlor(bot)
    await bot.add_cog(pc)
    pc.game_loop.cancel()
    threads = {}

    async def create_thread(self, name, auto_archive_duration=None):
        t = FakeThread(guild, 700 + len(threads), name)
        t.archive = auto_archive_duration
        threads[t.id] = t
        return t
    FakeMessage.create_thread = create_thread
    guild.get_channel_or_thread = lambda cid: channel if cid == channel.id else threads.get(cid)
    guild.get_channel = guild.get_channel_or_thread

    async def run(author, content, ch=None):
        msg = FakeMessage(ch or channel, content, author=author)
        ctx = await bot.get_context(msg)
        await bot.invoke(ctx)
        await asyncio.sleep(0.05)
        return ctx

    def reset(cmd):
        cmd.reset_cooldown(type("C", (), {"message": FakeMessage(channel, "!x", author=brad), "guild": guild,
                                          "channel": channel, "author": brad})())

    async def live():
        return await pc.config.guild(guild).mystery()

    # ---- starting: a bad case is retried once ----
    claude.replies[:] = ["not json at all", json.dumps(CASE)]
    await run(alex, "!mystery")
    mys = await live()
    thread = threads[mys["thread_id"]]
    card = channel.messages[mys["message_id"]]
    text = card_text(card)
    check(len([c for c in claude.calls if c["system"].startswith("You write a murder mystery")]) == 2
          and claude.calls[-1]["count_toward_limit"] is False and not claude.calls[-1].get("fast"), "written by Sonnet")
    check(text.startswith("### 🃏 Murder at the Manor: Death at the Gala\nA charity gala")
          and "**Colonel Ashby**\n-# Old army friend" in text and "**Clues**\n1. Chalk dust on the library rug." in text
          and "`!interrogate <name> <question>` · one `!accuse <name>` each · Solve it by <t:" in text
          and "next clue <t:" in text and "guilty" not in text.lower() and "IOU" not in text
          and card_color(card) == ui.ATTENTION, text)
    check(thread.name == "🃏 Death at the Gala" and thread.archive == 60
          and thread.sent[0].content.startswith("🃏 **The suspects are waiting in the drawing room:** Colonel Ashby, "
                                                "Mrs. Finch, Dr. Okafor, Lady Pell.")
          and "`!interrogate Ashby where were you at nine?`" in thread.sent[0].content
          and thread.sent[1].content == "🔎 **Clue 1:** Chalk dust on the library rug.", [m.content for m in thread.sent])
    check(abs(mys["ends_at"] - time.time() - 3600) < 5 and abs(mys["interval"] - 720) < 1 and mys["clues_shown"] == 1,
          "an hour, with clues spread through it")
    reset(pc.mystery)
    await run(chris, "!mystery long")
    check(channel.sent[-1].content.startswith("⏳ A mystery is already running in this server."), "one at a time")

    # ---- questioning ----
    await run(chris, "!interrogate Colonel where were you?")
    check(channel.sent[-1].content.startswith("❓ There's no mystery running here.")
          and f"/{mys['message_id']}" in channel.sent[-1].content, "outside the thread: a pointer to it")
    claude.replies.append("In the billiard room, naturally. Alone, before you ask.")
    pc.interrogate.reset_cooldown(await bot.get_context(FakeMessage(thread, "!interrogate", author=chris)))
    await run(chris, "!interrogate Colonel, where were you at nine?", ch=thread)
    call = claude.calls[-1]
    check(thread.sent[-1].content == "**Colonel Ashby:** In the billiard room, naturally. Alone, before you ask."
          and thread.sent[-1].kw.get("mention_author") is False, thread.sent[-1].content)
    check(call["fast"] and call["persona"] is False and call["count_toward_limit"] is False
          and "You play Colonel Ashby" in call["system"] and parlor_mod.MYSTERY_GUILTY in call["system"]
          and "Chalk dust" in call["system"] and "IOU" not in call["system"]
          and call["messages"][0]["content"] == "Chris asks: where were you at nine?", call["system"][:120])
    pc.interrogate.reset_cooldown(await bot.get_context(FakeMessage(thread, "!interrogate", author=chris)))
    claude.replies.append("I told you. The billiard room.")
    await run(chris, "!question Ashby was anyone with you?", ch=thread)
    check("Your earlier answers:\nQ (Chris): where were you at nine?\nA: In the billiard room" in
          claude.calls[-1]["messages"][0]["content"], "earlier answers keep a suspect consistent")
    claude.replies.append("I was in my kitchen.")
    await run(mira, "!interrogate finch where were you", ch=thread)
    check(parlor_mod.MYSTERY_INNOCENT in claude.calls[-1]["system"], "innocent suspects tell the truth")
    pc.interrogate.reset_cooldown(await bot.get_context(FakeMessage(thread, "!interrogate", author=mira)))
    await run(mira, "!interrogate the butler did it", ch=thread)
    check(thread.sent[-1].content.startswith("❓ Who are you asking?") and "Colonel Ashby, Mrs. Finch" in
          thread.sent[-1].content, thread.sent[-1].content)
    pc.interrogate.reset_cooldown(await bot.get_context(FakeMessage(thread, "!interrogate", author=mira)))
    await run(mira, "!interrogate Pell", ch=thread)
    check(thread.sent[-1].content.startswith("❓ What do you want to ask Lady Pell?"), thread.sent[-1].content)

    # @mentioning the bot in the thread points at !interrogate; plain chat is left alone
    note = FakeMessage(thread, f"<@{guild.me.id}> who did it?", author=alex)
    note.mentions = [guild.me]

    async def note_reply(content, **kw):
        return await thread.send(content, **kw)
    note.reply = note_reply
    calls = len(claude.calls)
    check(await pc.game_takes_message(note, "who did it?", command=False)
          and thread.sent[-1].content.startswith("🔎 The suspects answer `!interrogate <name> <question>`.")
          and len(claude.calls) == calls, "the AI chat steps aside, with a pointer and no AI")
    sent = len(thread.sent)
    chat = FakeMessage(thread, "reply to the clue", author=alex)
    check(await pc.game_takes_message(chat, "reply to the clue", command=False) and len(thread.sent) == sent,
          "a plain reply in the thread gets no pointer")

    # ---- clues on a timer ----
    async with pc.config.guild(guild).mystery() as live_m:
        live_m["next_clue_at"] = time.time() - 1
    await pc._tick_mystery(guild)
    mys = await live()
    check(thread.sent[-1].content == "🔎 **Clue 2:** A torn IOU in the fireplace." and mys["clues_shown"] == 2
          and "2. A torn IOU in the fireplace." in card_text(card), "the next clue")
    await pc._tick_mystery(guild)
    check((await live())["clues_shown"] == 2, "not before it's due")

    # ---- accusations ----
    await run(mira, "!accuse Lady Pell", ch=thread)
    check(thread.sent[-1].content.startswith("❌ **Lady Pell** didn't do it. Mira's accusation is spent.")
          and "1 accusation made" in card_text(card), thread.sent[-1].content)
    await run(mira, "!accuse Colonel Ashby", ch=thread)
    check(thread.sent[-1].content.startswith("🔒 You've already made your accusation in this mystery."), "one each")
    await run(chris, "!accuse Ashby", ch=thread)
    mys = await live()
    check(mys["phase"] == "solved" and mys["solved_by"] == chris.id
          and any(m.content.startswith("🏆 **Chris solved it!** It was **Colonel Ashby**.\n\n**What happened:** Colonel")
                  for m in thread.sent) and thread.edits[-1] == {"archived": True}, [m.content[:40] for m in thread.sent])
    text = card_text(card)
    check(card_color(card) == ui.HIGHLIGHT and "🏆 **Solved by Chris**\n-# It was Colonel Ashby." in text
          and "**What happened**\nColonel Ashby killed" in text and text.endswith("-# `!mystery` starts another"), text)
    check(channel.sent[-1].content.startswith("🏆 Murder at the Manor: Chris caught Colonel Ashby. https://discord.com/")
          and await pc.config.member(chris).wins() == {"detective": 1}, channel.sent[-1].content)
    await run(alex, "!accuse Ashby", ch=thread)
    check("There's no mystery running here." in thread.sent[-1].content, "over")

    # ---- a long one that runs out of time ----
    reset(pc.mystery)
    claude.replies[:] = [json.dumps(CASE)]
    await run(brad, "!mystery long")
    mys = await live()
    thread = threads[mys["thread_id"]]
    check(mys["long"] and thread.archive == 1440 and abs(mys["ends_at"] - time.time() - 4 * 86400) < 5, "long")
    async with pc.config.guild(guild).mystery() as live_m:
        live_m["ends_at"] = time.time() - 1
    await pc._tick_mystery(guild)
    check((await live())["phase"] == "unsolved" and thread.sent[-1].content.startswith("⌛ Time's up! It was **Colonel "
          "Ashby**.") and channel.sent[-1].content.startswith("🔎 Murder at the Manor went unsolved: it was Colonel Ashby.")
          and card_color(channel.messages[mys["message_id"]]) == ui.MUTED, thread.sent[-1].content)

    # ---- stopping ----
    reset(pc.mystery)
    claude.replies[:] = [json.dumps(CASE)]
    await run(mira, "!mystery")
    await run(chris, "!mystery stop")
    check(channel.sent[-1].content.startswith("🔒 Only whoever started the mystery"), channel.sent[-1].content)
    await run(mira, "!mystery stop")
    mys = await live()
    check(mys["phase"] == "cancelled" and channel.sent[-1].content.startswith("✅ The mystery is closed")
          and "**The case was closed early**" in card_text(channel.messages[mys["message_id"]]), "stopped")

    # ---- weekly, and the settings card ----
    async def convert_channel(self, ctx, argument):
        if argument.strip("<#>") == str(channel.id):
            return channel
        raise dcommands.ChannelNotFound(argument)
    dcommands.TextChannelConverter.convert = convert_channel
    await run(brad, f"!mystery weekly <#{channel.id}>")
    check(channel.sent[-1].content.startswith("✅ Weekly mysteries are on in"), channel.sent[-1].content)
    claude.replies[:] = [json.dumps(CASE)]
    await pc._weekly_mystery(guild)
    mys = await live()
    check(mys["phase"] == "open" and mys["long"] and mys["weekly"] and mys["started_by"] == guild.me.id
          and (await pc.config.guild(guild).mystery_weekly())["next_at"] > time.time() + 6 * 86400, "weekly mystery")
    await pc.config.channel(channel).threads.set(False)
    await run(alex, "!parlor settings")
    text = card_text(channel.sent[-1])
    check(text.startswith("### 🃏 Parlor settings\n**Weekly caption contest** · Off\n**Weekly mystery** · <#")
          and f"**Game threads off in** · {channel.mention}" in text
          and text.endswith("-# `!caption weekly`, `!mystery weekly` and `!parlor threads` change these"), text)
    await run(brad, "!mystery weekly off")
    check(await pc.config.guild(guild).mystery_weekly() == {}, "weekly off")

    check(not errors, f"command errors: {errors}")
    await bot.remove_cog("Parlor")
    print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")


asyncio.run(main())
