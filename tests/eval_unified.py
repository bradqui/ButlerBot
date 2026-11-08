"""
Live check of the merged AI chat: real member-style questions through the cog's own pipeline and the real API.
Commands it decides to run are recorded, never executed. Usage: python eval_unified.py [--dry]
The API key is read from ~/.butlerbot-eval-key and never printed.
"""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
DRY = "--dry" in sys.argv
sys.path.insert(0, str(HERE / "apilibs"))
import anthropic as real_anthropic  # noqa: E402  (before the harness swaps in its stub)

from harness import FakeGuild, FakeMessage, TestBot, discord, load  # noqa: E402

claude_mod = load("claude", "claude")
gm_mod = load("gamemanager", "gamemanager")
st_mod = load("activitystats", "activitystats")
sp_mod = load("speakup", "speakup")
bf_mod = load("parlor", "parlor")
hb_mod = load("handbook", "handbook")
sys.modules["anthropic"] = real_anthropic   # the real client's lazy imports need the real package
FakeMessage._state = None
MODEL = "claude-sonnet-5-5"


class RefMessage(discord.Message):
    def __init__(self, mid, author, content):
        self.id, self.author, self.content, self.attachments = mid, author, content, []
        self.mentions, self.role_mentions, self.channel_mentions, self.embeds = [], [], [], []


# (asker, text, conversation, expectations). Expectations: lookup (must / must not call bot_commands),
# run (substrings every one of which must appear in the commands it would run), norun, silent, reply_to.
CASES = [
    ("alex", "how do I start a vote on what to play?", "a", {"lookup": True, "norun": True, "says": "vote"}),
    ("alex", "what games do I own?", "a", {"source": True, "prefer": "mygames"}),
    ("alex", "add Rocket League to my games and mark it installed", "a",
     {"lookup": True, "run": ["games", "install", "Rocket League"]}),
    ("alex", "remind me tomorrow at 6pm to buy Helldivers", "b", {"lookup": True, "run": ["remind", "Helldivers"]}),
    ("alex", "how do I see when the server is busiest?", "b", {"lookup": True, "norun": True, "says": "heatmap"}),
    ("sam", "can you schedule a game night friday at 9pm?", "c", {"lookup": True, "run": ["games session", "9"]}),
    ("sam", "actually can that happen every friday instead?", "c", {"lookup": True, "says": "every friday"}),
    ("alex", "how do i stop the bot from summarizing links in this channel", "d", {"lookup": True, "says": "speakup"}),
    ("alex", "set up my gaming profile", "d", {"lookup": True, "run": ["games newprofile"]}),
    ("alex", "who owns Halo Infinite?", "e", {"source": True, "prefer": "whoowns"}),
    ("alex", "how do I get the bot to stop tracking my stats", "e", {"lookup": True, "says": "ignoreme"}),
    ("alex", "can the bot play music in voice?", "f", {"lookup": True, "norun": True, "nocommand": True}),
    ("alex", "how do I start a text adventure?", "f", {"lookup": True, "norun": True, "says": "adventure"}),
    ("alex", "what's a good co-op game for 4 people, and how do I add it to my library?", "g",
     {"lookup": True, "norun": True, "says": "games own"}),
    ("alex", "what's the capital of Australia?", "h", {"lookup": False, "norun": True, "says": "Canberra"}),
    ("alex", "write a haiku about pizza", "h", {"lookup": False, "norun": True}),
    ("alex", "make it about tacos instead", "h", {"lookup": False, "norun": True, "says": "tortilla"}),
    ("alex", "how do i use the lfg thing", "i", {"lookup": True, "says": "lfg"}),
    ("alex", "how do I add a game to the server library?", "i", {"lookup": True, "norun": True}),
    ("sam", "I'm in!", "j", {"silent": True, "reply_to": "🎮 **Raid night** · Friday 9:00 PM · Host: Brad · "
                                                       "Join below. Playing: Halo Infinite"}),
    ("sam", "what time is this in my timezone?", "j", {"silent": False, "reply_to": "🎮 **Raid night** · "
                                                       "<t:1794000000:F> · Host: Brad · Join below."}),
    ("brad", "add Minecraft to the server library", "k", {"lookup": True, "run": ["games admin add", "Minecraft"]}),
    # Server data (cases 23-30): checked or shown in the same turn, never from memory. "prefer" names the command
    # that shows exactly what was asked; running it or looking the data up both count as checking.
    ("alex", "who owns Helldivers 2?", "m", {"source": True, "prefer": "whoowns"}),
    ("alex", "does anyone own it but not have it installed?", "m", {"source": True, "norun": True, "says": "Alex"}),
    ("alex", "remind me again who owns it?", "m", {"source": True, "prefer": "whoowns"}),
    ("sam", "show me my games", "n", {"source": True, "prefer": "mygames"}),
    ("sam", "what can Alex, Brad and I all play?", "n", {"source": True}),
    ("sam", "which of those does Brad have installed?", "n", {"source": True}),
    ("alex", "what's the most wanted game?", "o", {"source": True, "prefer": "wanted"}),
    ("alex", "who's been most active here this month?", "o", {"source": True, "prefer": "stats"}),
]


