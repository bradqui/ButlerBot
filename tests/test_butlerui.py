"""Tests for the shared style module (_shared/butlerui.py)."""
import asyncio
import importlib.util
import sys

import harness  # noqa: F401  (puts discord.py on the path)
import discord

PATH = harness.os.path.join(harness.COGS, "_shared", "butlerui.py")
spec = importlib.util.spec_from_file_location("butlerui", PATH)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL", name, detail)


# line / hint / plural
check("line", ui.line(ui.DONE, "Saved.") == "✅ Saved.")
check("line hint", ui.line(ui.FAIL, "Nope.", "Try again.") == "❌ Nope.\n-# Try again.")
check("line no symbol", ui.line(None, "Plain") == "Plain")
check("hint multi", ui.hint("a\nb") == "-# a\n-# b")
check("plural 1", ui.plural(1, "reminder") == "1 reminder")
check("plural many", ui.plural(1204, "message") == "1,204 messages")
check("plural irregular", ui.plural(2, "person", "people") == "2 people")

# truncate
check("truncate short", ui.truncate("hello", 10) == "hello")
t = ui.truncate("word " * 100, 50)
check("truncate len", len(t) <= 50, len(t))
check("truncate at word", t.endswith("word…"), t)

# split_text
text = "\n".join(f"Line {i} " + "x" * 40 for i in range(200))
pages = ui.split_text(text, 1900)
check("split sizes", all(len(p) <= 1900 for p in pages), [len(p) for p in pages])
check("split keeps all", "".join(p.replace("\n", "") for p in pages) == text.replace("\n", ""))
check("split at lines", all(p.startswith("Line ") for p in pages))
words = " ".join(["supercalifragilistic"] * 300)
pages = ui.split_text(words, 500)
check("split words whole", all(not p.endswith("supercal") for p in pages) and all(len(p) <= 500 for p in pages))
check("split words intact", " ".join(pages).split() == words.split())
code = "Intro\n```py\n" + "\n".join(f"print({i})" for i in range(400)) + "\n```\nOutro"
pages = ui.split_text(code, 800)
check("code fences balanced", all(p.count("```") % 2 == 0 for p in pages), [p.count("```") for p in pages])
check("code reopened with lang", all(p.startswith("```py") for p in pages[1:-1]) if len(pages) > 2 else True)
check("code sizes", all(len(p) <= 800 for p in pages))
check("split short", ui.split_text("hi") == ["hi"])
huge = "y" * 5000
pages = ui.split_text(huge, 1000)
check("split hard", "".join(pages) == huge and all(len(p) <= 1000 for p in pages))


# ExpiringView
class Msg:
    def __init__(self, content):
        self.content, self.edits = content, []

    async def edit(self, **kw):
        self.edits.append(kw)
        if "content" in kw:
            self.content = kw["content"]


async def views():
    view = ui.ExpiringView(1, timeout=60)
    view.add_item(discord.ui.Button(label="Go"))
    msg = Msg("Pick one")
    view.message = msg
    await view.on_timeout()
    check("expired disables", all(i.disabled for i in view.children))
    check("expired note", msg.content == "Pick one\n-# Expired.", msg.content)
    await view.on_timeout()
    check("note added once", msg.content.count("Expired") == 1)

    class Resp:
        def __init__(self):
            self.sent = []

        async def send_message(self, content, **kw):
            self.sent.append((content, kw))

        def is_done(self):
            return bool(self.sent)

    class Inter:
        def __init__(self, uid):
            self.user = type("U", (), {"id": uid})()
            self.response = Resp()

    other = Inter(2)
    check("others refused", await view.interaction_check(other) is False)
    check("refusal private", other.response.sent[0][1].get("ephemeral") is True)
    check("owner allowed", await view.interaction_check(Inter(1)) is True)
    view2 = ui.ExpiringView(1)
    await view2.on_timeout()   # no message: nothing to do
    check("no message ok", True)

asyncio.run(views())


