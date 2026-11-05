---
title: Fun and games
nav_order: 6
permalink: /fun/
---

# Fun and games

## Guess the game

```
!guessgame
```

ButlerBot picks a game from the server's library and has Gemini paint it in an unusual style ("as a medieval tapestry", "as 8-bit pixel art").

**How a round runs:**
- The first person to type the game's name wins. Close misspellings count.
- Hints appear after 1 and 2 minutes, and the answer is revealed at 3.

**Commands:**
- `!guessgame top` is the leaderboard.
- Mods can end a round with `!guessgame stop`.

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
!maketrivia show our games                numbered questions, answers behind spoilers
!maketrivia remove our_games 4 17         drop questions by number
!maketrivia remove our_games release year drop the one question containing those words
!maketrivia redo our games                throw it away and write it again
```

`show` reveals the answers, so run it somewhere players won't see it. A failed `redo` leaves the old quiz as it was.

{: .staff }
> **Trivia settings** (mods): `!triviaset maxscore`, `timelimit`, `stopafter`, `revealanswer`, `usespoilers`, `botplays`, `showsettings`.

## Text adventures

```
!adventure a haunted space station where the AI has gone quiet
```

ButlerBot opens a thread and narrates a story everyone can play.
- **Playing:** just type what you do.
- **Turns:** ButlerBot waits a few seconds to gather everyone's moves, then tells you what happens.
- **Ending:** `!adventure stop` in the thread writes a final scene. Whoever started it, or a mod, can end it.

## Settle an argument

```
!judge
!judge 40
```

ButlerBot reads the recent messages (20 by default, up to 60) and delivers a ruling, in character: each side summed up, a verdict, and a penalty for the loser.

## Catch up on a busy channel

```
/catchup
```

You get a short summary of everything since you last spoke in the channel, and only you see it. The text version `!catchup` sends it to your DMs instead.

## Summarize a link

Someone posted a long article or video?
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
