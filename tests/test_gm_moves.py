"""
GameManager: finding a session after chatter has buried its card. The card moves to the bottom by itself for the
reminder, the start and a vote (and pings people there instead of a separate line); `games here` moves it on demand;
`games join` / `games leave` (and the slash versions) work without the card.
"""
import asyncio
from types import SimpleNamespace
from datetime import timedelta

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, card_text, discord, load
from gmcards import card_buttons, custom_ids

gm_mod = load("gamemanager", "gamemanager")
ui = gm_mod.ui
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


def pinged(kw):
    am = kw.get("allowed_mentions")
    if am is None or am.users is False:
        return "none"
    return sorted(u.id for u in am.users)


async def main():
    guild = FakeGuild()
    brad, alex, sam = guild.add(1, "Brad"), guild.add(2, "Alex"), guild.add(3, "Sam")
    bot = TestBot(guild)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    bot.dispatch = lambda *a: None
    channel = guild.channel
    channel.deleted = getattr(channel, "deleted", [])
    await gm.add_games(guild, brad, ["Rocket League", "Valorant"])
    for m in (brad, alex, sam):
        await gm.change_library(guild, m, ["Rocket League", "Valorant"], "install")

    # Channel history: the bot's messages plus people's chatter, oldest first.
    def history(after=None, limit=100):
        async def gen():
            n = 0
            for m in sorted(channel.sent, key=lambda m: m.id):
                if (after is None or m.id > after.id) and m.id not in channel.deleted:
                    yield m
                    n += 1
                    if n >= limit:
                        return
        return gen()
    channel.history = history

    def chatter(n):
        for i in range(n):
            channel.sent.append(FakeMessage(channel, f"lol {i}", author=sam))

    async def run(author, content):
        message = FakeMessage(channel, content, author=author)
        ctx = await bot.get_context(message)
        await bot.invoke(ctx)
        return message

    def last_text():
        return channel.sent[-1].content

    async def session_named(title):
        return next(s for s in (await gm.config.guild(guild).play_sessions()).values() if s["title"] == title)

    # ---------- join and leave by command ----------
    await run(brad, "!games session Raid night")
    raid = await session_named("Raid night")
    card = channel.messages[raid["message_id"]]
    await run(alex, "!games join")
    raid = await session_named("Raid night")
    check("2" in raid["participants"], "!games join joins the only session here")
    check(last_text().startswith("✅ You're in **Raid night**.\n-# [See the card](https://discord.com/channels/"),
          last_text())
    check(card.edits and "<@2>" in card_text(card), "the card is redrawn")
    await run(alex, "!games join")
    check(last_text() == "⚠️ You're already in.", last_text())
    await run(brad, "!games leave")
    check(last_text().startswith("❌ You're the host, so you can't leave."), last_text())
    await run(alex, "!games leave")   # no set time, so it's under way: did you play? (test_gm_leave.py has more)
    ask = channel.sent[-1]
    check("Did you play in **Raid night**?" in card_text(ask), card_text(ask))
    answer = FakeInteraction(bot, guild, alex, channel, message=ask)
    await next(b for b in card_buttons(ask) if b.label == "Didn't play").callback(answer)
    check("2" not in (await session_named("Raid night"))["participants"] and "✅ You've left **Raid night**."
          in card_text(answer.response.calls[-1][1]["view"]), "answered: left")

    await run(sam, "!games session Chill night")
    await run(alex, "!games join")
    check(last_text().startswith("❓ Which session? There's **Raid night** and **Chill night**.")
          and "`!games join Chill night`" in last_text(), last_text())
    await run(alex, "!games join raid")
    check("2" in (await session_named("Raid night"))["participants"], "join by part of the name")
    await run(alex, "!games join Nope")
    check(last_text().startswith("❓ There's no session called **Nope**."), last_text())

    # slash versions: autocomplete lists this channel's sessions; the value is the session ID; answers are private
    choices = await gm._ac_sessions(FakeInteraction(bot, guild, sam, channel), "")
    chill = await session_named("Chill night")
    check([c.name for c in choices] == ["Raid night", "Chill night"] and choices[1].value == chill["id"],
          [c.name for c in choices])
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.join_or_leave(i, chill["id"], join=True)
    check("2" in (await session_named("Chill night"))["participants"]
          and i.response.calls[-1][2].get("ephemeral") and "✅ You're in **Chill night**" in i.response.calls[-1][1],
          i.response.calls[-1])

    # ---------- games here: the card moves down ----------
    raid = await session_named("Raid night")
    old_id = raid["message_id"]
    chatter(12)
    sent_before = len(channel.sent)
    await run(brad, "!games here raid")
    raid = await session_named("Raid night")
    new = channel.sent[-1]
    check(len(channel.sent) == sent_before + 1 and new.id == raid["message_id"] and ui.is_card(new)
          and "Raid night" in card_text(new), "the card is reposted at the bottom")
    check(old_id in channel.deleted, "the old card is deleted")
    check(custom_ids(new)[0] == f"gm:s:join:{raid['id']}", "buttons are the same session's")
    check(pinged(new.kw) == "none", "moving on request pings nobody")
    await run(brad, "!games here raid")
    check(last_text().startswith("⏳ The card was just moved."), last_text())
    gm._here_last.clear()
    other = guild.add(4, "Dee")
    i = FakeInteraction(bot, guild, other, channel)
    await gm.bring_here(i, None)   # no name: the latest in this channel (Chill night)
    check((await session_named("Chill night"))["message_id"] == channel.sent[-1].id
          and "✅ Moved the card down here." in i.response.calls[-1][1], "slash here moves the latest")
    gm._here_last.clear()

    # buttons on the moved card still work
    await gm.on_session_button(FakeInteraction(bot, guild, sam, channel, message=new), "join", raid["id"])
    check("3" in (await session_named("Raid night"))["participants"], "Join on the moved card")

    # ---------- the reminder: buried card moves down and pings on itself ----------
    soon = gm_mod.utcnow() + timedelta(minutes=10)
    async with gm.config.guild(guild).play_sessions() as sessions:
        sessions[raid["id"]].update(starts_at=soon.isoformat(), reminded=False)
    raid = await session_named("Raid night")
    old_id = raid["message_id"]
    chatter(12)
    await gm._tick_session(guild, raid["id"], raid, gm_mod.utcnow())
    raid = await session_named("Raid night")
    moved = channel.messages.get(raid["message_id"]) or channel.sent[-1]
    check(raid["message_id"] != old_id and old_id in channel.deleted and 15 in gm_mod.sent_leads(raid),
          "buried at the reminder: the card moves")
    check(pinged(moved.kw) == [1, 2, 3] and raid.get("pings") == [] and not any(
        (m.content or "").startswith("🎮 <@") for m in channel.sent[-3:]), "the moved card is the ping, no ping line")

    # not buried: the start ping is a line, as before
    async with gm.config.guild(guild).play_sessions() as sessions:
        sessions[raid["id"]]["starts_at"] = (gm_mod.utcnow() - timedelta(minutes=1)).isoformat()
    raid = await session_named("Raid night")
    await gm._tick_session(guild, raid["id"], raid, gm_mod.utcnow())
    raid = await session_named("Raid night")
    check(last_text().startswith("🎮 <@1> <@2> <@3> **Raid night** is starting") and len(raid["pings"]) == 1,
          "card in sight: a ping line links to it")

    # ---------- a vote on a buried card ----------
    chatter(12)
    old_id = raid["message_id"]
    i = FakeInteraction(bot, guild, brad, channel)
    await gm.start_vote(i, session_id=raid["id"])
    raid = await session_named("Raid night")
    vote = (await gm.config.guild(guild).votes())[raid["vote_id"]]
    card = channel.sent[-1]
    check(raid["message_id"] == card.id and vote["message_id"] == card.id and old_id in channel.deleted,
          "the vote moves down with its card")
    check(vote["ping_id"] is None and raid["pings"] == [] and pinged(card.kw) == [1, 2, 3]
          and "Vote: what should we play?" in card_text(card), "the moved card pings the voters")
    await gm.on_vote_button(FakeInteraction(bot, guild, alex, channel, message=card), vote["id"], vote["games"][0])
    check(any(b.label.endswith(" · 1") for b in card_buttons(card)), "voting on the moved card")

    # ---------- an ended session can't be moved or joined ----------
    await gm.end_session(guild, chill["id"])
    await run(alex, "!games join Chill")
    check(last_text().startswith("❓ There's no session called **Chill**"), last_text())

    # ---------- the shortcuts: !session and !sessions ----------
    gm._here_last.clear()
    check(bot.get_command("session").signature == "", "!session shows no argument in its usage")
    await run(alex, "!session friday 9pm Raid")
    check(last_text().startswith("❓ `friday` isn't a session command.")
          and "`!session new friday 9pm Raid`" in last_text(), last_text())
    raid = await session_named("Raid night")
    old_id = raid["message_id"]
    chatter(3)
    await run(sam, "!session")
    check((await session_named("Raid night"))["message_id"] != old_id, "!session brings the card down")
    await run(sam, "!session new in 2h Late game")
    late = await session_named("Late game")
    check(late["host_id"] == "3" and late["starts_at"], "!session new starts one")
    await run(alex, "!session join late")
    check("2" in (await session_named("Late game"))["participants"], "!session join")
    await run(alex, "!session leave late")
    check("2" not in (await session_named("Late game"))["participants"], "!session leave")
    await run(alex, "!session end late")
    check(last_text().startswith("🔒"), "!session end checks the host")
    await run(sam, "!session end late")
    check(last_text() == "✅ Ended **Late game**." and not any(
        s["title"] == "Late game" for s in (await gm.config.guild(guild).play_sessions()).values()), last_text())
    await run(alex, "!sessions")
    check("Active sessions" in card_text(channel.sent[-1]) and "Raid night" in card_text(channel.sent[-1]),
          "!sessions lists them")
    other_channel = type(channel)(guild, 777)
    other_channel.name = "elsewhere"
    guild.text_channels.append(other_channel)
    m = FakeMessage(other_channel, "!session", author=alex)
    await bot.invoke(await bot.get_context(m))
    check(other_channel.sent and other_channel.sent[-1].content.startswith("❓ There's no session in this channel."),
          "!session where there's none")
    hb = load("handbook", "handbook")
    check(hb.Handbook.topic_for(SimpleNamespace(), bot.get_command("session join"), None) == "games/nights/"
          and hb.Handbook.topic_for(SimpleNamespace(), bot.get_command("sessions"), None) == "games/nights/",
          "help links the shortcuts to Game nights")

    passed = sum(ok for ok, _ in results)
    print(f"{passed}/{len(results)} checks passed")


asyncio.run(main())
