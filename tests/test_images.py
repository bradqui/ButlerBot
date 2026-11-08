"""Claude cog image handling: real format from bytes, shrinking big images, rejecting non-images."""
import asyncio
import base64
import io
import os

from harness import FakeGuild, TestBot, load

claude_mod = load("claude", "claude")
from PIL import Image  # noqa: E402  (pylibs is on the path after harness)

results = []


def check(cond, label):
    results.append((bool(cond), label))
    if not cond:
        print("FAIL:", label)


def png_bytes(w, h, noisy=False):
    img = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3)) if noisy else Image.new("RGBA", (w, h), (10, 20, 30, 128))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


class Att:
    def __init__(self, data, filename, content_type):
        self.data, self.filename, self.content_type, self.size = data, filename, content_type, len(data)

    async def read(self):
        return self.data


async def main():
    small = png_bytes(200, 100)
    check(claude_mod.sniff_image_type(small) == "image/png", "png sniffed")
    check(claude_mod.prepare_image(small) == (small, "image/png"), "small image passes through untouched")

    huge = png_bytes(3000, 2000, noisy=True)
    check(len(huge) > claude_mod.MAX_IMAGE_BYTES, f"test image is big: {len(huge)}")
    data, media = claude_mod.prepare_image(huge)
    with Image.open(io.BytesIO(data)) as img:
        size = img.size
    check(media == "image/jpeg" and max(size) == 1568 and len(data) <= claude_mod.MAX_IMAGE_BYTES,
          f"big image shrunk: {size} {len(data)}")
    wide = png_bytes(4000, 300)   # small file, too many pixels
    data, media = claude_mod.prepare_image(wide)
    check(media == "image/jpeg" and Image.open(io.BytesIO(data)).size[0] == 1568, "oversized dimensions shrunk")
    check(claude_mod.prepare_image(b"not an image at all") is None, "non-image rejected")
    gif = io.BytesIO()
    Image.new("P", (50, 50)).save(gif, "GIF")
    check(claude_mod.prepare_image(gif.getvalue())[1] == "image/gif", "gif kept")

    guild = FakeGuild()
    bot = TestBot(guild)
    cc = claude_mod.ClaudeChat(bot)
    # Discord labeled a PNG as webp (the 400 from the screenshot)
    block, note = await cc._attachment_block(Att(small, "tm0m3.png", "image/webp"))
    check(block["source"]["media_type"] == "image/png" and note is None, f"mislabeled png fixed: {block['source']['media_type']}")
    block, note = await cc._attachment_block(Att(huge, "weevils.png", "image/png"))
    check(block is not None and block["source"]["media_type"] == "image/jpeg"
          and len(base64.b64decode(block["source"]["data"])) <= claude_mod.MAX_IMAGE_BYTES, f"big upload shrunk: {note}")
    block, note = await cc._attachment_block(Att(b"x" * 100, "fake.png", "image/png"))
    check(block is None and "isn't an image" in note, note)


asyncio.run(main())
print(f"{sum(ok for ok, _ in results)}/{len(results)} checks passed")
