---
title: Your games
parent: Games
nav_order: 1
permalink: /games/library/
---

# Your games

Your library is what makes everything else work: finding games everyone owns, pinging the right people, and building fair votes.

## The quick way: profile setup

```
!games newprofile
```

You can also use `/games newprofile` (only you see it), or say "@ButlerBot set up my profile". A menu only you can use walks you through five steps. Every step is optional, and changes save as you go:

1. **Timezone:** so session times show correctly for you.
2. **Games you own:** tick them in a picker, or type names. Games the server doesn't have yet get added or requested for you.
3. **Installed games:** which of your games are on your computer right now.
4. **Favorites:** your #1, #2 and #3. These break ties in votes.
5. **Wishlist:** games you want but don't own. You get a ping when one goes on sale.

Run it again any time to update things. Menus like this expire after a while: their buttons grey out and say **Expired**, and anything you didn't save isn't kept.

## Adding and removing games

| Command | What it does |
|---|---|
| `!games own [games]` | Add games you own (comma-separated). With no names, opens a tick-box picker. |
| `!games unown [games]` | Remove games from your library. |
| `!games install [games]` | Mark games installed. Installing a game also means you own it. |
| `!games uninstall [games]` | Mark games not installed. They stay in your library. |
| `!games mygames` | Your library, favorites first (💾 = installed). |
| `!games usergames <member>` | Someone else's library. |
| `!games list` / `!games search <text>` | The whole server library, with how many people own and have installed each game. |

Long lists show 15 games at a time. Anyone can page through them with ◀ ▶ for 15 minutes after they're posted. `/games library` and `/games wishlist` show your own list just to you.

**Name matching:**
- Names match loosely: "counterstrike 2" finds "Counter-Strike 2".
- If a name could be more than one game, ButlerBot asks which one you meant.

### Games the server doesn't have yet

A button offers to **request** the game. Game admins approve requests with a button, and approving adds the game to your library automatically. Some servers let members add games directly.

Before a new game is requested or added, ButlerBot looks up its proper title:
- **Capitalization fixes** apply on their own: "helldivers 2" becomes **HELLDIVERS 2**.
- **Real spelling changes** ask you first: "an eggtremely hard game" becomes **An Eggstremely Hard Game**.

```
!games request Deep Rock Galactic
```

## Favorites

```
!games rank 1 Deadlock
!games rank 0 Deadlock      (clears it)
```

1 is your favorite. When a vote ties, the game the players rank higher wins.

## Wishlist and sales

| Command | What it does |
|---|---|
| `!games want <games>` | Add games you want (any Steam game, even ones not in the server library). |
| `!games unwant <game>` | Remove one. |
| `!games wishlist [member]` | Your wishlist with current Steam prices. |
| `!games wanted` | The server's most-wanted games, who wants each one, and which are on sale. People who already own a game don't count. |

**Sale alerts:**
- When sale alerts are on, ButlerBot checks Steam prices every few hours.
- When a game on your wishlist goes on sale, or gets cheaper, you get one ping in the alerts channel.
- You won't be pinged if you've added the game to your library by then.

{: .tip }
> Post a Steam store link in chat and ButlerBot replies with a card: the price, any sale, and who here owns it. It has **I own this** and **I want this** buttons.

## Your timezone

```
!games timezone America/Chicago
!games timezone CST
!games timezone            (shows yours)
```

Session times, stats heatmaps and reminders use it.

{: .staff }
> **Game admins:** `!games admin …`
> - `add` and `remove` (add accepts a list, one per line)
> - `rename Old -> New`
> - `approve` and `deny`
> - `requestinstall "<game>" [members…]`, which asks people to install a game
> - `memberadd true|false`, which lets members add games without a request
> - `timezone` for the server default
> - `sales [#channel]` turns on sale alerts; `freegames true|false` adds weekly free Epic games
> - `settings` shows them all on one card, with a warning if ButlerBot is missing a permission it needs
>
> Server admins set the game admin role with `!games admin setrole <role>`.
