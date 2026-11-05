"""
ButtonGreeter cog for Red-DiscordBot.

The welcome flow: a new member picks their group (alliance) with a button, which gives them its role and tags their
nickname `[TAG] Name`, then agrees to the rules and gets the rules role.

The buttons are persistent (discord.py dynamic items), so welcome and rules messages keep working after a restart or
reload. Each custom ID carries the member it's for:
- `bg:role:<role_id>:<member_id>`: a configured group button
- `bg:custom:<member_id>`: type your own alliance tag
- `bg:none:<member_id>`: no alliance
- `bg:rules:yes|no:<member_id>`: the rules agreement

Buttons read the server's settings when they're clicked. Problems are answered privately to the member and reported
in the admin channel.

The welcome and rules messages are cards (Components V2) with the buttons inside. Older ones are embed messages; the
handlers only ever delete them, which works the same for both.
"""

import importlib.util
import logging
import re
import sys
from pathlib import Path
from typing import Optional

import discord
from redbot.core import Config, checks, commands


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
log = logging.getLogger("red.buttongreeter")


# ==========================================
#                CONSTANTS
# ==========================================

MAX_ROLE_BUTTONS = 18           # four rows of role buttons, plus the two built-in ones
MAX_NICK = 32                   # Discord's nickname limit
TOLD = "A moderator has been told."
NOT_YOURS = "🔒 These buttons are only for the member this message welcomes."
SOMETHING_WRONG = "❌ Something went wrong on my side.\n-# A moderator has been told."
TAG_RE = re.compile(r"^\s*\[[^\]]*\]\s*")


# ==========================================
#                 HELPERS
# ==========================================

def tagged_nick(name: str, tag: str) -> str:
    """`[TAG] Name`: any existing leading [tag] is replaced, and the result fits Discord's 32 characters."""
    base = TAG_RE.sub("", name).strip() or name.strip()
    return f"[{tag}] {base}"[:MAX_NICK]


def clean_tag(text: str) -> str:
    """What someone typed as their alliance tag, without brackets, in capitals."""
    return text.strip().strip("[]").strip().upper()


async def has_mod_role(ctx: commands.Context) -> bool:
    """Administrators, or anyone with a role from `[p]bg addmodrole`."""
    if ctx.guild is None:
        return False
    if ctx.author.guild_permissions.administrator:
        return True
    cog = ctx.bot.get_cog("ButtonGreeter")
    allowed_ids = await cog.config.guild(ctx.guild).mod_roles() if cog else []
    if any(role.id in allowed_ids for role in ctx.author.roles):
        return True
    raise commands.UserFeedbackCheckFailure("🔒 Only admins and the welcome mod roles can do that.")


# ==========================================
#     PERSISTENT BUTTONS (survive restarts)
# ==========================================

class _GreeterItem:
    """Shared click handling: only the welcomed member may click, and errors always get an answer."""

    member_id: int

    async def run(self, interaction: discord.Interaction, handler: str, *args):
        cog = interaction.client.get_cog("ButtonGreeter")
        if cog is None or interaction.guild is None:
            return
        if interaction.user.id != self.member_id:
            return await ui.respond(interaction, NOT_YOURS)
        try:
            await getattr(cog, handler)(interaction, *args)
        except Exception:
            log.exception("Welcome button %s failed for %s", handler, interaction.user.id)
            await ui.respond(interaction, SOMETHING_WRONG)
            await cog.report(interaction.guild, "The welcome buttons hit an unexpected error. Details are in the "
                                                "bot's log.", interaction.user)


class RoleItem(_GreeterItem, discord.ui.DynamicItem[discord.ui.Button],
               template=r"bg:role:(?P<rid>\d+):(?P<uid>\d+)"):
    def __init__(self, role_id: int, member_id: int, label: str = "Choose"):
        super().__init__(discord.ui.Button(label=label[:80], style=discord.ButtonStyle.secondary,
                                           custom_id=f"bg:role:{role_id}:{member_id}"))
        self.role_id, self.member_id = role_id, member_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["rid"]), int(match["uid"]), getattr(item, "label", None) or "Choose")

    async def callback(self, interaction: discord.Interaction):
        await self.run(interaction, "on_role_click", self.role_id)


