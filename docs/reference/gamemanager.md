---
title: GameManager
parent: Command reference
nav_order: 21
permalink: /reference/gamemanager/
---

# GameManager

Track the games your server owns, find something everyone can play, and vote on it.

Mark games with `!games own` and `!games install` (with no names, they open a picker).
Start a session with `!games session`, optionally with a time such as
`!games session friday 9pm Raid night`, and press **Start vote** once everyone has joined.

For a task-by-task guide, see [Your games]({{ '/games/library/' | relative_url }}).

{% raw %}
<a id="games"></a>
### !games

`!games`

**Who:** everyone · **Also:** `!game`, `!gm`

Your game library, play sessions, and votes on what to play.

<a id="games-admin"></a>
### !games admin

`!games admin`

**Who:** game admins only

Library management for game admins (server admins, or the role set with `!games admin setrole`).

<a id="games-admin-add"></a>
### !games admin add

`!games admin add <game_names>`

**Who:** game admins only · **Also:** `!games admin import`

Add games to the server library. Separate them with commas or put one per line.

Up to 10 names at a time are checked for their proper titles (typos and capitalization)
before adding; you confirm any corrections. Bigger lists are added as typed.

**Example:** `!games admin add Rocket League, Halo Infinite`

<a id="games-admin-approve"></a>
### !games admin approve

`!games admin approve <game_name>`

**Who:** game admins only

Approve a game request by name (or use the button on the request).

<a id="games-admin-clearsessions"></a>
### !games admin clearsessions

`!games admin clearsessions`

**Who:** game admins only

End every active session (and its vote).

<a id="games-admin-clearvotes"></a>
### !games admin clearvotes

`!games admin clearvotes`

**Who:** game admins only

Cancel every running vote without picking a winner.

<a id="games-admin-deny"></a>
### !games admin deny

`!games admin deny <game_name>`

**Who:** game admins only

Deny a game request by name (or use the button on the request).

<a id="games-admin-eventchannel"></a>
### !games admin eventchannel

`!games admin eventchannel [channel]`

**Who:** game admins only

Set the voice channel session events point to. Run with no channel to list them without one.

<a id="games-admin-events"></a>
### !games admin events

`!games admin events <enabled>`

**Who:** game admins only

List scheduled sessions in the server's Discord events (on by default; needs Manage Events).

<a id="games-admin-freegames"></a>
### !games admin freegames

`!games admin freegames <enabled>`

**Who:** game admins only

Also announce games that are free to keep on the Epic Games Store (in the sale alerts channel).

<a id="games-admin-memberadd"></a>
### !games admin memberadd

`!games admin memberadd <allowed>`

**Who:** game admins only

Let members add new games to the library themselves instead of requesting them.

<a id="games-admin-remove"></a>
### !games admin remove

`!games admin remove <game_names>`

**Who:** game admins only

Remove games from the library, and from everyone's owned and installed lists.

Asks for confirmation first, listing the exact games.

<a id="games-admin-rename"></a>
### !games admin rename

`!games admin rename <names>`

**Who:** game admins only

Rename a game.

**Example:** `!games admin rename CS2 -> Counter-Strike 2`

<a id="games-admin-requestinstall"></a>
### !games admin requestinstall

`!games admin requestinstall <game_name> [members...]`

**Who:** game admins only

Ask people to install a game; they confirm with a button.

Quote game names with spaces. Leave out the members to ask everyone in this channel who has a library.

**Example:** `!games admin requestinstall "Rocket League" Alex Sam`

<a id="games-admin-sales"></a>
### !games admin sales

`!games admin sales [channel]`

**Who:** game admins only

Turn on wishlist sale alerts in a channel, or run with no channel to turn them off.

Steam prices are checked every few hours. When a wishlisted game goes on sale (or gets cheaper), the
people who want it are pinged once.

<a id="games-admin-setrole"></a>
### !games admin setrole

`!games admin setrole [role]`

