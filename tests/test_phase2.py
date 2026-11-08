"""GameManager phase 2: recurring sessions, Discord events, wishlist & sale alerts, free games, profile setup."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, card_color, card_text, discord, load
from gmcards import card_buttons

gm_mod = load("gamemanager", "gamemanager")
FakeMessage._state = None
results = []
S = SimpleNamespace


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


# ---- fake Steam / Epic ----
STEAM = {"elden ring": [("ELDEN RING", 1245620)], "baldurs": [("Baldur's Gate 3", 1086940), ("Baldur's Gate", 228280)],
         "rocket league": [("Rocket League", 252950)], "nothing": []}
PRICES = {1245620: {"final": 2999, "initial": 5999, "discount": 50, "final_text": "$29.99", "initial_text": "$59.99"},
          1086940: {"final": 5999, "initial": 5999, "discount": 0, "final_text": "$59.99", "initial_text": "$59.99"},
          252950: None}


async def fake_search(term):
    return STEAM.get(term.lower(), [])


async def fake_prices(appids):
    return {a: PRICES[a] for a in appids if a in PRICES}


gm_mod.steam_search = fake_search
gm_mod.steam_prices = fake_prices


class FakeEvent:
    def __init__(self, guild, **kw):
        self.guild, self.kw, self.id = guild, kw, 7000 + len(guild.events)
        self.status = discord.EventStatus.scheduled
        self.actions = []

    async def start(self):
        self.actions.append("start")
        self.status = discord.EventStatus.active

    async def end(self):
        self.actions.append("end")

    async def cancel(self):
        self.actions.append("cancel")


async def main():
    # ---- pure helpers ----
    chicago = ZoneInfo("America/Chicago")
    now = datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc)   # Wednesday noon in Chicago
    parsed = gm_mod.parse_recurring("every friday 9pm Raid night", chicago, now)
    check(parsed and parsed["title"] == "Raid night" and parsed["interval"] == 7
          and parsed["first"].astimezone(chicago) == datetime(2026, 11, 6, 21, 0, tzinfo=chicago), f"parse: {parsed}")
    parsed = gm_mod.parse_recurring("every other sun 8:30 pm", chicago, now)
    check(parsed and parsed["interval"] == 14 and (parsed["hour"], parsed["minute"]) == (20, 30) and parsed["title"] == "",
          f"every other: {parsed}")
    check(gm_mod.parse_recurring("every 9pm", chicago, now) is None, "needs a day")
    sched = {"tz": "America/Chicago", "hour": 21, "minute": 0, "interval": 7, "weekday": 4}
    before_dst_end = datetime(2026, 10, 30, 21, 0, tzinfo=chicago).astimezone(timezone.utc)
    after = gm_mod.advance_occurrence(before_dst_end, sched)
    check(after.astimezone(chicago).hour == 21 and after - before_dst_end == timedelta(days=7, hours=1),
          "keeps 9 PM local across the DST change")
    check(gm_mod.repeat_label(sched) == "Every Friday at 9 PM (America/Chicago)", gm_mod.repeat_label(sched))

    # ---- setup ----
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex = guild.add(2, "Alex")
    chris = guild.add(3, "Chris")
    channel = guild.channel
    channel.name = "games"
    guild.me.guild_permissions.manage_events = True
    guild.events = {}

    async def create_scheduled_event(**kw):
        event = FakeEvent(guild, **kw)
        guild.events[event.id] = event
        return event

    guild.create_scheduled_event = create_scheduled_event
    guild.get_scheduled_event = lambda eid: guild.events.get(eid)
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    await gm.config.user(brad).timezone.set("America/Chicago")
    await gm.add_games(guild, brad, ["Rocket League", "Deadlock", "Barony"], {"Rocket League": 252950})

    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        await bot.invoke(ctx)
        await asyncio.sleep(0.05)
        return channel.sent[-1]

    # ---- scheduled session -> Discord event ----
    await run(brad, "!games session tomorrow 9pm Raid night")
    sessions = await gm.config.guild(guild).play_sessions()
    session = next(iter(sessions.values()))
    event = guild.events.get(session["event_id"])
    check(event is not None and event.kw["entity_type"] == discord.EntityType.external
          and event.kw["location"] == "#games" and "Interested" in event.kw["description"], f"event created: {session}")
    session_msg = channel.messages[session["message_id"]]
    check("on the server's events" in card_text(session_msg), "card mentions the event")
    await gm._event_interest(event, alex, joined=True)
    sessions = await gm.config.guild(guild).play_sessions()
    check(sessions[session["id"]]["participants"] == ["1", "2"], "Interested joins the session")
    await gm._event_interest(event, brad, joined=False)
    await gm._event_interest(event, alex, joined=False)
    sessions = await gm.config.guild(guild).play_sessions()
    check(sessions[session["id"]]["participants"] == ["1"], "removing interest leaves (host stays)")
    start = gm_mod.parse_iso(session["starts_at"])
    await gm._tick_session(guild, session["id"], sessions[session["id"]], start + timedelta(minutes=1))
    check(event.actions == ["start"], "event starts with the session")
    await gm.end_session(guild, session["id"])
    check(event.actions == ["start", "end"], f"event ends with the session: {event.actions}")
    await run(brad, "!games session Quick game")
    check(len(guild.events) == 1, "sessions starting now get no event")
    await gm.config.guild(guild).events.set(False)
    await run(brad, "!games session in 3h Later game")
    check(len(guild.events) == 1, "events can be turned off")
    await gm.config.guild(guild).events.set(True)

    # ---- recurring ----
    sent = await run(brad, "!games session every friday 9pm Raid night")
    schedules = await gm.config.guild(guild).recurring()
    sched = next(iter(schedules.values()))
    check(sched["title"] == "Raid night" and sched["tz"] == "America/Chicago" and "Every Friday at 9 PM" in sent.content,
          sent.content)
    # the first one is made right away (its event shows now; its card a day ahead)
    sessions = await gm.config.guild(guild).play_sessions()
    new = [s for s in sessions.values() if s.get("recurring_id") == sched["id"]]
    first = gm_mod.parse_iso(new[0]["starts_at"]) if new else None
    check(len(new) == 1 and "Every Friday" in new[0]["repeat"] and first > gm_mod.utcnow(), "occurrence made")
    sched2 = (await gm.config.guild(guild).recurring())[sched["id"]]
    check(gm_mod.parse_iso(sched2["next_start"]) > first + timedelta(days=6), "advanced to the next week")
    check(not await gm._tick_recurring(guild, sched["id"], sched2, gm_mod.utcnow()), "not made twice")
    sent = await run(alex, f"!games recurring stop {sched['id']}")
    check("Only the host" in sent.content, "others can't stop it")
    sent = await run(brad, f"!games recurring skip {sched['id']}")
    left = [s for s in (await gm.config.guild(guild).play_sessions()).values() if s.get("recurring_id") == sched["id"]]
    check("Skipping" in sent.content and not left, "skip cancels the one already made")
    await gm._tick_recurring(guild, sched["id"], sched2, gm_mod.utcnow())
    left = [s for s in (await gm.config.guild(guild).play_sessions()).values() if s.get("recurring_id") == sched["id"]]
    check(len(left) == 1 and gm_mod.parse_iso(left[0]["starts_at"]) == gm_mod.parse_iso(sched2["next_start"]),
          "then the following week's is made")
    sent = await run(brad, "!games recurring")
    check("Raid night" in card_text(sent), "listed")
    await run(brad, f"!games recurring stop {sched['id']}")
    check(not await gm.config.guild(guild).recurring(), "stopped")

    # ---- wishlist ----
    sent = await run(alex, "!games want Elden Ring")
    check("Added **ELDEN RING**" in sent.content and "50% off" in sent.content and "aren't turned on" in sent.content,
          sent.content)
    wishlist = await gm.config.guild(guild).wishlist()
    check(wishlist["1245620"]["alerted"] == 50, "an existing sale isn't news")
    task = asyncio.create_task(run(chris, "!games want baldurs"))
    await asyncio.sleep(0.1)
    prompt = channel.sent[-1]
    view = prompt.kw["view"]
    check(isinstance(view, gm_mod.SteamPickView), "ambiguous name asks which one")
    select = next(c for c in view.walk_children() if isinstance(c, discord.ui.Select))
    select._values = ["1086940"]
    await select.callback(FakeInteraction(bot, guild, chris, channel, message=prompt))
    sent = await task
    check("Added **Baldur's Gate 3**" in sent.content, sent.content)
    await run(chris, "!games want Elden Ring")
    async with gm.config.guild(guild).users() as users:
        gm_mod.apply_change(gm_mod.user_entry(users, alex.id), next(
            g for g, v in (await gm.config.guild(guild).games()).items() if v["name"] == "Rocket League"), "own")
    sent = await run(alex, "!games want rocket league")
    check("You already own: Rocket League" in sent.content, sent.content)
    sent = await run(alex, "!games want nothing")
    check("Not found on Steam" in sent.content, sent.content)
    sent = await run(alex, "!games wishlist")
    check("ELDEN RING" in card_text(sent), "wishlist shows")
    sent = await run(brad, "!games wanted")
    text = card_text(sent)
    check(text.index("ELDEN RING") < text.index("Baldur") and "Wanted by 2: Alex and Chris" in text, text)

    # ---- sale alerts ----
    sale_channel = channel
    await run(brad, f"!games admin sales <#{sale_channel.id}>")
    await gm.config.guild(guild).sale_channel.set(sale_channel.id)  # (channel converter needs a real guild)
    n_before = len(channel.sent)
    PRICES[1086940] = {"final": 3599, "initial": 5999, "discount": 40, "final_text": "$35.99", "initial_text": "$59.99"}
    count = await gm.check_sales(guild)
    alert = channel.sent[-1]
    pinged = [u.id for u in alert.kw["allowed_mentions"].users]
    check(count == 1 and "<@3>" in card_text(alert) and pinged == [3] and "Baldur's Gate 3" in card_text(alert)
          and "40% off" in card_text(alert) and "ELDEN" not in card_text(alert), f"one alert for the new sale: {count}")
    check(card_color(alert) == gm_mod.ui.HIGHLIGHT and [b.label for b in card_buttons(alert)] == ["View on Steam"],
          "sale card: HIGHLIGHT with a Steam link for a single game")
    check(await gm.check_sales(guild) == 0, "no repeat alert for the same sale")
    PRICES[1086940]["discount"] = 60
    check(await gm.check_sales(guild) == 1, "a deeper discount alerts again")
    PRICES[1086940]["discount"] = 0
    await gm.check_sales(guild)
    PRICES[1086940]["discount"] = 25
    check(await gm.check_sales(guild) == 1, "a new sale after it ended alerts")
    # owners aren't pinged
    async with gm.config.guild(guild).wishlist() as wl:
        wl["252950"] = {"appid": 252950, "name": "Rocket League", "users": ["2"], "price": None, "checked_at": None,
                        "alerted": 0}
    PRICES[252950] = {"final": 999, "initial": 1999, "discount": 50, "final_text": "$9.99", "initial_text": "$19.99"}
    check(await gm.check_sales(guild) == 0, "nobody pinged for a game they own")

    # unwant
    sent = await run(chris, "!games unwant baldur")
    wishlist = await gm.config.guild(guild).wishlist()
    check("Removed **Baldur's Gate 3**" in sent.content and "1086940" not in wishlist, "unwant removes empty entry")

    # ---- free Epic games ----
    await gm.config.guild(guild).free_games.set(True)
    free = [{"id": "e1", "title": "Free Thing", "url": "https://store.epicgames.com/en-US/p/free-thing",
             "ends": (gm_mod.utcnow() + timedelta(days=5)).isoformat()}]
    check(await gm.check_free_games(guild, free) == 1 and "Free Thing" in card_text(channel.sent[-1])
          and card_color(channel.sent[-1]) == gm_mod.ui.HIGHLIGHT, "free game posted")
    check(channel.sent[-1].kw["allowed_mentions"] == gm_mod.ui.NO_PINGS, "free games don't ping")
    check(await gm.check_free_games(guild, free) == 0, "posted once")
    epic_sample = {"data": {"Catalog": {"searchStore": {"elements": [
        {"id": "x", "title": "Gift", "productSlug": "gift/home", "price": {"totalPrice": {"discountPrice": 0}},
         "promotions": {"promotionalOffers": [{"promotionalOffers": [
             {"startDate": "2026-01-01T15:00:00.000Z", "endDate": "2099-01-08T15:00:00.000Z",
              "discountSetting": {"discountPercentage": 0}}]}]}},
        {"id": "y", "title": "Paid", "price": {"totalPrice": {"discountPrice": 1999}}, "promotions": None}]}}}}

    async def fake_get_json(url, params=None, timeout=8):
        return epic_sample
    real_get_json = gm_mod._get_json
    gm_mod._get_json = fake_get_json
    parsed_free = await gm_mod.epic_free_games()
    gm_mod._get_json = real_get_json
    check([g["title"] for g in parsed_free] == ["Gift"] and parsed_free[0]["url"].endswith("/p/gift"),
          f"epic parsing: {parsed_free}")

    # ---- profile setup ----
    sent = await run(chris, "!games newprofile")
    wizard = sent.kw["view"]
    check(isinstance(wizard, gm_mod.ProfileWizard) and "1 of 5: Your timezone" in card_text(sent), "wizard opens")
    msg = sent

    def item(view, label=None, kind=discord.ui.Button, n=0):
        found = [c for c in view.walk_children() if isinstance(c, kind) and (label is None or c.label == label)]
        return found[n]

    def current_view():
        return msg.view

    async def click(view, label):
        i = FakeInteraction(bot, guild, chris, channel, message=msg)
        await item(view, label).callback(i)
        return i

    # step 1: timezone select
    tz_select = item(current_view(), kind=discord.ui.Select)
    tz_select._values = ["America/Denver"]
    await tz_select.callback(FakeInteraction(bot, guild, chris, channel, message=msg))
    check(await gm.config.user(chris).timezone() == "America/Denver", "timezone saved")
    check("2 of 5: Games you own" in card_text(msg) and "America/Denver" in card_text(msg),
          "advanced to step 2 with a note")
    # step 2: picker
    await click(current_view(), "Pick games")
    picker = current_view()
    check(isinstance(picker, gm_mod.GamePickerView), "picker took over")
    games = await gm.config.guild(guild).games()
    gid = {v["name"]: k for k, v in games.items()}
    sel = item(picker, kind=discord.ui.Select)
    sel._values = [gid["Deadlock"], gid["Barony"]]
    await sel.callback(FakeInteraction(bot, guild, chris, channel, message=msg))
    await click(picker, "Save")
    data = (await gm.config.guild(guild).users())["3"]
    check(set(data["owned"]) == {gid["Deadlock"], gid["Barony"]}, "owned saved")
    check("3 of 5" in card_text(msg) and "Saved (+2" in card_text(msg), "back to the wizard")
    # back, then typed names (an unknown game gets requested after the name check)
    await click(current_view(), "Back")
    i = await click(current_view(), "Type names")
    modal = i.response.calls[-1][1]
    modal.field._value = "Rocket League, Totally New Game"
    mi = FakeInteraction(bot, guild, chris, channel, message=msg)
    await modal.on_submit(mi)
    data = (await gm.config.guild(guild).users())["3"]
    requests = await gm.config.guild(guild).game_requests()
    check(gid["Rocket League"] in data["owned"] and any(r["name"] == "Totally New Game" for r in requests.values()),
          f"typed names owned/requested: {card_text(msg)}")
    await click(current_view(), "Next")
    # step 3: installed picker only lists owned games
    await click(current_view(), "Pick installed games")
    picker = current_view()
    check({g["name"] for g in picker.games} == {"Deadlock", "Barony", "Rocket League"}, "installed picker = owned")
    sel = item(picker, kind=discord.ui.Select)
    sel._values = [gid["Deadlock"]]
    await sel.callback(FakeInteraction(bot, guild, chris, channel, message=msg))
    await click(picker, "Save")
    data = (await gm.config.guild(guild).users())["3"]
    check(data["installed"] == [gid["Deadlock"]], "installed saved")
    # step 4: favorites
    check("4 of 5: Your favorites" in card_text(msg), card_text(msg))
    first = item(current_view(), kind=discord.ui.Select, n=0)
    first._values = [gid["Barony"]]
    await first.callback(FakeInteraction(bot, guild, chris, channel, message=msg))
    second = item(current_view(), kind=discord.ui.Select, n=1)
    second._values = [gid["Barony"]]  # moving Barony from #1 to #2
    await second.callback(FakeInteraction(bot, guild, chris, channel, message=msg))
    ranks = (await gm.config.guild(guild).users())["3"]["ranks"]
    check(ranks == {gid["Barony"]: 2}, f"ranks: {ranks}")
    await click(current_view(), "Next")
    # step 5: wishlist
    check("5 of 5: Games you want" in card_text(msg), card_text(msg))
    i = await click(current_view(), "Add wanted games")
    modal = i.response.calls[-1][1]
    modal.field._value = "baldurs\nnothing"
    await modal.on_submit(FakeInteraction(bot, guild, chris, channel, message=msg))
    desc = card_text(msg)
    check("Added:** Baldur's Gate 3" in desc and "`baldurs` → **Baldur's Gate 3**" in desc and "Not found" in desc, desc)
    await click(current_view(), "Finish")
    desc = card_text(msg)
    check("### 🎮 Your profile is set up" in desc and card_color(msg) == gm_mod.ui.SUCCESS and "America/Denver" in desc and "#2 Barony" in desc
          and "3 games, 1 installed" in desc and "**Wishlist** · 2 games" in desc, desc)
    # someone else can't use it
    sent = await run(chris, "!games newprofile")
    other = FakeInteraction(bot, guild, alex, channel, message=sent)
    check(not await sent.kw["view"].interaction_check(other), "only the owner can use the wizard")
    stop_i = FakeInteraction(bot, guild, chris, channel, message=sent)
    await item(sent.kw["view"], "Stop").callback(stop_i)
    check("Profile setup stopped" in card_text(stop_i.response.calls[-1][1]["view"]), "stop works")

    # guide lookup includes the wishlist
    out = await gm.guide_call_tool("games_library", {"member": "Chris"}, alex)
    check("Wishlist (wants, doesn't own): Baldur's Gate 3, ELDEN RING" in out, out)
    await bot.remove_cog("GameManager")


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
