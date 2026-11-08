"""GameManager `games deals`: games on sale for a group, from the library, wishlists and Steam's store (AI picks)."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from harness import (FakeGuild, FakeInteraction, FakeMessage, TestBot, card_color, card_text, dcommands, discord,
                     load)

gm_mod = load("gamemanager", "gamemanager")
claude_mod = load("claude", "claude")
ui = gm_mod.ui
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


class FakeClaude(dcommands.Cog, name="ClaudeChat"):
    def __init__(self):
        self.calls, self.replies = [], []

    async def complete(self, member, channel, *, system, messages, **kw):
        self.calls.append({"member": member, "system": system, "messages": messages, **kw})
        reply = self.replies.pop(0) if self.replies else "[]"
        return (None, reply) if reply.startswith(("⏳", "❌")) else (reply, None)


class Ctx:
    def __init__(self, guild, author):
        self.guild, self.author, self.channel = guild, author, guild.channel
        self.clean_prefix = "!"

    async def send(self, content=None, **kw):
        return await self.channel.send(content, **kw)

    def typing(self):
        return self.channel.typing()


def selects(target) -> list:
    view = getattr(target, "view", target)
    out = []
    for item in view.walk_children():
        inner = item.item if isinstance(item, discord.ui.DynamicItem) else item
        if isinstance(inner, discord.ui.Select) and inner not in out:
            out.append(inner)
    return out


def price(discount, final=999):
    initial = round(final * 100 / (100 - discount)) if discount else final
    return {"final": final, "initial": initial, "discount": discount, "final_text": f"${final / 100:.2f}",
            "initial_text": f"${initial / 100:.2f}"}


STORE_ROW = '''<a href="https://store.steampowered.com/app/{appid}/x/" data-ds-appid="{appid}" data-ds-itemkey="App_{appid}"
 data-ds-tagids="[1685,3859,9999]" class="search_result_row">
 <div class="search_name ellipsis"><span class="title">{name}</span></div>
 <div class="search_released responsive_secondrow">Oct 1, 2026</div>
 <div class="search_reviewscore responsive_secondrow"><span class="search_review_summary positive"
 data-tooltip-html="Very Positive&lt;br&gt;91% of the 12,345 user reviews for this game are positive."></span></div>
 <div class="search_price_discount_combined responsive_secondrow" data-price-final="{final}">
 {price}</div></a>'''
SALE_PRICE = ('<div class="discount_block search_discount_block" data-price-final="{final}" data-discount="{discount}">'
              '<div class="discount_pct">-{discount}%</div><div class="discount_prices"><div class="discount_original_'
              'price">$20.00</div><div class="discount_final_price">${dollars}</div></div></div>')
FREE_PRICE = ('<div class="discount_block no_discount search_discount_block"><div class="discount_prices">'
              '<div class="discount_final_price free">Free</div></div></div>')


def store_page():
    rows = [STORE_ROW.format(appid=901, name="Lantern Keepers &amp; Co", final=500,
                             price=SALE_PRICE.format(final=500, discount=75, dollars="5.00")),
            STORE_ROW.format(appid=902, name="Free Brawl", final=0, price=FREE_PRICE),
            '<a href="https://store.steampowered.com/bundle/5/" data-ds-bundleid="5" class="search_result_row">'
            '<span class="title">A Bundle</span></a>']
    return "\n".join(rows)


def days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%b %d, %Y").replace(" 0", " ")


RECENT = days_ago(10)


def store_game(appid, name, discount=50, reviews="Very Positive", tags=("Co-op",), released=RECENT):
    return {"appid": appid, "name": name, "price": price(discount) if discount is not None else None,
            "reviews": reviews, "review_count": 5000, "tags": list(tags), "released": released}


async def main():
    # ---- pure helpers ----
    found = gm_mod.parse_store_results(store_page(), {1685: "Co-op", 3859: "Multiplayer"})
    check([g["appid"] for g in found] == [901, 902], f"bundles skipped: {found}")
    first = found[0]
    check(first["name"] == "Lantern Keepers & Co" and first["price"]["discount"] == 75
          and first["price"]["final_text"] == "$5.00" and first["price"]["initial_text"] == "$20.00"
          and first["price"]["initial"] == 2000 and first["reviews"] == "Very Positive"
          and first["review_count"] == 12345 and first["tags"] == ["Co-op", "Multiplayer"]
          and first["released"] == "Oct 1, 2026", f"store row parsed: {first}")
    check(found[1]["price"] is None, "a free game has no price")

    pp = gm_mod.parse_picks
    check(pp('```json\n[{"n": 2, "why": "Like  Barony,\\nbut louder."}, {"n": 2, "why": "again"}, {"n": 9}, '
             '{"n": "1", "why": "ok"}, "junk"]\n```', 3) == [(2, "Like Barony, but louder."), (1, "ok")],
          "picks: fences, repeats and out-of-range numbers")
    check(pp("Sorry, no.", 3) == [] and pp(None, 3) == [] and pp("[{bad json", 3) == [], "unreadable replies")
    check(len(pp(json.dumps([{"n": i, "why": "x" * 400} for i in range(1, 10)]), 9)) == gm_mod.DEAL_PICKS
          and len(pp(json.dumps([{"n": 1, "why": "x" * 400}]), 1)[0][1]) <= gm_mod.DEAL_WHY_CHARS,
          "at most DEAL_PICKS, reasons shortened")
    check(gm_mod.link_name("Thing [Beta]", 7) == "**[Thing \\[Beta\\]](https://store.steampowered.com/app/7)**",
          gm_mod.link_name("Thing [Beta]", 7))

    # The store list is cached per mode
    fetches = []

    async def fake_get_json(url, params=None, timeout=8):
        fetches.append((url, dict(params or {})))
        if url == gm_mod.STEAM_TAGS_URL:
            return [{"tagid": 1685, "name": "Co-op"}]
        return {"results_html": store_page() if params["start"] == "0" else ""}
    real_get_json = gm_mod._get_json
    gm_mod._get_json = fake_get_json
    gm_mod._STORE_LISTS.clear()
    listed = await gm_mod.steam_store_list("sale")
    again = await gm_mod.steam_store_list("sale")
    store_calls = [p for u, p in fetches if u == gm_mod.STEAM_STORE_SEARCH_URL]
    check(len(listed) == 2 and again is listed and len(store_calls) == 2 and store_calls[0]["specials"] == "1"
          and store_calls[0]["category3"] == "1" and store_calls[0]["category1"] == "998",
          f"store list fetched once (stops at an empty page): {store_calls}")
    await gm_mod.steam_store_list("new")
    check([p for u, p in fetches if u == gm_mod.STEAM_STORE_SEARCH_URL][-1]["filter"] == "popularnew",
          "new releases use popularnew")
    gm_mod._get_json = real_get_json
    gm_mod._STORE_LISTS.clear()

    # ---- setup ----
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex = guild.add(2, "Alex")
    sam = guild.add(3, "Sam")
    jo = guild.add(4, "Jo")
    channel = guild.channel
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    claude = FakeClaude()
    await bot.add_cog(claude)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()

    prices = {100: price(60), 101: price(0), 102: price(25), 103: price(80), 200: price(50), 201: price(0)}
    price_calls = []

    async def fake_prices(appids):
        price_calls.append(list(appids))
        return {a: prices.get(a) for a in appids}
    gm_mod.steam_prices = fake_prices
    store = [store_game(100, "Deep Rock Galactic"), store_game(300, "Lantern Keepers"),
             store_game(301, "Grim Pitch", reviews="Mostly Negative"), store_game(302, "Full Price", discount=0),
             store_game(303, "Free Thing", discount=None), store_game(304, "Ship of Fools"),
             store_game(305, "Wizard Kitchen")]
    store_modes = []

    async def fake_store(mode):
        store_modes.append(mode)
        return store if mode == "sale" else [store_game(400, "Brand New", discount=None), store_game(401, "Fresh Co-op"),
                                             store_game(402, "Last Year", released=days_ago(200)),
                                             store_game(403, "Coming Soon", released="Coming soon")]
    gm_mod.steam_store_list = fake_store

    await gm.add_games(guild, brad, ["Deep Rock Galactic", "Barony", "Helldivers 2", "Lethal Company", "No Steam"],
                       {"Deep Rock Galactic": 100, "Barony": 101, "Helldivers 2": 102, "Lethal Company": 103})
    await gm.change_library(guild, brad, ["Deep Rock Galactic", "Barony", "Helldivers 2"], "own")
    await gm.change_library(guild, alex, ["Deep Rock Galactic", "Barony"], "install")
    await gm.change_library(guild, sam, ["Barony"], "own")
    await gm.change_library(guild, jo, ["Lethal Company"], "own")
    async with gm.config.guild(guild).users() as users:
        users["2"]["ranks"] = {next(g for g, d in (await gm.config.guild(guild).games()).items()
                                    if d["name"] == "Deep Rock Galactic"): 1}
    await gm.add_wants(guild, sam, [("Hades II", 200), ("Calm Seas", 201)])
    await gm.add_wants(guild, alex, [("Hades II", 200)])

    # ---- who it's for ----
    ctx = Ctx(guild, sam)
    label, members = await gm.deal_group(ctx, [])
    check(label == "the server" and [m.display_name for m in members] == ["Alex", "Brad", "Jo", "Sam"],
          f"everyone with a library or wishlist: {[m.display_name for m in members]}")
    check(await gm.deal_group(ctx, ["me"]) == ("you", [sam]), "me")
    label, members = await gm.deal_group(ctx, ["Alex", "me", "Brad"])
    check(label == "Sam, Alex and Brad" and members == [sam, alex, brad], f"named people plus the asker: {label}")
    check(await gm.deal_group(ctx, ["Nobody"]) is None and "Couldn't find" in channel.sent[-1].content,
          "an unknown name is explained")
    async with gm.config.guild(guild).play_sessions() as sessions:
        sessions["abc12345"] = {"id": "abc12345", "title": "Raid night", "participants": ["1", "3", "4"],
                                "channel_id": channel.id, "created_at": "2026-11-01T00:00:00+00:00",
                                "host_id": "1", "message_id": 77}
    label, members = await gm.deal_group(ctx, ["session"])
    check(label == "Raid night" and members == [brad, sam, jo], f"a session's players: {label}")
    empty = FakeGuild(gid=2)
    lonely = empty.add(9, "Lonely")
    bot2 = TestBot(empty)
    gm2 = gm_mod.GameManager(bot2)
    check(await gm2.deal_group(Ctx(empty, lonely), []) is None
          and "Nobody here has a library" in empty.channel.sent[-1].content, "an empty server says so")

    # ---- the card: Sam, Alex and Brad ----
    claude.replies = ['[{"n": 2, "why": "Co-op chaos like Barony."}, {"n": 1, "why": "Your favorite, for Sam."}, '
                      '{"n": 99, "why": "made up"}]']
    before = len(channel.sent)
    await gm.show_deals(ctx, "Sam, Alex and Brad", [sam, alex, brad])
    check(len(channel.sent) == before + 1, "one card")
    card = channel.sent[-1]
    text = card_text(card)
    check(card_color(card) == ui.HIGHLIGHT and text.startswith("### 🎮 Deals for Sam, Alex and Brad"), text[:80])
    owned_at, wish_at, ai_at = (text.find("**Some of you have these**"), text.find("**On your wishlists**"),
                                text.find("**You might like**"))
    check(0 < owned_at < wish_at < ai_at, f"sections in order: {owned_at, wish_at, ai_at}")
    check("[Deep Rock Galactic](https://store.steampowered.com/app/100)" in text[owned_at:wish_at]
          and "Alex and Brad have it · Sam doesn’t" in text and "**60% off**" in text,
          "a library game on sale that some of the group lack")
    check("Helldivers 2" in text and "Brad has it · Alex and Sam don’t" in text, "one owner")
    check("[Barony]" not in text, "not on sale (and everyone has it): left out")
    check("Lethal Company" not in text, "only Jo (not in the group) has it: left out")
    check("[Hades II]" in text[wish_at:ai_at] and "wanted by Alex and Sam" in text and "Calm Seas" not in text,
          "wishlisted games on sale, with who wants them")
    picks = text[ai_at:]
    check("Picked by AI from Steam's multiplayer sales." in picks
          and picks.find("Ship of Fools") < picks.find("Lantern Keepers")
          and "Co-op chaos like Barony." in picks and "made up" not in picks, f"AI picks in its order: {picks}")
    call = claude.calls[-1]
    prompt = call["messages"][0]["content"]
    check(call["member"] == sam and call["persona"] is False and "a group of 3" in call["system"]
          and "on sale right now" in call["system"], "one AI call, no persona, sized for the group")
    check("Deep Rock Galactic: 2 of 3 own it, 1 installed; favorite of Alex #1" in prompt
          and "Games they want: Hades II (2), Calm Seas (1)" in prompt, f"the group's taste: {prompt[:600]}")
    listing = prompt.split("The list:\n")[1]
    check("Deep Rock Galactic" not in listing and "Grim Pitch" not in listing and "Full Price" not in listing
          and "Free Thing" not in listing and listing.startswith("1. Lantern Keepers | 50% off: $9.99 (was $19.98)")
          and "Very Positive (5,000 reviews) | Co-op" in listing,
          f"owned, poorly reviewed and not-discounted games aren't offered: {listing}")
    menus = selects(card)
    check([s.custom_id for s in menus] == ["gm:deal:want", "gm:deal:own"]
          and [o.label for o in menus[0].options] == ["Deep Rock Galactic", "Helldivers 2", "Hades II",
                                                       "Ship of Fools", "Lantern Keepers"]
          and menus[0].max_values == 5, f"menus list the card's games: {[o.label for o in menus[0].options]}")
    check(text.endswith("-# US Steam prices · !games deals new for new releases"), text[-80:])

    # Prices are reused for an hour
    calls = len(price_calls)
    await gm.show_deals(ctx, "Sam, Alex and Brad", [sam, alex, brad])
    check(len(price_calls) == calls, "prices cached")
    claude.replies = ["[]"]
    await gm.show_deals(ctx, "you", [sam])
    text = card_text(channel.sent[-1])
    check("**Your friends have these**" in text and "2 people here have it" in text
          and "Deep Rock Galactic" in text and "**On your wishlist**" in text and "wanted by" not in text,
          f"just for you: {text}")
    check("The AI didn't find anything" in text and "You might like" not in text, "no picks: a note")
    check("someone who plays with friends" in claude.calls[-1]["system"], "sized for one")
    gm._deal_prices = {a: (t - gm_mod.PRICE_CACHE_SECONDS - 1, p) for a, (t, p) in gm._deal_prices.items()}
    claude.replies = ["[]"]
    await gm.show_deals(ctx, "you", [sam])
    check(len(price_calls) > calls, "stale prices are checked again")

    # The AI isn't available: Steam's most popular, with the reason
    claude.replies = ["⏳ You've reached your daily AI limit."]
    await gm.show_deals(ctx, "Raid night", [brad, sam, jo])
    text = card_text(channel.sent[-1])
    check("**Popular on sale**" in text and "You've reached your daily AI limit." in text
          and "⏳" not in text and "Lantern Keepers" in text, f"AI limit: popular instead: {text}")
    await bot.remove_cog("ClaudeChat")
    await gm.show_deals(ctx, "you", [jo])
    text = card_text(channel.sent[-1])
    check("AI picks need the AI chat cog" in text, "no AI chat cog")
    await bot.add_cog(claude)

    # New releases: only the picks, blurple
    claude.replies = ['[{"n": 2, "why": "Fresh and co-op."}]']
    await gm.show_deals(ctx, "the server", [alex, brad, jo, sam], "new")
    card = channel.sent[-1]
    text = card_text(card)
    check(card_color(card) == ui.BRAND and text.startswith("### 🎮 New games for the server")
          and "**New and worth a look**" in text and "Fresh Co-op" in text and f"released {RECENT}" in text
          and "Some of you have these" not in text and "On your wishlists" not in text
          and text.endswith("!games deals for sales"), f"new releases: {text}")
    listing = claude.calls[-1]["messages"][0]["content"].split("The list:\n")[1]
    check("Last Year" not in listing and "Coming Soon" not in listing and "Brand New" in listing,
          f"only releases from the last {gm_mod.NEW_RELEASE_DAYS} days: {listing}")
    check(gm_mod.release_age("Nov 6, 2026", datetime(2026, 11, 8, tzinfo=timezone.utc)) == 2
          and gm_mod.release_age("6 Nov, 2026", datetime(2026, 11, 8, tzinfo=timezone.utc)) == 2
          and gm_mod.release_age("Q1 2027") is None, "release dates read")
    check("released recently" in claude.calls[-1]["system"] and "a group of friends from this server"
          in claude.calls[-1]["system"] and store_modes[-1] == "new", "new mode prompt")

    # Nothing at all
    gm_mod.steam_store_list = lambda mode: asyncio.sleep(0, [])
    await gm.show_deals(ctx, "you", [jo], "new")
    check(channel.sent[-1].content.startswith("❓ I couldn't find new games to suggest right now.")
          and "Steam's store didn't answer" in channel.sent[-1].content, f"nothing: {channel.sent[-1].content!r}")
    prices.clear()
    gm._deal_prices.clear()
    await gm.show_deals(ctx, "Raid night", [brad, sam, jo])
    check(channel.sent[-1].content.startswith("❓ Nothing you play or want is on sale right now."),
          f"nothing on sale: {channel.sent[-1].content!r}")
    prices.update({100: price(60), 102: price(25), 103: price(80), 200: price(50)})
    gm_mod.steam_store_list = fake_store

    # The command: `new` first, then who
    claude.replies = ['[{"n": 1, "why": "New."}]']
    await gm.games_deals.callback(gm, Ctx(guild, alex), "new", "me")
    check(card_text(channel.sent[-1]).startswith("### 🎮 New games for you"), "!games deals new me")

    # ---- the menus ----
    menu = await gm_mod.DealSelect.from_custom_id(None, menus[0], {"action": "want"})
    check(menu.names["300"] == "Lantern Keepers" and menu.item.custom_id == "gm:deal:want",
          "a menu rebuilt after a restart reads the names from the message")
    i = FakeInteraction(bot, guild, jo, channel)
    i.data = {"values": ["300", "200"]}
    await menu.callback(i)
    reply = i.followup.calls[-1][0]
    wanted = {e["name"] for e in await gm.wanted_by(guild, jo)}
    check(wanted == {"Lantern Keepers", "Hades II"} and reply.startswith("✅ Added **Lantern Keepers** and "
                                                                         "**Hades II** to your wishlist.")
          and "Sale alerts aren't turned on" in reply and i.followup.calls[-1][1]["ephemeral"],
          f"wishlisted privately: {reply}")
    i = FakeInteraction(bot, guild, jo, channel)
    i.data = {"values": ["300"]}
    await menu.callback(i)
    check("Already on your wishlist: Lantern Keepers" in i.followup.calls[-1][0], i.followup.calls[-1][0])

    own = await gm_mod.DealSelect.from_custom_id(None, menus[1], {"action": "own"})
    i = FakeInteraction(bot, guild, sam, channel)
    i.data = {"values": ["100", "304"]}
    await own.callback(i)
    reply = i.followup.calls[-1][0]
    games = await gm.config.guild(guild).games()
    sam_owned = {games[g]["name"] for g in (await gm.config.guild(guild).users())["3"]["owned"]}
    requests = await gm.config.guild(guild).game_requests()
    check("Deep Rock Galactic" in sam_owned and "Ship of Fools" not in {g["name"] for g in games.values()}
          and any(r["name"] == "Ship of Fools" and r.get("steam_appid") == 304 for r in requests.values()),
          f"a library game is marked owned; a new one is requested: {reply}")
    i = FakeInteraction(bot, guild, brad, channel)
    i.data = {"values": ["305"]}
    await gm_mod.DealSelect("own", [discord.SelectOption(label="Wizard Kitchen", value="305")]).callback(i)
    games = await gm.config.guild(guild).games()
    added = next((g for g in games.values() if g["name"] == "Wizard Kitchen"), None)
    check(added is not None and added.get("steam_appid") == 305
          and added["id"] in (await gm.config.guild(guild).users())["1"]["owned"]
          and "Added **Wizard Kitchen** to the server library." in i.followup.calls[-1][0],
          f"a game admin adds it to the library and owns it: {i.followup.calls[-1][0]}")
    i = FakeInteraction(bot, guild, brad, channel)
    i.data = {"values": []}
    await own.callback(i)
    check(i.response.calls[0][1].startswith("❓"), "an empty choice")

    await bot.remove_cog("GameManager")


asyncio.run(main())
passed = sum(ok for ok, _ in results)
print(f"{passed}/{len(results)} checks passed")
