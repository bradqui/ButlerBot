---
title: ButlerFun
parent: Command reference
nav_order: 7
permalink: /reference/butlerfun/
---

# ButlerFun

AI extras: catch-up summaries, ButlerBot's judgments, text adventures, trivia writing and guess the game.

For a task-by-task guide, see [Fun and games]({{ '/fun/' | relative_url }}).

{% raw %}
<a id="adventure"></a>
### !adventure

`!adventure <setting>`

**Who:** everyone

Start a group text adventure in a new thread, narrated by ButlerBot.

Everyone in the thread plays by just typing what they do. ButlerBot waits a few seconds to gather everyone's
moves, then narrates what happens. End it with `!adventure stop` inside the thread.

**Example:** `!adventure a haunted space station where the AI has gone quiet`

<a id="adventure-stop"></a>
### !adventure stop

`!adventure stop`

**Who:** everyone · **Also:** `!adventure end`

End the adventure in this thread with a final scene (whoever started it, or a mod).

<a id="catchup"></a>
### !catchup

`!catchup`

**Who:** everyone

Get a summary of this channel since you last spoke, sent to you privately.

The text command sends it by DM; the `/catchup` slash command shows it only to you, right here.

<a id="guessgame"></a>
### !guessgame

`!guessgame`

**Who:** everyone · **Also:** `!guessthegame`

Gemini paints a game from the server's library in an unusual art style. First to type its name wins.

Hints appear after a minute. `!guessgame top` shows the leaderboard.

<a id="guessgame-stop"></a>
### !guessgame stop

`!guessgame stop`

**Who:** mods, or anyone with the manage messages permission

End the running round here and reveal the answer (mods).

<a id="guessgame-top"></a>
### !guessgame top

`!guessgame top`

**Who:** everyone · **Also:** `!guessgame leaderboard`

The guess-the-game leaderboard.

<a id="judge"></a>
### !judge

`!judge [messages=20]`

**Who:** everyone · **Also:** `!verdict`

Have ButlerBot settle the argument in this channel.

It reads the recent messages (20 by default, up to 60) and delivers a ruling, in character.

**Example:** `!judge` or `!judge 40`

<a id="maketrivia"></a>
### !maketrivia

`!maketrivia [count=20] <topic>`

**Who:** mods, or anyone with the manage messages permission · **Also:** `!trivia-make`, `!writetrivia`

Have Claude write a trivia list, ready to play with Red's trivia game (mods).

Use `our games` as the topic for questions about the games in this server's library. The list is saved
for the `trivia` cog, so you can start it right away.

**Examples:**
- `!maketrivia our games`
- `!maketrivia 15 1990s video game consoles`

{% endraw %}
