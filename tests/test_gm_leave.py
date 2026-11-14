"""
GameManager: leaving a session and Remove player. Before a session starts, leaving (or being removed) just takes the
name off. Once it's under way, Leave and Remove player ask whether they played: "Played" keeps them on the played
list (the ended card and stats), and either way they're out of its votes.
"""
import asyncio
from datetime import timedelta

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, card_buttons, card_text, load

import discord   # (the harness puts the test libraries on the path)

gm_mod = load("gamemanager", "gamemanager")
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


def press(view, label, interaction):
    button = next(b for b in card_buttons(view) if b.label == label)
    return button.callback(interaction)


def pick(view, uid, interaction):
    select = next(i for i in view.walk_children() if isinstance(i, discord.ui.Select))
    interaction.data = {"values": [uid]}
    return select.callback(interaction)


def select_labels(view):
    select = next((i for i in view.walk_children() if isinstance(i, discord.ui.Select)), None)
    return [o.label for o in select.options] if select else None


async def main():
    guild = FakeGuild()
    brad, alex, sam, kim = guild.add(1, "Brad"), guild.add(2, "Alex"), guild.add(3, "Sam"), guild.add(4, "Kim")
    bot = TestBot(guild)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    ended = []
    bot.dispatch = lambda name, *a: ended.append(a[1]) if name == "gm_session_ended" else None
    channel = guild.channel
    await gm.add_games(guild, brad, ["Deep Rock Galactic", "Helldivers 2", "Barony"])
    for m in (brad, alex, sam):
        await gm.change_library(guild, m, ["Deep Rock Galactic", "Helldivers 2"], "install")
    await gm.change_library(guild, kim, ["Barony"], "install")   # Kim only has Barony
    await gm.change_library(guild, brad, ["Barony"], "install")

    def click(member, message=None):
        return FakeInteraction(bot, guild, member, channel, message=message)

    async def sessions():
        return await gm.config.guild(guild).play_sessions()

    check(gm_mod.session_live({"starts_at": None}) and gm_mod.session_live({"started": True, "starts_at": "x"}),
          "no set time, or started: under way")
    later = (gm_mod.utcnow() + timedelta(hours=3)).isoformat()
    check(not gm_mod.session_live({"starts_at": later}), "a set time still ahead: not yet")
    check(gm_mod.session_played({"participants": ["1", "2"], "played": ["3", "2"]}) == ["1", "2", "3"],
          "played: players still in, then those who left after playing")

    # ================= before it starts: leaving and Remove player just take the name off =================
    soon = await gm.post_session(guild, channel, brad, "Friday raid", gm_mod.utcnow() + timedelta(hours=3))
    sid = soon["id"]
    card = channel.messages[soon["message_id"]]
    for m in (alex, sam, kim):
        await gm.set_membership(guild, sid, m, True)
    check("Remove player" in [b.label for b in card_buttons(await gm.session_card_now(guild, (await sessions())[sid]))],
          "the card has Remove player")
    i = click(alex, card)
    await gm.on_session_button(i, "leave", sid)
    check(i.response.calls[-1][0] == "edit" and "2" not in (await sessions())[sid]["participants"]
          and not (await sessions())[sid].get("played"), "Leave before the start: off the list right away, no question")

    i = click(sam, card)   # not the host or a game admin
    await gm.on_session_button(i, "remove", sid)
    check(i.response.calls[-1][1].startswith("🔒"), f"only the host or a game admin removes: {i.response.calls[-1]}")

    i = click(brad, card)
    await gm.on_session_button(i, "remove", sid)
    menu = i.response.calls[-1][2]["view"]
    check(i.response.calls[-1][2].get("ephemeral") and select_labels(menu) == ["Sam", "Kim"],
          f"Remove player: a private menu of everyone but the host: {select_labels(menu)}")
    j = click(brad, card)
    await pick(menu, "4", j)
    s = (await sessions())[sid]
    final = j.response.calls[-1][1]["view"]
    check("4" not in s["participants"] and not s.get("played") and "✅ Removed **Kim** from **Friday raid**."
          in card_text(final) and "played" not in card_text(final), f"before the start: removed at once: {card_text(final)}")
    check("<@4>" not in card_text(card), "the card was redrawn without them")

    # ================= under way: Leave asks whether you played =================
    live = await gm.post_session(guild, channel, brad, "Raid night", None)   # no set time: under way
    sid = live["id"]
    card = channel.messages[live["message_id"]]
    for m in (alex, sam, kim):
        await gm.set_membership(guild, sid, m, True)

    i = click(kim, card)
    await gm.on_session_button(i, "leave", sid)
    kind, _, kw = i.response.calls[-1]
    ask = kw["view"]
    check(kind == "send" and kw.get("ephemeral") and "Did you play in **Raid night**?" in card_text(ask)
          and [b.label for b in card_buttons(ask)] == ["Played", "Didn't play", "Cancel"],
          f"Leave once it's under way asks, privately: {card_text(ask)}")
    check("4" in (await sessions())[sid]["participants"], "nothing changes until they answer")
    j = click(kim)
    await press(ask, "Cancel", j)
    check("4" in (await sessions())[sid]["participants"] and "You're still in." in card_text(j.response.calls[-1][1]["view"]),
          "Cancel keeps them in")

    i = click(kim, card)
    await gm.on_session_button(i, "leave", sid)
    ask = i.response.calls[-1][2]["view"]
    j = click(kim)
    await press(ask, "Played", j)
    s = (await sessions())[sid]
    check("4" not in s["participants"] and s["played"] == ["4"], f"Played: out, but on the played list: {s.get('played')}")
    check("You're still listed as having played." in card_text(j.response.calls[-1][1]["view"]), "says so")
    text = card_text(card)
    check("**3 playing**" in text and "Played and left: <@4>" in text, f"the card lists who played and left: {text}")

    # Kim's games are out of the vote: with Kim in, only Barony could… without, everyone has the other two.
    games, users = await gm.config.guild(guild).games(), await gm.config.guild(guild).users()
    names = {g: games[g]["name"] for g in games}
    picks, basis, _ = gm.vote_candidates(games, users, s["participants"])
    check(sorted(names[g] for g in picks) == ["Deep Rock Galactic", "Helldivers 2"] and basis.startswith("everyone has"),
          f"votes only weigh the players still in: {[names[g] for g in picks]}")

    # Rejoining makes them a player again, not one who left
    await gm.set_membership(guild, sid, kim, True)
    s = (await sessions())[sid]
    check("4" in s["participants"] and not s["played"], "rejoining clears the played-and-left mark")

    # ================= Remove player once it's under way: who, then did they play =================
    i = click(brad, card)
    await gm.on_session_button(i, "remove", sid)
    menu = i.response.calls[-1][2]["view"]
    j = click(brad)
    await pick(menu, "3", j)
    check(j.response.calls[-1][0] == "edit" and "Did **Sam** play in **Raid night**?" in card_text(menu)
          and [b.label for b in card_buttons(menu)] == ["Played", "Didn't play", "Back"],
          f"under way: asks about the player picked: {card_text(menu)}")
    j = click(brad)
    await press(menu, "Back", j)
    check(select_labels(menu) == ["Alex", "Sam", "Kim"], "Back returns to the list")
    await pick(menu, "3", click(brad))
    j = click(brad)
    await press(menu, "Didn't play", j)
    s = (await sessions())[sid]
    check("3" not in s["participants"] and "3" not in s["played"]
          and "✅ Removed **Sam** from **Raid night**." in card_text(j.response.calls[-1][1]["view"]),
          "Didn't play: out, and not counted")
    i = click(brad, card)
    await gm.on_session_button(i, "remove", sid)
    menu = i.response.calls[-1][2]["view"]
    await pick(menu, "4", click(brad))
    await press(menu, "Played", click(brad))
    check((await sessions())[sid]["played"] == ["4"], "removed by the host, counted as played")

    # ================= someone drops during a vote: it stops waiting on them =================
    await gm.start_vote(click(brad), session_id=sid)
    s = (await sessions())[sid]
    vote = (await gm.config.guild(guild).votes())[s["vote_id"]]
    check(vote["allowed_voters"] == ["1", "2"], f"a new vote only has the players still in: {vote['allowed_voters']}")
    check("Remove player" in [b.label for b in card_buttons(card)], "Remove player is on the card during a vote")
    dr = next(g for g, n in vote["names"].items() if n == "Deep Rock Galactic")
    await gm.on_vote_button(click(brad, card), vote["id"], dr)
    await gm.on_vote_button(click(alex, card), vote["id"], dr)
    gm.vote_tasks.pop(vote["id"], None)
    s = (await sessions())[sid]
    check(s["winner"] == "Deep Rock Galactic", "the vote finished")

    await gm.set_membership(guild, sid, sam, True)
    await gm.start_vote(click(brad), session_id=sid)
    s = (await sessions())[sid]
    vid = s["vote_id"]
    vote = (await gm.config.guild(guild).votes())[vid]
    hd = next(g for g, n in vote["names"].items() if n == "Helldivers 2")
    await gm.on_vote_button(click(brad, card), vid, hd)
    await gm.on_vote_button(click(sam, card), vid, dr)   # Sam votes, then drops; Alex hasn't voted yet
    line, _ = await gm.drop_player(guild, sid, "3", played=True, by=brad)
    vote = (await gm.config.guild(guild).votes())[vid]
    check(vote["allowed_voters"] == ["1", "2"] and "3" not in vote["user_votes"] and vote["tallies"] == {hd: 1},
          f"their vote is taken back and the vote stops waiting on them: {vote['tallies']}")
    await gm.drop_player(guild, sid, "2", played=False, by=brad)   # Alex drops too: everyone left has voted
    gm.vote_tasks.pop(vid, None)
    s = (await sessions())[sid]
    check(vid not in await gm.config.guild(guild).votes() and s["winner"] == "Helldivers 2",
          "the vote finishes once everyone still in has voted")

    # ================= the host stays; nobody else to remove =================
    line, _ = await gm.drop_player(guild, sid, "1", played=False, by=brad)
    check(line.startswith("❌") and "host" in line, f"the host can't be removed: {line}")
    i = click(brad, card)
    await gm.on_session_button(i, "remove", sid)
    check(i.response.calls[-1][1].startswith("❓ There's nobody to remove."), f"{i.response.calls[-1]}")

    # ================= at the end, everyone who played is listed =================
    await gm.end_session(guild, sid)
    text = card_text(card)
    check("**3 played**\n-# <@1> (host), <@4>, <@3>" in text and "Played and left" not in text and "<@2>" not in text,
          f"the ended card lists who played, not who was removed without playing: {text}")
    check(ended and ended[-1]["played"] == ["4", "3"] and ended[-1]["participants"] == ["1"],
          "the stats get who played and left")

    # ================= the leave command asks too =================
    live = await gm.post_session(guild, channel, brad, "Late game", None)
    await gm.set_membership(guild, live["id"], alex, True)
    ctx = await bot.get_context(FakeMessage(channel, "!games leave Late game", author=alex))
    await bot.invoke(ctx)
    await asyncio.sleep(0.01)
    sent = channel.sent[-1]
    check("Did you play in **Late game**?" in card_text(sent) and "2" in (await sessions())[live["id"]]["participants"],
          f"games leave on a session under way asks first: {card_text(sent)}")

    passed = sum(ok for ok, _ in results)
    print(f"{passed}/{len(results)} checks passed")


asyncio.run(main())
