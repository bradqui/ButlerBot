"""SpeakUp: times in chat, Steam cards, link summaries, command suggestions, reminders, settings."""
import asyncio
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, card_color, card_text, dcommands, discord, load

sp_mod = load("speakup", "speakup")
sp_mod.EMBED_WAIT = 0
gm_mod = load("gamemanager", "gamemanager")
FakeMessage._state = None
results = []


def label_of(c):
    return getattr(c, "label", None) or getattr(getattr(c, "item", None), "label", None)


def card_items(msg):
    """Buttons in a card, DynamicItems included (as the DynamicItem)."""
    view = getattr(msg, "view", msg)
    return [i for i in view.walk_children() if isinstance(i, (discord.ui.Button, discord.ui.DynamicItem))]


def looks(msg):
    """(label, emoji) of every button in a card."""
    out = []
    for i in card_items(msg):
        b = getattr(i, "item", i)
        out.append((b.label, str(b.emoji) if b.emoji else None))
    return out


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


async def add_reaction(self, emoji):
    self.reactions_added = getattr(self, "reactions_added", []) + [emoji]
FakeMessage.add_reaction = add_reaction
FakeMessage.jump_url = "https://discord.com/channels/1/500/1"

STEAM = {1245620: {"name": "ELDEN RING", "price": {"discount_percent": 40, "final_formatted": "$35.99",
                                                   "initial_formatted": "$59.99"}, "free": False}}


async def fake_details(appid):
    return STEAM.get(appid)
sp_mod.steam_details = fake_details


class ClaudeChat(dcommands.Cog):
    def __init__(self):
        self.summaries, self.suggestions = [], {}

    async def summarize_link(self, url, member):
        self.summaries.append(url)
        return "- A short summary\n- Second point"

    async def suggest_command(self, message, typed):
        return self.suggestions.get(typed)


