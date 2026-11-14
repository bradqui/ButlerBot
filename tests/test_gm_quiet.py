"""
GameManager phase 4 ("less noise"): a game night is one card that updates itself, plus short ping lines that link
to it and are deleted afterwards. Also: votes from before Phase 4 (their own card) still finish, request results
are a one-line ping, sale alerts name each person once, LFG is one message.

Before Phase 4 a scheduled game night with a vote posted 7 messages, 5 of them pinging every player:
session card, timezone note, vote card (ping), "30 seconds left" (ping), winner (ping), 15-min reminder (ping),
start ping (ping).
"""
import asyncio
import types
from datetime import timedelta
from unittest.mock import MagicMock

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, card_color, card_text, discord, load
from gmcards import card_buttons, custom_ids

gm_mod = load("gamemanager", "gamemanager")
ui = gm_mod.ui
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


def pinged(kw) -> object:
    am = kw.get("allowed_mentions")
    if am is None:
        return "default"
    if am.everyone or am.roles:
        return "everyone/roles!"
    if am.users is False:
        return "none"
    if am.users is True:
        return "anyone mentioned"
    return sorted(u.id for u in am.users)


class Ctx:
    def __init__(self, guild, author):
        self.guild, self.author, self.channel = guild, author, guild.channel
        self.clean_prefix = "!"

    async def send(self, content=None, **kw):
        return await self.channel.send(content, **kw)


async def instant_sleep(seconds):
    await asyncio.sleep(0)


def http_error(cls, status):
    response = MagicMock(status=status, reason="test")
    return cls(response, "test")


