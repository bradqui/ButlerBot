# GameManager Cog for Red-DiscordBot

A comprehensive game library management system for Discord servers. Track owned and installed games, rank preferences, find shared games among friends, organize gaming sessions, and run voting polls.

## Features

- **Personal Game Library** - Track which games you own and have installed
- **Game Rankings** - Rank your games by preference (1 = highest)
- **Multi-Select Support** - Add/remove multiple games at once via buttons or text commands
- **Shared Game Discovery** - Find games owned by multiple users
- **Ranked-Choice Scoring** - See top games based on combined user rankings
- **Gaming Sessions** - Start sessions, gather players, then vote on what to play
- **Session Voting** - Vote restricted to session participants on their shared games
- **Game Requests** - Users can request new games for admin approval
- **Install Requests** - Admins can request users install specific games

## Installation

1. Copy the `gamemanager` folder to your Red-DiscordBot cogs directory
2. Load the cog:
   ```
   [p]load gamemanager
   ```

## Commands

### Basic Commands

| Command | Description |
|---------|-------------|
| `[p]games list` | Show all available games (full list) |
| `[p]games search <query>` | Search for games by name |
| `[p]games mygames` | View your complete game library with ranks |

### Managing Your Library

#### Adding Games You Own

**Interactive Selection:**
```
[p]games own
```
Opens a multi-select button menu. Click games to toggle selection, then click **Done**.

**By Name (Single or Multiple):**
```
[p]games ownadd Counter-Strike 2
[p]games ownadd Counter-Strike 2, Valorant, Apex Legends
[p]games ownadd "Left 4 Dead 2", "Team Fortress 2"
```
- Separate games with commas
- Use quotes for games with commas in their name
- Aliases: `addowned`, `iown`

#### Removing Games

**Interactive Selection:**
```
[p]games unown
```

**By Name:**
```
[p]games unown Counter-Strike 2, Valorant
```
- Aliases: `removeowned`, `disown`

#### Marking Games as Installed

**Interactive Selection:**
```
[p]games install
```

**By Name:**
```
[p]games install Counter-Strike 2, Valorant
```

#### Marking Games as Uninstalled

**Interactive Selection:**
```
[p]games uninstall
```

**By Name:**
```
[p]games uninstall Counter-Strike 2, Valorant
```

### Ranking Games

Set a rank for a game you own (1 = highest preference):
```
[p]games setrank "Counter-Strike 2" 1
[p]games setrank Valorant 2
```

### Finding Shared Games

Find games owned by all mentioned users:
```
[p]games shared @user1 @user2 @user3
```

Without mentions, uses all members who can see the current channel:
```
[p]games shared
```
- Maximum 10 users
- Minimum 2 users required

### Top Games (Ranked-Choice)

Show top-ranked games for channel members:
```
[p]games top
[p]games top true        # Installed only
[p]games top false true  # Shared only (owned by everyone)
```

**Scoring:**
- Sums all user ranks for each game
- Unranked games default to rank 100
- Lower total score = higher priority

### Requesting New Games

Request a game to be added (requires admin approval):
```
[p]games request Elden Ring
```

View pending requests:
```
[p]games requests
```

---

## Gaming Sessions

Gaming sessions allow you to gather players first, then vote on what game to play based on games everyone in the session owns.

### Session Workflow

1. **Start a session** - Host creates a general gaming session
2. **Players join** - Others click the Join button
3. **Start vote** - Host calls for a vote on shared games
4. **Vote** - Only session participants can vote
5. **Play** - Check results and play the winning game!

### Session Commands

**Start a gaming session:**
```
[p]games session
[p]games session Friday Night Gaming
[p]games play Game Night
```
- Optionally provide a title/description
- You automatically join as the first participant
- Aliases: `play`

**View active sessions:**
```
[p]games sessions
```

**Start a vote for your session:**
```
[p]games sessionvote
[p]games sessionvote <session_id> 2
```
- Only session host or admin can start
- Needs at least 2 participants
- Vote options are games **shared by all participants**
- Only session participants can vote
- Second argument sets max choices (default: 1)

