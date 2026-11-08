import asyncio
import re
from datetime import datetime, timedelta, timezone

from harness import (FakeChannel, FakeGuild, FakeInteraction, FakeMessage, TestBot, card_buttons, card_text, discord,
                     load)

from gmcards import card_buttons  # noqa: E402  (unwraps DynamicItem buttons)
gm_mod = load("gamemanager", "gamemanager")
from zoneinfo import ZoneInfo  # noqa: E402

FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


class Ctx:
    def __init__(self, guild, author):
        self.guild, self.author, self.channel = guild, author, guild.channel
        self.clean_prefix = "!"

    async def send(self, content=None, **kw):
        return await self.channel.send(content, **kw)


def pure_tests():
    games = {g["id"]: g for g in [
        {"id": "a1", "name": "Halo Infinite"}, {"id": "a2", "name": "Halo: MCC"},
        {"id": "a3", "name": "Rocket League"}, {"id": "a4", "name": "Counter-Strike 2"}]}
    r = gm_mod.resolve_game
    check(r(games, "rocket league")[0]["id"] == "a3", "exact, case-insensitive")
    check(r(games, "Rocket")[0]["id"] == "a3", "unique partial")
    g, cands = r(games, "Halo")
    check(g is None and {c["id"] for c in cands} == {"a1", "a2"}, "ambiguous partial gives candidates")
    check(r(games, "counterstrike 2")[0]["id"] == "a4", "punctuation-insensitive exact")
    check(r(games, "Minecraft") == (None, []), "unknown")

    p = gm_mod.parse_game_names
    check(p("Assassin's Creed, Baldur's Gate 3") == ["Assassin's Creed", "Baldur's Gate 3"], "apostrophes aren't quotes")
    check(p('"Warhammer 40,000: Darktide", Halo') == ["Warhammer 40,000: Darktide", "Halo"], "quoted names with commas")
    check(p("A\nB\n\n C ") == ["A", "B", "C"], "one per line")
    check(p("Warhammer 40,000: Space Marine 2, Halo") == ["Warhammer 40,000: Space Marine 2", "Halo"],
          "thousands comma stays in the name")
    check(p("Halo 3,Portal 2, Deadlock") == ["Halo 3", "Portal 2", "Deadlock"], "other commas split")
    check(p("Papers, Please\nWarhammer 40,000: Darktide") == ["Papers, Please", "Warhammer 40,000: Darktide"],
          "lines keep their commas")

    d = gm_mod.parse_duration
    check((d("90"), d("3m"), d("1h"), d("45s"), d("abc")) == (90, 180, 3600, 45, None), "durations")

    tz = ZoneInfo("America/Chicago")
    now = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)  # Tuesday, 12:00 in Chicago
    sw = gm_mod.split_when
    when, title = sw("friday 9pm Raid night", tz, now)
    check(when == datetime(2026, 11, 6, 21, 0, tzinfo=tz) and title == "Raid night", f"friday 9pm -> {when} {title!r}")
    when, title = sw("9:30 pm Rocket League", tz, now)
    check(when == datetime(2026, 11, 3, 21, 30, tzinfo=tz) and title == "Rocket League", f"9:30 pm today -> {when}")
    when, _ = sw("9am", tz, now)
    check(when == datetime(2026, 11, 4, 9, 0, tzinfo=tz), f"past time rolls to tomorrow -> {when}")
    when, _ = sw("tuesday 9am", tz, now)
    check(when == datetime(2026, 11, 10, 9, 0, tzinfo=tz), f"past weekday time rolls a week -> {when}")
    when, _ = sw("today 9am", tz, now)
    check(when == datetime(2026, 11, 3, 9, 0, tzinfo=tz), "explicit today stays (caller rejects past)")
    when, title = sw("in 1h30m Halo", tz, now)
    check(when == now + timedelta(minutes=90) and title == "Halo", "in 1h30m")
    when, title = sw("in 2 hours", tz, now)
    check(when == now + timedelta(hours=2) and title == "", "in 2 hours")
    when, _ = sw("tomorrow 8:30pm", tz, now)
    check(when == datetime(2026, 11, 4, 20, 30, tzinfo=tz), "tomorrow 8:30pm")
    when, _ = sw("11/14 7pm LAN", tz, now)
    check(when == datetime(2026, 11, 14, 19, 0, tzinfo=tz), "11/14 7pm")
    when, _ = sw("9pm fri", tz, now)
    check(when == datetime(2026, 11, 6, 21, 0, tzinfo=tz), "9pm fri")
    for title_only in ("Friday Night Raid", "Halo 3", "Tomorrow Never Dies", "Raid night"):
        check(sw(title_only, tz, now) == (None, title_only), f"no time in {title_only!r}")
    check(sw("<t:1800000000:F> big game", tz, now)[0] == datetime.fromtimestamp(1800000000, timezone.utc),
          "discord timestamp")

    ft = gm_mod.find_timezone
    check((ft("CST"), ft("chicago"), ft("America/New_York"), ft("Europe/Berlin"), ft("nowhere")) ==
          ("America/Chicago", "America/Chicago", "America/New_York", "Europe/Berlin", None), "timezones")

    data = {"owned": [], "installed": [], "ranks": {}}
    ac = gm_mod.apply_change
    check(ac(data, "x", "install") and data["owned"] == ["x"] and data["installed"] == ["x"], "install implies own")
    check(not ac(data, "x", "install"), "install twice is unchanged")
    data["ranks"]["x"] = 1
    check(ac(data, "x", "unown") and data == {"owned": [], "installed": [], "ranks": {}}, "unown clears everything")

    for action, sid in (("join", "abc123de"), ("vote", "zz99yy88")):
        b = gm_mod.SessionButton(action, sid)
        check(re.fullmatch(gm_mod.SessionButton.__discord_ui_compiled_template__, b.custom_id), f"template {action}")
    check(re.fullmatch(gm_mod.VoteButton.__discord_ui_compiled_template__, gm_mod.VoteButton("v1", "g1", "X").custom_id),
          "vote template")


