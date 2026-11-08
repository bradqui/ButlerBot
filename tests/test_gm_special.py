"""
GameManager: special nights (a Star Citizen night). Monthly schedules, a game set ahead (no vote), reminders and a
reminder note per session or schedule, sessions made ahead (event now, card later), replacing a regular night (and
it coming back), the same-night question, Plan next (button and command), and the Edit menu.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, card_buttons, card_text, discord, load

gm_mod = load("gamemanager", "gamemanager")
ui = gm_mod.ui
FakeMessage._state = None
results = []
LA = ZoneInfo("America/Los_Angeles")


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


def pinged(kw):
    am = kw.get("allowed_mentions")
    if am is None or am.users is False:
        return "none"
    return sorted(u.id for u in am.users)


class Event:
    def __init__(self, eid, kw):
        self.id, self.kw, self.edits = eid, dict(kw), []
        self.description = kw.get("description")
        self.status = discord.EventStatus.scheduled
        self.cover_image = None

    async def cancel(self):
        self.status = discord.EventStatus.cancelled

    async def start(self):
        self.status = discord.EventStatus.active

    async def end(self):
        self.status = discord.EventStatus.completed

    async def edit(self, **kw):
        self.edits.append(kw)
        if "description" in kw:
            self.description = kw["description"]
        return self


def labels_ok(modal):
    """Discord's limits for a modal: 5 top-level parts, labels up to 45 characters, descriptions up to 100."""
    parts = list(modal.children)
    return len(parts) <= 5 and all(len(c.text) <= 45 and len(c.description or "") <= 100 for c in parts)