async def main():
    guild = FakeGuild()
    brad, alex, sam = guild.add(1, "Brad"), guild.add(2, "Alex"), guild.add(3, "Sam")
    bot = TestBot(guild)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    channel = guild.channel
    dispatched = []
    bot.dispatch = lambda name, *args: dispatched.append((name, args))
    await gm.add_games(guild, brad, ["Rocket League", "Valorant", "Deadlock"], {"Rocket League": 252950})
    for m in (brad, alex, sam):
        await gm.change_library(guild, m, ["Rocket League", "Valorant"], "install")
    link_base = f"https://discord.com/channels/{guild.id}/{channel.id}/"

    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        await bot.invoke(ctx)
        await asyncio.sleep(0.01)

    def click(member, message):
        return FakeInteraction(bot, guild, member, channel, message=message)

    # ================= a full game night =================
    start_count = len(channel.sent)
    await run(brad, "!games session in 1h Raid night")   # Brad has no timezone of his own
    night = channel.sent[start_count:]
    sid, session = next(iter((await gm.config.guild(guild).play_sessions()).items()))
    card = channel.messages[session["message_id"]]
    link = link_base + str(card.id)
    check(len(night) == 1 and night[0] is card and ui.is_card(card), f"session: one message, the card ({len(night)})")
    check(":R> · time read as UTC\n" in card_text(card)
          and card_text(card).endswith("\n-# Wrong time? The host can set a timezone with `!games timezone <zone>`, "
                                       "then post it again"),
          f"timezone note folded into the card: short in the time block, the fix as the footer: {card_text(card)}")
    check(pinged(card.kw) == "none", "the card never pings")

    for m in (alex, sam):
        await gm.on_session_button(click(m, card), "join", sid)
    check(len(channel.sent) == start_count + 1, "joining only redraws the card")

    # ---- the vote, inside the card ----
    i = click(brad, card)
    await gm.on_session_button(i, "vote", sid)
    vid, vote = next(iter((await gm.config.guild(guild).votes()).items()))
    check(i.response.calls[-1][1] == "✅ Vote started." and i.response.calls[-1][2]["ephemeral"], "private ✅ for the host")
    check(vote["in_card"] and vote["message_id"] == card.id and vote["channel_id"] == channel.id,
          "the vote record points at the session card")
    vote_ping = channel.sent[-1]
    check(len(channel.sent) == start_count + 2, "starting the vote adds one message: its ping line")
    check(vote_ping.content == f"🗳️ <@1> <@2> <@3> Vote on what to play: {link}"
          and pinged(vote_ping.kw) == [1, 2, 3] and "\n" not in vote_ping.content,
          f"vote ping line: {vote_ping.content} {pinged(vote_ping.kw)}")
    text = card_text(card)
    check(card_color(card) == ui.ATTENTION and "🗳️ **Vote: what should we play?**\n-# Pick 1 · ends <t:" in text
          and "· 0 of 3 voted, waiting on Brad, Alex and Sam" in text, f"voting state: {text}")
    gids = vote["games"]
    check(custom_ids(card) == [f"gm:v:{vid}:{g}" for g in gids] + [f"gm:s:remove:{sid}", f"gm:s:end:{sid}"], custom_ids(card))
    check("time read as UTC" in text and "Wrong time?" not in text, "timezone note still shown before the start "
                                                                       "(short; a voting card has no footer)")

    await gm.on_vote_button(click(alex, card), vid, gids[0])
    await gm.on_vote_button(click(brad, card), vid, gids[0])
    check(len(channel.sent) == start_count + 2 and "2 of 3 voted, waiting on Sam" in card_text(card)
          and [b.label for b in card_buttons(card)][0] == f"{vote['names'][gids[0]]} · 2",
          "votes redraw the card and its tallies, no new messages")
    check(all(pinged(e) == "none" for e in card.edits), "no card edit pings")

    # The timer runs out (sleeps made instant): no "30 seconds left" message, just the result
    gm.vote_tasks.pop(vid).cancel()
    real_asyncio = gm_mod.asyncio
    gm_mod.asyncio = types.SimpleNamespace(sleep=instant_sleep, CancelledError=asyncio.CancelledError,
                                           current_task=asyncio.current_task, create_task=asyncio.create_task)
    try:
        await gm._vote_timer(guild.id, vid, gm_mod.utcnow() + timedelta(seconds=120))
    finally:
        gm_mod.asyncio = real_asyncio
    after_vote = channel.sent[start_count + 2:]
    check(not any("30 seconds" in (m.content or "") for m in channel.sent), "no 30-seconds-left message")
    check(len(after_vote) == 1, f"the result adds one message (the winner ping): {[m.content for m in after_vote]}")
    win = after_vote[-1]
    check(win.content == f"🏆 <@1> <@2> <@3> We're playing **{vote['names'][gids[0]]}**: {link}"
          and pinged(win.kw) == [1, 2, 3], f"winner ping line: {win.content}")
    check(vote_ping.id in channel.deleted, "the vote's ping line is deleted when the vote ends")
    text = card_text(card)
    check(card_color(card) == ui.SUCCESS and f"🏆 **{vote['names'][gids[0]]}** won the vote." in text
          and "🥇 **" in text and "2 votes (100%)" in text and "-# 2 of 3 voted · Time's up" in text,
          f"the result is in the card: {text}")
    check([b.label for b in card_buttons(card)] == ["Join", "Leave", "Start vote", "Add to calendar", "Edit",
                                                 "Remove player", "End session"],
          "normal buttons back after the vote")

    # ---- reminder and start ----
    s = (await gm.config.guild(guild).play_sessions())[sid]
    starts = gm_mod.parse_iso(s["starts_at"])
    await gm._tick_session(guild, sid, s, starts - timedelta(minutes=14))
    reminder = channel.sent[-1]
    check(reminder.content == f"🎮 <@1> <@2> <@3> **Raid night** starts {gm_mod.stamp(starts, 'R')}: {link}"
          and pinged(reminder.kw) == [1, 2, 3], f"reminder ping line: {reminder.content}")
    s = (await gm.config.guild(guild).play_sessions())[sid]
    await gm._tick_session(guild, sid, s, starts + timedelta(minutes=1))
    begin = channel.sent[-1]
    check(begin.content == f"🎮 <@1> <@2> <@3> **Raid night** is starting: {link}"
          and pinged(begin.kw) == [1, 2, 3], f"start ping line: {begin.content}")
    s = (await gm.config.guild(guild).play_sessions())[sid]
    check(s["pings"] == [win.id, reminder.id, begin.id], f"ping lines tracked on the session: {s['pings']}")
    check("time read as" not in card_text(card) and "Wrong time?" not in card_text(card),
          "timezone note gone once it has started")

    night = channel.sent[start_count:]
    ping_msgs = [m for m in night if pinged(m.kw) not in ("none", "default")]
    check(len(night) == 5 and len(ping_msgs) == 4, f"a game night: {len(night)} messages, {len(ping_msgs)} pings "
                                                   "(was 7 and 5)")
    check(all(len(m.content) < 200 and "\n" not in m.content for m in ping_msgs), "every ping is one short line")

    # ---- end: the pings are cleaned up, the card stays ----
    i = click(brad, card)
    await gm.on_session_button(i, "end", sid)
    check(all(m.id in channel.deleted for m in ping_msgs), "every ping line deleted when the session ends")
    left = [m for m in night if m.id in channel.messages]
    check(left == [card], f"only the card is left: {len(left)}")
    text = card_text(card)
    check(card_color(card) == ui.MUTED and "This session has ended." in text and "won the vote" in text
          and not card_buttons(card), text)
    check([d for d in dispatched if d[0] == "gm_session_ended"] and dispatched[-1][1][1]["id"] == sid,
          "gm_session_ended still dispatched (ActivityStats attendance)")

    # ================= ending a session mid-vote removes the vote's ping too =================
    await gm.create_session(Ctx(guild, alex), "Quick game")
    quick = max((await gm.config.guild(guild).play_sessions()).values(), key=lambda s: s["created_at"])
    qcard = channel.messages[quick["message_id"]]
    await gm.on_session_button(click(sam, qcard), "join", quick["id"])
    await gm.start_vote(Ctx(guild, alex), session_id=quick["id"])
    qping = channel.sent[-1]
    check(qping.content.startswith("🗳️ <@2> <@3> Vote on what to play"), qping.content)
    await gm.end_session(guild, quick["id"])
    check(qping.id in channel.deleted and not await gm.config.guild(guild).votes()
          and card_color(qcard) == ui.MUTED and "What should we play" not in card_text(qcard),
          "ending mid-vote: vote cancelled, its ping deleted, card ended")

    # ================= deleting tolerates gone messages and missing permissions =================
    await gm.create_session(Ctx(guild, alex), "Fragile night")
    frag = max((await gm.config.guild(guild).play_sessions()).values(), key=lambda s: s["created_at"])
    async with gm.config.guild(guild).play_sessions() as sessions:
        sessions[frag["id"]]["pings"] = [111, 222]
    errors = iter([http_error(discord.NotFound, 404), http_error(discord.Forbidden, 403)])

    class Broken:
        async def delete(self):
            raise next(errors)

    real_partial = channel.get_partial_message
    channel.get_partial_message = lambda mid: Broken() if mid in (111, 222) else real_partial(mid)
    try:
        ended = await gm.end_session(guild, frag["id"])
    finally:
        channel.get_partial_message = real_partial
    check(ended is not None and frag["id"] not in await gm.config.guild(guild).play_sessions(),
          "a ping already deleted (404) or not deletable (403) doesn't stop the session ending")

    # ================= a vote from before Phase 4 (its own card) still finishes =================
    await gm.create_session(Ctx(guild, brad), "Legacy night")
    legacy = max((await gm.config.guild(guild).play_sessions()).values(), key=lambda s: s["created_at"])
    lcard = channel.messages[legacy["message_id"]]
    await gm.on_session_button(click(alex, lcard), "join", legacy["id"])
    old_vote = {"id": "oldv1", "session_id": legacy["id"], "title": "Legacy night", "games": gids[:2],
                "names": {g: vote["names"].get(g, "Game") for g in gids[:2]}, "basis": "everyone has these installed",
                "tallies": {}, "user_votes": {}, "allowed_voters": ["1", "2"], "channel_id": channel.id,
                "message_id": None, "max_choices": 1, "created_at": gm_mod.utcnow().isoformat(), "created_by": "1",
                "ends_at": (gm_mod.utcnow() + timedelta(minutes=2)).isoformat(), "timeout": 120,
                "labels": {g: vote["names"].get(g, "Game") for g in gids[:2]}, "card": True}   # Phase 2/3 shape
    old_msg = await gm.send_card(channel, gm.vote_card(old_vote), allowed_mentions=gm_mod.pings(["1", "2"]))
    old_vote["message_id"] = old_msg.id
    async with gm.config.guild(guild).votes() as votes:
        votes["oldv1"] = dict(old_vote)
    async with gm.config.guild(guild).play_sessions() as sessions:
        sessions[legacy["id"]]["vote_id"] = "oldv1"
        legacy = dict(sessions[legacy["id"]])
    await gm.refresh_session_message(guild, legacy)
    check("Voting now: pick a game on the vote below." in card_text(lcard) and card_color(lcard) == ui.SUCCESS,
          "the session card points at the separate old vote card")
    await gm._resume_votes()
    check("oldv1" in gm.vote_tasks, "the old vote's timer resumes")
    await gm.on_vote_button(click(alex, old_msg), "oldv1", gids[0])
    check("**Voted (1/2):** <@2>" in card_text(old_msg) and "Voted (1/2)" not in card_text(lcard),
          "a press on the old vote card redraws that card, not the session")
    before = len(channel.sent)
    await gm.on_vote_button(click(brad, old_msg), "oldv1", gids[0])   # everyone voted
    check(card_text(old_msg).startswith("### 🗳️ Results: Legacy night") and card_color(old_msg) == ui.HIGHLIGHT
          and not card_buttons(old_msg), f"old vote card shows the results: {card_text(old_msg)}")
    new = channel.sent[before:]
    check(len(new) == 1 and new[0].content == f"🏆 <@1> <@2> We're playing **{old_vote['names'][gids[0]]}**: "
                                              f"{link_base}{old_msg.id}" and pinged(new[0].kw) == [1, 2],
          f"old vote: one winner ping line linking to its card: {[m.content for m in new]}")
    check(f"🏆 **{old_vote['names'][gids[0]]}** won the vote." in card_text(lcard)
          and "Voting now" not in card_text(lcard) and "oldv1" not in gm.vote_tasks, card_text(lcard))
    legacy = (await gm.config.guild(guild).play_sessions())[legacy["id"]]
    check(legacy["pings"] == [new[0].id], "the old vote's winner ping is tracked on its session")
    await gm.end_session(guild, legacy["id"])
    check(new[0].id in channel.deleted and old_msg.id in channel.messages, "…and deleted at the end (the card stays)")

    # an old vote cancelled: still the "Vote cancelled" card
    await gm.create_session(Ctx(guild, brad), "Legacy two")
    legacy2 = max((await gm.config.guild(guild).play_sessions()).values(), key=lambda s: s["created_at"])
    ov2 = dict(old_vote, id="oldv2", session_id=legacy2["id"])
    ov2_msg = await gm.send_card(channel, gm.vote_card(ov2))
    ov2["message_id"] = ov2_msg.id
    async with gm.config.guild(guild).votes() as votes:
        votes["oldv2"] = ov2
    await gm.cancel_vote(guild, "oldv2")
    check("Vote cancelled" in card_text(ov2_msg) and card_color(ov2_msg) == ui.MUTED, "old vote cancels as before")
    await gm.end_session(guild, legacy2["id"])

    # ================= game request results: a one-line ping linking to the card =================
    await gm.request_games_text(guild, channel, alex, ["Zork"], "own")
    await gm.request_games_text(guild, channel, sam, ["Myst"])
    reqs = {r["name"]: r for r in (await gm.config.guild(guild).game_requests()).values()}
    zcard = channel.messages[reqs["Zork"]["message_id"]]
    before = len(channel.sent)
    await gm.on_request_button(click(brad, zcard), "approve", reqs["Zork"]["id"])
    new = channel.sent[before:]
    check(len(new) == 1 and new[0].content == f"✅ <@2>, **Zork** was added to the server library: {link_base}{zcard.id}"
          and pinged(new[0].kw) == [2], f"approved: one line pinging the requester: {[m.content for m in new]}")
    check(card_text(zcard).startswith("### 🎮 Game request: Zork\n✅ **Approved**")
          and "-# It's in their library, not marked installed." in card_text(zcard), card_text(zcard))
    mcard = channel.messages[reqs["Myst"]["message_id"]]
    await gm.on_request_button(click(brad, mcard), "deny", reqs["Myst"]["id"])
    check(channel.sent[-1].content == f"❌ <@3>, your request for **Myst** was denied: {link_base}{mcard.id}"
          and pinged(channel.sent[-1].kw) == [3], channel.sent[-1].content)
    # a request whose card never got posted: the line carries the details itself
    async with gm.config.guild(guild).game_requests() as requests:
        requests["nocard"] = {"id": "nocard", "name": "Doom", "description": "", "requested_by": "3",
                              "requested_at": gm_mod.utcnow().isoformat(), "for_action": "install",
                              "channel_id": channel.id, "message_id": None, "steam_appid": None, "card": True}
    await gm.resolve_request(guild, "nocard", brad, approve=True)
    check(channel.sent[-1].content == "✅ <@3>, **Doom** was added to the server library.\n"
                                      "-# It's marked installed for them."
          and pinged(channel.sent[-1].kw) == [3], channel.sent[-1].content)

    # ================= sale alerts: each person named once =================
    async def fake_prices(appids):
        return {a: {"discount": 50, "final": 1999, "initial": 3999, "currency": "USD",
                    "final_text": "$19.99", "initial_text": "$39.99"} for a in appids}

    real_prices = gm_mod.steam_prices
    gm_mod.steam_prices = fake_prices
    try:
        async with gm.config.guild(guild).wishlist() as wishlist:
            wishlist["10"] = {"appid": 10, "name": "Game A", "users": ["2", "3"], "price": None, "alerted": 0}
            wishlist["20"] = {"appid": 20, "name": "Game B", "users": ["2"], "price": None, "alerted": 0}
            wishlist["30"] = {"appid": 30, "name": "Game C", "users": ["3", "2"], "price": None, "alerted": 0}
        await gm.config.guild(guild).sale_channel.set(channel.id)
        before = len(channel.sent)
        count = await gm.check_sales(guild)
    finally:
        gm_mod.steam_prices = real_prices
    alert = channel.sent[-1]
    text = card_text(alert)
    check(count == 3 and len(channel.sent) == before + 1, f"one alert card for three games: {count}")
    check(text.count("<@2>") == 1 and text.count("<@3>") == 1 and "-# Wanted by <@2>, <@3>" in text,
          f"each person listed once: {text}")
    check(all(g in text for g in ("Game A", "Game B", "Game C")) and pinged(alert.kw) == [2, 3],
          f"same people pinged: {pinged(alert.kw)}")

    # ================= LFG: still one short message =================
    before = len(channel.sent)
    await run(alex, "!games lfg Rocket League")
    new = channel.sent[before:]
    check(len(new) == 1 and new[0].content.startswith("🎮 <@2> wants to play **Rocket League**! <@1> <@3>")
          and pinged(new[0].kw) == "anyone mentioned" and len(new[0].content) < 300, f"LFG: {[m.content for m in new]}")

    # ================= ping_line keeps to one message =================
    many = [str(10 ** 18 + n) for n in range(150)]
    line = gm_mod.ping_line("🎮", many, "**Raid night** is starting", link)
    check(len(line) <= 2000 and line.endswith(f"is starting: {link}") and "more" in line and line.count("<@") <= 100,
          f"a huge session's ping still fits: {len(line)} chars, {line.count('<@')} mentions")

    for task in list(gm.vote_tasks.values()):
        task.cancel()
    await bot.remove_cog("GameManager")


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
