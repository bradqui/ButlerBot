"""
UI phase 2 (cards), part b: SpeakUp, ActivityStats, ButtonGreeter, Censord.

Each conversion's layout, the welcome ping (only the newcomer), no pings anywhere else, and old embed messages still
handled by the persistent buttons.
"""
import asyncio
import re
import time
import types
from types import SimpleNamespace

from harness import (FakeChannel, FakeGuild, FakeInteraction, FakeMember, FakeMessage, TestBot, card_color, card_text,
                     dcommands, discord, is_layout, load)

sp_mod = load("speakup", "speakup")
sp_mod.EMBED_WAIT = 0
gm_mod = load("gamemanager", "gamemanager")
stats_mod = load("activitystats", "activitystats")
bg_mod = load("buttongreeter", "buttongreeter")
cs_mod = load("censord", "censord")
ui = sp_mod.ui
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


# ---------------- helpers ----------------

def items(target):
    """Buttons in a card, in order: DynamicItems as themselves, plain buttons as buttons."""
    view = getattr(target, "view", target)
    return [i for i in view.walk_children() if isinstance(i, (discord.ui.Button, discord.ui.DynamicItem))]


def looks(target):
    out = []
    for i in items(target):
        b = getattr(i, "item", i)
        out.append((b.label, str(b.emoji) if b.emoji else None, b.style))
    return out


def count_components(view) -> int:
    """Every component Discord counts toward the 40 limit (nested ones and accessories included)."""
    def walk(data):
        n = 1
        for child in data.get("components", []):
            n += walk(child)
        if "accessory" in data:
            n += walk(data["accessory"])
        return n
    return sum(walk(c) for c in view.to_components())


def received(view):
    """The components a real Message would carry for this view (as Discord sends them back)."""
    return [discord.components._component_factory(d) for d in view.to_components()]


def no_pings(am) -> bool:
    return am is not None and am.everyone is False and am.users is False and am.roles is False


async def add_reaction(self, emoji):
    self.reactions_added = getattr(self, "reactions_added", []) + [emoji]
FakeMessage.add_reaction = add_reaction
FakeMessage.jump_url = "https://discord.com/channels/1/500/1"


async def _delete(self, **kw):
    self.deleted = True
    self.channel.messages.pop(self.id, None)
FakeMessage.delete = _delete
FakeMessage.deleted = False

STEAM = {
    1245620: {"name": "ELDEN RING", "free": False,
              "price": {"discount_percent": 40, "final_formatted": "$35.99", "initial_formatted": "$59.99"}},
    1145360: {"name": "Hades II", "free": False, "price": {"discount_percent": 0, "final_formatted": "$29.99"}},
    570: {"name": "Dota 2", "free": True, "price": None},
}


async def fake_details(appid):
    return STEAM.get(appid)
sp_mod.steam_details = fake_details


class ClaudeChat(dcommands.Cog):
    async def summarize_link(self, url, member):
        return "- a point"

    async def suggest_command(self, message, typed):
        return None


# ---------------- SpeakUp ----------------

