---
title: Censord
parent: Command reference
nav_order: 6
permalink: /reference/censord/
---

# Censord

Censor chat using CSV-based lists with specific levels and threshold punishments.

For a task-by-task guide, see [Filters and spam]({{ '/filters/' | relative_url }}).

{% raw %}
<a id="censord"></a>
### !censord

`!censord`

**Who:** everyone · **Also:** `!censor`

Word filter settings.

<a id="censord-action"></a>
### !censord action

`!censord action <action> [channel]`

**Who:** everyone

Sets the punishment action for violations.

Arguments:
- action: 'delete', 'kick', or 'ban'.
- channel (optional): If specified, the action applies ONLY to that channel.
                      If omitted, it sets the global server action.

<a id="censord-addword"></a>
### !censord addword

`!censord addword <level> <word>`

**Who:** everyone

Adds a word or phrase to the censorship list.

Your command message is deleted (when I can), and the reply doesn't repeat the word.

Arguments:
- level: 'low' or 'high'.
- word: The word to censor. Supports wildcards (e.g. *bad*).

<a id="censord-config"></a>
### !censord config

`!censord config`

**Who:** everyone

Show the word filter's settings.

Shows:
- The server level (off, low or high) and the punishment action
- The threshold
- The channel strategy, with the channels on the include and exceptions lists
- Channels with their own level or action
- How many entries each word list has
- The filter admin role

<a id="censord-delword"></a>
### !censord delword

`!censord delword <level> <word>`

**Who:** everyone

Removes a word or phrase from the censorship list.

Your command message is deleted (when I can), and the reply doesn't repeat the word.

Arguments:
- level: 'low' or 'high'.
- word: The word to remove. Must match the existing entry exactly.

<a id="censord-exceptchan"></a>
### !censord exceptchan

`!censord exceptchan <channel>`

**Who:** everyone

Toggles a channel for the 'Exclude' strategy.

If the strategy is 'exclude', adding a channel here stops the bot from monitoring it.
Running the command again removes it from the list.

<a id="censord-includechan"></a>
### !censord includechan

`!censord includechan <channel>`

**Who:** everyone

Toggles a channel for the 'Include' strategy.

If the strategy is 'include', adding a channel here makes the bot monitor it.
Running the command again removes it from the list.

<a id="censord-level"></a>
### !censord level

`!censord level <level> [channel]`

**Who:** everyone

Sets the censorship level to Off, Low, or High.

Arguments:
- level: 'off', 'low', or 'high'.
- channel (optional): If specified, the level applies ONLY to that channel.
                      If omitted, it sets the global server level.

<a id="censord-reload"></a>
### !censord reload

`!censord reload`

**Who:** everyone

Reloads the CSV word lists from the data folder.

Use this command after manually editing the CSV files on the disk
to apply changes immediately without reloading the entire cog.

<a id="censord-setrole"></a>
### !censord setrole

`!censord setrole [role]`

**Who:** everyone

Set a Discord Role that is allowed to edit censorship settings.

If no role is provided, the setting is cleared (restricted to Manage Server only).

<a id="censord-strategy"></a>
### !censord strategy

`!censord strategy <mode>`

**Who:** everyone

Sets the global channel monitoring strategy.

Options:
- include: Whitelist mode. The bot ONLY monitors channels added via `!censor includechan`.
- exclude: Blacklist mode. The bot monitors ALL channels EXCEPT those added via `!censor exceptchan`.

<a id="censord-threshold"></a>
### !censord threshold

`!censord threshold <count> <seconds>`

**Who:** everyone

Sets the violation threshold for punishments.

The bot punishes a user if they send [count] violating messages within [seconds].
Both numbers must be at least 1.

Example: !censor threshold 5 10
(Punishes if 5 bad messages are sent in 10 seconds).

{% endraw %}
