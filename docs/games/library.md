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
2. **Games you own:** tick them in a picker, or type names, one per line. Games the server doesn't have yet get added or requested for you.
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

Long lists show 8 games at a time, each with its numbers in small text underneath. Anyone can page through them with ◀ ▶, or skip ahead with the **Jump to** menu on long lists, for 15 minutes after they're posted. `/games library` and `/games wishlist` show your own list just to you.

**Name matching:**
- Names match loosely: "counterstrike 2" finds "Counter-Strike 2".
- If a name could be more than one game, ButlerBot asks which one you meant.

### Games the server doesn't have yet

A button offers to **request** the game. The request is a card with **Approve** and **Deny** buttons for game admins, and approving adds the game to your library automatically. When it's decided, the card shows the answer and you get a one-line ping that links to it. Some servers let members add games directly.

Requesting several games at once, for example while setting up your profile, makes **one card** for all of them instead of one each. You get a single ping once every game on it is decided.

{: .staff }
> On a card for several games, **Approve all** and **Deny all** decide them together, and Deny all asks first. **Review** opens a private list where you pick games and approve or deny just those. Rows marked ⚠️ are names ButlerBot couldn't confirm, so check their spelling. `!games admin approve <game>` and `deny <game>` work too, and update the card.

Before a new game is requested or added, ButlerBot looks up its proper title:
- **Capitalization fixes** apply on their own: "helldivers 2" becomes **HELLDIVERS 2**.
- **Real spelling changes** ask you first: "an eggtremely hard game" becomes **An Eggstremely Hard Game**.
- **Names it can't find** on Steam or the web ask you too: keep them, skip them, or cancel. Game admins see a warning on these requests, so they can check the spelling before approving.

Commas separate names typed on one line, except in numbers like "40,000". To keep a name with a comma, like "Papers, Please", put one name per line or use quotes.

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
- When a game on your wishlist goes on sale, or gets cheaper, you get one ping in the alerts channel: a card listing the deals, with everyone who wants one of them named once at the bottom.
- You won't be pinged if you've added the game to your library by then.

## Finding deals

When you're shopping for something to play together, ask for deals:

```
!games deals                 (everyone with a library)
!games deals session         (the players in this channel's session)
!games deals Alex Sam        (you and the people you name)
!games deals me              (just you)
!games deals new Alex Sam    (new releases instead of sales)
```

The card has up to three parts:
- **Some of you have these:** games in the server library that some of the group own and that are on sale, so the rest can catch up. Just for you, it's games other members have.
- **On your wishlists:** wishlisted games that are on sale right now.
- **You might like:** a few games picked by AI from Steam's current multiplayer sales, chosen to fit what the group owns, ranks and wants, each with a short reason. With `new`, it's picked from popular multiplayer games released in the last 90 days, and this is the only part.

Two menus under the card add any of its games to **your wishlist**, or mark them as **owned**; a game that isn't in the server library yet is added or requested first. Anyone can use them, and the reply is just for you.

Prices are US Steam prices. Nothing is posted on its own: the AI runs only when someone asks. If AI is unavailable, the last part shows Steam's most popular games instead.

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