**Who:** admins, or anyone with the administrator permission

Set the game admin role (server admins only). Run with no role to clear it.

<a id="games-admin-settings"></a>
### !games admin settings

`!games admin settings`

**Who:** game admins only

Show the game manager's settings for this server.

<a id="games-admin-timezone"></a>
### !games admin timezone

`!games admin timezone <zone>`

**Who:** game admins only

Set the server's default timezone for session times (members can set their own).

<a id="games-endsession"></a>
### !games endsession

`!games endsession [session_id]`

**Who:** everyone

End your latest session in this channel, or a session by ID (host or game admin).

<a id="games-endvote"></a>
### !games endvote

`!games endvote [vote_id]`

**Who:** everyone

End a vote now and announce the winner (whoever started it, the session host, or a game admin).

<a id="games-here"></a>
### !games here

`!games here [session]`

**Who:** everyone · **Also:** `!games bump`

Bring this channel's game session card back down to the bottom, after chatter has buried it.

Cards also move down by themselves for the reminder, the start and a vote. Add a name if this channel has
more than one session.

<a id="games-install"></a>
### !games install

`!games install [game_names]`

**Who:** everyone

Mark games as installed. Separate several with commas. Installed games also count as owned.

With no names, opens a picker where you tick what you have installed.

**Example:** `!games install Rocket League, Valorant`

<a id="games-installed"></a>
### !games installed

`!games installed [members...]`

**Who:** everyone · **Also:** `!games sharedinstalled`

Find games everyone in a group has installed, ready to play right now.

Name the people, or leave it empty to use everyone in this channel who has a library.

<a id="games-installrequests"></a>
### !games installrequests

`!games installrequests`

**Who:** everyone

Show install requests from game admins and how many people have installed each game.

<a id="games-join"></a>
### !games join

`!games join [session]`

**Who:** everyone

Join a game session without finding its card.

With one session in this channel (or in the server), just type `!games join`. With more, add its name:
`!games join Raid night`.

<a id="games-leave"></a>
### !games leave

`!games leave [session]`

**Who:** everyone

Leave a game session without finding its card. Add its name if there's more than one.

<a id="games-lfg"></a>
### !games lfg

`!games lfg <game_name>`

**Who:** everyone · **Also:** `!games whoplays`, `!games letsplay`

Looking for group: ping everyone who has a game installed to see who wants to play.

You can ping once every 5 minutes.

**Example:** `!games lfg Rocket League`

<a id="games-list"></a>
### !games list

`!games list`

**Who:** everyone

Show every game in the server's library (💾 = you have it installed).

<a id="games-mygames"></a>
### !games mygames

`!games mygames`

**Who:** everyone · **Also:** `!games library`, `!games mylibrary`

Show your library, favorites first (💾 = installed).

<a id="games-newprofile"></a>
### !games newprofile

`!games newprofile`

**Who:** everyone · **Also:** `!games setup`, `!games profilesetup`

Set up your gaming profile step by step.

Walks you through your timezone, the games you own and have installed, your top 3 favorites, and a
wishlist of games you want (you get a ping when they go on sale). Every step can be skipped, and you
can run it again any time.

<a id="games-own"></a>
### !games own

`!games own [game_names]`

**Who:** everyone · **Also:** `!games ownadd`, `!games addowned`, `!games iown`

Add games you own to your library. Separate several with commas.

