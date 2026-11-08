"""SetupWizard: `!setup`, the private wizard, its pages, and changes made by running the server's own commands."""
import asyncio
from types import SimpleNamespace

from harness import (LAYOUT_PROBLEMS, FakeGuild, FakeInteraction, FakeMessage, TestBot, card_buttons, card_text,
                     dcommands, discord, load)

sw_mod = load("setupwizard", "setupwizard")
gm_mod = load("gamemanager", "gamemanager")
claude_mod = load("claude", "claude")
sp_mod = load("speakup", "speakup")
bg_mod = load("buttongreeter", "buttongreeter")
parlor_mod = load("parlor", "parlor")
censor_mod = load("censord", "censord")
ui = sw_mod.ui
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


class Role:
    def __init__(self, guild, rid, name, position):
        self.guild, self.id, self.name, self.position = guild, rid, name, position
        self.mention = f"<@&{rid}>"

    def __ge__(self, other):
        return self.position >= other.position

    def __eq__(self, other):
        return getattr(other, "id", None) == self.id

    def __hash__(self):
        return hash(self.id)


class Channel:
    def __init__(self, cid, name, kind):
        self.id, self.name, self.kind = cid, name, kind
        self.mention = f"<#{cid}>"


class FakeCore(dcommands.Cog, name="Core"):
    """Stand-ins for Red's own commands (set roles, modlogset, warningset, slash, antispamset): they record what ran."""

    def __init__(self):
        self.ran = []

    @dcommands.group(name="set")
    async def set_(self, ctx):
        pass

    @set_.group(name="roles")
    async def roles(self, ctx):
        pass

    @roles.command(name="addmodrole")
    async def addmodrole(self, ctx, role: int):
        self.ran.append(("addmodrole", role))
        await ctx.send("That role is now considered a mod role.")

    @roles.command(name="removemodrole")
    async def removemodrole(self, ctx, role: int):
        self.ran.append(("removemodrole", role))

    @roles.command(name="addadminrole")
    @dcommands.check(lambda ctx: ctx.author.id == ctx.guild.owner_id)
    async def addadminrole(self, ctx, role: int):
        self.ran.append(("addadminrole", role))

    @dcommands.group(name="slash")
    async def slash(self, ctx):
        pass

    @slash.command(name="enable")
    async def slash_enable(self, ctx, name: str, kind: str = "slash"):
        self.ran.append(("enable", name, kind))

    @slash.command(name="sync")
    async def slash_sync(self, ctx):
        self.ran.append(("sync",))
        await ctx.send(embed=discord.Embed(description="Synced 4 commands."))

    @dcommands.command(name="ownersonly")
    @dcommands.check(lambda ctx: False)
    async def ownersonly(self, ctx):
        self.ran.append(("ownersonly",))


class CustomGroup:
    def __init__(self, store, key):
        self.store, self.key = store, key

    async def all(self):
        if len(self.key) == 1:
            return {k[1]: v for k, v in self.store.items() if k[0] == self.key[0]}
        return self.store.get(self.key, {"dest_category_id": None})

    async def set(self, value):
        self.store[self.key] = value


class FakeAutoRoom(dcommands.Cog, name="AutoRoom"):
    def __init__(self):
        self.store, self.perms_ok = {}, True
        self.config = SimpleNamespace(custom=lambda name, *key: CustomGroup(self.store, key))

    def check_perms_source_dest(self, source, dest, *, with_manage_roles_guild=False, detailed=False):
        return self.perms_ok, True, None if self.perms_ok else "**Move Members** missing in the category"


