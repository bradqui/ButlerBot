# GameManager

Track the games your server owns, find something everyone can play, and vote on it.

- **Libraries:** everyone marks the games they own and have installed. Installing a game counts as owning it.
- **Pickers:** run `!games own` or `!games install` with no names to tick games in a searchable menu, 25 per page.
- **Finding games:** list what a group owns or has installed in common, and rank favorites.
- **Profile setup:** `!games newprofile` walks you through your timezone, library, installed games, favorites and wishlist.
- **Looking for group:** `!games lfg <game>` pings everyone who has a game installed.
- **Sessions:** start one now, schedule it ("friday 9pm"), or repeat it every week. People join with a button (or by pressing **Interested** on the session's Discord event), get a reminder 15 minutes before (each session can set its own reminders), and get a ping at the start.
- **Wishlists:** list games you want, and get a ping when one goes on sale on Steam.
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
| `!games newprofile` | Set up everything above step by step. Every step is optional. Aliases `setup`, `profilesetup` |

## Profile setup

`!games newprofile` (or `/games newprofile`, or "@ButlerBot set up my profile") opens a five-step menu that only you can use:

1. **Timezone:** pick from common zones or type your own.
2. **Games you own:** tick them in the picker, or type names. Games the server doesn't have yet go through the usual name check, then are added or requested.
3. **Installed games:** a picker of just your games.
4. **Favorites:** choose your #1, #2 and #3. Votes use these to break ties.
5. **Wishlist:** type games you want. A name that isn't exact takes Steam's closest match, which the summary shows so you can fix it.

**Back**, **Next** and **Stop** work at every step, and changes save as you go.

## Wishlist and sale alerts

| Command | What it does |
|---|---|
| `!games want <games>` | Add games you want but don't own (any Steam game, comma-separated). If a name could be several games, a menu asks which. |
| `!games unwant <game>` | Remove one |
| `!games wishlist [member]` | Your wishlist with current Steam prices |
| `!games wanted` | The server's most-wanted games, who wants them, and which are on sale |

**Sale alerts:**
- When a game admin turns them on, Steam prices are checked every 6 hours.
- When a wishlisted game goes on sale, or gets a deeper discount, the people who want it are pinged once in the alerts channel.
- People who own the game by then aren't pinged.
- A sale that was already running when you added the game doesn't trigger an alert.

**Name matching:**
- Names match ignoring case and punctuation ("counterstrike 2" finds "Counter-Strike 2").
- A partial name is used only when exactly one game fits. For example, "Halo" asks which one you meant when there are two Halo games.
- If a name isn't in the server library at all, a button offers to request it. Game admins, and members when `memberadd` is on, get a button to add it instead.
- After an approval, the game is also owned or installed for the requester, matching what they were trying to do.
- Several new games requested at once (a profile import, or `!games request A, B, C`) share **one card**, with **Approve all**, **Review** (a private pick-and-decide menu) and **Deny all** (asks first). Each game's row shows ✅, Denied or ⚠️ (name not confirmed). The requester gets one ping when the last game is decided.

**Proper titles for new games:** before a game is requested or added, the bot looks up its official name.
1. **A close match already in the library:** "rocket leage" suggests the existing **Rocket League**.
2. **An exact name on Steam:** "helldivers 2" becomes **HELLDIVERS 2**.
3. **An AI web search,** when the Claude cog is loaded: "an eggtremely hard game" finds **An Eggstremely Hard Game**. This costs about 1¢ and is limited to 10 lookups per command. Lookups run four at a time.

**What happens next:**
- Fixes to capitalization or symbols are applied automatically.
- Real spelling changes ask first: **Use suggestion**, **Keep my spelling**, or **Cancel**.
- Names nothing could confirm ask too: **Keep it**, **Skip it** (when other names in the batch were fine), or **Cancel**. Kept ones are requested with a ⚠️ "couldn't confirm" line on the request card.
- Games found on Steam keep their Steam ID, and requests link to the store page.
- More than 25 names at once skip the lookups, and the check lists them as not looked up.

**Splitting names:** names typed on separate lines are split by line only, so "Papers, Please" survives. On a single line, commas split names, except thousands commas ("Warhammer 40,000: Darktide"). Quotes keep a name together either way.

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
!games session every friday 9pm Raid night        repeats weekly
!games session every other sunday 8pm             every two weeks
!games session every first friday 8pm             monthly (first … fourth, or last)
```

**Lines under the command** (Shift+Enter) set the rest:

```
!games session every first friday 8pm Star Citizen night
Game: Star Citizen                      set ahead: no vote
Reminders: 36h, 15m                     or none: just the ping at the start
Reminder note: Update your drivers      shown on the card with every reminder
Replaces: Friday Night Games            that schedule's night is off
Length: 3h                              how long the Discord event runs
```

**Repeating sessions:**
- The next one is set up as soon as the last one ends: its Discord event shows right away, and its card is posted a day before it starts (or at its earliest reminder). The host is whoever set it up.
- `!games recurring` lists them. `!games recurring skip <name or ID>` skips the next one, and `!games recurring stop <name or ID>` stops them (host or game admin).
- `!games recurring plan <name> <date>` (or the card's **Plan next** button on special nights) books another night.
- Times stay at the same local time across daylight saving changes.

**Special nights:** a session or schedule with `Replaces:` takes that schedule's night. When one lands on another schedule's night without saying, the bot asks **Replace it** or **Keep both**. A cancelled special night brings the regular one back.

**Editing:** the card's **Edit** button (host or game admin) opens a private menu with every setting: title and time, event details, game, reminders and what it replaces. On repeating sessions each form can also change future ones.

**Discord events:**
- Scheduled sessions also appear in the server's **Events** list.
- Pressing **Interested** there joins the session, and removing it leaves.
- The event starts when the session does, and ends or is cancelled with it.
- The bot needs the **Manage Events** permission.

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
| `!games admin reminders <times>` | The reminders new sessions get (`15m`, `1d, 1h` or `none`) |
| `!games admin setrole [role]` | Set the game admin role (server admins only) |
| `!games admin sales [#channel]` | Turn on wishlist sale alerts in a channel (no channel turns them off) |
| `!games admin freegames <true/false>` | Also announce games that are free to keep on the Epic Games Store, in the sale alerts channel |
| `!games admin events <true/false>` | List scheduled sessions in Discord events (on by default) |
| `!games admin eventchannel [voice channel]` | Point session events at your usual voice channel. With no channel, they list the text channel as the location |
| `!games admin settings` | Show the settings |
| `!games admin clearsessions` / `clearvotes` | End all sessions / cancel all votes |

## Slash commands

The bot owner turns these on once:

```
!slash enable games
!slash sync
```

The `/games` commands are `own`, `unown`, `install`, `uninstall`, `library`, `rank`, `whoowns`, `lfg`, `shared`, `top`, `session` (with a `weekly` option), `vote`, `endsession`, `request`, `timezone`, `newprofile`, `want` and `wishlist`.
- Game names autocomplete as you type, including after a comma.
- Library changes and pickers are only visible to you.

## Asking in plain English

With the Claude cog loaded, `!butler` (or an @mention of the bot) can explain these commands and run them for you. For example:

```
!butler add Rocket League to my games and mark it installed
!butler set up my gaming profile
```

It runs with your own permissions. Game-admin commands wait for you to press **Run**.

The butler can also look things up before answering:
- anyone's library and wishlist
- who owns or has installed a game, or whether it's been requested
- active sessions and votes

So questions like `!butler what games do Alex and I both have installed?` or `!butler is Barony installed for me?` get real answers.

## Data

Everything is stored per server in Red's Config (identifier `8675309420`): games, each player's owned, installed and ranked games, requests, sessions, votes, repeating schedules and wishlists (by Steam app ID, with the last price seen). Personal timezones are stored per user.

Timezone support needs the `tzdata` package (`!pipinstall tzdata`).