class CustomItem(_GreeterItem, discord.ui.DynamicItem[discord.ui.Button], template=r"bg:custom:(?P<uid>\d+)"):
    def __init__(self, member_id: int):
        super().__init__(discord.ui.Button(label="Custom alliance", emoji="🛡️", style=discord.ButtonStyle.secondary,
                                           custom_id=f"bg:custom:{member_id}"))
        self.member_id = member_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["uid"]))

    async def callback(self, interaction: discord.Interaction):
        await self.run(interaction, "on_custom_click")


class NoneItem(_GreeterItem, discord.ui.DynamicItem[discord.ui.Button], template=r"bg:none:(?P<uid>\d+)"):
    def __init__(self, member_id: int):
        super().__init__(discord.ui.Button(label="No alliance", emoji="👋", style=discord.ButtonStyle.secondary,
                                           custom_id=f"bg:none:{member_id}"))
        self.member_id = member_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["uid"]))

    async def callback(self, interaction: discord.Interaction):
        await self.run(interaction, "on_none_click")


class RulesItem(_GreeterItem, discord.ui.DynamicItem[discord.ui.Button],
                template=r"bg:rules:(?P<answer>yes|no):(?P<uid>\d+)"):
    def __init__(self, answer: str, member_id: int):
        agree = answer == "yes"
        super().__init__(discord.ui.Button(
            label="Yes, I agree" if agree else "No",
            style=discord.ButtonStyle.primary if agree else discord.ButtonStyle.secondary,
            custom_id=f"bg:rules:{answer}:{member_id}",
        ))
        self.answer, self.member_id = answer, member_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["answer"], int(match["uid"]))

    async def callback(self, interaction: discord.Interaction):
        await self.run(interaction, "on_rules_click", self.answer == "yes")


GREETER_ITEMS = (RoleItem, CustomItem, NoneItem, RulesItem)


def welcome_card(member: discord.Member, roles: dict) -> discord.ui.LayoutView:
    """
    The welcome card: avatar, greeting with the newcomer's mention (the one ping in the flow, so send it with
    allowed_mentions for just them), then the group buttons five to a row and the two built-in ones on a row of their
    own. At most 18 + 2 buttons: 30 components in all, under Discord's 40.
    """
    group_buttons = [RoleItem(int(role_id), member.id, label)
                     for label, role_id in list(roles.items())[:MAX_ROLE_BUTTONS]]
    return ui.CardView(ui.card(
        ui.two_line(f"{member.mention}, select your identity below to proceed.",
                    "Your alliance's tag goes in front of your nickname."),
        group_buttons,
        [CustomItem(member.id), NoneItem(member.id)],
        title=f"👋 Welcome to {discord.utils.escape_markdown(member.guild.name)}",
        thumbnail=member.display_avatar.url,
        color=ui.BRAND,
    ))


def rules_card(member: discord.Member, rules: str) -> discord.ui.LayoutView:
    """The rules agreement: it mentions the member, so send it ping-free (they were pinged by the welcome)."""
    return ui.CardView(ui.card(
        ui.two_line(f"{member.mention}, do you agree to the rules in {rules}?",
                    "Identity accepted. Agreeing finishes your welcome."),
        [RulesItem("yes", member.id), RulesItem("no", member.id)],
        title="👋 Protocol agreement",
        color=ui.ATTENTION,
    ))


# ==========================================
#                  MODAL
# ==========================================

