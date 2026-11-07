---
title: Fun and games
nav_order: 6
permalink: /fun/
---

# Fun and games

`!parlor` lists everything on this page in one card.

## Guessing games

`!parlor top` is the leaderboard for all three guessing games, with each person's wins at each one.

### Guess the game

```
!guessgame
```

ButlerBot picks a game from the server's library and has Gemini paint it in an unusual style ("as a medieval tapestry", "as 8-bit pixel art").
- **How a round runs:** the first person to type the game's name wins. Close misspellings count, and so does "is it Barony?".
- **Hints:** they appear after 1 and 2 minutes, and the answer is revealed at 3.
- **Stopping:** mods can end a round with `!guessgame stop`.

### Emoji game

```
!emojigame
!emojigame any
```

ButlerBot spells out a game in emoji (🧟🔫🚁🏝️), and the first person to type its name wins.
- **Which games:** games from the server's library, or any well-known game with `any`.
- **How a round runs:** close misspellings count, and "is it Barony?" works too. Hints appear as time runs down, and the answer is revealed after 2 minutes.
- **Stopping:** mods can end a round with `!emojigame stop`.

### Twenty questions

```
!twentyq
!twentyq any
```

ButlerBot thinks of a game and opens a thread. Everyone asks yes-or-no questions there.
- **Asking:** end a question with `?`. Messages without one are just chat.
- **Guessing:** type the game's name at any time. The first right answer wins.
- **The limit:** after 20 questions you get 2 more minutes for last guesses, then the answer is revealed.
- **Giving up:** `!twentyq stop` in the thread reveals the answer.
- **Idle rounds:** a round with no questions for 15 minutes ends on its own.

## Critiques and roasts

### Critique

```
!critique
!critique my new hangar
```

Attach a screenshot to the command, or reply to someone's screenshot with it. ButlerBot reviews it like a gallery critic and gives it a score out of 10. Add a few words to say what it is.

### Roast

```
!roast me
!roast @Mira
```

ButlerBot roasts a game library: what you own, never install, rank and wish for, compared with the rest of the server.
- **Yourself:** you can always roast your own library.
- **Others:** only people who've opted in with `!roast optin`. `!roast optout` turns it off again.
- **What's off limits:** the roast sticks to games and habits, never looks or real life.

## Trivia

```
!trivia list                 see the available quizzes
!trivia games                start one
!trivia games anime          mix several
!trivia stop                 end it (whoever started it, or a mod)
!trivia leaderboard          the server's best
```

To answer, just type in the channel; capitalization doesn't matter.

**Making your own quiz (mods):** ButlerBot writes a new quiz with AI and saves it so you can play it right away. `our games` asks about the games in the server's library.

```
!maketrivia our games
!maketrivia 50 1990s video game consoles
```

- **Size:** 30 questions unless you give a number (10–100).
- **Name:** the quiz is saved as `bb_<topic>`, so start it with `!trivia bb_our_games`.
- **Growing a quiz:** run `!maketrivia` on the same topic again to add new questions. ButlerBot skips the ones it already wrote, so a quiz can grow to 300 questions and stay fresh.

**Managing quizzes (mods):**

```
!maketrivia show                          every quiz ButlerBot wrote
!maketrivia show our games                numbered questions and answers, sent to your DMs
!maketrivia remove our_games 4 17         drop questions by number
!maketrivia remove our_games release year drop the one question containing those words
!maketrivia redo our games                throw it away and write it again
```

`show` with a quiz name sends the questions and answers to your DMs, so players can't see them, and puts a ✅ on your command. If your DMs are closed, it's posted in the channel instead, with the answers behind spoilers. Long quizzes page 8 questions at a time with ◀ ▶, plus a **Jump to** menu. A failed `redo` leaves the old quiz as it was.

{: .staff }
> **Trivia settings** (mods): `!triviaset maxscore`, `timelimit`, `stopafter`, `revealanswer`, `usespoilers`, `botplays`, `showsettings`.

## Text adventures

```
!adventure a haunted space station where the AI has gone quiet
```

ButlerBot opens a thread and narrates a story everyone can play.
- **Playing:** just type what you do.
- **Turns:** ButlerBot waits a few seconds to gather everyone's moves, then tells you what happens. It remembers about the last 100 turns.
- **Ending:** `!adventure stop` in the thread writes a final scene, and Gemini paints a picture of it. Whoever started it, or a mod, can end it.
- **Keep it PG-13:** fights happen, but without gore, and nothing sexual. If a move goes too far, the narrator tones it down or ignores it and carries on.

**Your character:** set who you play once, and the narrator uses it in every adventure you join.

```
!adventure bio a red-haired dwarf engineer with a bad knee and a fear of birds
!adventure bio                 see yours (or !adventure bio @someone)
!adventure bio clear           remove it
```

- **Length:** up to 200 characters.
- **What's allowed:** looks, skills, quirks and backstory. Bios that are sexual, gory, hateful, about real people, or that make you unbeatable or boss the narrator around are turned down.
- **Changing it for one story:** say it in the adventure ("my character shaved her beard for the disguise"). That counts for that adventure only; your bio stays as it is.

{: .staff }
> Mods can remove someone's bio with `!adventure bio clear @member`.

## Settle an argument

```
!judge
!judge 40
```

ButlerBot reads the recent messages (20 by default, up to 60) and delivers a ruling, in character: each side summed up, a verdict, and a penalty for the loser.

## Summarize a link

Someone posted a long article? (Videos can't be summarized.)
- **Just for you:** right-click the message (long-press on mobile) → **Apps** → **Summarize link**. You get a three-line summary that only you can see.
- **For everyone:** click the 📄 that ButlerBot adds under the link, and the summary is posted in the channel.

Pictures and GIFs aren't summarized. See [Reminders and auto-replies]({{ '/speakup/' | relative_url }}).

## Quick fun

| Command | What it does |
|---|---|
| `!8 <question?>` (or `!8ball`) | Ask the magic 8-ball. End with a `?`. |
| `!roll [max]` | Random number from 1 to max (default 100). |
| `!flip [member]` | Flip a coin, or flip someone upside down. |
| `!choose <a> <b> [c…]` | Picks one. Quote options with spaces. |
| `!rps <rock\|paper\|scissors>` | Rock, paper, scissors against the bot. |
| `!urban <word>` | Urban Dictionary. |
| `!lmgtfy <search>` | A "let me google that for you" link. |
| `!stopwatch` | Start or stop your stopwatch. |
| `!draw <prompt>` | Make an image. See [AI chat and images]({{ '/ai/' | relative_url }}). |

## Handy tools

| Command | What it does |
|---|---|
| `!userinfo [member]` / `!names <member>` | Someone's join date, roles and previous names. |
| `!serverinfo` | About the server. |
| `!selfrole list` / `!selfrole <role>` | See and toggle roles you can give yourself. |
| `!chatchart [#channel] [messages]` | Pie chart of who's been talking most. For deeper numbers, see [Server stats]({{ '/stats/' | relative_url }}). |
| `!mywarnings` | Your own warnings, if any. |
| `!info` / `!uptime` | About the bot. |
| `!contact <message>` | Send a message to the bot's owner. |
| `!mydata whatdata` / `!mydata forgetme` | What the bot stores about you, and how to delete it. |
