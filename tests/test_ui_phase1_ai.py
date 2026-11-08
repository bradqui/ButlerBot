"""UI phase 1 (AI cogs): sanitized errors, split_text replies, missing-key notices, model checks, Gemini validation."""
import asyncio
import re
import sys
import types

from harness import FakeGuild, FakeMessage, TestBot, card_text, load

import anthropic  # noqa: E402  (the harness's stub)

# ---- a stub google.genai, enough for the Gemini cog ----
google = types.ModuleType("google")
genai = types.ModuleType("google.genai")
genai_types = types.ModuleType("google.genai.types")
genai_types.GenerateContentConfig = lambda **kw: kw
LISTING = {"models": ["models/gemini-2.5-flash-image", "models/gemini-3-pro-image-preview", "models/gemini-2.5-pro"],
           "fail": False}


class _Model:
    def __init__(self, name):
        self.name, self.supported_actions = name, ["generateContent"]


class _Models:
    async def list(self):
        if LISTING["fail"]:
            raise RuntimeError("503 UNAVAILABLE raw listing failure")

        async def gen():
            for name in LISTING["models"]:
                yield _Model(name)
        return gen()


class _Chat:
    async def send_message(self, prompt):
        raise RuntimeError("400 INVALID_ARGUMENT: secret raw details {'prompt': 'x'}")


class _Chats:
    def create(self, **kw):
        return _Chat()


class _Client:
    def __init__(self, api_key):
        self.aio = types.SimpleNamespace(models=_Models(), chats=_Chats(), aclose=self._close)

    async def _close(self):
        pass


genai.Client = _Client
genai.types = genai_types
google.genai = genai
sys.modules.update({"google": google, "google.genai": genai, "google.genai.types": genai_types})

claude_mod = load("claude", "claude")
gemini_mod = load("gemini", "gemini")
FakeMessage._state = None
SYMBOLS = ("✅", "❌", "⚠️", "⏳", "🔒", "❓")
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


