"""One AI for everything: !ai, !butler, @mentions and replies share a conversation; commands are looked up on demand."""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, discord, load

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
        self.citations = None
        Block._n += 1
        self.id = f"toolu_{Block._n}"


def response(blocks, stop):
    r = MagicMock()
    r.model, r.stop_reason, r.content = "claude-sonnet-5-5", stop, blocks
    r.usage = MagicMock(input_tokens=100, output_tokens=20, cache_read_input_tokens=0,
                        cache_creation_input_tokens=0, server_tool_use=None)
    return r


def lookup(sections, search=""):
    return response([Block("text", "Let me check."),
                     Block("tool_use", name="bot_commands", input={"sections": sections, "search": search})],
                    "tool_use")


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


class RefMessage(discord.Message):
    def __init__(self, mid, author, content):
        self.id, self.author, self.content, self.attachments = mid, author, content, []
        self.mentions, self.role_mentions, self.channel_mentions = [], [], []


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "Brad")
    alex = guild.add(2, "Alex")
    channel = guild.channel
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    cc = claude_mod.ClaudeChat(bot)
    await bot.add_cog(cc)
    client = Client()

    async def get_client():
        return client
    cc._get_client = get_client

    async def no_title(name, member):
        return None
    cc.find_game_title = no_title
    cc._reply_cooldown = discord.ext.commands.CooldownMapping.from_cooldown(
        1000, 1, discord.ext.commands.BucketType.user)
    await gm.add_games(guild, brad, ["Rocket League", "Halo Infinite"])
    key = f"CHANNEL_{channel.id}"

    def msg(author, content="x"):
        return FakeMessage(channel, content, author=author)

    async def run(author, content):
        ctx = await bot.get_context(msg(author, content))
        await bot.invoke(ctx)
        if ctx.command is not None:
            ctx.command.reset_cooldown(ctx)

    # --- the system prompt and tools ---
    system = await cc._system_prompt(guild, True, True, lookups=True, actions=True)
    check("About this bot:" in system and "- GameManager:" in system and "games: admin," in system,
          "system prompt lists what the bot can do")
    check("Call bot_commands first" in system and "Doing things for people:" in system, "rules in the prompt")
    check("Never state server data unless a lookup or command in this same turn returned it" in system
          and "run it with run_commands so its real card is posted" in system
          and "use the lookup tools and answer in your own words" in system, "server data rules in the prompt")
    no_actions = await cc._system_prompt(guild, True, True, lookups=False, actions=False)
    check("Never state server data" in no_actions and "real card is posted" not in no_actions
          and "use the lookup tools" not in no_actions, "data rules follow what's available")
    check(system.rstrip().endswith("(UTC)."), "the date comes last so the rest stays cached")
    check("point them to" not in system, "no more sending people to the butler")
    tool = await cc._commands_tool(guild)
    enum = tool["input_schema"]["properties"]["sections"]["items"]["enum"]
    check(tool["strict"] and "GameManager" in enum and "ClaudeChat" in enum, f"lookup sections: {enum}")

    # --- the lookup itself ---
    result = await cc._commands_result(alex, {"sections": ["GameManager"], "search": "remind me tomorrow"})
    check(result.startswith("Asker: Alex (member). Command prefix: `!`."), "lookup says who's asking")
    check("They have no saved timezone, so their session times are read in the server's (UTC)" in result.split("\n")[0],
          "lookup says the asker has no timezone yet")
    await gm.config.user(alex).timezone.set("America/Los_Angeles")
    result = await cc._commands_result(alex, {"sections": ["GameManager"], "search": ""})
    check("Their saved timezone is America/Los_Angeles" in result.split("\n")[0]
          and "don't run games timezone" in result, "lookup gives the asker's saved timezone")
    await gm.config.user(alex).timezone.clear()
    check("## GameManager" in result and "`!games install" in result, "requested section in full")
    check("Search matches" not in result or "remind" in result.lower(), "search adds matches from elsewhere")
    nothing = await cc._commands_result(alex, {"sections": [], "search": "zzzz"})
    check("Nothing matched" in nothing, "empty lookup says so")
    owner = await cc._commands_result(brad, {"sections": ["ClaudeChat"], "search": ""})
    check(owner.startswith("Asker: Brad (bot owner"), "the owner's lookup includes owner commands")

    # --- plain chat: one call, counts toward the daily limit ---
    client.queue.append(response([Block("text", "Try Guildy McGuildface.")], "end_turn"))
    await run(alex, "!ai what's a good guild name?")
    check(channel.sent[-1].content == "Try Guildy McGuildface.", "plain chat answered")
    kw = client.calls[-1]
    names = [t.get("name") for t in kw["tools"]]
    check(names[:2] == ["bot_commands", "run_commands"], f"tools offered: {names}")
    check(not channel.sent[-1].kw.get("suppress_embeds"), "chat answers keep link previews")
    check((await cc.config.member(alex).daily())["count"] == 1, "chat counts toward the daily limit")

    # --- a bot question via !ai: lookup, then answer ---
    client.queue += [lookup(["GameManager"]), response([Block("text", "Use `!games session 8pm`.")], "end_turn")]
    await run(alex, "!ai how do I start a game night?")
    check(channel.sent[-1].content == "Use `!games session 8pm`.", "bot question answered, preamble dropped")
    res = client.calls[-1]["messages"][-1]["content"][0]
    check(res["type"] == "tool_result" and "## GameManager" in res["content"], "lookup result sent back")
    check(channel.sent[-1].kw.get("suppress_embeds") is True, "bot answers don't get link previews")
    check((await cc.config.member(alex).daily())["count"] == 1, "bot questions don't count toward the limit")
    history = cc._sessions[key].messages
    check(all(isinstance(m["content"], str) or all(b.get("type") == "text" for b in m["content"]) for m in history),
          "history keeps no tool blocks")

    # --- a server-data lookup is also about the bot: no daily count ---
    client.queue += [response([Block("tool_use", name="games_library", input={"member": "me"})], "tool_use"),
                     response([Block("text", "You own Halo Infinite.")], "end_turn")]
    await run(alex, "!ai what games do I own?")
    check(channel.sent[-1].content == "You own Halo Infinite." and
          (await cc.config.member(alex).daily())["count"] == 1, "data lookups don't count toward the limit")

    # --- follow-up via !butler lands in the same conversation ---
    client.queue.append(response([Block("text", "Yes: `!games recurring every friday 8pm`.")], "end_turn"))
    await run(alex, "!butler can I make that weekly?")
    sent_history = client.calls[-1]["messages"]
    check(any("how do I start a game night" in str(m["content"]) for m in sent_history),
          "!butler continues the !ai conversation")

    # --- a request to do something: lookup, then run as the asker ---
    client.queue += [lookup(["GameManager"]), response([
        Block("tool_use", name="run_commands", input={"message": "Marking Rocket League installed for you.",
                                                      "commands": ["games install Rocket League"]})], "tool_use")]
    await run(alex, "!ai mark rocket league installed for me")
    posted = channel.sent[-1].content if channel.sent[-1].content.startswith("Marking") else \
        next(m.content for m in reversed(channel.sent) if (m.content or "").startswith("Marking"))
    check("-# Running: `!games install Rocket League`" in posted, f"plan posted: {posted}")
    users = await gm.config.guild(guild).users()
    games = await gm.config.guild(guild).games()
    rl = next(g for g, v in games.items() if v["name"] == "Rocket League")
    check(rl in users["2"]["installed"], "command ran as the asker")
    check(cc._sessions[key].messages[-1]["content"].endswith("[Ran: !games install Rocket League]"),
          "history notes what ran")

    # --- staff commands wait for Run ---
    client.queue += [lookup(["GameManager"]), response([
        Block("tool_use", name="run_commands", input={"message": "Adding Minecraft.",
                                                      "commands": ["games admin add Minecraft"]})], "tool_use")]
    task = asyncio.create_task(run(brad, "!ai add minecraft to the server"))
    for _ in range(100):
        await asyncio.sleep(0.01)
        if channel.sent and isinstance(channel.sent[-1].kw.get("view"), claude_mod.ActionConfirmView):
            break
    confirm_msg = channel.sent[-1]
    view = confirm_msg.kw.get("view")
    check(isinstance(view, claude_mod.ActionConfirmView), "confirm prompt shown")
    check(not cc._sessions[key].lock.locked(), "waiting for Run doesn't block the conversation")
    run_button = next(c for c in view.children if getattr(c, "label", "") == "Run")
    await run_button.callback(FakeInteraction(bot, guild, brad, channel, message=confirm_msg))
    await asyncio.wait_for(task, 5)
    games = await gm.config.guild(guild).games()
    check(any(v["name"] == "Minecraft" for v in games.values()), "confirmed command ran")

    # --- nothing fits: the flag is stripped and recorded ---
    unmet = []

    fake_stats = SimpleNamespace(record_unmet=lambda g, u, q: unmet.append(q) or asyncio.sleep(0))
    orig_get_cog = bot.get_cog
    bot.get_cog = lambda name: fake_stats if name == "ActivityStats" else orig_get_cog(name)
    client.queue += [lookup([], "karaoke"), response([Block("text", "There's no karaoke feature.\n[no-command]")],
                                                     "end_turn")]
    await run(alex, "!ai start karaoke")
    bot.get_cog = orig_get_cog
    check(channel.sent[-1].content == "There's no karaoke feature.", "no-command flag removed")
    check(unmet == ["start karaoke"], f"unmet question recorded: {unmet}")

    # --- @mention goes to the channel conversation ---
    client.queue.append(response([Block("text", "Hello!")], "end_turn"))
    m = msg(alex, f"<@{bot.user.id}> hi there")
    m.mentions = [bot.user]
    await cc.on_message_without_command(m)
    check(channel.sent[-1].content == "Hello!", "@mention answered")
    check("hi there" in str(cc._sessions[key].messages[-2]["content"]), "@mention joins the channel conversation")
    # Discord's @ menu also offers the bot's own role under its name; that counts as addressing the bot
    guild.self_role = SimpleNamespace(id=4321)
    client.queue.append(response([Block("text", "Good afternoon.")], "end_turn"))
    m = msg(alex, "<@&4321> critique this please")
    await cc.on_message_without_command(m)
    turn = cc._sessions[key].messages[-2]["content"]
    turn = turn if isinstance(turn, str) else turn[-1]["text"]
    check(channel.sent[-1].content == "Good afternoon." and turn.endswith("\ncritique this please"),
          "the bot's role mention is answered, with the mention taken out")
    before = len(channel.sent)
    await cc.on_message_without_command(msg(alex, "<@&555> another role"))
    check(len(channel.sent) == before, "other roles' mentions aren't for the bot")
    del guild.self_role

    # --- replies to the bot's announcements: answered when for the bot, silent otherwise ---
    announcement = RefMessage(4242, guild.me, "✅ **Barony** was added to the server library.")
    typing_used = []
    orig_typing = channel.typing
    channel.typing = lambda: typing_used.append(1) or orig_typing()

    def reply(author, content, ref):
        r = FakeMessage(channel, content, author=author)
        r.reference = SimpleNamespace(message_id=ref.id, resolved=ref)
        r.mentions = [guild.me]
        return r

    before, length = len(channel.sent), len(cc._sessions[key].messages)
    client.queue.append(response([Block("text", "[silent]")], "end_turn"))
    await cc.on_message_without_command(reply(alex, "I'm in!", announcement))
    check(len(channel.sent) == before and len(cc._sessions[key].messages) == length, "silent: nothing posted or kept")
    turn_text = client.calls[-1]["messages"][-1]["content"][-1]["text"]
    check('Replying to Quillbot: "✅ **Barony** was added' in turn_text and "[silent]" in turn_text,
          "announcement quoted with the silence rule")
    check(not typing_used, "no typing indicator for replies that might be ignored")
    client.queue.append(response([Block("text", "It's in the library, not installed.")], "end_turn"))
    await cc.on_message_without_command(reply(alex, "is it installed too?", announcement))
    check(channel.sent[-1].content == "It's in the library, not installed.", "question about the post answered")
    channel.typing = orig_typing

    # --- !butler with nothing says what it does ---
    await run(alex, "!butler")
    check("Ask me anything" in channel.sent[-1].content and "`!ai` works the same way" in channel.sent[-1].content,
          "butler intro")

    # --- daily limit: chat is stopped, bot questions still answered ---
    await cc.config.guild(guild).daily_limit.set(1)
    client.queue.append(response([Block("text", "Some chat.")], "end_turn"))
    await run(alex, "!ai tell me a joke")
    check("used all" in channel.sent[-1].content, "over the limit: chat stopped")
    client.queue += [lookup(["GameManager"]), response([Block("text", "Use `!games own <game>`.")], "end_turn")]
    await run(alex, "!ai how do I add a game?")
    check(channel.sent[-1].content == "Use `!games own <game>`.", "over the limit: bot questions still answered")
    await cc.config.guild(guild).daily_limit.set(0)

    # --- actions off: no run tool, explain-only rule ---
    await cc.config.guild(guild).guide_actions.set(False)
    client.queue.append(response([Block("text", "Type `!games install Valorant`.")], "end_turn"))
    await run(alex, "!ai install valorant")
    names = [t.get("name") for t in client.calls[-1]["tools"]]
    check("run_commands" not in names and "can't run commands" in client.calls[-1]["system"][0]["text"], "actions disabled")
    await cc.config.guild(guild).guide_actions.set(True)

    # --- !myai is gone: one conversation per channel ---
    check(bot.get_command("myai") is None, "no !myai")
    client.queue.append(response([Block("text", "Shared answer.")], "end_turn"))
    await run(alex, "!ai a question")
    answer = channel.sent[-1]
    client.queue.append(response([Block("text", "Sure.")], "end_turn"))
    r = FakeMessage(channel, "me too", author=brad)
    r.reference = SimpleNamespace(message_id=answer.id, resolved=answer)

    async def fetch_message(mid):
        return answer
    channel.fetch_message = fetch_message
    await cc.on_message_without_command(r)
    check(channel.sent[-1].content == "Sure.", "anyone can continue the channel's conversation")

    passed = sum(ok for ok, _ in results)
    print(f"{passed}/{len(results)} passed")


asyncio.run(main())