With no names, opens a picker where you tick the games you own (and untick ones you don't).
Games the server doesn't have yet can be requested (or added) with one button.

**Examples:**
- `!games own Rocket League, Halo Infinite`
- `!games own` (opens the picker)

<a id="games-recurring"></a>
### !games recurring

`!games recurring`

**Who:** everyone · **Also:** `!games repeating`

Repeating game sessions.

Start one with `!games session every friday 9pm Raid night` (or `every other friday`). Each session is
posted a day before it starts. This lists them; `skip` and `stop` manage them.

<a id="games-recurring-skip"></a>
### !games recurring skip

`!games recurring skip <schedule_id>`

**Who:** everyone

Skip the next occurrence of a repeating session (host or game admin).

<a id="games-recurring-stop"></a>
### !games recurring stop

`!games recurring stop <schedule_id>`

**Who:** everyone · **Also:** `!games recurring delete`, `!games recurring remove`

Stop a repeating session (host or game admin). Sessions already posted stay up.

<a id="games-request"></a>
### !games request

`!games request <game_names>`

**Who:** everyone

Ask for games to be added to the server library. Separate several with commas.

The bot looks up each game's proper title (fixing typos and capitalization) and asks
before using a corrected name. A game admin approves or denies each request with a button.

<a id="games-requests"></a>
### !games requests

`!games requests`

**Who:** everyone

Show pending game requests.

<a id="games-results"></a>
### !games results

`!games results [vote_id]`

**Who:** everyone

Show the current tally of a running vote (the latest one in this channel by default).

<a id="games-search"></a>
### !games search

`!games search <query>`

**Who:** everyone

Search the server's library by name.

<a id="games-session"></a>
### !games session

`!games session [time_and_title]`

**Who:** everyone · **Also:** `!games play`

Start a game session people can join with a button.

Optionally start with a time; everyone sees it in their own timezone, and players get
a reminder 15 minutes before and a ping at the start. Times are read in your timezone
(set it with `!games timezone`).

Scheduled sessions also show up in the server's Discord events. Start with `every` to repeat weekly
(or `every other` for every two weeks); each one is posted a day ahead. For the event, attach an image
as its banner and mention a voice channel to hold it there; the host can change these later with the
card's **Edit event** button.

**Examples:**
- `!games session` (starts now)
- `!games session Raid night`
- `!games session friday 9pm Raid night`
- `!games session in 2h Rocket League`
- `!games session tomorrow 8:30pm`
- `!games session every friday 9pm Raid night`

<a id="games-sessions"></a>
### !games sessions

`!games sessions`

**Who:** everyone

Show active game sessions.

<a id="games-sessionvote"></a>
### !games sessionvote

`!games sessionvote [options...]`

**Who:** everyone · **Also:** `!games vote`, `!games startvote`

Start a vote on what to play for the latest session in this channel (host or game admin).

Optional, in any order: how many games each person can pick (a number up to 10), how long
the vote runs (`90s`, `3m`), and a session ID. The **Start vote** button on the session does
the same with the defaults: 1 pick, 2 minutes.

Options are games everyone has installed; if there are none, games everyone owns; if there are
none of those either, games most players have installed.

**Examples:** `!games vote`, `!games vote 2 3m`

<a id="games-setrank"></a>
### !games setrank

`!games setrank <rank> <game_name>`

**Who:** everyone · **Also:** `!games rank`

Rank a game: 1 is your favorite. Rankings decide `!games top` and break vote ties.

Use 0 to clear a rank. Ranking a game adds it to your library if needed.

**Example:** `!games setrank 1 Counter-Strike 2`

<a id="games-shared"></a>
### !games shared

`!games shared [members...]`

**Who:** everyone

Find games everyone in a group owns.

Name the people, or leave it empty to use everyone in this channel who has a library.

**Example:** `!games shared Alex Sam Jordan`

<a id="games-timezone"></a>
### !games timezone

`!games timezone [zone]`

**Who:** everyone · **Also:** `!games tz`

Set the timezone used to read your session times.

Accepts names like `America/Chicago`, cities like `Chicago`, or abbreviations like `CST`.
Use `reset` to fall back to the server default. Run with nothing to see your current one.

<a id="games-top"></a>
### !games top

`!games top [filters...]`

**Who:** everyone

Rank games by how much the players in this channel like them.

Filters: `installed` (only games every owner has installed), `shared` (only games everyone owns).

**Example:** `!games top shared installed`

<a id="games-uninstall"></a>
### !games uninstall

`!games uninstall [game_names]`

**Who:** everyone

Mark games as no longer installed (they stay in your library). With no names, opens the picker.

<a id="games-unown"></a>
### !games unown

`!games unown [game_names]`

**Who:** everyone · **Also:** `!games removeowned`, `!games disown`

Remove games from your library (also clears their installed mark and rank).

With no names, opens the library picker.

<a id="games-unwant"></a>
### !games unwant

`!games unwant <game_name>`

**Who:** everyone · **Also:** `!games wishlistremove`

Remove a game from your wishlist.

<a id="games-usergames"></a>
### !games usergames

`!games usergames <member>`

**Who:** everyone · **Also:** `!games userlibrary`

Show someone else's library.

**Example:** `!games usergames Alex`

<a id="games-want"></a>
### !games want

`!games want <game_names>`

**Who:** everyone · **Also:** `!games wishlistadd`

Add games you want but don't own to your wishlist. Separate several with commas.

When a wishlisted game goes on sale on Steam, you get a ping (if sale alerts are on in this server).
The game doesn't need to be in the server library.

**Example:** `!games want Elden Ring, Baldur's Gate 3`

<a id="games-wanted"></a>
### !games wanted

`!games wanted`

**Who:** everyone · **Also:** `!games mostwanted`

The server's most-wanted games: who wants each one, and which are on sale.

<a id="games-whoinstalled"></a>
### !games whoinstalled

`!games whoinstalled <game_name>`

**Who:** everyone · **Also:** `!games whohasinstalled`

List who has a game installed.

<a id="games-whoowns"></a>
### !games whoowns

`!games whoowns <game_name>`

**Who:** everyone · **Also:** `!games whohas`

List who owns a game (💾 = has it installed).

<a id="games-wishlist"></a>
### !games wishlist

`!games wishlist [member]`

**Who:** everyone

Show your wishlist with current Steam prices, or someone else's.

<a id="session"></a>
### !session

`!session`

**Who:** everyone

Game sessions. On its own, brings this channel's session card down to you.

- `!session new friday 9pm Raid night` starts one (`!session new every friday 9pm` repeats weekly)
- `!session join` and `!session leave` (add its name if there's more than one)
- `!session vote` and `!session end` (host or game admin)
- `!sessions` lists them all

<a id="session-end"></a>
### !session end

`!session end [session]`

**Who:** everyone

End your session in this channel, or one by name (host or game admin).

<a id="session-here"></a>
### !session here

`!session here [session]`

**Who:** everyone · **Also:** `!session bump`

Bring a session card in this channel down to the bottom. Add its name if there's more than one.

<a id="session-join"></a>
### !session join

`!session join [session]`

**Who:** everyone

Join a game session. Add its name if there's more than one.

<a id="session-leave"></a>
### !session leave

`!session leave [session]`

**Who:** everyone

Leave a game session. Add its name if there's more than one.

<a id="session-new"></a>
### !session new

`!session new [time_and_title]`

**Who:** everyone · **Also:** `!session create`, `!session host`

Start a game session people can join.

Optionally start with a time (read in your timezone; everyone sees their own). Start with `every` to
repeat weekly. Attach an image for the Discord event's banner, and mention a voice channel to hold it there.
The same as `!games session`.

**Examples:** `!session new`, `!session new friday 9pm Raid night`, `!session new in 2h Rocket League`,
`!session new every friday 9pm`

<a id="session-vote"></a>
### !session vote

`!session vote [options...]`

**Who:** everyone

Start a vote on what to play for this channel's latest session (host or game admin).

Optional: how many games each person can pick (up to 10) and how long it runs (`90s`, `3m`).
**Examples:** `!session vote`, `!session vote 2 3m`

<a id="sessions"></a>
### !sessions

`!sessions`

**Who:** everyone

List the active game sessions, with links to their cards. The same as `!games sessions`.

{% endraw %}
