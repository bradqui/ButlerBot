---
title: Parlor
parent: Command reference
nav_order: 24
permalink: /reference/parlor/
---

# Parlor

Parlor games: critiques, roasts, the emoji game and twenty questions.

For a task-by-task guide, see [Fun and games]({{ '/fun/' | relative_url }}).

{% raw %}
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

<a id="parlor"></a>
### !parlor

`!parlor`

**Who:** everyone

What's in ButlerBot's parlor: the games and toys, and how to start each one.

<a id="parlor-top"></a>
### !parlor top

`!parlor top`

**Who:** everyone · **Also:** `!parlor leaderboard`

The leaderboard for the parlor's guessing games (the emoji game and twenty questions).

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
