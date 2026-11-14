"""GameManager phase 2 (cards): sessions, votes, requests, settings, menus, old embed messages, and who gets pinged."""
import asyncio
from datetime import timedelta

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, card_color, card_text, discord, load
from gmcards import action_buttons, card_buttons, custom_ids

gm_mod = load("gamemanager", "gamemanager")
ui = gm_mod.ui
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


def pinged(kw) -> object:
    """Who a send would ping: 'none', or the sorted user IDs (and it must never allow everyone/roles)."""
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


def components(view) -> int:
    return sum(1 for _ in view.walk_children())


class Ctx:
    def __init__(self, guild, author):
        self.guild, self.author, self.channel = guild, author, guild.channel
        self.clean_prefix = "!"

    async def send(self, content=None, **kw):
        return await self.channel.send(content, **kw)


async def main():
    guild = FakeGuild()
    brad, alex, sam = guild.add(1, "Brad"), guild.add(2, "Alex"), guild.add(3, "Sam")
    bot = TestBot(guild)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    channel = guild.channel
    await gm.add_games(guild, brad, ["Rocket League", "Valorant", "Deadlock"], {"Rocket League": 252950})
    for m in (brad, alex, sam):
        await gm.change_library(guild, m, ["Rocket League", "Valorant"], "install")

    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        before = len(channel.sent)
        await bot.invoke(ctx)
        await asyncio.sleep(0.01)
        return channel.sent[-1] if len(channel.sent) > before else None

    def click(member, message):
        return FakeInteraction(bot, guild, member, channel, message=message)

    # ================= session card =================
    await gm.config.user(brad).timezone.set("America/Chicago")
    await run(brad, "!games session tomorrow 9pm Raid night")
    sid, session = next(iter((await gm.config.guild(guild).play_sessions()).items()))
    smsg = channel.messages[session["message_id"]]
    text = card_text(smsg)
    starts = gm_mod.parse_iso(session["starts_at"])
    check(ui.is_card(smsg) and session.get("card") is True, "session posted as a card and marked as one")
    check(text.startswith("### 🎮 Raid night\n")
          and f"**{gm_mod.stamp(starts)}**\n-# {gm_mod.stamp(starts, 'R')} · your local time" in text
          and "**1 playing**\n-# <@1> (host)" in text, text)
    blocks = [i.content for i in smsg.view.walk_children() if isinstance(i, discord.ui.TextDisplay)]
    check(blocks[1].startswith("**<t:") and blocks[2].startswith("**1 playing**") and " · " not in blocks[2].split("\n")[0],
          f"when and who are blocks of their own, details underneath: {blocks}")
    check(card_color(smsg) == ui.SUCCESS, "open session is SUCCESS")
    check(any(isinstance(i, discord.ui.Separator) for i in smsg.view.walk_children()), "separator above the buttons")
    labels = [b.label for b in card_buttons(smsg)]
    check(labels == ["Join", "Leave", "Start vote", "Add to calendar", "Edit", "Remove player", "End session"],
          f"session buttons inside the card (scheduled: Edit event too): {labels}")
    check(custom_ids(smsg) == [f"gm:s:{a}:{sid}" for a in ("join", "leave", "vote", "cal", "event", "remove", "end")],
          "persistent custom IDs")
    check([b.style for b in card_buttons(smsg)].count(discord.ButtonStyle.primary) == 1
          and card_buttons(smsg)[0].style == discord.ButtonStyle.primary, "Join is the one blurple button")
    check(sid not in text and "Session ID" not in text, "session ID hidden from the card")
    check(text.endswith("-# Reminder 15 min before"), f"footer: {text.splitlines()[-1]!r}")
    check(pinged(smsg.kw) == "none", f"posting a session pings nobody: {pinged(smsg.kw)}")

    # join / leave redraw the card
    i = click(alex, smsg)
    await gm.on_session_button(i, "join", sid)
    kind, kw = i.response.calls[-1]
    check(kind == "edit" and "embed" not in kw and "**2 playing**\n-# <@1> (host), <@2>" in card_text(kw["view"])
          and pinged(kw) == "none", f"join redraws the card without a ping: {card_text(kw['view'])}")
    check(custom_ids(kw["view"])[0] == f"gm:s:join:{sid}", "buttons survive the redraw")
    i = click(sam, smsg)
    await gm.on_session_button(i, "join", sid)
    i = click(sam, smsg)
    await gm.on_session_button(i, "leave", sid)
    check("<@3>" not in card_text(smsg) and "<@2>" in card_text(smsg), "leave redraws")
    await gm.on_session_button(click(sam, smsg), "join", sid)

    # an unscheduled session's footer explains the vote
    await run(alex, "!games session Quick game")
    quick = max((await gm.config.guild(guild).play_sessions()).values(), key=lambda s: s["created_at"])
    qtext = card_text(channel.messages[quick["message_id"]])
    check("<t:" not in qtext and qtext.endswith("-# When everyone's in, the host presses Start vote"), qtext)

    # ================= the vote runs inside the session card (Phase 4) =================
    i = click(brad, smsg)
    await gm.on_session_button(i, "vote", sid)
    vid, vote = next(iter((await gm.config.guild(guild).votes()).items()))
    check(vote["message_id"] == smsg.id and vote.get("in_card") and vote.get("labels"),
          "the vote lives on the session card, with its labels saved")
    vtext = card_text(smsg)
    check(vtext.startswith("### 🎮 Raid night") and "🗳️ **Vote: what should we play?**" in vtext
          and card_color(smsg) == ui.ATTENTION, vtext[:200])
    check("\n-# Pick 1 · ends <t:" in vtext and ":R> · 0 of 3 voted, waiting on Brad, Alex and Sam" in vtext, vtext)
    check("Press a game again" not in vtext and "Only players" not in vtext and "\n-# Options:" not in vtext
          and not vtext.endswith("can vote"), "how-to-vote guidance and the footer are off the card")
    check([b.label for b in card_buttons(smsg)][:len(vote["games"])] == [vote["names"][g] for g in vote["games"]],
          "no tallies on the buttons before anyone votes")
    ping = channel.sent[-1]
    check(ping.content.startswith("🗳️ <@1> <@2> <@3> Vote on what to play: https://discord.com/channels/")
          and ping.content.endswith(f"/{smsg.id}") and pinged(ping.kw) == [1, 2, 3],
          f"one short ping line for the vote, pinging exactly the players: {ping.content} {pinged(ping.kw)}")
    check((await gm.config.guild(guild).votes())[vid]["ping_id"] == ping.id, "ping line ID saved")
    check(vid not in vtext and "Vote ID" not in vtext, "vote ID hidden")
    gids = vote["games"]
    check(custom_ids(smsg) == [f"gm:v:{vid}:{g}" for g in gids] + [f"gm:s:remove:{sid}", f"gm:s:end:{sid}"]
          and all(b.style == discord.ButtonStyle.secondary for b in card_buttons(smsg)),
          f"grey option buttons inside, then Remove player and End session: {custom_ids(smsg)}")
    # pressing an option redraws the session card (no pings)
    i = click(alex, smsg)
    await gm.on_vote_button(i, vid, gids[0])
    edit = smsg.edits[-1]
    check("1 of 3 voted, waiting on Brad and Sam" in card_text(edit["view"]) and pinged(edit) == "none", card_text(smsg))
    check(i.response.calls[-1][1] == f"✅ Voted for **{vote['names'][gids[0]]}**.\n-# Press it again to take your "
                                     "vote back, then you can pick another." and i.response.calls[-1][2]["ephemeral"],
          f"how to vote is in the voter's private reply: {i.response.calls[-1][1]!r}")
    labels = [b.label for b in card_buttons(smsg)]
    check(labels[0] == f"{vote['names'][gids[0]]} · 1" and labels[1] == vote["names"][gids[1]],
          f"the running tally is on the button, none on an option with no votes: {labels}")
    i = click(alex, smsg)
    await gm.on_vote_button(i, vid, gids[0])   # take it back: the tally goes away again
    check(i.response.calls[-1][1].startswith("✅ Took back") and card_buttons(smsg)[0].label == vote["names"][gids[0]]
          and "0 of 3 voted" in card_text(smsg), f"taking a vote back redraws the tally: {card_buttons(smsg)[0].label}")
    await gm.on_vote_button(click(alex, smsg), vid, gids[0])
    check(custom_ids(smsg)[:len(gids)] == [f"gm:v:{vid}:{g}" for g in gids], "options kept after the redraw")
    await gm.on_vote_button(click(brad, smsg), vid, gids[0])
    await gm.on_vote_button(click(sam, smsg), vid, gids[1])   # everyone voted -> results
    rtext = card_text(smsg)
    check(rtext.startswith("### 🎮 Raid night") and "🏆 **Rocket League** won the vote." in rtext
          and "🥇 **" in rtext and "🥈 **" in rtext and card_color(smsg) == ui.SUCCESS
          and "-# 3 of 3 voted · Everyone voted" in rtext, f"results in the session card: {rtext}")
    check(ping.deleted and ping.id in channel.deleted, "the vote's ping line is deleted when it ends")
    win = channel.sent[-1]
    check(win.content.startswith("🏆 <@1> <@2> <@3> We're playing **Rocket League**: https://discord.com/channels/")
          and pinged(win.kw) == [1, 2, 3], f"winner line still pings the players: {win.content}")
    check("Voting now" not in rtext and [b.label for b in card_buttons(smsg)] == ["Join", "Leave", "Start vote",
                                                                                  "Add to calendar", "Edit",
                                                                                  "Remove player", "End session"],
          rtext)

    # many options: 20 buttons in 4 rows (plus Remove player and End session), under the 40-component limit
    fake = {"id": "v20", "title": "Big", "games": [f"g{n}" for n in range(20)], "names": {}, "labels": {},
            "basis": "everyone owns these", "tallies": {}, "user_votes": {}, "allowed_voters": ["1", "2"],
            "max_choices": 1, "ends_at": gm_mod.utcnow().isoformat()}
    view = gm.vote_card(fake)
    rows = [i for i in view.walk_children() if isinstance(i, discord.ui.ActionRow)]
    check(len(rows) == 4 and len(card_buttons(view)) == 20 and components(view) <= 40,
          f"20 options (old vote card): {len(rows)} rows, {components(view)} components")
    big = dict(session, participants=[str(10 ** 18 + n) for n in range(100)])   # snowflake-length IDs
    view = gm.session_card(big, vote=dict(fake, in_card=True, allowed_voters=big["participants"]))
    check(len(card_buttons(view)) == 22 and components(view) <= 40,
          f"20 options in the session card: {components(view)} components")
    from harness import validate_layout
    check(not validate_layout(view), f"big voting card within Discord's limits: {validate_layout(view)}")

    # Phase 5 blocks: a weekly session voting with 2 picks, options that not everyone has installed
    weekly = dict(session, repeat="Every other Friday at 9 PM (America/Chicago)", participants=["1", "2", "3", "999"])
    multi = dict(fake, id="v2p", games=["g1", "g2"], labels={"g1": "Deep Rock Galactic", "g2": "Barony"},
                 tallies={"g1": 2}, user_votes={"1": ["g1"], "2": ["g1"]}, allowed_voters=["1", "2", "3", "999"],
                 max_choices=2, in_card=True,
                 basis="everyone owns these, but not everyone has them installed")
    view = gm.session_card(weekly, vote=multi, guild=guild)
    text = card_text(view)
    blocks = [i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay)]
    check(":R> · every other Friday · your local time" in blocks[1] and blocks[2].startswith("**4 playing**\n-# <@1> (host)"),
          f"when block says how often: {blocks[1]!r}")
    check("-# Pick up to 2 · ends <t:" in text and "2 of 4 voted, waiting on Sam and <@999>" in text
          and "\n-# Options: everyone owns these, but not everyone has them installed." in text,
          f"vote block: picks, end, who's left (display names), and an unusual basis: {text}")
    check([b.label for b in card_buttons(view)][:2] == ["Deep Rock Galactic · 2", "Barony"], "tallies on the labels")
    check(not text.rstrip().endswith("can vote") and not any(t.startswith("-# ") for t in blocks[-1:]),
          "no footer while voting")
    # the private reply for a 2-pick vote, and the refusal for someone who wasn't in the session
    async with gm.config.guild(guild).votes() as votes:
        votes["v2p"] = dict(multi, names={"g1": "Deep Rock Galactic", "g2": "Barony"}, session_id="none")
    i = click(sam, smsg)
    await gm.on_vote_button(i, "v2p", "g2")
    check(i.response.calls[-1][1] == "✅ Voted for **Barony**.\n-# Press a game again to take your vote back. "
                                     "You can pick up to 2.", i.response.calls[-1][1])
    stranger = guild.add(4, "Stranger")
    i = click(stranger, smsg)
    await gm.on_vote_button(i, "v2p", "g1")
    check(i.response.calls[-1][1] == "🔒 Only players who were in the session when the vote started can vote.",
          i.response.calls[-1][1])
    async with gm.config.guild(guild).votes() as votes:
        votes.pop("v2p", None)

    # cancelled vote: the card goes back to normal and the ping line goes
    await gm.start_vote(Ctx(guild, brad), session_id=sid)
    vid2, vote2 = next(iter((await gm.config.guild(guild).votes()).items()))
    ping2 = channel.sent[-1]
    await gm.cancel_vote(guild, vid2)
    check(card_color(smsg) == ui.SUCCESS and "What should we play" not in card_text(smsg)
          and "🏆 **Rocket League** won the vote." in card_text(smsg) and ping2.id in channel.deleted,
          card_text(smsg))

    # end the session: MUTED, no buttons
    await run(brad, "!games endsession " + sid)
    etext = card_text(smsg)
    check(card_color(smsg) == ui.MUTED and not card_buttons(smsg) and "This session has ended." in etext
          and "**3 played**\n-# <@1> (host), <@2>, <@3>" in etext and pinged(smsg.edits[-1]) == "none", etext)
    # a click on the ended card: told it's over, and the card isn't touched (it can't be emptied)
    edits = len(smsg.edits)
    i = click(alex, smsg)
    await gm.on_session_button(i, "join", sid)
    check(i.response.calls[-1][1] == "⚠️ This session has ended." and len(smsg.edits) == edits, "ended card left alone")

    # ================= old embed messages still work =================
    now = gm_mod.utcnow().isoformat()
    old = {"id": "old1", "title": "Old night", "host_id": "1", "participants": ["1"], "channel_id": channel.id,
           "message_id": None, "created_at": now, "starts_at": None, "reminded": False, "started": False,
           "vote_id": None, "winner": None, "event_id": None}
    old_msg = await channel.send(embed=gm.session_embed(old), view=gm_mod.session_view("old1"))
    old["message_id"] = old_msg.id
    async with gm.config.guild(guild).play_sessions() as s:
        s["old1"] = dict(old)
    i = click(alex, old_msg)
    await gm.on_session_button(i, "join", "old1")
    kind, kw = i.response.calls[-1]
    check(not ui.is_card(old_msg) and "embed" in kw and isinstance(kw["view"], discord.ui.View)
          and not isinstance(kw["view"], discord.ui.LayoutView) and "<@2>" in old_msg.embeds[0].fields[0].value,
          "old embed session: join edits the embed")
    # its vote is still an embed message too (the session isn't a card); a vote record without "card"
    old_vote = {"id": "oldv", "session_id": "old1", "title": "Old night", "games": [gids[0], gids[1]],
                "names": {gids[0]: "A", gids[1]: "B"}, "basis": "", "tallies": {}, "user_votes": {},
                "allowed_voters": ["1", "2"], "channel_id": channel.id, "message_id": None, "max_choices": 1,
                "created_at": now, "created_by": "1", "ends_at": (gm_mod.utcnow() + timedelta(minutes=5)).isoformat(),
                "timeout": 300}
    ov_msg = await channel.send("<@1> <@2>", embed=gm.vote_embed(old_vote, guild),
                                view=gm_mod.vote_view("oldv", [(gids[0], "A"), (gids[1], "B")]))
    old_vote["message_id"] = ov_msg.id
    async with gm.config.guild(guild).votes() as v:
        v["oldv"] = dict(old_vote)
    async with gm.config.guild(guild).play_sessions() as s:
        s["old1"]["vote_id"] = "oldv"
    await gm.on_vote_button(click(alex, ov_msg), "oldv", gids[0])
    check("embed" in ov_msg.edits[-1] and "Voted (1/2)" in ov_msg.embeds[0].fields[0].name, "old vote: embed updated")
    await gm.finish_vote(guild, "oldv", "test")
    check("Results" in ov_msg.edits[-1]["embed"].title and ov_msg.edits[-1]["view"] is None, "old vote: embed results")
    check("embed" in old_msg.edits[-1] and not ui.is_card(old_msg), "old session refreshed as an embed")
    await gm.end_session(guild, "old1")
    check(old_msg.edits[-1]["view"] is None and "(ended)" in old_msg.edits[-1]["embed"].title, "old session ends as embed")
    i = click(alex, old_msg)
    await gm.on_session_button(i, "join", "old1")
    check(old_msg.edits[-1] == {"view": None}, "gone session: old embed message loses its buttons")

    # ================= requests =================
    text = await gm.request_games_text(guild, channel, alex, ["Zork"], "own")
    text += await gm.request_games_text(guild, channel, alex, ["Myst"], "own")   # one at a time: single cards
    check(text.startswith("✅ **Requested:** Zork"), text)
    reqs = await gm.config.guild(guild).game_requests()
    by_name = {r["name"]: r for r in reqs.values()}
    zmsg = channel.messages[by_name["Zork"]["message_id"]]
    mmsg = channel.messages[by_name["Myst"]["message_id"]]
    ztext = card_text(zmsg)
    check(ui.is_card(zmsg) and card_color(zmsg) == ui.ATTENTION and ztext.startswith("### 🎮 Game request: Zork")
          and "**Zork**\n-# Requested by <@2>" in ztext and "approving also adds it to their library" in ztext, ztext)
    check([b.label for b in card_buttons(zmsg)] == ["Approve", "Deny"]
          and card_buttons(zmsg)[0].style == discord.ButtonStyle.primary
          and custom_ids(zmsg) == [f"gm:r:approve:{by_name['Zork']['id']}", f"gm:r:deny:{by_name['Zork']['id']}"],
          "Approve/Deny inside the card")
    check(pinged(zmsg.kw) == "none" and by_name["Zork"]["id"] not in ztext, "request card doesn't ping the requester")
    i = click(alex, zmsg)
    await gm.on_request_button(i, "approve", by_name["Zork"]["id"])
    check(i.response.calls[-1][1].startswith("🔒"), "members can't approve")
    await gm.on_request_button(click(brad, zmsg), "approve", by_name["Zork"]["id"])
    check(card_color(zmsg) == ui.SUCCESS and card_text(zmsg).startswith("### 🎮 Game request: Zork")
          and "✅ **Approved**\n-# Requested by <@2> · approved by <@1>" in card_text(zmsg) and not card_buttons(zmsg)
          and pinged(zmsg.edits[-1]) == "none", card_text(zmsg))
    note = channel.sent[-1]
    check(note.content == f"✅ <@2>, **Zork** was added to the server library: "
                          f"https://discord.com/channels/{guild.id}/{channel.id}/{zmsg.id}"
          and pinged(note.kw) == [2], f"the requester gets a one-line ping linking to the card: {note.content}")
    check("-# It's in their library, not marked installed. If it's installed: `!games install Zork`"
          in card_text(zmsg), card_text(zmsg))
    await gm.on_request_button(click(brad, mmsg), "deny", by_name["Myst"]["id"])
    check(card_color(mmsg) == ui.DANGER and card_text(mmsg).startswith("### 🎮 Game request: Myst\n**Denied**"), card_text(mmsg))
    # a second click: already handled, card left as it is
    edits = len(mmsg.edits)
    i = click(brad, mmsg)
    await gm.on_request_button(i, "deny", by_name["Myst"]["id"])
    check(len(mmsg.edits) == edits and "already handled" in i.followup.calls[-1][0], "double click handled")
    # Steam link button on requests with a known app ID
    await gm.request_games_text(guild, channel, alex, ["Halo Infinite"], appids={"Halo Infinite": 1240440})
    hmsg = channel.sent[-1]
    check([b.url for b in card_buttons(hmsg)][-1] == "https://store.steampowered.com/app/1240440",
          "View on Steam link inside the request card")
    # an old embed request is resolved the old way
    old_req_msg = await channel.send(embed=discord.Embed(title="📨 Game request: Doom"), view=gm_mod.request_view("oldr"))
    async with gm.config.guild(guild).game_requests() as r:
        r["oldr"] = {"id": "oldr", "name": "Doom", "description": "", "requested_by": "3", "requested_at": now,
                     "for_action": None, "channel_id": channel.id, "message_id": old_req_msg.id, "steam_appid": None}
    await gm.resolve_request(guild, "oldr", brad, approve=False)
    check(old_req_msg.edits[-1]["view"] is None and old_req_msg.edits[-1]["embed"].title == "❌ Denied: Doom"
          and not ui.is_card(old_req_msg), "old embed request edited as an embed")

    # install request: ATTENTION card, pings exactly the people asked
    out = await run(brad, '!games admin requestinstall "Rocket League" Alex Sam')
    check(ui.is_card(out) and card_color(out) == ui.ATTENTION and "<@2>, <@3>: please install **Rocket League**"
          in card_text(out) and pinged(out.kw) == [2, 3], f"install request: {card_text(out)} {pinged(out.kw)}")
    check([b.label for b in card_buttons(out)] == ["I've installed it", "View on Steam"]
          and all(b.emoji for b in card_buttons(out)), "install + store buttons, both with emoji")

    # ================= settings card =================
    out = await run(brad, "!games admin settings")
    stext = card_text(out)
    check(ui.is_card(out) and card_color(out) == ui.BRAND and stext.startswith("### 🎮 Game night settings"), stext[:60])
    check("**Who can do what**\n**Game admin role** · none (server admins only)" in stext
          and "**Free Epic games** · Off" in stext and "**Sale alerts** · Off" in stext, stext)
    check("⚠️ I need the **Manage Events** permission" in stext, "missing Manage Events is a ⚠️ line in the card")
    check(stext.endswith("· Staff only") and "-# !help games admin shows how to change these" in stext and "[p]" not in stext,
          stext.splitlines()[-1])
    check(any(isinstance(i, discord.ui.Separator) for i in out.view.walk_children()) and pinged(out.kw) == "none",
          "separator, no pings")

    # ================= library results are plain lines =================
    out = await run(alex, "!games own Deadlock")
    check(out.content.startswith("✅ **Added to your library:** Deadlock") and not out.embeds and not ui.is_card(out)
          and pinged(out.kw) == "none", out.content)
    out = await run(alex, "!games own Minecraft")
    check(isinstance(out.view, gm_mod.UnknownGamesView) and ui.is_card(out)
          and "❌ **Not in the server's library:** Minecraft" in card_text(out)
          and [b.label for b in card_buttons(out)] == ["Request it"] and pinged(out.kw) == "none",
          "unknown game: the result and its button in a card")
    out = await run(brad, "!games admin add Tetris")
    check(out.content.startswith("✅ **Added (1):** Tetris") and not out.embeds, out.content)

    # ================= menus: expiry, paging, owner check =================
    await gm.add_games(guild, brad, [f"Filler {n:02d}" for n in range(30)])
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.library_command(i, None, "own", ephemeral=True)
    kind, _, kw = i.response.calls[-1]
    picker = kw["view"]
    check(kind == "send" and kw["ephemeral"] and isinstance(picker, gm_mod.GamePickerView)
          and pinged(kw) == "none", "slash picker: an ephemeral card")
    pmsg = i.sent_message
    check(card_text(pmsg).endswith("-# Page 1/2 · Only Alex can use this menu"), card_text(pmsg).splitlines()[-1])
    nxt = next(b for b in card_buttons(picker) if b.label == "Next")
    prev = next(b for b in card_buttons(picker) if b.label == "Prev")
    check(prev.disabled and not nxt.disabled, "page 1: Prev off, Next on")
    await nxt.callback(click(alex, pmsg))
    check("Page 2/2" in card_text(pmsg) and next(b for b in card_buttons(pmsg) if b.label == "Next").disabled,
          "Next pages inside the card")
    o = click(sam, pmsg)
    check(not await picker.interaction_check(o) and o.response.calls[-1][1].startswith("🔒"), "not your menu")
    await picker.on_timeout()
    check(card_text(pmsg).endswith("-# Expired. Nothing was saved.")
          and all(b.disabled for b in action_buttons(pmsg)), "picker card expires")

    out = await run(sam, "!games newprofile")
    wizard = out.view
    check(isinstance(wizard, gm_mod.ProfileWizard) and ui.is_card(out)
          and "### 🎮 Profile setup · 1 of 5: Your timezone" in card_text(out), card_text(out)[:80])
    await wizard.on_timeout()
    check(card_text(out).endswith("-# Expired. Everything you saved is kept.")
          and all(getattr(c, "disabled", True) for c in out.view.walk_children()
                  if isinstance(c, (discord.ui.Button, discord.ui.Select))), "wizard card expires")

    # slash newprofile: an ephemeral card
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.slash_newprofile.callback(gm, i)
    kind, _, kw = i.response.calls[-1]
    check(kind == "send" and kw["ephemeral"] and isinstance(kw["view"], gm_mod.ProfileWizard), "slash wizard ephemeral")

    # slash request after a defer: the name check is an ephemeral followup card, the result a private line
    async def fake_steam(name):
        return ("Portal 2", 620) if name.lower() == "portl 2" else None
    gm_mod.steam_exact_title = fake_steam

    async def finder(name, member):
        return {"title": "Portal 2", "steam_appid": 620} if name.lower() == "portl 2" else None
    gm.bot.get_cog = (lambda real: (lambda n: type("C", (), {"find_game_title": staticmethod(finder)})()
                                    if n == "ClaudeChat" else real(n)))(gm.bot.get_cog)
    i = FakeInteraction(bot, guild, alex, channel)
    task = asyncio.create_task(gm.slash_request.callback(gm, i, "portl 2"))
    await asyncio.sleep(0.05)
    content, kw = i.followup.calls[-1]
    check(content is None and kw["ephemeral"] and isinstance(kw["view"], gm_mod.NameCheckView)
          and "**Portal 2**\n-# You typed `portl 2` · Steam's name for it" in card_text(kw["view"]) and pinged(kw) == "none", "name check card")
    view = kw["view"]
    await card_buttons(view)[0].callback(FakeInteraction(bot, guild, alex, channel, message=FakeMessage(channel)))
    await asyncio.wait_for(task, 5)
    content, kw = i.followup.calls[-1]
    check(content.startswith("✅ **Requested:** Portal 2") and kw["ephemeral"], f"slash request result: {content}")

    # slash session: posted card in the channel (no pings) and a private ✅
    i = FakeInteraction(bot, guild, sam, channel)
    await gm.slash_session.callback(gm, i, "Late game", None, False)
    posted = channel.sent[-1]
    check(ui.is_card(posted) and "Late game" in card_text(posted) and pinged(posted.kw) == "none"
          and i.response.calls[-1][1] == "✅ Session posted." and i.response.calls[-1][2]["ephemeral"],
          "slash session: card + private line")

    for task in list(gm.vote_tasks.values()):
        task.cancel()
    await bot.remove_cog("GameManager")


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
