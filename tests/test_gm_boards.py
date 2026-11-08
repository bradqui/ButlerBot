"""GameManager phase 3 (boards): every list is a paged card, paging works, private lists stay private, no pings."""
import asyncio
from datetime import timedelta

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, card_buttons, card_text, discord, load

gm_mod = load("gamemanager", "gamemanager")
ui = gm_mod.ui
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


def no_pings(kw) -> bool:
    am = kw.get("allowed_mentions")
    return am is not None and not am.everyone and not am.users and not am.roles and not am.replied_user


def is_board(msg) -> bool:
    return msg is not None and isinstance(getattr(msg, "view", None), ui.Board)


def nav(msg):
    return [b for b in card_buttons(msg) if b.custom_id and b.custom_id.startswith("board:")]


async def main():
    guild = FakeGuild()
    brad, alex, chris = guild.add(1, "Brad", admin=True), guild.add(2, "Alex"), guild.add(3, "Chris")
    bot = TestBot(guild)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    channel = guild.channel

    async def run(author, content):
        msg = FakeMessage(channel, content, author=author)
        ctx = await bot.get_context(msg)
        before = len(channel.sent)
        await bot.invoke(ctx)
        return channel.sent[-1] if len(channel.sent) > before else None

    # ================= empty lists stay one ❓/⚠️ line =================
    out = await run(alex, "!games requests")
    check(out.content == "❓ No pending requests." and not is_board(out), out.content)
    out = await run(alex, "!games sessions")
    check(out.content.startswith("❓ No active sessions"), out.content)
    out = await run(alex, "!games recurring")
    check(out.content.startswith("❓ No repeating sessions"), out.content)
    out = await run(alex, "!games installrequests")
    check(out.content == "❓ No install requests.", out.content)
    out = await run(alex, "!games list")
    check(out.content.startswith("⚠️ No games have been added yet"), out.content)
    out = await run(alex, "!games library")
    check(out.content.startswith("⚠️ Your library is empty"), out.content)
    out = await run(alex, "!games wanted")
    check(out.content.startswith("❓ Nobody has a wishlist yet"), out.content)
    await gm.send_list(Ctx(guild, alex), [], "Nothing")
    check(channel.sent[-1].content == "❓ Nothing to show.", "send_list with no rows")

    # ================= a 45-game library pages =================
    names = [f"Game {n:02d}" for n in range(45)]
    await gm.add_games(guild, brad, names)
    games = await gm.config.guild(guild).games()
    by_name = {g["name"]: gid for gid, g in games.items()}
    async with gm.config.guild(guild).users() as users:
        for n in range(20):
            gm_mod.apply_change(gm_mod.user_entry(users, alex.id), by_name[names[n]], "own")
        for n in range(5):
            gm_mod.apply_change(gm_mod.user_entry(users, alex.id), by_name[names[n]], "install")
        for n in range(10):
            gm_mod.apply_change(gm_mod.user_entry(users, chris.id), by_name[names[n]], "own")
        gm_mod.apply_change(gm_mod.user_entry(users, chris.id), by_name[names[0]], "install")
        users["777"] = {"owned": [by_name[names[0]]], "installed": [], "ranks": {}}   # someone who left
        gm_mod.user_entry(users, alex.id)["ranks"][by_name[names[3]]] = 1

    out = await run(alex, "!games list")
    text = card_text(out)
    check(is_board(out) and not out.content and not out.embeds, "library list is a board")
    check(text.startswith("### 🎮 Server library"), text[:60])
    check("**Game 00** 💾\n-# 2 own · 2 installed" in text,
          "two-line row: bold name, 💾 at the end, counts underneath (people who left don't count)")
    check("**Game 05**\n-# 2 own" in text and "Game 07" in text and "Game 08" not in text, "8 rows on page 1")
    check("-# Page 1 of 6 · 45 games · 💾 = you have it installed" in text, text[-90:])
    prev, nxt = nav(out)
    check(prev.disabled and not nxt.disabled and prev.emoji.name == "◀️", "◀ disabled on page 1")
    check(no_pings(out.kw), "lists never ping")
    rows = [i.content for i in out.view.walk_children()
            if isinstance(i, discord.ui.TextDisplay) and i.content.startswith("**Game ")]
    check(len(rows) == 8 and all(r.count("\n") == 1 and "\n-# " in r and " · " not in r.split("\n")[0] for r in rows),
          f"each row is its own block: a main line, details underneath: {rows[:2]}")
    jump = [i for i in out.view.walk_children() if isinstance(i, discord.ui.Select)]
    check(jump and jump[0].options[0].label == "Page 1" and jump[0].options[0].description == "Game 00 – Game 07",
          "a 6-page board gets a Jump to menu with plain row names")

    # paging: anyone can page, and it redraws the same message
    i = FakeInteraction(bot, guild, chris, channel, message=out)
    await nxt.callback(i)
    kind, kw = i.response.calls[-1]
    text = card_text(out)
    check(kind == "edit" and "Game 08" in text and "Game 07" not in text and "Page 2 of 6" in text,
          "▶ shows page 2 (paged by someone else)")
    check(no_pings(kw), "paging doesn't ping")
    prev, nxt = nav(out)
    check(not prev.disabled and not nxt.disabled, "both arrows live on a middle page")
    for _ in range(4):
        await nav(out)[1].callback(FakeInteraction(bot, guild, alex, channel, message=out))
    text = card_text(out)
    check("Game 44" in text and "Page 6 of 6" in text and nav(out)[1].disabled, "last page")
    await nav(out)[0].callback(FakeInteraction(bot, guild, alex, channel, message=out))
    check("Page 5 of 6" in card_text(out), "◀ goes back")
    # expiry greys the arrows out with a note
    board = out.view
    board.message = out
    await board.on_timeout()
    check(all(b.disabled for b in nav(out)) and "Run the command again to page through it." in card_text(out),
          "expired board says how to get a fresh one")

    # ================= search, whoowns, whoinstalled =================
    out = await run(alex, "!games search game 4")
    text = card_text(out)
    check(is_board(out) and "🎮 Games matching “game 4”" in text and "5 games" in text and not nav(out)
          and "**Game 40**\n-# 0 own" in text, "search: a one-page board has no arrows")
    out = await run(alex, "!games whoowns Game 00")
    text = card_text(out)
    check(is_board(out) and "### 🎮 Who owns Game 00" in text and "**Alex** 💾" in text and "**Chris** 💾" in text
          and "2 owners, 2 installed" in text and no_pings(out.kw), text)
    out = await run(alex, "!games whoinstalled Game 03")
    text = card_text(out)
    check("### 🎮 Who has Game 03 installed" in text and "**Alex**\n-# Their #1" in text and "Chris" not in text,
          f"a name-only row, with their rank as the detail when they have one: {text}")

    # ================= your library (ranked first) =================
    out = await run(alex, "!games library")
    text = card_text(out)
    check(is_board(out) and "### 🎮 Alex's library" in text and "**1. Game 03** 💾" in text
          and text.index("Game 03") < text.index("Game 00") and "**Game 06**\n**Game 07**" in text,
          "ranked games first, rank inside the bold; name-only rows")
    check("Page 1 of 3 · 20 games, 5 installed · 💾 = installed" in text, text[-80:])

    # ================= shared and top (top has no cap: it pages) =================
    out = await run(alex, "!games shared Alex Chris")
    text = card_text(out)
    check(is_board(out) and "### 🎮 Owned by everyone" in text and "With Alex, Chris" in text
          and "10 games" in text and "**Game 00** 💾\n-# 2 of 2 installed" in text
          and "**Game 05**\n-# 0 of 2 installed" in text, text)
    async with gm.config.guild(guild).users() as users:
        for n in range(45):
            gm_mod.apply_change(gm_mod.user_entry(users, brad.id), by_name[names[n]], "own")
    out = await run(alex, "!games top")
    text = card_text(out)
    check(is_board(out) and "### 🎮 Top games" in text and "Page 1 of 6" in text, "top: all 45 games, paged")
    check("**1. Game 03** 💾\n-# 3 of 3 own · 1 installed" in text and "**6. Game 05**\n-# 3 of 3 own\n" in text,
          f"top row: rank inside the bold, counts underneath: {text}")
    out = await run(alex, "!games top shared")
    check("Only games owned by everyone." in card_text(out), "filters shown under the title")

    # ================= requests, sessions, recurring: mentions without pings =================
    async with gm.config.guild(guild).game_requests() as requests:
        requests["r1"] = {"id": "r1", "name": "Deadlock", "requested_by": "2", "channel_id": channel.id}
    out = await run(brad, "!games requests")
    text = card_text(out)
    check(is_board(out) and "**Deadlock**\n-# Requested by <@2>" in text and no_pings(out.kw), text)
    check("Game admins approve with !games admin approve <game>" in text, "request footer hint")

    await gm.create_session(Ctx(guild, alex), "Raid night")
    out = await run(alex, "!games sessions")
    text = card_text(out)
    check(is_board(out) and "### 🎮 Active sessions" in text and "**\n-# Hosted by <@2> · 1 player · ID `" in text
          and no_pings(out.kw), text)

    nxt_start = gm_mod.utcnow() + timedelta(days=3)
    async with gm.config.guild(guild).recurring() as rec:
        rec["w1"] = {"id": "w1", "title": "Weekly raid", "weekday": 4, "hour": 21, "minute": 0, "interval": 7,
                     "tz": "UTC", "next_start": nxt_start.isoformat(), "host_id": "3", "channel_id": channel.id}
    out = await run(alex, "!games recurring")
    text = card_text(out)
    check(is_board(out) and "### 🎮 Repeating sessions" in text and "**Weekly raid**\n-# Every Friday at 9 PM (UTC) · next"
          in text and no_pings(out.kw), text)

    # ================= vote results: an empty tally is the board's empty text =================
    sid = next(iter(await gm.config.guild(guild).play_sessions()))
    async with gm.config.guild(guild).play_sessions() as sessions:
        sessions[sid]["participants"].append("3")
    await gm.start_vote(Ctx(guild, alex), session_id=sid)
    out = await run(alex, "!games results")
    text = card_text(out)
    check(is_board(out) and text.startswith("### 🗳️ Votes so far") and "No votes yet." in text
          and "voted · ID" in text, text)
    async with gm.config.guild(guild).votes() as votes:
        vote = next(iter(votes.values()))
        gid = next(iter(vote["names"]))
        vote["tallies"][gid] = 2
    out = await run(alex, "!games results")
    check("**\n-# 2 votes" in card_text(out), card_text(out))
    out = await run(alex, "!games sessions")
    check("** 🗳️\n-# " in card_text(out) and "· 🗳️ = voting now" in card_text(out),
          f"a session that's voting is marked at the end of its main line: {card_text(out)}")
    for vid in list(await gm.config.guild(guild).votes()):
        await gm.cancel_vote(guild, vid)

    # ================= install requests =================
    async with gm.config.guild(guild).install_requests() as ireq:
        ireq["i1"] = {"id": "i1", "game_id": by_name["Game 01"], "target_users": ["2", "3"], "installed_by": ["2"]}
    out = await run(alex, "!games installrequests")
    check(is_board(out) and "**Game 01**\n-# 1 of 2 installed" in card_text(out), card_text(out))

    # ================= wishlist and most-wanted =================
    async with gm.config.guild(guild).wishlist() as wl:
        wl["620"] = {"appid": 620, "name": "Portal 2", "users": ["2", "3"], "checked_at": "x",
                     "price": {"discount": 40, "final_text": "$5.99", "initial_text": "$9.99"}, "alerted": 40}
        wl["400"] = {"appid": 400, "name": "Portal", "users": ["2"], "checked_at": None, "price": None, "alerted": 0}
    out = await run(alex, "!games wishlist")
    text = card_text(out)
    check(is_board(out) and "### 🎮 Alex's wishlist" in text
          and "**[Portal 2](https://store.steampowered.com/app/620)**\n-# **40% off**: $5.99 (was $9.99)" in text
          and "**[Portal](https://store.steampowered.com/app/400)**\n**[Portal 2]" in text
          and "2 games · Sale alerts aren't turned on" in text, text)
    out = await run(brad, "!games wanted")
    text = card_text(out)
    check(is_board(out) and "### 🎮 Most-wanted games" in text and "\n-# Wanted by 2: Alex and Chris · **40% off**"
          in text and text.index("Portal 2") < text.index("[Portal]"), text)

    # ================= slash: personal lists are private, others' are public =================
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.slash_library.callback(gm, i, None)
    kind, content, kw = i.response.calls[0]
    check(kind == "send" and kw.get("ephemeral") is True and isinstance(kw["view"], ui.Board) and no_pings(kw),
          "/games library: private board")
    board = kw["view"]
    check(board.timeout == gm_mod.LIST_PRIVATE_TIMEOUT and board.message in (i, i.sent_message)
          and board.message is not None,
          "private board expires before its token and edits through the interaction")
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.slash_library.callback(gm, i, chris)
    kind, content, kw = i.response.calls[0]
    check(kw.get("ephemeral") is False and isinstance(kw["view"], ui.Board)
          and "Chris's library" in card_text(kw["view"]), "/games library @someone: public board")
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.slash_wishlist.callback(gm, i, None)
    kind, content, kw = i.response.calls[0]
    check(kw.get("ephemeral") is True and "Portal 2" in card_text(kw["view"]), "/games wishlist: private board")

    # after a defer the board goes out as a followup, still private
    i = FakeInteraction(bot, guild, alex, channel)
    await i.response.defer(ephemeral=True, thinking=True)
    await gm.show_library(i, alex, ephemeral=True)
    content, kw = i.followup.calls[-1]
    check(kw.get("ephemeral") is True and kw.get("wait") is True and isinstance(kw["view"], ui.Board)
          and no_pings(kw), "deferred: private board as a followup")

    i = FakeInteraction(bot, guild, alex, channel)
    await gm.slash_whoowns.callback(gm, i, "Game 00")
    kind, content, kw = i.response.calls[0]
    check(kw.get("ephemeral") is False and "Who owns Game 00" in card_text(kw["view"]) and no_pings(kw),
          "/games whoowns: public board, no pings")
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.slash_top.callback(gm, i, False, False)
    check(isinstance(i.response.calls[0][2]["view"], ui.Board), "/games top: board")
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.slash_shared.callback(gm, i, chris, None, None, None, False)
    check("Owned by everyone" in card_text(i.response.calls[0][2]["view"]), "/games shared: board")

    # ================= big rows stay inside Discord's limits =================
    long_rows = [f"**{'X' * 300} {n}** · <@{n}>" for n in range(40)]
    await gm.send_list(Ctx(guild, alex), long_rows, "🎮 Long rows")
    out = channel.sent[-1]
    check(is_board(out) and len(out.view.pages) > 3, "long rows break into more pages by size")

    # butler lookups still return plain text
    text = await gm.guide_call_tool("games_library", {"member": "Alex"}, alex)
    check(isinstance(text, str) and "Game 03" in text, text[:80])

    passed = sum(ok for ok, _ in results)
    print(f"{passed}/{len(results)} checks passed")


asyncio.run(main())