async def main():
    guild = FakeGuild()
    people = {"brad": guild.add(1, "Brad", admin=True), "alex": guild.add(2, "Alex"), "sam": guild.add(3, "Sam")}
    channel = guild.channel
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    bot.set_help_formatter = lambda f: None
    bot.reset_help_formatter = lambda: None
    for cls in (gm_mod.GameManager, st_mod.ActivityStats, sp_mod.SpeakUp, bf_mod.Parlor, hb_mod.Handbook,
                claude_mod.ClaudeChat):
        await bot.add_cog(cls(bot))
    cc, gm = bot.get_cog("ClaudeChat"), bot.get_cog("GameManager")
    persona = (HERE / "ButlerBot-persona.txt")
    if persona.exists():
        await cc.config.guild(guild).persona.set(persona.read_text(encoding="utf-8").strip())

    async def no_title(name, member):
        return None
    cc.find_game_title = no_title
    await gm.add_games(guild, people["brad"], ["Rocket League", "Halo Infinite", "Deep Rock Galactic", "Barony"])
    await gm.change_library(guild, people["alex"], ["Halo Infinite", "Barony"], "own")
    await gm.change_library(guild, people["brad"], ["Halo Infinite"], "install")
    await gm.add_games(guild, people["brad"], ["Helldivers 2"])
    await gm.change_library(guild, people["brad"], ["Helldivers 2", "Deep Rock Galactic"], "install")
    await gm.change_library(guild, people["sam"], ["Helldivers 2", "Barony", "Deep Rock Galactic"], "install")
    await gm.change_library(guild, people["alex"], ["Helldivers 2", "Deep Rock Galactic"], "own")
    await gm.add_wants(guild, people["sam"], [("Hades II", 1145350)])
    await gm.add_wants(guild, people["alex"], [("Hades II", 1145350)])

    if DRY:
        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=None)))
        print(await cc._system_prompt(guild, True, False, lookups=True, actions=True))
        return
    key_file = next(p for p in (Path.home() / ".butlerbot-eval-key", Path.home() / ".butlerbot-eval-key.txt")
                    if p.exists())
    key = key_file.read_text(encoding="utf-8-sig").strip()
    client = real_anthropic.AsyncAnthropic(api_key=key, timeout=300.0, max_retries=2)
    del key

    looked_up = []
    orig_run = cc._run_lookups

    async def run_lookups(calls, lookups, member):
        looked_up.extend((c.name, c.input) for c in calls)
        return await orig_run(calls, lookups, member)
    cc._run_lookups = run_lookups

    report, passed = [], 0
    only = {int(a) for a in sys.argv[1:] if a.isdigit()}
    for n, (who, text, conv, expect) in enumerate(CASES, 1):
        if only and n not in only:
            continue
        member = people[who]
        key_name = f"CHANNEL_{conv}"
        session = cc._get_session(key_name)
        message = FakeMessage(channel, text, author=member)
        silent_ok = "reply_to" in expect
        if silent_ok:
            ref = RefMessage(9000 + n, guild.me, expect["reply_to"])
            message.reference = SimpleNamespace(message_id=ref.id, resolved=ref)
        content, _ = await cc._build_user_turn(message, text, key_name, session, may_stay_silent=silent_ok)
        session.messages.append({"role": "user", "content": content})
        looked_up.clear()
        try:
            turn = await cc._call_claude(client, MODEL, session, member, actions=True)
        except Exception as e:
            report.append(f"#{n} ERROR {type(e).__name__}: {str(e)[:300]}")
            session.messages.pop()
            continue
        names = [name for name, _ in looked_up]
        problems = []
        if expect.get("lookup") is True and "bot_commands" not in names:
            problems.append("didn't look up commands")
        if expect.get("lookup") is False and "bot_commands" in names:
            problems.append("looked up commands for a non-bot question")
        if expect.get("tool") and expect["tool"] not in names:
            problems.append(f"didn't use {expect['tool']}")
        commands = turn.action["commands"] if turn.action else []
        if expect.get("run") and not any(all(s.lower() in c.lower() for s in expect["run"]) for c in commands):
            problems.append(f"expected to run something with {expect['run']}")
        if expect.get("norun") and commands:
            problems.append("ran commands for a how-to question")
        said = turn.text + " " + " ".join(commands) + " " + (turn.action or {}).get("message", "")
        if expect.get("says") and expect["says"].lower() not in said.lower():
            problems.append(f"answer doesn't mention {expect['says']!r}")
        if expect.get("nocommand") and claude_mod.GUIDE_NO_COMMAND not in turn.text:
            problems.append("no [no-command] flag")
        is_silent = turn.text.strip() == claude_mod.GUIDE_SILENT
        data_lookups = [x for x in names if x != "bot_commands"]
        data_commands = [c for c in commands if c.split()[0] in ("games", "stats", "reminders")]
        if expect.get("source") and not (data_lookups or data_commands):
            problems.append("answered server data without checking it this turn")
        if expect.get("prefer"):
            how = "ran " + "; ".join(commands) if data_commands else f"looked up {', '.join(data_lookups) or 'nothing'}"
            report_note = f"   wanted `{expect['prefer']}` shown as a card: {how}\n"
        else:
            report_note = ""
        if "silent" in expect and is_silent != expect["silent"]:
            problems.append("should have stayed silent" if expect["silent"] else "stayed silent wrongly")
        passed += not problems
        record = turn.text if not turn.action else (turn.action["message"] + f"\n[Ran: {'; '.join(commands)}]")
        if is_silent:
            session.messages.pop()
        else:
            session.messages.append({"role": "assistant", "content": record or "(empty)"})
        report.append(f"#{n} {'PASS' if not problems else 'FAIL: ' + '; '.join(problems)}\n"
                      f"   {member.display_name}: {text}\n   lookups: {looked_up}\n"
                      f"   about_bot={turn.about_bot} run={commands}\n{report_note}   reply: {record[:700]}")
    usage = await cc.config.guild(guild).usage()
    report.append(f"\n{passed}/{len(only) or len(CASES)} passed · {usage['requests']} turns · input {usage['input']} · "
                  f"cache read {usage['cache_read']} · cache write {usage['cache_write']} · output {usage['output']} · "
                  f"searches {usage['searches']} · est. cost ${usage['cost']:.3f}")
    out = HERE / "eval_unified_report.txt"
    out.write_text("\n\n".join(report), encoding="utf-8")
    print(report[-1].strip())
    await client.close()


asyncio.run(main())
