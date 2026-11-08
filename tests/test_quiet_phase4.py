"""
UI phase 4 (less noise), our part: SpeakUp offers take their reaction back once used or expired, and personal numbers
(`!stats me`, `!claude usage`, `!maketrivia show <list>`) go to DMs with a tick, falling back to the channel.
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from harness import (DATA_DIR, FakeGuild, FakeMessage, TestBot, card_text, dcommands, discord, enable_dms, load)

sp_mod = load("speakup", "speakup")
sp_mod.EMBED_WAIT = 0
stats_mod = load("activitystats", "activitystats")
claude_mod = load("claude", "claude")
bf_mod = load("parlor", "parlor")
ui = stats_mod.ui
FakeMessage._state = None
enable_dms()
results = []
TICKS = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


async def tick(self, **kw):
    TICKS.append(self.message.id)
    return True
dcommands.Context.tick = tick


async def add_reaction(self, emoji):
    self.reactions_added = getattr(self, "reactions_added", []) + [emoji]
    self.reactions = getattr(self, "reactions", []) + [SimpleNamespace(emoji=emoji, me=True)]


async def remove_reaction(self, emoji, member):
    if getattr(self, "gone", False):
        raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
    self.reactions_removed = getattr(self, "reactions_removed", []) + [(str(emoji), member.id)]
    self.reactions = [r for r in getattr(self, "reactions", []) if not (str(r.emoji) == str(emoji) and r.me)]
FakeMessage.add_reaction = add_reaction
FakeMessage.remove_reaction = remove_reaction
FakeMessage.jump_url = "https://discord.com/channels/1/500/1"


def no_pings(am):
    return am is not None and not am.everyone and not am.users and not am.roles


class ClaudeStub(dcommands.Cog, name="ClaudeChat"):
    def __init__(self):
        self.urls = []

    async def summarize_link(self, url, member):
        self.urls.append(url)
        return "- point one"


async def speakup_part(guild, bot, alex, chris):
    channel = guild.channel
    claude = ClaudeStub()
    await bot.add_cog(claude)
    sp = sp_mod.SpeakUp(bot)
    await bot.add_cog(sp)
    sp.reminder_loop.cancel()

    async def fetch_message(mid):
        if mid not in channel.messages:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
        return channel.messages[mid]
    channel.fetch_message = fetch_message

    def said(author, text):
        m = FakeMessage(channel, text, author=author)
        channel.messages[m.id] = m
        return m

    def click(m, emoji, who):
        return sp.on_raw_reaction_add(SimpleNamespace(message_id=m.id, user_id=who.id, emoji=emoji,
                                                      guild_id=guild.id, channel_id=channel.id, member=who))

    # ---- a used time offer takes its 🕘 back; a second click does nothing ----
    m = said(alex, "anyone want to play at 9?")
    await sp.on_message_without_command(m)
    check(m.reactions_added == ["🕘"] and sp._tracked[m.id]["channel"] == channel.id, "clock offered and tracked")
    before = len(channel.sent)
    await click(m, "🕘", chris)
    check(len(channel.sent) == before + 1 and "**at 9** is <t:" in card_text(channel.sent[-1]), "time answered")
    check(getattr(m, "reactions_removed", []) == [("🕘", guild.me.id)], "the bot's own 🕘 is taken back after use")
    await click(m, "🕘", alex)
    check(len(channel.sent) == before + 1 and m.reactions_removed == [("🕘", guild.me.id)],
          "second click after use: nothing posted, nothing removed again")
    check(not any("went wrong" in (s.content or "") for s in channel.sent), "no error message")

    # ---- a used link offer takes its 📄 back ----
    link = said(alex, "good read https://example.com/story")
    await sp.on_message_without_command(link)
    check(link.reactions_added == ["📄"], "page offered")
    await click(link, "📄", chris)
    check("**Summary**" in channel.sent[-1].content and link.reactions_removed == [("📄", guild.me.id)],
          "summary posted, 📄 taken back")
    await click(link, "📄", alex)
    check(claude.urls == ["https://example.com/story"], "second click: no second summary")
    # after a reload the offer is forgotten, but the 📄 is gone so it isn't rebuilt either
    sp._tracked.clear()
    await click(link, "📄", alex)
    check(claude.urls == ["https://example.com/story"], "after a reload: a used offer stays used")

    # ---- a rate-limited click leaves the offer (and its reaction) up ----
    limited = said(alex, "https://example.com/limited")
    await sp.on_message_without_command(limited)
    sp._summaries[chris.id] = [time.time()] * sp_mod.SUMMARIES_PER_HOUR
    await click(limited, "📄", chris)
    check(not sp._tracked[limited.id]["done"] and not getattr(limited, "reactions_removed", []),
          "not answered: the 📄 stays")
    sp._summaries.clear()

    # ---- a failed post leaves the offer up too ----
    real_send = channel.send

    async def failing_send(*a, **kw):
        raise discord.HTTPException(SimpleNamespace(status=500, reason="err"), "boom")
    channel.send = failing_send
    await click(limited, "📄", chris)
    channel.send = real_send
    check(not sp._tracked[limited.id]["done"] and not getattr(limited, "reactions_removed", []),
          "post failed: the 📄 stays")
    await click(limited, "📄", chris)
    check(limited.reactions_removed == [("📄", guild.me.id)], "retry works and then takes the 📄 back")

    # ---- the message was deleted meanwhile: still answered, no error ----
    gone = said(alex, "https://example.com/gone")
    await sp.on_message_without_command(gone)
    gone.gone = True
    before = len(channel.sent)
    await click(gone, "📄", chris)
    check(len(channel.sent) == before + 1 and "**Summary**" in channel.sent[-1].content
          and sp._tracked[gone.id]["done"], "a reaction that can't be removed doesn't break the answer")

    # ---- a rebuilt offer (after a restart) is cleaned when used ----
    sp._cooldowns.clear()
    old_time = said(alex, "anyone up to play at 9?")
    old_time.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    old_time.reactions = [SimpleNamespace(emoji="🕘", me=True)]
    await click(old_time, "🕘", chris)
    check("**at 9** is <t:" in card_text(channel.sent[-1]) and old_time.reactions_removed == [("🕘", guild.me.id)],
          "rebuilt offer answered and its 🕘 taken back")
    before = len(channel.sent)
    sp._tracked.clear()
    await click(old_time, "🕘", alex)
    check(len(channel.sent) == before, "rebuilt + used: not rebuilt again")

    # ---- expiry: the sweep takes back unused reactions and forgets old offers ----
    sp._tracked.clear()
    sp._cooldowns.clear()
    fresh = said(alex, "https://example.com/fresh")
    stale = said(alex, "https://example.com/stale")
    used = said(alex, "https://example.com/used")
    for msg in (fresh, stale, used):
        await sp.on_message_without_command(msg)
    await click(used, "📄", chris)
    removed_before = list(used.reactions_removed)
    day_ago = time.time() - sp_mod.TRACK_SECONDS - 60
    sp._tracked[stale.id]["at"] = day_ago
    sp._tracked[used.id]["at"] = day_ago
    await sp.sweep_offers()
    check(stale.reactions_removed == [("📄", guild.me.id)] and stale.id not in sp._tracked,
          "expired unused offer: 📄 taken back, forgotten")
    check(used.id not in sp._tracked and used.reactions_removed == removed_before,
          "expired used offer: just forgotten (its reaction was already taken back)")
    check(fresh.id in sp._tracked and not getattr(fresh, "reactions_removed", []), "fresh offer untouched")
    # the reminder loop runs the sweep every SWEEP_SECONDS
    sp._tracked[fresh.id]["at"] = day_ago
    sp._last_sweep = time.monotonic() - sp_mod.SWEEP_SECONDS - 1
    await sp.reminder_loop.coro(sp)
    check(fresh.reactions_removed == [("📄", guild.me.id)] and fresh.id not in sp._tracked,
          "the reminder loop sweeps expired offers")
    again = said(alex, "https://example.com/again")
    await sp.on_message_without_command(again)
    sp._tracked[again.id]["at"] = day_ago
    await sp.reminder_loop.coro(sp)
    check(again.id in sp._tracked, "…but not more often than every SWEEP_SECONDS")
    # a click on an expired tracked offer takes the reaction back and answers nothing
    before = len(channel.sent)
    await click(again, "📄", chris)
    check(len(channel.sent) == before and again.reactions_removed == [("📄", guild.me.id)]
          and again.id not in sp._tracked, "click after expiry: no answer, 📄 taken back")
    # a deleted message during the sweep is fine
    lost = said(alex, "https://example.com/lost")
    await sp.on_message_without_command(lost)
    lost.gone = True
    sp._tracked[lost.id]["at"] = day_ago
    await sp.sweep_offers()
    check(lost.id not in sp._tracked, "sweep tolerates deleted messages")
    # the memory cap never drops an unused offer before the sweep can take its reaction back
    sp._tracked = {k: {"kind": "link", "at": day_ago, "done": k % 2 == 0, "channel": channel.id, "guild": guild.id}
                   for k in range(sp_mod.MAX_TRACKED + 5)}
    sp._track(said(alex, "x"), {"kind": "link", "url": "https://example.com/x", "author": alex.id})
    check(all(not v.get("done") for k, v in sp._tracked.items() if v["at"] == day_ago),
          "the cap forgets used expired offers only")
    sp._tracked.clear()
    for name in ("SpeakUp", "ClaudeChat"):
        await bot.remove_cog(name)


async def stats_part(guild, bot, brad, alex, chris):
    general = guild.channel
    for m in guild.members:
        m.joined_at = datetime.now(timezone.utc) - timedelta(days=200)
    general.last_message_id = None
    st = stats_mod.ActivityStats(bot)
    await bot.add_cog(st)
    now = time.time()
    await st.config.guild(guild).started_at.set(int(now - 20 * 86400))
    rows = [(guild.id, general.id, 2, stats_mod.hour_of(now - d * 86400), 5) for d in range(1, 10)]
    rows += [(guild.id, general.id, 1, stats_mod.hour_of(now - d * 86400), 3) for d in range(1, 10)]
    await st.db.execute_many("INSERT INTO messages VALUES (?, ?, ?, ?, ?)", rows)

    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(general, content, author=author))
        await bot.invoke(ctx)
        return ctx

    # your own stats: DM + tick, nothing in the channel
    before = len(general.sent)
    ctx = await run(alex, "!stats me")
    dm = alex.dms[-1] if alex.dms else None
    text = card_text(dm) if dm else ""
    check(dm is not None and dm.flags.components_v2 and text.startswith("### 📊 Your stats")
          and "**45 messages**\n-# #1 in the server" in text.replace(",", "") and text.endswith("-# From Test Server"),
          text[-200:])
    check(no_pings(dm.kw.get("allowed_mentions")) if dm else False, "DM card is ping-free")
    check(len(general.sent) == before and ctx.message.id in TICKS, "!stats me: DM, ✅ tick, nothing in the channel")
    # DMs closed: posted here after all, with a note, and no tick
    alex.dms_closed = True
    ctx = await run(alex, "!stats me")
    alex.dms_closed = False
    sent = general.sent[-1] if len(general.sent) > before else None
    text = card_text(sent) if sent else ""
    check(sent is not None and text.startswith("### 📊 Your stats") and text.endswith("-# I couldn't DM you, so here it is.")
          and ctx.message.id not in TICKS, text[-120:])
    # staff looking at someone else: right here, Staff only
    dms_before = len(brad.dms)
    ctx = await bot.get_context(FakeMessage(general, "!stats me Alex", author=brad))
    await st.stats_me.callback(st, ctx, alex, None)
    text = card_text(general.sent[-1])
    check(text.startswith("### 📊 Alex's stats") and text.endswith("-# Staff only") and len(brad.dms) == dms_before
          and len(alex.dms) == 1, text[-120:])
    # members can't look at others
    ctx = await bot.get_context(FakeMessage(general, "!stats me", author=chris))
    await st.stats_me.callback(st, ctx, alex, None)
    check(general.sent[-1].content.startswith("🔒"), general.sent[-1].content)
    # a chart goes along with the DM card (the overview has one)
    ctx = await bot.get_context(FakeMessage(general, "!stats", author=alex))
    await st._send_private(ctx, await st.report_overview(alex, 7))
    dm = alex.dms[-1]
    gal = [i for i in dm.view.walk_children() if isinstance(i, discord.ui.MediaGallery)]
    f = dm.kw.get("file")
    check(f is not None and f.filename == "stats.png" and gal and gal[0].items[0].media.url == "attachment://stats.png",
          "chart file attached to the DM card")
    # ...and to the channel fallback, readable from the start again
    alex.dms_closed = True
    await st._send_private(ctx, await st.report_overview(alex, 7))
    alex.dms_closed = False
    f = general.sent[-1].kw.get("file")
    check(f is not None and f.fp.tell() == 0 and len(f.fp.read()) > 1000, "fallback card still carries the chart")
    await bot.remove_cog("ActivityStats")


async def claude_part(guild, bot, brad, alex, chris):
    channel = guild.channel
    cc = claude_mod.ClaudeChat(bot)
    await bot.add_cog(cc)
    await cc.config.member(alex).usage.set(dict(claude_mod.EMPTY_USAGE, requests=12, cost=1.234))
    await cc.config.guild(guild).usage.set(dict(claude_mod.EMPTY_USAGE, requests=20, cost=3.5))

    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        await bot.invoke(ctx)
        return ctx

    before = len(channel.sent)
    ctx = await run(alex, "!claude usage")
    text = card_text(alex.dms[-1]) if len(alex.dms) else ""
    check(text.startswith("### 🤖 AI usage: Alex\n**Requests** · 12") and text.endswith("\n-# From Test Server")
          and "Staff only" not in text and no_pings(alex.dms[-1].kw.get("allowed_mentions")), text)
    check(len(channel.sent) == before and ctx.message.id in TICKS, "!claude usage: DM + tick, nothing in the channel")
    alex.dms_closed = True
    ctx = await run(alex, "!claude usage")
    alex.dms_closed = False
    text = card_text(channel.sent[-1]) if len(channel.sent) > before else ""
    check(text.startswith("### 🤖 AI usage: Alex") and text.endswith("-# I couldn't DM you, so here it is.")
          and ctx.message.id not in TICKS, text[-150:])
    # staff views stay where they're asked
    dms = len(brad.dms)
    await run(brad, "!claude usage")
    text = card_text(channel.sent[-1])
    check(text.startswith("### 🤖 AI usage: Test Server") and text.endswith("\n-# Staff only") and len(brad.dms) == dms
          and "**Alex**\n-# 12 requests · $1.23" in text, "server totals: in the channel, a row per member")
    ctx = await bot.get_context(FakeMessage(channel, "!claude usage Alex", author=brad))
    await cc.claude_usage.callback(cc, ctx, alex)
    text = card_text(channel.sent[-1])
    check(text.startswith("### 🤖 AI usage: Alex") and text.endswith("Staff only") and len(brad.dms) == dms,
          "another member's usage: in the channel")
    # an admin naming themselves gets their own numbers privately
    ctx = await bot.get_context(FakeMessage(channel, "!claude usage Brad", author=brad))
    await cc.claude_usage.callback(cc, ctx, brad)
    check(len(brad.dms) == dms + 1 and card_text(brad.dms[-1]).startswith("### 🤖 AI usage: Brad"), "admin's own: DM")
    ctx = await bot.get_context(FakeMessage(channel, "!claude usage Brad", author=alex))
    await cc.claude_usage.callback(cc, ctx, brad)
    check(channel.sent[-1].content.startswith("🔒"), "members still can't see others' usage")
    await bot.remove_cog("ClaudeChat")


async def trivia_part(guild, bot, brad, alex):
    channel = guild.channel
    bf = bf_mod.Parlor(bot)
    await bot.add_cog(bf)
    questions = {f"Question {k}?": [f"Answer {k}"] for k in range(20)}
    bf_mod.write_trivia(DATA_DIR / "bb_quiet.yaml", {"AUTHOR": "x"}, questions)

    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        await bot.invoke(ctx)
        await asyncio.sleep(0.02)
        return ctx

    before, dms = len(channel.sent), len(brad.dms)
    ctx = await run(brad, "!maketrivia show quiet")
    board = brad.dms[-1] if len(brad.dms) > dms else None
    text = card_text(board) if board else ""
    check(text.startswith("### 🧠 bb_quiet\n**1.** Question 0?\n-# ||Answer 0||") and "nyone here" not in text
          and "Page 1 of 3" in text, text[:200])
    check(len(channel.sent) == before and ctx.message.id in TICKS, "trivia list: DM + tick, nothing in the channel")
    # paging works in the DM
    nxt = next(b for b in board.view.walk_children() if isinstance(b, discord.ui.Button) and str(b.emoji) == "▶️")
    from harness import FakeInteraction
    await nxt.callback(FakeInteraction(bot, guild, brad, board.channel, board))
    check("**9.** Question 8?" in card_text(board) and "Page 2 of 3" in card_text(board), "pages in the DM")
    # DMs closed: here, with the spoiler warning and the note
    brad.dms_closed = True
    ctx = await run(brad, "!maketrivia show quiet")
    brad.dms_closed = False
    text = card_text(channel.sent[-1]) if len(channel.sent) > before else ""
    check(text.startswith("### 🧠 bb_quiet") and " · 20 questions · anyone here can reveal the answers\n" in text
          and text.endswith("-# I couldn't DM you, so here it is.") and ctx.message.id not in TICKS, text[-200:])
    # the list of lists has no answers: it stays in the channel
    await run(brad, "!maketrivia show")
    check(card_text(channel.sent[-1]).startswith("### 🧠 Trivia lists"), "list of lists stays in the channel")
    await bot.remove_cog("Parlor")


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex = guild.add(2, "Alex")
    chris = guild.add(3, "Chris")
    guild.channel.name = "general"
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    await speakup_part(guild, bot, alex, chris)
    await stats_part(guild, bot, brad, alex, chris)
    await claude_part(guild, bot, brad, alex, chris)
    await trivia_part(guild, bot, brad, alex)


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