async def main():
    # ---------- parsing ----------
    check(gm_mod.parse_reminders("36h, 15m") == [2160, 15] and gm_mod.parse_reminders("none") == []
          and gm_mod.parse_reminders("2 days and 1h") == [2880, 60] and gm_mod.parse_reminders("forever") is None
          and gm_mod.parse_reminders("2m") is None and gm_mod.parse_reminders("1d 12h") == [2160], "reminder times")
    check(gm_mod.fmt_lead(2160) == "36 hours" and gm_mod.fmt_lead(2880) == "2 days" and gm_mod.fmt_lead(15) == "15 min"
          and gm_mod.fmt_lead(60) == "1 hour" and gm_mod.leads_text([15, 2160]) == "36 hours and 15 min before",
          "reminder text")
    now = gm_mod.utcnow()
    first = gm_mod.parse_recurring("every first friday 8pm Star Citizen night", LA, now)
    check(first["nth"] == 1 and first["weekday"] == 4 and first["title"] == "Star Citizen night"
          and first["first"].astimezone(LA).day <= 7 and first["first"].astimezone(LA).weekday() == 4, "monthly")
    last = gm_mod.parse_recurring("every last friday of the month 9pm Raid", LA, now)
    check(last["nth"] == -1 and last["title"] == "Raid" and last["first"].astimezone(LA).day > 21, "last of the month")
    check(gm_mod.parse_recurring("every other friday 9pm", LA, now)["interval"] == 14
          and gm_mod.parse_recurring("monthly friday 9pm", LA, now) is None, "every other; monthly needs which one")
    check(gm_mod.nth_weekday(2026, 11, 4, 1).day == 6 and gm_mod.nth_weekday(2026, 11, 4, -1).day == 27
          and gm_mod.nth_weekday(2026, 2, 0, 5) is None, "nth weekday")
    sched = {"tz": "America/Los_Angeles", "nth": 1, "weekday": 4, "hour": 20, "minute": 0, "interval": None}
    nov = datetime(2026, 11, 6, 20, tzinfo=LA).astimezone(timezone.utc)
    check(gm_mod.advance_occurrence(nov, sched).astimezone(LA) == datetime(2026, 12, 4, 20, tzinfo=LA)
          and "First Friday of every month at 8 PM" in gm_mod.repeat_label(sched), "monthly steps and label")
    check(gm_mod.plan_date("11/20", sched, datetime(2026, 11, 7, tzinfo=timezone.utc)).astimezone(LA)
          == datetime(2026, 11, 20, 20, tzinfo=LA), "plan a date at the usual time")

    # ---------- a server ----------
    guild = FakeGuild()
    brad, alex, cole = guild.add(1, "Brad", admin=True), guild.add(2, "Alex"), guild.add(3, "Cole")
    guild.me.guild_permissions.manage_events = True
    bot = TestBot(guild)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    bot.dispatch = lambda *a: None
    channel = guild.channel
    channel.name = "game-night"
    await gm.config.guild(guild).timezone.set("America/Los_Angeles")
    async with gm.config.guild(guild).games() as games:
        games["sc"] = {"id": "sc", "name": "Star Citizen"}
        games["drg"] = {"id": "drg", "name": "Deep Rock Galactic"}

    events = {}

    async def create_scheduled_event(**kw):
        event = Event(7000 + len(events), kw)
        event.guild = guild
        events[event.id] = event
        return event
    guild.create_scheduled_event = create_scheduled_event
    guild.get_scheduled_event = lambda eid: events.get(eid)

    async def fetch_scheduled_event(eid):
        return events[eid]
    guild.fetch_scheduled_event = fetch_scheduled_event

    async def run(author, content):
        message = FakeMessage(channel, content, author=author)
        await bot.invoke(await bot.get_context(message))
        return channel.sent[-1] if channel.sent else None

    async def sessions():
        return await gm.config.guild(guild).play_sessions()

    async def schedules():
        return await gm.config.guild(guild).recurring()

    def of(all_sessions, rid):
        return sorted((s for s in all_sessions.values() if s.get("recurring_id") == rid), key=lambda s: s["starts_at"])

    # ---------- typed settings are checked ----------
    await run(brad, "!session new in 50h Bad\nReminders: forever")
    check("as reminders" in channel.sent[-1].content, "bad reminders are refused")
    await run(brad, "!session new in 50h Bad\nGame: Nonexistent Game 9")
    check("Bad" not in [s["title"] for s in (await sessions()).values()], "an unknown game is refused")
    await run(brad, "!session new in 50h Bad\nReplaces: no such thing")
    check("no repeating session called" in channel.sent[-1].content, "an unknown schedule is refused")

    # ---------- the two schedules ----------
    sent = await run(brad, "!session new every friday 8pm Friday Night Games\nReminders: none")
    fng = next(s for s in (await schedules()).values() if s["title"] == "Friday Night Games")
    check(fng["reminders"] == [] and "repeats: Every Friday at 8 PM" in sent.content
          and "each Discord event as soon as the last session ends" in sent.content, sent.content)
    await run(brad, "!session new every first friday 8pm Star Citizen night\nGame: Star Citizen\n"
                    "Reminders: 36h, 15m\nReminder note: Update your drivers, patch the game and build shaders.\n"
                    "Replaces: Friday Night Games")
    sc = next(s for s in (await schedules()).values() if s["title"] == "Star Citizen night")
    check(sc["nth"] == 1 and sc["game"] == {"id": "sc", "name": "Star Citizen"} and sc["reminders"] == [2160, 15]
          and sc["reminder_note"].startswith("Update your drivers") and sc["replaces"] == [fng["id"]]
          and sc["replaces_titles"] == ["Friday Night Games"], f"special schedule: {sc}")
    check(not any(isinstance(m.view, gm_mod.ReplaceAskView) for m in channel.sent if getattr(m, "view", None)),
          "Replaces given: no question")

    # Reset to a known night T: the first Friday of a month, at least 3 days away.
    await gm.config.guild(guild).play_sessions.set({})
    T = gm_mod.next_monthly(1, 4, (20, 0), LA, gm_mod.utcnow() + timedelta(days=3))
    async with gm.config.guild(guild).recurring() as rec:
        for rid in (fng["id"], sc["id"]):
            rec[rid]["next_start"] = T.isoformat()
            rec[rid].pop("replaced_dates", None)
    fng, sc = (await schedules())[fng["id"]], (await schedules())[sc["id"]]

    # ---------- the regular night gives way to the monthly special ----------
    made = await gm._tick_recurring(guild, fng["id"], fng, gm_mod.utcnow())
    check(made and gm_mod.parse_iso(made["starts_at"]) == T + timedelta(days=7)
          and (await schedules())[fng["id"]]["replaced_dates"] == [T.isoformat()],
          "the regular night on a Star Citizen Friday is skipped (and remembered)")
    check(gm_mod.is_pending(made) and made["event_id"] and not made["message_id"],
          "made a week ahead: its event is up, its card isn't")
    check(await gm._tick_recurring(guild, fng["id"], (await schedules())[fng["id"]], gm_mod.utcnow()) is None,
          "one regular night at a time")
    special = await gm._tick_recurring(guild, sc["id"], sc, gm_mod.utcnow())
    check(special and gm_mod.parse_iso(special["starts_at"]) == T and gm_mod.is_pending(special)
          and special["game"]["name"] == "Star Citizen" and special["reminders"] == [2160, 15],
          "the special night is made from its schedule")

    # Interested before the card is up joins it.
    await gm._event_interest(events[special["event_id"]], alex, joined=True)
    check("2" in (await sessions())[special["id"]]["participants"], "Interested joins a session made ahead")
    check((await gm.latest_session(guild, channel.id)) is None, "a session made ahead isn't this channel's session")

    # ---------- cancelling the special brings the regular night back ----------
    await gm.end_session(guild, special["id"])
    back = [s for s in of(await sessions(), fng["id"]) if gm_mod.parse_iso(s["starts_at"]) == T]
    check(back and not (await schedules())[fng["id"]].get("replaced_dates")
          and events[special["event_id"]].status == discord.EventStatus.cancelled,
          "cancelled before it started: the regular night comes back")

    # ---------- Plan next books the special night again; the regular one is replaced ----------
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.open_plan_next(i, {"recurring_id": sc["id"], "host_id": "1"})
    check("🔒" in str(i.response.calls[-1]), "only the host or a game admin plans")
    i = FakeInteraction(bot, guild, brad, channel)
    await gm.open_plan_next(i, {"recurring_id": sc["id"], "host_id": "1"})
    view = i.response.calls[-1][2]["view"]
    options = view.select.options
    check(isinstance(view, gm_mod.PlanNextView) and 1 <= len(options) <= gm_mod.PLAN_CHOICES
          and all(len(o.label) <= 100 and len(o.description or "") <= 100 for o in options)
          and gm_mod.parse_iso(sc["next_start"]) != gm_mod.parse_iso(options[0].value),
          f"Plan next offers Fridays: {[o.label for o in options[:3]]}")
    check(T.isoformat() in [o.value for o in options], "the regular-replaced Friday is offered")
    line = await gm.book_night(guild, brad, sc["id"], T)   # what picking it does
    booked = [s for s in of(await sessions(), sc["id"]) if gm_mod.parse_iso(s["starts_at"]) == T]
    check(line.startswith("✅") and booked and booked[0]["booked"], f"booked: {line}")
    check(not [s for s in of(await sessions(), fng["id"]) if gm_mod.parse_iso(s["starts_at"]) == T]
          and T.isoformat() in (await schedules())[fng["id"]]["replaced_dates"], "and the regular night is off again")
    check("already on that night" in await gm.book_night(guild, brad, sc["id"], T), "a night can't be booked twice")
    special = booked[0]

    # The command does the same.
    later = T + timedelta(days=14)
    out = await run(brad, f"!games recurring plan Star Citizen night {later.astimezone(LA).month}/{later.astimezone(LA).day}")
    check(out.content.startswith("✅ **Star Citizen night** is on") and any(
        gm_mod.parse_iso(s["starts_at"]) == later for s in of(await sessions(), sc["id"])), out.content)
    out = await run(brad, "!session plan Star Citizen night someday")
    check("couldn't read the date" in out.content, "a date it can't read")

    # ---------- the card goes up at the 36-hour reminder and pings who joined ----------
    await gm._event_interest(events[special["event_id"]], alex, joined=True)
    special = (await sessions())[special["id"]]
    await gm._tick_session(guild, special["id"], special, T - timedelta(hours=40))
    check(gm_mod.is_pending((await sessions())[special["id"]]), "not before its earliest reminder")
    sent_before = len(channel.sent)
    await gm._tick_session(guild, special["id"], special, T - timedelta(hours=36) + timedelta(minutes=1))
    special = (await sessions())[special["id"]]
    card = channel.messages.get(special["message_id"])
    text = card_text(card) if card else ""
    check(card is not None and len(channel.sent) == sent_before + 1 and pinged(card.kw) == [1, 2],
          f"the card is the 36-hour reminder and pings who joined: {pinged(card.kw) if card else None}")
    check(2160 in gm_mod.sent_leads(special) and 15 not in gm_mod.sent_leads(special), "that reminder is done")
    check("**Playing Star Citizen**" in text and "**Before you play**" in text and "Update your drivers" in text
          and "**Replaces Friday Night Games**" in text and "Reminder 15 min before" in text, text)
    labels = [b.label for b in card_buttons(card)]
    check(labels == ["Join", "Leave", "Add to calendar", "Edit", "Plan next", "End session"], f"no vote, Plan next: {labels}")
    check(any("discord.com/channels" in (e.get("description") or "") for e in events[special["event_id"]].edits),
          "its event now links to the card")

    # No vote on a night set to a game.
    i = FakeInteraction(bot, guild, brad, channel)
    await gm.start_vote(i, session_id=special["id"])
    check("so there's no vote" in str(i.response.calls[-1]), "no vote when the game is set")

    # The 15-minute reminder (card in sight: a ping line).
    await gm._tick_session(guild, special["id"], special, T - timedelta(minutes=14))
    special = (await sessions())[special["id"]]
    check(channel.sent[-1].content.startswith("🎮 <@1> <@2> **Star Citizen night** starts")
          and gm_mod.sent_leads(special) == {2160, 15}, channel.sent[-1].content)
    check("Players are pinged when it starts" in card_text(channel.messages[special["message_id"]]),
          "the footer after the last reminder")

    # ---------- the regular night: no reminders, card a day ahead, quiet ----------
    regular = of(await sessions(), fng["id"])[0]
    rstart = gm_mod.parse_iso(regular["starts_at"])
    await gm._tick_session(guild, regular["id"], regular, rstart - timedelta(hours=23))
    regular = (await sessions())[regular["id"]]
    rcard = channel.messages.get(regular["message_id"])
    check(rcard is not None and pinged(rcard.kw) == "none" and "Players are pinged when it starts" in card_text(rcard)
          and "Start vote" in [b.label for b in card_buttons(rcard)] and "Plan next" not in
          [b.label for b in card_buttons(rcard)], "the regular card: a day ahead, no ping, a vote, no Plan next")
    count = len(channel.sent)
    await gm._tick_session(guild, regular["id"], regular, rstart - timedelta(minutes=10))
    check(len(channel.sent) == count, "no reminder before the start")

    # ---------- the same-night question ----------
    await run(brad, f"!session new {rstart.astimezone(LA).month}/{rstart.astimezone(LA).day} 9pm Tournament")
    ask = channel.sent[-1]
    check(isinstance(ask.view, gm_mod.ReplaceAskView) and "same night as **Friday Night Games**" in card_text(ask),
          card_text(ask))
    i = FakeInteraction(bot, guild, alex, channel, message=ask)
    check(not await ask.view.interaction_check(i), "only whoever made it answers")
    i = FakeInteraction(bot, guild, brad, channel, message=ask)
    await ask.view._replace(i)
    tour = next(s for s in (await sessions()).values() if s["title"] == "Tournament")
    check(tour["replaces"] == [fng["id"]] and regular["id"] not in await sessions()
          and "Replaced by Tournament this time." in card_text(rcard), card_text(rcard))
    await gm.end_session(guild, tour["id"])
    check(any(gm_mod.parse_iso(s["starts_at"]) == rstart for s in of(await sessions(), fng["id"])),
          "the tournament cancelled: Friday Night Games is back")
    await run(brad, f"!session new {rstart.astimezone(LA).month}/{rstart.astimezone(LA).day} 9pm Movie night")
    ask = channel.sent[-1]
    await ask.view._keep(FakeInteraction(bot, guild, brad, channel, message=ask))
    check(any(gm_mod.parse_iso(s["starts_at"]) == rstart for s in of(await sessions(), fng["id"]))
          and "Both stay on" in card_text(ask), "Keep both leaves the regular night")

    # ---------- the Edit menu ----------
    i = FakeInteraction(bot, guild, brad, channel, message=card)
    await gm.on_session_button(i, "event", special["id"])
    menu = i.response.calls[-1][2]["view"]
    mtext = card_text(menu)
    check(isinstance(menu, gm_mod.SessionEditMenu) and "**Game** · Star Citizen" in mtext
          and "**Reminders** · 36 hours and 15 min before" in mtext and "**Replaces** · Friday Night Games" in mtext,
          mtext)
    check([b.label for b in card_buttons(menu)] == ["Title & time", "Event details", "Game", "Reminders", "Replaces",
                                                    "Plan next", "Draw banner"], [b.label for b in card_buttons(menu)])
    forms = [gm_mod.TitleTimeModal(menu), gm_mod.GameModal(menu), gm_mod.RemindersModal(menu),
             gm_mod.ReplacesModal(menu, [fng])]
    check(all(labels_ok(f) for f in forms), "every form fits Discord's limits")
    check([o.default for o in forms[2].choices.options] == [False, True, False, False, True],
          "the reminders form ticks the current ones")
    # Saving (what the Reminders form does with its answers); the menu then redraws with the result.
    line = await gm.save_settings(guild, brad, special["id"], {"reminders": [1440, 60], "reminder_note": "Patch!"},
                                  True, "Reminders saved.")
    saved = (await sessions())[special["id"]]
    check(line == "✅ Reminders saved. Future sessions use it too." and saved["reminders"] == [1440, 60]
          and (await schedules())[sc["id"]]["reminders"] == [1440, 60] and "Patch!" in card_text(card)
          and all(s["reminders"] == [1440, 60] for s in of(await sessions(), sc["id"]) if not s.get("started")),
          f"{line} {saved['reminders']}")
    j = FakeInteraction(bot, guild, brad, channel)
    await menu.saved(j, line)
    check("Reminders saved" in card_text(menu) and "**Reminder note** · Patch!" in card_text(menu),
          "the menu shows the change")
    check("Not in the server" in await gm.save_game(guild, brad, special["id"], "Nonexistent 9", False), "unknown game")
    line = await gm.save_game(guild, brad, special["id"], "", False)
    check(not (await sessions())[special["id"]].get("game") and "Start vote" in
          [b.label for b in card_buttons(card)], f"no set game: the vote is back: {line}")
    line = await gm.save_game(guild, alex, special["id"], "Star Citizen", False)
    check(line.startswith("🔒"), "only the host or a game admin edits")
    await gm.save_game(guild, brad, special["id"], "star citizen", False)
    new_time = (T + timedelta(hours=1)).astimezone(LA)
    line = await gm.save_title_time(guild, brad, special["id"], "SC night", f"{new_time.month}/{new_time.day} 9pm",
                                    False)
    saved = (await sessions())[special["id"]]
    edit = events[special["event_id"]].edits[-1]
    check(line.startswith("✅") and saved["title"] == "SC night" and gm_mod.parse_iso(saved["starts_at"]) == T +
          timedelta(hours=1) and edit.get("name") == "SC night" and edit.get("start_time") == T + timedelta(hours=1),
          f"title and time: {line}")
    line = await gm.save_replaces(guild, brad, special["id"], [], False)
    check(line == "✅ Replaces nothing." and any(gm_mod.parse_iso(s["starts_at"]) == T
                                                 for s in of(await sessions(), fng["id"])),
          "no longer replacing: that regular night comes back")
    await gm.save_replaces(guild, brad, special["id"], [fng["id"]], False)
    check(not any(gm_mod.parse_iso(s["starts_at"]) == T for s in of(await sessions(), fng["id"])),
          "replacing again: it's off again")

    # ---------- /games session with the new options ----------
    i = FakeInteraction(bot, guild, brad, channel)
    when = (gm_mod.utcnow() + timedelta(days=2)).astimezone(LA)
    await gm.slash_session.callback(gm, i, title="DRG night", when=f"{when.month}/{when.day} 6pm", weekly=False,
                                    description=None, banner=None, voice=None, length=None, game="Deep Rock Galactic",
                                    reminders="1h", reminder_note="Bring snacks", replaces="none")
    drg = next(s for s in (await sessions()).values() if s["title"] == "DRG night")
    check(drg["game"]["name"] == "Deep Rock Galactic" and drg["reminders"] == [60]
          and drg["reminder_note"] == "Bring snacks" and drg["replaces"] == [], f"slash options: {drg}")

    # ---------- the server's default reminders ----------
    out = await run(brad, "!games admin reminders 1d, 1h")
    check(await gm.config.guild(guild).reminders() == [1440, 60] and "1 day and 1 hour before" in out.content,
          out.content)
    await run(brad, "!session new in 50h Default night")
    check(next(s for s in (await sessions()).values() if s["title"] == "Default night")["reminders"] == [1440, 60],
          "new sessions get the server's reminders")

    passed = sum(ok for ok, _ in results)
    print(f"{passed}/{len(results)} checks passed")


asyncio.run(main())
