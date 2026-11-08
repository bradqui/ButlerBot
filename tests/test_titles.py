"""Game title checking: library near-matches, Steam exact names, AI web search fallback, confirmation."""
import asyncio
from unittest.mock import MagicMock

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, card_text, dcommands, load, sys
from gmcards import card_buttons

gm_mod = load("gamemanager", "gamemanager")
claude_mod = load("claude", "claude")
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


STEAM = {"helldivers 2": ("HELLDIVERS 2", 553850)}
AI = {"an eggtremely hard game": {"title": "An Eggstremely Hard Game", "steam_appid": 3486540}}
ai_calls = []


async def fake_steam(name):
    return STEAM.get(name.lower())


gm_mod.steam_exact_title = fake_steam


class ClaudeChat(dcommands.Cog):
    async def find_game_title(self, name, member):
        ai_calls.append(name)
        return AI.get(name.lower())


async def main():
    check(gm_mod.clean_title("HELLDIVERS™  2 ") == "HELLDIVERS 2", "clean_title")
    games = {"g1": {"id": "g1", "name": "Rocket League"}, "g2": {"id": "g2", "name": "Deadlock"}}
    g, cands = gm_mod.resolve_game(games, "rocket leage")
    check(g is None and [c["name"] for c in cands] == ["Rocket League"], "typo gives a suggestion, not a match")

    guild = FakeGuild()
    brad = guild.add(1, "Brad")
    alex = guild.add(2, "Alex")
    channel = guild.channel
    bot = TestBot(guild)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    await bot.add_cog(ClaudeChat())
    await gm.add_games(guild, brad, ["Rocket League"])

    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        return asyncio.create_task(bot.invoke(ctx))

    async def click(label, author):
        await asyncio.sleep(0.05)
        prompt = channel.sent[-1]
        view = prompt.kw.get("view")
        button = next(c for c in card_buttons(view) if c.label.startswith(label))
        await button.callback(FakeInteraction(bot, guild, author, channel, message=prompt))
        return prompt

    # 1) Typo -> AI web search -> confirm -> request with corrected name + Steam ID
    task = await run(alex, "!games request an eggtremely hard game")
    prompt = await click("Use suggestion", alex)
    await asyncio.wait_for(task, 5)
    check("**An Eggstremely Hard Game**\n-# You typed `an eggtremely hard game` · found by web search" in card_text(prompt)
          and "Using the suggested name." in card_text(prompt), card_text(prompt))
    reqs = await gm.config.guild(guild).game_requests()
    req = next(iter(reqs.values()))
    check(req["name"] == "An Eggstremely Hard Game" and req["steam_appid"] == 3486540, f"request: {req}")
    check(any(b.url == "https://store.steampowered.com/app/3486540" for b in card_buttons(channel.sent[-2])),
          "store link button on the request card")
    check(channel.sent[-1].content.startswith("✅ **Requested:** An Eggstremely Hard Game"), channel.sent[-1].content)

    # Approval keeps the Steam ID on the game
    rid = next(iter(reqs))
    await gm.resolve_request(guild, rid, brad, approve=True)
    games = await gm.config.guild(guild).games()
    egg = next(v for v in games.values() if v["name"] == "An Eggstremely Hard Game")
    check(egg["steam_appid"] == 3486540, "approved game keeps Steam ID")

    # 2) Capitalization only (Steam exact) -> fixed silently, no prompt, no AI call
    ai_before = len(ai_calls)
    task = await run(alex, "!games request helldivers 2")
    await asyncio.wait_for(task, 5)
    reqs = await gm.config.guild(guild).game_requests()
    check(any(r["name"] == "HELLDIVERS 2" and r["steam_appid"] == 553850 for r in reqs.values()),
          "Steam exact name applied silently")
    check(len(ai_calls) == ai_before, "no AI call when Steam matches")
    check(not any(m.kw.get("view") and isinstance(m.kw["view"], gm_mod.NameCheckView)
                  for m in channel.sent[-2:]), "no confirmation for case-only fixes")

    # 3) Typo of a game already in the library -> suggests it -> 'Already in the library'
    task = await run(alex, "!games request rocket leage")
    prompt = await click("Use suggestion", alex)
    await asyncio.wait_for(task, 5)
    check("**Rocket League**\n-# You typed `rocket leage` · already in the library" in card_text(prompt),
          card_text(prompt))
    check("Already in the library:** Rocket League" in channel.sent[-1].content, "routes to existing")

    # 4) Keep what I typed / cancel / other people can't click
    AI["valorantt"] = {"title": "VALORANT", "steam_appid": None}
    task = await run(alex, "!games request valorantt")
    await asyncio.sleep(0.05)
    view = channel.sent[-1].kw["view"]
    check(not await view.interaction_check(FakeInteraction(bot, guild, brad, channel, message=channel.sent[-1])),
          "only the requester can choose")
    await click("Keep my spelling", alex)
    await asyncio.wait_for(task, 5)
    reqs = await gm.config.guild(guild).game_requests()
    check(any(r["name"] == "valorantt" for r in reqs.values()), "typed name kept on request")
    task = await run(alex, "!games request an eggtremely hard gam")
    AI["an eggtremely hard gam"] = AI["an eggtremely hard game"]
    count = len(await gm.config.guild(guild).game_requests())
    await click("Cancel", alex)
    await asyncio.wait_for(task, 5)
    check(len(await gm.config.guild(guild).game_requests()) == count, "cancel files nothing")

    # 5) Unknown names: no match anywhere -> asks before using them, and the request card warns the admin
    task = await run(alex, "!games request Some Indie Thing")
    prompt = await click("Keep it", alex)
    await asyncio.wait_for(task, 5)
    text = card_text(prompt)
    check("I couldn't confirm this one" in text and "**Some Indie Thing**\n-# Not found on Steam or by web search"
          in text and "Using the name as is." in text, text)
    check([b.label for b in card_buttons(prompt.kw["view"])] == ["Keep it", "Cancel"],
          "nothing else in the batch: no Skip button")
    reqs = await gm.config.guild(guild).game_requests()
    indie = next(r for r in reqs.values() if r["name"] == "Some Indie Thing")
    check(indie["unconfirmed"], "request remembers it wasn't confirmed")
    card = next(m for m in channel.sent if m.kw.get("view") and "Game request: Some Indie Thing" in card_text(m))
    check("⚠️ I couldn't confirm this name on Steam or the web.\n-# Check the spelling before approving."
          in card_text(card), card_text(card))
    egg_card = next(m for m in channel.sent if m.kw.get("view") and "Game request: An Eggstremely" in card_text(m))
    check("couldn't confirm" not in card_text(egg_card), "confirmed names carry no warning")

    # 5b) A mix: one fine, one unknown -> Skip drops the unknown one only
    STEAM["portal 2"] = ("Portal 2", 620)
    task = await run(alex, "!games request portal 2, 000: Space Marine 2")
    prompt = await click("Skip it", alex)
    await asyncio.wait_for(task, 5)
    reqs = await gm.config.guild(guild).game_requests()
    check(any(r["name"] == "Portal 2" and not r["unconfirmed"] for r in reqs.values())
          and not any("Space Marine" in r["name"] for r in reqs.values()), "skip keeps only the confirmed name")
    check("Skipping the name I couldn't confirm." in card_text(prompt), card_text(prompt))

    # 5c) A correction plus an unknown: suggestions, the unknown block, and Skip unconfirmed
    AI["starfeild"] = {"title": "Starfield", "steam_appid": None}
    task = await run(alex, "!games request starfeild, Zzyzx Unknown")
    await asyncio.sleep(0.05)
    view = channel.sent[-1].kw["view"]
    check([b.label for b in card_buttons(view)] == ["Use suggestions", "Keep my spelling", "Skip unconfirmed",
                                                     "Cancel"], [b.label for b in card_buttons(view)])
    await click("Use suggestions", alex)
    await asyncio.wait_for(task, 5)
    reqs = await gm.config.guild(guild).game_requests()
    check(any(r["name"] == "Starfield" and not r["unconfirmed"] for r in reqs.values())
          and any(r["name"] == "Zzyzx Unknown" and r["unconfirmed"] for r in reqs.values()),
          "suggestion used, unknown kept and flagged")

    # 5d) A thousands comma doesn't split a name
    STEAM["warhammer 40,000: space marine 2"] = ("Warhammer 40,000: Space Marine 2", 2183900)
    task = await run(alex, "!games request Warhammer 40,000: Space Marine 2")
    await asyncio.wait_for(task, 5)
    reqs = await gm.config.guild(guild).game_requests()
    check(any(r["name"] == "Warhammer 40,000: Space Marine 2" for r in reqs.values()), "40,000 stays one name")

    # 6) Admin bulk add over the limit skips lookups and says so
    ai_before = len(ai_calls)
    names = ", ".join(f"Game {i}" for i in range(gm_mod.MAX_CHECKED_NAMES + 2))
    task = await run(brad, f"!games admin add {names}")
    prompt = await click("Keep them", brad)
    await asyncio.wait_for(task, 5)
    check(len(ai_calls) == ai_before, "bulk add skips AI lookups")
    check(f"**Not looked up: more than {gm_mod.MAX_CHECKED_NAMES} names at once**" in card_text(prompt),
          card_text(prompt))
    games = await gm.config.guild(guild).games()
    check(sum(1 for v in games.values() if v["name"].startswith("Game ")) == gm_mod.MAX_CHECKED_NAMES + 2,
          "bulk add added all")

    # 6b) Lookups run in parallel, and only MAX_AI_TITLE_LOOKUPS go to the AI
    running, peak = [0], [0]

    async def slow_find(self, name, member):
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        await asyncio.sleep(0.02)
        running[0] -= 1
        ai_calls.append(name)
        return None
    real_find = ClaudeChat.find_game_title
    ClaudeChat.find_game_title = slow_find
    ai_before = len(ai_calls)
    found = await gm.suggest_titles(alex, [f"Mystery {i}" for i in range(12)])
    ClaudeChat.find_game_title = real_find
    check(len(ai_calls) - ai_before == gm_mod.MAX_AI_TITLE_LOOKUPS, "AI lookups capped")
    check(1 < peak[0] <= gm_mod.LOOKUP_CONCURRENCY, f"parallel, at most {gm_mod.LOOKUP_CONCURRENCY}: {peak[0]}")
    check([s for *_, s in found].count(gm_mod.NOT_SEARCHED) == 12 - gm_mod.MAX_AI_TITLE_LOOKUPS
          and [s for *_, s in found].count(gm_mod.NOT_FOUND) == gm_mod.MAX_AI_TITLE_LOOKUPS, "reasons per name")

    # 7) Unknown-game button flow: install a typo of an existing game -> suggestions shown immediately
    task = await run(alex, "!games install rocket leage")
    await asyncio.wait_for(task, 5)
    check("could be **Rocket League**" in channel.sent[-1].content and not channel.sent[-1].embeds,
          "install typo suggests existing (a plain status line)")

    await bot.remove_cog("GameManager")


