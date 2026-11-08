"""ButtonGreeter: persistent welcome/rules buttons, answers on every failure, one ping, nickname tags, prefixes."""
import asyncio
import re
import types

from harness import (FakeChannel, FakeGuild, FakeInteraction, FakeMember, FakeMessage, TestBot, card_color,
                     card_text, discord, load)

bg_mod = load("buttongreeter", "buttongreeter")
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


def forbidden():
    return discord.Forbidden(types.SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")


# ---------------- richer fakes (local to this test) ----------------

class FakeRole:
    def __init__(self, rid, name, position=1):
        self.id, self.name, self.position = rid, name, position
        self.mention = f"<@&{rid}>"

    def __ge__(self, other):
        return self.position >= other.position

    def __eq__(self, other):
        return getattr(other, "id", None) == self.id

    def __hash__(self):
        return hash(self.id)


class Member(FakeMember):
    def __init__(self, guild, uid, name, admin=False):
        super().__init__(guild, uid, name, admin)
        self.display_avatar = types.SimpleNamespace(url="https://example.invalid/a.png")
        self.fail_roles = self.fail_nick = False

    async def add_roles(self, *roles, **kw):
        if self.fail_roles:
            raise forbidden()
        self.roles += [r for r in roles if r not in self.roles]

    async def remove_roles(self, *roles, **kw):
        if self.fail_roles:
            raise forbidden()
        self.roles = [r for r in self.roles if r not in roles]

    async def edit(self, nick=None, **kw):
        if self.fail_nick:
            raise forbidden()
        self.display_name = nick


class Guild(FakeGuild):
    def __init__(self):
        super().__init__()
        self.role_map = {}
        self.admin_channel = FakeChannel(self, 600)
        self.admin_channel.name = "admin"
        self.text_channels.append(self.admin_channel)
        self.me.top_role = self.role(99, "Bot", position=50)

    def role(self, rid, name, position=1):
        self.role_map[rid] = FakeRole(rid, name, position)
        return self.role_map[rid]

    def get_role(self, rid):
        return self.role_map.get(rid)

    def add(self, uid, name, admin=False):
        m = Member(self, uid, name, admin)
        self.members.append(m)
        return m


async def _delete(self, **kw):
    self.deleted = True
    self.channel.messages.pop(self.id, None)


FakeMessage.delete = _delete
FakeMessage.deleted = False


class Ctx:
    def __init__(self, bot, guild, author):
        self.bot, self.guild, self.author, self.channel = bot, guild, author, guild.channel
        self.message = FakeMessage(guild.channel, "", author=author)

    async def send(self, content=None, **kw):
        return await self.channel.send(content, **kw)


def items(target):
    """The persistent buttons in a card (message or view), as DynamicItems, in order."""
    view = getattr(target, "view", target)
    return [i for i in view.walk_children() if isinstance(i, discord.ui.DynamicItem)]


def sent_text(inter):
    """Everything an interaction answered, privately or not."""
    out = [c[1] for c in inter.response.calls if c[0] == "send"]
    out += [c[0] for c in inter.followup.calls]
    return out


def ephemeral_ok(inter):
    return all(c[2].get("ephemeral") for c in inter.response.calls if c[0] == "send") and \
        all(c[1].get("ephemeral") for c in inter.followup.calls)


# ---------------- tests ----------------

def pure_tests():
    t = bg_mod.tagged_nick
    check(t("Alice", "KVK") == "[KVK] Alice", "tag added")
    check(t("[OLD] Alice", "KVK") == "[KVK] Alice", "existing tag replaced")
    check(t("  [old]   Alice ", "ABC") == "[ABC] Alice", "spaces around old tag")
    check(t("Bo]b", "KVK") == "[KVK] Bo]b", "a ] later in the name is kept")
    check(len(t("A" * 40, "KVK")) == 32, "fits 32 characters")
    check(bg_mod.clean_tag(" [kvk] ") == "KVK", "tag typed with brackets")
    for item, cid in ((bg_mod.RoleItem(10, 5, "KVK"), "bg:role:10:5"), (bg_mod.CustomItem(5), "bg:custom:5"),
                      (bg_mod.NoneItem(5), "bg:none:5"), (bg_mod.RulesItem("yes", 5), "bg:rules:yes:5"),
                      (bg_mod.RulesItem("no", 5), "bg:rules:no:5")):
        check(item.custom_id == cid and re.fullmatch(type(item).__discord_ui_compiled_template__, cid),
              f"custom id {cid}")
    g = Guild()
    newcomer = g.add(5, "Newcomer")
    view = bg_mod.welcome_card(newcomer, {"KVK": 10, "ABC": 11})
    styles = [c.item.style for c in items(view)]
    check(discord.ButtonStyle.danger not in styles and discord.ButtonStyle.success not in styles,
          "no red or green buttons on the welcome")
    rules = bg_mod.rules_card(newcomer, "#rules")
    check([(c.item.label, c.item.style) for c in items(rules)] == [("Yes, I agree", discord.ButtonStyle.primary),
                                                           ("No", discord.ButtonStyle.secondary)], "rules buttons")


async def flow_tests():
    guild = Guild()
    admin = guild.add(1, "Brad", admin=True)
    alice = guild.add(2, "[OLD] Alice")
    bob = guild.add(3, "Bob")
    kvk, abc, rules_role = guild.role(10, "Kings"), guild.role(11, "Aces"), guild.role(20, "Agreed")
    bot = TestBot(guild)
    cog = bg_mod.ButtonGreeter(bot)
    await bot.add_cog(cog)
    store = bot._connection._view_store
    check(all(item.__discord_ui_compiled_template__ in store._dynamic_items for item in bg_mod.GREETER_ITEMS),
          "dynamic items registered on load")

    conf = cog.config.guild(guild)
    await conf.welcome_channel.set(guild.channel.id)
    await conf.admin_channel.set(guild.admin_channel.id)
    await conf.rules_channel.set(700)
    await conf.rules_role.set(20)
    await conf.roles.set({"KVK": 10, "ABC": 11})

    # Welcome: pings only the new member, with persistent buttons
    await cog.on_member_join(alice)
    welcome = guild.channel.sent[-1]
    am = welcome.kw["allowed_mentions"]
    check(not welcome.content and alice.mention in card_text(welcome) and am.users == [alice] and not am.everyone
          and not am.roles, "welcome pings only the new member")
    ids = [c.custom_id for c in items(welcome)]
    check(ids == ["bg:role:10:2", "bg:role:11:2", "bg:custom:2", "bg:none:2"], f"welcome ids {ids}")

    # Someone else clicks: refused privately, nothing happens
    kvk_button = items(welcome)[0]
    i = FakeInteraction(bot, guild, bob, guild.channel, message=welcome)
    await kvk_button.callback(i)
    check(sent_text(i) == [bg_mod.NOT_YOURS] and ephemeral_ok(i) and kvk not in bob.roles, "not for you")
    check(bg_mod.NOT_YOURS.startswith("🔒"), "lock symbol")

    # Alice picks KVK: role, tag replaced, greeter removed, rules prompt mentions without pinging
    i = FakeInteraction(bot, guild, alice, guild.channel, message=welcome)
    await kvk_button.callback(i)
    rules_msg = guild.channel.sent[-1]
    check(kvk in alice.roles and alice.display_name == "[KVK] Alice", f"role and nick: {alice.display_name}")
    check(welcome.deleted, "welcome message removed")
    check(alice.mention in card_text(rules_msg) and rules_msg.kw["allowed_mentions"].users is False,
          "rules prompt mentions without a ping")
    check("Protocol agreement" in card_text(rules_msg) and "<#700>" in card_text(rules_msg),
          "rules prompt text kept")
    check([c.custom_id for c in items(rules_msg)] == ["bg:rules:yes:2", "bg:rules:no:2"], "rules ids")

    # Restart: a fresh cog, buttons rebuilt from their custom IDs
    await bot.remove_cog("ButtonGreeter")
    check(not any(item.__discord_ui_compiled_template__ in store._dynamic_items for item in bg_mod.GREETER_ITEMS),
          "dynamic items removed on unload")
    bot2 = TestBot(guild)
    cog2 = bg_mod.ButtonGreeter(bot2)
    cog2.config = cog.config            # same saved settings
    await bot2.add_cog(cog2)

    async def rebuilt(cls, message, n):
        base = items(message)[n]
        match = re.fullmatch(cls.__discord_ui_compiled_template__, base.custom_id)
        return await cls.from_custom_id(None, base, match)

    no = await rebuilt(bg_mod.RulesItem, rules_msg, 1)
    i = FakeInteraction(bot2, guild, alice, guild.channel, message=rules_msg)
    await no.callback(i)
    check(sent_text(i) == ["⚠️ You need to agree to the rules to finish joining.\n-# This prompt stays here, so "
                           "press Yes, I agree whenever you're ready."] and ephemeral_ok(i),
          "No explains and keeps the prompt (one line, the advice underneath)")
    check(not rules_msg.deleted and rules_role not in alice.roles, "prompt still there after No")

    yes = await rebuilt(bg_mod.RulesItem, rules_msg, 0)
    i = FakeInteraction(bot2, guild, bob, guild.channel, message=rules_msg)
    await yes.callback(i)
    check(sent_text(i) == [bg_mod.NOT_YOURS], "rules not for others")
    i = FakeInteraction(bot2, guild, alice, guild.channel, message=rules_msg)
    await yes.callback(i)
    check(rules_role in alice.roles and rules_msg.deleted, "agreeing after a restart works")
    check(sent_text(i)[0].startswith("✅") and "Agreed" in sent_text(i)[0], "agree confirmed")

    # No rules role set: the member still gets an answer, admins get told
    await conf.rules_role.set(None)
    await cog2.on_member_join(bob)
    welcome_b = guild.channel.sent[-1]
    none_btn = await rebuilt(bg_mod.NoneItem, welcome_b, 3)
    before_admin = len(guild.admin_channel.sent)
    i = FakeInteraction(bot2, guild, bob, guild.channel, message=welcome_b)
    await none_btn.callback(i)
    check(sent_text(i) == ["✅ You're all set. Welcome!"] and ephemeral_ok(i), "no rules role: still answered")
    report = guild.admin_channel.sent[-1] if len(guild.admin_channel.sent) > before_admin else None
    check(report is not None and report.content.startswith("⚠️") and "!bg setrulesrole" in report.content
          and report.kw["allowed_mentions"].users is False, "admins told how to fix it")
    check("[p]" not in report.content, "no literal [p]")
    await conf.rules_role.set(20)

    # Role can't be given: answered (no "interaction failed") and reported
    carol = guild.add(4, "Carol")
    await cog2.on_member_join(carol)
    welcome_c = guild.channel.sent[-1]
    carol.fail_roles = True
    i = FakeInteraction(bot2, guild, carol, guild.channel, message=welcome_c)
    await (await rebuilt(bg_mod.RoleItem, welcome_c, 1)).callback(i)
    check(sent_text(i) == ["❌ I couldn't give you that role.\n-# A moderator has been told."] and ephemeral_ok(i),
          "role failure answered")
    check("Aces" in guild.admin_channel.sent[-1].content, "role failure reported")
    check(not welcome_c.deleted, "welcome stays so they can try again")
    carol.fail_roles = False

    # An unexpected error is answered too
    async def boom(*a, **k):
        raise RuntimeError("database on fire")
    real = cog2.show_rules
    cog2.show_rules = boom
    i = FakeInteraction(bot2, guild, carol, guild.channel, message=welcome_c)
    await (await rebuilt(bg_mod.RoleItem, welcome_c, 1)).callback(i)
    check(sent_text(i) == [bg_mod.SOMETHING_WRONG], "unexpected error answered")
    check("database on fire" not in guild.admin_channel.sent[-1].content, "no raw exception text posted")
    cog2.show_rules = real

    # Custom alliance: modal, tag cleaned, nickname failure explained
    dave = guild.add(5, "Dave")
    await cog2.on_member_join(dave)
    welcome_d = guild.channel.sent[-1]
    i = FakeInteraction(bot2, guild, dave, guild.channel, message=welcome_d)
    await (await rebuilt(bg_mod.CustomItem, welcome_d, 2)).callback(i)
    modal = i.response.calls[-1][1]
    check(isinstance(modal, bg_mod.CustomAllianceModal) and modal.title == "Custom alliance", "modal opens")
    modal.tag._value = "[kvk]"
    i = FakeInteraction(bot2, guild, dave, guild.channel, message=welcome_d)
    await modal.on_submit(i)
    check(dave.display_name == "[KVK] Dave" and sent_text(i)[0] == "✅ Your nickname is now **[KVK] Dave**.",
          f"custom tag: {dave.display_name}")
    check(welcome_d.deleted and "Protocol agreement" in card_text(guild.channel.sent[-1]), "then rules")

    erin = guild.add(6, "Erin")
    erin.fail_nick = True
    await cog2.on_member_join(erin)
    welcome_e = guild.channel.sent[-1]
    modal = bg_mod.CustomAllianceModal(cog2)
    modal.tag._value = "abc"
    i = FakeInteraction(bot2, guild, erin, guild.channel, message=welcome_e)
    await modal.on_submit(i)
    check(sent_text(i)[0] == "⚠️ Noted **ABC**, but I couldn't change your nickname.\n-# A moderator has been told.",
          "nickname failure explained")

    # Commands: real prefix, consistent nickname rule, mod check
    ctx = Ctx(bot2, guild, admin)
    await cog2.removerole.callback(cog2, ctx, button_label="Nope")
    out = guild.channel.sent[-1].content
    check(out == "❓ There's no button called **Nope**.\n-# `!bg settings` lists them.", out)
    await cog2.forceclass.callback(cog2, ctx, alice, exact_label="Nope")
    out = guild.channel.sent[-1].content
    check(out.startswith("❓ There's no group called **Nope**.\n-# Options: ") and "`KVK`" in out
          and "[p]" not in out, out)
    await cog2.forceclass.callback(cog2, ctx, alice, exact_label="ABC")
    check(abc in alice.roles and kvk not in alice.roles and alice.display_name == "[ABC] Alice",
          f"forceclass swaps role and tag: {alice.display_name}")
    alice.display_name = "[XYZ] Alice"     # a tag that isn't a button label: still replaced
    await cog2.changerole.callback(cog2, Ctx(bot2, guild, alice), exact_label="KVK")
    check(kvk in alice.roles and abc not in alice.roles and alice.display_name == "[KVK] Alice",
          f"changerole strips and replaces: {alice.display_name}")
    check(guild.channel.sent[-1].content.startswith("✅"), "changerole confirmed")

    try:
        await bg_mod.has_mod_role(Ctx(bot2, guild, bob))
        refused = None
    except Exception as e:
        refused = e
    check(type(refused).__name__ == "UserFeedbackCheckFailure" and str(refused.message).startswith("🔒"),
          f"mod check explains itself: {refused!r}")
    check(await bg_mod.has_mod_role(Ctx(bot2, guild, admin)), "admins pass the mod check")

    await cog2.addrole.callback(cog2, ctx, guild.role(12, "Too high", position=60), button_label="HI")
    check(guild.channel.sent[-1].content.startswith("❌ I can't give"), "role above mine refused")
    await cog2.show_settings.callback(cog2, ctx)
    shown = guild.channel.sent[-1]
    check("### 👋 Welcome settings" in card_text(shown) and card_color(shown) == bg_mod.ui.BRAND, "settings card")
    check(card_text(shown).endswith("\n-# `!help bg` shows how to change these · Staff only")
          and "\n-# Every welcome also has **Custom alliance**" in card_text(shown), "settings footer: one hint")

    await bot2.remove_cog("ButtonGreeter")


pure_tests()
asyncio.run(flow_tests())
passed = sum(ok for ok, _ in results)
print(f"{passed}/{len(results)} checks passed")