async def speakup_tests():
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex = guild.add(2, "Alex")
    chris = guild.add(3, "Chris")
    mira = guild.add(4, "Mira")
    tor = guild.add(5, "*Tor*")      # markdown in a display name
    channel = guild.channel
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    await bot.add_cog(ClaudeChat())
    sp = sp_mod.SpeakUp(bot)
    await bot.add_cog(sp)
    sp.reminder_loop.cancel()

    def said(author, text):
        m = FakeMessage(channel, text, author=author)
        channel.messages[m.id] = m
        return m

    # ---- Steam card: the approved layout ----
    await gm.add_games(guild, brad, ["Hades II"], {"Hades II": 1145360})
    hades = next(g for g in (await gm.config.guild(guild).games()).values() if g["name"] == "Hades II")
    async with gm.config.guild(guild).users() as users:
        gm_mod.apply_change(gm_mod.user_entry(users, 4), hades["id"], "own")
        gm_mod.apply_change(gm_mod.user_entry(users, 5), hades["id"], "install")
    await sp.on_message_without_command(said(alex, "https://store.steampowered.com/app/1145360/Hades_II/"))
    card = channel.sent[-1]
    texts = [i for i in card.view.walk_children() if isinstance(i, discord.ui.TextDisplay)]
    check(is_layout(card.view) and not card.embeds and not card.content, "Steam link: a card, no embed or content")
    check(len(texts) == 1 and texts[0].content ==
          "**[Hades II](https://store.steampowered.com/app/1145360)**\n-# $29.99\n-# Owned by Mira and \\*Tor\\*",
          repr(card_text(card)))
    check(card_color(card) == ui.BRAND, "full price: blurple")
    check(looks(card) == [("I own it", None, discord.ButtonStyle.secondary),
                          ("Add to wishlist", None, discord.ButtonStyle.secondary),
                          (None, "🗑️", discord.ButtonStyle.secondary)], looks(card))
    container = card.view.children[0]
    check(len(card.view.children) == 1 and isinstance(container, discord.ui.Container)
          and any(isinstance(c, discord.ui.ActionRow) for c in container.children), "buttons inside the card")
    check([i.custom_id for i in items(card)] == ["sp:own:1145360", "sp:want:1145360", "sp:x:2"], "persistent ids")
    check(no_pings(card.kw.get("allowed_mentions")) and card.kw.get("mention_author") is False, "Steam card: no pings")
    check(not any(isinstance(i, (discord.ui.Thumbnail, discord.ui.MediaGallery)) for i in card.view.walk_children()),
          "no image (Discord's preview has one)")

    # on sale, not in the library, wanted
    await gm.add_wants(guild, chris, [("ELDEN RING", 1245620)])
    await sp.on_message_without_command(said(alex, "https://store.steampowered.com/app/1245620"))
    sale = channel.sent[-1]
    check(card_color(sale) == ui.HIGHLIGHT and card_text(sale) ==
          "**[ELDEN RING](https://store.steampowered.com/app/1245620)**\n-# 40% off, $35.99\n"
          "-# Wanted by 1 · not in the library", repr(card_text(sale)))
    # free, and a name with brackets
    STEAM[570]["name"] = "Dota [2]"
    await sp.on_message_without_command(said(alex, "https://store.steampowered.com/app/570"))
    check(card_text(channel.sent[-1]).startswith("**[Dota \\[2\\]](https://store.steampowered.com/app/570)**\n-# "
                                                 "Free to play"), card_text(channel.sent[-1]))
    check(sp_mod.name_list(["A", "b", "c", "d", "e", "f", "g"]) == "A, b, c, d, e and 2 more", "long name lists")

    # ---- clicks on a card: private answer, and the card is redrawn ----
    card.components = received(card.view)
    i = FakeInteraction(bot, guild, alex, channel, message=card)
    await sp.steam_button(i, "own", 1145360)
    check(i.followup.calls and i.followup.calls[-1][1].get("ephemeral") and "✅" in i.followup.calls[-1][0]
          and not i.followup.calls[-1][1].get("embed"), f"own: private text line {i.followup.calls}")
    edit = card.edits[-1] if card.edits else {}
    check(is_layout(edit.get("view")) and "Owned by Alex, Mira and \\*Tor\\*" in card_text(edit["view"])
          and no_pings(edit.get("allowed_mentions")), f"card redrawn: {card_text(card)!r}")
    check([x.custom_id for x in items(edit["view"])][-1] == "sp:x:2", "redraw keeps the Remove button's owner")
    i = FakeInteraction(bot, guild, chris, channel, message=card)
    await sp.steam_button(i, "want", 1145360)
    check("wanted by 1" in card_text(card), card_text(card))

    # ---- an old embed Steam card (before cards): the buttons still work, the message isn't touched ----
    old = FakeMessage(channel, None, author=guild.me, embed=discord.Embed(title="Hades II"))
    old_edits = len(old.edits)
    sp._steam_info.clear()
    sp._steam_names.clear()                 # as after a restart
    button = await sp_mod.SteamButton.from_custom_id(None, None, {"action": "own", "appid": "1145360"})
    i = FakeInteraction(bot, guild, chris, channel, message=old)
    await button.callback(i)
    check(not ui.is_card(old) and len(old.edits) == old_edits and i.followup.calls
          and i.followup.calls[-1][1].get("ephemeral"), "old embed card: answered privately, not edited")

    # ---- GameManager answering with text or a card (after its own conversion) still reads right ----
    async def as_text(*a, **k):
        return ("✅ **Owned:** Hades II", [])
    gm.change_library = gm.change_library_text = as_text   # whichever SpeakUp uses
    i = FakeInteraction(bot, guild, mira, channel, message=card)
    await sp.steam_button(i, "own", 1145360)
    check(i.followup.calls[-1][0] == "✅ **Owned:** Hades II", i.followup.calls[-1])

    async def as_card(*a, **k):
        return (ui.CardView(ui.card("✅ **Owned:** Hades II", title="🎮 Library")), [])
    gm.change_library = gm.change_library_text = as_card
    i = FakeInteraction(bot, guild, mira, channel, message=card)
    await sp.steam_button(i, "own", 1145360)
    check("✅ **Owned:** Hades II" in i.followup.calls[-1][0], i.followup.calls[-1])
    del gm.change_library, gm.change_library_text
    check(hasattr(gm, "change_library_text"), "GameManager has the text helper SpeakUp prefers")

    # ---- the time answer: a compact card with both buttons inside ----
    await gm.config.user(alex).timezone.set("America/Chicago")
    m = said(alex, "anyone want to play at 9?")
    await sp.on_message_without_command(m)
    await sp.on_raw_reaction_add(SimpleNamespace(message_id=m.id, user_id=3, emoji="🕘", guild_id=guild.id,
                                                 channel_id=channel.id, member=chris))
    answer = channel.sent[-1]
    text = card_text(answer)
    check(is_layout(answer.view) and text.startswith("🕘 **at 9** is <t:") and "(<t:" in text
          and "\n-# Discord shows that in your own timezone. Read in America/Chicago (Alex's timezone)." in text
          and "###" not in text, repr(text))
    check(card_color(answer) == ui.BRAND, "time card: blurple")
    check(looks(answer) == [("Schedule a session", "🎮", discord.ButtonStyle.primary),
                            (None, "🗑️", discord.ButtonStyle.secondary)], looks(answer))
    check(no_pings(answer.kw.get("allowed_mentions")), "time card: no pings")
    ts = int(re.search(r"<t:(\d+):F>", text).group(1))
    sched = await sp_mod.ScheduleButton.from_custom_id(None, None, {"ts": str(ts)})
    for target in (answer, FakeMessage(channel, "🕘 **at 9** is …", author=guild.me)):   # card, and an old text one
        i = FakeInteraction(bot, guild, chris, channel, message=target)
        await sched.callback(i)
        check(i.response.calls and i.response.calls[-1][0] == "modal", "Schedule a session opens the form")

    # ---- Remove on a card: private confirm, then deleted for everyone ----
    remove = await sp_mod.RemoveButton.from_custom_id(None, None, {"uid": "3"})
    i = FakeInteraction(bot, guild, chris, channel, message=answer)
    await remove.callback(i)
    view = i.response.calls[-1][2]["view"]
    check(i.response.calls[-1][2].get("ephemeral"), "remove asks privately")
    yes = next(c for c in view.children if c.label == "Remove for everyone")
    await yes.callback(FakeInteraction(bot, guild, chris, channel, message=FakeMessage(channel, "?")))
    check(answer.deleted, "card removed")

    # ---- settings card ----
    ctx = await bot.get_context(FakeMessage(channel, "!speakup", author=alex))
    await bot.invoke(ctx)
    shown = channel.sent[-1]
    text = card_text(shown)
    check(text.startswith("### 🗣️ SpeakUp settings\n**Clock reaction on times in chat** · On"), repr(text))
    check("**This channel** · On" in text and "**Your messages** · On" in text, "channel and person rows")
    check(any(isinstance(c, discord.ui.Separator) for c in shown.view.walk_children())
          and "\n-# Change with `!speakup me off`" in text and "[p]" not in text and card_color(shown) == ui.BRAND,
          "separator, footer with the real prefix")
    check(no_pings(shown.kw.get("allowed_mentions")), "settings: no pings")

    # ---- reminders list: a small card; mentions in reminder text don't ping ----
    ctx = await bot.get_context(FakeMessage(channel, "!remindme 2h tell <@3> and @everyone hi", author=alex))
    await bot.invoke(ctx)
    ctx = await bot.get_context(FakeMessage(channel, "!reminders", author=alex))
    await bot.invoke(ctx)
    shown = channel.sent[-1]
    text = card_text(shown)
    check(text.startswith("### ⏰ Your reminders\n**tell <@3> and @everyone hi**\n-# <t:") and " · ID `" in text
          and text.endswith("-# `!reminders cancel <id>` cancels one"), repr(text))
    check(no_pings(shown.kw.get("allowed_mentions")), "reminders card: no pings")

    # ---- plain text stays plain text ----
    async with sp.config.reminders() as rem:
        for r in rem.values():
            r["due"] = time.time() - 1
    await sp.reminder_loop.coro(sp)
    delivered = channel.sent[-1]
    am = delivered.kw.get("allowed_mentions")
    check(delivered.content.startswith("⏰ <@2>, you asked me to remind you") and not is_layout(delivered.view)
          and [u.id for u in am.users] == [2], "reminder delivery: text that pings only its owner")
    link = said(alex, "read https://example.com/article")
    await sp.on_message_without_command(link)
    await sp.on_raw_reaction_add(SimpleNamespace(message_id=link.id, user_id=3, emoji="📄", guild_id=guild.id,
                                                 channel_id=channel.id, member=chris))
    summary = channel.sent[-1]
    check("**Summary**" in summary.content and not is_layout(summary.view), "link summary: plain text")
    ctx = await bot.get_context(FakeMessage(channel, "!gmaes list", author=alex))
    try:
        await bot.invoke(ctx)
    except dcommands.CommandNotFound as e:
        await sp.on_command_error(ctx, e)
    await asyncio.sleep(0.05)
    check("Did you mean" in channel.sent[-1].content and not is_layout(channel.sent[-1].view),
          "mistake suggestion: plain text")

    for name in ("SpeakUp", "ClaudeChat", "GameManager"):
        await bot.remove_cog(name)