class CustomAllianceModal(discord.ui.Modal, title="Custom alliance"):
    tag = discord.ui.TextInput(label="Alliance tag", placeholder="Just the tag, e.g. KVK", min_length=1,
                               max_length=5, required=True)

    def __init__(self, cog: "ButtonGreeter"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.cog.on_custom_submit(interaction, clean_tag(self.tag.value))
        except Exception:
            log.exception("Custom alliance form failed for %s", interaction.user.id)
            await ui.respond(interaction, SOMETHING_WRONG)
            await self.cog.report(interaction.guild, "The custom alliance form hit an unexpected error. Details are "
                                                     "in the bot's log.", interaction.user)


# ==========================================
#                  THE COG
# ==========================================

class ButtonGreeter(commands.Cog):
    """
    Welcome buttons for new members: pick a group (role and nickname tag), then agree to the rules.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8473829102)
        self.config.register_guild(
            welcome_channel=None,
            rules_channel=None,
            admin_channel=None,
            rules_role=None,
            mod_roles=[],
            roles={},           # button label (the nickname tag) -> role ID
        )

    async def cog_load(self):
        self.bot.add_dynamic_items(*GREETER_ITEMS)

    async def cog_unload(self):
        self.bot.remove_dynamic_items(*GREETER_ITEMS)

    async def red_delete_data_for_user(self, **kwargs):
        return  # nothing stored per user

    # ---------- helpers ----------

    async def prefix(self, guild: Optional[discord.Guild]) -> str:
        """The server's real text prefix (not a bot mention), for hints."""
        for prefix in await self.bot.get_valid_prefixes(guild):
            if not prefix.startswith("<@"):
                return prefix
        return "!"

    async def report(self, guild: Optional[discord.Guild], text: str, member: Optional[discord.abc.User] = None):
        """Tell the admins about a problem in the admin channel (if one is set), and log it."""
        if guild is None:
            return
        who = f" (member: {member.display_name}, {member.id})" if member is not None else ""
        log.warning("%s: %s%s", guild.id, text, who)
        channel = guild.get_channel(await self.config.guild(guild).admin_channel() or 0)
        if channel is None:
            return
        content = ui.line(ui.WARN, f"Welcome flow: {text}",
                          f"Member: {member.display_name} ({member.id})" if member is not None else None)
        try:
            await channel.send(content, allowed_mentions=ui.NO_PINGS)
        except discord.HTTPException as e:
            log.info("Couldn't post to the admin channel in %s: %s", guild.id, e)

    async def set_tag(self, member: discord.Member, tag: str) -> Optional[str]:
        """Tag the nickname `[TAG] Name`. Returns the nickname, or None if Discord wouldn't let me change it."""
        new = tagged_nick(member.display_name, tag)
        if new == member.display_name:
            return new
        try:
            await member.edit(nick=new)
            return new
        except discord.HTTPException as e:
            log.info("Couldn't rename %s in %s: %s", member.id, member.guild.id, e)
            await self.report(member.guild, f"I couldn't change **{member.display_name}**'s nickname to **{new}**. "
                                            "My role needs to be above theirs, with Manage Nicknames.", member)
            return None

    async def _swap_group_role(self, member: discord.Member, roles: dict, target: discord.Role):
        """Give `target` and take away the member's other group roles."""
        others = [r for r in (member.guild.get_role(rid) for rid in roles.values())
                  if r is not None and r != target and r in member.roles]
        if others:
            await member.remove_roles(*others)
        await member.add_roles(target)

    # ---------- the welcome flow ----------

    async def on_role_click(self, interaction: discord.Interaction, role_id: int):
        guild, member = interaction.guild, interaction.user
        await interaction.response.defer()
        roles = await self.config.guild(guild).roles()
        label = next((lbl for lbl, rid in roles.items() if int(rid) == role_id), None)
        role = guild.get_role(role_id)
        if label is None or role is None:
            await ui.respond(interaction, ui.line(ui.FAIL, "That option isn't available any more.",
                                                  "Ask a moderator to set your group."))
            return await self.report(guild, f"A welcome button points to a role that no longer exists or was "
                                            f"removed (ID {role_id}).", member)
        try:
            await self._swap_group_role(member, roles, role)
        except discord.HTTPException as e:
            log.info("Couldn't give role %s in %s: %s", role_id, guild.id, e)
            await ui.respond(interaction, ui.line(ui.FAIL, "I couldn't give you that role.", TOLD))
            return await self.report(guild, f"I couldn't give the **{role.name}** role. My role needs to be above "
                                            "it, with Manage Roles.", member)
        await self.set_tag(member, label)
        await self.show_rules(interaction, member)

    async def on_custom_click(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CustomAllianceModal(self))

    async def on_custom_submit(self, interaction: discord.Interaction, tag: str):
        member = interaction.user
        if not tag:
            return await ui.respond(interaction, "❓ Type a tag, like KVK.")
        nick = await self.set_tag(member, tag)
        await ui.respond(interaction, ui.line(ui.DONE, f"Your nickname is now **{nick}**.") if nick else
                         ui.line(ui.WARN, f"Noted **{tag}**, but I couldn't change your nickname.", TOLD))
        await self.show_rules(interaction, member)

    async def on_none_click(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.show_rules(interaction, interaction.user)

    async def show_rules(self, interaction: discord.Interaction, member: discord.Member):
        """Replace the welcome buttons with the rules agreement (or finish, if no rules role is set)."""
        guild = interaction.guild
        try:
            if interaction.message is not None:
                await interaction.message.delete()
        except discord.HTTPException:
            pass  # already gone
        data = await self.config.guild(guild).all()
        if guild.get_role(data["rules_role"] or 0) is None:
            await ui.respond(interaction, "✅ You're all set. Welcome!")
            return await self.report(guild, "No rules role is set (or it was deleted), so the rules step was "
                                            f"skipped. Set one with `{await self.prefix(guild)}bg setrulesrole "
                                            "<role>`.", member)
        rules = f"<#{data['rules_channel']}>" if data["rules_channel"] else "#rules"
        try:
            # Mention, but don't ping (send_card's default): the welcome message already pinged them.
            await ui.send_card(interaction.channel, rules_card(member, rules), allowed_mentions=ui.NO_PINGS)
        except discord.HTTPException as e:
            log.info("Couldn't post the rules prompt in %s: %s", guild.id, e)
            await ui.respond(interaction, ui.line(ui.FAIL, "I couldn't post the rules prompt.", TOLD))
            await self.report(guild, f"I couldn't post the rules prompt in {interaction.channel.mention}.", member)

    async def on_rules_click(self, interaction: discord.Interaction, agree: bool):
        guild, member = interaction.guild, interaction.user
        if not agree:
            return await ui.respond(interaction, ui.line(
                ui.WARN, "You need to agree to the rules to finish joining.",
                "This prompt stays here, so press Yes, I agree whenever you're ready."))
        role = guild.get_role(await self.config.guild(guild).rules_role() or 0)
        if role is None:
            await ui.respond(interaction, ui.line(ui.FAIL, "The rules role is missing, so I can't finish your "
                                                           "welcome.", TOLD))
            return await self.report(guild, "The rules role isn't set or was deleted, so a member couldn't finish "
                                            f"joining. Set it with `{await self.prefix(guild)}bg setrulesrole "
                                            "<role>`.", member)
        try:
            await member.add_roles(role)
        except discord.HTTPException as e:
            log.info("Couldn't give the rules role in %s: %s", guild.id, e)
            await ui.respond(interaction, ui.line(ui.FAIL, "I couldn't give you the rules role.", TOLD))
            return await self.report(guild, f"I couldn't give the **{role.name}** role. My role needs to be above "
                                            "it, with Manage Roles.", member)
        await ui.respond(interaction, ui.line(ui.DONE, f"You now have the **{role.name}** role.",
                                              "Thanks for agreeing, and welcome!"))
        try:
            await interaction.message.delete()
        except (discord.HTTPException, AttributeError):
            pass

    # ==========================================
    #               SETTINGS
    # ==========================================

    @commands.group(aliases=["bg"])
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def buttongreeter(self, ctx: commands.Context):
        """Admin settings for the welcome flow: channels, group buttons and the rules role."""

    @buttongreeter.command(name="settings")
    async def show_settings(self, ctx: commands.Context):
        """Show the current channels, roles and buttons."""
        data = await self.config.guild(ctx.guild).all()

        def channel(cid):
            return f"<#{cid}>" if cid else "not set"

        def role_text(rid):
            role = ctx.guild.get_role(rid) if rid else None
            return role.mention if role else (f"deleted role ({rid})" if rid else "not set")

        mods = ", ".join(role_text(rid) for rid in data.get("mod_roles", [])) or "none (admins only)"
        channels = ui.settings_text([("Welcome", channel(data["welcome_channel"])),
                                     ("Rules", channel(data["rules_channel"])),
                                     ("Error reports", channel(data["admin_channel"]))])
        roles = ui.settings_text([("Rules role", role_text(data["rules_role"])), ("Mod roles", mods)])
        buttons = ui.settings_text([(f"[{discord.utils.escape_markdown(label)}]", f"gives {role_text(rid)}")
                                    for label, rid in data["roles"].items()]) or "None yet."
        view = ui.CardView(ui.card(
            f"**Channels**\n{channels}",
            f"**Roles**\n{roles}",
            f"**Group buttons**\n{ui.truncate(buttons, 2000)}\n"
            + ui.hint("Every welcome also has **Custom alliance** (type a tag) and **No alliance**."),
            ui.SEPARATOR,
            title="👋 Welcome settings",
            color=ui.BRAND,
            footer=f"`{await self.prefix(ctx.guild)}help bg` shows how to change these · Staff only",
        ))
        await ui.send_card(ctx, view)   # ping-free: the role mentions only show the roles

    @buttongreeter.command()
    async def addmodrole(self, ctx: commands.Context, role: discord.Role):
        """Let a role use `[p]forceclass` and `[p]forcerulesremove`."""
        async with self.config.guild(ctx.guild).mod_roles() as mod_roles:
            if role.id in mod_roles:
                return await ctx.send(f"⚠️ **{role.name}** is already a mod role.")
            mod_roles.append(role.id)
        await ctx.send(f"✅ **{role.name}** is now a mod role.")

    @buttongreeter.command()
    async def removemodrole(self, ctx: commands.Context, role: discord.Role):
        """Stop a role from using the force commands."""
        async with self.config.guild(ctx.guild).mod_roles() as mod_roles:
            if role.id not in mod_roles:
                return await ctx.send(f"⚠️ **{role.name}** wasn't a mod role.")
            mod_roles.remove(role.id)
        await ctx.send(f"✅ **{role.name}** is no longer a mod role.")

    @buttongreeter.command()
    async def setchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel where new members are greeted."""
        await self.config.guild(ctx.guild).welcome_channel.set(channel.id)
        await ctx.send(f"✅ New members will be greeted in {channel.mention}.")

    @buttongreeter.command()
    async def setruleschannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel that has your server rules."""
        await self.config.guild(ctx.guild).rules_channel.set(channel.id)
        await ctx.send(f"✅ Rules channel set to {channel.mention}.")

    @buttongreeter.command()
    async def setadminchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel where problems with the welcome flow are reported."""
        await self.config.guild(ctx.guild).admin_channel.set(channel.id)
        await ctx.send(f"✅ Problems will be reported in {channel.mention}.")

    @buttongreeter.command()
    async def setrulesrole(self, ctx: commands.Context, role: discord.Role):
        """Set the role members get when they agree to the rules."""
        await self.config.guild(ctx.guild).rules_role.set(role.id)
        await ctx.send(f"✅ Members who agree to the rules will get the **{role.name}** role.")

    @buttongreeter.command()
    async def addrole(self, ctx: commands.Context, role: discord.Role, *, button_label: str):
        """Add a group button to the welcome message. Its label becomes the nickname tag."""
        if role >= ctx.guild.me.top_role:
            await ctx.send(ui.line(ui.FAIL, f"I can't give **{role.name}** because it's at or above my highest "
                                            "role.", "Move my role above it first."))
            return await self.report(ctx.guild, f"Someone tried to add a button for **{role.name}**, which is above "
                                                "my highest role.")
        if len(button_label) > 80:
            return await ctx.send("❌ Button labels can be up to 80 characters.")
        async with self.config.guild(ctx.guild).roles() as roles:
            if button_label not in roles and len(roles) >= MAX_ROLE_BUTTONS:
                return await ctx.send(ui.line(
                    ui.WAIT, f"The welcome message has room for {MAX_ROLE_BUTTONS} group buttons.",
                    f"Remove one first with `{await self.prefix(ctx.guild)}bg removerole <label>`."))
            roles[button_label] = role.id
        await ctx.send(f"✅ Added the **[{button_label}]** button, which gives **{role.name}**.")

    @buttongreeter.command()
    async def removerole(self, ctx: commands.Context, *, button_label: str):
        """Remove a group button."""
        async with self.config.guild(ctx.guild).roles() as roles:
            if button_label not in roles:
                return await ctx.send(ui.line(ui.ASK, f"There's no button called **{button_label}**.",
                                              f"`{await self.prefix(ctx.guild)}bg settings` lists them."))
            del roles[button_label]
        await ctx.send(f"✅ Removed the **[{button_label}]** button.")

    # ==========================================
    #          MEMBER AND MOD COMMANDS
    # ==========================================

    async def _option(self, ctx: commands.Context, label: str):
        """(roles config, the role for this button label), or None after explaining what's wrong."""
        roles = await self.config.guild(ctx.guild).roles()
        if label not in roles:
            options = ", ".join(f"`{name}`" for name in roles) or "none yet"
            await ctx.send(ui.line(ui.ASK, f"There's no group called **{label}**.", f"Options: {options}."),
                           allowed_mentions=ui.NO_PINGS)
            return None
        role = ctx.guild.get_role(roles[label])
        if role is None:
            await ctx.send(ui.line(ui.FAIL, f"The role for **{label}** no longer exists.", TOLD))
            await self.report(ctx.guild, f"The **{label}** button's role no longer exists (ID {roles[label]}).",
                              ctx.author)
            return None
        return roles, role

    @commands.command()
    @commands.guild_only()
    async def changerole(self, ctx: commands.Context, *, exact_label: str):
        """Switch your group if you clicked the wrong button. Use the button's exact label."""
        found = await self._option(ctx, exact_label)
        if found is None:
            return
        roles, role = found
        try:
            await self._swap_group_role(ctx.author, roles, role)
        except discord.Forbidden:
            await ctx.send(ui.line(ui.FAIL, "I couldn't change your roles.", TOLD))
            return await self.report(ctx.guild, f"I couldn't switch a member to **{role.name}**. My role needs to be "
                                                "above the group roles, with Manage Roles.", ctx.author)
        nick = await self.set_tag(ctx.author, exact_label)
        await ctx.send(f"✅ Your group is now **{role.name}** and your nickname is **{nick}**." if nick else
                       f"✅ Your group is now **{role.name}**, but I couldn't change your nickname.",
                       allowed_mentions=ui.NO_PINGS)

    @commands.command()
    @commands.guild_only()
    @commands.check(has_mod_role)
    async def forceclass(self, ctx: commands.Context, member: discord.Member, *, exact_label: str):
        """(Admins and welcome mod roles) Put a member in a group: its role and nickname tag."""
        found = await self._option(ctx, exact_label)
        if found is None:
            return
        roles, role = found
        try:
            await self._swap_group_role(member, roles, role)
        except discord.Forbidden:
            await ctx.send(ui.line(ui.FAIL, f"I couldn't change {member.display_name}'s roles.",
                                   "My role needs to be above theirs."), allowed_mentions=ui.NO_PINGS)
            return await self.report(ctx.guild, f"{ctx.author.display_name} tried to move a member to "
                                                f"**{role.name}**, but I lack the permissions.", member)
        nick = await self.set_tag(member, exact_label)
        await ctx.send(f"✅ Moved **{member.display_name}** to **{role.name}**." if nick else
                       f"✅ Moved **{member.display_name}** to **{role.name}**, but I couldn't change their "
                       "nickname.", allowed_mentions=ui.NO_PINGS)

    @commands.command()
    @commands.guild_only()
    @commands.check(has_mod_role)
    async def forcerulesremove(self, ctx: commands.Context, member: discord.Member):
        """(Admins and welcome mod roles) Take the rules role away from a member."""
        rid = await self.config.guild(ctx.guild).rules_role()
        role = ctx.guild.get_role(rid or 0)
        if role is None:
            return await ctx.send(ui.line(ui.WARN, "No rules role is set.",
                                          f"Set one with `{await self.prefix(ctx.guild)}bg setrulesrole <role>`."))
        if role not in member.roles:
            return await ctx.send(f"⚠️ **{member.display_name}** doesn't have **{role.name}**.",
                                  allowed_mentions=ui.NO_PINGS)
        try:
            await member.remove_roles(role)
        except discord.Forbidden:
            await ctx.send(ui.line(ui.FAIL, f"I couldn't remove **{role.name}**.", "My role needs to be above it."))
            return await self.report(ctx.guild, f"I couldn't remove **{role.name}** (permissions).", member)
        await ctx.send(f"✅ Removed **{role.name}** from **{member.display_name}**.", allowed_mentions=ui.NO_PINGS)

    # ==========================================
    #                 WELCOME
    # ==========================================

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Greet a new member with the group buttons."""
        data = await self.config.guild(member.guild).all()
        channel_id, roles = data["welcome_channel"], data["roles"]
        if not channel_id or not roles:
            return
        channel = member.guild.get_channel(channel_id)
        if channel is None:
            return await self.report(member.guild, f"The welcome channel (ID {channel_id}) is gone, so I couldn't "
                                                   "greet a new member.", member)
        try:
            # The one ping in the flow: the greeting itself. Mentions in card text ping, so only the newcomer is allowed.
            await ui.send_card(channel, welcome_card(member, roles),
                               allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=[member]))
        except discord.HTTPException as e:
            log.info("Couldn't greet %s in %s: %s", member.id, member.guild.id, e)
            await self.report(member.guild, f"I couldn't post the welcome message in {channel.mention}.", member)
