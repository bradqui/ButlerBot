"""
GameManager: details for a session's Discord event (description, banner, voice channel, length) when it's started,
from the Edit event form, for a repeating session's future ones, and edits made in Discord flowing back.
"""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

from harness import FakeChannel, FakeGuild, FakeInteraction, FakeMessage, TestBot, card_buttons, card_text, dcommands, discord, load
from gmcards import custom_ids

gm_mod = load("gamemanager", "gamemanager")
ui = gm_mod.ui
FakeMessage._state = None
results = []
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPG = b"\xff\xd8\xff" + b"1" * 64


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


class FakeVoice(FakeChannel):
    pass


class Upload:
    def __init__(self, data, filename="banner.png", content_type="image/png", size=None):
        self.data, self.filename, self.content_type = data, filename, content_type
        self.size = len(data) if size is None else size

    async def read(self):
        return self.data


class Event:
    """A Discord event: Discord keeps its banner (cover image) at a URL that changes when the banner does."""

    def __init__(self, eid, kw):
        self.id, self.kw, self.edits, self.banners = eid, dict(kw), [], 0
        self.description = kw.get("description")
        self.status = discord.EventStatus.scheduled
        self.cover_image = None
        if kw.get("image"):
            self._new_cover()

    def _new_cover(self):
        self.banners += 1
        self.cover_image = SimpleNamespace(url=f"https://cdn.discordapp.com/guild-events/{self.id}/b{self.banners}.png")

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
        if "image" in kw:
            if kw["image"]:
                self._new_cover()
            else:
                self.cover_image = None
        return self


