import discord
from redbot.core import commands, Config, checks
from discord.ui import View, Button, Modal, TextInput
import traceback

# --- Helper: Shared Rules Trigger ---
async def launch_rules_view(interaction, rules_config, bot, guild_config, user):
    """
    Shared function to transition from Alliance Selection -> Rules Agreement.
    Used by: RoleButton, CustomAllianceModal, and NoAllianceButton.
    """
    # 1. Delete the previous interaction message (The Greeter View)
    try:
        await interaction.message.delete()
    except Exception:
        pass # Message might already be deleted or ephemeral

    # 2. Prepare Rules View
    rules_role_id = rules_config.get("rules_role")
    rules_channel_id = rules_config.get("rules_channel")
    
    if rules_role_id:
        rules_channel_mention = f"<#{rules_channel_id}>" if rules_channel_id else "#rules"
        
        embed = discord.Embed(
            title="Protocol Agreement",
            description=f"Identity accepted. Now, do you agree to the rules listed in {rules_channel_mention}?",
            color=discord.Color.orange()
        )
        
        new_view = RulesView(user, rules_role_id, bot, guild_config)
        
        try:
            # We use interaction.channel.send because the previous message was deleted
            await interaction.channel.send(content=user.mention, embed=embed, view=new_view)
        except Exception as e:
            print(f"Failed to send rules view: {e}")

# --- Configurable Mod Check ---
async def has_mod_role(ctx):
    """
    Custom check: Returns True if the user is an Administrator 
    OR has a role ID listed in the 'mod_roles' config.
    """
    if ctx.author.guild_permissions.administrator:
        return True
    
    cog = ctx.bot.get_cog("ButtonGreeter")
    if not cog:
        return False
        
    allowed_ids = await cog.config.guild(ctx.guild).mod_roles()
    if not allowed_ids:
        return False
    
    user_role_ids = [r.id for r in ctx.author.roles]
    return any(mid in user_role_ids for mid in allowed_ids)


class ErrorLoggingView(View):
    """Base View class that adds error logging capabilities."""
    def __init__(self, bot, guild_config, timeout=None):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild_config = guild_config

    async def log_error(self, interaction: discord.Interaction, error_message: str):
        admin_channel_id = await self.guild_config.admin_channel()
        if admin_channel_id:
            channel = interaction.guild.get_channel(admin_channel_id)
            if channel:
                try:
                    await channel.send(f"⚠️ **Error in ButtonGreeter:**\n{error_message}\n**User:** {interaction.user} ({interaction.user.id})")
                except discord.Forbidden:
                    pass 
                except Exception as e:
                    print(f"Failed to log to admin channel: {e}")

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        await self.log_error(interaction, f"View Interaction Error:\n```py\n{tb[:1900]}```")


