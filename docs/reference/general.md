---
title: General
parent: Command reference
nav_order: 19
permalink: /reference/general/
---

# General

General commands.

For a task-by-task guide, see [Fun and games]({{ '/fun/' | relative_url }}).

{% raw %}
<a id="8"></a>
### !8

`!8 <question>`

**Who:** everyone · **Also:** `!8ball`

Ask 8 ball a question.

Question must end with a question mark.

<a id="choose"></a>
### !choose

`!choose <first> <second> [others...]`

**Who:** everyone

Choose between multiple options.

There must be at least 2 options to pick from.
Options are separated by spaces.

To denote options which include whitespace, you should enclose the options in double quotes.

<a id="flip"></a>
### !flip

`!flip [user]`

**Who:** everyone

Flip a coin... or a user.

Defaults to a coin.

<a id="lmgtfy"></a>
### !lmgtfy

`!lmgtfy <search_terms>`

**Who:** everyone

Create a lmgtfy link.

<a id="roll"></a>
### !roll

`!roll [number=100]`

**Who:** everyone

Roll a random number.

The result will be between 1 and `<number>`.

`<number>` defaults to 100.

<a id="rps"></a>
### !rps

`!rps <your_choice>`

**Who:** everyone

Play Rock Paper Scissors.

<a id="serverinfo"></a>
### !serverinfo

`!serverinfo [details=False]`

**Who:** everyone

Show server information.

`details`: Shows more information when set to `True`.
Default to False.

<a id="stopwatch"></a>
### !stopwatch

`!stopwatch`

**Who:** everyone · **Also:** `!sw`

Start or stop the stopwatch.

<a id="urban"></a>
### !urban

`!urban <word>`

**Who:** everyone

Search the Urban Dictionary.

This uses the unofficial Urban Dictionary API.

{% endraw %}
