# GameManager

Track the games your server owns, find something everyone can play, and vote on it.

- **Libraries:** everyone marks the games they own and have installed. Installing a game counts as owning it.
- **Pickers:** run `!games own` or `!games install` with no names to tick games in a searchable menu, 25 per page.
- **Finding games:** list what a group owns or has installed in common, and rank favorites.
- **Looking for group:** `!games lfg <game>` pings everyone who has a game installed.
- **Sessions:** start one now or schedule it ("friday 9pm"). People join with a button, get a reminder 15 minutes before, and get a ping at the start.
- **Votes:** the host presses **Start vote**. Everyone votes with buttons, ties are broken by people's rankings, and the winner is announced.
- **Slash commands:** `/games …` with autocomplete for game names.

Buttons keep working after restarts and reloads, and running votes pick back up.

## Your library

| Command | What it does |
|---|---|
| `!games own [games]` | Add games you own (comma-separated). With no names, opens the picker. Aliases `ownadd`, `iown` |
| `!games unown [games]` | Remove games from your library. With no names, opens the picker |
| `!games install [games]` | Mark games installed (and owned). With no names, opens the installed-games picker |
| `!games uninstall [games]` | Mark games as not installed. They stay in your library |
| `!games setrank <rank> <game>` | 1 = favorite; 0 clears. Alias `rank` |
| `!games mygames` | Your library, favorites first. Aliases `library`, `mylibrary` |
| `!games usergames <member>` | Someone else's library |
| `!games timezone [zone]` | Set the timezone your session times are read in (`America/Chicago`, `Chicago`, `CST`) |

**Name matching:**
- Names match ignoring case and punctuation ("counterstrike 2" finds "Counter-Strike 2").
- A partial name is used only when exactly one game fits. For example, "Halo" asks which one you meant when there are two Halo games.
- If a name isn't in the server library at all, a button offers to request it. Game admins, and members when `memberadd` is on, get a button to add it instead.
- After an approval, the game is also owned or installed for the requester, matching what they were trying to do.

## Finding something to play

| Command | What it does |
|---|---|
| `!games list` / `!games search <text>` | The server library (✅ = you have it installed) |
| `!games whoowns <game>` / `!games whoinstalled <game>` | Who has a game |
| `!games shared [members…]` | Games everyone named owns (no names = everyone in this channel with a library) |
| `!games installed [members…]` | Games everyone named has installed |
| `!games top [installed] [shared]` | The channel's favorites, by everyone's rankings |
| `!games lfg <game>` | Ping everyone who has it installed (once per 5 minutes per person) |
| `!games request <games>` | Ask for games to be added. A game admin approves with a button |
| `!games requests` / `!games installrequests` | Pending requests |

## Sessions and votes

```
!games session                          start now
!games session Raid night               with a title
!games session friday 9pm Raid night    scheduled (everyone sees it in their own timezone)
!games session in 2h Rocket League
```

**Times:**
- Accepted forms: `9pm`, `9:30 pm`, `21:00`, `tonight 9pm`, `tomorrow 8pm`, `friday 9pm`, `9pm fri`, `11/14 7pm`, `in 1h30m`, or a pasted Discord timestamp.
- Times are read in your timezone, falling back to the server default, then UTC.
- Sessions end on their own 12 hours after they start (or were created).

**Session buttons:** **Join**, **Leave**, **Start vote** (host or game admin), and **End session**.

**Vote options** come from the first of these that has any games:
1. Games everyone has installed.
2. Games everyone owns.
3. Games at least two players have installed, with counts on the buttons.

**How a vote runs:**
- Each person picks up to N games, and pressing a game again takes the vote back.
- The vote ends when everyone has voted or time runs out.
- A tie goes to the game the players rank higher; if that's still tied, one is picked at random.

| Command | What it does |
|---|---|
| `!games vote [picks] [duration] [session id]` | Start a vote, same as the button. E.g. `!games vote 2 3m`. Aliases `sessionvote`, `startvote` |
| `!games results [vote id]` | The tally so far |
| `!games endvote [vote id]` | End now and announce the winner |
| `!games sessions` | Active sessions with links |
| `!games endsession [session id]` | End your latest session here |

## Game admins

Game admins are server administrators, Red admins, the bot owner, or anyone with the role set by `!games admin setrole`.

| Command | What it does |
|---|---|
| `!games admin add <games>` | Add games (commas or one per line). Alias `import` |
| `!games admin remove <games>` | Remove games, and remove them from everyone's lists. Asks for confirmation |
| `!games admin rename Old -> New` | Rename a game |
| `!games admin approve <game>` / `deny <game>` | Handle requests (or use the buttons) |
| `!games admin requestinstall "<game>" [members…]` | Ask people to install a game; they confirm with a button |
| `!games admin memberadd <true/false>` | Let members add games themselves instead of requesting |
| `!games admin timezone <zone>` | The server's default timezone for session times |
| `!games admin setrole [role]` | Set the game admin role (server admins only) |
| `!games admin settings` | Show the settings |
| `!games admin clearsessions` / `clearvotes` | End all sessions / cancel all votes |

## Slash commands

The bot owner turns these on once:

```
!slash enable games
!slash sync
```

The `/games` commands are `own`, `unown`, `install`, `uninstall`, `library`, `rank`, `whoowns`, `lfg`, `shared`, `top`, `session`, `vote`, `endsession`, `request` and `timezone`.
- Game names autocomplete as you type, including after a comma.
- Library changes and pickers are only visible to you.

## Asking in plain English

With the Claude cog loaded, `!guide` (or an @mention of the bot) can explain these commands and run them for you. For example:

```
!guide add Rocket League to my games and mark it installed
```

It runs with your own permissions. Game-admin commands wait for you to press **Run**.

## Data

Everything is stored per server in Red's Config (identifier `8675309420`): games, each player's owned, installed and ranked games, requests, sessions and votes. Personal timezones are stored per user.

Timezone support needs the `tzdata` package (`!pipinstall tzdata`).
