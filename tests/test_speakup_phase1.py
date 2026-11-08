"""SpeakUp, style phase 1: no pings, safe long summaries with retry, expiring menus, 📄 cooldown, card colors."""
import asyncio
import time
from types import SimpleNamespace

from harness import FakeChannel, FakeGuild, FakeInteraction, FakeMessage, TestBot, card_color, dcommands, discord, load

sp_mod = load("speakup", "speakup")
sp_mod.EMBED_WAIT = 0
gm_mod = load("gamemanager", "gamemanager")
FakeMessage._state = None
ui = sp_mod.ui
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


async def add_reaction(self, emoji):
    self.reactions_added = getattr(self, "reactions_added", []) + [emoji]
FakeMessage.add_reaction = add_reaction
FakeMessage.jump_url = "https://discord.com/channels/1/500/1"


class ClaudeChat(dcommands.Cog):
    def __init__(self):
        self.summary = "- short"

    async def summarize_link(self, url, member):
        return self.summary

    async def suggest_command(self, message, typed):
        return None


def label_of(c):
    return getattr(c, "label", None) or getattr(getattr(c, "item", None), "label", None)


def http_error():
    return discord.HTTPException(SimpleNamespace(status=400, reason="Bad Request"), "Must be 2000 or fewer")


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)
    alex = guild.add(2, "Alex")
    chris = guild.add(3, "Chris")
    channel = guild.channel
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    claude = ClaudeChat()
    await bot.add_cog(claude)
    sp = sp_mod.SpeakUp(bot)
    await bot.add_cog(sp)
    sp.reminder_loop.cancel()

    def said(author, text, where=channel):
        m = FakeMessage(where, text, author=author)
        where.messages[m.id] = m
        return m

    def click(m, member, emoji="📄"):
        return sp.on_raw_reaction_add(SimpleNamespace(message_id=m.id, user_id=member.id, emoji=emoji,
                                                      guild_id=guild.id, channel_id=channel.id, member=member))

    # ---- 📄 goes on every link message: no cooldown ----
    m1 = said(alex, "read https://example.com/one")
    await sp.on_message_without_command(m1)
    m2 = said(chris, "and https://example.com/two")
    await sp.on_message_without_command(m2)
    other = FakeChannel(guild, 777)
    m3 = said(chris, "elsewhere https://example.com/three", other)
    await sp.on_message_without_command(m3)
    check(getattr(m1, "reactions_added", []) == ["📄"] and getattr(m2, "reactions_added", []) == ["📄"]
          and getattr(m3, "reactions_added", []) == ["📄"], "📄 on every link message")

    # ---- the rate-limit notice doesn't ping the clicker ----
    sp._summaries[chris.id] = [time.time()] * sp_mod.SUMMARIES_PER_HOUR
    await click(m1, chris)
    note = channel.sent[-1]
    am = note.kw.get("allowed_mentions")
    check(note.content.startswith("⏳ ") and am is not None and am.users is False and am.everyone is False,
          f"rate limit: no ping ({note.content!r}, {am})")
    check(not sp._tracked[m1.id]["done"], "still clickable by someone else")
    sp._summaries.clear()

    # ---- a long summary fits one message; a failed post can be retried ----
    claude.summary = ("- " + "word " * 80 + "\n") * 12   # ~5,000 characters
    real_send = channel.send
    fails = [True]

    async def flaky_send(content=None, **kw):
        if fails and content and "**Summary**" in content:
            fails.pop()
            raise http_error()
        return await real_send(content, **kw)
    channel.send = flaky_send
    before = len(channel.sent)
    await click(m1, alex)
    check(len(channel.sent) == before and not sp._tracked[m1.id]["done"], "post failed: offer open again")
    await click(m1, alex)
    reply = channel.sent[-1]
    check(len(reply.content) <= 2000 and reply.content.startswith("📄 **Summary** of <https://example.com/one>")
          and reply.content.endswith("-# Asked by <@2>") and "…" in reply.content,
          f"long summary shortened to fit ({len(reply.content)} chars)")
    check(sp._tracked[m1.id]["done"], "answered on the retry")
    channel.send = real_send
    text = sp_mod.summary_text("https://example.com/" + "x" * 900, "y " * 2000, "Asked by someone")
    check(len(text) <= 2000 and "<https://" not in text, "very long URL left out of the header")

    # menu: long summaries are shortened too
    i = FakeInteraction(bot, guild, alex, channel)
    msg = said(alex, "https://example.com/menu")
    msg.embeds = [SimpleNamespace(type="article", url="https://example.com/menu")]
    await sp.summarize_from_menu(i, msg)
    content, kw = i.followup.calls[-1]
    check(len(content) <= 2000 and kw.get("ephemeral"), "menu summary fits")

    # ---- Remove's private confirmation expires visibly ----
    target = channel.sent[-1]
    i = FakeInteraction(bot, guild, alex, channel, message=target)
    remove = sp_mod.RemoveButton(2)
    await remove.callback(i)
    view = i.response.calls[-1][2]["view"]
    check(view.message is i, "confirm view knows its message")
    await view.on_timeout()
    edit = i.sent_message.edits[-1]
    check(all(c.disabled for c in edit["view"].children) and "-# Expired." in edit["content"],
          f"confirm view greys out and says Expired: {edit.get('content')!r}")
    styles = {c.label: (c.style, c.emoji) for c in view.children}
    check(styles["Remove for everyone"] == (discord.ButtonStyle.danger, None)
          and styles["Keep it"] == (discord.ButtonStyle.secondary, None), f"confirm buttons: {styles}")
    i = FakeInteraction(bot, guild, chris, channel, message=target)
    await remove.callback(i)
    check(i.response.calls[-1][1].startswith("🔒 Only <@2>"), "not yours: 🔒")

    # ---- Run it expires; Remove keeps working ----
    ctx = await bot.get_context(FakeMessage(channel, "!games owns Barony", author=alex))
    await bot.invoke(ctx)
    await asyncio.sleep(0.05)
    reply = channel.sent[-1]
    view = reply.kw["view"]
    run = next(c for c in view.children if label_of(c) == "Run it")
    check(run.style == discord.ButtonStyle.primary, "Run it is the main action")
    await view.on_timeout()
    edited = reply.edits[-1]["view"]
    items = {label_of(c): c for c in edited.children}
    remove_item = items["Remove"]
    remove_button = getattr(remove_item, "item", remove_item)
    check(items["Run it"].disabled and not remove_button.disabled and "-# Expired." in reply.content,
          f"Run it greyed out, Remove still live: {reply.content!r}")

    # ---- Steam card: colors and buttons ----
    sale = {"name": "ELDEN RING", "free": False,
            "price": {"discount_percent": 40, "final_formatted": "$35.99", "initial_formatted": "$59.99"}}
    full = {"name": "ELDEN RING", "free": False, "price": {"discount_percent": 0, "final_formatted": "$59.99"}}
    gone = {"name": "Delisted", "free": False, "price": None}
    check(card_color(await sp.steam_card(guild, 1, sale, 2)) == ui.HIGHLIGHT, "on sale: highlight")
    check(card_color(await sp.steam_card(guild, 1, full, 2)) == ui.BRAND, "full price: brand")
    check(sp_mod.price_text(gone) == "Not for sale right now", "not-for-sale wording")
    own, want = sp_mod.SteamButton("own", 1).item, sp_mod.SteamButton("want", 1).item
    check(own.style == want.style == discord.ButtonStyle.secondary and not own.emoji and not want.emoji,
          "Steam buttons grey, no emoji (the 🗑️ beside them is icon-only)")

    # ---- status lines ----
    async def run_cmd(author, content):
        c = await bot.get_context(FakeMessage(channel, content, author=author))
        await bot.invoke(c)
        return channel.sent[-1].content

    out = await run_cmd(brad, "!speakup feature tims off")
    check(out.startswith("❓ ") and "`!speakup feature links off`" in out, out)
    out = await run_cmd(alex, "!reminders clear")
    check(out.startswith("❓ "), out)
    await run_cmd(alex, "!remindme 2h one")
    await run_cmd(alex, "!remindme 3h two")
    out = await run_cmd(alex, "!reminders clear")
    check(out == "✅ Cancelled 2 reminders.", out)
    out = await run_cmd(brad, "!speakup off")
    check(out.startswith("✅ "), out)
    i = FakeInteraction(bot, guild, alex, channel)
    await sp.schedule_from_time(i, int(time.time()) - 10)
    check(i.response.calls[-1][1] == "⚠️ That time has already passed.", i.response.calls[-1])

    for name in ("SpeakUp", "ClaudeChat", "GameManager"):
        await bot.remove_cog(name)


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
