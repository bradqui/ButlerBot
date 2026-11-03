import discord
from google import genai
from google.genai import types
from redbot.core import commands, Config, checks
from redbot.core.utils.chat_formatting import box, pagify
import asyncio
import io
import re

class GeminiChat(commands.Cog):
    """
    Stable 5.2: Thread Typing Fix & Robust Routing.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9283748291)
        self.client = None
        self.current_api_key = None
        
        # --- CONFIGURATION ---
        default_global = {
            "api_key": None,
            "registered_threads": [],
            # Safety Defaults (Server Level)
            "safety": {
                "HARM_CATEGORY_HARASSMENT": "BLOCK_ONLY_HIGH",
                "HARM_CATEGORY_HATE_SPEECH": "BLOCK_ONLY_HIGH",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_ONLY_HIGH",
                "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_ONLY_HIGH"
            }
        }
        default_context = {
            "text_model": "gemini-2.5-flash",       
            "image_model": "gemini-2.5-flash-image" 
        }
        default_channel = {
            "text_model": "gemini-2.5-flash",
            "image_model": "gemini-2.5-flash-image",
            "safety_override": {} 
        }
        
        self.config.register_global(**default_global)
        self.config.register_user(**default_context)
        self.config.register_channel(**default_channel)
        
        self.text_sessions = {}  
        self.image_sessions = {} 

        self.model_aliases = {
            "flash": "gemini-2.5-flash",
            "image": "gemini-2.5-flash-image",
            "pro": "gemini-2.5-pro",
            "3pro": "gemini-3-pro-preview",
            "3image": "gemini-3-pro-image-preview",
            "2": "gemini-2.0-flash-exp",
        }

        self.image_new_triggers = [
            r"draw\s+.*", r"generate\s+an?\s+image.*", r"create\s+an?\s+image.*",
            r"paint\s+.*", r"image\s+of\s+.*", r"picture\s+of\s+.*"
        ]
        
        self.image_update_triggers = [
            r"update\s+image.*", r"change\s+the\s+image.*", r"add\s+.*to\s+the\s+image",
            r"make\s+it\s+.*", r"change\s+it\s+.*"
        ]

        self.strictness_levels = [
            "BLOCK_NONE", "BLOCK_ONLY_HIGH", "BLOCK_MEDIUM_AND_ABOVE", "BLOCK_LOW_AND_ABOVE"
        ]
        
        self.safety_categories = [
            "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"
        ]

    async def _get_api_key(self):
        return await self.config.api_key()

    async def _init_genai(self):
        api_key = await self._get_api_key()
        if not api_key: return None
        if self.client is None or self.current_api_key != api_key:
            self.client = genai.Client(api_key=api_key)
            self.current_api_key = api_key
            self.text_sessions = {}
            self.image_sessions = {}
        return True
    
    async def _send_reply(self, target, content=None, files=None):
        if files is None: files = []
        try:
            if hasattr(target, "reply"):
                await target.reply(content=content, files=files)
            else:
                await target.send(content=content, files=files)
        except Exception:
            if hasattr(target, "channel"):
                await target.channel.send(content=content, files=files)
            else:
                await target.send(content=content, files=files)

    # ==========================================
    #            SAFETY MANAGEMENT
    # ==========================================

    def _get_readable_category(self, cat):
        return cat.replace("HARM_CATEGORY_", "").replace("_", " ").title()

    def _get_readable_level(self, level):
        return level.replace("BLOCK_", "").replace("_", " ").title()

    @commands.group(name="geminisafety", aliases=["gsafety"])
    async def safety_cmd(self, ctx):
        """Manage Safety Settings (Server & Channel)."""
        pass

    @safety_cmd.command(name="view")
    async def view_safety(self, ctx):
        global_safety = await self.config.safety()
        channel_override = await self.config.channel(ctx.channel).safety_override()
        embed = discord.Embed(title="🛡️ Gemini Safety Settings", color=discord.Color.blue())
        embed.description = "Channel managers can only make settings **stricter** than the Server Default."
        for cat in self.safety_categories:
            g_level = global_safety.get(cat, "BLOCK_ONLY_HIGH")
            c_level = channel_override.get(cat, None)
            cat_name = self._get_readable_category(cat)
            val = f"**Server:** {self._get_readable_level(g_level)}"
            if c_level:
                val += f"\n**Channel:** {self._get_readable_level(c_level)} (Override)"
            else:
                val += "\n**Channel:** *Using Server Default*"
            embed.add_field(name=cat_name, value=val, inline=False)
        await ctx.send(embed=embed)

    @safety_cmd.command(name="server")
    @checks.admin_or_permissions(manage_guild=True)
    async def set_server_safety(self, ctx, category: str, level: str):
        cat_key = self._match_category(category)
        lvl_key = self._match_level(level)
        if not cat_key or not lvl_key: return await ctx.send("❌ Invalid Category or Level.")
        async with self.config.safety() as s: s[cat_key] = lvl_key
        self.text_sessions = {}
        self.image_sessions = {}
        await ctx.send(f"✅ Server Setting Updated: {self._get_readable_category(cat_key)} -> **{self._get_readable_level(lvl_key)}**")

    @safety_cmd.command(name="channel")
    @checks.mod_or_permissions(manage_channels=True)
    async def set_channel_safety(self, ctx, category: str, level: str):
        cat_key = self._match_category(category)
        lvl_key = self._match_level(level)
        if not cat_key or not lvl_key: return await ctx.send("❌ Invalid Category or Level.")
        global_safety = await self.config.safety()
        server_level = global_safety.get(cat_key, "BLOCK_ONLY_HIGH")
        server_idx = self.strictness_levels.index(server_level)
        new_idx = self.strictness_levels.index(lvl_key)
        if new_idx < server_idx:
            return await ctx.send("⛔ You cannot make this channel looser than the server.")
        async with self.config.channel(ctx.channel).safety_override() as s: s[cat_key] = lvl_key
        if f"CHANNEL_{ctx.channel.id}" in self.text_sessions: del self.text_sessions[f"CHANNEL_{ctx.channel.id}"]
        await ctx.send(f"✅ Channel Override Set: {self._get_readable_category(cat_key)} -> **{self._get_readable_level(lvl_key)}**")

    @safety_cmd.command(name="clear")
    @checks.mod_or_permissions(manage_channels=True)
    async def clear_channel_safety(self, ctx):
        await self.config.channel(ctx.channel).safety_override.set({})
        if f"CHANNEL_{ctx.channel.id}" in self.text_sessions: del self.text_sessions[f"CHANNEL_{ctx.channel.id}"]
        await ctx.send("✅ Channel overrides cleared.")

    def _match_category(self, user_input):
        user_input = user_input.lower()
        if "harass" in user_input: return "HARM_CATEGORY_HARASSMENT"
        if "hate" in user_input: return "HARM_CATEGORY_HATE_SPEECH"
        if "sex" in user_input: return "HARM_CATEGORY_SEXUALLY_EXPLICIT"
        if "danger" in user_input: return "HARM_CATEGORY_DANGEROUS_CONTENT"
        return None

    def _match_level(self, user_input):
        user_input = user_input.lower()
        if "none" in user_input: return "BLOCK_NONE"
        if "high" in user_input: return "BLOCK_ONLY_HIGH"
        if "med" in user_input: return "BLOCK_MEDIUM_AND_ABOVE"
        if "low" in user_input: return "BLOCK_LOW_AND_ABOVE" 
        return None

    async def _get_compiled_safety(self, channel):
        server_safe = await self.config.safety()
        chan_safe = await self.config.channel(channel).safety_override()
        final_safety = []
        for cat in self.safety_categories:
            lvl = server_safe.get(cat, "BLOCK_ONLY_HIGH")
            if cat in chan_safe: lvl = chan_safe[cat]
            final_safety.append({"category": cat, "threshold": lvl})
        return final_safety

    # ==========================================
    #             THREAD MANAGEMENT
    # ==========================================

    @commands.command(name="aithread")
    @commands.guild_only()
    async def create_ai_thread(self, ctx, *, prompt: str):
        if not await self._init_genai(): return await ctx.send("⚠️ API key not set.")

        async with ctx.typing():
            text_model = await self.config.channel(ctx.channel).text_model()
            topic_title = "AI Conversation"
            try:
                safety = [{"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"}]
                title_prompt = f"Summarize this into a short title (4-6 words). No quotes:\n\n{prompt}"
                response = self.client.models.generate_content(
                    model=text_model, 
                    contents=title_prompt,
                    config=types.GenerateContentConfig(tools=None, safety_settings=safety)
                )
                if response.text:
                    topic_title = response.text.strip().replace("*", "").replace('"', '')
                    if len(topic_title) > 90: topic_title = topic_title[:87] + "..." 
            except Exception:
                topic_title = prompt[:30] + "..."

            try:
                name = f"🤖 {topic_title}"
                thread = await ctx.message.create_thread(name=name, auto_archive_duration=60)
                async with self.config.registered_threads() as threads:
                    if thread.id not in threads: threads.append(thread.id)
                
                image_model = await self.config.channel(ctx.channel).image_model()
                session_key = f"THREAD_{thread.id}"
                
                await self._process_request(thread, prompt, session_key, text_model, image_model, reply_target=thread)

            except Exception as e:
                await ctx.send(f"❌ Could not create thread: {box(str(e), lang='py')}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        registered = await self.config.registered_threads()
        if message.channel.id not in registered: return

        is_mention = self.bot.user in message.mentions
        is_reply = (message.reference and message.reference.resolved and 
                    message.reference.resolved.author == self.bot.user)

        if not (is_mention or is_reply): return
        if not await self._init_genai(): return

        parent_channel = message.channel.parent
        text_model = await self.config.channel(parent_channel).text_model()
        image_model = await self.config.channel(parent_channel).image_model()
        
        clean_prompt = message.content.replace(self.bot.user.mention, "").strip()
        if not clean_prompt: return 

        await self._process_request(parent_channel, clean_prompt, f"THREAD_{message.channel.id}", text_model, image_model, reply_target=message)

    # ==========================================
    #            STANDARD COMMANDS
    # ==========================================

    @commands.group(name="ai", aliases=["chat", "ask", "g"], invoke_without_command=True)
    @commands.cooldown(1, 3, commands.BucketType.channel)
    async def shared_chat(self, ctx, *, prompt: str = None):
        if prompt is None: return await ctx.send_help()
        text_model = await self.config.channel(ctx.channel).text_model()
        image_model = await self.config.channel(ctx.channel).image_model()
        session_key = f"CHANNEL_{ctx.channel.id}"
        await self._process_request(ctx.channel, prompt, session_key, text_model, image_model, reply_target=ctx)

    @shared_chat.command(name="updateimage")
    async def ai_update_image(self, ctx, *, prompt: str):
        image_model = await self.config.channel(ctx.channel).image_model()
        session_key = f"CHANNEL_{ctx.channel.id}"
        await self._generate_image_response(ctx.channel, prompt, session_key, image_model, reply_target=ctx)

    @shared_chat.command(name="reset")
    async def reset_channel_context(self, ctx):
        if not ctx.author.guild_permissions.manage_channels: return await ctx.send("⛔ Permission denied.")
        self._clear_session(f"CHANNEL_{ctx.channel.id}")
        await ctx.send("🧹 **Shared Channel Context** wiped.")

    @commands.group(name="myai", invoke_without_command=True)
    async def private_chat(self, ctx, *, prompt: str = None):
        if prompt is None: return await ctx.send_help()
        text_model = await self.config.user(ctx.author).text_model()
        image_model = await self.config.user(ctx.author).image_model()
        session_key = f"USER_{ctx.author.id}"
        await self._process_request(ctx.channel, prompt, session_key, text_model, image_model, reply_target=ctx)

    @private_chat.command(name="updateimage")
    async def myai_update_image(self, ctx, *, prompt: str):
        image_model = await self.config.user(ctx.author).image_model()
        session_key = f"USER_{ctx.author.id}"
        await self._generate_image_response(ctx.channel, prompt, session_key, image_model, reply_target=ctx)

    @private_chat.command(name="reset")
    async def reset_private_context(self, ctx):
        self._clear_session(f"USER_{ctx.author.id}")
        await ctx.send("🧹 **Your Private Context** wiped.")

    # ==========================================
    #            CORE LOGIC
    # ==========================================

    async def _process_request(self, ctx_channel, prompt, session_key, text_model, image_model, reply_target):
        if not await self._init_genai(): return

        # FIX: Check if reply_target is a thread or a message/context
        typing_target = reply_target.channel if hasattr(reply_target, "channel") else reply_target

        async with typing_target.typing():
            is_new_image = any(re.search(p, prompt.lower()) for p in self.image_new_triggers)
            is_update_image = any(re.search(p, prompt.lower()) for p in self.image_update_triggers)
            
            if is_new_image:
                if session_key in self.image_sessions: del self.image_sessions[session_key]
                await self._generate_image_response(ctx_channel, prompt, session_key, image_model, reply_target)
            elif is_update_image and session_key in self.image_sessions:
                await self._generate_image_response(ctx_channel, prompt, session_key, image_model, reply_target)
            else:
                await self._generate_text_response(ctx_channel, prompt, session_key, text_model, reply_target)

    async def _generate_text_response(self, ctx_channel, prompt, session_key, model_name, reply_target):
        try:
            if session_key not in self.text_sessions:
                await self._rebuild_text_session(ctx_channel, session_key, model_name)

            chat_session = self.text_sessions[session_key]
            try:
                response = chat_session.send_message(prompt)
            except Exception as e:
                if "400" in str(e):
                     await self._rebuild_text_session(ctx_channel, session_key, model_name, force_empty=True)
                     chat_session = self.text_sessions[session_key]
                     response = chat_session.send_message(prompt)
                else: raise e

            text_out = ""
            sources_text = ""
            content = response.candidates[0].content if hasattr(response, 'candidates') else response

            if hasattr(content, "parts") and content.parts:
                for part in content.parts:
                    if hasattr(part, "text") and part.text: text_out += part.text
            if not text_out and hasattr(content, "text") and content.text: text_out = content.text

            show_sources = re.search(r"cite|source|reference|where did|link", prompt.lower())
            if show_sources and hasattr(response, "candidates") and response.candidates:
                for candidate in response.candidates:
                    if (hasattr(candidate, "grounding_metadata") and 
                        candidate.grounding_metadata and 
                        candidate.grounding_metadata.grounding_chunks):
                        sources_text = "\n\n**🔍 Sources:**"
                        unique_links = set()
                        for chunk in candidate.grounding_metadata.grounding_chunks:
                            if hasattr(chunk, "web") and chunk.web.uri:
                                title = chunk.web.title if chunk.web.title else "Source"
                                if chunk.web.uri not in unique_links:
                                    sources_text += f"\n- [{title}](<{chunk.web.uri}>)"
                                    unique_links.add(chunk.web.uri)
            if sources_text: text_out += sources_text

            if not text_out:
                finish = response.candidates[0].finish_reason if hasattr(response, 'candidates') else "UNKNOWN"
                await self._send_reply(reply_target, content=f"😶 No text. Reason: {finish}")
                return

            for page in pagify(text_out):
                await self._send_reply(reply_target, content=page)

        except Exception as e:
            await self._handle_error(reply_target, e, model_name, session_key)

    async def _generate_image_response(self, ctx_channel, prompt, session_key, model_name, reply_target):
        try:
            if session_key not in self.image_sessions:
                config = types.GenerateContentConfig(tools=None)
                chat = self.client.chats.create(model=model_name, config=config)
                self.image_sessions[session_key] = chat

            chat_session = self.image_sessions[session_key]
            response = chat_session.send_message(prompt)

            files = []
            content = response.candidates[0].content if hasattr(response, 'candidates') else response
            if hasattr(content, "parts") and content.parts:
                for part in content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        data = part.inline_data.data
                        ext = "jpg" if "jpeg" in part.inline_data.mime_type else "png"
                        files.append(discord.File(io.BytesIO(data), f"generated.{ext}"))

            if files:
                await self._send_reply(reply_target, content=f"🎨 **{model_name}:** {prompt[:50]}...", files=files)
            else:
                text = ""
                if hasattr(content, "text") and content.text: text = content.text
                await self._send_reply(reply_target, content=f"⚠️ **Generation Failed:** {text}")

        except Exception as e:
            await self._handle_error(reply_target, e, model_name, session_key)

    async def _rebuild_text_session(self, ctx_channel, session_key, model_name, force_empty=False):
        history_list = []
        if not force_empty and hasattr(ctx_channel, "history"):
            try:
                async for msg in ctx_channel.history(limit=15):
                    if msg.author.bot and msg.author != self.bot.user: continue
                    role = "model" if msg.author == self.bot.user else "user"
                    if msg.content:
                        history_list.append(types.Content(role=role, parts=[types.Part(text=msg.content)]))
                history_list.reverse()
            except: pass

        safety = await self._get_compiled_safety(ctx_channel)
        tools_config = [{'google_search': {}}]
        if "image" in model_name or "3-pro" in model_name: tools_config = None
        config = types.GenerateContentConfig(tools=tools_config, safety_settings=safety)
        chat = self.client.chats.create(model=model_name, config=config, history=history_list)
        self.text_sessions[session_key] = chat

    def _clear_session(self, session_key):
        if session_key in self.text_sessions: del self.text_sessions[session_key]
        if session_key in self.image_sessions: del self.image_sessions[session_key]

    async def _handle_error(self, ctx, e, model_name, session_key):
        err = str(e)
        msg = f"❌ Error: {box(err, lang='py')}"
        if "NOT_FOUND" in err or "404" in err: msg = f"❌ **Model Not Found:** `{model_name}`. Run `[p]gemini list`."
        elif "INVALID_ARGUMENT" in err or "400" in err:
            self._clear_session(session_key)
            msg = f"⚠️ **Config Error:** `{model_name}` rejected the request. Memory reset."
        elif "token" in err.lower():
             self._clear_session(session_key)
             msg = "⚠️ Context limit. Memory reset."
        elif "503" in err: msg = "🛑 **Server Overloaded:** Google is too busy. Try again in 1 minute."
        await self._send_reply(ctx, content=msg)

    # --- CONFIGURATION (Keep Existing) ---
    @commands.group()
    async def gemini(self, ctx): pass
    
    @gemini.command(name="setkey")
    @checks.is_owner()
    async def set_api_key(self, ctx, key: str):
        await self.config.api_key.set(key)
        await ctx.send("API key set.")
        try: await ctx.message.delete()
        except: pass

    @gemini.command(name="list")
    async def list_models(self, ctx):
        if not await self._init_genai(): return await ctx.send("⚠️ API key not set.")
        async with ctx.typing():
            try:
                models = []
                models_response = self.client.models.list()
                for m in models_response:
                    if 'generateContent' in m.supported_actions:
                        models.append(m.name.replace("models/", ""))
                if not models: return await ctx.send("No models found.")
                models.sort()
                msg = "**API Supported Models:**\n" + ", ".join([f"`{m}`" for m in models])
                for page in pagify(msg): await ctx.send(page)
            except Exception as e: await ctx.send(f"❌ Error: {str(e)}")

    @gemini.command(name="settings")
    async def show_settings(self, ctx):
        u_text = await self.config.user(ctx.author).text_model()
        u_img = await self.config.user(ctx.author).image_model()
        c_text = await self.config.channel(ctx.channel).text_model()
        c_img = await self.config.channel(ctx.channel).image_model()
        msg = (f"**👤 Private:** Text=`{u_text}`, Image=`{u_img}`\n**📺 Channel:** Text=`{c_text}`, Image=`{c_img}`")
        await ctx.send(msg)
        
    @gemini.group(name="model")
    async def user_model_config(self, ctx): pass

    @user_model_config.command(name="text")
    async def set_user_text_model(self, ctx, model_name: str):
        model_name = model_name.lower()
        target = self.model_aliases.get(model_name, model_name)
        await self.config.user(ctx.author).text_model.set(target)
        self._clear_session(f"USER_{ctx.author.id}")
        await ctx.send(f"✅ Private Text model: `{target}`")

    @user_model_config.command(name="image")
    async def set_user_image_model(self, ctx, model_name: str):
        model_name = model_name.lower()
        target = self.model_aliases.get(model_name, model_name)
        await self.config.user(ctx.author).image_model.set(target)
        self._clear_session(f"USER_{ctx.author.id}")
        await ctx.send(f"✅ Private Image model: `{target}`")

    @gemini.group(name="channelmodel")
    @checks.mod_or_permissions(manage_channels=True)
    async def channel_model_config(self, ctx): pass

    @channel_model_config.command(name="text")
    async def set_channel_text_model(self, ctx, model_name: str):
        model_name = model_name.lower()
        target = self.model_aliases.get(model_name, model_name)
        await self.config.channel(ctx.channel).text_model.set(target)
        self._clear_session(f"CHANNEL_{ctx.channel.id}")
        await ctx.send(f"✅ Channel Text model: `{target}`")

    @channel_model_config.command(name="image")
    async def set_channel_image_model(self, ctx, model_name: str):
        model_name = model_name.lower()
        target = self.model_aliases.get(model_name, model_name)
        await self.config.channel(ctx.channel).image_model.set(target)
        self._clear_session(f"CHANNEL_{ctx.channel.id}")
        await ctx.send(f"✅ Channel Image model: `{target}`")

def setup(bot): pass