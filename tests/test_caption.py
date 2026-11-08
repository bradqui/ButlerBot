"""Parlor's caption contest: starting (screenshot or drawn), captions, voting, judging, the loop's steps, weekly."""
import asyncio
import time

from harness import DATA_DIR, card_buttons, card_color, card_text, FakeGuild, FakeInteraction, FakeMessage, TestBot, \
    dcommands, discord, load

parlor_mod = load("parlor", "parlor")
claude_mod = load("claude", "claude")
ui = parlor_mod.ui
FakeMessage._state = None
results = []
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


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
        return (None, reply) if reply.startswith(("ERR", "❌")) else (reply, None)

    async def image_block(self, source):
        self.images.append(source)
        return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}, None


class FakeGemini(dcommands.Cog, name="GeminiChat"):
    def __init__(self):
        self.prompts, self.fail = [], None

    async def render_image(self, prompt, *, channel):
        self.prompts.append(prompt)
        return (None, self.fail) if self.fail else (JPG, None)


class FakeAttachment:
    def __init__(self, filename, data, content_type="image/png"):
        self.filename, self.data, self.content_type, self.size = filename, data, content_type, len(data)

    async def read(self):
        return self.data


class FakeThread:
    def __init__(self, tid):
        self.id, self.sent, self.edits = tid, [], []

    async def send(self, content=None, **kw):
        self.sent.append(content)

    async def edit(self, **kw):
        self.edits.append(kw)