async def main():
    guild = FakeGuild()
    guild.owner_id = 1
    brad = guild.add(1, "Brad", admin=True)
    alex = guild.add(2, "Alex")
    channel = guild.channel
    roles = {r.id: r for r in (Role(guild, 70, "Raiders", 3), Role(guild, 71, "Member", 2), Role(guild, 72, "Mods", 4),
                               Role(guild, 73, "Owners", 9))}
    guild.get_role = roles.get
    guild.me.top_role = Role(guild, 99, "ButlerBot", 5)
    extra = {600: Channel(600, "deals", "text"), 601: Channel(601, "Lounge", "voice"),
             602: Channel(602, "Voice rooms", "category")}
    orig_get = guild.get_channel_or_thread
    guild.get_channel = guild.get_channel_or_thread = lambda cid: extra.get(cid) or orig_get(cid)
    async def convert_channel(self, ctx, argument):   # the real converters need a gateway connection
        digits = "".join(c for c in argument if c.isdigit())
        found = ctx.guild.get_channel(int(digits)) if digits else None
        if found is None:
            raise dcommands.ChannelNotFound(argument)
        return found
    dcommands.TextChannelConverter.convert = convert_channel
    dcommands.VoiceChannelConverter.convert = convert_channel

    async def convert_role(self, ctx, argument):
        digits = "".join(c for c in argument if c.isdigit())
        found = ctx.guild.get_role(int(digits)) if digits else None
        if found is None:
            raise dcommands.RoleNotFound(argument)
        return found
    dcommands.RoleConverter.convert = convert_role
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    for cog in (gm_mod.GameManager(bot), claude_mod.ClaudeChat(bot), sp_mod.SpeakUp(bot),
                bg_mod.ButtonGreeter(bot), parlor_mod.Parlor(bot), censor_mod.Censord(bot)):
        await bot.add_cog(cog)
    gm, cc, sp = bot.get_cog("GameManager"), bot.get_cog("ClaudeChat"), bot.get_cog("SpeakUp")
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    sp.reminder_loop.cancel()
    bot.get_cog("Parlor").game_loop.cancel()
    core = FakeCore()
    await bot.add_cog(core)
    sw = sw_mod.SetupWizard(bot)
    await bot.add_cog(sw)

    mod_roles = []

    async def get_mod_roles(g):
        return [roles[r] for r in mod_roles]

    async def get_admin_roles(g):
        return []
    bot.get_mod_roles, bot.get_admin_roles = get_mod_roles, get_admin_roles

    # ---- the launcher ----
    ctx = await bot.get_context(FakeMessage(channel, "!setup", author=brad))
    await bot.invoke(ctx)
    launcher = channel.sent[-1]
    check(card_text(launcher).startswith("### ⚙️ Server setup") and
          [b.custom_id for b in card_buttons(launcher)] == ["sw:open"], card_text(launcher))
    i = FakeInteraction(bot, guild, alex, channel, message=launcher)
    await sw_mod.OpenButton().callback(i)
    check(i.response.calls[0][1].startswith("🔒") and i.response.calls[0][2]["ephemeral"], "only admins open it")
    sent_before = len(channel.sent)
    i = FakeInteraction(bot, guild, brad, channel, message=launcher)
    await sw_mod.OpenButton().callback(i)
    kind, _, kw = i.response.calls[0]
    wizard = kw["view"]
    check(kind == "send" and kw["ephemeral"] and isinstance(wizard, sw_mod.Wizard), "the wizard opens privately")
    home = card_text(wizard)
    check(home.startswith("### ⚙️ Server setup") and "**Permissions** ⚠️" in home and "Missing 10 permissions" in home
          and "**Welcome flow**" in home and "Not set up" in home and "**Voice rooms**" not in home,
          f"overview lists the steps whose cogs are loaded: {home}")
    check(any(b.label == "Start" for b in card_buttons(wizard)), "Start on a fresh server")
    wizard_msg = FakeMessage(channel, view=wizard)

    async def click(view_msg, label, who=brad):
        b = next(b for b in card_buttons(view_msg.view) if b.label == label)
        inter = FakeInteraction(bot, guild, who, channel, message=view_msg)
        await b.callback(inter)
        return inter

    def selects(view):
        out = []
        for item in view.walk_children():
            if isinstance(item, discord.ui.Select | discord.ui.ChannelSelect | discord.ui.RoleSelect):
                out.append(item)
        return out

    async def pick(view_msg, placeholder, values, who=brad):
        s = next(s for s in selects(view_msg.view) if s.placeholder.startswith(placeholder))
        inter = FakeInteraction(bot, guild, who, channel, message=view_msg)
        inter.data = {"values": [str(v) for v in values]}
        await s.callback(inter)
        return inter

    # ---- every page draws within Discord's limits ----
    for key, title in wizard.steps():
        wizard.page = key
        await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
        text = card_text(wizard_msg)
        check(text.startswith(f"### ⚙️ Setup: {title} (") and text.endswith("-# Only you can see this"),
              f"page {key}: {text[:80]}")
    check(not LAYOUT_PROBLEMS, f"no layout problems: {LAYOUT_PROBLEMS[:3]}")
    check(set(await sw.config.guild(guild).visited()) == {k for k, _ in wizard.steps()}, "pages visited are remembered")
    wizard.page = None
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    check(any(b.label == "Carry on" for b in card_buttons(wizard_msg.view)), "Carry on once started")

    # ---- navigation ----
    await click(wizard_msg, "Carry on")
    check(wizard.page == "perms", f"carry on goes to the first step: {wizard.page}")
    await click(wizard_msg, "Next")
    check(wizard.page == "staff", "Next")
    await click(wizard_msg, "Back")
    await click(wizard_msg, "All steps")
    check(wizard.page is None, "All steps goes home")
    inter = await pick(wizard_msg, "Go to a step", ["games"])
    check(wizard.page == "games", "the step menu jumps")

    # ---- the permissions page ----
    wizard.page = "perms"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    text = card_text(wizard_msg)
    check("**Manage Events**\n-# For Discord events for game nights" in text
          and "**Create Public Threads, Send Messages in Threads**" in text, f"missing permissions listed: {text}")

    # ---- changes run the server's own commands, privately ----
    wizard.page = "games"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    posted = len(channel.sent)
    await pick(wizard_msg, "Sale alerts channel", [channel.id])
    check(await gm.config.guild(guild).sale_channel() == channel.id, "sale alerts channel set by its own command")
    text = card_text(wizard_msg)
    check(text.split("\n")[1].startswith(f"-# ✅ Sale alerts will be posted in <#{channel.id}>.")
          and "**Sale alerts** · <#500>" in text, f"the command's reply shows in the wizard: {text[:300]}")
    check(len(channel.sent) == posted, "nothing is posted in the channel")
    await pick(wizard_msg, "Sale alerts channel", [])
    check(await gm.config.guild(guild).sale_channel() is None, "clearing the menu turns sale alerts off")
    await pick(wizard_msg, "Server timezone", ["America/Los_Angeles"])
    check(await gm.config.guild(guild).timezone() == "America/Los_Angeles", "timezone set")
    await click(wizard_msg, "Members add games")
    check(await gm.config.guild(guild).member_add() is True, "toggle on")
    await click(wizard_msg, "Members add games")
    check(await gm.config.guild(guild).member_add() is False, "toggle off")

    wizard.page = "ai"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    await click(wizard_msg, "@mentions")
    check(await cc.config.guild(guild).guide_mentions() is False, "AI mentions off")
    await pick(wizard_msg, "Daily limit", ["20"])
    check(await cc.config.guild(guild).daily_limit() == 20, "daily limit")

    wizard.page = "replies"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    await click(wizard_msg, "Link summaries")
    check((await sp.config.guild(guild).features())["links"] is False, "a SpeakUp feature off")

    # ---- staff roles: differences become add/remove commands; checks are kept ----
    wizard.page = "staff"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    mod_roles[:] = [71]
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    await pick(wizard_msg, "Mod roles", [72])
    check(core.ran[-2:] == [("addmodrole", 72), ("removemodrole", 71)], f"mod roles: {core.ran}")
    check("That role is now considered a mod role." in card_text(wizard_msg), "Red's reply shown")
    await pick(wizard_msg, "Game admin role", [70])
    check(await gm.config.guild(guild).admin_role() == 70, "game admin role")
    note = await sw.run(alex, launcher, ["set roles addadminrole 73", "ownersonly", "nosuchcommand"])
    check(note.split("\n") == ["🔒 You can't run `!set roles addadminrole`.", "🔒 You can't run `!ownersonly`.",
                               "❌ `!nosuchcommand` isn't available here. Is its cog loaded?"],
          f"commands keep their own checks: {note}")
    check(("addadminrole", 73) not in core.ran, "nothing ran without permission")
    mod_roles.clear()

    # ---- welcome: a group button asks for its label ----
    wizard.page = "welcome"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    inter = await pick(wizard_msg, "Add a group button", [70])
    modal = inter.response.calls[-1][1]
    check(inter.response.calls[-1][0] == "modal" and modal.label.default == "Raiders", "label asked, role name first")
    modal.label._value = "RDR"
    submit = FakeInteraction(bot, guild, brad, channel, message=wizard_msg)
    await modal.on_submit(submit)
    greeter = await bot.get_cog("ButtonGreeter").config.guild(guild).roles()
    check(greeter == {"RDR": 70} and "RDR (<@&70>)" in card_text(wizard_msg), f"group button added: {greeter}")
    await pick(wizard_msg, "Rules role", [73])
    check("Move ButlerBot's role above <@&73>" in (await wizard.page_perms())[1], "role order problems spotted")

    # ---- weekly games ----
    wizard.page = "fun"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    await pick(wizard_msg, "Weekly caption contest", [channel.id])
    check((await bot.get_cog("Parlor").config.guild(guild).caption_weekly()).get("channel") == channel.id, "weekly on")
    await pick(wizard_msg, "Weekly caption contest", [])
    check(await bot.get_cog("Parlor").config.guild(guild).caption_weekly() == {}, "weekly off")

    # ---- moderation: the word filter ----
    wizard.page = "moderation"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    await pick(wizard_msg, "Word filter…", ["low"])
    check(await bot.get_cog("Censord").config.guild(guild).global_level() == "low", "word filter level")

    # ---- slash commands: the owner turns them all on ----
    enabled = {"slash": {"games": None}, "message": {}}

    async def list_enabled():
        return enabled
    bot.list_enabled_app_commands = list_enabled
    wizard.page = "apps"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    text = card_text(wizard_msg)
    check("**/games** ✅" in text and "**/catchup**\n-# Off" in text and "Translate" not in text,
          f"apps listed for loaded cogs: {text}")
    await click(wizard_msg, "Turn them all on")
    check(core.ran[-3:] == [("enable", "catchup", "slash"), ("enable", "Summarize link", "message"), ("sync",)]
          and "Synced 4 commands." in card_text(wizard_msg), f"enabled and synced: {core.ran[-3:]}")
    alex_wizard = sw_mod.Wizard(sw, alex, launcher)
    alex_wizard.page = "apps"
    check("Only the bot owner can switch these on" in "\n".join(
        p for p in await alex_wizard.page_apps() if isinstance(p, str)), "others are told who can")

    # ---- voice rooms ----
    ar = FakeAutoRoom()
    await bot.add_cog(ar)
    check("voice" in [k for k, _ in wizard.steps()], "voice rooms appear when AutoRoom is loaded")
    made = []

    async def create_category(name, reason=None):
        made.append(("category", name))
        return extra[602]

    async def create_voice_channel(name, category=None, reason=None):
        made.append(("voice", name, category.id))
        return extra[601]
    guild.create_category, guild.create_voice_channel = create_category, create_voice_channel
    guild.me.guild_permissions.manage_channels = True
    for cid, cls, name in ((601, discord.VoiceChannel, "Lounge"), (602, discord.CategoryChannel, "Voice rooms")):
        real = cls.__new__(cls)   # real channel classes, so the wizard's isinstance checks pass
        real.id, real.name, real.guild = cid, name, guild
        extra[cid] = real
    wizard.page = "voice"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    check(next(b for b in card_buttons(wizard_msg.view) if b.label == "Save").disabled, "Save waits for both picks")
    await click(wizard_msg, "Make them for me")
    check(made == [("category", "Voice rooms"), ("voice", "➕ Join to create", 602)]
          and "Made <#601> in <#602>" in card_text(wizard_msg), f"channels made: {made}")
    await pick(wizard_msg, "Room type", ["private"])
    ar.perms_ok = False
    await click(wizard_msg, "Save")
    check("missing permissions" in card_text(wizard_msg) and not ar.store, "AutoRoom's own permission check is used")
    ar.perms_ok = True
    await click(wizard_msg, "Save")
    check(ar.store == {("1", "601"): {"dest_category_id": 602, "room_type": "private",
                                      "channel_name_type": "username"}}
          and "Voice rooms are on" in card_text(wizard_msg), f"saved like autoroomset create: {ar.store}")
    check(await sw.status(guild, "voice") == ("✅", "1 join-to-create channel"), "voice status")

    # ---- the wizard belongs to the person who opened it ----
    i = FakeInteraction(bot, guild, alex, channel, message=wizard_msg)
    check(not await wizard.interaction_check(i) and i.response.calls[0][1].startswith("🔒"), "not your wizard")

    await bot.remove_cog("SetupWizard")


asyncio.run(main())
passed = sum(ok for ok, _ in results)
print(f"{passed}/{len(results)} checks passed")