async def flow_tests():
    guild = FakeGuild()
    brad = guild.add(1, "Brad")       # bot owner -> game admin
    alex = guild.add(2, "Alex")
    sam = guild.add(3, "Sam")
    bot = TestBot(guild)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    channel = guild.channel

    added, existing = await gm.add_games(guild, brad, ["Rocket League", "Halo Infinite", "Halo: MCC", "Valorant",
                                                       "rocket league"])
    check(added == ["Rocket League", "Halo Infinite", "Halo: MCC", "Valorant"] and existing == ["Rocket League"],
          "add_games dedupes")
    games = await gm.config.guild(guild).games()
    ids = {g["name"]: gid for gid, g in games.items()}

    embed, unknown = await gm.change_library(guild, alex, ["rocket league", "Halo", "Minecraft"], "install")
    check(unknown == ["Minecraft"], "unknown game reported")
    check("Which one?" in embed.description and "Marked installed" in embed.description, embed.description)
    users = await gm.config.guild(guild).users()
    check(ids["Rocket League"] in users["2"]["owned"] and ids["Rocket League"] in users["2"]["installed"],
          "alex installed+owns RL")

    # Text command through the real discord.py command machinery
    async def run(author, content):
        msg = FakeMessage(channel, content, author=author)
        ctx = await bot.get_context(msg)
        check(ctx.valid, f"command parses: {content}")
        await bot.invoke(ctx)
        return channel.sent[-1] if channel.sent else None

    await run(brad, "!games install Rocket League, Valorant")
    users = await gm.config.guild(guild).users()
    check(set(users["1"]["installed"]) == {ids["Rocket League"], ids["Valorant"]}, "brad installs via command")
    await run(sam, "!games own Valorant")
    await run(sam, "!games setrank 1 valorant")
    users = await gm.config.guild(guild).users()
    check(users["3"]["ranks"] == {ids["Valorant"]: 1}, "rank via command")

    # Unknown-game button: Alex (not admin, member_add off) requests Minecraft
    before = len(channel.sent)
    out = await run(alex, "!games install Minecraft")
    view = out.kw.get("view")
    check(isinstance(view, gm_mod.UnknownGamesView) and not view.can_add, "request button offered to member")
    inter = FakeInteraction(bot, guild, alex, channel, message=out)
    await card_buttons(view)[0].callback(inter)
    reqs = await gm.config.guild(guild).game_requests()
    check(len(reqs) == 1 and list(reqs.values())[0]["for_action"] == "install", "request created with action")
    req_msg = channel.sent[-1]
    check(req_msg.kw.get("view") is not None and "Game request" in card_text(req_msg), "approval message posted")

    # Alex can't approve; Brad can, and Alex ends up with it installed
    rid = list(reqs)[0]
    i1 = FakeInteraction(bot, guild, alex, channel, message=req_msg)
    await gm.on_request_button(i1, "approve", rid)
    check(i1.response.calls[0][0] == "send" and "Only game admins" in i1.response.calls[0][1], "member can't approve")
    i2 = FakeInteraction(bot, guild, brad, channel, message=req_msg)
    await gm.on_request_button(i2, "approve", rid)
    games = await gm.config.guild(guild).games()
    mc = next(g for g, v in games.items() if v["name"] == "Minecraft")
    users = await gm.config.guild(guild).users()
    check(mc in users["2"]["installed"], "approval installs for requester")
    check(req_msg.edits and not [b for b in card_buttons(req_msg.edits[-1]["view"]) if not b.url]
          and "Game request: Minecraft\n✅ **Approved**" in card_text(req_msg), "request buttons removed after approval")

    # Game admin check is visible to the guide and blocks members
    admin_add = bot.get_command("games admin add")
    labels = [getattr(c, "requirement", None) for c in admin_add.parent.checks]
    check("game admin" in labels, "game admin check carries a label")
    msg = FakeMessage(channel, "!games admin add Foo", author=alex)
    ctx = await bot.get_context(msg)
    try:
        ok = await admin_add.can_run(ctx, check_all_parents=True)
    except Exception as e:
        ok = type(e).__name__
    check(ok == "UserFeedbackCheckFailure", f"member blocked from admin add: {ok}")

    # Sessions
    await run(brad, "!games session Rocket night")
    sessions = await gm.config.guild(guild).play_sessions()
    sid, session = next(iter(sessions.items()))
    smsg = channel.messages[session["message_id"]]
    check(session["title"] == "Rocket night" and smsg.kw.get("view") is not None, "session posted with buttons")

    def click(member, message):
        return FakeInteraction(bot, guild, member, channel, message=message)

    await gm.on_session_button(click(alex, smsg), "join", sid)
    i = click(alex, smsg)
    await gm.on_session_button(i, "join", sid)
    check("already in" in i.response.calls[0][1], "double join rejected")
    i = click(brad, smsg)
    await gm.on_session_button(i, "leave", sid)
    check("host" in i.response.calls[0][1], "host can't leave")
    i = click(alex, smsg)
    await gm.on_session_button(i, "vote", sid)
    check("Only the host" in i.response.calls[0][1], "non-host can't start vote")

    i = click(brad, smsg)
    await gm.on_session_button(i, "vote", sid)
    votes = await gm.config.guild(guild).votes()
    check(len(votes) == 1, "vote started")
    vid, vote = next(iter(votes.items()))
    check(vote["games"] == [ids["Rocket League"]] and vote["basis"].startswith("everyone has"),
          f"candidates: installed by all -> {vote['names']}")
    vmsg = channel.messages[vote["message_id"]]
    check(gm.vote_tasks.get(vid) is not None, "vote timer scheduled")

    i = click(sam, vmsg)
    await gm.on_vote_button(i, vid, ids["Rocket League"])
    check("Only players" in i.response.calls[0][1], "non-player can't vote")
    await gm.on_vote_button(click(brad, vmsg), vid, ids["Rocket League"])
    i = click(brad, vmsg)
    await gm.on_vote_button(i, vid, ids["Rocket League"])
    check("Took back" in i.response.calls[0][1], "toggle vote off")
    votes = await gm.config.guild(guild).votes()
    check(votes[vid]["tallies"] == {} and votes[vid]["user_votes"] == {}, "no zero tallies left behind")
    await gm.on_vote_button(click(brad, vmsg), vid, ids["Rocket League"])
    await gm.on_vote_button(click(alex, vmsg), vid, ids["Rocket League"])   # everyone voted -> finish
    check(not await gm.config.guild(guild).votes(), "vote finished when everyone voted")
    check(vid not in gm.vote_tasks, "timer cleared")
    win = [m for m in channel.sent if m.content and m.content.startswith("🏆")]
    check(win and "We're playing **Rocket League**" in win[-1].content, "winner announced (a short ping line)")
    session = (await gm.config.guild(guild).play_sessions())[sid]
    check(session["vote_id"] is None and session["winner"] == "Rocket League", "session updated after vote")
    check(vmsg is smsg and "🏆 **Rocket League** won the vote." in card_text(smsg) and "🥇" in card_text(smsg),
          "the session card shows the results (the vote ran inside it)")

    # Fallback candidates + tie broken by ranks: Sam joins (only owns Valorant)
    await gm.on_session_button(click(sam, smsg), "join", sid)
    await gm.change_library(guild, alex, ["Valorant"], "install")
    await gm.change_library(guild, sam, ["Valorant"], "unown")       # Sam shares nothing with the others
    await gm.change_library(guild, sam, ["Halo: MCC"], "own")
    await run(brad, "!games setrank 1 Valorant")                      # Brad's favorite breaks the tie
    await gm.start_vote(Ctx(guild, brad), session_id=sid, max_choices=1, seconds=120)
    vid2, vote2 = next(iter((await gm.config.guild(guild).votes()).items()))
    check(vote2["basis"].startswith("nobody") and set(vote2["games"]) == {ids["Rocket League"], ids["Valorant"]},
          f"fallback to most-installed: {vote2['basis']} {vote2['names']}")
    v2msg = channel.messages[vote2["message_id"]]
    await gm.on_vote_button(click(brad, v2msg), vid2, ids["Valorant"])
    await gm.on_vote_button(click(alex, v2msg), vid2, ids["Rocket League"])
    winner = await gm.finish_vote(guild, vid2, "test")
    check(winner == "Valorant", f"tie broken by Brad's rank of Valorant -> {winner}")
    check("tie, broken by everyone's game rankings" in card_text(smsg), "tie note in the session card")

    # Ending the session removes its buttons
    await run(brad, "!games endsession")
    check(not await gm.config.guild(guild).play_sessions() and not card_buttons(smsg)
          and "This session has ended." in card_text(smsg), "session ended")

    # Scheduled session reminders
    now = datetime.now(timezone.utc)
    await gm.create_session(Ctx(guild, alex), "in 1h Valorant scrims")
    sid3, s3 = next(iter((await gm.config.guild(guild).play_sessions()).items()))
    check(s3["title"] == "Valorant scrims" and not gm_mod.sent_leads(s3), "scheduled session")
    check("time read as UTC" in card_text(channel.sent[-1]) and not channel.sent[-1].content,
          "timezone note for users without one (in the card, not a message of its own)")
    await gm._tick_session(guild, sid3, s3, now + timedelta(minutes=50))
    s3 = (await gm.config.guild(guild).play_sessions())[sid3]
    check(15 in gm_mod.sent_leads(s3) and "starts" in channel.sent[-1].content, "15-minute reminder")
    await gm._tick_session(guild, sid3, s3, now + timedelta(minutes=61))
    s3 = (await gm.config.guild(guild).play_sessions())[sid3]
    check(s3["started"] and "**Valorant scrims** is starting" in channel.sent[-1].content, "start ping")
    await gm._tick_session(guild, sid3, s3, now + timedelta(hours=14))
    check(sid3 not in await gm.config.guild(guild).play_sessions(), "stale session expires")

    # Votes resume after reload: an overdue vote finishes on load
    await gm.create_session(Ctx(guild, brad), "Resume test")
    sid4 = next(iter(await gm.config.guild(guild).play_sessions()))
    await gm.on_session_button(click(alex, channel.messages[(await gm.config.guild(guild).play_sessions())[sid4]["message_id"]]), "join", sid4)
    await gm.start_vote(Ctx(guild, brad), session_id=sid4)
    vid4 = next(iter(await gm.config.guild(guild).votes()))
    gm.vote_tasks.pop(vid4).cancel()
    async with gm.config.guild(guild).votes() as v:
        v[vid4]["ends_at"] = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    await gm._resume_votes()
    await asyncio.sleep(0.05)
    check(not await gm.config.guild(guild).votes(), "overdue vote finished on resume")

    # sessionvote argument parsing: "2 3m"
    calls = []
    orig = gm.start_vote

    async def fake_start(target, session_id=None, max_choices=1, seconds=120):
        calls.append((session_id, max_choices, seconds))
    gm.start_vote = fake_start
    await run(brad, "!games vote 2 3m")
    await run(brad, "!games sessionvote 60")
    gm.start_vote = orig
    check(calls == [(None, 2, 180), (None, 1, 60)], f"vote args parsed: {calls}")

    # Picker: tick Halo Infinite, untick Rocket League, save
    users = await gm.config.guild(guild).users()
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.open_picker(i, "installed", ephemeral=True)
    picker = i.response.calls[0][2]["view"]
    check(isinstance(picker, gm_mod.GamePickerView) and picker.selected == set(users["2"]["installed"]), "picker preselects")
    select = next(c for c in picker.walk_children() if isinstance(c, discord.ui.Select))
    check(len(select.options) == 5 and not any(o.default for o in select.options), "no pre-selected chips")
    check(all(str(o.emoji) == ("☑️" if o.value in picker.selected else "⬜") for o in select.options), "option marks")
    embed_text = picker.text()
    check("☑️ Rocket League" in embed_text and "⬜ Halo Infinite" in embed_text, "embed lists ticks")
    target = {ids["Halo Infinite"], mc}
    new_values = sorted(picker.selected ^ target)  # choosing games toggles them
    select._values = new_values  # what Discord would send back
    try:
        values_ok = list(select.values) == new_values
    except Exception:
        values_ok = False
    if values_ok:
        i2 = FakeInteraction(bot, guild, alex, channel, message=FakeMessage(channel))
        await select.callback(i2)
        check(picker.selected == target, "select toggles selection")
        check("**Halo Infinite** *(unsaved)*" in picker.text(), "unsaved changes marked")
        save = next(c for c in card_buttons(picker) if c.label == "Save")
        i3 = FakeInteraction(bot, guild, alex, channel, message=FakeMessage(channel))
        await save.callback(i3)
        users = await gm.config.guild(guild).users()
        check(set(users["2"]["installed"]) == {ids["Halo Infinite"], mc}, "picker save applies diff")
        check(ids["Halo Infinite"] in users["2"]["owned"] and ids["Rocket League"] in users["2"]["owned"],
              "installing via picker owns; uninstalling keeps owned")
    else:
        print("note: couldn't simulate select values; skipped picker callback test")
    picker.stop()

    # Slash command tree registered and autocomplete works
    tree_cmd = bot.tree.get_command("games")
    check(tree_cmd is not None and len(tree_cmd.commands) <= 25, f"slash group with {len(tree_cmd.commands)} subcommands")
    i = FakeInteraction(bot, guild, alex, channel)
    choices = await gm._game_choices(i, "Rocket League, ha", "all")
    check([c.value for c in choices] == ["Rocket League, Halo Infinite", "Rocket League, Halo: MCC"],
          f"autocomplete keeps earlier names: {[c.value for c in choices]}")

    await bot.remove_cog("GameManager")
    for task in list(gm.vote_tasks.values()):
        task.cancel()


pure_tests()
asyncio.run(flow_tests())
passed = sum(ok for ok, _ in results)
print(f"{passed}/{len(results)} checks passed")
