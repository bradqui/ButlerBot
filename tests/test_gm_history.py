"""GameManager: a session keeps every vote's winner and its card shows the history (a vote can keep the game)."""
import asyncio

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, card_text, load

gm_mod = load("gamemanager", "gamemanager")
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


async def main():
    check(gm_mod.played_text(["A"]) == "A", "one winner")
    check(gm_mod.played_text(["A", "A", "B", "A", "A", "A"]) == "A (won twice), then B, then A (won 3 times)",
          gm_mod.played_text(["A", "A", "B", "A", "A", "A"]))

    guild = FakeGuild()
    brad, alex, sam = guild.add(1, "Brad"), guild.add(2, "Alex"), guild.add(3, "Sam")
    bot = TestBot(guild)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    bot.dispatch = lambda *a: None
    channel = guild.channel
    await gm.add_games(guild, brad, ["Deep Rock Galactic", "Helldivers 2"])
    for m in (brad, alex, sam):
        await gm.change_library(guild, m, ["Deep Rock Galactic", "Helldivers 2"], "install")
    session = await gm.post_session(guild, channel, brad, "Raid night", None)
    sid = session["id"]
    for m in (alex, sam):
        await gm.set_membership(guild, sid, m, True)
    card = channel.messages[session["message_id"]]

    async def vote_for(name):
        await gm.start_vote(FakeInteraction(bot, guild, brad, channel), session_id=sid)
        s = (await gm.config.guild(guild).play_sessions())[sid]
        vote = (await gm.config.guild(guild).votes())[s["vote_id"]]
        gid = next(g for g, n in vote["names"].items() if n == name)
        for m in (brad, alex, sam):   # everyone votes, so it finishes right away
            await gm.on_vote_button(FakeInteraction(bot, guild, m, channel, message=card), vote["id"], gid)
        gm.vote_tasks.pop(vote["id"], None)
        return (await gm.config.guild(guild).play_sessions())[sid]

    s = await vote_for("Deep Rock Galactic")
    text = card_text(card)
    check(s["winners"] == ["Deep Rock Galactic"] and "🏆 **Deep Rock Galactic** won the vote." in text
          and "Earlier:" not in text, "first vote: no history line yet")
    s = await vote_for("Deep Rock Galactic")   # a vote to switch, but everyone stays
    text = card_text(card)
    check(s["winners"] == ["Deep Rock Galactic", "Deep Rock Galactic"]
          and "-# Earlier: Deep Rock Galactic" in text, "staying on the game is listed again")
    s = await vote_for("Helldivers 2")
    text = card_text(card)
    check(s["winners"][-1] == "Helldivers 2" and "🏆 **Helldivers 2** won the vote." in text
          and "-# Earlier: Deep Rock Galactic (won twice)" in text, text)

    await gm.end_session(guild, sid)
    text = card_text(card)
    check("🏆 **Helldivers 2** won the last vote.\n-# Earlier: Deep Rock Galactic (won twice)" in text, text)

    # sessions from before the history: only the last winner is known, and new winners add to it
    old = gm_mod.GameManager.session_card(gm, {**session, "winners": None, "winner": "Barony", "vote_result": None},
                                          True, None, guild)
    check("🏆 **Barony** won the vote." in card_text(old) and "Earlier" not in card_text(old), "older session")

    passed = sum(ok for ok, _ in results)
    print(f"{passed}/{len(results)} checks passed")


asyncio.run(main())