# ---------------- cards ----------------
async def cards():
    buttons = [discord.ui.Button(label=f"B{i}", custom_id=f"b{i}") for i in range(7)]
    sel = discord.ui.Select(custom_id="s", options=[discord.SelectOption(label="x")])
    c = ui.card("Hello <@1>", ui.SEPARATOR, buttons, [sel], "", None, title="🎮 Raid night", color=ui.SUCCESS,
                footer="Reminder 15 min before")
    comps = c.to_component_dict()
    types = [p["type"] for p in comps["components"]]
    check("card layout", types == [10, 10, 14, 1, 1, 1, 10], types)
    check("card title", comps["components"][0]["content"] == "### 🎮 Raid night")
    check("card color", comps["accent_color"] == 0x57F287)
    check("rows of five", [len(p["components"]) for p in comps["components"] if p["type"] == 1] == [5, 2, 1])
    check("footer hint", comps["components"][-1]["content"] == "-# Reminder 15 min before")

    t = ui.card("Some text", "More", title="Hades II", thumbnail="https://img/x.png").to_component_dict()
    first = t["components"][0]
    check("thumbnail section", first["type"] == 9 and first["accessory"]["type"] == 11
          and [x["content"] for x in first["components"]] == ["### Hades II", "Some text"], first)
    check("thumbnail rest", t["components"][1]["content"] == "More")

    check("settings rows", ui.settings_text([("Web search", True), ("Limit", None), ("Model", "Sonnet")])
          == "**Web search** · On\n**Limit** · not set\n**Model** · Sonnet")

    v = ui.CardView(ui.card("x", title="T"))
    check("cardview v2", v.has_components_v2() and len(v.children) == 1)

    class Built(ui.CardView):
        n = 0

        def build(self):
            self.n += 1
            return ui.card(f"count {self.n}")
    b = Built()
    b.redraw(); b.redraw()
    check("redraw replaces", len(b.children) == 1 and b.children[0].children[0].content == "count 2")

    link = discord.ui.Button(label="Open", url="https://example.com")
    exp = ui.ExpiringCard(1, ui.card("Pick", [discord.ui.Button(label="Go", custom_id="go"), link]), timeout=30)
    msg = Msg("")
    exp.message = msg
    await exp.on_timeout()
    go = [i for i in exp.walk_children() if isinstance(i, discord.ui.Button) and i.label == "Go"][0]
    check("card expired disables", go.disabled and not link.disabled)
    texts = [i.content for i in exp.children[0].children if isinstance(i, discord.ui.TextDisplay)]
    check("card expired note", texts[-1] == "-# Expired.", texts)
    check("card expired edit", msg.edits and msg.edits[-1].get("view") is exp and "content" not in msg.edits[-1],
          msg.edits)
    await exp.on_timeout()
    texts = [i.content for i in exp.children[0].children if isinstance(i, discord.ui.TextDisplay)]
    check("note once", texts.count("-# Expired.") == 1)

    class Flags:
        components_v2 = True
    class M:
        flags = Flags()
    check("is_card", ui.is_card(M()) and not ui.is_card(None) and not ui.is_card(Msg("")))

    sent = []
    class Chan:
        async def send(self, **kw):
            sent.append(kw)
            return "msg"
    r = await ui.send_card(Chan(), v)
    check("send_card no pings", r == "msg" and sent[0]["allowed_mentions"] is ui.NO_PINGS and sent[0]["view"] is v)

    class Resp2:
        def __init__(self): self.calls = []
        def is_done(self): return False
        async def send_message(self, **kw): self.calls.append(kw)
    class Inter2(discord.Interaction):
        def __init__(self):
            self._r = Resp2()
        response = property(lambda s: s._r)
        async def original_response(self): return "orig"
    i2 = Inter2()
    r = await ui.send_card(i2, v, ephemeral=True)
    check("send_card interaction", r == "orig" and i2._r.calls[0]["ephemeral"] is True
          and i2._r.calls[0]["allowed_mentions"] is ui.NO_PINGS)

asyncio.run(cards())


# ---------------- boards ----------------
import harness as H  # noqa: E402