async def main():
    # ---- time parsing ----
    chi = ZoneInfo("America/Chicago")
    now = datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc)   # Wednesday 2 PM in Chicago

    def local(text):
        found = sp_mod.find_time(text, chi, now)
        return (found[0].astimezone(chi).strftime("%a %H:%M"), found[1]) if found else None

    check(local("anyone want to play at 9?") == ("Wed 21:00", "at 9"), local("anyone want to play at 9?"))
    check(local("friday 8:30 pm works for me") == ("Fri 20:30", "friday 8:30 pm"), local("friday 8:30 pm works for me"))
    check(local("let's do 21:15") == ("Wed 21:15", "21:15"), local("let's do 21:15"))
    check(local("tomorrow 8am raid") == ("Thu 08:00", "tomorrow 8am"), local("tomorrow 8am raid"))
    check(local("join tomorrow morning at 9") == ("Thu 09:00", "tomorrow at 9"), local("join tomorrow morning at 9"))
    check(local("this morning at 9 was rough") is None, "a bare 'at 9' needs planning words")
    check(local("lunch at 1pm") == ("Thu 13:00", "1pm"), "a time already passed today means tomorrow")
    check(local("today at 9am") is None, "explicit today in the past is ignored")
    for text in ("I got 5 kills at 5", "won 3:2", "at 50% hp", "costs $9pm", "see https://x.com/a/12:30",
                 "`at 9`", "at 9 players", "level 9"):
        check(local(text) is None, f"no time in: {text}")
    check(local("tonight at 9") == ("Wed 21:00", "tonight at 9"), local("tonight at 9"))

    links = sp_mod.summary_links("read https://example.com/article and https://tenor.com/x.gif "
                                 "https://cdn.discordapp.com/a.png https://store.steampowered.com/app/1 "
                                 "https://youtu.be/abc https://x.com/post")
    check(links == ["https://example.com/article"], links)   # YouTube: web fetch can't summarize a video
    check(sp_mod.parse_relative("2h check the oven") == (7200, "check the oven"), "relative")
    check(sp_mod.parse_relative("in 1d 3h to call") == (97200, "to call"), "relative with in")
    check(sp_mod.parse_relative("friday 6pm") is None, "not relative")
    check(sp_mod.tidy_reminder("to call mom") == "call mom", "tidy")

    # ---- setup ----
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex = guild.add(2, "Alex")
    chris = guild.add(3, "Chris")
    channel = guild.channel
    channel.name = "general"
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    claude = ClaudeChat()
    await bot.add_cog(claude)
    sp = sp_mod.SpeakUp(bot)
    await bot.add_cog(sp)
    sp.reminder_loop.cancel()
    await gm.config.user(alex).timezone.set("America/Chicago")

    def said(author, text):
        return FakeMessage(channel, text, author=author)

    # ---- times ----
    m = said(alex, "anyone want to play at 9?")
    await sp.on_message_without_command(m)
    check(getattr(m, "reactions_added", []) == ["🕘"] and sp._tracked[m.id]["kind"] == "time", "clock reaction")
    m2 = said(chris, "or friday 9pm")
    await sp.on_message_without_command(m2)
    check(not getattr(m2, "reactions_added", []), "channel cooldown")
    payload = SimpleNamespace(message_id=m.id, user_id=3, emoji="🕘", guild_id=guild.id, channel_id=channel.id,
                              member=chris)
    channel.messages[m.id] = m
    await sp.on_raw_reaction_add(payload)
    reply = channel.sent[-1]
    check(not reply.content and "**at 9** is <t:" in card_text(reply)
          and "America/Chicago (Alex's timezone)" in card_text(reply), card_text(reply))
    check(looks(reply) == [("Schedule a session", "🎮"), (None, "🗑️")], looks(reply))
    before = len(channel.sent)
    await sp.on_raw_reaction_add(payload)
    check(len(channel.sent) == before, "answered once")
    # schedule a session from the time
    ts = sp._tracked[m.id]["ts"]
    i = FakeInteraction(bot, guild, chris, channel, message=reply)
    await sp.schedule_from_time(i, ts)
    modal = i.response.calls[-1][1]
    modal.name._value = "Raid night"
    mi = FakeInteraction(bot, guild, chris, channel, message=reply)
    await modal.on_submit(mi)
    sessions = await gm.config.guild(guild).play_sessions()
    s = next(iter(sessions.values()))
    check(s["title"] == "Raid night" and s["host_id"] == "3" and gm_mod.parse_iso(s["starts_at"]).timestamp() == ts,
          f"session scheduled: {s}")
    # opted-out and quiet channels
    sp._cooldowns.clear()
    await sp.config.user(chris).opted_out.set(True)
    m3 = said(chris, "at 10 then")
    await sp.on_message_without_command(m3)
    check(not getattr(m3, "reactions_added", []), "opted out")
    await sp.config.user(chris).opted_out.set(False)
    await sp.config.guild(guild).quiet_channels.set([channel.id])
    await sp.on_message_without_command(m3)
    check(not getattr(m3, "reactions_added", []), "quiet channel")
    await sp.config.guild(guild).quiet_channels.set([])

    # ---- link summaries ----
    m4 = said(alex, "good read https://example.com/news/story")
    await sp.on_message_without_command(m4)
    check(getattr(m4, "reactions_added", []) == ["📄"], "page reaction")
    channel.messages[m4.id] = m4
    await sp.on_raw_reaction_add(SimpleNamespace(message_id=m4.id, user_id=3, emoji="📄", guild_id=guild.id,
                                                 channel_id=channel.id, member=chris))
    reply = channel.sent[-1]
    check("**Summary** of <https://example.com/news/story>" in reply.content and "- A short summary" in reply.content
          and reply.kw.get("suppress_embeds") and claude.summaries == ["https://example.com/news/story"], reply.content)
    sp._summaries[2] = [time.time()] * sp_mod.SUMMARIES_PER_HOUR
    sp._cooldowns.clear()   # one 📄 per channel per 5 minutes
    m5 = said(chris, "https://example.com/other")
    await sp.on_message_without_command(m5)
    channel.messages[m5.id] = m5
    await sp.on_raw_reaction_add(SimpleNamespace(message_id=m5.id, user_id=2, emoji="📄", guild_id=guild.id,
                                                 channel_id=channel.id, member=alex))
    check("summaries this hour" in channel.sent[-1].content and not sp._tracked[m5.id]["done"],
          "rate limited, still clickable by others")

    # ---- Steam cards ----
    await gm.add_games(guild, brad, ["Elden Ring"], {"Elden Ring": 1245620})
    games = await gm.config.guild(guild).games()
    er = next(iter(g for g in games.values() if g["name"] == "Elden Ring"))
    async with gm.config.guild(guild).users() as users:
        gm_mod.apply_change(gm_mod.user_entry(users, 1), er["id"], "install")
    m6 = said(alex, "this is on sale https://store.steampowered.com/app/1245620/ELDEN_RING/")
    await sp.on_message_without_command(m6)
    card = channel.sent[-1]
    desc = card_text(card)
    check(not card.embeds and desc == "**[ELDEN RING](https://store.steampowered.com/app/1245620)**\n-# 40% off, $35.99"
          "\n-# Owned by Brad", desc)
    check(looks(card) == [("I own it", None), ("Add to wishlist", None), (None, "🗑️")], looks(card))
    check(not getattr(m6, "reactions_added", []), "steam links get a card, not a summary offer")
    before = len(channel.sent)
    await sp.on_message_without_command(said(chris, "https://store.steampowered.com/app/1245620"))
    check(len(channel.sent) == before, "one card per game per channel for a while")
    i = FakeInteraction(bot, guild, alex, channel, message=card)
    await sp.steam_button(i, "want", 1245620)
    check("Added **ELDEN RING** to your wishlist" in i.followup.calls[-1][0], i.followup.calls)
    i = FakeInteraction(bot, guild, alex, channel, message=card)
    await sp.steam_button(i, "own", 1245620)
    data = (await gm.config.guild(guild).users())["2"]
    check(er["id"] in data["owned"], "I own this adds it to the library")

    # ---- command mistakes ----
    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        try:
            await bot.invoke(ctx)
        except dcommands.CommandNotFound as e:
            await sp.on_command_error(ctx, e)
        await asyncio.sleep(0.05)
        return ctx

    before = len(channel.sent)
    await run(alex, "!games owns Barony")
    reply = channel.sent[-1]
    check(len(channel.sent) == before + 1 and "Did you mean `!games own Barony`?" in reply.content,
          [m.content for m in channel.sent[before:]])
    view = reply.kw["view"]
    run_button = next(c for c in view.children if getattr(c, "label", "") == "Run it")
    i = FakeInteraction(bot, guild, chris, channel, message=reply)
    await run_button.callback(i)
    check("Only the person" in i.response.calls[-1][1], "only the typer can run it")
    sp._cooldowns.clear()
    ctx = await run(alex, "!gmaes list")
    check("Did you mean `!games list`?" in channel.sent[-1].content, channel.sent[-1].content)
    sp._cooldowns.clear()
    claude.suggestions["!showme my stats"] = "!games mygames"
    await run(alex, "!showme my stats")
    check("Did you mean `!games mygames`?" in channel.sent[-1].content, "AI suggestion used when fuzzy fails")
    sp._cooldowns.clear()
    before = len(channel.sent)
    await run(alex, "!!!")
    await run(alex, "!zzzzqqq")
    check(len(channel.sent) == before, "nothing for noise or no match")

    # ---- reminders ----
    ctx = await run(alex, "!remindme 2h check the oven")
    rem = await sp.config.reminders()
    r = next(iter(rem.values()))
    check(r["text"] == "check the oven" and 7100 < r["due"] - time.time() < 7300 and "I'll remind you" in
          channel.sent[-1].content, channel.sent[-1].content)
    await run(alex, "!remindme friday 6pm to buy Helldivers")
    rem = await sp.config.reminders()
    fri = next(x for x in rem.values() if "Helldivers" in x["text"])
    when = datetime.fromtimestamp(fri["due"], ZoneInfo("America/Chicago"))
    check(fri["text"] == "buy Helldivers" and when.strftime("%a %H:%M") == "Fri 18:00", f"{fri} {when}")
    await run(alex, "!remindme soonish do stuff")
    check("Start with when" in channel.sent[-1].content, "bad time explained")
    sent = await run(alex, "!reminders")
    check("check the oven" in card_text(channel.sent[-1]) and "Your reminders" in card_text(channel.sent[-1]),
          "listed")
    blocks = [i.content for i in channel.sent[-1].view.walk_children() if isinstance(i, discord.ui.TextDisplay)]
    oven = next(b for b in blocks if "check the oven" in b)
    check(oven.startswith("**check the oven**\n-# <t:") and f"(<t:{int(r['due'])}:R>) · in <#{channel.id}> · "
          f"ID `{r['id']}`" in oven and oven.count("\n") == 1, oven)
    check(card_text(channel.sent[-1]).endswith("-# `!reminders cancel <id>` cancels one"), "reminders footer: one hint")
    await run(chris, f"!reminders cancel {r['id']}")
    check("You have no reminder" in channel.sent[-1].content, "can't cancel someone else's")
    await run(alex, f"!reminders cancel {r['id']}")
    check(r["id"] not in await sp.config.reminders(), "cancelled")
    async with sp.config.reminders() as rem:
        rem[fri["id"]]["due"] = time.time() - 5
    await sp.reminder_loop.coro(sp)
    check("<@2>, you asked me to remind you: **buy Helldivers**" in channel.sent[-1].content
          and fri["id"] not in await sp.config.reminders(), channel.sent[-1].content)

    # ---- settings & dismiss ----
    await run(brad, "!speakup feature times off")
    check(not (await sp.config.guild(guild).features())["times"], "feature off")
    sp._cooldowns.clear()
    m7 = said(alex, "at 8 tonight?")
    await sp.on_message_without_command(m7)
    check(not getattr(m7, "reactions_added", []), "times feature off")
    await run(alex, "!speakup me off")
    check(await sp.config.user(alex).opted_out(), "me off")
    sent = await run(alex, "!speakup")
    check("**Your messages** · Opted out" in card_text(channel.sent[-1]), "status shows opt-out")
    check(card_text(channel.sent[-1]).endswith("\n-# Change with `!speakup me off`, `!speakup off` (mods) or "
                                               "`!speakup feature` (admins)"), "settings footer: one line")
    remove = sp_mod.RemoveButton(2)
    check(remove.item.label == "Remove" and str(remove.item.emoji) == "🗑️", "labeled Remove, not Dismiss")
    msg = channel.sent[-1]
    deleted = []

    async def delete():
        deleted.append(True)
    msg.delete = delete
    i = FakeInteraction(bot, guild, chris, channel, message=msg)
    await remove.callback(i)
    check(not deleted and "Only <@2>" in i.response.calls[-1][1], "others can't remove")
    i = FakeInteraction(bot, guild, alex, channel, message=msg)
    await remove.callback(i)
    _, text, kw = i.response.calls[-1]
    confirm_view = kw["view"]
    check(not deleted and kw.get("ephemeral") and "for everyone" in text, "asks privately first")
    keep = next(c for c in confirm_view.children if c.label == "Keep it")
    ki = FakeInteraction(bot, guild, alex, channel, message=FakeMessage(channel, text))
    await keep.callback(ki)
    check(not deleted, "Keep it keeps it")
    await remove.callback(i := FakeInteraction(bot, guild, alex, channel, message=msg))
    confirm_view = i.response.calls[-1][2]["view"]
    yes = next(c for c in confirm_view.children if c.label == "Remove for everyone")
    ci = FakeInteraction(bot, guild, alex, channel, message=FakeMessage(channel, "Remove this message for everyone?"))
    await yes.callback(ci)
    check(deleted and ci.response.calls[-1][1]["content"] == "✅ Removed.", "confirmed: removed for everyone")

    for name in ("SpeakUp", "ClaudeChat", "GameManager"):
        await bot.remove_cog(name)


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
