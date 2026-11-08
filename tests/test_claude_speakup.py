"""Claude cog helpers for SpeakUp: summarize_link (web fetch fallbacks) and suggest_command (guide cache)."""
import asyncio
from unittest.mock import MagicMock

from harness import FakeGuild, FakeMessage, TestBot, load, sys

claude_mod = load("claude", "claude")
gm_mod = load("gamemanager", "gamemanager")
FakeMessage._state = None
results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def resp(blocks, model="claude-haiku-5-5"):
    r = MagicMock()
    r.model, r.stop_reason, r.content = model, "end_turn", blocks
    r.usage = MagicMock(input_tokens=3000, output_tokens=60, cache_read_input_tokens=20000,
                        cache_creation_input_tokens=0, server_tool_use=None)
    return r


async def main():
    guild = FakeGuild()
    alex = guild.add(2, "Alex")
    bot = TestBot(guild)
    bot.loop = asyncio.get_running_loop()
    cc = claude_mod.ClaudeChat(bot)
    await bot.add_cog(cc)
    gm = gm_mod.GameManager(bot)
    await bot.add_cog(gm)
    gm.sale_loop.cancel()
    gm.session_loop.cancel()
    calls = []
    replies = []

    class Client:
        class messages:
            @staticmethod
            async def create(**kw):
                calls.append(kw)
                tools = kw.get("tools") or []
                if tools and tools[0].get("type") == "web_fetch_20260209" and kw["model"] == "claude-haiku-5-5":
                    raise sys.modules["anthropic"].BadRequestError("web_fetch_20260209 is not supported")
                return replies.pop(0)

    async def get_client():
        return Client()
    cc._get_client = get_client

    # summarize_link: falls back, keeps only the text after the fetch
    replies.append(resp([Block(type="text", text="Let me fetch that."),
                         Block(type="server_tool_use", name="web_fetch"),
                         Block(type="web_fetch_tool_result"),
                         Block(type="text", text="- It's about a thing\n- And another")]))
    out = await cc.summarize_link("https://example.com/a", alex)
    check(out == "- It's about a thing\n- And another", out)
    check([c["tools"][0]["type"] for c in calls] == ["web_fetch_20260209", "web_fetch_20250910"], "fallback order")
    check(cc._link_reader == 1, "remembers the working option")
    replies.append(resp([Block(type="text", text="UNAVAILABLE")]))
    check(await cc.summarize_link("https://example.com/b", alex) is None, "unavailable -> None")
    usage = await cc.config.guild(guild).usage()
    check(usage["requests"] == 2, f"usage recorded: {usage}")

    # suggest_command: the cached command reference, validated against real commands
    calls.clear()
    replies.append(resp([Block(type="text", text="`!games own Barony`")]))
    message = FakeMessage(guild.channel, "!game owns barony", author=alex)
    out = await cc.suggest_command(message, "!game owns barony")
    kw = calls[-1]
    check(out == "!games own Barony", out)
    check("tools" not in kw and kw["system"][0]["cache_control"] == {"type": "ephemeral"}
          and "# Command reference" in kw["system"][0]["text"] and "`!games own" in kw["system"][0]["text"],
          "whole command reference, cached, no tools")
    replies.append(resp([Block(type="text", text="!notacommand x")]))
    check(await cc.suggest_command(message, "!nope") is None, "unknown command rejected")
    replies.append(resp([Block(type="text", text="none")]))
    check(await cc.suggest_command(message, "!nope") is None, "none -> None")
    for name in ("GameManager", "ClaudeChat"):
        await bot.remove_cog(name)


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
