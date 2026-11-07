---
title: Parlor
parent: Command reference
nav_order: 24
permalink: /reference/parlor/
---

# Parlor

Parlor games: guess the game, the emoji game, twenty questions, adventures, judge, critiques, roasts and trivia.

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

<a id="critique"></a>
### !critique

`!critique [about]`

**Who:** everyone · **Also:** `!critic`

ButlerBot reviews a screenshot like a gallery critic, with a score out of 10.

Attach an image to the command, or reply to a message that has one. Add a few words to say what it is.

**Examples:**
- `!critique` with a screenshot attached
- `!critique my new hangar` as a reply to someone's screenshot

<a id="emojigame"></a>
### !emojigame

`!emojigame [mode]`

**Who:** everyone · **Also:** `!emoji`

Guess the game from a row of emoji. First to type its name wins.

Games come from the server's library; add `any` for any well-known game. Hints appear as time runs down,
and `!parlor top` shows the leaderboard.

**Examples:** `!emojigame` or `!emojigame any`

<a id="emojigame-stop"></a>
### !emojigame stop

`!emojigame stop`

**Who:** mods, or anyone with the manage messages permission

End the emoji round running here and reveal the answer (mods).

<a id="guessgame"></a>
### !guessgame

`!guessgame`

**Who:** everyone · **Also:** `!guessthegame`

Gemini paints a game from the server's library in an unusual art style. First to type its name wins.

Hints appear after a minute. `!parlor top` shows the leaderboard.

<a id="guessgame-stop"></a>
### !guessgame stop

`!guessgame stop`

**Who:** mods, or anyone with the manage messages permission

End the running round here and reveal the answer (mods).

<a id="guessgame-top"></a>
### !guessgame top

`!guessgame top`

**Who:** everyone · **Also:** `!guessgame leaderboard`

The leaderboard for the parlor's guessing games (the same as `!parlor top`).

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

<a id="parlor"></a>
### !parlor

`!parlor`

**Who:** everyone

What's in ButlerBot's parlor: the games and toys, and how to start each one.

<a id="parlor-top"></a>
### !parlor top

`!parlor top`

**Who:** everyone · **Also:** `!parlor leaderboard`

The leaderboard for the parlor's guessing games (guess the game, the emoji game and twenty questions).

<a id="roast"></a>
### !roast

`!roast [who]`

**Who:** everyone

ButlerBot roasts a game library: what you own, never install, rank and wish for.

Roast yourself any time. Someone else can only be roasted if they've opted in with `!roast optin`.

**Examples:** `!roast me` or `!roast @Mira`

<a id="roast-optin"></a>
### !roast optin

`!roast optin`

**Who:** everyone

Let anyone here roast your game library with `!roast @you`.

<a id="roast-optout"></a>
### !roast optout

`!roast optout`

**Who:** everyone

Stop others from roasting your game library (you can still roast yourself).

<a id="twentyq"></a>
### !twentyq

`!twentyq [mode]`

**Who:** everyone · **Also:** `!20q`, `!20questions`

Twenty questions: ButlerBot thinks of a game, and everyone asks yes-or-no questions in a thread.

End questions with `?`. Type the game's name when you know it; first right answer wins. Games come from the
server's library; add `any` for any well-known game. `!twentyq stop` in the thread gives up and reveals it.

**Examples:** `!twentyq` or `!twentyq any`

<a id="twentyq-stop"></a>
### !twentyq stop

`!twentyq stop`

**Who:** everyone · **Also:** `!twentyq giveup`, `!twentyq reveal`

Give up on the twenty questions round in this thread and reveal the answer.

{% endraw %}
