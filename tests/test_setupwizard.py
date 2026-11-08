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

    @dcommands.group(name="autoroomset")
    async def autoroomset(self, ctx):
        pass

    @autoroomset.command(name="remove")
    async def remove(self, ctx, source: int):
        self.store.pop(("1", str(source)), None)
        await ctx.send(f"<#{source}> is no longer an AutoRoom Source channel.")

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

    def items(view):
        """The card's top-level items, in order."""
        container = next(c for c in view.children if isinstance(c, discord.ui.Container))
        return list(container.children)

    def field_select(view, label):
        """The menu under a field's bold label."""
        parts = items(view)
        for n, item in enumerate(parts):
            if isinstance(item, discord.ui.TextDisplay) and item.content.startswith(f"**{label}**"):
                return parts[n + 1].children[0]
        raise AssertionError(f"no field {label!r}")

    async def pick(view_msg, label, values, who=brad):
        select = field_select(view_msg.view, label)
        inter = FakeInteraction(bot, guild, who, channel, message=view_msg)
        inter.data = {"values": [str(v) for v in values]}
        await select.callback(inter)
        return inter

    def switch_text(view, label):
        return next(s for s in items(view) if isinstance(s, discord.ui.Section)
                    and s.children[0].content.startswith(f"**{label}**"))

    async def flip(view_msg, label, who=brad):
        section = switch_text(view_msg.view, label)
        inter = FakeInteraction(bot, guild, who, channel, message=view_msg)
        await section.accessory.callback(inter)
        return inter

    # ---- every page draws within Discord's limits, and every menu has a label ----
    for key, title in wizard.steps():
        wizard.page = key
        await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
        text = card_text(wizard_msg)
        check(text.startswith(f"### ⚙️ Setup: {title} (") and text.endswith("-# Changes save as soon as you make them"),
              f"page {key}: {text[:80]}")
        parts = items(wizard_msg.view)
        unlabelled = [n for n, item in enumerate(parts) if isinstance(item, discord.ui.ActionRow)
                      and isinstance(item.children[0], discord.ui.Select | discord.ui.ChannelSelect
                                     | discord.ui.RoleSelect)
                      and not (isinstance(parts[n - 1], discord.ui.TextDisplay)
                               and parts[n - 1].content.startswith("**"))]
        check(not unlabelled, f"page {key}: every menu has a bold label above it")
        check(all(len(item.children[0].content.split("\n")) == 2 for item in parts
                  if isinstance(item, discord.ui.Section)), f"page {key}: every switch says what it does")
        nav = [b.label for b in card_buttons(wizard_msg.view)][-4:]
        check(nav[1:] in (["Next", "Overview", "Close"], ["Finish", "Overview", "Close"]), f"page {key}: nav {nav}")
    check(not LAYOUT_PROBLEMS, f"no layout problems: {LAYOUT_PROBLEMS[:3]}")
    check(set(await sw.config.guild(guild).visited()) == {k for k, _ in wizard.steps()}, "pages visited are remembered")
    wizard.page = None
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    check([b.label for b in card_buttons(wizard_msg.view)] == ["Carry on", "Close"], "Carry on once started")

    # ---- navigation ----
    await click(wizard_msg, "Carry on")
    check(wizard.page == "perms", f"carry on goes to the first step: {wizard.page}")
    check(next(b for b in card_buttons(wizard_msg.view) if b.label == "Back").disabled, "no Back on the first step")
    await click(wizard_msg, "Next")
    check(wizard.page == "staff", "Next")
    await click(wizard_msg, "Back")
    await click(wizard_msg, "Overview")
    check(wizard.page is None, "Overview goes home")
    menu = next(i for i in wizard_msg.view.walk_children() if isinstance(i, discord.ui.Select))
    inter = FakeInteraction(bot, guild, brad, channel, message=wizard_msg)
    inter.data = {"values": ["games"]}
    await menu.callback(inter)
    check(wizard.page == "games", "the step menu jumps")

    # ---- the permissions page ----
    wizard.page = "perms"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    text = card_text(wizard_msg)
    check("**Manage Events** ⚠️\n-# For Discord events for game nights" in text
          and "**Create Public Threads, Send Messages in Threads** ⚠️" in text, f"missing permissions listed: {text}")

    # ---- changes run the server's own commands, privately ----
    wizard.page = "games"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    check(field_select(wizard_msg.view, "Sale alerts channel").placeholder == "Sale alerts are off",
          "an empty menu says what that means")
    posted = len(channel.sent)
    await pick(wizard_msg, "Sale alerts channel", [channel.id])
    check(await gm.config.guild(guild).sale_channel() == channel.id, "sale alerts channel set by its own command")
    text = card_text(wizard_msg)
    check(text.split("\n")[1] == f"✅ Sale alerts will be posted in <#{channel.id}>.",
          f"the command's reply shows under the title: {text[:300]}")
    check([o.id for o in field_select(wizard_msg.view, "Sale alerts channel").default_values] == [channel.id],
          "the menu shows the saved channel")
    check(len(channel.sent) == posted, "nothing is posted in the channel")
    check(switch_text(wizard_msg.view, "Free Epic games").accessory.label == "Turn on"
          and not switch_text(wizard_msg.view, "Free Epic games").accessory.disabled, "free games can be turned on now")
    await pick(wizard_msg, "Sale alerts channel", [])
    check(await gm.config.guild(guild).sale_channel() is None, "clearing the menu turns sale alerts off")
    check(switch_text(wizard_msg.view, "Free Epic games").accessory.disabled
          and "Needs a sale alerts channel first." in switch_text(wizard_msg.view, "Free Epic games").children[0].content,
          "a switch that can't work yet says why")
    await pick(wizard_msg, "Server timezone", ["America/Los_Angeles"])
    check(await gm.config.guild(guild).timezone() == "America/Los_Angeles", "timezone set")
    await flip(wizard_msg, "Members add games")
    check(await gm.config.guild(guild).member_add() is True
          and switch_text(wizard_msg.view, "Members add games").children[0].content.startswith(
              "**Members add games** · On") and switch_text(wizard_msg.view, "Members add games").accessory.label
          == "Turn off", "switch on")
    await flip(wizard_msg, "Members add games")
    check(await gm.config.guild(guild).member_add() is False, "switch off")

    wizard.page = "ai"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    text = card_text(wizard_msg)
    check("**Personality** · ButlerBot's own\n-# You are ButlerBot" in text, f"the personality in use: {text}")
    check(next(b for b in card_buttons(wizard_msg.view) if b.label == "Use ButlerBot's own").disabled,
          "nothing to reset yet")
    await flip(wizard_msg, "@mentions go to the AI")
    check(await cc.config.guild(guild).guide_mentions() is False, "AI mentions off")
    await pick(wizard_msg, "Daily limit per member", ["20"])
    check(await cc.config.guild(guild).daily_limit() == 20, "daily limit")
    inter = await click(wizard_msg, "Write your own")
    modal = inter.response.calls[-1][1]
    check(inter.response.calls[-1][0] == "modal" and isinstance(modal, sw_mod.PersonaModal), "personality form")
    modal.text._value = "You are a cheerful pirate.\nKeep it short."
    await modal.on_submit(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    check(await cc.config.guild(guild).persona() == "You are a cheerful pirate.\nKeep it short."
          and "**Personality** · This server's own\n-# You are a cheerful pirate. Keep it short." in card_text(wizard_msg),
          f"personality written: {card_text(wizard_msg)[-300:]}")
    await click(wizard_msg, "Use ButlerBot's own")
    check(await cc.config.guild(guild).persona() is None, "back to ButlerBot's own")

    wizard.page = "replies"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    check("Channels where ButlerBot never chimes in on its own" in card_text(wizard_msg), "quiet channels explained")
    await flip(wizard_msg, "Link summaries")
    check((await sp.config.guild(guild).features())["links"] is False, "a SpeakUp feature off")
    await pick(wizard_msg, "Quiet channels", [channel.id])
    check(await sp.config.guild(guild).quiet_channels() == [channel.id], "a quiet channel")

    # ---- staff roles: differences become add/remove commands; checks are kept ----
    wizard.page = "staff"
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
    alex_staff = await sw_mod.Wizard(sw, alex, launcher).page_staff()
    check(any("Only the server owner can change mod and admin roles." in p for p in alex_staff if isinstance(p, str)),
          "others see the roles, read-only")

    # ---- welcome: a group button asks for its label ----
    wizard.page = "welcome"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    inter = await pick(wizard_msg, "Group buttons", [70])
    modal = inter.response.calls[-1][1]
    check(inter.response.calls[-1][0] == "modal" and modal.label.default == "Raiders", "label asked, role name first")
    modal.label._value = "RDR"
    await modal.on_submit(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    greeter = await bot.get_cog("ButtonGreeter").config.guild(guild).roles()
    check(greeter == {"RDR": 70} and "Now: RDR (<@&70>)." in card_text(wizard_msg), f"group button added: {greeter}")
    await pick(wizard_msg, "Rules role", [73])
    check(any("Move ButlerBot's role above <@&73>" in p for p in await wizard.page_perms() if isinstance(p, str)),
          "role order problems spotted")

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
    await pick(wizard_msg, "Word filter", ["low"])
    check(await bot.get_cog("Censord").config.guild(guild).global_level() == "low", "word filter level")
    check("trips the filter 3 times within 60 seconds" in card_text(wizard_msg), "repeat offenders explained")

    # ---- slash commands: the owner turns them all on ----
    enabled = {"slash": {"games": None}, "message": {}}

    async def list_enabled():
        return enabled
    bot.list_enabled_app_commands = list_enabled
    wizard.page = "apps"
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    text = card_text(wizard_msg)
    check("**/games** · On" in text and "**/catchup** · Off\n-# A private summary" in text and "Translate" not in text,
          f"apps listed for loaded cogs: {text}")
    await click(wizard_msg, "Turn them on")
    check(core.ran[-3:] == [("enable", "catchup", "slash"), ("enable", "Summarize link", "message"), ("sync",)]
          and "Synced 4 commands." in card_text(wizard_msg), f"enabled and synced: {core.ran[-3:]}")
    alex_wizard = sw_mod.Wizard(sw, alex, launcher)
    check(any("Only the bot owner can switch these on" in p for p in await alex_wizard.page_apps()
              if isinstance(p, str)), "others are told who can")

    # ---- finishing and closing ----
    check([b.label for b in card_buttons(wizard_msg.view)][-3] == "Finish", "the last step finishes")
    await click(wizard_msg, "Finish")
    text = card_text(wizard_msg)
    check(wizard.page == "done" and text.startswith("### ⚙️ Setup finished\n✅ That's every step.")
          and "These could still use a look:" in text and "**Permissions** ⚠️" in text and "**What's next**" in text,
          f"finish page: {text}")
    check([b.label for b in card_buttons(wizard_msg.view)][:2] == ["Close", "Back to overview"], "finish buttons")
    deleted = []
    inter = FakeInteraction(bot, guild, brad, channel, message=wizard_msg)

    async def delete_original_response():
        deleted.append(True)
    inter.delete_original_response = delete_original_response
    await next(b for b in card_buttons(wizard_msg.view) if b.label == "Close").callback(inter)
    check(deleted and wizard.is_finished(), "Close removes the wizard")

    # ---- voice rooms ----
    wizard = sw_mod.Wizard(sw, brad, launcher)
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
    for cid, cls, name in ((601, discord.VoiceChannel, "Lounge"), (602, discord.CategoryChannel, "Voice rooms"),
                           (603, discord.VoiceChannel, "Old lobby"), (604, discord.CategoryChannel, "autorooms")):
        real = cls.__new__(cls)   # real channel classes, so the wizard's isinstance checks pass
        real.id, real.name, real.guild = cid, name, guild
        extra[cid] = real
    wizard.page = "voice"
    wizard_msg = FakeMessage(channel, view=wizard)
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    check(next(b for b in card_buttons(wizard_msg.view) if b.label == "Save").disabled, "Save waits for both picks")
    await click(wizard_msg, "Make the channels")
    check(made == [("category", "Voice rooms"), ("voice", "➕ Join to create", 602)]
          and "Made <#601> in <#602>" in card_text(wizard_msg), f"channels made: {made}")
    check("Make the channels" not in [b.label for b in card_buttons(wizard_msg.view)], "no need to make them again")
    await pick(wizard_msg, "Who can get in", ["private"])
    ar.perms_ok = False
    await click(wizard_msg, "Save")
    check("missing permissions" in card_text(wizard_msg) and not ar.store, "AutoRoom's own permission check is used")
    ar.perms_ok = True
    await click(wizard_msg, "Save")
    check(ar.store == {("1", "601"): {"dest_category_id": 602, "room_type": "private",
                                      "channel_name_type": "username"}}
          and "Voice rooms are on" in card_text(wizard_msg), f"saved like autoroomset create: {ar.store}")
    check(await sw.status(guild, "voice") == ("✅", "1 join-to-create channel"), "voice status")
    # An existing setup (made with autoroomset) opens ready to edit, and keeps its other settings when saved
    ar.store = {("1", "603"): {"dest_category_id": 604, "room_type": "locked", "channel_name_type": "game",
                               "perm_send_messages": True}}
    wizard = sw_mod.Wizard(sw, brad, launcher)
    wizard.page = "voice"
    wizard_msg = FakeMessage(channel, view=wizard)
    await wizard.show(FakeInteraction(bot, guild, brad, channel, message=wizard_msg))
    text = card_text(wizard_msg)
    check("**Editing: <#603>**" in text
          and [o.id for o in field_select(wizard_msg.view, "Where new rooms go").default_values] == [604]
          and any(o.default and o.value == "locked" for o in field_select(wizard_msg.view, "Who can get in").options),
          f"the existing setup is shown: {text}")
    check({"Add another", "Turn off"} <= {b.label for b in card_buttons(wizard_msg.view)}, "edit buttons")
    await pick(wizard_msg, "Room names", ["username"])
    await click(wizard_msg, "Save")
    check(ar.store[("1", "603")] == {"dest_category_id": 604, "room_type": "locked", "channel_name_type": "username",
                                     "perm_send_messages": True}, f"other settings kept: {ar.store}")
    await click(wizard_msg, "Turn off")
    check(not ar.store and "no longer an AutoRoom Source" in card_text(wizard_msg), "turned off with autoroomset")

    # ---- the wizard belongs to the person who opened it ----
    i = FakeInteraction(bot, guild, alex, channel, message=wizard_msg)
    check(not await wizard.interaction_check(i) and i.response.calls[0][1].startswith("🔒"), "not your wizard")

    await bot.remove_cog("SetupWizard")


asyncio.run(main())
passed = sum(ok for ok, _ in results)
print(f"{passed}/{len(results)} checks passed")
