"""
Game Manager Cog for Red-DiscordBot

A comprehensive game library management system that allows users to:
- Track owned and installed games
- Rank their game preferences
- Find shared games among users
- Start play sessions and votes
"""

import discord
from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from typing import Optional, List, Dict, Any, Union
import asyncio
from datetime import datetime, timedelta
import random
import string
import re


class MemberConverter(commands.Converter):
    """Convert member by name, nickname, or mention."""
    async def convert(self, ctx: commands.Context, argument: str) -> discord.Member:
        # Try standard conversion first (mentions, IDs)
        try:
            return await commands.MemberConverter().convert(ctx, argument)
        except commands.MemberNotFound:
            pass
        
        # Try by name/nickname
        argument_lower = argument.lower()
        for member in ctx.guild.members:
            if member.name.lower() == argument_lower or (member.nick and member.nick.lower() == argument_lower):
                return member
        
        # Try partial match
        for member in ctx.guild.members:
            if argument_lower in member.name.lower() or (member.nick and argument_lower in member.nick.lower()):
                return member
        
        raise commands.MemberNotFound(argument)


class MultiGameSelectView(discord.ui.View):
    """View for selecting multiple games from a paginated list."""
    
    def __init__(self, cog, user: discord.Member, games: List[Dict], mode: str, page: int = 0):
        super().__init__(timeout=300)
        self.cog = cog
        self.user = user
        self.games = games
        self.mode = mode
        self.page = page
        self.per_page = 10
        self.selected_games: List[Dict] = []
        self.cancelled = False
        self.update_buttons()
    
    def update_buttons(self):
        self.clear_items()
        start = self.page * self.per_page
        end = start + self.per_page
        page_games = self.games[start:end]
        
        for i, game in enumerate(page_games):
            is_selected = game["id"] in [g["id"] for g in self.selected_games]
            style = discord.ButtonStyle.success if is_selected else discord.ButtonStyle.secondary
            label = game["name"][:75]
            if is_selected:
                label = "[X] " + label[:71]
            
            button = discord.ui.Button(label=label, style=style, custom_id=f"game_{game['id']}", row=i // 5)
            button.callback = self.make_callback(game)
            self.add_item(button)
        
        if self.page > 0:
            prev_btn = discord.ui.Button(label="< Prev", style=discord.ButtonStyle.primary, row=4)
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
        
        if end < len(self.games):
            next_btn = discord.ui.Button(label="Next >", style=discord.ButtonStyle.primary, row=4)
            next_btn.callback = self.next_page
            self.add_item(next_btn)
        
        done_btn = discord.ui.Button(label=f"Done ({len(self.selected_games)})", style=discord.ButtonStyle.success, row=4)
        done_btn.callback = self.done
        self.add_item(done_btn)
        
        cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger, row=4)
        cancel_btn.callback = self.cancel
        self.add_item(cancel_btn)
    
    def make_callback(self, game):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user.id:
                await interaction.response.send_message("This menu is not for you!", ephemeral=True)
                return
            game_ids = [g["id"] for g in self.selected_games]
            if game["id"] in game_ids:
                self.selected_games = [g for g in self.selected_games if g["id"] != game["id"]]
            else:
                self.selected_games.append(game)
            self.update_buttons()
            await interaction.response.edit_message(view=self)
        return callback
    
    async def prev_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return
        self.page -= 1
        self.update_buttons()
        await interaction.response.edit_message(view=self)
    
    async def next_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return
        self.page += 1
        self.update_buttons()
        await interaction.response.edit_message(view=self)
    
    async def done(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return
        self.cancelled = False
        self.stop()
        await interaction.response.defer()
    
    async def cancel(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return
        self.selected_games = []
        self.cancelled = True
        self.stop()
        await interaction.response.defer()


class PlaySessionView(discord.ui.View):
    """View for play session registration with live participant updates."""
    
    def __init__(self, cog, session_id: str, host: discord.Member, message: discord.Message = None):
        super().__init__(timeout=None)
        self.cog = cog
        self.session_id = session_id
        self.host = host
        self.message = message
    
    async def update_embed(self, guild: discord.Guild):
        """Update the session embed with current participants."""
        if not self.message:
            return
        
        sessions = await self.cog.config.guild(guild).play_sessions()
        if self.session_id not in sessions:
            return
        
        session = sessions[self.session_id]
        participants = []
        for i, uid in enumerate(session["participants"], 1):
            member = guild.get_member(int(uid))
            name = member.display_name if member else f"User {uid}"
            participants.append(f"{i}. {member.mention if member else name}")
        
        embed = discord.Embed(
            title=f"Gaming Session: {session['title']}",
            description=f"Click **Join Session** to participate.\nOnce everyone has joined, the host can run `!games sessionvote` to vote on a game.",
            color=discord.Color.green()
        )
        embed.add_field(name=f"Participants ({len(session['participants'])})", value="\n".join(participants) or "None", inline=False)
        embed.set_footer(text=f"Session ID: {self.session_id}")
        
        try:
            await self.message.edit(embed=embed, view=self)
        except discord.NotFound:
            pass
    
    @discord.ui.button(label="Join Session", style=discord.ButtonStyle.success, custom_id="join_session")
    async def join_session(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        sessions = await self.cog.config.guild_from_id(guild_id).play_sessions()
        if self.session_id not in sessions:
            await interaction.response.send_message("This session no longer exists!", ephemeral=True)
            return
        session = sessions[self.session_id]
        user_id = str(interaction.user.id)
        if user_id in session["participants"]:
            await interaction.response.send_message("You've already joined this session!", ephemeral=True)
            return
        session["participants"].append(user_id)
        sessions[self.session_id] = session
        await self.cog.config.guild_from_id(guild_id).play_sessions.set(sessions)
        
        await interaction.response.send_message(f"You've joined the gaming session!", ephemeral=True)
        await self.update_embed(interaction.guild)
    
    @discord.ui.button(label="Leave Session", style=discord.ButtonStyle.danger, custom_id="leave_session")
    async def leave_session(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        sessions = await self.cog.config.guild_from_id(guild_id).play_sessions()
        if self.session_id not in sessions:
            await interaction.response.send_message("This session no longer exists!", ephemeral=True)
            return
        session = sessions[self.session_id]
        user_id = str(interaction.user.id)
        if user_id not in session["participants"]:
            await interaction.response.send_message("You haven't joined this session!", ephemeral=True)
            return
        if user_id == session["host_id"]:
            await interaction.response.send_message("The host cannot leave! Use `!games endsession` to end the session.", ephemeral=True)
            return
        session["participants"].remove(user_id)
        sessions[self.session_id] = session
        await self.cog.config.guild_from_id(guild_id).play_sessions.set(sessions)
        
        await interaction.response.send_message("You've left the gaming session.", ephemeral=True)
        await self.update_embed(interaction.guild)


class SessionVoteView(discord.ui.View):
    """View for voting on games - restricted to session participants with live updates."""
    
    def __init__(self, cog, vote_id: str, games: List[Dict], max_votes: int, allowed_voters: List[str], message: discord.Message = None):
        super().__init__(timeout=None)
        self.cog = cog
        self.vote_id = vote_id
        self.games = games
        self.max_votes = max_votes
        self.allowed_voters = allowed_voters
        self.message = message
        self.update_buttons()
    
    def update_buttons(self):
        self.clear_items()
        for i, game in enumerate(self.games[:20]):
            button = discord.ui.Button(label=game["name"][:80], style=discord.ButtonStyle.primary, custom_id=f"svote_{self.vote_id}_{game['id']}", row=i // 5)
            button.callback = self.make_vote_callback(game)
            self.add_item(button)
    
    async def update_embed(self, guild: discord.Guild, vote_data: Dict):
        """Update the vote embed with current voters."""
        if not self.message:
            return
        
        voters = list(vote_data["user_votes"].keys())
        voter_names = []
        for uid in voters:
            member = guild.get_member(int(uid))
            voter_names.append(member.display_name if member else f"User {uid}")
        
        total_voters = len(self.allowed_voters)
        voted_count = len(voters)
        
        embed = self.message.embeds[0] if self.message.embeds else discord.Embed(title="Vote", color=discord.Color.purple())
        
        # Update or add voters field
        voters_text = ", ".join(voter_names) if voter_names else "No votes yet"
        voted_field_name = f"Voted ({voted_count}/{total_voters})"
        
        # Remove old voted field if exists
        embed.clear_fields()
        embed.add_field(name=voted_field_name, value=voters_text, inline=False)
        
        try:
            await self.message.edit(embed=embed, view=self)
        except discord.NotFound:
            pass
    
    def make_vote_callback(self, game):
        async def callback(interaction: discord.Interaction):
            user_id = str(interaction.user.id)
            if user_id not in self.allowed_voters:
                await interaction.response.send_message("Only session participants can vote!", ephemeral=True)
                return
            guild_id = interaction.guild.id
            votes = await self.cog.config.guild_from_id(guild_id).votes()
            if self.vote_id not in votes:
                await interaction.response.send_message("This vote has ended!", ephemeral=True)
                return
            vote_data = votes[self.vote_id]
            game_id = game["id"]
            if user_id not in vote_data["user_votes"]:
                vote_data["user_votes"][user_id] = []
            user_votes = vote_data["user_votes"][user_id]
            if game_id in user_votes:
                user_votes.remove(game_id)
                if game_id in vote_data["tallies"]:
                    vote_data["tallies"][game_id] -= 1
                await interaction.response.send_message(f"Removed vote for **{game['name']}**", ephemeral=True)
            elif len(user_votes) >= self.max_votes:
                await interaction.response.send_message(f"You can only vote for {self.max_votes} game(s)!", ephemeral=True)
                return
            else:
                user_votes.append(game_id)
                if game_id not in vote_data["tallies"]:
                    vote_data["tallies"][game_id] = 0
                vote_data["tallies"][game_id] += 1
                await interaction.response.send_message(f"Voted for **{game['name']}**!", ephemeral=True)
            vote_data["user_votes"][user_id] = user_votes
            votes[self.vote_id] = vote_data
            await self.cog.config.guild_from_id(guild_id).votes.set(votes)
            
            # Update embed with voters
            await self.update_embed(interaction.guild, vote_data)
            
            # Check if everyone has voted
            if len(vote_data["user_votes"]) >= len(self.allowed_voters):
                # Everyone voted - end vote early
                vote_data["ended_early"] = True
                votes[self.vote_id] = vote_data
                await self.cog.config.guild_from_id(guild_id).votes.set(votes)
        return callback


class GameRequestApprovalView(discord.ui.View):
    """View for admins to approve/deny game requests."""
    
    def __init__(self, cog, request_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.request_id = request_id
    
    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="approve_request")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.cog.is_admin(interaction.user, interaction.guild):
            await interaction.response.send_message("Only admins can approve requests!", ephemeral=True)
            return
        guild_id = interaction.guild.id
        requests = await self.cog.config.guild_from_id(guild_id).game_requests()
        if self.request_id not in requests:
            await interaction.response.send_message("This request no longer exists!", ephemeral=True)
            return
        request = requests[self.request_id]
        games = await self.cog.config.guild_from_id(guild_id).games()
        game_id = self.cog.generate_id()
        games[game_id] = {"id": game_id, "name": request["name"], "description": request.get("description", ""), "added_by": str(interaction.user.id), "added_at": datetime.utcnow().isoformat()}
        await self.cog.config.guild_from_id(guild_id).games.set(games)
        del requests[self.request_id]
        await self.cog.config.guild_from_id(guild_id).game_requests.set(requests)
        await interaction.response.send_message(f"Approved! **{request['name']}** has been added.", ephemeral=False)
        self.stop()
    
    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="deny_request")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.cog.is_admin(interaction.user, interaction.guild):
            await interaction.response.send_message("Only admins can deny requests!", ephemeral=True)
            return
        guild_id = interaction.guild.id
        requests = await self.cog.config.guild_from_id(guild_id).game_requests()
        if self.request_id not in requests:
            await interaction.response.send_message("This request no longer exists!", ephemeral=True)
            return
        request = requests[self.request_id]
        del requests[self.request_id]
        await self.cog.config.guild_from_id(guild_id).game_requests.set(requests)
        await interaction.response.send_message(f"Denied request for **{request['name']}**.", ephemeral=False)
        self.stop()


class InstallRequestView(discord.ui.View):
    """View for users to mark games as installed from admin requests."""
    
    def __init__(self, cog, request_id: str, game_id: str, game_name: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.request_id = request_id
        self.game_id = game_id
        self.game_name = game_name
    
    @discord.ui.button(label="I've Installed It", style=discord.ButtonStyle.success)
    async def mark_installed(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        user_id = str(interaction.user.id)
        users = await self.cog.config.guild_from_id(guild_id).users()
        if user_id not in users:
            users[user_id] = {"owned": [], "installed": [], "ranks": {}}
        if self.game_id not in users[user_id]["owned"]:
            users[user_id]["owned"].append(self.game_id)
        if self.game_id not in users[user_id]["installed"]:
            users[user_id]["installed"].append(self.game_id)
        await self.cog.config.guild_from_id(guild_id).users.set(users)
        install_requests = await self.cog.config.guild_from_id(guild_id).install_requests()
        if self.request_id in install_requests:
            if user_id not in install_requests[self.request_id]["installed_by"]:
                install_requests[self.request_id]["installed_by"].append(user_id)
                await self.cog.config.guild_from_id(guild_id).install_requests.set(install_requests)
        await interaction.response.send_message(f"Marked **{self.game_name}** as installed!", ephemeral=True)


class GameManager(commands.Cog):
    """Manage your game library and find games to play with friends."""
    
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8675309420, force_registration=True)
        default_guild = {
            "games": {},
            "users": {},
            "game_requests": {},
            "play_sessions": {},
            "votes": {},
            "install_requests": {},
            "admin_role": None
        }
        self.config.register_guild(**default_guild)
        self.active_votes: Dict[str, asyncio.Task] = {}
    
    def cog_unload(self):
        """Cancel all active vote timers on unload."""
        for task in self.active_votes.values():
            task.cancel()
    
    def generate_id(self) -> str:
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    
    async def is_admin(self, user: discord.Member, guild: discord.Guild) -> bool:
        if user.guild_permissions.administrator:
            return True
        admin_role_id = await self.config.guild(guild).admin_role()
        if admin_role_id:
            return any(role.id == admin_role_id for role in user.roles)
        return False
    
    async def get_channel_members_with_games(self, channel: discord.TextChannel) -> List[discord.Member]:
        """Get channel members who have game records."""
        users = await self.config.guild(channel.guild).users()
        members = []
        for member in channel.guild.members:
            if channel.permissions_for(member).read_messages and not member.bot:
                user_id = str(member.id)
                if user_id in users and (users[user_id].get("owned") or users[user_id].get("installed")):
                    members.append(member)
        return members
    
    async def find_member(self, guild: discord.Guild, name: str) -> Optional[discord.Member]:
        """Find a member by name, nickname, or mention."""
        # Check for mention format
        if name.startswith("<@") and name.endswith(">"):
            user_id = name.strip("<@!>")
            try:
                return guild.get_member(int(user_id))
            except ValueError:
                pass
        
        name_lower = name.lower()
        # Exact match first
        for member in guild.members:
            if member.name.lower() == name_lower or (member.nick and member.nick.lower() == name_lower):
                return member
        # Partial match
        for member in guild.members:
            if name_lower in member.name.lower() or (member.nick and name_lower in member.nick.lower()):
                return member
        return None
    
    def find_game_by_name(self, games: Dict, name: str) -> Optional[Dict]:
        name_lower = name.lower().strip()
        for game in games.values():
            if game["name"].lower() == name_lower:
                return game
        for game in games.values():
            if name_lower in game["name"].lower():
                return game
        return None
    
    def parse_game_names(self, input_str: str) -> List[str]:
        games = []
        quoted_pattern = r'"([^"]+)"|\'([^\']+)\''
        quoted_matches = re.findall(quoted_pattern, input_str)
        for match in quoted_matches:
            game_name = match[0] or match[1]
            if game_name.strip():
                games.append(game_name.strip())
        remaining = re.sub(quoted_pattern, '', input_str)
        for part in re.split(r'[,\n]', remaining):
            part = part.strip()
            if part:
                games.append(part)
        return games
    
    def format_game_name(self, name: str, is_installed: bool) -> str:
        """Format game name - add checkmark if installed."""
        return f"{name} ✅" if is_installed else name
    
    async def send_full_list(self, ctx, items: List[str], title: str, footer: str = None):
        """Send a complete list using multiple embeds if needed."""
        if not items:
            await ctx.send("No items to display.")
            return
        per_embed = 40
        embeds = []
        for i in range(0, len(items), per_embed):
            page_items = items[i:i + per_embed]
            description = "\n".join(page_items)
            embed = discord.Embed(
                title=title if i == 0 else f"{title} (continued)",
                description=description,
                color=discord.Color.blue()
            )
            if i + per_embed >= len(items):
                embed.set_footer(text=footer or f"Total: {len(items)} items")
            embeds.append(embed)
        for i in range(0, len(embeds), 10):
            await ctx.send(embeds=embeds[i:i + 10])
    
    async def run_vote_timer(self, guild_id: int, channel_id: int, vote_id: str, duration: int, message: discord.Message):
        """Run a vote timer with countdown announcements."""
        try:
            end_time = datetime.utcnow() + timedelta(seconds=duration)
            announced = set()
            
            while datetime.utcnow() < end_time:
                # Check if vote ended early
                votes = await self.config.guild_from_id(guild_id).votes()
                if vote_id not in votes or votes[vote_id].get("ended_early"):
                    break
                
                remaining = (end_time - datetime.utcnow()).total_seconds()
                
                # Announce at specific times
                channel = self.bot.get_channel(channel_id)
                if channel:
                    if remaining <= 60 and "60" not in announced and remaining > 30:
                        await channel.send(f"⏰ **1 minute** remaining to vote!")
                        announced.add("60")
                    elif remaining <= 30 and "30" not in announced and remaining > 10:
                        await channel.send(f"⏰ **30 seconds** remaining to vote!")
                        announced.add("30")
                    elif remaining <= 10 and "10" not in announced and remaining > 0:
                        await channel.send(f"⏰ **10 seconds** remaining to vote!")
                        announced.add("10")
                
                await asyncio.sleep(1)
            
            # End the vote
            await self.end_vote(guild_id, channel_id, vote_id, message)
            
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Vote timer error: {e}")
    
    async def end_vote(self, guild_id: int, channel_id: int, vote_id: str, message: discord.Message):
        """End a vote and display results."""
        votes = await self.config.guild_from_id(guild_id).votes()
        if vote_id not in votes:
            return
        
        vote_data = votes[vote_id]
        games = await self.config.guild_from_id(guild_id).games()
        
        # Calculate results with percentages
        total_votes = sum(vote_data["tallies"].values()) if vote_data["tallies"] else 0
        sorted_results = sorted(vote_data["tallies"].items(), key=lambda x: -x[1])
        
        results = []
        for gid, count in sorted_results:
            if gid in games:
                percentage = (count / total_votes * 100) if total_votes > 0 else 0
                results.append(f"**{games[gid]['name']}** - {count} vote(s) ({percentage:.1f}%)")
        
        if not results:
            results = ["No votes were cast!"]
        
        # Delete the vote message
        try:
            await message.delete()
        except discord.NotFound:
            pass
        
        # Send results
        channel = self.bot.get_channel(channel_id)
        if channel:
            embed = discord.Embed(
                title="Vote Results",
                description="\n".join(results),
                color=discord.Color.gold()
            )
            voters = len(vote_data["user_votes"])
            embed.set_footer(text=f"Total voters: {voters} | Total votes: {total_votes}")
            await channel.send(embed=embed)
        
        # Clean up
        del votes[vote_id]
        await self.config.guild_from_id(guild_id).votes.set(votes)
        
        if vote_id in self.active_votes:
            del self.active_votes[vote_id]
    
    @commands.group(name="games", aliases=["game", "gm"])
    @commands.guild_only()
    async def games(self, ctx: commands.Context):
        """Game management commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)
    
    @games.command(name="list")
    async def games_list(self, ctx: commands.Context):
        """Show all available games."""
        games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        user_id = str(ctx.author.id)
        installed = users.get(user_id, {}).get("installed", [])
        
        if not games:
            await ctx.send("No games have been added yet! Ask an admin to add some games.")
            return
        sorted_games = sorted(games.values(), key=lambda x: x["name"].lower())
        items = [f"- {self.format_game_name(g['name'], g['id'] in installed)}" for g in sorted_games]
        await self.send_full_list(ctx, items, "Available Games", f"Total: {len(sorted_games)} games | ✅ = Installed")
    
    @games.command(name="search")
    async def games_search(self, ctx: commands.Context, *, query: str):
        """Search for games by name."""
        games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        user_id = str(ctx.author.id)
        installed = users.get(user_id, {}).get("installed", [])
        
        query_lower = query.lower()
        matches = [g for g in games.values() if query_lower in g["name"].lower()]
        if not matches:
            await ctx.send(f"No games found matching '{query}'.")
            return
        sorted_matches = sorted(matches, key=lambda x: x["name"].lower())
        items = [f"- {self.format_game_name(g['name'], g['id'] in installed)}" for g in sorted_matches]
        await self.send_full_list(ctx, items, f"Search Results for '{query}'")
    
    @games.command(name="own")
    async def games_own(self, ctx: commands.Context):
        """Mark games you own (interactive multi-select)."""
        games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        user_id = str(ctx.author.id)
        if not games:
            await ctx.send("No games available! Ask an admin to add some games.")
            return
        owned = users.get(user_id, {}).get("owned", [])
        available = [g for g in games.values() if g["id"] not in owned]
        if not available:
            await ctx.send("You already own all available games!")
            return
        sorted_games = sorted(available, key=lambda x: x["name"].lower())
        embed = discord.Embed(title="Select Games You Own", description="Click games to toggle, then **Done**.\nOr use `games ownadd Game1, Game2` to add by name.", color=discord.Color.green())
        view = MultiGameSelectView(self, ctx.author, sorted_games, "own")
        message = await ctx.send(embed=embed, view=view)
        await view.wait()
        
        try:
            if view.cancelled:
                await message.delete()
                return
            
            if view.selected_games:
                if user_id not in users:
                    users[user_id] = {"owned": [], "installed": [], "ranks": {}}
                added = []
                for game in view.selected_games:
                    if game["id"] not in users[user_id]["owned"]:
                        users[user_id]["owned"].append(game["id"])
                        added.append(game["name"])
                await self.config.guild(ctx.guild).users.set(users)
                if added:
                    games_str = ", ".join(f"**{n}**" for n in added[:10])
                    if len(added) > 10:
                        games_str += f" and {len(added) - 10} more"
                    result_embed = discord.Embed(title="Games Added", description=f"Added {len(added)} game(s):\n{games_str}", color=discord.Color.green())
                else:
                    result_embed = discord.Embed(title="No new games added", color=discord.Color.grey())
            else:
                result_embed = discord.Embed(title="No games selected", color=discord.Color.grey())
            
            await message.delete()
            await ctx.send(embed=result_embed, delete_after=10)
        except discord.NotFound:
            pass
    
    @games.command(name="ownadd", aliases=["addowned", "iown"])
    async def games_ownadd(self, ctx: commands.Context, *, game_names: str):
        """Add multiple games to your owned list by name."""
        all_games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        user_id = str(ctx.author.id)
        if not all_games:
            await ctx.send("No games available!")
            return
        requested = self.parse_game_names(game_names)
        if not requested:
            await ctx.send("Please provide at least one game name!")
            return
        if user_id not in users:
            users[user_id] = {"owned": [], "installed": [], "ranks": {}}
        added, already_owned, not_found = [], [], []
        for name in requested:
            game = self.find_game_by_name(all_games, name)
            if not game:
                not_found.append(name)
            elif game["id"] in users[user_id]["owned"]:
                already_owned.append(game["name"])
            else:
                users[user_id]["owned"].append(game["id"])
                added.append(game["name"])
        await self.config.guild(ctx.guild).users.set(users)
        parts = []
        if added:
            parts.append(f"**Added ({len(added)}):** {', '.join(added)}")
        if already_owned:
            parts.append(f"**Already owned ({len(already_owned)}):** {', '.join(already_owned)}")
        if not_found:
            parts.append(f"**Not found ({len(not_found)}):** {', '.join(not_found)}")
        embed = discord.Embed(title="Update Owned Games", description="\n".join(parts), color=discord.Color.green() if added else discord.Color.orange())
        await ctx.send(embed=embed)
    
    @games.command(name="unown", aliases=["removeowned", "disown"])
    async def games_unown(self, ctx: commands.Context, *, game_names: str = None):
        """Remove games from your owned list."""
        all_games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        user_id = str(ctx.author.id)
        owned = users.get(user_id, {}).get("owned", [])
        if not owned:
            await ctx.send("You don't own any games yet!")
            return
        if game_names:
            requested = self.parse_game_names(game_names)
            removed, not_owned, not_found = [], [], []
            for name in requested:
                game = self.find_game_by_name(all_games, name)
                if not game:
                    not_found.append(name)
                elif game["id"] not in users[user_id]["owned"]:
                    not_owned.append(game["name"])
                else:
                    users[user_id]["owned"].remove(game["id"])
                    if game["id"] in users[user_id].get("installed", []):
                        users[user_id]["installed"].remove(game["id"])
                    if game["id"] in users[user_id].get("ranks", {}):
                        del users[user_id]["ranks"][game["id"]]
                    removed.append(game["name"])
            await self.config.guild(ctx.guild).users.set(users)
            parts = []
            if removed:
                parts.append(f"**Removed ({len(removed)}):** {', '.join(removed)}")
            if not_owned:
                parts.append(f"**Not owned ({len(not_owned)}):** {', '.join(not_owned)}")
            if not_found:
                parts.append(f"**Not found ({len(not_found)}):** {', '.join(not_found)}")
            embed = discord.Embed(title="Update Owned Games", description="\n".join(parts), color=discord.Color.orange() if removed else discord.Color.grey())
            await ctx.send(embed=embed)
            return
        owned_games = [all_games[gid] for gid in owned if gid in all_games]
        if not owned_games:
            await ctx.send("You don't own any games yet!")
            return
        sorted_games = sorted(owned_games, key=lambda x: x["name"].lower())
        embed = discord.Embed(title="Remove Games", description="Click games to toggle, then **Done**.", color=discord.Color.red())
        view = MultiGameSelectView(self, ctx.author, sorted_games, "unown")
        message = await ctx.send(embed=embed, view=view)
        await view.wait()
        
        try:
            if view.cancelled:
                await message.delete()
                return
            
            if view.selected_games:
                removed = []
                for game in view.selected_games:
                    if game["id"] in users[user_id]["owned"]:
                        users[user_id]["owned"].remove(game["id"])
                        if game["id"] in users[user_id].get("installed", []):
                            users[user_id]["installed"].remove(game["id"])
                        if game["id"] in users[user_id].get("ranks", {}):
                            del users[user_id]["ranks"][game["id"]]
                        removed.append(game["name"])
                await self.config.guild(ctx.guild).users.set(users)
                if removed:
                    games_str = ", ".join(f"**{n}**" for n in removed[:10])
                    if len(removed) > 10:
                        games_str += f" and {len(removed) - 10} more"
                    result_embed = discord.Embed(title="Games Removed", description=f"Removed {len(removed)} game(s):\n{games_str}", color=discord.Color.orange())
                else:
                    result_embed = discord.Embed(title="No games removed", color=discord.Color.grey())
            else:
                result_embed = discord.Embed(title="No games selected", color=discord.Color.grey())
            
            await message.delete()
            await ctx.send(embed=result_embed, delete_after=10)
        except discord.NotFound:
            pass
    
    @games.command(name="install")
    async def games_install(self, ctx: commands.Context, *, game_names: str = None):
        """Mark games as installed."""
        all_games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        user_id = str(ctx.author.id)
        owned = users.get(user_id, {}).get("owned", [])
        if not owned:
            await ctx.send("You need to own games first! Use `games own` or `games ownadd`.")
            return
        installed = users.get(user_id, {}).get("installed", [])
        if game_names:
            requested = self.parse_game_names(game_names)
            marked, already, not_owned, not_found = [], [], [], []
            for name in requested:
                game = self.find_game_by_name(all_games, name)
                if not game:
                    not_found.append(name)
                elif game["id"] not in owned:
                    not_owned.append(game["name"])
                elif game["id"] in installed:
                    already.append(game["name"])
                else:
                    users[user_id]["installed"].append(game["id"])
                    marked.append(game["name"])
            await self.config.guild(ctx.guild).users.set(users)
            parts = []
            if marked:
                parts.append(f"**Installed ({len(marked)}):** {', '.join(marked)}")
            if already:
                parts.append(f"**Already installed ({len(already)}):** {', '.join(already)}")
            if not_owned:
                parts.append(f"**Not owned ({len(not_owned)}):** {', '.join(not_owned)}")
            if not_found:
                parts.append(f"**Not found ({len(not_found)}):** {', '.join(not_found)}")
            embed = discord.Embed(title="Update Installed", description="\n".join(parts), color=discord.Color.blurple() if marked else discord.Color.grey())
            await ctx.send(embed=embed)
            return
        available = [all_games[gid] for gid in owned if gid in all_games and gid not in installed]
        if not available:
            await ctx.send("All owned games are already installed!")
            return
        sorted_games = sorted(available, key=lambda x: x["name"].lower())
        embed = discord.Embed(title="Mark as Installed", description="Click games to toggle, then **Done**.", color=discord.Color.blurple())
        view = MultiGameSelectView(self, ctx.author, sorted_games, "install")
        message = await ctx.send(embed=embed, view=view)
        await view.wait()
        
        try:
            if view.cancelled:
                await message.delete()
                return
            
            if view.selected_games:
                marked = []
                for game in view.selected_games:
                    if game["id"] not in users[user_id]["installed"]:
                        users[user_id]["installed"].append(game["id"])
                        marked.append(game["name"])
                await self.config.guild(ctx.guild).users.set(users)
                if marked:
                    result_embed = discord.Embed(title="Games Installed", description=f"Marked {len(marked)} as installed", color=discord.Color.green())
                else:
                    result_embed = discord.Embed(title="No changes", color=discord.Color.grey())
            else:
                result_embed = discord.Embed(title="No games selected", color=discord.Color.grey())
            
            await message.delete()
            await ctx.send(embed=result_embed, delete_after=10)
        except discord.NotFound:
            pass
    
    @games.command(name="uninstall")
    async def games_uninstall(self, ctx: commands.Context, *, game_names: str = None):
        """Mark games as not installed."""
        all_games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        user_id = str(ctx.author.id)
        installed = users.get(user_id, {}).get("installed", [])
        if not installed:
            await ctx.send("No games marked as installed!")
            return
        if game_names:
            requested = self.parse_game_names(game_names)
            unmarked, not_installed, not_found = [], [], []
            for name in requested:
                game = self.find_game_by_name(all_games, name)
                if not game:
                    not_found.append(name)
                elif game["id"] not in installed:
                    not_installed.append(game["name"])
                else:
                    users[user_id]["installed"].remove(game["id"])
                    unmarked.append(game["name"])
            await self.config.guild(ctx.guild).users.set(users)
            parts = []
            if unmarked:
                parts.append(f"**Uninstalled ({len(unmarked)}):** {', '.join(unmarked)}")
            if not_installed:
                parts.append(f"**Not installed ({len(not_installed)}):** {', '.join(not_installed)}")
            if not_found:
                parts.append(f"**Not found ({len(not_found)}):** {', '.join(not_found)}")
            embed = discord.Embed(title="Update Installed", description="\n".join(parts), color=discord.Color.orange() if unmarked else discord.Color.grey())
            await ctx.send(embed=embed)
            return
        installed_games = [all_games[gid] for gid in installed if gid in all_games]
        sorted_games = sorted(installed_games, key=lambda x: x["name"].lower())
        embed = discord.Embed(title="Uninstall Games", description="Click games to toggle, then **Done**.", color=discord.Color.orange())
        view = MultiGameSelectView(self, ctx.author, sorted_games, "unown")
        message = await ctx.send(embed=embed, view=view)
        await view.wait()
        
        try:
            if view.cancelled:
                await message.delete()
                return
            
            if view.selected_games:
                unmarked = []
                for game in view.selected_games:
                    if game["id"] in users[user_id]["installed"]:
                        users[user_id]["installed"].remove(game["id"])
                        unmarked.append(game["name"])
                await self.config.guild(ctx.guild).users.set(users)
                if unmarked:
                    result_embed = discord.Embed(title="Games Uninstalled", description=f"Unmarked {len(unmarked)}", color=discord.Color.orange())
                else:
                    result_embed = discord.Embed(title="No changes", color=discord.Color.grey())
            else:
                result_embed = discord.Embed(title="No games selected", color=discord.Color.grey())
            
            await message.delete()
            await ctx.send(embed=result_embed, delete_after=10)
        except discord.NotFound:
            pass
    
    @games.command(name="setrank")
    async def games_setrank(self, ctx: commands.Context, rank: int, *, game_name: str):
        """Set rank for a game (1 = highest).
        
        Example: [p]games setrank 1 Counter-Strike 2
        """
        if rank < 1:
            await ctx.send("Rank must be 1 or higher!")
            return
        games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        user_id = str(ctx.author.id)
        game = self.find_game_by_name(games, game_name)
        if not game:
            await ctx.send(f"Game '{game_name}' not found!")
            return
        owned = users.get(user_id, {}).get("owned", [])
        if game["id"] not in owned:
            await ctx.send("You need to own this game first!")
            return
        if user_id not in users:
            users[user_id] = {"owned": [], "installed": [], "ranks": {}}
        if "ranks" not in users[user_id]:
            users[user_id]["ranks"] = {}
        users[user_id]["ranks"][game["id"]] = rank
        await self.config.guild(ctx.guild).users.set(users)
        await ctx.send(f"Set rank for **{game['name']}** to **{rank}**!")
    
    @games.command(name="mygames", aliases=["library", "mylibrary"])
    async def games_mygames(self, ctx: commands.Context):
        """Show your complete game library."""
        games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        user_id = str(ctx.author.id)
        user_data = users.get(user_id, {"owned": [], "installed": [], "ranks": {}})
        owned = user_data.get("owned", [])
        installed = user_data.get("installed", [])
        ranks = user_data.get("ranks", {})
        if not owned:
            await ctx.send("Your library is empty! Use `games own` or `games ownadd`.")
            return
        entries = []
        for gid in owned:
            if gid not in games:
                continue
            game = games[gid]
            rank = ranks.get(gid)
            entries.append({"id": gid, "name": game["name"], "rank": rank if rank else float('inf'), "display_rank": rank, "installed": gid in installed})
        entries.sort(key=lambda x: (x["rank"] == float('inf'), x["rank"], x["name"].lower()))
        items = []
        for e in entries:
            name = self.format_game_name(e["name"], e["installed"])
            if e["display_rank"]:
                items.append(f"{e['display_rank']}. {name}")
            else:
                items.append(f"- {name}")
        installed_count = len([e for e in entries if e["installed"]])
        await self.send_full_list(ctx, items, f"{ctx.author.display_name}'s Library", f"{len(entries)} owned | {installed_count} installed | ✅ = Installed")
    
    @games.command(name="usergames", aliases=["userlibrary"])
    async def games_usergames(self, ctx: commands.Context, *, member_name: str):
        """Show another user's game library.
        
        Example: [p]games usergames John
        """
        member = await self.find_member(ctx.guild, member_name)
        if not member:
            await ctx.send(f"Could not find member '{member_name}'!")
            return
        
        games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        user_id = str(member.id)
        user_data = users.get(user_id, {"owned": [], "installed": [], "ranks": {}})
        owned = user_data.get("owned", [])
        installed = user_data.get("installed", [])
        ranks = user_data.get("ranks", {})
        
        if not owned:
            await ctx.send(f"{member.display_name}'s library is empty!")
            return
        
        entries = []
        for gid in owned:
            if gid not in games:
                continue
            game = games[gid]
            rank = ranks.get(gid)
            entries.append({"id": gid, "name": game["name"], "rank": rank if rank else float('inf'), "display_rank": rank, "installed": gid in installed})
        entries.sort(key=lambda x: (x["rank"] == float('inf'), x["rank"], x["name"].lower()))
        
        items = []
        for e in entries:
            name = self.format_game_name(e["name"], e["installed"])
            if e["display_rank"]:
                items.append(f"{e['display_rank']}. {name}")
            else:
                items.append(f"- {name}")
        
        installed_count = len([e for e in entries if e["installed"]])
        await self.send_full_list(ctx, items, f"{member.display_name}'s Library", f"{len(entries)} owned | {installed_count} installed | ✅ = Installed")
    
    @games.command(name="whoowns", aliases=["whohas"])
    async def games_whoowns(self, ctx: commands.Context, *, game_name: str):
        """List users who own a specific game.
        
        Example: [p]games whoowns Counter-Strike 2
        """
        all_games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        
        game = self.find_game_by_name(all_games, game_name)
        if not game:
            await ctx.send(f"Game '{game_name}' not found!")
            return
        
        owners = []
        for uid, udata in users.items():
            if game["id"] in udata.get("owned", []):
                member = ctx.guild.get_member(int(uid))
                if member:
                    is_installed = game["id"] in udata.get("installed", [])
                    status = " ✅" if is_installed else ""
                    owners.append(f"- {member.display_name}{status}")
        
        if not owners:
            await ctx.send(f"No one owns **{game['name']}** yet!")
            return
        
        await self.send_full_list(ctx, owners, f"Users who own {game['name']}", f"{len(owners)} owner(s) | ✅ = Installed")
    
    @games.command(name="whoinstalled", aliases=["whohasinstalled"])
    async def games_whoinstalled(self, ctx: commands.Context, *, game_name: str):
        """List users who have a specific game installed.
        
        Example: [p]games whoinstalled Counter-Strike 2
        """
        all_games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        
        game = self.find_game_by_name(all_games, game_name)
        if not game:
            await ctx.send(f"Game '{game_name}' not found!")
            return
        
        installers = []
        for uid, udata in users.items():
            if game["id"] in udata.get("installed", []):
                member = ctx.guild.get_member(int(uid))
                if member:
                    installers.append(f"- {member.display_name}")
        
        if not installers:
            await ctx.send(f"No one has **{game['name']}** installed!")
            return
        
        await self.send_full_list(ctx, installers, f"Users with {game['name']} installed", f"{len(installers)} user(s)")
    
    @games.command(name="request")
    async def games_request(self, ctx: commands.Context, *, game_name: str):
        """Request a new game to be added."""
        games = await self.config.guild(ctx.guild).games()
        existing = self.find_game_by_name(games, game_name)
        if existing:
            await ctx.send(f"**{existing['name']}** already exists!")
            return
        requests = await self.config.guild(ctx.guild).game_requests()
        for req in requests.values():
            if req["name"].lower() == game_name.lower():
                await ctx.send(f"**{req['name']}** already requested!")
                return
        request_id = self.generate_id()
        requests[request_id] = {"id": request_id, "name": game_name, "description": "", "requested_by": str(ctx.author.id), "requested_at": datetime.utcnow().isoformat()}
        await self.config.guild(ctx.guild).game_requests.set(requests)
        embed = discord.Embed(title="Game Request Submitted", description=f"**{game_name}** submitted for approval.", color=discord.Color.blue())
        view = GameRequestApprovalView(self, request_id)
        await ctx.send(embed=embed, view=view)
    
    @games.command(name="requests")
    async def games_requests(self, ctx: commands.Context):
        """Show pending game requests."""
        requests = await self.config.guild(ctx.guild).game_requests()
        if not requests:
            await ctx.send("No pending requests!")
            return
        items = []
        for req in requests.values():
            requester = ctx.guild.get_member(int(req["requested_by"]))
            name = requester.display_name if requester else "Unknown"
            items.append(f"- **{req['name']}** (by {name})")
        await self.send_full_list(ctx, items, "Pending Game Requests")
    
    @games.command(name="shared")
    async def games_shared(self, ctx: commands.Context, *member_names: str):
        """Find games owned by all specified users.
        
        Example: [p]games shared John Jane Mike
        """
        games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        user_installed = users.get(str(ctx.author.id), {}).get("installed", [])
        
        if member_names:
            target = []
            for name in member_names:
                member = await self.find_member(ctx.guild, name)
                if member:
                    target.append(member)
                else:
                    await ctx.send(f"Could not find member '{name}'!")
                    return
        else:
            target = await self.get_channel_members_with_games(ctx.channel)
        
        if len(target) > 10:
            await ctx.send("Maximum 10 users!")
            return
        if len(target) < 2:
            await ctx.send("Need at least 2 users with game records!")
            return
        
        shared_ids = None
        for member in target:
            user_owned = set(users.get(str(member.id), {}).get("owned", []))
            shared_ids = user_owned if shared_ids is None else shared_ids & user_owned
        
        if not shared_ids:
            await ctx.send("No shared games!")
            return
        
        shared = sorted([games[gid] for gid in shared_ids if gid in games], key=lambda x: x["name"].lower())
        items = [f"- {self.format_game_name(g['name'], g['id'] in user_installed)}" for g in shared]
        names = ", ".join([m.display_name for m in target])
        await self.send_full_list(ctx, items, "Shared Games", f"Owned by: {names} | ✅ = Installed")
    
    @games.command(name="installed", aliases=["sharedinstalled"])
    async def games_installed_shared(self, ctx: commands.Context, *member_names: str):
        """Find games installed by all specified users.
        
        Example: [p]games installed John Jane Mike
        """
        games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        user_installed = users.get(str(ctx.author.id), {}).get("installed", [])
        
        if member_names:
            target = []
            for name in member_names:
                member = await self.find_member(ctx.guild, name)
                if member:
                    target.append(member)
                else:
                    await ctx.send(f"Could not find member '{name}'!")
                    return
        else:
            target = await self.get_channel_members_with_games(ctx.channel)
        
        if len(target) > 10:
            await ctx.send("Maximum 10 users!")
            return
        if len(target) < 2:
            await ctx.send("Need at least 2 users with game records!")
            return
        
        shared_ids = None
        for member in target:
            user_inst = set(users.get(str(member.id), {}).get("installed", []))
            shared_ids = user_inst if shared_ids is None else shared_ids & user_inst
        
        if not shared_ids:
            await ctx.send("No games installed by everyone!")
            return
        
        shared = sorted([games[gid] for gid in shared_ids if gid in games], key=lambda x: x["name"].lower())
        items = [f"- {g['name']} ✅" for g in shared]
        names = ", ".join([m.display_name for m in target])
        await self.send_full_list(ctx, items, "Shared Installed Games", f"Installed by: {names}")
    
    @games.command(name="top")
    async def games_top(self, ctx: commands.Context, *flags: str):
        """Show top ranked games for channel members.
        
        Flags:
            installed - Only show games everyone has installed
            shared - Only show games owned by everyone
        
        Example: [p]games top installed shared
        """
        installed_only = "installed" in [f.lower() for f in flags]
        shared_only = "shared" in [f.lower() for f in flags]
        
        games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        user_installed = users.get(str(ctx.author.id), {}).get("installed", [])
        members = await self.get_channel_members_with_games(ctx.channel)
        
        if not members:
            await ctx.send("No users with game records in this channel!")
            return
        
        member_ids = [str(m.id) for m in members]
        scores = {}
        
        for game_id, game in games.items():
            owners, installers = [], []
            rank_scores = []
            
            for mid in member_ids:
                ud = users.get(mid, {"owned": [], "installed": [], "ranks": {}})
                if game_id in ud.get("owned", []):
                    owners.append(mid)
                    if game_id in ud.get("installed", []):
                        installers.append(mid)
                    # Normalized ranking: convert rank to 0-1 scale
                    user_rank = ud.get("ranks", {}).get(game_id)
                    if user_rank:
                        # Lower rank = better, so invert for scoring
                        rank_scores.append(1.0 / user_rank)
                    else:
                        rank_scores.append(0.01)  # Unranked gets low score
            
            if not owners:
                continue
            if shared_only and len(owners) < len(member_ids):
                continue
            if installed_only and len(installers) < len(owners):
                continue
            
            # Calculate average normalized score (higher = better)
            avg_score = sum(rank_scores) / len(rank_scores) if rank_scores else 0
            
            scores[game_id] = {
                "name": game["name"],
                "owners": len(owners),
                "installers": len(installers),
                "score": avg_score,
                "is_installed": game_id in user_installed
            }
        
        if not scores:
            await ctx.send("No games match criteria!")
            return
        
        # Sort by score (higher is better), then by owner count
        sorted_games = sorted(scores.values(), key=lambda x: (-x["score"], -x["owners"], x["name"].lower()))
        
        items = []
        for i, g in enumerate(sorted_games, 1):
            name = self.format_game_name(g["name"], g["is_installed"])
            items.append(f"**{i}.** {name} (Owners: {g['owners']}/{len(member_ids)}, Installed: {g['installers']})")
        
        title = "Top Games"
        if installed_only:
            title += " (Installed)"
        if shared_only:
            title += " (Shared)"
        await self.send_full_list(ctx, items, title, f"Based on {len(members)} members with game records | ✅ = Installed")
    
    @games.command(name="session", aliases=["play"])
    async def games_session(self, ctx: commands.Context, *, title: str = None):
        """Start a gaming session for others to join."""
        session_id = self.generate_id()
        sessions = await self.config.guild(ctx.guild).play_sessions()
        session_title = title or f"{ctx.author.display_name}'s Gaming Session"
        sessions[session_id] = {
            "id": session_id,
            "title": session_title,
            "host_id": str(ctx.author.id),
            "participants": [str(ctx.author.id)],
            "channel_id": ctx.channel.id,
            "created_at": datetime.utcnow().isoformat(),
            "vote_id": None
        }
        await self.config.guild(ctx.guild).play_sessions.set(sessions)
        
        embed = discord.Embed(
            title=f"Gaming Session: {session_title}",
            description=f"Click **Join Session** to participate.\nOnce everyone has joined, the host can run `{ctx.prefix}games sessionvote` to vote on a game.",
            color=discord.Color.green()
        )
        embed.add_field(name="Participants (1)", value=f"1. {ctx.author.mention}", inline=False)
        embed.set_footer(text=f"Session ID: {session_id}")
        
        view = PlaySessionView(self, session_id, ctx.author)
        message = await ctx.send(embed=embed, view=view)
        view.message = message
    
    @games.command(name="sessionvote")
    async def games_sessionvote(self, ctx: commands.Context, session_id: str = None, max_choices: int = 1, timeout: int = 120):
        """Start a vote for a gaming session.
        
        Args:
            session_id: Optional session ID (uses most recent if not specified)
            max_choices: Maximum number of games to vote for (default: 1)
            timeout: Vote duration in seconds (default: 120)
        
        Only installed games shared by all participants are included.
        """
        sessions = await self.config.guild(ctx.guild).play_sessions()
        
        if not sessions:
            await ctx.send("No active sessions!")
            return
        
        if session_id:
            if session_id not in sessions:
                await ctx.send("Session not found!")
                return
            session = sessions[session_id]
        else:
            channel_sessions = [(sid, s) for sid, s in sessions.items() if s["channel_id"] == ctx.channel.id]
            if not channel_sessions:
                await ctx.send("No active sessions in this channel!")
                return
            session_id, session = max(channel_sessions, key=lambda x: x[1]["created_at"])
        
        if str(ctx.author.id) != session["host_id"] and not await self.is_admin(ctx.author, ctx.guild):
            await ctx.send("Only the session host or an admin can start a vote!")
            return
        
        if len(session["participants"]) < 2:
            await ctx.send("Need at least 2 participants to start a vote!")
            return
        
        # Find shared INSTALLED games among participants
        all_games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        
        shared_ids = None
        for participant_id in session["participants"]:
            installed = set(users.get(participant_id, {}).get("installed", []))
            shared_ids = installed if shared_ids is None else shared_ids & installed
        
        if not shared_ids:
            await ctx.send("No games are installed by all session participants! Participants need to mark games as installed.")
            return
        
        vote_games = sorted([all_games[gid] for gid in shared_ids if gid in all_games], key=lambda x: x["name"].lower())[:20]
        
        if not vote_games:
            await ctx.send("No shared installed games found!")
            return
        
        vote_id = self.generate_id()
        votes = await self.config.guild(ctx.guild).votes()
        votes[vote_id] = {
            "id": vote_id,
            "session_id": session_id,
            "games": [g["id"] for g in vote_games],
            "tallies": {},
            "user_votes": {},
            "allowed_voters": session["participants"].copy(),
            "channel_id": ctx.channel.id,
            "max_choices": max_choices,
            "created_at": datetime.utcnow().isoformat(),
            "created_by": str(ctx.author.id),
            "timeout": timeout
        }
        await self.config.guild(ctx.guild).votes.set(votes)
        
        session["vote_id"] = vote_id
        sessions[session_id] = session
        await self.config.guild(ctx.guild).play_sessions.set(sessions)
        
        mentions = " ".join([f"<@{uid}>" for uid in session["participants"]])
        
        embed = discord.Embed(
            title=f"Vote: {session['title']}",
            description=f"Session participants, vote for a game!\nMax {max_choices} choice(s). Click again to remove vote.\nTime limit: **{timeout} seconds**\n\n{mentions}",
            color=discord.Color.purple()
        )
        embed.add_field(name=f"Voted (0/{len(session['participants'])})", value="No votes yet", inline=False)
        embed.set_footer(text=f"Vote ID: {vote_id} | Only session participants can vote")
        
        view = SessionVoteView(self, vote_id, vote_games, max_choices, session["participants"])
        message = await ctx.send(embed=embed, view=view)
        view.message = message
        
        # Start vote timer
        task = asyncio.create_task(self.run_vote_timer(ctx.guild.id, ctx.channel.id, vote_id, timeout, message))
        self.active_votes[vote_id] = task
    
    @games.command(name="sessions")
    async def games_sessions(self, ctx: commands.Context):
        """Show active gaming sessions."""
        sessions = await self.config.guild(ctx.guild).play_sessions()
        if not sessions:
            await ctx.send("No active sessions!")
            return
        items = []
        for s in sessions.values():
            host = ctx.guild.get_member(int(s["host_id"]))
            vote_status = " (voting)" if s.get("vote_id") else ""
            items.append(f"- **{s['title']}**{vote_status} - Host: {host.display_name if host else 'Unknown'} ({len(s['participants'])} players) [ID: {s['id']}]")
        await self.send_full_list(ctx, items, "Active Gaming Sessions")
    
    @games.command(name="endsession")
    async def games_endsession(self, ctx: commands.Context, session_id: str = None):
        """End a gaming session."""
        sessions = await self.config.guild(ctx.guild).play_sessions()
        
        if not sessions:
            await ctx.send("No active sessions!")
            return
        
        if session_id:
            if session_id not in sessions:
                await ctx.send("Session not found!")
                return
            session = sessions[session_id]
        else:
            user_sessions = [(sid, s) for sid, s in sessions.items() 
                           if s["channel_id"] == ctx.channel.id and s["host_id"] == str(ctx.author.id)]
            if not user_sessions:
                if await self.is_admin(ctx.author, ctx.guild):
                    channel_sessions = [(sid, s) for sid, s in sessions.items() if s["channel_id"] == ctx.channel.id]
                    if channel_sessions:
                        session_id, session = max(channel_sessions, key=lambda x: x[1]["created_at"])
                    else:
                        await ctx.send("No active sessions in this channel!")
                        return
                else:
                    await ctx.send("No active sessions found that you host in this channel!")
                    return
            else:
                session_id, session = max(user_sessions, key=lambda x: x[1]["created_at"])
        
        if str(ctx.author.id) != session["host_id"] and not await self.is_admin(ctx.author, ctx.guild):
            await ctx.send("Only the session host or an admin can end a session!")
            return
        
        session_title = session["title"]
        
        if session.get("vote_id"):
            votes = await self.config.guild(ctx.guild).votes()
            if session["vote_id"] in votes:
                del votes[session["vote_id"]]
                await self.config.guild(ctx.guild).votes.set(votes)
            if session["vote_id"] in self.active_votes:
                self.active_votes[session["vote_id"]].cancel()
                del self.active_votes[session["vote_id"]]
        
        del sessions[session_id]
        await self.config.guild(ctx.guild).play_sessions.set(sessions)
        
        await ctx.send(f"Ended gaming session: **{session_title}**")
    
    @games.command(name="results")
    async def games_results(self, ctx: commands.Context, vote_id: Optional[str] = None):
        """Show vote results."""
        games = await self.config.guild(ctx.guild).games()
        votes = await self.config.guild(ctx.guild).votes()
        if not votes:
            await ctx.send("No active votes!")
            return
        if not vote_id:
            vote_id = max(votes.keys(), key=lambda k: votes[k]["created_at"])
        if vote_id not in votes:
            await ctx.send("Vote not found!")
            return
        vote = votes[vote_id]
        
        total_votes = sum(vote["tallies"].values()) if vote["tallies"] else 0
        sorted_results = sorted(vote["tallies"].items(), key=lambda x: -x[1])
        
        items = []
        for gid, count in sorted_results:
            if gid in games:
                percentage = (count / total_votes * 100) if total_votes > 0 else 0
                items.append(f"**{games[gid]['name']}** - {count} vote(s) ({percentage:.1f}%)")
        
        if not items:
            items = ["No votes yet!"]
        
        await self.send_full_list(ctx, items, "Vote Results", f"Vote ID: {vote_id} | Total votes: {total_votes}")
    
    @games.command(name="endvote")
    async def games_endvote(self, ctx: commands.Context, vote_id: Optional[str] = None):
        """End a vote and show results."""
        votes = await self.config.guild(ctx.guild).votes()
        if not votes:
            await ctx.send("No active votes!")
            return
        if not vote_id:
            vote_id = max(votes.keys(), key=lambda k: votes[k]["created_at"])
        if vote_id not in votes:
            await ctx.send("Vote not found!")
            return
        vote = votes[vote_id]
        if str(ctx.author.id) != vote["created_by"] and not await self.is_admin(ctx.author, ctx.guild):
            await ctx.send("Only creator or admin can end!")
            return
        
        # Cancel timer if exists
        if vote_id in self.active_votes:
            self.active_votes[vote_id].cancel()
            del self.active_votes[vote_id]
        
        # Show results
        games = await self.config.guild(ctx.guild).games()
        total_votes = sum(vote["tallies"].values()) if vote["tallies"] else 0
        sorted_results = sorted(vote["tallies"].items(), key=lambda x: -x[1])
        
        results = []
        for gid, count in sorted_results:
            if gid in games:
                percentage = (count / total_votes * 100) if total_votes > 0 else 0
                results.append(f"**{games[gid]['name']}** - {count} vote(s) ({percentage:.1f}%)")
        
        if not results:
            results = ["No votes were cast!"]
        
        embed = discord.Embed(
            title="Vote Results",
            description="\n".join(results),
            color=discord.Color.gold()
        )
        voters = len(vote["user_votes"])
        embed.set_footer(text=f"Total voters: {voters} | Total votes: {total_votes}")
        await ctx.send(embed=embed)
        
        # Clean up
        del votes[vote_id]
        await self.config.guild(ctx.guild).votes.set(votes)
    
    @games.command(name="installrequests")
    async def games_installrequests(self, ctx: commands.Context):
        """Show pending install requests."""
        games = await self.config.guild(ctx.guild).games()
        reqs = await self.config.guild(ctx.guild).install_requests()
        if not reqs:
            await ctx.send("No pending install requests!")
            return
        items = []
        for r in reqs.values():
            if r["game_id"] in games:
                items.append(f"- **{games[r['game_id']]['name']}** - {len(r['installed_by'])}/{len(r['target_users'])} installed")
        await self.send_full_list(ctx, items, "Install Requests")
    
    @games.group(name="admin")
    @commands.guild_only()
    async def games_admin(self, ctx: commands.Context):
        """Admin commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)
    
    @games_admin.command(name="setrole")
    @checks.admin_or_permissions(administrator=True)
    async def admin_setrole(self, ctx: commands.Context, role: discord.Role):
        """Set admin role."""
        await self.config.guild(ctx.guild).admin_role.set(role.id)
        await ctx.send(f"Admin role: **{role.name}**")
    
    @games_admin.command(name="add")
    async def admin_add(self, ctx: commands.Context, *, game_names: str):
        """Add games (comma-separated)."""
        if not await self.is_admin(ctx.author, ctx.guild):
            await ctx.send("No permission!")
            return
        games = await self.config.guild(ctx.guild).games()
        existing = {g["name"].lower() for g in games.values()}
        requested = self.parse_game_names(game_names)
        added, skipped = [], []
        for name in requested:
            if name.lower() in existing:
                skipped.append(name)
                continue
            gid = self.generate_id()
            games[gid] = {"id": gid, "name": name, "description": "", "added_by": str(ctx.author.id), "added_at": datetime.utcnow().isoformat()}
            existing.add(name.lower())
            added.append(name)
        await self.config.guild(ctx.guild).games.set(games)
        parts = []
        if added:
            parts.append(f"**Added ({len(added)}):** {', '.join(added)}")
        if skipped:
            parts.append(f"**Exists ({len(skipped)}):** {', '.join(skipped)}")
        embed = discord.Embed(title="Add Games", description="\n".join(parts), color=discord.Color.green() if added else discord.Color.orange())
        await ctx.send(embed=embed)
    
    @games_admin.command(name="remove")
    async def admin_remove(self, ctx: commands.Context, *, game_names: str):
        """Remove games (comma-separated)."""
        if not await self.is_admin(ctx.author, ctx.guild):
            await ctx.send("No permission!")
            return
        games = await self.config.guild(ctx.guild).games()
        users = await self.config.guild(ctx.guild).users()
        requested = self.parse_game_names(game_names)
        removed, not_found = [], []
        for name in requested:
            game = self.find_game_by_name(games, name)
            if not game:
                not_found.append(name)
                continue
            gid = game["id"]
            del games[gid]
            for uid in users:
                if gid in users[uid].get("owned", []):
                    users[uid]["owned"].remove(gid)
                if gid in users[uid].get("installed", []):
                    users[uid]["installed"].remove(gid)
                if gid in users[uid].get("ranks", {}):
                    del users[uid]["ranks"][gid]
            removed.append(game["name"])
        await self.config.guild(ctx.guild).games.set(games)
        await self.config.guild(ctx.guild).users.set(users)
        parts = []
        if removed:
            parts.append(f"**Removed ({len(removed)}):** {', '.join(removed)}")
        if not_found:
            parts.append(f"**Not found ({len(not_found)}):** {', '.join(not_found)}")
        embed = discord.Embed(title="Remove Games", description="\n".join(parts), color=discord.Color.orange() if removed else discord.Color.grey())
        await ctx.send(embed=embed)
    
    @games_admin.command(name="rename")
    async def admin_rename(self, ctx: commands.Context, old_name: str, *, new_name: str):
        """Rename a game."""
        if not await self.is_admin(ctx.author, ctx.guild):
            await ctx.send("No permission!")
            return
        games = await self.config.guild(ctx.guild).games()
        game = self.find_game_by_name(games, old_name)
        if not game:
            await ctx.send(f"'{old_name}' not found!")
            return
        old = game["name"]
        games[game["id"]]["name"] = new_name
        await self.config.guild(ctx.guild).games.set(games)
        await ctx.send(f"Renamed **{old}** to **{new_name}**!")
    
    @games_admin.command(name="requestinstall")
    async def admin_requestinstall(self, ctx: commands.Context, game_name: str, *member_names: str):
        """Request users install a game."""
        if not await self.is_admin(ctx.author, ctx.guild):
            await ctx.send("No permission!")
            return
        games = await self.config.guild(ctx.guild).games()
        game = self.find_game_by_name(games, game_name)
        if not game:
            await ctx.send(f"'{game_name}' not found!")
            return
        
        if member_names:
            targets = []
            for name in member_names:
                member = await self.find_member(ctx.guild, name)
                if member and not member.bot:
                    targets.append(member)
        else:
            targets = await self.get_channel_members_with_games(ctx.channel)
            if not targets:
                # Fall back to all channel members
                targets = [m for m in ctx.channel.members if not m.bot]
        
        target_ids = [str(m.id) for m in targets]
        req_id = self.generate_id()
        reqs = await self.config.guild(ctx.guild).install_requests()
        reqs[req_id] = {"id": req_id, "game_id": game["id"], "requested_by": str(ctx.author.id), "target_users": target_ids, "installed_by": [], "created_at": datetime.utcnow().isoformat()}
        await self.config.guild(ctx.guild).install_requests.set(reqs)
        mentions = " ".join([f"<@{uid}>" for uid in target_ids])
        embed = discord.Embed(title=f"Install Request: {game['name']}", description=f"Please install **{game['name']}**:\n{mentions}", color=discord.Color.blue())
        view = InstallRequestView(self, req_id, game["id"], game["name"])
        await ctx.send(embed=embed, view=view)
    
    @games_admin.command(name="approve")
    async def admin_approve(self, ctx: commands.Context, *, game_name: str):
        """Approve a game request."""
        if not await self.is_admin(ctx.author, ctx.guild):
            await ctx.send("No permission!")
            return
        requests = await self.config.guild(ctx.guild).game_requests()
        req_id = None
        for rid, r in requests.items():
            if r["name"].lower() == game_name.lower():
                req_id = rid
                break
        if not req_id:
            await ctx.send(f"No request for '{game_name}'!")
            return
        req = requests[req_id]
        games = await self.config.guild(ctx.guild).games()
        gid = self.generate_id()
        games[gid] = {"id": gid, "name": req["name"], "description": req.get("description", ""), "added_by": str(ctx.author.id), "added_at": datetime.utcnow().isoformat()}
        await self.config.guild(ctx.guild).games.set(games)
        del requests[req_id]
        await self.config.guild(ctx.guild).game_requests.set(requests)
        await ctx.send(f"Approved! **{req['name']}** added.")
    
    @games_admin.command(name="deny")
    async def admin_deny(self, ctx: commands.Context, *, game_name: str):
        """Deny a game request."""
        if not await self.is_admin(ctx.author, ctx.guild):
            await ctx.send("No permission!")
            return
        requests = await self.config.guild(ctx.guild).game_requests()
        req_id = None
        for rid, r in requests.items():
            if r["name"].lower() == game_name.lower():
                req_id = rid
                break
        if not req_id:
            await ctx.send(f"No request for '{game_name}'!")
            return
        req = requests[req_id]
        del requests[req_id]
        await self.config.guild(ctx.guild).game_requests.set(requests)
        await ctx.send(f"Denied **{req['name']}**.")
    
    @games_admin.command(name="import")
    async def admin_import(self, ctx: commands.Context, *, game_list: str):
        """Bulk import (one per line)."""
        if not await self.is_admin(ctx.author, ctx.guild):
            await ctx.send("No permission!")
            return
        games = await self.config.guild(ctx.guild).games()
        existing = {g["name"].lower() for g in games.values()}
        lines = [l.strip() for l in game_list.split("\n") if l.strip()]
        added, skipped = [], []
        for name in lines:
            if name.lower() in existing:
                skipped.append(name)
                continue
            gid = self.generate_id()
            games[gid] = {"id": gid, "name": name, "description": "", "added_by": str(ctx.author.id), "added_at": datetime.utcnow().isoformat()}
            existing.add(name.lower())
            added.append(name)
        await self.config.guild(ctx.guild).games.set(games)
        msg = f"Added {len(added)} games!"
        if skipped:
            msg += f" Skipped {len(skipped)} duplicates."
        await ctx.send(msg)
    
    @games_admin.command(name="clearsessions")
    async def admin_clearsessions(self, ctx: commands.Context):
        """Clear all sessions."""
        if not await self.is_admin(ctx.author, ctx.guild):
            await ctx.send("No permission!")
            return
        await self.config.guild(ctx.guild).play_sessions.set({})
        await ctx.send("Cleared sessions!")
    
    @games_admin.command(name="clearvotes")
    async def admin_clearvotes(self, ctx: commands.Context):
        """Clear all votes."""
        if not await self.is_admin(ctx.author, ctx.guild):
            await ctx.send("No permission!")
            return
        # Cancel all active vote timers
        for vote_id, task in list(self.active_votes.items()):
            task.cancel()
        self.active_votes.clear()
        await self.config.guild(ctx.guild).votes.set({})
        await ctx.send("Cleared votes!")


async def setup(bot: Red):
    await bot.add_cog(GameManager(bot))