async def main():
    # ---- helpers ----
    check(parlor_mod.parse_caption_options("") == (False, "both", False, None), "defaults: both judges, 24 h")
    check(parlor_mod.parse_caption_options("quick butler thread draw a cat in space")
          == (True, "butler", True, "a cat in space"), "options, then what to draw")
    check(parlor_mod.parse_caption_options("people a frog judge") == (False, "people", False, "a frog judge"), "people")
    check(parlor_mod.clean_caption("  Hi <@123>\nthere @everyone ") == "Hi there @​everyone", "mentions dropped")
    check(len(parlor_mod.clean_caption("x" * 400)) == parlor_mod.CAPTION_MAX_CHARS, "capped")
    check(parlor_mod.image_ext(PNG) == "png" and parlor_mod.image_ext(JPG) == "jpg"
          and parlor_mod.image_ext(b"GIF89a....") == "gif" and parlor_mod.image_ext(b"RIFF\0\0\0\0WEBPVP8 ") == "webp"
          and parlor_mod.image_ext(b"hello") is None, "image types by magic bytes")

    # ---- setup ----
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex, chris, mira, dana = guild.add(2, "Alex"), guild.add(3, "Chris"), guild.add(4, "Mira"), guild.add(5, "Dana")
    channel = guild.channel
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    errors = []

    async def on_command_error(ctx, error):
        errors.append(f"{ctx.message.content}: {error!r}")
    bot.on_command_error = on_command_error
    claude, gemini = FakeClaude(), FakeGemini()
    await bot.add_cog(claude)
    await bot.add_cog(gemini)
    pc = parlor_mod.Parlor(bot)
    await bot.add_cog(pc)
    pc.game_loop.cancel()
    threads = {}

    async def create_thread(self, name, auto_archive_duration=None):
        t = FakeThread(800 + len(threads))
        t.name, t.archive = name, auto_archive_duration
        threads[t.id] = t
        return t
    FakeMessage.create_thread = create_thread
    guild.get_channel_or_thread = lambda cid: channel if cid == channel.id else threads.get(cid)
    guild.get_channel = guild.get_channel_or_thread

    async def run(author, content, **attrs):
        msg = FakeMessage(channel, content, author=author)
        for k, v in attrs.items():
            setattr(msg, k, v)
        ctx = await bot.get_context(msg)
        await bot.invoke(ctx)
        await asyncio.sleep(0.05)
        return ctx

    def reset():
        pc.caption.reset_cooldown(FakeContext())

    class FakeContext:   # enough for reset_cooldown (the channel bucket)
        def __init__(self):
            self.message = FakeMessage(channel, "!caption", author=brad)
            self.channel, self.author, self.guild = channel, brad, guild

    async def contest():
        caps = await pc.config.guild(guild).captions()
        live = [c for c in caps.values() if c["phase"] in parlor_mod.CAPTION_RUNNING]
        return live[-1] if live else list(caps.values())[-1]

    def card():
        return channel.messages[CURRENT["id"]]

    CURRENT = {}

    async def submit(member, text, cid):
        i = FakeInteraction(bot, guild, member, channel, card())
        await parlor_mod.CaptionButton(cid).callback(i)
        kind, *rest = i.response.calls[-1]
        if kind != "modal":
            return i.response.calls[-1][1]
        modal = rest[0]
        modal.text._value = text
        j = FakeInteraction(bot, guild, member, channel, card())
        await modal.on_submit(j)
        return j.response.calls[-1][1]

    async def vote(member, number, cid):
        i = FakeInteraction(bot, guild, member, channel, card())
        i.data = {"values": [str(number)]}
        await parlor_mod.CaptionVote(cid).callback(i)
        return i.response.calls[-1][1]

    async def expire(cid, key):
        async with pc.config.guild(guild).captions() as caps:
            caps[cid][key] = time.time() - 1
        await pc._advance_caption(guild, cid)

    # ---- a screenshot contest, judged by both ----
    shot = FakeAttachment("base.png", PNG)
    await run(alex, "!caption thread", attachments=[shot])
    c = await contest()
    CURRENT["id"] = c["message_id"]
    cid = c["id"]
    text = card_text(card())
    check(text.startswith("### 🃏 Caption contest\n") and "**Write a caption for this picture**\n-# Captions close <t:"
          in text and "0 captions in so far" in text
          and text.endswith("-# Judged by everyone's votes and the Butler · captions stay hidden until voting"), text)
    check(card_color(card()) == ui.ATTENTION and [b.label for b in card_buttons(card())] == ["Submit caption"]
          and card().kw["file"].filename == f"caption_{cid}.png"
          and (DATA_DIR / "captions" / f"caption_{cid}.png").read_bytes() == PNG, "card with the picture attached")
    check(c["thread_id"] in threads and threads[c["thread_id"]].name == "🃏 Caption contest chat"
          and "Chat about the contest here." in threads[c["thread_id"]].sent[0], "chat thread")
    check(c["submit_ends"] - time.time() > 23 * 3600 and c["vote_for"] == 24 * 3600 and not gemini.prompts,
          "24 hours each; a screenshot needs no drawing")
    reset()
    await run(chris, "!caption", attachments=[shot])
    check(channel.sent[-1].content.startswith("⏳ A caption contest is already running here."), "one per channel")

    reply = await submit(alex, "When the <@99> boss is   just a chicken", cid)
    check(reply.startswith("✅ Your caption is in: “When the boss is just a chicken”")
          and "Nobody sees it until voting." in reply, reply)
    check("1 caption in so far" in card_text(card()) and "chicken" not in card_text(card()), "count only, captions hidden")
    first_at = (await contest())["entries"]["2"]["at"]
    await submit(alex, "Chicken boss, take two", cid)
    entry = (await contest())["entries"]["2"]
    check(entry["text"] == "Chicken boss, take two" and entry["at"] == first_at, "changing keeps your place in line")
    i = FakeInteraction(bot, guild, alex, channel, card())
    await parlor_mod.CaptionButton(cid).callback(i)
    check(i.response.calls[-1][1].text.default == "Chicken boss, take two", "the form shows your current caption")
    await submit(chris, "Not the face!", cid)
    await submit(mira, "This is fine", cid)
    check("   " not in (await submit(dana, "   ", cid)) and "empty" in (await submit(dana, "   ", cid)), "empty refused")

    # captions close: voting, in a shuffled order
    await expire(cid, "submit_ends")
    c = await contest()
    text = card_text(card())
    voting_line = channel.sent[-1]
    check(voting_line.content == f"🗳️ Voting is open in the caption contest: https://discord.com/channels/1/"
          f"{channel.id}/{c['message_id']}" and c["line_id"] == voting_line.id
          and not voting_line.kw["allowed_mentions"].users, voting_line.content)
    check(c["phase"] == "voting" and sorted(c["order"]) == ["2", "3", "4"] and text.startswith("### 🃏 Caption contest: vote")
          and "**Vote for your favorite**\n-# Voting ends <t:" in text and "Chicken boss, take two" in text
          and "Alex" not in text, text)
    select = [getattr(x, "item", x) for x in card().view.walk_children()
              if isinstance(getattr(x, "item", x), discord.ui.Select)]
    check(len(select) == 1 and [o.value for o in select[0].options] == ["1", "2", "3"]
          and select[0].custom_id == f"pl:cap:vote:{cid}", "the vote menu")
    own = c["order"].index("2") + 1
    other = 1 if own != 1 else 2
    check((await vote(alex, own, cid)).startswith("🔒 You can't vote for your own caption."), "no voting for your own")
    check((await vote(alex, other, cid)).startswith(f"✅ Voted for caption {other}."), "vote")
    chicken = own
    for voter in (brad, dana, mira):
        await vote(voter, chicken, cid)
    await vote(dana, chicken, cid)   # changing to the same is fine
    check("4 votes so far" in card_text(card()), card_text(card()))
    check((await vote(dana, 9, cid)).startswith("❌ That caption isn't in this contest."), "bad number")
    reply = await submit(dana, "too late", cid)
    check(reply.startswith("❌ Captions are closed"), reply)

    # voting closes: People's Choice, the Butler's Award, wins, cleanup
    butler_pick = next(n for n in range(1, 4) if n != chicken)
    claude.replies.append(f"{butler_pick}\nA bold choice, delivered with conviction.")
    await expire(cid, "vote_ends")
    c = await contest()
    text = card_text(card())
    butler_uid = c["order"][butler_pick - 1]
    check(c["phase"] == "done" and c["result"]["people"] == "2" and c["result"]["butler"] == butler_uid
          and card_color(card()) == ui.HIGHLIGHT, c.get("result"))
    check(text.startswith("### 🃏 Caption contest: results") and "🏆 **“Chicken boss, take two”**\n-# People's Choice · "
          "Alex · 3 votes" in text and "-# The Butler's Award · " in text
          and "*A bold choice, delivered with conviction.*" in text and text.endswith("-# `!caption top` shows the winners"),
          text)
    judge = claude.calls[-1]
    check(judge["system"] == parlor_mod.CAPTION_JUDGE_SYSTEM and judge["count_toward_limit"] is False
          and claude.images[-1] == PNG and "1. " in judge["messages"][0]["content"][1]["text"], "Butler sees picture")
    check(await pc.config.member(alex).wins() == {"caption": 1}
          and (await pc.config.member(guild.get_member(int(butler_uid))).wins()).get("butler") == 1, "wins recorded")
    results_line = channel.sent[-1].content
    check(voting_line.id in channel.deleted and results_line.startswith("🏆 Caption contest: “Chicken boss, take two” by "
          "Alex wins the People's Choice; “") and "wins the Butler's Award." in results_line
          and results_line.endswith(f"/{c['message_id']}"), results_line)
    check(not (DATA_DIR / "captions" / f"caption_{cid}.png").exists()
          and threads[c["thread_id"]].edits == [{"archived": True}], "picture deleted, thread archived")

    # ---- a thread by default where threads are on (and allowed) ----
    from harness import Perms
    Perms.create_public_threads = Perms.send_messages_in_threads = True
    reset()
    before = len(threads)
    await run(mira, "!caption", attachments=[FakeAttachment("x.png", PNG)])
    c = await contest()
    check(len(threads) == before + 1 and c["thread_id"] in threads, "threads on: the card starts a chat thread")
    CURRENT["id"] = c["message_id"]
    await run(mira, "!caption stop")
    check(c["thread_id"] in threads and threads[c["thread_id"]].edits == [{"archived": True}], "thread closed")
    await pc.config.channel(channel).threads.set(False)
    reset()
    before = len(threads)
    await run(mira, "!caption", attachments=[FakeAttachment("x.png", PNG)])
    check(len(threads) == before, "threads off: no thread unless asked for")
    await run(mira, "!caption stop")
    await pc.config.channel(channel).threads.set(True)
    del Perms.create_public_threads, Perms.send_messages_in_threads

    # ---- a drawn contest that's too quiet: extended once, then called off ----
    reset()
    claude.replies.append("A raccoon running a tiny bank.")
    await run(chris, "!caption quick people")
    c = await contest()
    CURRENT["id"] = c["message_id"]
    check(gemini.prompts[-1].startswith("A raccoon running a tiny bank.\nOne funny picture.")
          and claude.calls[-1]["system"] == parlor_mod.CAPTION_SCENE_SYSTEM and c["file"].endswith(".jpg")
          and c["quick"] and c["submit_for"] == 600 and c["vote_for"] == 300 and c["judging"] == "people"
          and c["thread_id"] is None, c)
    await submit(alex, "Interest rates are nuts", c["id"])
    await expire(c["id"], "submit_ends")
    c = await contest()
    check(c["phase"] == "open" and c["extended"] and "extended for more entries" in card_text(card()), "extended once")
    await expire(c["id"], "submit_ends")
    c = await contest()
    check(c["phase"] == "cancelled" and card_color(card()) == ui.MUTED
          and "Not enough captions came in, so this one's off." in card_text(card())
          and card_text(card()).endswith("-# Start another with `!caption`"), card_text(card()))

    # ---- people only: no Butler; a tie goes to the earlier caption ----
    reset()
    await run(brad, "!caption people draw a goose in a suit")
    c = await contest()
    CURRENT["id"] = c["message_id"]
    check(gemini.prompts[-1].startswith("a goose in a suit"), gemini.prompts[-1])
    for m, t in ((chris, "Honk if you're audited"), (mira, "Business casual"), (dana, "Goose on the loose")):
        await submit(m, t, c["id"])
    await expire(c["id"], "submit_ends")
    c = await contest()
    by = {uid: n for n, uid in enumerate(c["order"], 1)}
    await vote(alex, by["3"], c["id"])
    await vote(brad, by["4"], c["id"])
    calls = len(claude.calls)
    await expire(c["id"], "vote_ends")
    c = await contest()
    text = card_text(card())
    check(c["result"]["people"] == "3" and c["result"]["butler"] is None and len(claude.calls) == calls
          and "Butler" not in text and "Honk if you're audited" in text and "Goose on the loose" in text, text)

    # ---- the Butler alone: no vote; a ruling it can't read means no award ----
    reset()
    await run(mira, "!caption butler", attachments=[FakeAttachment("x.png", PNG)])
    c = await contest()
    CURRENT["id"] = c["message_id"]
    for m, t in ((alex, "One"), (chris, "Two"), (dana, "Three")):
        await submit(m, t, c["id"])
    claude.replies.append("I simply can't choose.")
    await expire(c["id"], "submit_ends")
    c = await contest()
    text = card_text(card())
    check(c["phase"] == "done" and not c["order"] and "**The Butler couldn't reach a verdict**" in text
          and "votes" not in text, text)

    # ---- stopping, and permissions ----
    reset()
    await run(dana, "!caption", attachments=[FakeAttachment("x.png", PNG)])
    c = await contest()
    CURRENT["id"] = c["message_id"]
    await run(chris, "!caption stop")
    check(channel.sent[-1].content.startswith("🔒 Only whoever started the contest"), channel.sent[-1].content)
    await run(dana, "!caption stop")
    check(channel.sent[-1].content.startswith("✅ Caption contest called off.")
          and "Called off by Dana." in card_text(card()), card_text(card()))
    await run(dana, "!caption stop")
    check(channel.sent[-1].content.startswith("❓ There's no caption contest running here."), "nothing to stop")

    # ---- problems starting ----
    reset()
    await run(alex, "!caption", attachments=[FakeAttachment("big.png", PNG + b"\0" * parlor_mod.CAPTION_IMAGE_MAX)])
    check(channel.sent[-1].content.startswith("❌ That picture is too big."), channel.sent[-1].content)
    reset()
    gemini.fail = "❌ Gemini didn't return an image. Try a different idea."
    await run(alex, "!caption a duck")
    check(channel.sent[-1].content == gemini.fail, "Gemini's failure is shown")
    gemini.fail = None

    # ---- weekly ----
    await run(alex, "!caption weekly")
    check(channel.sent[-1].content.startswith("Weekly caption contests are off."), channel.sent[-1].content)
    async def convert_channel(self, ctx, argument):   # the real converter needs a gateway connection
        if argument.strip("<#>") == str(channel.id):
            return channel
        raise dcommands.ChannelNotFound(argument)
    dcommands.TextChannelConverter.convert = convert_channel
    await run(brad, "!caption weekly #nowhere")
    check(channel.sent[-1].content.startswith("❓ I can't find a channel called #nowhere."), channel.sent[-1].content)
    await run(brad, f"!caption weekly <#{channel.id}>")
    weekly = await pc.config.guild(guild).caption_weekly()
    check(channel.sent[-1].content.startswith("✅ Weekly caption contests are on in") and weekly["channel"] == channel.id,
          channel.sent[-1].content)
    claude.replies.append("A knight stuck in a revolving door.")
    await pc._weekly_caption(guild)
    c = await contest()
    weekly = await pc.config.guild(guild).caption_weekly()
    check(c["weekly"] and c["started_by"] == guild.me.id and c["thread_id"] in threads
          and weekly["next_at"] > time.time() + 6 * 24 * 3600, "weekly contest with a thread, next one booked")
    await run(brad, "!caption weekly off")
    check(await pc.config.guild(guild).caption_weekly() == {}, "weekly off")

    # ---- the leaderboard, and restarts ----
    await run(alex, "!caption top")
    top = card_text(channel.sent[-1])
    check("Alex** " in top and "1 People's Choice" in top and "Butler's Award" in top, top)
    item = await parlor_mod.CaptionButton.from_custom_id(None, None, {"cid": "abcd1234"})
    check(item.cid == "abcd1234" and item.item.custom_id == "pl:cap:submit:abcd1234", "buttons work after a restart")
    check(not errors, f"command errors: {errors}")
    await bot.remove_cog("Parlor")
    print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")


asyncio.run(main())
