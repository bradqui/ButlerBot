"""GameManager phase 1 style: status symbols, expiring menus, installed marks, real prefixes, button colors."""
import asyncio

from harness import FakeGuild, FakeInteraction, FakeMessage, TestBot, card_buttons, card_color, card_text, discord, load

from gmcards import card_buttons  # noqa: E402  (unwraps DynamicItem buttons)
gm_mod = load("gamemanager", "gamemanager")
FakeMessage._state = None
results = []
SYMBOLS = ("✅", "❌", "⚠️", "⏳", "🔒", "❓")


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


class Ctx:
    def __init__(self, guild, author):
        self.guild, self.author, self.channel = guild, author, guild.channel
        self.clean_prefix = "!"

    async def send(self, content=None, **kw):
        return await self.channel.send(content, **kw)


def buttons(view):
    if hasattr(view, "walk_children"):
        return card_buttons(view)
    return [getattr(c, "item", c) for c in view.children if isinstance(getattr(c, "item", c), discord.ui.Button)]


async def main():
    guild = FakeGuild()
    brad, alex = guild.add(1, "Brad"), guild.add(2, "Alex")
    bot = TestBot(guild)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    channel = guild.channel

    async def run(author, content):
        msg = FakeMessage(channel, content, author=author)
        ctx = await bot.get_context(msg)
        before = len(channel.sent)
        await bot.invoke(ctx)
        return channel.sent[-1] if len(channel.sent) > before else None

    # Lines that used to have no symbol
    out = await run(alex, "!games requests")
    check(out.content == "❓ No pending requests.", out.content)
    out = await run(alex, "!games endsession")
    check(out.content == "❓ No matching session found.", out.content)
    out = await run(alex, "!games endvote")
    check(out.content == "❓ There's no running vote.", out.content)
    out = await run(alex, "!games list")
    check(out.content.startswith("⚠️ No games have been added yet") and "`!games request <game>`" in out.content,
          out.content)
    await gm.send_list(Ctx(guild, alex), [], "Nothing")
    check(channel.sent[-1].content == "❓ Nothing to show.", "empty list")
    await gm.library_command(Ctx(guild, alex), " , ", "own")
    check(channel.sent[-1].content == "❓ Name at least one game.", channel.sent[-1].content)

    # Session refusals: 🔒 everywhere
    await gm.add_games(guild, brad, ["Rocket League", "Valorant"])
    await run(brad, "!games session Test night")
    out = await run(alex, "!games endsession " + next(iter(await gm.config.guild(guild).play_sessions())))
    check(out.content == "🔒 Only the host or a game admin can end that session.", out.content)
    sid = next(iter(await gm.config.guild(guild).play_sessions()))
    smsg = channel.sent[-2] if channel.sent[-1] is out else channel.sent[-1]
    i = FakeInteraction(bot, guild, alex, channel, message=smsg)
    await gm.on_session_button(i, "end", sid)
    check(i.response.calls[0][1] == "🔒 Only the host or a game admin can do that.", i.response.calls[0][1])
    view = gm_mod.session_view(sid)
    styles = [b.style for b in buttons(view)]
    check(styles.count(discord.ButtonStyle.primary) == 1 and discord.ButtonStyle.danger not in styles
          and discord.ButtonStyle.success not in styles, f"session buttons: {styles}")
    check(all(b.emoji for b in buttons(view)), "emoji on every session button")
    req = [b.style for b in buttons(gm_mod.request_view("abc"))]
    check(req == [discord.ButtonStyle.primary, discord.ButtonStyle.secondary], f"request buttons {req}")

    # Installed games are marked 💾, not ✅
    await gm.change_library(guild, alex, ["Rocket League"], "install")
    await gm.change_library(guild, alex, ["Valorant"], "own")
    await gm.show_library(Ctx(guild, alex), alex)
    lib = card_text(channel.sent[-1])
    check("**Rocket League** 💾" in lib and "✅" not in lib and "💾 = installed" in lib, lib)
    text, _ = await gm.change_library_text(guild, alex, ["Rocket League"], "own")
    check(text.startswith("⚠️ **Already in your library:**"), text)
    embed, _ = await gm.change_library(guild, alex, ["Rocket League"], "own")   # the embed form other cogs use
    check(embed.description == text and embed.color == gm_mod.ui.MUTED, embed.description)

    # Expiring menus grey out and say what happened
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.open_picker(Ctx(guild, alex), "owned")
    picker_msg = channel.sent[-1]
    picker = picker_msg.kw["view"]
    save = next(b for b in buttons(picker) if b.label == "Save")
    check(save.style == discord.ButtonStyle.primary and not save.emoji, "Save is the one blurple button")
    await picker.on_timeout()
    last = picker_msg.edits[-1]
    check(all(c.disabled for c in buttons(last["view"])) and card_text(picker_msg).endswith("-# Expired. Nothing was saved."),
          f"picker expiry: {card_text(picker_msg)[-60:]!r}")
    confirm = gm_mod.ConfirmView(brad.id, "⚠️ Remove **X**?", label="Remove")
    confirm.message = await channel.send(view=confirm)
    await confirm.on_timeout()
    check(card_text(confirm.message) == "⚠️ Remove **X**?\n-# Expired. Nothing happened.", card_text(confirm.message))
    check([b.style for b in buttons(confirm)] == [discord.ButtonStyle.danger, discord.ButtonStyle.secondary],
          "confirm: red only for the destructive confirm")
    names = gm_mod.NameCheckView(brad.id, plural=False, text="I checked that name")
    styles = {b.label: b.style for b in buttons(names)}
    check(styles["Cancel"] == discord.ButtonStyle.secondary
          and styles["Use suggestion"] == discord.ButtonStyle.primary and "Keep my spelling" in styles
          and all(len(label.split()) <= 3 for label in styles), f"name check buttons {styles}")
    names.message = await channel.send(view=names)
    await names.on_timeout()
    check(card_text(names.message).endswith("-# Expired. Nothing was added or requested."), card_text(names.message))
    i = FakeInteraction(bot, guild, brad, channel, message=picker_msg)
    check(not await picker.interaction_check(i) and i.response.calls[0][1].startswith("🔒"), "not your menu: 🔒")

    # Sale alert footer uses the real prefix
    async def fake_prices(appids):
        return {a: {"final": 100, "initial": 200, "discount": 50, "final_text": "$1", "initial_text": "$2"}
                for a in appids}
    gm_mod.steam_prices = fake_prices
    await gm.config.guild(guild).sale_channel.set(channel.id)
    await gm.config.guild(guild).wishlist.set({"1": {"appid": 1, "name": "Thing", "users": ["2"], "price": None,
                                                     "checked_at": None, "alerted": 0}})
    await gm.check_sales(guild)
    alert = channel.sent[-1]
    check(card_text(alert).endswith("-# From your wishlists · !games want / !games unwant")
          and card_color(alert) == gm_mod.ui.HIGHLIGHT, card_text(alert))

    # Every status line the vote path sends has a symbol
    i = FakeInteraction(bot, guild, alex, channel)
    await gm.on_vote_button(i, "nope", "nope")
    check(i.response.calls[0][1].startswith(SYMBOLS), i.response.calls[0][1])

    await bot.remove_cog("GameManager")


asyncio.run(main())
passed = sum(ok for ok, _ in results)
print(f"{passed}/{len(results)} checks passed")