**View vote results:**
```
[p]games results
[p]games results <vote_id>
```

**End a vote:**
```
[p]games endvote
```

**End a session:**
```
[p]games endsession
[p]games endsession <session_id>
```
- Only session host or admin can end
- Also cleans up associated vote

### Quick-Vote (Channel-Based)

For a quick vote without a session (all channel members can vote):
```
[p]games vote
[p]games vote 3
```

---

## Admin Commands

All admin commands require either:
- Server Administrator permission, OR
- The designated admin role (set with `setrole`)

### Setup

Set the admin role:
```
[p]games admin setrole @GameAdmin
```

### Managing Games

**Add games:**
```
[p]games admin add Counter-Strike 2
[p]games admin add Counter-Strike 2, Valorant, Apex Legends
```

**Remove games:**
```
[p]games admin remove Counter-Strike 2
[p]games admin remove Counter-Strike 2, Valorant
```

**Rename a game:**
```
[p]games admin rename "CS2" Counter-Strike 2
```

**Bulk import (one per line):**
```
[p]games admin import
Counter-Strike 2
Valorant
Apex Legends
Overwatch 2
```

### Handling Requests

**Approve a game request:**
```
[p]games admin approve Elden Ring
```

**Deny a game request:**
```
[p]games admin deny Elden Ring
```

### Install Requests

Request specific users (or all channel members) to install a game:
```
[p]games admin requestinstall "Counter-Strike 2" @user1 @user2
[p]games admin requestinstall Valorant
```

View pending install requests:
```
[p]games installrequests
```

### Cleanup

Clear all gaming sessions:
```
[p]games admin clearsessions
```

Clear all votes:
```
[p]games admin clearvotes
```

---

## Command Aliases

| Primary | Aliases |
|---------|---------|
| `games` | `game`, `gm` |
| `ownadd` | `addowned`, `iown` |
| `unown` | `removeowned`, `disown` |
| `mygames` | `library`, `mylibrary` |
| `session` | `play` |

---

## Data Storage

All data is stored per-server using Red's Config system:

- **Games** - Server-wide game list with names and descriptions
- **Users** - Per-user owned games, installed games, and rankings
- **Game Requests** - Pending requests for new games
- **Gaming Sessions** - Active sessions with participants
- **Votes** - Active voting polls (session or channel-based)
- **Install Requests** - Admin requests for users to install games

Data persists across bot restarts.

---

## Examples

### Setting Up Your Library

```
# Add multiple games at once
[p]games ownadd Counter-Strike 2, Valorant, Apex Legends, Minecraft

# Mark some as installed
[p]games install Counter-Strike 2, Minecraft

# Set your rankings
[p]games setrank "Counter-Strike 2" 1
[p]games setrank Minecraft 2
[p]games setrank Valorant 3

# View your library
[p]games mygames
```

### Organizing a Game Night

```
# 1. Start a session
[p]games session Friday Night Gaming

# 2. Wait for friends to click "Join Session"

# 3. Check who's joined
[p]games sessions

# 4. Start the vote (host only)
[p]games sessionvote

# 5. Everyone votes by clicking buttons

# 6. Check results
[p]games results

# 7. End the session when done
[p]games endsession
```

### Finding Games to Play

```
# See what games your group shares
[p]games shared @friend1 @friend2 @friend3

# See top-ranked games for the channel
[p]games top

# Quick vote for channel members
[p]games vote 2
```

---

## Tips

1. **Use quotes** for game names with spaces when using text commands:
   ```
   [p]games setrank "Counter-Strike 2" 1
   ```

2. **Build your library first** - Session votes only show games that ALL participants own

3. **Interactive menus** support pagination - use the navigation buttons to see more games

4. **Rankings affect scoring** - set ranks on your favorite games to influence the `top` command results

5. **Session votes are restricted** - only participants who joined the session can vote

6. **Buttons persist** - Session and vote buttons remain functional even after bot restarts

---

## Support

For issues or feature requests, contact your server administrator or the bot maintainer.