# ---------------- ActivityStats ----------------

async def stats_tests():
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    general = guild.channel
    general.last_message_id = None
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    st = stats_mod.ActivityStats(bot)
    await bot.add_cog(st)
    await st.config.guild(guild).started_at.set(int(time.time() - 86400 * 10))
    await st.config.guild(guild).excluded_channels.set([general.id, 4242])
    ctx = await bot.get_context(FakeMessage(general, "!stats admin", author=brad))
    await st.stats_admin.callback(st, ctx)
    menu = general.sent[-1]
    text = card_text(menu)
    check(is_layout(menu.view) and text.startswith("### 📊 Admin stats\n`!stats admin active [period]`")
          and text.endswith("-# Staff only") and card_color(menu) == ui.BRAND, repr(text[-80:]))
    check(no_pings(menu.kw.get("allowed_mentions")), "admin menu: no pings")
    await st.admin_settings.callback(st, ctx)
    shown = general.sent[-1]
    text = card_text(shown)
    check(text.startswith("### 📊 Stats settings\n**Tracking since** · <t:") and "**Game tracking** · On" in text
          and f"**Excluded channels** · <#{general.id}>, #deleted-channel" in text
          and "**Weekly digest** · Off · not set · Mon 9 AM (UTC)" in text, repr(text))
    check(text.endswith("-# Staff only") and "`!stats admin exclude|include #channel`" in text
          and any(isinstance(c, discord.ui.Separator) for c in shown.view.walk_children())
          and no_pings(shown.kw.get("allowed_mentions")), "settings: separator, change commands, staff hint")
    await bot.remove_cog("ActivityStats")


