import io
import logging

import discord
from google import genai
from google.genai import types
from redbot.core import commands, Config, checks
from redbot.core.utils.chat_formatting import box, pagify

log = logging.getLogger("red.gemini")

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
        kwargs = {"allowed_mentions": discord.AllowedMentions.none()}
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
        err = str(e)
        if "NOT_FOUND" in err or "404" in err:
            return f"❌ **Model Not Found:** `{model_name}`. Run `{prefix}gemini list`."
        if "402" in err:
            return "💳 The Gemini account needs payment or credits."
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            return "⏳ Gemini's rate limit or quota was hit. Try again in a minute."
        if "503" in err:
            return "🛑 **Server Overloaded:** Google is too busy. Try again in 1 minute."
        return f"❌ Error: {box(err[:500], lang='py')}"

    def _channel_key(self, channel):
        # The Claude cog keys AI threads as THREAD_<id>; reuse that image session if one exists.
        thread_key = f"THREAD_{channel.id}"
        return thread_key if thread_key in self.image_sessions else f"CHANNEL_{channel.id}"

    # ==========================================
    #        IMAGE GENERATION (public API)
    # ==========================================

    async def generate_image(self, prompt, session_key, reply_target, *, channel, user, new=True):
        """
        Generate a new image (new=True) or refine the session's last one (new=False) and post it.

        `session_key` is the caller's conversation key (CHANNEL_/THREAD_/USER_<id>).
        Returns the posted message, or None if nothing was generated.
        Called by the Claude cog; keep this signature stable.
        """
        prefix = await self._prefix(channel.guild)
        if not await self._init_genai():
            await self._send(reply_target, channel, f"⚠️ Gemini API key not set. The bot owner can run `{prefix}gemini setkey <key>`.")
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
            reason = " ".join(texts).strip()[:1500] or "No image was returned (the request may have been blocked)."
            await self._send(reply_target, channel, f"⚠️ **Image generation failed:** {reason}")
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
            return await ctx.send(f"There's no recent image here to edit. Start one with `{ctx.clean_prefix}draw`.")
        async with ctx.typing():
            await self.generate_image(changes, key, ctx.message, channel=ctx.channel, user=ctx.author, new=False)

    @commands.group()
    async def gemini(self, ctx):
        """Gemini image generation settings."""

    @gemini.command(name="setkey")
    @checks.is_owner()
    async def set_api_key(self, ctx, key: str):
        """Set the Gemini API key (your message is deleted)."""
        await self.config.api_key.set(key)
        await ctx.send("API key set.")
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

    @gemini.command(name="list")
    async def list_models(self, ctx):
        """List the Gemini models that can generate images."""
        if not await self._init_genai():
            return await ctx.send("⚠️ API key not set.")
        async with ctx.typing():
            try:
                models = []
                async for m in await self.client.aio.models.list():
                    name = m.name.replace("models/", "")
                    if "generateContent" in (m.supported_actions or []) and "image" in name:
                        models.append(name)
            except Exception as e:
                return await ctx.send(self._error_text(e, "list", ctx.clean_prefix))
        if not models:
            return await ctx.send("No image models found.")
        msg = "**Image-capable models:**\n" + ", ".join(f"`{m}`" for m in sorted(models))
        for page in pagify(msg):
            await ctx.send(page)

    @gemini.command(name="settings")
    async def show_settings(self, ctx):
        """Show the image models used for you and this channel."""
        u_img = await self.config.user(ctx.author).image_model()
        c_img = await self.config.channel(ctx.channel).image_model()
        await ctx.send(f"**👤 Private (`{ctx.clean_prefix}myai draw …`):** `{u_img}`\n**📺 This channel:** `{c_img}`")

    @gemini.command(name="model")
    async def set_user_image_model(self, ctx, model_name: str):
        """Set the image model for your private requests. Aliases: `image`, `3image`."""
        target = self.model_aliases.get(model_name.lower(), model_name)
        await self.config.user(ctx.author).image_model.set(target)
        self.image_sessions.pop(f"USER_{ctx.author.id}", None)
        await ctx.send(f"✅ Private image model: `{target}`")

    @gemini.command(name="channelmodel")
    @checks.mod_or_permissions(manage_channels=True)
    async def set_channel_image_model(self, ctx, model_name: str):
        """Set the image model for this channel. Aliases: `image`, `3image`."""
        target = self.model_aliases.get(model_name.lower(), model_name)
        await self.config.channel(ctx.channel).image_model.set(target)
        self.image_sessions.pop(f"CHANNEL_{ctx.channel.id}", None)
        await ctx.send(f"✅ Channel image model: `{target}`")
