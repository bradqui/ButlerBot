import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, dcommands, load

claude_mod = load("claude", "claude")
gm_mod = load("gamemanager", "gamemanager")
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


class Block:
    _n = 0

    def __init__(self, type, text=None, name=None, input=None):
        self.type, self.text, self.name, self.input = type, text, name, input
        Block._n += 1
        self.id = f"toolu_{Block._n}"


def response(blocks, stop):
    r = MagicMock()
    r.model, r.stop_reason, r.content = "claude-haiku-5-5", stop, blocks
    r.usage = MagicMock(input_tokens=100, output_tokens=20, cache_read_input_tokens=0,
                        cache_creation_input_tokens=0, server_tool_use=None)
    return r


class Client:
    def __init__(self):
        self.queue, self.calls = [], []
        outer = self

        class Messages:
            async def create(self, **kw):
                outer.calls.append(kw)
                return outer.queue.pop(0)
        self.messages = Messages()
        self.beta = SimpleNamespace(messages=Messages())


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "Brad")
    alex = guild.add(2, "Alex")
    channel = guild.channel
    bot = TestBot(guild)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    cc = claude_mod.ClaudeChat(bot)
    await bot.add_cog(cc)
    client = Client()
    KEY = f"CHANNEL_{channel.id}"
    cc._reply_cooldown = dcommands.CooldownMapping.from_cooldown(1000, 1, dcommands.BucketType.user)

    async def get_client():
        return client
    cc._get_client = get_client

    async def no_title(name, member):
        return None
    cc.find_game_title = no_title
    await gm.add_games(guild, brad, ["Rocket League", "Halo Infinite"])

    req, owner_only = cc._requirement(bot.get_command("games admin add"))
    check((req, owner_only) == ("game admin only", False), f"custom check label: {req}")
    check(cc._requirement(bot.get_command("games install")) == ("", False), "member command has no requirement")
    check(await cc._permission_level(alex) == "member", "member level")
    check(await cc._permission_level(brad) == "bot owner, game admin", await cc._permission_level(brad))
    catalog = await cc._command_catalog(guild, "!", include_owner=False)
    check("`!games admin add <game_names>` (aliases: import; game admin only)" in catalog, "catalog shows game admin")
    check(bot.get_command("howto") is None and bot.get_command("howdoi") is None, "howto/howdoi removed")

    def msg(author, content="x"):
        return FakeMessage(channel, content, author=author)

    planned, problems, confirm = await cc._plan_actions(
        msg(alex), ["games install Rocket League", "!games admin add Foo", "ai hello", "frobnicate now",
                    "`games own Halo Infinite`"], "!")
    check(planned == ["!games install Rocket League", "!games own Halo Infinite"], f"planned: {planned}")
    check(len(problems) == 3 and not confirm, f"problems: {problems}")
    planned, problems, confirm = await cc._plan_actions(msg(brad), ["games admin add Minecraft", "games install Minecraft"], "!")
    check(planned == ["!games admin add Minecraft", "!games install Minecraft"] and confirm and not problems,
          "admin plan needs confirmation")
    planned, problems, _ = await cc._plan_actions(msg(alex), [f"games own G{i}" for i in range(7)], "!")
    check(len(planned) == 5 and "only run 5" in problems[-1], "max 5 commands")

    # Member asks the guide to do something: runs immediately, as them
    client.queue.append(response([
        Block("text", "Sure."),
        Block("tool_use", name="run_commands", input={"message": "Marking Rocket League installed for you.",
                                                      "commands": ["games install Rocket League"]}),
    ], "tool_use"))
    await cc._respond(msg(alex, "!guide add rocket league and mark it installed"),
                            "add rocket league and mark it installed", KEY)
    kw = client.calls[-1]
    check(any(t.get("name") == "run_commands" and t.get("strict") for t in kw["tools"]), "tool sent")
    check("Doing things for people" in kw["system"][0]["text"], "action rules in prompt")
    check(kw["messages"][-1]["content"][-1]["text"].startswith("Alex: "), "speaker label")
    posted = [m.content for m in channel.sent]
    check(any(p.startswith("Marking Rocket League installed") and "-# Running: `!games install Rocket League`" in p
              for p in posted), f"plan message: {posted[-3:]}")
    users = await gm.config.guild(guild).users()
    games = await gm.config.guild(guild).games()
    rl = next(g for g, v in games.items() if v["name"] == "Rocket League")
    check(rl in users["2"]["installed"], "command ran as the asker")
    session = cc._sessions[KEY]
    check(session.messages[-1]["content"].endswith("[Ran: !games install Rocket League]"), session.messages[-1])

    # Plain question: no tool call, normal answer
    client.queue.append(response([Block("text", "Use `!games session`.")], "end_turn"))
    await cc._respond(msg(alex, "how do i start a session"), "how do i start a session", KEY)
    check(channel.sent[-1].content == "Use `!games session`.", "plain answer")
    check(not channel.sent[-1].kw.get("suppress_embeds"), "answers without a lookup keep link previews")

    # Admin request: waits for Run, then executes
    client.queue.append(response([
        Block("tool_use", name="run_commands", input={"message": "Adding Minecraft and marking it installed.",
                                                      "commands": ["games admin add Minecraft",
                                                                   "games install Minecraft"]}),
    ], "tool_use"))
    task = asyncio.create_task(cc._respond(msg(brad, "add minecraft"), "add minecraft", KEY))
    await asyncio.sleep(0.05)
    confirm_msg = channel.sent[-1]
    view = confirm_msg.kw.get("view")
    check(isinstance(view, claude_mod.ActionConfirmView) and "press **Run**" in confirm_msg.content, "confirm prompt")
    games = await gm.config.guild(guild).games()
    check(not any(v["name"] == "Minecraft" for v in games.values()), "nothing ran before confirming")
    i = FakeInteraction(bot, guild, alex, channel, message=confirm_msg)
    check(not await view.interaction_check(i), "only the asker can confirm")
    run_button = next(c for c in view.children if getattr(c, "label", "") == "Run")
    await run_button.callback(FakeInteraction(bot, guild, brad, channel, message=confirm_msg))
    await asyncio.wait_for(task, 5)
    games = await gm.config.guild(guild).games()
    mc = next((g for g, v in games.items() if v["name"] == "Minecraft"), None)
    users = await gm.config.guild(guild).users()
    check(mc and mc in users["1"]["installed"], "confirmed commands ran in order")
    check("Done." in confirm_msg.content and "Running…" not in confirm_msg.content and confirm_msg.view is None,
          f"confirm message updated: {confirm_msg.content}")

    # Cancel path
    client.queue.append(response([
        Block("tool_use", name="run_commands", input={"message": "Removing Halo Infinite.",
                                                      "commands": ["games admin remove Halo Infinite"]}),
    ], "tool_use"))
    task = asyncio.create_task(cc._respond(msg(brad, "remove halo"), "remove halo", KEY))
    await asyncio.sleep(0.05)
    view = channel.sent[-1].kw["view"]
    cancel = next(c for c in view.children if getattr(c, "label", "") == "Cancel")
    await cancel.callback(FakeInteraction(bot, guild, brad, channel, message=channel.sent[-1]))
    await asyncio.wait_for(task, 5)
    games = await gm.config.guild(guild).games()
    check(any(v["name"] == "Halo Infinite" for v in games.values()), "cancel runs nothing")

    # Actions off: no tools, explain-only prompt
    await cc.config.guild(guild).guide_actions.set(False)
    client.queue.append(response([Block("text", "Type `!games install Valorant`.")], "end_turn"))
    await cc._respond(msg(alex, "install valorant"), "install valorant", KEY)
    check("run_commands" not in [t["name"] for t in client.calls[-1].get("tools", [])]
          and "can't run commands" in client.calls[-1]["system"][0]["text"],
          "actions disabled")

    # Intro, empty question
    intro = cc._butler_intro("!", True)
    check("butler how do I start a vote" in intro and "howdoi" not in intro,
          "intro examples")

    # Replies to the bot's other messages (e.g. a GameManager announcement) go to the guide
    import discord
    from types import SimpleNamespace

    class RefMessage(discord.Message):
        def __init__(self, mid, author, content):
            self.id, self.author, self.content, self.attachments = mid, author, content, []
            self.mentions, self.role_mentions, self.channel_mentions = [], [], []

    await cc.config.guild(guild).guide_actions.set(True)
    announcement = RefMessage(4242, guild.me, "✅ @Alex, **Barony** was added to the server library and it's in your library.")
    sent_before, calls_before = len(channel.sent), len(client.calls)

    typing_used = []
    orig_typing = channel.typing
    channel.typing = lambda: typing_used.append(1) or orig_typing()

    def reply(author, content, ref):
        m = FakeMessage(channel, content, author=author)
        m.reference = SimpleNamespace(message_id=ref.id, resolved=ref)
        m.mentions = [guild.me]
        return m

    cc._sessions.pop(KEY, None)
    client.queue.append(response([Block("text", "No, it's only in your library. Run `!games install Barony`.")],
                                 "end_turn"))
    await cc.on_message_without_command(reply(alex, "Did you also mark it installed?", announcement))
    check(len(client.calls) == calls_before + 1, "reply to bot announcement reaches the guide")
    turn = client.calls[-1]["messages"][-1]["content"][-1]["text"]
    check('Replying to Quillbot: "✅ @Alex, **Barony** was added' in turn, f"announcement quoted: {turn[:120]}")
    check(channel.sent[-1].content.startswith("No, it's only in your library"), "answer posted")
    check(not typing_used, "no typing indicator for replies that might be ignored")
    check("[silent]" in client.calls[-1]["messages"][-1]["content"][-1]["text"], "silence rule in the turn")

    sam = guild.add(3, "Sam")
    sent_before = len(channel.sent)
    client.queue.append(response([Block("text", "[silent]")], "end_turn"))
    await cc.on_message_without_command(reply(sam, "nice, I'm in!", announcement))
    check(len(channel.sent) == sent_before and "nice, I'm in" not in str(cc._sessions[KEY].messages),
          "chit-chat reply: silent, no history")

    human = RefMessage(4343, alex, "anyone up for Barony?")
    calls_before = len(client.calls)
    await cc.on_message_without_command(reply(brad, "me!", human))
    check(len(client.calls) == calls_before, "replies to people are ignored")

    await cc.config.guild(guild).guide_mentions.set(False)
    cc._reply_cooldown = type(cc._reply_cooldown).from_cooldown(100, 1, discord.ext.commands.BucketType.user)
    await cc.on_message_without_command(reply(brad, "what does this mean?", announcement))
    check(len(client.calls) == calls_before, "guidementions off disables reply routing")
    channel.typing = orig_typing

    client.queue.append(response([Block("text", "[silent]")], "end_turn"))
    await cc._respond(msg(alex, "!guide hmm"), "hmm", KEY)
    check("didn't come up with a reply" in channel.sent[-1].content, "direct !guide never goes silent")

    # ---------- library lookups ----------
    await cc.config.guild(guild).guide_mentions.set(True)
    lookups = cc._lookup_tools()
    check(set(lookups) == {"games_library", "games_game", "games_activity"}, f"lookup tools: {set(lookups)}")
    await gm.change_library(guild, alex, ["Halo Infinite"], "own")
    await gm.set_rank(type("T", (), {"guild": guild, "author": alex, "channel": channel,
                                     "send": channel.send})(), 1, "Rocket League")
    lib = await gm.guide_call_tool("games_library", {"member": "me"}, alex)
    check("Alex's library: 2 games, 1 installed" in lib and "Installed: Rocket League (rank 1)" in lib
          and "Owned but not installed: Halo Infinite" in lib, lib)
    check("Brad's library" in await gm.guide_call_tool("games_library", {"member": "brad"}, alex), "lookup by name")
    check("No member matches" in await gm.guide_call_tool("games_library", {"member": "zed"}, alex), "unknown member")
    game = await gm.guide_call_tool("games_game", {"game": "rocket"}, alex)
    check(game.startswith("Rocket League is in the server library") and "Installed by 1: Alex" in game, game)
    await gm.request_games(guild, channel, sam, ["Barony"], "own")
    check("Sam requested it" in await gm.guide_call_tool("games_game", {"game": "Barony"}, alex), "pending request")
    await gm.create_session(type("T", (), {"guild": guild, "author": brad, "channel": channel,
                                           "send": channel.send})(), "in 2h Raid night")
    act = await gm.guide_call_tool("games_activity", {}, alex)
    check('Session "Raid night"' in act and "host Brad" in act and "<t:" in act, act)

    # Loop: lookup -> tool_result -> final answer; history stays text-only
    cc._sessions.pop(KEY, None)
    calls_before = len(client.calls)
    client.queue.append(response([Block("tool_use", name="games_library", input={"member": "me"})], "tool_use"))
    client.queue.append(response([Block("text", "No, Barony isn't marked installed yet.")], "end_turn"))
    await cc._respond(msg(alex, "did you mark barony installed?"), "did you mark barony installed?", KEY)
    check(len(client.calls) == calls_before + 2, "two API calls for one lookup")
    second = client.calls[-1]
    names = [t["name"] for t in second["tools"]]
    check(names[:2] == ["bot_commands", "run_commands"] and names[-3:] == ["games_library", "games_game", "games_activity"],
          f"tools offered: {names}")
    results = second["messages"][-1]["content"]
    check(results[0]["type"] == "tool_result" and "Alex's library" in results[0]["content"], "tool_result sent")
    hist = cc._sessions[KEY].messages
    check([m["role"] for m in hist[-2:]] == ["user", "assistant"] and hist[-1]["content"].startswith("No, Barony"),
          "history text-only")
    check("lookup tools" in second["system"][0]["text"], "lookup rule in prompt")

    # Lookup then act in the next round
    client.queue.append(response([Block("tool_use", name="games_game", input={"game": "Halo"})], "tool_use"))
    client.queue.append(response([Block("tool_use", name="run_commands",
                                        input={"message": "Marking Halo Infinite installed.",
                                               "commands": ["games install Halo Infinite"]})], "tool_use"))
    await cc._respond(msg(alex, "mark halo installed"), "mark halo installed", KEY)
    users = await gm.config.guild(guild).users()
    games = await gm.config.guild(guild).games()
    halo = next(g for g, v in games.items() if v["name"] == "Halo Infinite")
    check(halo in users["2"]["installed"], "lookup then action works")

    # Runaway lookups stop after MAX_LOOKUP_ROUNDS
    calls_before = len(client.calls)
    for _ in range(claude_mod.MAX_LOOKUP_ROUNDS + 1):
        client.queue.append(response([Block("tool_use", name="games_activity", input={})], "tool_use"))
    await cc._respond(msg(alex, "loop"), "loop", KEY)
    check(len(client.calls) - calls_before == claude_mod.MAX_LOOKUP_ROUNDS + 1 and not client.queue, "lookup cap")
    check("didn't come up with a reply" in channel.sent[-1].content, "graceful when lookups never finish")

    await bot.remove_cog("ClaudeChat")
    await bot.remove_cog("GameManager")


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")


