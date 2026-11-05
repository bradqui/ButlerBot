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
moves, then narrates what happens. End it with `!adventure stop` inside the thread, for a final scene and a
picture of it. Set the character you play with `!adventure bio`.

**Example:** `!adventure a haunted space station where the AI has gone quiet`

<a id="adventure-bio"></a>
### !adventure bio

`!adventure bio [text]`

**Who:** everyone · **Also:** `!adventure character`

Set the character you play in every adventure (up to 200 characters).

The narrator uses it in every adventure you join. Anything you say during an adventure ("my character has
dyed her hair green") wins for that adventure only; your bio stays as it is.

**Examples:**
- `!adventure bio` shows yours (`!adventure bio @member` shows theirs)
- `!adventure bio a red-haired dwarf engineer with a bad knee and a fear of birds`
- `!adventure bio clear` removes yours (mods: `!adventure bio clear @member`)

<a id="adventure-stop"></a>
### !adventure stop

`!adventure stop`

**Who:** everyone · **Also:** `!adventure end`

End the adventure in this thread with a final scene and a picture of it (whoever started it, or a mod).

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

`!maketrivia [count=30] <topic>`

**Who:** mods, or anyone with the manage messages permission · **Also:** `!trivia-make`, `!writetrivia`

Have Claude write a trivia list, ready to play with Red's trivia game (mods).

Writes 30 questions unless you give a number (10-100). Running it again on the same topic adds new
questions to the list instead of replacing it. Use `our games` as the topic for questions about the games in
this server's library.

**Examples:**
- `!maketrivia our games`
- `!maketrivia 50 1990s video game consoles`

<a id="maketrivia-redo"></a>
### !maketrivia redo

`!maketrivia redo [count=30] <topic>`

**Who:** mods, or anyone with the manage messages permission

Throw away a trivia list and write it again from scratch (mods).

**Example:** `!maketrivia redo 40 our games`

<a id="maketrivia-remove"></a>
### !maketrivia remove

`!maketrivia remove <name> <which>`

**Who:** mods, or anyone with the manage messages permission · **Also:** `!maketrivia delete`

Remove questions from a trivia list ButlerBot wrote (mods).

Give the question numbers from `!maketrivia show`, or part of the question's text. Put quotes around a list
name with spaces, or use its saved name (`our_games` or `bb_our_games`).

**Examples:**
- `!maketrivia remove our_games 4 17`
- `!maketrivia remove our_games which year was Barony released`

<a id="maketrivia-show"></a>
### !maketrivia show

`!maketrivia show [name]`

**Who:** mods, or anyone with the manage messages permission

Show a trivia list ButlerBot wrote, numbered, with the answers behind spoilers (mods).

A list is sent to you by DM, so players don't see the answers, with a ✅ on your command. Leave out the name
to see every list, right here. Long lists page with ◀ ▶.

**Example:** `!maketrivia show our games`

{% endraw %}