async def main():
    check(gm_mod.parse_length("2h") == 120 and gm_mod.parse_length("90m") == 90 and gm_mod.parse_length("1h30m") == 90
          and gm_mod.parse_length("1.5h") == 90 and gm_mod.parse_length("soon") is None, "lengths")
    check(gm_mod.fmt_minutes(90) == "1h30m" and gm_mod.fmt_minutes(120) == "2h", "length text")
    check(gm_mod.image_ext(PNG) == "png" and gm_mod.image_ext(JPG) == "jpg" and gm_mod.image_ext(b"hello") is None,
          "image types")

    guild = FakeGuild()
    brad, alex = guild.add(1, "Brad", admin=True), guild.add(2, "Alex")
    guild.me.guild_permissions.manage_events = True
    bot = TestBot(guild)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    bot.dispatch = lambda *a: None
    channel = guild.channel
    channel.name = "game-night"
    discord.VoiceChannel = FakeVoice   # after loading, so the cog's isinstance checks see this fake as voice
    voice = FakeVoice(guild, 900)
    voice.name = "Raid Voice"
    guild.voice_channels.append(voice)

    events = {}

    async def create_scheduled_event(**kw):
        event = Event(7000 + len(events), kw)
        events[event.id] = event
        return event
    guild.create_scheduled_event = create_scheduled_event
    guild.get_scheduled_event = lambda eid: events.get(eid)

    async def fetch_scheduled_event(eid):
        return events[eid]
    guild.fetch_scheduled_event = fetch_scheduled_event

    async def session_named(title):
        return next(s for s in (await gm.config.guild(guild).play_sessions()).values() if s["title"] == title)

    async def run(author, content, attachments=()):
        message = FakeMessage(channel, content, author=author)
        message.attachments = list(attachments)
        await bot.invoke(await bot.get_context(message))

    # ---------- a text command: the attached image is the banner, the mentioned voice channel is the place ----------
    await run(brad, "!session new in 2h Raid night <#900>", [Upload(PNG)])
    raid = await session_named("Raid night")
    event = events[raid["event_id"]]
    check(raid["title"] == "Raid night" and raid["event"]["voice_id"] == 900, "the mention isn't in the title")
    check(event.kw.get("channel") is voice and event.kw.get("image") == PNG and "end_time" not in event.kw,
          f"event in voice, with the banner, open-ended: {sorted(event.kw)}")
    check(event.kw["description"].startswith("Hosted by Brad. Press Interested"), event.kw["description"][:60])
    card = channel.messages[raid["message_id"]]
    check("in <#900>" in card_text(card), "the card says where")
    check(custom_ids(card) == [f"gm:s:{a}:{raid['id']}" for a in ("join", "leave", "vote", "cal", "event", "remove", "end")],
          "a scheduled session has Edit event")
    check((gm._banner_dir() / raid["event"]["banner"]).read_bytes() == PNG, "the banner is saved")
    first = card.view.children[0].children[0]
    check(isinstance(first, discord.ui.MediaGallery) and first.items[0].media.url == event.cover_image.url
          and raid["event"]["cover_url"] == event.cover_image.url,
          "the card shows the event's banner, full width at the top, from Discord's copy")
    await run(brad, "!session new Quick one", [Upload(b"not an image", "x.txt", "text/plain")])
    quick = await session_named("Quick one")
    check(not quick["event"].get("banner"), "a non-image attachment is ignored, not a banner")
    await run(brad, "!session new Now game", [Upload(PNG)])
    check(channel.sent[-1].content.startswith("⚠️ The event details weren't used"), "no time: no event, and it says so")

    # ---------- lines after the first are the description ----------
    await run(brad, "!session new in 4h Late raid <#900>\nBring a mic.\nWe're starting the new raid.")
    late = await session_named("Late raid")
    check(late["event"]["description"] == "Bring a mic.\nWe're starting the new raid." and late["event"]["voice_id"] == 900
          and events[late["event_id"]].kw["description"].startswith("Bring a mic.\nWe're starting the new raid.\n\nHosted"),
          f"multi-line description: {late['event']}")
    await run(brad, "!session new in 5h Long raid <#900>\nBring a mic.\nLength: 7h\nDuration of the raid is long.")
    long_raid = await session_named("Long raid")
    event = events[long_raid["event_id"]]
    check(long_raid["event"]["minutes"] == 420
          and long_raid["event"]["description"] == "Bring a mic.\nDuration of the raid is long."
          and event.kw["end_time"] - event.kw["start_time"] == timedelta(hours=7),
          f"a Length line sets the event's length, other lines stay the description: {long_raid['event']}")
    await run(brad, "!session new in 5h Odd raid\nlength: forever")
    check("as a length" in channel.sent[-1].content and "Odd raid" not in
          [s["title"] for s in (await gm.config.guild(guild).play_sessions()).values()], "a bad Length line is refused")
    await run(brad, "!session new every friday 9pm Weekly long raid\nlength 7 hours")
    weekly_long = next(s for s in (await gm.config.guild(guild).recurring()).values() if s["title"] == "Weekly long raid")
    check(weekly_long["event"].get("minutes") == 420 and not weekly_long["event"].get("description"),
          f"a repeating session keeps the length for every week: {weekly_long['event']}")
    async with gm.config.guild(guild).recurring() as recurring:
        recurring.pop(weekly_long["id"])

    # ---------- what the AI chat does: run the command on a copy of the asker's message (attachments and all) ----
    from copy import copy
    asked = FakeMessage(channel, "!ai set up a weekly raid on fridays at 9pm in <#900>, banner attached", author=brad)
    asked.attachments = [Upload(PNG)]
    ran = copy(asked)
    ran.content = "!games session every friday 9pm Friday raid <#900>\nWeekly raid night. Bring a mic."
    await bot.invoke(await bot.get_context(ran))
    weekly_ai = next(s for s in (await gm.config.guild(guild).recurring()).values() if s["title"] == "Friday raid")
    check(weekly_ai["event"]["description"] == "Weekly raid night. Bring a mic." and weekly_ai["event"]["voice_id"] == 900
          and gm.banner_bytes(weekly_ai["event"]["banner"]) == PNG, f"through the AI chat: {weekly_ai['event']}")
    async with gm.config.guild(guild).recurring() as recurring:
        recurring.pop(weekly_ai["id"])

    # ---------- the slash command's options ----------
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.slash_session.callback(gm, i, title="Chill night", when="in 3h", description="Bring snacks",
                                    banner=Upload(JPG, "b.jpg", "image/jpeg"), voice=None, length="90m")
    chill = await session_named("Chill night")
    event = events[chill["event_id"]]
    starts = gm_mod.parse_iso(chill["starts_at"])
    check(event.kw["description"].startswith("Bring snacks\n\nHosted by Alex.")
          and event.kw["entity_type"] == discord.EntityType.external
          and event.kw["end_time"] == starts + timedelta(minutes=90) and event.kw["location"] == "#game-night"
          and event.kw["image"] == JPG, f"slash details: {event.kw}")
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.slash_session.callback(gm, i, title="Bad", when="in 3h", description=None, banner=None, voice=None,
                                    length="forever")
    check("❓ I couldn't use **forever** as a length." in str(i.response.calls[-1]), "bad length")

    # ---------- Edit event ----------
    i = FakeInteraction(bot, guild, alex, channel, message=card)
    await gm.on_session_button(i, "event", raid["id"])
    check("🔒" in str(i.response.calls[-1]), "only the host or a game admin")
    i = FakeInteraction(bot, guild, brad, channel, message=card)
    await gm.on_session_button(i, "event", raid["id"])
    menu = i.response.calls[-1][2]["view"]
    check(isinstance(menu, gm_mod.SessionEditMenu) and i.response.calls[-1][2].get("ephemeral"),
          "Edit opens the private settings menu")
    i = FakeInteraction(bot, guild, brad, channel)
    await menu._event(i)
    modal = i.response.calls[-1][1]
    labels = [c for c in modal.children]
    check(isinstance(modal, gm_mod.EventDetailsModal) and len(labels) == 5
          and all(len(c.text) <= 45 and len(c.description or "") <= 100 for c in labels),
          f"the form: {[c.text for c in labels]}")
    payload = modal.to_dict()
    kinds = [c["component"]["type"] for c in payload["components"]]
    check(payload["title"] == "Event details" and kinds == [4, 4, 8, 19, 22] and all(c["type"] == 18 for c in
          payload["components"]), f"the form serializes for Discord: {kinds}")
    check(modal.voice.default_values and modal.voice.default_values[0].id == 900
          and [o.value for o in modal.options.options] == ["remove"], "current voice channel; Remove the banner")
    i = FakeInteraction(bot, guild, brad, channel, message=card)
    await gm.apply_event_details(i, raid["id"], description="Bring a mic", length="2h", voice_ids=[],
                                 banners=[Upload(JPG, "new.jpg", "image/jpeg")], options=[])
    raid = await session_named("Raid night")
    event = events[raid["event_id"]]
    edit = event.edits[-1]
    check(raid["event"]["minutes"] == 120 and raid["event"]["description"] == "Bring a mic"
          and "voice_id" not in raid["event"], raid["event"])
    check(edit["entity_type"] == discord.EntityType.external and edit["channel"] is None and edit["image"] == JPG
          and edit["description"].startswith("Bring a mic\n\n"), f"event edited: {sorted(edit)}")
    check(i.followup.calls[-1][0] == "✅ Event details saved.", i.followup.calls[-1])
    check("in <#900>" not in card_text(channel.messages[raid["message_id"]]), "the card follows")
    await gm.apply_event_details(FakeInteraction(bot, guild, brad, channel), raid["id"], description="", length="",
                                 voice_ids=[900], banners=[], options=["remove"])
    raid = await session_named("Raid night")
    edit = events[raid["event_id"]].edits[-1]
    check(edit["image"] is None and edit["channel"] is voice and not raid["event"].get("banner"),
          "remove the banner, back to voice")
    check(not raid["event"].get("cover_url") and not any(
        isinstance(c, discord.ui.MediaGallery) for c in channel.messages[raid["message_id"]].view.walk_children()),
        "no banner, no picture on the card")

    # ---------- edits made in Discord come back ----------
    later = gm_mod.utcnow() + timedelta(hours=5)
    after = SimpleNamespace(id=raid["event_id"], guild=guild, status=discord.EventStatus.scheduled, start_time=later,
                            name="Raid night (moved)", channel_id=900)
    await gm.on_scheduled_event_update(None, after)
    raid = await session_named("Raid night (moved)")
    check(abs((gm_mod.parse_iso(raid["starts_at"]) - later).total_seconds()) < 1 and not gm_mod.sent_leads(raid),
          "a new time from Discord moves the session and its reminder")
    check("Raid night (moved)" in card_text(channel.messages[raid["message_id"]]), "the card shows the new name")
    after.cover_image = SimpleNamespace(url="https://cdn.discordapp.com/guild-events/1/set-in-discord.png")
    await gm.on_scheduled_event_update(None, after)
    raid = await session_named("Raid night (moved)")
    top = channel.messages[raid["message_id"]].view.children[0].children[0]
    check(isinstance(top, discord.ui.MediaGallery) and top.items[0].media.url.endswith("set-in-discord.png"),
          "a banner set in Discord shows on the card")
    await gm.start_vote(FakeInteraction(bot, guild, brad, channel), session_id=raid["id"])
    voting = channel.messages[raid["message_id"]].view.children[0].children[0]
    await gm.on_session_button(FakeInteraction(bot, guild, alex, channel, message=card), "join", raid["id"])
    check(isinstance(voting, discord.ui.MediaGallery), "the banner stays while voting")
    after.status = events[raid["event_id"]].status = discord.EventStatus.cancelled   # as Discord has it now
    await gm.on_scheduled_event_update(None, after)
    check(not any(s["id"] == raid["id"] for s in (await gm.config.guild(guild).play_sessions()).values()),
          "cancelling the event ends the session")

    # ---------- a repeating session: details for this one or for the future ones ----------
    i = FakeInteraction(bot, guild, brad, channel)
    await gm.slash_session.callback(gm, i, title="Weekly raid", when=(gm_mod.utcnow() + timedelta(hours=10)).strftime("%A %I%p").lower(),
                                    weekly=True, description="Every week", banner=Upload(PNG), voice=voice, length=None)
    schedule = next(iter((await gm.config.guild(guild).recurring()).values()))
    check(schedule["event"]["description"] == "Every week" and schedule["event"]["voice_id"] == 900
          and schedule["event"]["banner"].startswith(schedule["id"]), f"schedule details: {schedule['event']}")
    weekly = await session_named("Weekly raid")
    check({k: v for k, v in weekly["event"].items() if k != "cover_url"} == schedule["event"]
          and "cover_url" not in schedule["event"] and weekly["event"].get("cover_url") and events[weekly["event_id"]].kw.get("image") == PNG,
          "the posted occurrence uses the schedule's details")
    # Add to calendar: anyone, privately; this night, plus the whole schedule
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.on_session_button(i, "cal", weekly["id"])
    kind, text, kw = i.response.calls[-1]
    files = {f.filename: f.fp.read().decode() for f in kw.get("files", [])}
    one = files.get("weekly-raid.ics", "")
    every = files.get("weekly-raid-every-time.ics", "")
    check(kind == "send" and kw.get("ephemeral") and text.startswith("🗓️ **Weekly raid** for your calendar")
          and "every night on the schedule" in text, text)
    check("BEGIN:VEVENT" in one and "SUMMARY:Weekly raid (Test Server)" in one and "DTSTART:" in one
          and "RRULE" not in one and "DESCRIPTION:Every week" in one and "LOCATION:" in one, one)
    check(f"RRULE:FREQ=WEEKLY;BYDAY=" in every and f"DTSTART;TZID={schedule['tz']}:" in every
          and f"UID:schedule-{schedule['id']}@butlerbot" in every, every)
    # Draw banner: Gemini paints it from the title and an idea; saved like an uploaded one
    line = await gm.draw_banner(guild, brad, weekly["id"], "a dragon over a castle", True)
    check(line.startswith("⚠️ Drawing a banner needs image generation"), line)

    class FakeGemini(dcommands.Cog, name="GeminiChat"):
        prompts = []

        async def render_image(self, prompt, *, channel):
            self.prompts.append(prompt)
            return PNG, None
    await bot.add_cog(FakeGemini())
    line = await gm.draw_banner(guild, alex, weekly["id"], "", False)
    check(line.startswith("🔒"), "only the host or a game admin draws banners")
    line = await gm.draw_banner(guild, brad, weekly["id"], "a dragon over a castle", True)
    prompt = FakeGemini.prompts[-1]
    check(line.startswith("✅ New banner drawn. Future sessions use it too.") and 'game night called "Weekly raid"' in prompt
          and "It shows: a dragon over a castle." in prompt and "No text" in prompt, f"{line} / {prompt}")
    drawn = await session_named("Weekly raid")
    check(drawn["event"]["banner"].startswith(weekly["recurring_id"])
          and (await gm.config.guild(guild).recurring())[weekly["recurring_id"]]["event"]["banner"]
          == drawn["event"]["banner"], "the drawn banner is saved for future sessions too")
    i = FakeInteraction(bot, guild, brad, channel)
    await gm.on_session_button(i, "event", weekly["id"])
    menu = i.response.calls[-1][2]["view"]
    check("Draw banner" in [b.label for b in card_buttons(menu)], "the Edit menu offers Draw banner")
    await bot.remove_cog("GeminiChat")

    i = FakeInteraction(bot, guild, brad, channel)
    await gm.on_session_button(i, "event", weekly["id"])
    i2 = FakeInteraction(bot, guild, brad, channel)
    await i.response.calls[-1][2]["view"]._event(i2)
    modal = i2.response.calls[-1][1]
    check([o.value for o in modal.options.options] == ["remove", "future"], "repeating: also for future sessions")
    await gm.apply_event_details(FakeInteraction(bot, guild, brad, channel), weekly["id"], description="Just this week",
                                 length="", voice_ids=[900], banners=[], options=[])
    check((await gm.config.guild(guild).recurring())[schedule["id"]]["event"]["description"] == "Every week",
          "this one only: the schedule keeps its details")
    await gm.apply_event_details(FakeInteraction(bot, guild, brad, channel), weekly["id"], description="New plan",
                                 length="2h", voice_ids=[900], banners=[Upload(JPG, "w.jpg", "image/jpeg")],
                                 options=["future"])
    future = (await gm.config.guild(guild).recurring())[schedule["id"]]["event"]
    check(future["description"] == "New plan" and future["minutes"] == 120 and future["banner"].startswith(schedule["id"])
          and gm.banner_bytes(future["banner"]) == JPG, f"future ones use them: {future}")

    passed = sum(ok for ok, _ in results)
    print(f"{passed}/{len(results)} checks passed")


asyncio.run(main())
