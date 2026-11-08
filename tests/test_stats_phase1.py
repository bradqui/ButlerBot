"""ActivityStats, style phase 1: digest title, joins colors, departed members, safe cuts, staff hint, wording."""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

from harness import FakeGuild, FakeMessage, TestBot, card_color, card_text, dcommands, discord, load

stats_mod = load("activitystats", "activitystats")
FakeMessage._state = None
ui = stats_mod.ui
results = []
DAY = 86400


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex = guild.add(2, "Alex")
    chris = guild.add(3, "Chris")
    for m in guild.members:
        m.joined_at = datetime.now(timezone.utc) - timedelta(days=200)
    general = guild.channel
    general.last_message_id = None
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    st = stats_mod.ActivityStats(bot)
    await bot.add_cog(st)
    now = time.time()
    await st.config.guild(guild).started_at.set(int(now - 100 * DAY))
    await st.db.execute_many("INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
                             [(guild.id, 500, 2, stats_mod.hour_of(now - d * DAY), 3) for d in range(1, 20)])

    # ---- weekly digest: plain dates in the title (timestamps don't render there) ----
    r = await st.report_digest(guild)
    week = datetime.fromtimestamp(now - 7 * DAY, timezone.utc).date()
    today = datetime.fromtimestamp(now, timezone.utc).date()
    expected = f"📊 Weekly digest: {week:%b} {week.day} – {today:%b} {today.day}"
    check("<t:" not in r.title and r.title == expected, r.title)
    board, _ = await st._report_card(r)
    check(card_text(board).endswith("-# Staff only") and card_color(board) == ui.BRAND,
          "admin report: brand color + staff hint")

    # ---- member reports: no staff hint; footers combine ----
    r = await st.report_overview(alex, 7)
    board, _ = await st._report_card(r, footer="More: …")
    check(card_text(board).endswith("\n-# More: …") and card_color(board) == ui.BRAND, card_text(board)[-40:])
    r = await st.report_active(guild, 90)
    board, _ = await st._report_card(r, footer="extra")
    check(card_text(board).endswith("\n-# Staff only · extra"), card_text(board)[-40:])

    # ---- joins chart: joined green, left red ----
    captured = {}
    real_chart = stats_mod.daily_chart

    def spy(days, series, ylabel, colors=None):
        captured.update(series=list(series), colors=colors)
        return real_chart(days, series, ylabel, colors=colors)
    stats_mod.daily_chart = spy
    r = await st.report_joins(guild, 30)
    png = r.chart()
    stats_mod.daily_chart = real_chart
    check(captured["series"] == ["Joined", "Left"] and captured["colors"] == [stats_mod.CHART_GOOD, stats_mod.CHART_BAD]
          and stats_mod.CHART_GOOD == "#3ba55c" and stats_mod.CHART_BAD == "#ed4245"
          and png[:4] == b"\x89PNG", captured)

    # ---- one wording for periods ----
    check(r.title == "📊 Joins and leaves: this month", r.title)
    check((await st.report_commands(guild, 7)).title == "📊 Command usage: this week", "commands title")
    check((await st.report_active(guild, 90)).title == "📊 Active members: last 90 days", "active title")

    # ---- channel report: the name isn't repeated ----
    r = await st.report_channel(alex, 500, 30)
    check(r.title.startswith("📊 #general") and r.lines[0][0] == "**57 messages**"
          and "<#500>" not in r.lines[0][1], r.lines[0])

    # ---- retention: 🔥 only means "busiest" ----
    r = await st.report_retention(guild, 365)
    check(not any("🔥" in ui.row_text(l) for l in r.lines), r.lines)

    # ---- attendance: people who left aren't shown as @unknown-user ----
    start = int(now - 5 * DAY)
    for sid, showed in (("s1", [2]), ("s2", [2])):
        await st.db.query("INSERT INTO game_sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (guild.id, sid, f"Night {sid}", start, start + 3600, json.dumps([2, 3, 88]),
                           json.dumps(showed)))
    r = await st.report_attendance(guild)
    text = "\n".join(ui.row_text(l) for l in r.lines)
    check("\n-# Didn't show: <@3>, 1 person who left the server" in text and "<@88>" not in text, text)
    at = next(i for i, l in enumerate(r.lines) if l[0] == "**Show-up rates**")
    rates = r.lines[at + 1:]
    check(rates == [("**Alex**", "showed up 100% of the time · joined 2"),
                    ("**Chris**", "showed up 0% of the time · joined 2")], rates)
    check(st._names_or_departed(guild, [88, 89]) == "2 people who left the server", "only departed")
    await st.record_unmet(guild, guild.add(77, "Temp"), "how do I fly")
    guild.members = [m for m in guild.members if m.id != 77]
    r = await st.report_unmet(guild, 30)
    check(r.lines[0][0] == "**“how do I fly”**" and r.lines[0][1].startswith("A former member · ")
          and "<@77>" not in ui.row_text(r.lines[0]), r.lines)

    # ---- long reports page instead of being cut; no line is cut in half ----
    long = stats_mod.Report("📊 Long", lines=[f"line {i:03d} " + "x" * 60 for i in range(100)])
    board, _ = await st._report_card(long)
    shown = []
    for page in board.pages:
        shown.extend(page)
    check(len(board.pages) == 13 and shown == long.lines and len(card_text(board)) <= 4000,
          f"paged, nothing cut ({len(board.pages)} pages)")
    rows = stats_mod.Report("📊 Rows", lines=[ui.row(f"**Item {i}**", f"{i} things") for i in range(20)], rows_from=0)
    board, _ = await st._report_card(rows)
    check(board.pages[0][0] == "**Item 0**\n-# 0 things" and len(board.pages) == 3,
          "tuple rows: a bold main line, the details small underneath, 8 a page")

    # ---- status lines ----
    ctx = await bot.get_context(FakeMessage(general, "!stats soonish", author=alex))
    try:
        await stats_mod.Period().convert(ctx, "soonish")
        check(False, "bad period raises")
    except dcommands.BadArgument as e:
        check(str(e).startswith("❓ `soonish` isn't a time period."), str(e))
    ctx = await bot.get_context(FakeMessage(general, "!stats me", author=chris))
    await st.stats_me.callback(st, ctx, alex, None)
    check(general.sent[-1].content.startswith("🔒 "), general.sent[-1].content)
    ctx = await bot.get_context(FakeMessage(general, "!x", author=brad))
    await st.digest_time.callback(st, ctx, "someday", "9am")
    check(general.sent[-1].content.startswith("❓ "), general.sent[-1].content)
    await st.stats_admin.callback(st, await bot.get_context(FakeMessage(general, "!stats admin", author=brad)))
    menu = general.sent[-1]
    check(card_text(menu).endswith("-# Staff only") and card_color(menu) == ui.BRAND, "admin menu: staff hint")
    container = next(c for c in menu.view.children if isinstance(c, discord.ui.Container))
    blocks = [c.content for c in container.children if isinstance(c, discord.ui.TextDisplay)][1:-1]
    check(len(blocks) == 15 and blocks[0] == "`!stats admin active [period]`\n-# Daily, weekly and monthly active members"
          and all("\n-# " in b for b in blocks) and "[p]" not in card_text(menu),
          f"admin menu: one block per command, its use underneath: {blocks[:2]}")
    await st.admin_digest.callback(st, await bot.get_context(FakeMessage(general, "!stats admin digest", author=brad)))
    card = general.sent[-1]
    text = card_text(card)
    check(text.startswith("### 📊 Digest settings\n**Weekly digest** · Off\n**Channel** · not set")
          and text.endswith("-# Staff only") and card_color(card) == ui.BRAND, text)
    ctx = await bot.get_context(FakeMessage(general, "!x", author=brad))
    await st.digest_on.callback(st, ctx)
    check(general.sent[-1].content == "⚠️ Pick a channel for the digest first.\n"
                                      "-# `!stats admin digest channel #channel`", general.sent[-1].content)
    await st.stats_ignoreme.callback(st, ctx)
    check(general.sent[-1].content == "✅ I've stopped tracking you and deleted your stats.\n"
                                      "-# `!stats trackme` turns tracking back on.", general.sent[-1].content)
    await st.stats_trackme.callback(st, ctx)
    r = await st.report_games(alex, 30)
    check(stats_mod.ui.plural(1, "player") == "1 player", "plural helper")

    # ---- times say whose timezone they're in ----
    from zoneinfo import ZoneInfo

    async def timezone_for(member):
        return ZoneInfo("America/New_York"), "America/New_York", member.id == alex.id
    fake_gm = type("GM", (), {"timezone_for": staticmethod(timezone_for)})()
    real_get_cog = bot.get_cog
    bot.get_cog = lambda name: fake_gm if name == "GameManager" else real_get_cog(name)
    r = await st.report_overview(alex, 7)
    block = next(l for l in r.lines if l[0].startswith("**Busiest on "))
    check(block[1] == "your timezone", block)
    r = await st.report_me(brad, alex, 30)
    block = next(l for l in r.lines if l[0].startswith("**Usually around "))
    check(block[1].endswith(" · America/New_York time") and "your" not in block[1],
          f"staff looking at someone else's: the zone's name: {block}")
    r = await st.report_overview(brad, 7)
    block = next(l for l in r.lines if l[0].startswith("**Busiest on "))
    check(block[1] == "America/New_York time", f"a server timezone isn't \"yours\": {block}")
    bot.get_cog = real_get_cog
    r = stats_mod.Report("📊 T", lines=[ui.row("**A\\_b**", "c\\*d"), "plain <@2>"])
    check(st._plain(guild, r) == "📊 T\n**A_b** — c*d\nplain Alex", st._plain(guild, r))
    await bot.remove_cog("ActivityStats")


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