# --- Modal: Custom Alliance Input ---
class CustomAllianceModal(Modal):
    def __init__(self, rules_config, bot, guild_config, greeter_view_interaction):
        super().__init__(title="Custom Alliance Details")
        self.rules_config = rules_config
        self.bot = bot
        self.guild_config = guild_config
        # We store the interaction from the button click to delete the message later
        self.greeter_view_interaction = greeter_view_interaction

    tag = TextInput(
        label="Alliance Tag",
        placeholder="Enter just the tag (e.g. KVK)",
        min_length=1,
        max_length=5,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        # 1. Update Nickname
        custom_tag = self.tag.value.upper()
        current_name = interaction.user.display_name
        
        # Clean existing tags if present
        if "]" in current_name:
            clean_name = current_name.split("]", 1)[1].strip()
        else:
            clean_name = current_name

        new_nickname = f"[{custom_tag}] {clean_name}"
        
        # Truncate to Discord limit
        if len(new_nickname) > 32: 
            new_nickname = new_nickname[:32]

        try:
            await interaction.user.edit(nick=new_nickname)
            await interaction.response.send_message(f"Nickname updated to **{new_nickname}**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(f"Noted custom alliance **{custom_tag}** (Could not update nick due to permissions).", ephemeral=True)
        except Exception as e:
             await interaction.response.send_message("Error updating nickname, but proceeding.", ephemeral=True)

        # 2. Trigger Rules View
        # We pass the ORIGINAL button interaction to delete the menu, 
        # but we use the current modal interaction for context.
        await launch_rules_view(self.greeter_view_interaction, self.rules_config, self.bot, self.guild_config, interaction.user)


# --- View 3: Rules Agreement ---
class RulesView(ErrorLoggingView):
    def __init__(self, target_member, rules_role_id, bot, guild_config):
        super().__init__(bot, guild_config, timeout=None)
        self.target_member = target_member
        self.rules_role_id = rules_role_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.target_member:
            await interaction.response.send_message("These buttons are not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Yes, I Agree", style=discord.ButtonStyle.success)
    async def agree_button(self, interaction: discord.Interaction, button: Button):
        role = interaction.guild.get_role(self.rules_role_id)
        if role:
            try:
                await interaction.user.add_roles(role)
                await interaction.response.send_message(f"You have accepted the rules and received the **{role.name}** role.", ephemeral=True)
            except discord.Forbidden:
                msg = "Error: I do not have permission to assign the Rules role."
                await interaction.response.send_message(msg, ephemeral=True)
                await self.log_error(interaction, msg)
                return
            except Exception as e:
                await self.log_error(interaction, f"Unexpected error adding rules role: {e}")
                return
        else:
            msg = "Configuration Error: The Rules role no longer exists."
            await interaction.response.send_message(msg, ephemeral=True)
            await self.log_error(interaction, msg)
            return
        
        try:
            await interaction.message.delete()
        except Exception as e:
            await self.log_error(interaction, f"Failed to delete rules message: {e}")
        self.stop()

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def disagree_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("You declined the rules.", ephemeral=True)
        try:
            await interaction.message.delete()
        except Exception as e:
            await self.log_error(interaction, f"Failed to delete rules message on decline: {e}")
        self.stop()


# --- View 2: Role/Alliance Selection ---
class GreeterView(ErrorLoggingView):
    def __init__(self, target_member, roles_config, rules_config, bot, guild_config):
        super().__init__(bot, guild_config, timeout=None)
        self.target_member = target_member
        self.roles_config = roles_config
        self.rules_config = rules_config
        
        # 1. Add Configured Role Buttons
        for label, role_id in roles_config.items():
            self.add_item(RoleButton(label, role_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.target_member:
            await interaction.response.send_message("This menu is not for you.", ephemeral=True)
            return False
        return True

    # 2. Add Fixed "Custom Alliance" Button
    @discord.ui.button(label="Custom Alliance", style=discord.ButtonStyle.secondary, emoji="🛡️", row=4)
    async def custom_alliance(self, interaction: discord.Interaction, button: Button):
        # Open Modal
        modal = CustomAllianceModal(self.rules_config, self.bot, self.guild_config, interaction)
        await interaction.response.send_modal(modal)

    # 3. Add Fixed "No Alliance" Button
    @discord.ui.button(label="No Alliance", style=discord.ButtonStyle.secondary, emoji="👋", row=4)
    async def no_alliance(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("You selected **No Alliance**. Proceeding...", ephemeral=True)
        # Skip roles/nick, go straight to rules
        await launch_rules_view(interaction, self.rules_config, self.bot, self.guild_config, interaction.user)


class RoleButton(Button):
    def __init__(self, label: str, role_id: int):
        super().__init__(style=discord.ButtonStyle.primary, label=label)
        self.role_id = role_id
        self.role_label = label

    async def callback(self, interaction: discord.Interaction):
        view: GreeterView = self.view
        
        role = interaction.guild.get_role(self.role_id)
        if not role:
            msg = f"Configuration Error: Role ID {self.role_id} for label '{self.role_label}' no longer exists."
            await interaction.response.send_message("Configuration Error: This role no longer exists.", ephemeral=True)
            await view.log_error(interaction, msg)
            return

        # 1. Assign Role
        try:
            await interaction.user.add_roles(role)
        except discord.Forbidden:
            msg = f"Permission Error: I cannot assign role '{role.name}'."
            await interaction.response.send_message("Permission Error: I cannot assign roles. Please contact an admin.", ephemeral=True)
            await view.log_error(interaction, msg)
            return
        except Exception as e:
            await view.log_error(interaction, f"Unexpected error assigning role '{role.name}': {e}")
            return

        # 2. Update Nickname
        tag = f"[{self.role_label}]"
        current_name = interaction.user.display_name
        
        if not current_name.startswith("["):
            new_nick = f"{tag} {current_name}"
            if len(new_nick) > 32: new_nick = new_nick[:32]
            try:
                await interaction.user.edit(nick=new_nick)
            except discord.Forbidden:
                await view.log_error(interaction, f"Warning: Could not update nickname for {interaction.user.name} (Permission/Hierarchy issue).")
            except Exception as e:
                await view.log_error(interaction, f"Unexpected error updating nickname: {e}")

        # 3. Trigger Shared Rules Logic
        await interaction.response.defer() # Defer to prevent "Interaction failed" while processing
        await launch_rules_view(interaction, view.rules_config, view.bot, view.guild_config, interaction.user)


# --- Main Cog ---
class ButtonGreeter(commands.Cog):
    """
    A welcome system that greets users with buttons to self-assign a role/nickname, 
    followed by a mandatory rules agreement check.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8473829102)
        
        default_guild = {
            "welcome_channel": None,
            "rules_channel": None,
            "admin_channel": None,
            "rules_role": None,
            "mod_roles": [],
            "roles": {} 
        }
        self.config.register_guild(**default_guild)

    async def log_cog_error(self, guild, message):
        if not guild: return
        admin_channel_id = await self.config.guild(guild).admin_channel()
        if admin_channel_id:
            channel = guild.get_channel(admin_channel_id)
            if channel:
                try:
                    await channel.send(f"⚠️ **Command Error in ButtonGreeter:**\n{message}")
                except:
                    pass

    # --- Configuration Commands ---
    @commands.group(aliases=["bg"])
    @checks.admin_or_permissions(manage_roles=True)
    async def buttongreeter(self, ctx):
        """Admin configuration commands for the Welcome/Role system."""
        pass

    @buttongreeter.command(name="settings")
    async def show_settings(self, ctx):
        """Show the current configuration for channels, roles, and buttons."""
        data = await self.config.guild(ctx.guild).all()
        
        wc = f"<#{data['welcome_channel']}>" if data['welcome_channel'] else "**Not Set**"
        rc = f"<#{data['rules_channel']}>" if data['rules_channel'] else "**Not Set**"
        ac = f"<#{data['admin_channel']}>" if data['admin_channel'] else "**Not Set**" 
        
        rr_id = data['rules_role']
        if rr_id:
            rr_obj = ctx.guild.get_role(rr_id)
            rr_text = rr_obj.mention if rr_obj else "Deleted Role"
        else:
            rr_text = "**Not Set**"
        
        mod_roles_list = data.get("mod_roles", [])
        if mod_roles_list:
            mod_text_list = []
            for rid in mod_roles_list:
                r_obj = ctx.guild.get_role(rid)
                mod_text_list.append(r_obj.mention if r_obj else f"Deleted Role ({rid})")
            mod_roles_text = ", ".join(mod_text_list)
        else:
            mod_roles_text = "None (Only Admins)"

        roles_text = ""
        if data['roles']:
            for label, rid in data['roles'].items():
                r_obj = ctx.guild.get_role(rid)
                r_name = r_obj.name if r_obj else "Deleted Role"
                roles_text += f"🔘 **[{label}]** assigns role: `@{r_name}`\n"
        else:
            roles_text = "No buttons configured."

        embed = discord.Embed(title="ButtonGreeter Configuration", color=discord.Color.blue())
        embed.add_field(name="📍 Locations", value=f"**Welcome Channel:** {wc}\n**Rules Channel:** {rc}\n**Admin Log Channel:** {ac}", inline=False)
        embed.add_field(name="🛡️ Permissions", value=f"**Rules Role:** {rr_text}\n**Authorized Mod Roles:** {mod_roles_text}", inline=False)
        embed.add_field(name="🏷️ Assignable Role Buttons", value=roles_text, inline=False)
        embed.add_field(name="ℹ️ Built-in Options", value="🛡️ **Custom Alliance** (Modal Input)\n👋 **No Alliance** (Skip Role)", inline=False)
        
        await ctx.send(embed=embed)

    @buttongreeter.command()
    async def addmodrole(self, ctx, role: discord.Role):
        """Authorize a role to use the 'forceclass' and 'forcerulesremove' commands."""
        async with self.config.guild(ctx.guild).mod_roles() as mod_roles:
            if role.id in mod_roles:
                await ctx.send(f"⚠️ **{role.name}** is already in the list.")
                return
            mod_roles.append(role.id)
        await ctx.send(f"✅ Added **{role.name}** to Authorized Mod Roles.")

    @buttongreeter.command()
    async def removemodrole(self, ctx, role: discord.Role):
        """Remove a role's authorization to use force commands."""
        async with self.config.guild(ctx.guild).mod_roles() as mod_roles:
            if role.id not in mod_roles:
                await ctx.send(f"⚠️ **{role.name}** was not in the list.")
                return
            mod_roles.remove(role.id)
        await ctx.send(f"✅ Removed **{role.name}** from Authorized Mod Roles.")

    @buttongreeter.command()
    async def setchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel where new members are greeted."""
        await self.config.guild(ctx.guild).welcome_channel.set(channel.id)
        await ctx.send(f"✅ Welcome messages will now be sent to {channel.mention}.")

    @buttongreeter.command()
    async def setruleschannel(self, ctx, channel: discord.TextChannel):
        """Set the channel that contains your server rules."""
        await self.config.guild(ctx.guild).rules_channel.set(channel.id)
        await ctx.send(f"✅ Rules channel set to {channel.mention}.")

    @buttongreeter.command()
    async def setadminchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel where error logs should be sent."""
        await self.config.guild(ctx.guild).admin_channel.set(channel.id)
        await ctx.send(f"✅ Error logs will now be sent to {channel.mention}.")

    @buttongreeter.command()
    async def setrulesrole(self, ctx, role: discord.Role):
        """Set the role given to a user when they click 'Yes' to accept rules."""
        await self.config.guild(ctx.guild).rules_role.set(role.id)
        await ctx.send(f"✅ Users who agree to rules will receive the **{role.name}** role.")

    @buttongreeter.command()
    async def addrole(self, ctx, role: discord.Role, *, button_label: str):
        """Add a button to the welcome message that assigns a specific role."""
        if role >= ctx.guild.me.top_role:
            await ctx.send("❌ Error: That role is higher than or equal to my highest role. I cannot assign it.")
            await self.log_cog_error(ctx.guild, f"Admin tried to add role '{role.name}' which is too high in hierarchy.")
            return

        async with self.config.guild(ctx.guild).roles() as roles:
            if len(roles) >= 18: # Lowered slightly to make room for fixed buttons
                await ctx.send("❌ Error: Maximum of 18 buttons allowed.")
                return
            roles[button_label] = role.id
        
        await ctx.send(f"✅ Added button **[{button_label}]** which assigns **{role.name}**.")

    @buttongreeter.command()
    async def removerole(self, ctx, *, button_label: str):
        """Remove a button from the configuration."""
        async with self.config.guild(ctx.guild).roles() as roles:
            if button_label in roles:
                del roles[button_label]
                await ctx.send(f"✅ Removed button **[{button_label}]**.")
            else:
                await ctx.send("❌ Error: Could not find a button with that label. Use `[p]bg settings` to see list.")

    # --- User Commands ---
    @commands.command()
    async def changerole(self, ctx, *, exact_label: str):
        """Self-service command to change your role if you clicked the wrong button."""
        roles_data = await self.config.guild(ctx.guild).roles()
        
        if exact_label not in roles_data:
            await ctx.send("❌ That is not a valid role option. Please check spelling.")
            return
        
        target_role_id = roles_data[exact_label]
        target_role = ctx.guild.get_role(target_role_id)
        
        if not target_role:
            msg = f"User tried to switch to label '{exact_label}', but the role ID {target_role_id} is missing."
            await ctx.send("❌ The configured role for that label no longer exists.")
            await self.log_cog_error(ctx.guild, msg)
            return

        to_remove = []
        old_label = None
        
        for label, rid in roles_data.items():
            user_has = ctx.guild.get_role(rid)
            if user_has and user_has in ctx.author.roles:
                to_remove.append(user_has)
                old_label = label

        try:
            if to_remove:
                await ctx.author.remove_roles(*to_remove)
            await ctx.author.add_roles(target_role)
        except discord.Forbidden:
            msg = f"Failed to change roles for {ctx.author}. Missing permissions."
            await ctx.send("❌ Permission Error: I don't have permission to modify your roles.")
            await self.log_cog_error(ctx.guild, msg)
            return

        current_nick = ctx.author.display_name
        new_nick = current_nick
        
        if old_label and f"[{old_label}]" in current_nick:
            new_nick = current_nick.replace(f"[{old_label}]", f"[{exact_label}]")
        elif not current_nick.startswith("["):
             new_nick = f"[{exact_label}] {current_nick}"
        
        if len(new_nick) > 32: new_nick = new_nick[:32]

        if new_nick != current_nick:
            try:
                await ctx.author.edit(nick=new_nick)
            except discord.Forbidden:
                await ctx.send(f"✅ Role changed to **{target_role.name}**, but I couldn't update your nickname.")
                await self.log_cog_error(ctx.guild, f"Changed role for {ctx.author}, but failed to update nick (Permission/Hierarchy).")
                return

        await ctx.send(f"✅ Role updated to **{target_role.name}** and nickname adjusted.")

    # --- R4 / R5 Commands ---
    @commands.command()
    @commands.check(has_mod_role)
    async def forceclass(self, ctx, member: discord.Member, *, exact_label: str):
        """(Authorized Mod Roles Only) Force assign a specific class role to a user."""
        roles_data = await self.config.guild(ctx.guild).roles()
        if exact_label not in roles_data:
            await ctx.send("❌ Invalid Label. Use `[p]bg settings` to see valid options.")
            return

        target_role = ctx.guild.get_role(roles_data[exact_label])
        if not target_role:
            await ctx.send("❌ That role is invalid/deleted.")
            return
        
        to_remove = []
        old_label = None
        for label, rid in roles_data.items():
            r = ctx.guild.get_role(rid)
            if r and r in member.roles:
                to_remove.append(r)
                old_label = label

        try:
            if to_remove: await member.remove_roles(*to_remove)
            await member.add_roles(target_role)
        except discord.Forbidden:
            await ctx.send("❌ Permission error.")
            await self.log_cog_error(ctx.guild, f"Mod {ctx.author} tried to forceclass {member} but bot lacks permissions.")
            return

        current = member.display_name
        new_n = current
        if old_label and f"[{old_label}]" in current:
            new_n = current.replace(f"[{old_label}]", f"[{exact_label}]")
        elif not current.startswith("["):
            new_n = f"[{exact_label}] {current}"
            
        if len(new_n) > 32: new_n = new_n[:32]
        
        try:
            await member.edit(nick=new_n)
            await ctx.send(f"✅ Forced **{member.name}** to **{target_role.name}** and updated nick.")
        except:
            await ctx.send(f"✅ Role changed for **{member.name}**, but could not edit nick.")
            await self.log_cog_error(ctx.guild, f"Mod {ctx.author} forced class on {member}, but bot failed to edit nick.")

    @commands.command()
    @commands.check(has_mod_role)
    async def forcerulesremove(self, ctx, member: discord.Member):
        """(Authorized Mod Roles Only) Remove the 'Rules Agreed' role from a user."""
        rid = await self.config.guild(ctx.guild).rules_role()
        if not rid:
            await ctx.send("❌ Rules role not configured.")
            return
        
        role = ctx.guild.get_role(rid)
        if role and role in member.roles:
            try:
                await member.remove_roles(role)
                await ctx.send(f"✅ Removed **{role.name}** from {member.mention}.")
            except discord.Forbidden:
                await ctx.send("❌ Permission error.")
                await self.log_cog_error(ctx.guild, f"Mod {ctx.author} tried to remove rules role from {member} but failed (Permissions).")
        else:
            await ctx.send("❌ User does not have the rules role or role not found.")

    # --- Event Listener ---
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Listens for new members and sends the greeting."""
        data = await self.config.guild(member.guild).all()
        channel_id = data["welcome_channel"]
        roles_config = data["roles"]

        # Pass guild config object to views so they can fetch admin channel
        guild_config = self.config.guild(member.guild)

        if not channel_id or not roles_config: return
        channel = member.guild.get_channel(channel_id)
        if not channel:
            await self.log_cog_error(member.guild, f"Welcome channel ID {channel_id} not found. Could not greet {member.name}.")
            return

        # Prepare Config for Rules to pass to View
        rules_conf = {
            "rules_role": data["rules_role"],
            "rules_channel": data["rules_channel"]
        }

        view = GreeterView(member, roles_config, rules_conf, self.bot, guild_config)
        
        embed = discord.Embed(
            title=f"Welcome to {member.guild.name}",
            description="Select your Identity below to proceed.",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        try:
            await channel.send(member.mention, embed=embed, view=view)
        except discord.Forbidden:
            await self.log_cog_error(member.guild, f"Failed to send welcome message to {channel.mention} (Permission Denied).")