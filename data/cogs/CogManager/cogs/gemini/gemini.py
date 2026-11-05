import importlib.util
import io
import logging
import sys
from pathlib import Path
from typing import List, Optional

import discord
from google import genai
from google.genai import types
from redbot.core import commands, Config, checks

log = logging.getLogger("red.gemini")


def _load_butlerui():
    """The shared style module (../_shared/butlerui.py), re-read when the file changes."""
    path = Path(__file__).resolve().parent.parent / "_shared" / "butlerui.py"
    module, mtime = sys.modules.get("butlerui"), path.stat().st_mtime
    if module is None or getattr(module, "_mtime", None) != mtime:
        spec = importlib.util.spec_from_file_location("butlerui", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module._mtime = mtime
        sys.modules["butlerui"] = module
    return module


ui = _load_butlerui()

DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image"


class GeminiChat(commands.Cog):
    """
    Image generation with Google Gemini.

    Chat is handled by the Claude cog, which hands image requests ("draw ...",
    "image of ...") to this cog. You can also use `[p]draw` directly.
    """

    def __init__(self, bot):
        self.bot = bot
        # Same identifier as before so the saved API key and image model choices carry over.
        self.config = Config.get_conf(self, identifier=9283748291)
        self.config.register_global(api_key=None)
        self.config.register_user(image_model=DEFAULT_IMAGE_MODEL)
        self.config.register_channel(image_model=DEFAULT_IMAGE_MODEL)

        self.client = None
        self.current_api_key = None
        self.image_sessions = {}  # session key -> AsyncChat, so follow-up edits refine the same image

        self.model_aliases = {
            "image": "gemini-2.5-flash-image",
            "3image": "gemini-3-pro-image-preview",
        }

    async def cog_unload(self):
        if self.client is not None:
            try:
                await self.client.aio.aclose()
            except Exception:
                pass

    async def _init_genai(self):
        api_key = await self.config.api_key()
        if not api_key:
            return False
        if self.client is None or self.current_api_key != api_key:
            self.client = genai.Client(api_key=api_key)
            self.current_api_key = api_key
            self.image_sessions = {}
        return True

    async def _send(self, reply_target, channel, content, files=None):
        kwargs = {"allowed_mentions": ui.NO_PINGS}
        if files:
            kwargs["files"] = files
        if isinstance(reply_target, discord.Message) and reply_target.channel == channel:
            kwargs["reference"] = reply_target.to_reference(fail_if_not_exists=False)
            kwargs["mention_author"] = False
        return await channel.send(content, **kwargs)

    async def _prefix(self, guild):
        for prefix in await self.bot.get_valid_prefixes(guild):
            if not prefix.startswith("<@"):
                return prefix
        return "!"

    def _error_text(self, e, model_name, prefix="!"):
        """A short sentence for a Gemini error. Callers log the raw error; it's never posted."""
        err = str(e)
        if "NOT_FOUND" in err or "404" in err:
            return ui.line(ui.FAIL, f"The image model `{model_name}` wasn't found.",
                           hint=f"`{prefix}gemini list` shows the models that work.")
        if "402" in err:
            return ui.line(ui.WARN, "The Gemini account needs payment or credits, so the bot owner needs to top it up.")
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            return ui.line(ui.WAIT, "Gemini's rate limit or quota was hit. Try again in a minute.")
        if "503" in err or "UNAVAILABLE" in err:
            return ui.line(ui.WAIT, "Google's image service is busy right now. Try again in a minute.")
        return ui.line(ui.FAIL, "Something went wrong talking to Gemini. Try again in a moment; the error was logged.")

    async def _not_set_up(self, user) -> str:
        """The missing-key notice, with the setup command only for the bot owner."""
        if user is not None and await self.bot.is_owner(user):
            prefix = await self._prefix(getattr(user, "guild", None))
            return ui.line(ui.WARN, "Image generation isn't set up yet.",
                           hint=f"Add a key with `{prefix}gemini setkey <key>`.")
        return ui.line(ui.WARN, "Image generation isn't set up yet. Ask the bot owner to add a Gemini API key.")

    async def image_models(self) -> Optional[List[str]]:
        """The models the API lists that can generate images (sorted), or None if they couldn't be listed."""
        if not await self._init_genai():
            return None
        try:
            models = []
            async for m in await self.client.aio.models.list():
                name = m.name.replace("models/", "")
                if "generateContent" in (m.supported_actions or []) and "image" in name:
                    models.append(name)
        except Exception as e:
            log.warning("Couldn't list Gemini models: %s", e)
            return None
        return sorted(models)

    def _channel_key(self, channel):
        # The Claude cog keys AI threads as THREAD_<id>; reuse that image session if one exists.
        thread_key = f"THREAD_{channel.id}"
        return thread_key if thread_key in self.image_sessions else f"CHANNEL_{channel.id}"

    # ==========================================
    #        IMAGE GENERATION (public API)
    # ==========================================

    async def generate_image(self, prompt, session_key, reply_target, *, channel, user, new=True, quiet=False):
        """
        Generate a new image (new=True) or refine the session's last one (new=False) and post it.

        `session_key` is the caller's conversation key (CHANNEL_/THREAD_/USER_<id>). With `quiet`, failures are
        only logged, not posted (for optional pictures, like an adventure's final scene).
        Returns the posted message, or None if nothing was generated.
        Called by the Claude cog and ButlerFun; keep this signature stable.
        """
        prefix = await self._prefix(channel.guild)
        if not await self._init_genai():
            if not quiet:
                await self._send(reply_target, channel, await self._not_set_up(user))
            return None

        if session_key.startswith("USER_"):
            model_name = await self.config.user(user).image_model()
        else:
            conf_channel = channel.parent if isinstance(channel, discord.Thread) and channel.parent else channel
            model_name = await self.config.channel(conf_channel).image_model()

        if new:
            self.image_sessions.pop(session_key, None)

        try:
            chat = self.image_sessions.get(session_key)
            if chat is None:
                chat = self.client.aio.chats.create(model=model_name, config=types.GenerateContentConfig(tools=None))
                self.image_sessions[session_key] = chat
            response = await chat.send_message(prompt)
        except Exception as e:
            self.image_sessions.pop(session_key, None)
            log.warning("Gemini image generation failed: %s", e)
            if not quiet:
                await self._send(reply_target, channel, self._error_text(e, model_name, prefix))
            return None

        files, texts = [], []
        for candidate in response.candidates or []:
            if candidate.content is None or not candidate.content.parts:
                continue
            for part in candidate.content.parts:
                if part.inline_data and part.inline_data.data:
                    ext = "jpg" if "jpeg" in (part.inline_data.mime_type or "") else "png"
                    files.append(discord.File(io.BytesIO(part.inline_data.data), f"generated.{ext}"))
                elif part.text:
                    texts.append(part.text)
            break  # only the first candidate

        if not files:
            self.image_sessions.pop(session_key, None)
            reason = " ".join(" ".join(texts).split())
            log.info("Gemini returned no image: %s", reason[:200] or "(no text)")
            if not quiet:
                # Gemini's own words usually say why (a blocked request): shortened, in a small note.
                await self._send(reply_target, channel, ui.line(
                    ui.FAIL, "Gemini didn't return an image. Try rewording the request.",
                    hint=ui.truncate(reason, 300) if reason else "The request may have been blocked."))
            return None

        # Just the image: echoing the prompt back is noise, and it would give away guess-the-game answers.
        return await self._send(reply_target, channel, None, files=files)

    # ==========================================
    #                 COMMANDS
    # ==========================================

    @commands.group(name="draw", invoke_without_command=True)
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def draw(self, ctx, *, prompt: str = None):
        """
        Generate an image with Gemini.

        Use `[p]draw edit <changes>` to refine the last image in this channel.
        You can also ask in chat: `[p]ai draw a castle at sunset`.
        """
        if not prompt:
            return await ctx.send_help()
        async with ctx.typing():
            await self.generate_image(prompt, self._channel_key(ctx.channel), ctx.message,
                                      channel=ctx.channel, user=ctx.author, new=True)

    @draw.command(name="edit")
    async def draw_edit(self, ctx, *, changes: str):
        """Refine the last image generated in this channel."""
        key = self._channel_key(ctx.channel)
        if key not in self.image_sessions:
            return await ctx.send(f"❓ There's no recent image here to edit. Start one with "
                                  f"`{ctx.clean_prefix}draw <prompt>`.")
        async with ctx.typing():
            await self.generate_image(changes, key, ctx.message, channel=ctx.channel, user=ctx.author, new=False)

    @commands.group()
    async def gemini(self, ctx):
        """Gemini image generation settings."""

    @gemini.command(name="setkey")
    @checks.is_owner()
    async def set_api_key(self, ctx, key: str):
        """Set the Gemini API key (your message is deleted)."""
        # Delete the key's message first, so it's gone even if saving or replying fails.
        try:
            await ctx.message.delete()
            deleted = True
        except discord.HTTPException:
            deleted = False
        await self.config.api_key.set(key)
        await ctx.send(ui.line(ui.DONE, "Gemini API key saved.") if deleted else
                       ui.line(ui.WARN, "Gemini API key saved, but I couldn't delete your message. Delete it yourself."))

    @gemini.command(name="list")
    async def list_models(self, ctx):
        """List the Gemini models that can generate images."""
        if not await self._init_genai():
            return await ctx.send(await self._not_set_up(ctx.author))
        async with ctx.channel.typing():
            models = await self.image_models()
        if models is None:
            return await ctx.send(ui.line(ui.FAIL, "I couldn't get the model list from Google. Try again in a minute."))
        if not models:
            return await ctx.send(ui.line(ui.ASK, "Google didn't list any image models."))
        # One model a row; a long list pages with ◀ ▶.
        shortcuts = "Shortcuts: " + ", ".join(f"{a} = {m}" for a, m in self.model_aliases.items())
        await ui.Board("🎨 Image models", [f"`{m}`" for m in models], color=ui.BRAND,
                       footer=ui.truncate(shortcuts, 300)).send(ctx)

    @gemini.command(name="settings")
    async def show_settings(self, ctx):
        """Show the image models used for you and this channel."""
        u_img = await self.config.user(ctx.author).image_model()
        c_img = await self.config.channel(ctx.channel).image_model()
        p = ctx.clean_prefix
        container = ui.card(
            ui.settings_text([(f"Your private requests (`{p}myai draw …`)", f"`{u_img}`"),
                              ("This channel", f"`{c_img}`")]),
            ui.SEPARATOR, title="🎨 Image settings", color=ui.BRAND,
            footer=f"Change with {p}gemini model or {p}gemini channelmodel · {p}gemini list shows the models")
        await ui.send_card(ctx, ui.CardView(container))

    async def _check_model(self, ctx, model_name: str):
        """
        (model to save, hint or None), or (None, error line). Aliases always work; other names must be in the
        API's list of image models. If the list can't be fetched, the name is accepted with a hint.
        """
        name = model_name.strip().strip("`")
        if name.lower() in self.model_aliases:
            return self.model_aliases[name.lower()], None
        name = name.replace("models/", "")
        async with ctx.channel.typing():
            models = await self.image_models()
        if models is None:
            return name,"I couldn't check that name with Google, so make sure it's right."
        if name not in models:
            shown = ", ".join(models[:10]) or "none right now"
            return None, ui.line(ui.FAIL, f"`{name[:80]}` isn't an image model I can use.",
                                 hint=f"Try `image` or `3image`, or one of: {shown}.")
        return name, None

    @gemini.command(name="model")
    async def set_user_image_model(self, ctx, model_name: str):
        """Set the image model for your private requests. Aliases: `image`, `3image`."""
        target, note = await self._check_model(ctx, model_name)
        if target is None:
            return await ctx.send(note)
        await self.config.user(ctx.author).image_model.set(target)
        self.image_sessions.pop(f"USER_{ctx.author.id}", None)
        await ctx.send(ui.line(ui.DONE, f"Your private image model is now `{target}`.", hint=note))

    @gemini.command(name="channelmodel")
    @checks.mod_or_permissions(manage_channels=True)
    async def set_channel_image_model(self, ctx, model_name: str):
        """Set the image model for this channel. Aliases: `image`, `3image`."""
        target, note = await self._check_model(ctx, model_name)
        if target is None:
            return await ctx.send(note)
        await self.config.channel(ctx.channel).image_model.set(target)
        self.image_sessions.pop(f"CHANNEL_{ctx.channel.id}", None)
        await ctx.send(ui.line(ui.DONE, f"This channel's image model is now `{target}`.", hint=note))