# ---------------- ButtonGreeter ----------------

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
        self.display_avatar = types.SimpleNamespace(url=f"https://cdn.example.invalid/{uid}.png")

    async def add_roles(self, *roles, **kw):
        self.roles += [r for r in roles if r not in self.roles]

    async def remove_roles(self, *roles, **kw):
        self.roles = [r for r in self.roles if r not in roles]

    async def edit(self, nick=None, **kw):
        self.display_name = nick


class Guild(FakeGuild):
    def __init__(self):
        super().__init__()
        self.name = "The *Keep*"
        self.role_map = {}
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


async def greeter_tests():
    guild = Guild()
    admin = guild.add(1, "Brad", admin=True)
    alice = guild.add(2, "Alice")
    bot = TestBot(guild)
    cog = bg_mod.ButtonGreeter(bot)
    await bot.add_cog(cog)
    conf = cog.config.guild(guild)
    roles = {f"T{n}": 100 + n for n in range(18)}
    for label, rid in roles.items():
        guild.role(rid, f"Team {label}")
    guild.role(20, "Agreed")
    await conf.welcome_channel.set(guild.channel.id)
    await conf.rules_channel.set(700)
    await conf.rules_role.set(20)
    await conf.roles.set(roles)

    # ---- welcome card: avatar, title, mention, 18 + 2 buttons inside, one ping ----
    await cog.on_member_join(alice)
    welcome = guild.channel.sent[-1]
    view = welcome.view
    section = next((c for c in view.walk_children() if isinstance(c, discord.ui.Section)), None)
    check(is_layout(view) and not welcome.content and not welcome.embeds, "welcome: a card")
    check(section is not None and section.accessory.media.url == "https://cdn.example.invalid/2.png",
          "welcome: the member's avatar as thumbnail")
    text = card_text(welcome)
    check(text.startswith("### 👋 Welcome to The \\*Keep\\*\n<@2>, select your identity below to proceed.\n"
                          "-# Your alliance's tag goes in front of your nickname."), repr(text))
    check(card_color(welcome) == ui.BRAND, "welcome: blurple")
    rows = [r for r in view.walk_children() if isinstance(r, discord.ui.ActionRow)]
    check([len(r.children) for r in rows] == [5, 5, 5, 3, 2], [len(r.children) for r in rows])
    check([getattr(i, "custom_id", None) for i in rows[-1].children] == ["bg:custom:2", "bg:none:2"],
          "built-in buttons on their own row")
    check(all(not getattr(i.item, "emoji", None) for r in rows[:-1] for i in r.children)
          and all(i.item.emoji for i in rows[-1].children), "emoji all-or-none per row")
    check(count_components(view) <= 40, f"{count_components(view)} components (limit 40)")
    am = welcome.kw.get("allowed_mentions")
    check(am is not None and am.users == [alice] and am.everyone is False and am.roles is False,
          "welcome pings only the newcomer")

    # ---- a role click on the card: the welcome goes, the rules card comes (no ping) ----
    first = items(welcome)[0]
    i = FakeInteraction(bot, guild, alice, guild.channel, message=welcome)
    await first.callback(i)
    rules = guild.channel.sent[-1]
    check(welcome.deleted and is_layout(rules.view), "welcome replaced by the rules card")
    text = card_text(rules)
    check(text == "### 👋 Protocol agreement\n<@2>, do you agree to the rules in <#700>?\n"
                  "-# Identity accepted. Agreeing finishes your welcome.", repr(text))
    check(card_color(rules) == ui.ATTENTION and no_pings(rules.kw.get("allowed_mentions")),
          "rules card: needs action, no ping")
    check(looks(rules) == [("Yes, I agree", None, discord.ButtonStyle.primary),
                           ("No", None, discord.ButtonStyle.secondary)], looks(rules))
    yes = items(rules)[0]
    i = FakeInteraction(bot, guild, alice, guild.channel, message=rules)
    await yes.callback(i)
    check(rules.deleted and guild.get_role(20) in alice.roles, "agreeing on the card")

    # ---- old embed messages (posted before cards) still work with the persistent buttons ----
    bob = guild.add(3, "Bob")
    old_welcome = await guild.channel.send(bob.mention, embed=discord.Embed(title="Welcome to The Keep"))
    none_btn = await bg_mod.NoneItem.from_custom_id(None, None, {"uid": "3"})
    i = FakeInteraction(bot, guild, bob, guild.channel, message=old_welcome)
    await none_btn.callback(i)
    new_rules = guild.channel.sent[-1]
    check(old_welcome.deleted and is_layout(new_rules.view), "old embed welcome: deleted, rules card posted")
    old_rules = await guild.channel.send(bob.mention, embed=discord.Embed(title="Protocol Agreement"))
    no = await bg_mod.RulesItem.from_custom_id(None, None, {"answer": "no", "uid": "3"})
    i = FakeInteraction(bot, guild, bob, guild.channel, message=old_rules)
    await no.callback(i)
    check(not old_rules.deleted and i.response.calls[-1][1].startswith("⚠️"), "old embed rules prompt: No keeps it")
    yes = await bg_mod.RulesItem.from_custom_id(None, None, {"answer": "yes", "uid": "3"})
    i = FakeInteraction(bot, guild, bob, guild.channel, message=old_rules)
    await yes.callback(i)
    check(old_rules.deleted and guild.get_role(20) in bob.roles, "old embed rules prompt: Yes works")

    # ---- settings card ----
    await conf.mod_roles.set([100])

    class Ctx:
        def __init__(self):
            self.bot, self.guild, self.author, self.channel = bot, guild, admin, guild.channel
            self.message = FakeMessage(guild.channel, "", author=admin)

        async def send(self, content=None, **kw):
            return await self.channel.send(content, **kw)

    await cog.show_settings.callback(cog, Ctx())
    shown = guild.channel.sent[-1]
    text = card_text(shown)
    check(text.startswith("### 👋 Welcome settings\n**Channels**\n**Welcome** · <#500>\n**Rules** · <#700>\n"
                          "**Error reports** · not set"), repr(text[:160]))
    check("**Rules role** · <@&20>" in text and "**Mod roles** · <@&100>" in text
          and "**[T0]** · gives <@&100>" in text and "**Custom alliance**" in text, "roles and buttons listed")
    check(text.endswith("\n-# `!help bg` shows how to change these · Staff only") and "[p]" not in text
          and card_color(shown) == ui.BRAND, "footer: one hint, staff hint")
    check(no_pings(shown.kw.get("allowed_mentions")), "settings: role mentions don't ping")
    await bot.remove_cog("ButtonGreeter")


