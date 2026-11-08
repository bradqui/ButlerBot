"""Censord: words never echoed, command deleted, honest add/remove replies, status symbols, threshold checks."""
import asyncio
import types

from harness import (DATA_DIR, FakeChannel, FakeGuild, FakeMessage, TestBot, card_color, card_text, discord, load,
                     validate_layout)

cs_mod = load("censord", "censord")
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


async def _delete(self, **kw):
    if getattr(self, "fail_delete", False):
        raise discord.Forbidden(types.SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")
    self.deleted = True


FakeMessage.delete = _delete
FakeMessage.deleted = False
FakeMessage._state = None
SYMBOLS = ("✅", "❌", "⚠️", "⏳", "🔒", "❓")


async def main():
    guild = FakeGuild()
    admin = guild.add(1, "Brad", admin=True)
    member = guild.add(2, "trolluser")
    member.display_name = "Troll Display"
    kicked = []

    async def kick(user, reason=None):
        kicked.append(user)
    guild.kick = kick
    bot = TestBot(guild)
    cog = cs_mod.Censord(bot)
    await bot.add_cog(cog)
    channel = guild.channel

    async def run(content, author=admin, fail_delete=False):
        msg = FakeMessage(channel, content, author=author)
        msg.fail_delete = fail_delete
        ctx = await bot.get_context(msg)
        check(ctx.valid, f"parses: {content}")
        before = len(channel.sent)
        await bot.invoke(ctx)
        return msg, (channel.sent[-1].content if len(channel.sent) > before else None)

    def on_list(level, word):
        return word in (DATA_DIR / f"{level}.csv").read_text(encoding="utf-8")

    # addword: no echo, command deleted, honest replies
    msg, out = await run("!censor addword low zorblax")
    check(out.startswith("✅ Added that word to the **low** list."), out)
    check("zorblax" not in out, "added word not echoed")
    check(msg.deleted and "I deleted your command" in out, "command message deleted, with a note")
    check(on_list("low", "zorblax"), "word saved")
    msg, out = await run("!censor addword low zorblax")
    check(out.startswith("⚠️ That word is already on the **low** list.") and "zorblax" not in out, out)

    # delword: honest when it wasn't there; deletion failure is ignored
    msg, out = await run("!censor delword high zorblax", fail_delete=True)
    check(out == "❓ That word wasn't on the **high** list.\n-# It has to match the entry exactly.", out)
    check(not msg.deleted and "I deleted" not in out, "no note when the command couldn't be deleted")
    msg, out = await run("!censor delword low zorblax")
    check(out.startswith("✅ Removed that word from the **low** list.") and not on_list("low", "zorblax"), out)
    msg, out = await run("!censor addword medium zorblax")
    check(out.startswith("❓") and "zorblax" not in out and msg.deleted, "bad level: still hidden")
    check(cog._update_csv("high", " spaced ", add=True) and not cog._update_csv("high", "spaced", add=True),
          "_update_csv reports changes (and trims)")

    # threshold must be at least 1
    _, out = await run("!censor threshold 0 60")
    check(out.startswith("❓") and "\n-# For example `!censor threshold 3 60`." in out, out)
    _, out = await run("!censor threshold 3 -5")
    check(out.startswith("❓"), "negative seconds refused")
    conf = await cog.config.guild(guild).all()
    check((conf["threshold_count"], conf["threshold_time"]) == (3, 60), "bad threshold not saved")
    _, out = await run("!censor threshold 2 1")
    check(out == "✅ The punishment now comes after 2 violations within 1 second.", out)

    # Other replies use status symbols and consistent wording
    for content in ("!censor level loud", "!censor level low", "!censor action smite", "!censor action kick",
                    "!censor strategy maybe", "!censor strategy exclude", "!censor reload", "!censor setrole"):
        _, out = await run(content)
        check(out is not None and out.startswith(SYMBOLS), f"{content} -> {out}")
    # Channel toggles (called directly: the fake channel can't go through the TextChannel converter)
    ctx = await bot.get_context(FakeMessage(channel, "!censor reload", author=admin))
    for command in (cog.exceptchan, cog.exceptchan, cog.includechan):
        await command.callback(cog, ctx, channel)
        out = channel.sent[-1].content
        check(out.startswith("✅") and channel.mention in out, out)
    _, out = await run("!censor reload")
    check("pattern" in out and "(s)" not in out, out)

    # Settings card
    await run("!censor config")
    shown = channel.sent[-1]
    check("### 🛡️ Word filter settings" in card_text(shown) and card_color(shown) == cs_mod.ui.BRAND, "settings card")
    check("**Threshold** · 2 messages in 1 second" in card_text(shown), "threshold row")
    check(card_text(shown).endswith("\n-# `!help censor` shows how to change these · Staff only")
          and "**Channel overrides**\nNone" in card_text(shown), "footer: one hint; no overrides")
    # Phase 5: each channel override is its own two-line block, and a long list is capped
    extra = []
    for n in range(12):
        ch = FakeChannel(guild, 900 + n)
        guild.text_channels.append(ch)
        extra.append(ch)
        await cog.config.channel(ch).override_level.set("high")
    await cog.config.channel(extra[0]).override_action.set("ban")
    await run("!censor config")
    shown = channel.sent[-1]
    blocks = [c.content for c in shown.view.walk_children() if isinstance(c, discord.ui.TextDisplay)]
    check(f"{extra[0].mention}\n-# Level high · action ban" in blocks
          and f"{extra[1].mention}\n-# Level high" in blocks, blocks)
    check(sum(b.startswith("<#9") for b in blocks) == cs_mod.MAX_OVERRIDES_SHOWN
          and "-# …and 2 more channels" in blocks, "overrides capped")
    check(validate_layout(shown.view) == [], validate_layout(shown.view))
    for ch in extra:
        guild.text_channels.remove(ch)

    # Non-admins get a 🔒 explanation
    ctx = await bot.get_context(FakeMessage(channel, "!censor level off", author=member))
    try:
        await cog.cog_check(ctx)
        refused = None
    except Exception as e:
        refused = e
    check(type(refused).__name__ == "UserFeedbackCheckFailure" and refused.message.startswith("🔒"), repr(refused))

    # Filtering: warning mentions without pinging; punishment names the display name
    await cog.config.guild(guild).global_level.set("low")
    await cog.config.guild(guild).threshold_time.set(60)
    cog._update_csv("low", "zorblax", add=True)
    bad = FakeMessage(channel, "you zorblax", author=member)
    await cog.on_message(bad)
    warn = channel.sent[-1]
    check(bad.deleted and warn.content == f"⚠️ {member.mention}, watch your language." and
          warn.kw["allowed_mentions"].users is False and warn.kw["delete_after"] == 3, "warning, no ping")
    await cog.on_message(FakeMessage(channel, "zorblax again", author=member))
    announce = channel.sent[-1]
    check(kicked == [member], "kicked at the threshold")
    check(announce.content == "👢 **Troll Display** was kicked for repeated offensive language."
          and announce.kw["allowed_mentions"].users is False, announce.content)
    clean = FakeMessage(channel, "hello friends", author=member)
    await cog.on_message(clean)
    check(not clean.deleted, "clean messages untouched")


asyncio.run(main())
passed = sum(ok for ok, _ in results)
print(f"{passed}/{len(results)} checks passed")
