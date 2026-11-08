"""GameManager batch requests: several games requested at once get one card, decided all at once or one by one."""
import asyncio

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, card_color, card_text, discord, load
from harness import LAYOUT_PROBLEMS
from gmcards import card_buttons, custom_ids

gm_mod = load("gamemanager", "gamemanager")
ui = gm_mod.ui
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


def request_cards(channel):
    return [m for m in channel.sent if m.kw.get("view") and "Game request" in card_text(m)]


async def main():
    guild = FakeGuild()
    brad, alex = guild.add(1, "Brad"), guild.add(2, "Alex")
    bot = TestBot(guild)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    channel = guild.channel

    def click(member, message=None):
        return FakeInteraction(bot, guild, member, channel, message=message)

    # 1) Several new games at once: one batch card, not one card each
    text = await gm.request_games_text(guild, channel, alex, ["Zork", "Myst", "Riven"], "own",
                                       unconfirmed={"Riven"})
    check(text.startswith("✅ **Requested:** Zork, Myst, Riven"), text)
    cards = request_cards(channel)
    check(len(cards) == 1, f"one card for the batch, got {len(cards)}")
    card = cards[0]
    batches = await gm.config.guild(guild).request_batches()
    bid, batch = next(iter(batches.items()))
    reqs = await gm.config.guild(guild).game_requests()
    by_name = {r["name"]: r for r in reqs.values()}
    check(all(r["batch"] == bid for r in reqs.values()) and batch["message_id"] == card.id,
          "requests point at their batch, which knows its card")
    t = card_text(card)
    check(t.startswith("### 🎮 Game requests: 3 games") and card_color(card) == ui.ATTENTION
          and "**3 games** requested by <@2>\n-# For the server library · approving also adds them to their library" in t
          and "**Zork**\n**Myst**\n**Riven** ⚠️\n-# Couldn't confirm this name on Steam or the web" in t, t)
    check([b.label for b in card_buttons(card)] == ["Approve all", "Review", "Deny all"]
          and card_buttons(card)[0].style == discord.ButtonStyle.primary
          and custom_ids(card) == [f"gm:rb:{a}:{bid}" for a in ("approve", "review", "deny")], "batch buttons")
    sent_before = len(channel.sent)

    # 2) One game at a time still gets the single card
    await gm.request_games_text(guild, channel, alex, ["Loom"])
    check(len(request_cards(channel)) == 2 and "Game request: Loom" in card_text(channel.sent[-1])
          and [b.label for b in card_buttons(channel.sent[-1])] == ["Approve", "Deny"], "single request, single card")
    sent_before = len(channel.sent)

    # 3) Members can't decide; a name command decides one game and redraws the batch card, no ping yet
    i = click(alex, card)
    await gm.on_batch_button(i, "approve", bid)
    check(i.response.calls[-1][1].startswith("🔒"), "members can't approve a batch")
    await gm.resolve_request(guild, by_name["Myst"]["id"], brad, approve=True)
    t = card_text(card)
    check("**Myst** ✅" in t and [b.label for b in card_buttons(card)] == ["Approve the rest", "Review", "Deny the rest"],
          t)
    check(len(channel.sent) == sent_before, "no ping until the whole batch is decided")
    users = await gm.config.guild(guild).users()
    games = await gm.config.guild(guild).games()
    myst = next(g for g, v in games.items() if v["name"] == "Myst")
    check(myst in users[str(alex.id)]["owned"], "approved game is in the requester's library")

    # 4) Review: pick Riven, deny it; the menu redraws with what's left
    i = click(brad, card)
    await gm.on_batch_button(i, "review", bid)
    kind, _, kw = i.response.calls[-1]
    review = kw["view"]
    check(kind == "send" and kw["ephemeral"] and isinstance(review, gm_mod.BatchReviewView)
          and [o.label for o in review.select.options] == ["Zork", "Riven"]
          and review.select.options[1].description == "Couldn't confirm this name", "review menu lists waiting games")
    picked = click(alex)
    check(not await review.interaction_check(picked), "only the admin who opened it can use the review menu")
    i2 = click(brad)
    await next(b for b in card_buttons(review) if b.label == "Deny picked").callback(i2)
    check(i2.response.calls[-1][1].startswith("❓ Pick at least one"), "nothing picked: asks to pick")
    review.select._values = [by_name["Riven"]["id"]]
    i3 = click(brad)
    await next(b for b in card_buttons(review) if b.label == "Deny picked").callback(i3)
    _, kw = i3.response.calls[-1]
    nxt = kw["view"]
    check(isinstance(nxt, gm_mod.BatchReviewView) and [o.label for o in nxt.select.options] == ["Zork"]
          and "✅ Denied 1." in card_text(nxt), card_text(nxt))
    check("**Riven**\n-# Denied" in card_text(card), card_text(card))

    # 5) Approve the rest: the card settles (SUCCESS), one ping, the batch is gone
    await gm.on_batch_button(click(brad, card), "approve", bid)
    t = card_text(card)
    check(card_color(card) == ui.SUCCESS and not card_buttons(card)
          and "**2 approved, 1 denied**\n-# requested by <@2>" in t and "**Zork** ✅" in t
          and "Approved games are in their library, not marked installed" in t, t)
    ping = channel.sent[-1]
    check(ping.content.startswith("✅ <@2> 2 of the 3 games you requested were added to the server library: https://")
          and [u.id for u in ping.kw["allowed_mentions"].users] == [2], ping.content)
    check(bid not in await gm.config.guild(guild).request_batches()
          and not any(r.get("batch") == bid for r in (await gm.config.guild(guild).game_requests()).values()),
          "settled batch and its requests are gone")
    i = click(brad, card)
    await gm.on_batch_button(i, "approve", bid)
    check(i.response.calls[-1][1].startswith("⚠️ Those requests were already handled"), "old buttons say so")

    # 6) Deny all asks first; Cancel keeps them; confirm denies, card turns DANGER, one ❌ ping
    await gm.request_games_text(guild, channel, alex, ["Grim Fandango", "Full Throttle"])
    card = request_cards(channel)[-1]
    bid = next(iter((await gm.config.guild(guild).request_batches())))
    i = click(brad, card)
    task = asyncio.create_task(gm.on_batch_button(i, "deny", bid))
    await asyncio.sleep(0.05)
    confirm = i.response.calls[-1][2]["view"]
    check(isinstance(confirm, gm_mod.ConfirmView) and "Deny 2 waiting requests?" in card_text(confirm)
          and card_buttons(confirm)[0].style == discord.ButtonStyle.danger, card_text(confirm))
    await card_buttons(confirm)[1].callback(click(brad))   # Cancel
    await asyncio.wait_for(task, 5)
    check(len(await gm.batch_pending(guild, bid)) == 2, "cancel denies nothing")
    i = click(brad, card)
    task = asyncio.create_task(gm.on_batch_button(i, "deny", bid))
    await asyncio.sleep(0.05)
    confirm = i.response.calls[-1][2]["view"]
    await card_buttons(confirm)[0].callback(click(brad))
    await asyncio.wait_for(task, 5)
    t = card_text(card)
    check(card_color(card) == ui.DANGER and "**0 approved, 2 denied**" in t and not card_buttons(card), t)
    check(channel.sent[-1].content.startswith("❌ <@2> your requests for 2 games were denied: https://"),
          channel.sent[-1].content)
    games = await gm.config.guild(guild).games()
    check(not any(v["name"] in ("Grim Fandango", "Full Throttle") for v in games.values()), "denied games not added")

    # 7) Profile setup's typed list for a member who can't add games: one batch card, games owned on approval
    before = len(request_cards(channel))
    note = await gm.add_typed_games(click(alex), alex, "Outer Wilds\nPapers, Please\nWarhammer 40,000: Darktide")
    check(len(request_cards(channel)) == before + 1, f"profile import: one card ({note})")
    card = request_cards(channel)[-1]
    check("**Papers, Please**" in card_text(card) and "**Warhammer 40,000: Darktide**" in card_text(card)
          and "Game requests: 3 games" in card_text(card), card_text(card))
    bid = next(iter((await gm.config.guild(guild).request_batches())))
    await gm.on_batch_button(click(brad, card), "approve", bid)
    games = await gm.config.guild(guild).games()
    owned = (await gm.config.guild(guild).users())[str(alex.id)]["owned"]
    check(all(any(v["name"] == n and g in owned for g, v in games.items())
              for n in ("Outer Wilds", "Papers, Please", "Warhammer 40,000: Darktide")), "approved and owned")
    check(channel.sent[-1].content.startswith("✅ <@2> all 3 games you requested were added"), channel.sent[-1].content)

    # 8) A big batch lists the first BATCH_ROWS_SHOWN and says how many more
    names = [f"Game {n}" for n in range(gm_mod.BATCH_ROWS_SHOWN + 5)]
    await gm.request_games_text(guild, channel, alex, names)
    t = card_text(request_cards(channel)[-1])
    check(f"Game requests: {len(names)} games" in t and "-# And 5 more." in t and "**Game 34**" not in t, t[-200:])

    # 9) After a restart the buttons rebuild from their custom IDs
    item = await gm_mod.RequestBatchButton.from_custom_id(None, None, {"action": "review", "bid": "abc"})
    check(item.action == "review" and item.bid == "abc" and item.item.custom_id == "gm:rb:review:abc", "dynamic item")

    await bot.remove_cog("GameManager")


asyncio.run(main())
if LAYOUT_PROBLEMS:
    print("LAYOUT PROBLEMS:", *LAYOUT_PROBLEMS, sep="\n  ")
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
