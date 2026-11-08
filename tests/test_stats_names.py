"""ActivityStats: channels that share a name (a text and a voice channel) can be told apart."""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from harness import (FakeChannel, FakeGuild, FakeInteraction, FakeMessage, TestBot, card_buttons, card_text,
                     discord, load)


class FakeVoice(FakeChannel):
    pass


discord.VoiceChannel = FakeVoice   # so the cog's isinstance checks see the fake voice channel as voice
stats_mod = load("activitystats", "activitystats")
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


async def until(cond, tries=200):
    for _ in range(tries):
        if cond():
            return True
        await asyncio.sleep(0.01)
    return False


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex = guild.add(2, "Alex")
    for m in guild.members:
        m.joined_at = datetime.now(timezone.utc) - timedelta(days=200)
    general = guild.channel
    founders = FakeChannel(guild, 501)
    founders.name, founders.position, founders.category = "founders", 1, None
    vfounders = FakeVoice(guild, 601)
    vfounders.name, vfounders.position, vfounders.category, vfounders.members = "founders", 0, None, [alex]
    lounge = FakeVoice(guild, 602)
    lounge.name, lounge.position, lounge.category, lounge.members = "Lounge", 1, None, []
    guild.text_channels.append(founders)
    guild.voice_channels += [vfounders, lounge]
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    st = stats_mod.ActivityStats(bot)
    await bot.add_cog(st)
    await st.config.guild(guild).started_at.set(int(time.time() - 100 * 86400))
    conv = stats_mod.ChannelArg()
    ctx = await bot.get_context(FakeMessage(general, "!x", author=brad))

    # --- the converter ---
    check(await conv.convert(ctx, "Lounge") is lounge, "a unique name resolves straight away")
    check(await conv.convert(ctx, "lounge") is lounge, "names match without case when nothing matches exactly")
    check(await conv.convert(ctx, "<#601>") is vfounders, "a mention picks the voice channel")
    lounge.id = 123456789012345678
    check(await conv.convert(ctx, "123456789012345678") is lounge, "so does an ID")
    lounge.id = 602
    shared = await conv.convert(ctx, "#founders")
    check(isinstance(shared, stats_mod.SharedName) and set(shared.channels) == {founders, vfounders},
          "a shared name (with or without #) gives both channels")
    try:
        await conv.convert(ctx, "nowhere")
        check(False, "an unknown name is refused")
    except stats_mod.commands.BadArgument as e:
        check("couldn't find a channel" in str(e), "an unknown name is refused with a ❓ line")

    # --- exclude asks which one, then excludes the voice channel ---
    st._voice_open[(guild.id, alex.id)] = (601, time.time() - 600)
    await st.db.query("INSERT INTO voice VALUES (?, ?, ?, ?, ?)", (guild.id, 601, alex.id, 1.0, 500.0))
    await st.db.query("INSERT INTO messages VALUES (?, ?, ?, ?, ?)", (guild.id, 501, alex.id, 3600, 4))
    before = len(general.sent)
    task = asyncio.create_task(bot.invoke(await bot.get_context(
        FakeMessage(general, "!stats admin exclude founders", author=brad))))
    check(await until(lambda: len(general.sent) > before), "the picker is posted")
    picker = general.sent[before]
    check("More than one channel is called **founders**" in card_text(picker), "the picker names the channel")
    buttons = card_buttons(picker)
    check([b.label for b in buttons] == ["founders", "founders"], "one button per channel")
    check([str(b.emoji) for b in buttons] == ["🔊", "💬"], "icons tell voice from text (voice first by position)")
    other = FakeInteraction(bot, guild, alex, general, picker)
    await picker.view.interaction_check(other)
    check(other._resp.calls and other._resp.calls[0][2].get("ephemeral"), "someone else can't choose")
    await buttons[0].callback(FakeInteraction(bot, guild, brad, general, picker))
    await asyncio.wait_for(task, 2)
    check(601 in await st.config.guild(guild).excluded_channels(), "the voice channel is excluded")
    check(501 not in await st.config.guild(guild).excluded_channels(), "the text channel isn't")
    check(getattr(picker, "deleted", False) or picker in getattr(general, "deleted", []), "the picker is removed")
    check("<#601>" in (general.sent[-1].content or ""), "the reply names the voice channel")
    check((guild.id, alex.id) not in st._voice_open, "a visit in progress isn't recorded after excluding")
    check(not await st.db.query("SELECT * FROM voice WHERE channel = 601"), "its voice time is deleted")
    check(await st.db.query("SELECT * FROM messages WHERE channel = 501"), "the text channel's counts stay")

    # --- include starts tracking people already in the channel ---
    await bot.invoke(await bot.get_context(FakeMessage(general, "!stats admin include <#601>", author=brad)))
    check(601 not in await st.config.guild(guild).excluded_channels(), "include by mention needs no picker")
    check(st._voice_open.get((guild.id, alex.id), (None,))[0] == 601, "people already there are tracked again")

    # --- the picker times out quietly ---
    view = stats_mod.ChannelPicker(brad.id, shared)
    view.message = await general.send(view=view)
    await view.on_timeout()
    check("Expired. Nothing was changed." in card_text(view.message.view or view), "an unused picker expires")

    # --- member commands use the same picker ---
    before = len(general.sent)
    task = asyncio.create_task(bot.invoke(await bot.get_context(
        FakeMessage(general, "!stats channel founders", author=alex))))
    check(await until(lambda: len(general.sent) > before), "stats channel asks too")
    await card_buttons(general.sent[before])[1].callback(FakeInteraction(bot, guild, alex, general,
                                                                         general.sent[before]))
    await asyncio.wait_for(task, 5)
    check(len(general.sent) > before + 1, "and then sends the report")

    # --- more than five channels with one name: a select menu instead of buttons ---
    many = []
    for n in range(7):
        c = FakeChannel(guild, 900 + n)
        c.name, c.position, c.category = "lobby", n, None
        many.append(c)
    view = stats_mod.ChannelPicker(alex.id, stats_mod.SharedName("lobby", many))
    selects = [i for i in view.walk_children() if isinstance(i, discord.ui.Select)]
    check(not card_buttons(view) and len(selects) == 1 and len(selects[0].options) == 7,
          "seven same-named channels: one select menu, no buttons")
    view.message = await general.send(view=view)
    i = FakeInteraction(bot, guild, alex, general, view.message)
    selects[0]._values = ["3"]
    try:
        selects[0].values = ["3"]
    except AttributeError:
        pass
    await selects[0].callback(i)
    check(view.chosen is many[3] and view.is_finished(), "picking from the menu chooses that channel")

    passed = sum(ok for ok, _ in results)
    print(f"{passed}/{len(results)} passed")


asyncio.run(main())
