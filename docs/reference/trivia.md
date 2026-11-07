---
title: Trivia
parent: Command reference
nav_order: 27
permalink: /reference/trivia/
---

# Trivia

Play trivia with friends!

For a task-by-task guide, see [Fun and games]({{ '/fun/' | relative_url }}).

{% raw %}
<a id="trivia"></a>
### !trivia

`!trivia <categories...>`

**Who:** everyone

Start trivia session on the specified category.

You may list multiple categories, in which case the trivia will involve
questions from all of them.

<a id="trivia-info"></a>
### !trivia info

`!trivia info <category>`

**Who:** everyone

Get information about a trivia category.

<a id="trivia-leaderboard"></a>
### !trivia leaderboard

`!trivia leaderboard`

**Who:** everyone · **Also:** `!trivia lboard`

Leaderboard for trivia.

Defaults to the top 10 of this server, sorted by total wins. Use
subcommands for a more customised leaderboard.

<a id="trivia-leaderboard-global"></a>
### !trivia leaderboard global

`!trivia leaderboard global [sort_by=wins] [top=10]`

**Who:** everyone

Global trivia leaderboard.

`<sort_by>` can be any of the following fields:
 - `wins`  : total wins
 - `avg`   : average score
 - `total` : total correct answers from all sessions
 - `games` : total games played

`<top>` is the number of ranks to show on the leaderboard.

<a id="trivia-leaderboard-server"></a>
### !trivia leaderboard server

`!trivia leaderboard server [sort_by=wins] [top=10]`

**Who:** everyone

Leaderboard for this server.

`<sort_by>` can be any of the following fields:
 - `wins`  : total wins
 - `avg`   : average score
 - `total` : total correct answers
 - `games` : total games played

`<top>` is the number of ranks to show on the leaderboard.

<a id="trivia-list"></a>
### !trivia list

`!trivia list`

**Who:** everyone

List available trivia categories.

<a id="trivia-stop"></a>
### !trivia stop

`!trivia stop`

**Who:** everyone

Stop an ongoing trivia session.

<a id="triviaset"></a>
### !triviaset

`!triviaset`

**Who:** mods, or anyone with the administrator permission

Manage Trivia settings.

<a id="triviaset-botplays"></a>
### !triviaset botplays

`!triviaset botplays <true_or_false>`

**Who:** mods, or anyone with the administrator permission

Set whether or not the bot gains points.

If enabled, the bot will gain a point if no one guesses correctly.

<a id="triviaset-maxscore"></a>
### !triviaset maxscore

`!triviaset maxscore <score>`

**Who:** mods, or anyone with the administrator permission

Set the total points required to win.

<a id="triviaset-override"></a>
### !triviaset override

`!triviaset override <enabled>`

**Who:** mods, or anyone with the administrator permission

Allow/disallow trivia lists to override settings.

<a id="triviaset-payout"></a>
### !triviaset payout

`!triviaset payout <multiplier>`

**Who:** admins, or anyone with the manage guild permission

Set the payout multiplier.

This can be any positive decimal number. If a user wins trivia when at
least 3 members are playing, they will receive credits. Set to 0 to
disable.

The number of credits is determined by multiplying their total score by
this multiplier.

<a id="triviaset-revealanswer"></a>
### !triviaset revealanswer

`!triviaset revealanswer <true_or_false>`

**Who:** mods, or anyone with the administrator permission

Set whether or not the answer is revealed.

If enabled, the bot will reveal the answer if no one guesses correctly
in time.

<a id="triviaset-showsettings"></a>
### !triviaset showsettings

`!triviaset showsettings`

**Who:** mods, or anyone with the administrator permission

Show the current trivia settings.

<a id="triviaset-stopafter"></a>
### !triviaset stopafter

`!triviaset stopafter <seconds>`

**Who:** mods, or anyone with the administrator permission

Set how long until trivia stops due to no response.

<a id="triviaset-timelimit"></a>
### !triviaset timelimit

`!triviaset timelimit <seconds>`

**Who:** mods, or anyone with the administrator permission

Set the maximum seconds permitted to answer a question.

<a id="triviaset-usespoilers"></a>
### !triviaset usespoilers

`!triviaset usespoilers <true_or_false>`

**Who:** mods, or anyone with the administrator permission

Set if bot will display the answers in spoilers.

If enabled, the bot will use spoilers to hide answers.

{% endraw %}