async def persona_test():
    guild = FakeGuild()
    guild.add(1, "Brad")
    bot = TestBot(guild)
    cc = claude_mod.ClaudeChat(bot)
    await bot.add_cog(cc)
    default = await cc._system_prompt(guild, False, False, actions=True)
    check(claude_mod.DEFAULT_PERSONA in default, "default persona in the prompt")
    await cc.config.guild(guild).persona.set("You are a grizzled pirate quartermaster.")
    custom = await cc._system_prompt(guild, False, False, actions=True)
    check("grizzled pirate" in custom and "never changes command names" in custom, "custom persona with accuracy rule")
    await bot.remove_cog("ClaudeChat")


asyncio.run(persona_test())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed (incl. persona)")


async def ai_lookup_test():
    guild = FakeGuild()
    guild.add(1, "Brad")
    alex = guild.add(2, "Alex")
    bot = TestBot(guild)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    cc = claude_mod.ClaudeChat(bot)
    await bot.add_cog(cc)
    await gm.add_games(guild, alex, ["Barony", "Deadlock"])
    await gm.change_library(guild, alex, ["Barony"], "install")

    calls = []
    queue = [
        response([Block("text", "Let me check your library."),
                  Block("tool_use", name="games_library", input={"member": "me"})], "tool_use"),
        response([Block("text", "You already have Barony; Deadlock isn't in your library.")], "end_turn"),
    ]

    class Beta:
        class messages:
            @staticmethod
            async def create(**kw):
                calls.append(kw)
                return queue.pop(0)

    client = MagicMock()
    client.beta = Beta()
    session = claude_mod.Session()
    session.messages.append({"role": "user", "content": [{"type": "text", "text": "Alex: which of these do I own?"}]})
    turn = await cc._call_claude(client, "claude-sonnet-5-5", session, alex)
    text, footer, stop, images = turn.text, turn.sources, turn.stop_reason, turn.images
    check(text == "You already have Barony; Deadlock isn't in your library.", f"AI chat final text only: {text!r}")
    check(len(calls) == 2 and "games_library" in [t.get("name") for t in calls[0]["tools"]], "AI chat offered lookups")
    check("lookup tools" in calls[0]["system"][0]["text"], "AI chat prompt mentions lookups")
    res = calls[1]["messages"][-1]["content"][0]
    check(res["type"] == "tool_result" and "Alex's library" in res["content"], "AI chat sent lookup result")
    check(len(session.messages) == 1, "AI chat session untouched by tool blocks")

    queue.append(response([Block("tool_use", name="generate_image", input={"prompt": "a cat", "edit": False})],
                          "tool_use"))
    turn = await cc._call_claude(client, "claude-sonnet-5-5", session, alex)
    text, stop, images = turn.text, turn.stop_reason, turn.images
    check(stop == "tool_use" and images == [{"prompt": "a cat", "edit": False}] and len(calls) == 3,
          "image calls still handed back without a lookup round")
    await bot.remove_cog("ClaudeChat")
    await bot.remove_cog("GameManager")


asyncio.run(ai_lookup_test())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed (incl. AI chat lookups)")