async def claude_title_test():
    guild = FakeGuild()
    member = guild.add(2, "Alex")
    bot = TestBot(guild)
    cc = claude_mod.ClaudeChat(bot)
    await bot.add_cog(cc)
    calls = []

    class Block:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def resp(blocks):
        r = MagicMock()
        r.model, r.stop_reason, r.content = "claude-haiku-5-5", "tool_use", blocks
        r.usage = MagicMock(input_tokens=5000, output_tokens=100, cache_read_input_tokens=0,
                            cache_creation_input_tokens=0, server_tool_use=MagicMock(web_search_requests=1))
        return r

    class Client:
        class messages:
            @staticmethod
            async def create(**kw):
                calls.append(kw)
                if kw["tools"][0]["type"] == "web_search_20260209" and kw["model"] == "claude-haiku-5-5":
                    raise sys.modules["anthropic"].BadRequestError("web_search_20260209 is not supported")
                return resp([Block(type="tool_use", name="report_title",
                                   input={"found": True, "title": "An Eggstremely Hard Game", "steam_appid": 3486540})])

    async def get_client():
        return Client()
    cc._get_client = get_client
    found = await cc.find_game_title("an eggtremely hard game", member)
    check(found == {"title": "An Eggstremely Hard Game", "steam_appid": 3486540}, f"title found: {found}")
    check([c["tools"][0]["type"] for c in calls] == ["web_search_20260209", "web_search_20250305"],
          "falls back to the basic search tool on Haiku")
    check(cc._title_searcher == 1, "remembers the working option")
    calls.clear()
    await cc.find_game_title("x", member)
    check(len(calls) == 1 and calls[0]["tools"][0]["type"] == "web_search_20250305", "skips the refused option next time")
    usage = await cc.config.guild(guild).usage()
    check(usage["searches"] == 2 and usage["requests"] == 2, f"usage recorded: {usage}")
    await bot.remove_cog("ClaudeChat")


asyncio.run(main())
asyncio.run(claude_title_test())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