async def boards():
    import inspect
    check("edit_message takes allowed_mentions",
          "allowed_mentions" in inspect.signature(discord.InteractionResponse.edit_message).parameters)
    rows = [f"Game {i}" for i in range(40)]
    b = ui.Board("🎮 Server library", rows, footer="40 games", header="Owned here")
    check("pages", len(b.pages) == 5 and [len(p) for p in b.pages] == [8, 8, 8, 8, 8])
    check("timeout set", b.timeout == 900)
    text = H.card_text(b)
    check("page 1 text", "Game 0" in text and "Game 8" not in text and "Owned here" in text, text)
    check("footer page", "-# Page 1 of 5 · 40 games" in text, text)
    blocks = [c for c in b.children[0].children if isinstance(c, discord.ui.TextDisplay)]
    check("each row its own block", sum(1 for t in blocks if t.content.startswith("Game ")) == 8)
    check("no jump menu up to 5 pages", not any(isinstance(c, discord.ui.Select) for c in b.walk_children()))
    btns = H.card_buttons(b)
    check("nav buttons", len(btns) == 2 and btns[0].disabled and not btns[1].disabled)
    check("no layout problems", not H.validate_layout(b))

    class Resp:
        def __init__(self): self.edits = []
        def is_done(self): return False
        async def edit_message(self, **kw): self.edits.append(kw)
    class Inter(discord.Interaction):
        def __init__(self): self._r = Resp()
        response = property(lambda s: s._r)
    i = Inter()
    await btns[1].callback(i)
    text = H.card_text(b)
    check("next page", b.page == 1 and "Game 8" in text and "Game 0\n" not in text and "Page 2 of 5" in text)
    check("edit sent", i._r.edits and i._r.edits[0]["view"] is b and i._r.edits[0]["allowed_mentions"] is ui.NO_PINGS)
    for _ in range(3):
        btns = H.card_buttons(b)
        await btns[1].callback(Inter())
    btns = H.card_buttons(b)
    check("last page", b.page == 4 and not btns[0].disabled and btns[1].disabled)
    await btns[1].callback(Inter())
    check("clamped", b.page == 4)

    # two-line rows and the jump menu
    tall = ui.Board("🎮 Server library", [ui.row(f"**Game {i:02}**", f"{i} own") for i in range(60)] + ["Loose row"])
    text = H.card_text(tall)
    check("row detail is small text", "**Game 00**\n-# 0 own" in text, text[:200])
    menu = next((c for c in tall.walk_children() if isinstance(c, discord.ui.Select)), None)
    check("jump menu past 5 pages", menu is not None and len(menu.options) == 8
          and menu.options[1].label == "Page 2" and menu.options[1].description == "Game 08 – Game 15",
          [(o.label, o.description) for o in (menu.options if menu else [])][:2])
    check("tall valid", not H.validate_layout(tall))

    class Sel:
        values = ["6"]
    await tall._jump(Sel)(Inter())
    check("jump goes to the page", tall.page == 6 and "Game 48" in H.card_text(tall))
    many = ui.Board("Many", [f"r{i}" for i in range(8 * 60)])
    m = next(c for c in many.walk_children() if isinstance(c, discord.ui.Select))
    check("jump groups pages over 25", len(m.options) <= 25 and m.options[1].label == "Pages 4–6",
          [o.label for o in m.options[:3]])
    check("plain strips markup", ui.plain("**A** `b` <@123>") == "A b", ui.plain("**A** `b` <@123>"))
    check("two_line", ui.two_line("**X**", "y") == "**X**\n-# y" and ui.two_line("**X**") == "**X**")

    one = ui.Board("Few", ["a", "b"], footer="2 things")
    check("single page", one.timeout is None and not H.card_buttons(one) and "Page" not in H.card_text(one))
    empty = ui.Board("None", [])
    check("empty", "Nothing to show yet." in H.card_text(empty))
    big = ui.Board("Big", ["x" * 500] * 15)
    check("size paging", all(sum(len(r) + 1 for r in p) <= 3400 for p in big.pages) and len(big.pages) > 1)
    check("big valid", not H.validate_layout(big))
    withimg = ui.Board("Chart", ["a"], media=ui.image("attachment://stats.png", "chart"))
    kinds = [type(c).__name__ for c in withimg.children[0].children]
    check("media in card", "MediaGallery" in kinds, kinds)

    g = H.FakeGuild()
    msg = await b.send(g.channel)
    check("board send", msg is g.channel.sent[-1] and b.message is msg and msg.flags.components_v2)
    await b.on_timeout()
    check("board expiry", all(x.disabled for x in H.card_buttons(b))
          and "Run the command again to page through it." in H.card_text(b))

asyncio.run(boards())
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
