"""ActivityStats: tracking, reports, charts, privacy, the guide lookup, attendance and the digest."""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from harness import FakeChannel, FakeGuild, FakeMessage, TestBot, card_text, dcommands, discord, load

stats_mod = load("activitystats", "activitystats")
FakeMessage._state = None
results = []
DAY = 86400


def text_of(report):
    """A report's lines as the markdown its board shows (rows: main line, then a -# detail line)."""
    return "\n".join(stats_mod.ui.row_text(line) for line in report.lines)


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


class Private:
    """Permissions where the member can't see the channel."""
    view_channel = read_messages = False


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex = guild.add(2, "Alex")
    chris = guild.add(3, "Chris")
    dana = guild.add(4, "Dana")
    for m in guild.members:
        m.joined_at = datetime.now(timezone.utc) - timedelta(days=200)
    dana.joined_at = datetime.now(timezone.utc) - timedelta(days=20)
    general = guild.channel
    general.last_message_id = None
    staff = FakeChannel(guild, 501)
    staff.name, staff.last_message_id = "staff", None
    staff.permissions_for = lambda m: Private() if m.id == 2 else type(general).permissions_for(staff, m)
    old = FakeChannel(guild, 502)
    old.name = "old-news"
    old.last_message_id = discord.utils.time_snowflake(datetime.now(timezone.utc) - timedelta(days=60))
    voice = FakeChannel(guild, 600)
    voice.name, voice.members = "Lounge", []
    guild.text_channels += [staff, old]
    guild.voice_channels.append(voice)
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    st = stats_mod.ActivityStats(bot)
    await bot.add_cog(st)
    now = time.time()
    await st.config.guild(guild).started_at.set(int(now - 100 * DAY))

    # --- live tracking ---
    for author, channel in [(alex, general), (alex, general), (chris, general), (brad, staff)]:
        await st.on_message(FakeMessage(channel, "hi", author=author))
    bot_msg = FakeMessage(general, "beep", author=guild.me)
    guild.me.bot = True
    await st.on_message(bot_msg)
    check(sum(st._pending.values()) == 4, f"bots skipped, 4 pending: {st._pending}")
    await st.flush()
    rows = await st.db.query("SELECT channel, user, count FROM messages ORDER BY channel, user")
    check(rows == [(500, 2, 2), (500, 3, 1), (501, 1, 1)], f"counts saved: {rows}")

    # history: alex posted daily in #general for 60 days at 9 PM UTC; chris was active 40-80 days ago only
    hist = []
    for d in range(1, 61):
        hist.append((guild.id, 500, 2, stats_mod.hour_of(now - d * DAY), 5))
    for d in range(40, 80):
        hist.append((guild.id, 500, 4, stats_mod.hour_of(now - d * DAY), 1))
    await st.db.execute_many("INSERT INTO messages VALUES (?, ?, ?, ?, ?)", hist)

    # voice: alex and chris overlap in the lounge
    S = SimpleNamespace
    await st.on_voice_state_update(alex, S(channel=None), S(channel=voice))
    st._voice_open[(guild.id, alex.id)] = (600, now - 7200)
    await st.on_voice_state_update(chris, S(channel=None), S(channel=voice))
    st._voice_open[(guild.id, chris.id)] = (600, now - 3600)
    await st.on_voice_state_update(chris, S(channel=voice), S(channel=None))
    vrows = await st.db.query("SELECT user, end - start FROM voice")
    check(len(vrows) == 1 and vrows[0][0] == 3 and 3500 < vrows[0][1] < 3700, f"voice visit saved: {vrows}")

    # presence: a game started and stopped
    game = discord.Game("Deadlock")
    before = S(bot=False, id=2, guild=guild, activities=[])
    after = S(bot=False, id=2, guild=guild, activities=[game])
    await st.on_presence_update(before, after)
    st._games_open[(guild.id, 2, "Deadlock")] = now - 3 * 3600
    await st.on_presence_update(after, before)
    grows = await st.db.query("SELECT user, game FROM games")
    check(grows == [(2, "Deadlock")], f"game saved: {grows}")

    # joins/leaves, commands
    await st.on_member_join(alex)
    await st.on_member_remove(S(bot=False, id=77, guild=guild))
    ctx = S(guild=guild, author=alex, command=None, invoked_with="gmaes")
    await st.on_command_error(ctx, dcommands.CommandNotFound("x"))
    await st._record_command(guild, alex, "games own", True)
    await st._record_command(guild, alex, "games own", False)

    # --- reports for everyone ---
    r = await st.report_overview(alex, 7)
    text = text_of(r)
    check(r.lines[0][1].startswith("from 2 members") and "**Busiest in <#500>**" in text, text)
    check(all(isinstance(line, tuple) for line in r.lines[:3]) and "🔥" not in text and "💬" not in text,
          "overview: fact blocks, no per-line emoji")
    check(any(l[0].startswith("**Busiest on ") for l in r.lines if isinstance(l, tuple)), "busiest hour block")
    check(any(l[0].endswith(" in voice**") and "most played: Deadlock" in (l[1] or "") for l in r.lines
              if isinstance(l, tuple)), f"voice block names the top game: {text}")
    check("<#501>" not in text, "alex can't see #staff in the overview")
    png = r.chart()
    check(png[:4] == b"\x89PNG", "overview chart draws")
    r = await st.report_overview(brad, 7)
    check("<#501>" in text_of(r), "brad (can see #staff) gets it")

    r = await st.report_channels(alex, guild, 30)
    check(any(isinstance(l, tuple) and l[0] == "**<#500>**" and l[1].endswith(" a day") for l in r.lines)
          and r.chart()[:4] == b"\x89PNG", r.lines)
    r = await st.report_top(alex, None, 0)
    check(r.lines[0][0] == "**1. Alex** 🥇" and r.lines[0][1].endswith(" messages") and "<@" not in text_of(r),
          r.lines)
    r = await st.report_heatmap(alex, None, 30)
    check(r.lines[0][0].startswith("**Busiest on ") and "then " in r.lines[0][1] and "UTC time" in r.lines[0][1]
          and r.chart()[:4] == b"\x89PNG", r.lines)
    r = await st.report_voice(alex, 30)
    check("**Up to 2 people at once**" in text_of(r) and r.chart()[:4] == b"\x89PNG", r.lines)
    check(r.lines[r.rows_from] == ("**1. Alex** 🥇", "2.0 h in voice") and r.lines[0][0] == "**3.0 h in voice**",
          f"voice: total, then the people as ranked rows: {r.lines}")
    r = await st.report_games(alex, 30)
    check(r.lines[0] == ("**1. Deadlock** 🥇", "3.0 h · 1 player"), r.lines)
    r = await st.report_me(alex, alex, 30)
    text = text_of(r)
    check(r.lines[0][1].startswith("#1 in the server · ") and "all time" in r.lines[0][1] and "Deadlock" in text,
          text)
    check(r.title.startswith("📊 Your stats") and "**Most played: Deadlock**" in text, r.title)

    # --- admin reports ---
    r = await st.report_active(guild, 90)
    check(r.lines[2][0].endswith("active this month**") and "of 4 members" in r.lines[2][1]
          and r.chart()[:4] == b"\x89PNG", r.lines)
    r = await st.report_quiet(guild)
    text = text_of(r)
    check(r.lines[0][0] == "**Went quiet: 1 member**" and r.lines[1] == "<@4>", text)
    check("**Silent for 30 days: 1 of 4 members**" in text, "dana is also silent for 30 days")
    r = await st.report_joins(guild, 30)
    check(r.lines[0] == ("**1 joined, 1 left**", "net +0"), r.lines)
    r = await st.report_dead_channels(guild, 30)
    check(any(l[0] == "**<#502>**" for l in r.lines) and "<#500>" not in text_of(r), r.lines)
    r = await st.report_commands(guild, 30)
    text = text_of(r)
    check(("**`!games own`**", "2 uses · 1 failed") in r.lines and "`!gmaes` (1)" in text, text)
    check(r.lines[0][0] == "**2 commands run by members**", r.lines[0])
    r = await st.report_retention(guild, 90)
    text = text_of(r)
    check("**1 person joined**" in text and "**0 posted in their first week**" in text, text)

    # --- attendance via GameManager's event ---
    start = datetime.now(timezone.utc) - timedelta(minutes=90)
    session = {"id": "s1", "title": "Raid night", "created_at": (start - timedelta(hours=1)).isoformat(),
               "starts_at": start.isoformat(), "participants": ["2", "3", "1"]}
    await st.on_gm_session_ended(guild, session)
    r = await st.report_attendance(guild)
    text = text_of(r)
    check(r.lines[0][0] == "**Raid night**" and "2 of 3 showed up" in r.lines[0][1]
          and "\n-# Didn't show: <@1>" in text, text)

    # --- guide lookup ---
    out = await st.guide_call_tool("stats_report", {"report": "quiet", "target": "", "days": 0}, alex)
    check(out == "That report is for server admins only.", out)
    out = await st.guide_call_tool("stats_report", {"report": "me", "target": "Chris", "days": 0}, alex)
    check("only look up their own" in out, out)
    out = await st.guide_call_tool("stats_report", {"report": "top", "target": "general", "days": 0}, alex)
    check("**1. Alex** 🥇 — " in out and "<@" not in out and "-# " not in out, out)
    out = await st.guide_call_tool("stats_report", {"report": "overview", "target": "", "days": 0}, alex)
    lines = out.split("\n")
    check(lines[1].startswith("**") and " — from 2 members" in lines[1] and "**Busiest in #general** — " in out
          and "<#" not in out, f"_plain: one line per block, details after a dash: {out}")
    out = await st.guide_call_tool("stats_report", {"report": "channel", "target": "staff", "days": 7}, alex)
    check("No channel matches" in out, f"hidden channel refused: {out}")
    out = await st.guide_call_tool("stats_report", {"report": "attendance", "target": "", "days": 0}, brad)
    check("Raid night" in out and "UTC" in out, out)

    # --- commands ---
    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(general, content, author=author))
        await bot.invoke(ctx)
        return general.sent[-1]

    sent = await run(alex, "!stats")
    check(card_text(sent).startswith("### 📊") and "file" in sent.kw and not sent.embeds,
          "!stats posts a card + chart")
    sent = await run(alex, "!stats week")
    check("this week" in card_text(sent).split("\n")[0], card_text(sent)[:80])
    me_ctx = await bot.get_context(FakeMessage(general, "!stats me", author=chris))
    await st.stats_me.callback(st, me_ctx, alex, None)
    sent = general.sent[-1]
    check("only see your own" in (sent.content or ""), sent.content)
    sent = await run(brad, "!stats admin")
    check("### 📊 Admin stats" in card_text(sent) and not sent.embeds, "admin menu card")

    # --- privacy ---
    await run(alex, "!stats ignoreme")
    left = await st.db.query("SELECT COUNT(*) FROM messages WHERE user = 2")
    check(left[0][0] == 0 and 2 in st._ignored, "ignoreme deletes and stops tracking")
    await st.on_message(FakeMessage(general, "hi", author=alex))
    check(not any(k[2] == 2 for k in st._pending), "ignored user not counted")
    await run(alex, "!stats trackme")
    check(2 not in st._ignored, "trackme resumes")

    # --- unmet questions & digest ---
    await st.record_unmet(guild, chris, "how do I order pizza")
    r = await st.report_unmet(guild, 30)
    check(r.lines[0][0] == "**“how do I order pizza”**" and r.lines[0][1].startswith("Chris · <t:"), r.lines)
    await st.config.guild(guild).digest_channel.set(500)
    await st.config.guild(guild).digest_enabled.set(True)
    data = await st.config.guild(guild).all()
    monday_9 = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)  # a Monday
    before = len(general.sent)
    await st._maybe_send_digest(guild, data, now=monday_9 - timedelta(hours=1))
    check(len(general.sent) == before, "not due yet")
    await st._maybe_send_digest(guild, data, now=monday_9)
    check(len(general.sent) == before + 1 and "Weekly digest" in card_text(general.sent[-1]).split("\n")[0],
          "digest sent")
    data = await st.config.guild(guild).all()
    await st._maybe_send_digest(guild, data, now=monday_9 + timedelta(hours=3))
    check(len(general.sent) == before + 1, "only once per week")

    # --- charts to look at ---
    open("chart_channels.png", "wb").write((await st.report_channels(brad, guild, 60)).chart())
    open("chart_heatmap.png", "wb").write((await st.report_heatmap(brad, None, 60)).chart())

    # --- backfill: counts history before tracking started, once ---
    started = await st.config.guild(guild).started_at()
    old_msgs = [S(author=chris, webhook_id=None, created_at=datetime.fromtimestamp(started - 2 * DAY, timezone.utc))
                for _ in range(3)]

    async def history(limit=None, after=None, before=None):
        for m in old_msgs:
            if after < m.created_at < before:
                yield m
    general.history = history
    for c in (staff, old, voice):
        c.history = lambda **kw: history(after=datetime.max.replace(tzinfo=timezone.utc), before=None)
    status = await general.send("…")
    await st._backfill(guild, started - 5 * DAY, started, status)
    n = await st.db.query("SELECT SUM(count) FROM messages WHERE user = 3 AND hour < ?", (started,))
    check(n[0][0] == 3 and "Backfill done" in status.edits[-1]["content"], f"backfill counted 3: {n}")
    check(await st.config.guild(guild).backfilled_from() == int(started - 5 * DAY), "backfill start saved")

    check(stats_mod.parse_period("2 weeks") == 14 and stats_mod.parse_period("all") == 0
          and stats_mod.parse_period("soon") is None, "period parsing")
    await bot.remove_cog("ActivityStats")


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
