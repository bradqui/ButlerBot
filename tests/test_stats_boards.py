"""
UI phase 3 (boards), ActivityStats: every report is a paged card with its chart inside, charts read on both themes.
Also writes chart_line.png, chart_joins.png, chart_heatmap.png and light/dark composites of each to look at.
"""
import asyncio
import io
import json
import re
import time
from datetime import datetime, timedelta, timezone

from harness import (FakeChannel, FakeGuild, FakeInteraction, FakeMessage, TestBot, card_buttons, card_color,
                     card_text, discord, is_layout, load)
from PIL import Image

stats_mod = load("activitystats", "activitystats")
FakeMessage._state = None
ui = stats_mod.ui
results = []
DAY = 86400


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


def galleries(target):
    view = getattr(target, "view", target)
    return [i for i in view.walk_children() if isinstance(i, discord.ui.MediaGallery)]


def order(target):
    """The card's items in order, as kinds: text / image / row."""
    view = getattr(target, "view", target)
    container = next(c for c in view.children if isinstance(c, discord.ui.Container))
    kinds = []
    for item in container.children:
        kinds.append("image" if isinstance(item, discord.ui.MediaGallery) else
                     "text" if isinstance(item, discord.ui.TextDisplay) else
                     "row" if isinstance(item, discord.ui.ActionRow) else "sep")
    return kinds


def no_pings(am):
    return am is not None and not am.everyone and not am.users and not am.roles