# ---------------- Censord ----------------

async def censord_tests():
    guild = FakeGuild()
    admin = guild.add(1, "Brad", admin=True)
    channel = guild.channel
    memes = FakeChannel(guild, 501)
    memes.name = "memes"
    guild.text_channels.append(memes)
    bot = TestBot(guild)
    cog = cs_mod.Censord(bot)
    await bot.add_cog(cog)
    conf = cog.config.guild(guild)
    await conf.global_level.set("low")
    await conf.strategy.set("exclude")
    await conf.excluded_channels.set([501, 9999])
    await cog.config.channel(memes).override_level.set("off")
    await cog.config.channel(channel).override_action.set("kick")
    ctx = await bot.get_context(FakeMessage(channel, "!censor config", author=admin))
    await bot.invoke(ctx)
    shown = channel.sent[-1]
    text = card_text(shown)
    check(is_layout(shown.view) and text.startswith("### 🛡️ Word filter settings\n**Server level** · Low\n"
                                                    "**Action** · Delete\n**Threshold** · 3 messages in 60 seconds"),
          repr(text[:200]))
    check("**Admin role** · none (Manage Server only)" in text, "admin role row")
    check("**Exceptions** · <#501>, 1 deleted channel" in text and "**Include list** · none" in text,
          "channel lists show names, not just counts")
    check("**Channel overrides**\n<#500>\n-# Action kick\n<#501>\n-# Level off" in text, "per-channel overrides shown")
    blocks = [c.content for c in shown.view.walk_children() if isinstance(c, discord.ui.TextDisplay)]
    check("<#500>\n-# Action kick" in blocks and "<#501>\n-# Level off" in blocks, "each override is its own block")
    check(text.endswith("\n-# `!help censor` shows how to change these · Staff only") and card_color(shown) == ui.BRAND,
          "footer and color")
    check(no_pings(shown.kw.get("allowed_mentions")), "censor config: no pings")
    await bot.remove_cog("Censord")


async def main():
    await speakup_tests()
    await stats_tests()
    await greeter_tests()
    await censord_tests()


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