async def main():
    guild = FakeGuild()
    brad = guild.add(1, "Brad", admin=True)     # bot owner
    alex = guild.add(2, "Alex")
    channel = guild.channel
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    cc = claude_mod.ClaudeChat(bot)
    await bot.add_cog(cc)

    # ---- Claude: errors are short sentences, never the API's raw text ----
    raw = "messages.0.content: secret raw API details <@1> {\"type\": \"invalid\"}"
    cases = [anthropic.BadRequestError(raw), anthropic.AuthenticationError(raw), anthropic.PermissionDeniedError(raw),
             anthropic.NotFoundError(raw), anthropic.RateLimitError(raw), anthropic.APITimeoutError(raw),
             anthropic.APIConnectionError(raw), RuntimeError(raw)]
    big = anthropic.APIStatusError(raw)
    big.status_code = 529
    odd = anthropic.APIStatusError(raw)
    odd.status_code = 418
    cases += [big, odd]
    for e in cases:
        text, _ = cc._describe_error(e, "!")
        check(text.startswith(SYMBOLS) and "secret" not in text and "```" not in text,
              f"{type(e).__name__} -> {text}")
    check(cc._describe_error(big, "!")[0].startswith("⏳"), "overloaded is a wait")
    check(cc._describe_error(anthropic.BadRequestError("prompt is too long"), "!")[1], "too long still resets")
    check(cc._describe_error(anthropic.BadRequestError("Your credit balance is too low"), "!")[0].startswith("⚠️"),
          "credits is a heads-up")
    check(not hasattr(claude_mod, "split_for_discord"), "local splitter removed")
    # Phase 5: one sentence, the advice on a small line underneath
    for e in cases:
        text, _ = cc._describe_error(e, "!")
        check(len(text.split("\n")) <= 2 and all(ln.startswith("-# ") for ln in text.split("\n")[1:]), text)
    check(cc._describe_error(anthropic.RateLimitError(raw), "!")[0]
          == "⏳ Claude is getting too many requests right now.\n-# Try again in a minute.", "rate limit wording")

    # The Run/Cancel prompt expires like every other menu: greyed out, "Expired. Nothing was run."
    edits = []

    class Msg:
        content = "Here's the plan.\n`!games admin add Halo`"

        async def edit(self, **kw):
            edits.append(kw)
    confirm = claude_mod.ActionConfirmView(2)
    confirm.message = Msg()
    await confirm.on_timeout()
    check(edits and edits[-1]["content"].endswith("\n-# Expired. Nothing was run.") and edits[-1]["view"] is confirm
          and all(b.disabled for b in confirm.children), edits)

    # ---- Claude: long replies go through split_text ----
    text = "Intro.\n```py\n" + "\n".join(f"print({i})  # a line of code" for i in range(150)) + "\n```\nOutro words."
    message = FakeMessage(channel, "!ai code", author=alex)
    before = len(channel.sent)
    await cc._send(message, channel, text)
    pages = [m.content for m in channel.sent[before:]]
    check(len(pages) >= 2 and all(len(pg) <= 1900 for pg in pages) and all(pg.count("```") % 2 == 0 for pg in pages)
          and pages[1].startswith("```py") and pages[-1].endswith("Outro words."), [len(pg) for pg in pages])
    check(all(m.kw.get("suppress_embeds") is None for m in channel.sent[before:]), "AI chat keeps link previews")

    # ---- Claude: missing key and daily limit wording ----
    async def no_client():
        return None
    real_client = cc._get_client
    cc._get_client = no_client
    await cc._respond(FakeMessage(channel, "!ai hi", author=alex), "hi", "CHANNEL_500")
    member_note = channel.sent[-1].content
    await cc._respond(FakeMessage(channel, "!ai hi", author=brad), "hi", "CHANNEL_500")
    owner_note = channel.sent[-1].content
    check(member_note.startswith("⚠️ AI chat isn't set up yet") and "set api" not in member_note, member_note)
    check(owner_note.startswith("⚠️ AI chat isn't set up yet") and "set api anthropic" in owner_note, owner_note)
    text, err = await cc.complete(alex, channel, system="x", messages=[{"role": "user", "content": "hi"}])
    check(text is None and err == member_note, "complete() uses the same notice")
    cc._get_client = real_client
    check(re.fullmatch(r"⏳ You've used all 1 AI message for today\.\n-# The limit resets <t:\d+:R>\.", cc.limit_text(1))
          and "30 AI messages" in cc.limit_text(30), cc.limit_text(1))

    # ---- Claude: commands ----
    async def run(author, content):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        await bot.invoke(ctx)
        return channel.sent[-1].content

    out = await run(brad, "!claude disallowmodel gpt5")
    check(out.startswith("❓") and "`sonnet`" in out and "`haiku`" in out
          and "claude-sonnet-5-5" in await cc.config.allowed_models(), out)
    out = await run(brad, "!claude disallowmodel opus")
    check(out.startswith("✅") and "claude-opus-5-5" not in await cc.config.allowed_models(), out)
    out = await run(brad, "!claude disallowmodel opus")
    check(out.startswith("⚠️") and "already" in out, out)
    out = await run(alex, "!ai reset")
    check(out.startswith("✅") and out.endswith("."), out)
    check(bot.get_command("myai") is None, "no !myai")
    out = await run(brad, "!claude key")
    check(out.startswith("✅ The Anthropic API key is set.") and "\n-# " in out, out)
    await run(brad, "!claude models")
    out = card_text(channel.sent[-1])
    check("🚫" not in out and "**Opus 5.5**\n-# `opus` · $4 in, $20 out per 1M tokens · not allowed" in out
          and "**Sonnet 5.5**\n-# `sonnet` · $2 in, $10 out per 1M tokens · allowed · default" in out
          and "no web search" in out and out.count("\n-# ") == 4, out)
    ctx = await bot.get_context(FakeMessage(channel, "!claude usage", author=alex))
    await cc.claude_usage.callback(cc, ctx, brad)
    out = channel.sent[-1].content
    check(out.startswith("🔒"), out)
    await bot.remove_cog("ClaudeChat")

    # ---- Gemini ----
    gem = gemini_mod.GeminiChat(bot)
    await bot.add_cog(gem)
    sent_before = len(channel.sent)
    await gem.generate_image("a castle", "CHANNEL_500", None, channel=channel, user=alex)
    note = channel.sent[-1].content
    check(len(channel.sent) == sent_before + 1 and note.startswith("⚠️ Image generation isn't set up")
          and "setkey" not in note, note)
    await gem.generate_image("a castle", "CHANNEL_500", None, channel=channel, user=brad)
    check("setkey" in channel.sent[-1].content, "the owner sees the setup command")
    await gem.config.api_key.set("test-key")
    await gem.generate_image("a castle", "CHANNEL_500", None, channel=channel, user=alex)
    note = channel.sent[-1].content
    check(note.startswith("❌") and "secret" not in note and "```" not in note and "Error:" not in note, note)
    for err, symbol in (("404 NOT_FOUND models/x", "❌"), ("402 payment", "⚠️"), ("429 RESOURCE_EXHAUSTED", "⏳"),
                        ("503 UNAVAILABLE", "⏳"), ("500 INTERNAL secret", "❌")):
        text = gem._error_text(RuntimeError(err), "gemini-x", "!")
        check(text.startswith(symbol) and "secret" not in text and "**" not in text, f"{err} -> {text}")

    async def grun(author, content):
        ctx = await bot.get_context(FakeMessage(channel, content, author=author))
        await bot.invoke(ctx)
        return channel.sent[-1].content

    check(bot.get_command("gemini model") is None, "no personal image model")
    out = await grun(brad, "!gemini channelmodel 3image")
    check(out.startswith("✅") and await gem.config.channel(channel).image_model() == "gemini-3-pro-image-preview", out)
    out = await grun(brad, "!gemini channelmodel gpt-image-9")
    check(out.startswith("❌") and "gemini-3-pro-image-preview" in out and "gemini-2.5-pro" not in out
          and await gem.config.channel(channel).image_model() == "gemini-3-pro-image-preview", out)
    out = await grun(brad, "!gemini channelmodel models/gemini-3-pro-image-preview")
    check(out.startswith("✅") and await gem.config.channel(channel).image_model() == "gemini-3-pro-image-preview", out)
    LISTING["fail"] = True
    out = await grun(brad, "!gemini channelmodel gemini-9-image-preview")
    check(out.startswith("✅") and "couldn't check" in out
          and await gem.config.channel(channel).image_model() == "gemini-9-image-preview", out)
    await gem.config.channel(channel).image_model.set("gemini-3-pro-image-preview")
    out = await grun(alex, "!gemini list")
    check(out.startswith("❌") and "503" not in out, out)
    LISTING["fail"] = False
    await grun(alex, "!gemini list")
    out = card_text(channel.sent[-1])
    check(out.startswith("### 🎨 Image models") and "gemini-2.5-pro`" not in out
          and "`gemini-2.5-flash-image`\n-# Shortcut `image` · default\n" in out
          and "`gemini-3-pro-image-preview`\n-# Shortcut `3image` · this channel\n" in out
          and out.endswith("-# Pick one with !gemini channelmodel"), out)
    out = await grun(alex, "!draw edit bluer")
    check(out.startswith("❓"), out)

    order = []
    key_msg = FakeMessage(channel, "!gemini setkey new-key", author=brad)

    async def delete():
        order.append("delete")
    key_msg.delete = delete

    ctx = await bot.get_context(key_msg)
    await bot.invoke(ctx)
    check(order == ["delete"] and await gem.config.api_key() == "new-key"
          and channel.sent[-1].content == "✅ Gemini API key saved.", channel.sent[-1].content)
    await bot.remove_cog("GeminiChat")


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