def transparent_png(png: bytes):
    img = Image.open(io.BytesIO(png))
    check(img.mode == "RGBA", f"chart is RGBA ({img.mode})")
    alpha = img.getchannel("A")
    corner = alpha.getpixel((0, 0))
    hist = alpha.histogram()
    clear = hist[0] / sum(hist)
    return img, corner, clear, hist[255]


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex = guild.add(2, "Alex")
    for i in range(60):
        guild.add(100000000000000000 + i, f"Member{i}")
    for m in guild.members:
        m.joined_at = datetime.now(timezone.utc) - timedelta(days=200)
    general = guild.channel
    general.last_message_id = None
    extra = []
    for n in range(20):   # lots of channels: the channel list pages
        c = FakeChannel(guild, 700 + n)
        c.name, c.last_message_id = f"room-{n:02d}", None
        extra.append(c)
    for n in range(25):   # and channels nobody posts in: the dead-channel list pages
        c = FakeChannel(guild, 760 + n)
        c.name, c.last_message_id = f"old-{n:02d}", None
        extra.append(c)
    guild.text_channels += extra
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    st = stats_mod.ActivityStats(bot)
    await bot.add_cog(st)
    now = time.time()
    await st.config.guild(guild).started_at.set(int(now - 20 * DAY))   # tracking started 20 days ago
    rows = []
    for d in range(1, 19):
        for h in (9, 13, 20, 21):
            ts = stats_mod.hour_of(now - d * DAY) - 3600 * ((d * 5 + h) % 24)
            rows.append((guild.id, 500, 2, ts, (d % 5 + 1) * (3 if h >= 20 else 1)))
            rows.append((guild.id, 700 + d, 1, ts, d))
    await st.db.execute_many("INSERT INTO messages VALUES (?, ?, ?, ?, ?)", rows)
    await st.db.execute_many("INSERT INTO member_events VALUES (?, ?, ?, ?)",
                             [(guild.id, 900 + d, "join" if d % 3 else "leave", int(now - d * DAY)) for d in range(1, 30)])

    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(general, content, author=author))
        await bot.invoke(ctx)
        return general.sent[-1]

    # ---- a member report: a card, the chart inside it, the file attached ----
    sent = await run(alex, "!stats")
    text = card_text(sent)
    gal = galleries(sent)
    check(is_layout(sent.view) and not sent.embeds and not sent.content, "overview: a card, no embed or content")
    check(text.startswith("### 📊 Test Server: this week") and "<t:" not in text.split("\n")[0], text[:60])
    check(len(gal) == 1 and gal[0].items[0].media.url == "attachment://stats.png", "chart referenced by attachment")
    f = sent.kw.get("file")
    check(f is not None and f.filename == "stats.png", "chart file sent with the card")
    alt = gal[0].items[0].description if gal else ""
    check(alt and alt.startswith("Line chart of messages per day") and len(alt) <= 1024, alt)
    kinds = order(sent)
    blocks = kinds.index("image") - 1
    check(blocks >= 3 and kinds[:blocks + 2] == ["text"] * (blocks + 1) + ["image"],
          f"title, each fact its own block, then the chart: {kinds}")
    container = next(c for c in sent.view.children if isinstance(c, discord.ui.Container))
    facts = [c.content for c in container.children[1:blocks + 1]]
    check(facts[0] == "**230 messages**\n-# from 2 members · down 48% on the week before"
          and facts[1].startswith("**Busiest in <#500>**\n-# 139 messages · then <#")
          and all(f.startswith(("**", "-# ")) for f in facts),
          f"bold fact, small details: {facts}")
    check(not any(e in text for e in ("💬", "🔥", "🕘", "🔊", "🎮")), "no per-line emoji")
    check(text.rstrip().split("\n")[-1] == "-# More with !help stats", "overview footer: one pointer")
    check(card_color(sent) == ui.BRAND and not card_buttons(sent) and sent.view.timeout is None,
          "one page: brand color, no buttons, no timeout")
    check(no_pings(sent.kw.get("allowed_mentions")), "report: no pings")

    # ---- heatmap alt text ----
    sent = await run(alex, "!stats heatmap")
    alt = galleries(sent)[0].items[0].description
    check(alt.startswith("Heatmap of messages by weekday") and "busiest hour is" in alt, alt)

    # ---- the channel list: 15 channels, 8 a page; the tracking note joins the summary, not the rows ----
    sent = await run(brad, "!stats channels")
    board = sent.view
    check([len(p) for p in board.pages] == [8, 7], f"channel list: {[len(p) for p in board.pages]}")
    head = board.header or ""
    check(head.startswith("**") and "Tracking started" in head and not any("Tracking started" in r for p in board.pages
                                                                          for r in p), "coverage note in the summary")
    check(order(sent)[:5] == ["text", "text", "text", "image", "text"],
          f"title, summary blocks (the total, the note), chart, list: {order(sent)}")
    first = board.pages[0][0]
    check(re.fullmatch(r"\*\*<#\d+>\*\*\n-# [\d,]+ messages? · [\d.,]+ a day", first), first)
    check([str(b.emoji) for b in card_buttons(sent)] == ["◀️", "▶️"], "two pages: arrows")

    # ---- a long list pages with the arrows; paging keeps the same message ----
    sent = await run(brad, "!stats admin dead")
    labels = [str(b.emoji) for b in card_buttons(sent)]
    check(labels == ["◀️", "▶️"] and card_buttons(sent)[0].disabled, labels)
    check("-# Page 1 of 4 · Staff only" in card_text(sent) and sent.view.timeout == 900, "page footer, expires")
    i = FakeInteraction(bot, guild, alex, general, message=sent)
    await card_buttons(sent)[1].callback(i)
    edit = i.response.calls[-1]
    check(edit[0] == "edit" and "attachments" not in edit[1] and "Page 2 of 4" in card_text(sent),
          "▶ pages (anyone can), attachments untouched")
    check(no_pings(edit[1].get("allowed_mentions")), "paging: no pings")

    # ---- admin reports: staff footer; joins card ----
    sent = await run(brad, "!stats admin joins")
    text = card_text(sent)
    check(text.startswith("### 📊 Joins and leaves") and text.endswith("-# Staff only") and galleries(sent)
          and "joining and leaving" in galleries(sent)[0].items[0].description, text[-60:])

    # ---- quiet: long name lists become rows, never cutting a mention ----
    r = await st.report_quiet(guild)
    board, file = await st._report_card(r)
    all_rows = [row for page in board.pages for row in page]
    check(file is None and not galleries(board), "no chart, no file")
    check(all(len(row) <= stats_mod.ROW_ROOM for row in all_rows), [len(r) for r in all_rows])
    joined = "\n".join(all_rows)
    check(len(re.findall(r"<@\d+>", joined)) == len(re.findall(r"<@", joined)) == stats_mod.MAX_NAMES,
          "every mention whole")
    check("and 35 more" in joined and "Tracking started" in board.header, "the cap is kept")
    check(all_rows[0] == "**Went quiet: 0 members**\n-# 10+ messages 1–3 months ago, none in the last 30 days"
          and all_rows[1].startswith("**Silent for 30 days: 60 of 62 members**\n-# "), all_rows[:2])
    # _plain (the butler's text): one line per block, a row's details after a dash
    plain = st._plain(guild, r)
    check(plain.split("\n")[0] == "📊 Quiet members" and len(plain.split("\n")) == len(r.lines) + 1
          and plain.split("\n")[1] == "**Went quiet: 0 members** — 10+ messages 1–3 months ago, none in the last 30 days"
          and "<@" not in plain and "-# " not in plain, plain[:200])

    # ---- dead channels: 27 dead channels (capped at 30) page ----
    r = await st.report_dead_channels(guild, 30)
    board, _ = await st._report_card(r)
    check(len(r.lines) == 27 and len(board.pages) == 4 and board.title.startswith("📊"), len(r.lines))
    check(card_text(board).endswith("-# Page 1 of 4 · Staff only"), card_text(board)[-40:])
    check(re.fullmatch(r"\*\*<#\d+>\*\*\n-# (no posts seen|last post <t:\d+:R>)", board.pages[0][0]),
          board.pages[0][0])

    # ---- attendance: a session's "didn't show" names stay with it ----
    many = [100000000000000000 + i for i in range(40)]
    start = int(now - 2 * DAY)
    await st.db.query("INSERT INTO game_sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (guild.id, "s1", "Raid night", start, start + 3600, json.dumps(many), json.dumps(many[:3])))
    r = await st.report_attendance(guild)
    board, _ = await st._report_card(r)
    first = board.pages[0][0]
    check(first.startswith("**Raid night**") and "\n-# Didn't show:" in first and len(first) <= stats_mod.ROW_ROOM,
          first[:120])
    check(all(row.startswith(("**", "-# ")) for page in board.pages for row in page), "continuation rows stay small")

    # ---- nothing to show ----
    board, _ = await st._report_card(stats_mod.Report("📊 Empty"))
    check(card_text(board) == "### 📊 Empty\nNothing to show yet.", repr(card_text(board)))

    # ---- the weekly digest: a card in its channel, chart attached, no pings ----
    digest = FakeChannel(guild, 800)
    digest.name, digest.last_message_id = "staff-digest", None
    guild.text_channels.append(digest)
    await st.config.guild(guild).digest_channel.set(800)
    await st.config.guild(guild).digest_enabled.set(True)
    data = await st.config.guild(guild).all()
    await st._maybe_send_digest(guild, data, now=datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc))
    check(len(digest.sent) == 1, "digest sent")
    msg = digest.sent[-1]
    text = card_text(msg)
    check(is_layout(msg.view) and text.startswith("### 📊 Weekly digest:") and "<t:" not in text.split("\n")[0]
          and text.endswith("-# Staff only"), text[:60])
    check(no_pings(msg.kw.get("allowed_mentions")) and msg.kw.get("file") and galleries(msg), "digest: chart, no pings")

    # ---- charts: transparent background, legible type ----
    figs = []
    real_png = stats_mod._png

    def spy(fig):
        figs.append(fig)
        return real_png(fig)
    stats_mod._png = spy
    line_png = (await st.report_channels(brad, guild, 30)).chart()
    joins_png = (await st.report_joins(guild, 30)).chart()
    heat_png = (await st.report_heatmap(brad, None, 30)).chart()
    stats_mod._png = real_png
    for name, png in (("line", line_png), ("joins", joins_png), ("heatmap", heat_png)):
        img, corner, clear, solid = transparent_png(png)
        check(corner == 0 and clear > 0.4 and solid > 200, f"{name}: transparent background ({clear:.0%} clear)")
        check(img.width >= 800, f"{name}: {img.width}px wide")
        open(f"chart_{name}.png", "wb").write(png)
        for bg, label in (("#ffffff", "light"), ("#313338", "dark")):
            base = Image.new("RGBA", img.size, bg)
            base.alpha_composite(img)
            base.convert("RGB").save(f"chart_{name}_{label}.png")
    line_fig = figs[0]
    ax = line_fig.axes[0]
    sizes = [t.get_fontsize() for t in ax.get_xticklabels() + ax.get_yticklabels()]
    check(min(sizes) >= 11 and ax.yaxis.label.get_fontsize() >= 11, f"tick/label sizes {set(sizes)}")
    legend = ax.get_legend()
    check(legend is not None and min(t.get_fontsize() for t in legend.get_texts()) >= 11
          and len(legend.get_texts()) == stats_mod.MAX_CHART_SERIES, "legend: 4 lines, legible")
    check([l.get_color() for l in ax.get_lines()][:4] == stats_mod.CHART_COLORS, "palette order")
    check(not any(s.get_visible() for s in ax.spines.values()), "no spines")
    hax = figs[2].axes[0]
    check(min(t.get_fontsize() for t in hax.get_yticklabels()) >= 11
          and [t.get_text() for t in hax.get_yticklabels()] == stats_mod.WEEKDAYS, "heatmap weekday labels")
    await bot.remove_cog("ActivityStats")


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
