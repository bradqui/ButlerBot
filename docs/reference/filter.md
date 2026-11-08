---
title: Filter
parent: Command reference
nav_order: 15
permalink: /reference/filter/
---

# Filter

This cog is designed for "filtering" unwanted words and phrases from a server.

It provides tools to manage a list of words or sentences, and to customize automatic actions to be taken against users who use those words in channels or in their name/nickname.

This can be used to prevent inappropriate language, off-topic discussions, invite links, and more.

For a task-by-task guide, see [Filters and spam]({{ '/filters/' | relative_url }}).

{% raw %}
<a id="filter"></a>
### !filter

`!filter`

**Who:** mods, or anyone with the manage messages permission

Base command to add or remove words from the server filter.

Use double quotes to add or remove sentences.

<a id="filter-add"></a>
### !filter add

`!filter add <words...>`

**Who:** mods, or anyone with the manage messages permission

Add words to the filter.

Use double quotes to add sentences.

Examples:
- `!filter add word1 word2 word3`
- `!filter add "This is a sentence"`

**Arguments:**

- `[words...]` The words or sentences to filter.

<a id="filter-channel"></a>
### !filter channel

`!filter channel`

**Who:** mods, or anyone with the manage messages permission

Base command to add or remove words from the channel filter.

Use double quotes to add or remove sentences.

<a id="filter-channel-add"></a>
### !filter channel add

`!filter channel add <channel> <words...>`

**Who:** mods, or anyone with the manage messages permission

Add words to the filter.

Use double quotes to add sentences.

Examples:
- `!filter channel add #channel word1 word2 word3`
- `!filter channel add #channel "This is a sentence"`

**Arguments:**

- `<channel>` The text, voice, stage, or forum channel to add filtered words to.
- `[words...]` The words or sentences to filter.

<a id="filter-channel-clear"></a>
### !filter channel clear

`!filter channel clear`

**Who:** mods, or anyone with the manage messages permission

Clears this channel's filter list.

<a id="filter-channel-delete"></a>
### !filter channel delete

`!filter channel delete <channel> <words...>`

**Who:** mods, or anyone with the manage messages permission · **Also:** `!filter channel remove`, `!filter channel del`

Remove words from the filter.

Use double quotes to remove sentences.

Examples:
- `!filter channel remove #channel word1 word2 word3`
- `!filter channel remove #channel "This is a sentence"`

**Arguments:**

- `<channel>` The text, voice, stage, or forum channel to add filtered words to.
- `[words...]` The words or sentences to no longer filter.

<a id="filter-channel-list"></a>
### !filter channel list

`!filter channel list`

**Who:** mods, or anyone with the manage messages permission

Send a list of the channel's filtered words.

<a id="filter-clear"></a>
### !filter clear

`!filter clear`

**Who:** mods, or anyone with the manage messages permission

Clears this server's filter list.

<a id="filter-delete"></a>
### !filter delete

`!filter delete <words...>`

**Who:** mods, or anyone with the manage messages permission · **Also:** `!filter remove`, `!filter del`

Remove words from the filter.

Use double quotes to remove sentences.

Examples:
- `!filter remove word1 word2 word3`
- `!filter remove "This is a sentence"`

**Arguments:**

- `[words...]` The words or sentences to no longer filter.

<a id="filter-list"></a>
### !filter list

`!filter list`

**Who:** mods, or anyone with the manage messages permission

Send a list of this server's filtered words.

<a id="filter-names"></a>
### !filter names

`!filter names`

**Who:** mods, or anyone with the manage messages permission

Toggle name and nickname filtering.

This is disabled by default.

<a id="filterset"></a>
### !filterset

`!filterset`

**Who:** admins, or anyone with the manage guild permission

Base command to manage filter settings.

<a id="filterset-ban"></a>
### !filterset ban

`!filterset ban <count> <timeframe>`

**Who:** admins, or anyone with the manage guild permission

Set the filter's autoban conditions.

Users will be banned if they send `<count>` filtered words in
`<timeframe>` seconds.

Set both to zero to disable autoban.

Examples:
- `!filterset ban 5 5` - Ban users who say 5 filtered words in 5 seconds.
- `!filterset ban 2 20` - Ban users who say 2 filtered words in 20 seconds.

**Arguments:**

- `<count>` The amount of filtered words required to trigger a ban.
- `<timeframe>` The period of time in which too many filtered words will trigger a ban.

<a id="filterset-defaultname"></a>
### !filterset defaultname

`!filterset defaultname <name>`

**Who:** admins, or anyone with the manage guild permission

Set the nickname for users with a filtered name.

Note that this has no effect if filtering names is disabled
(to toggle, run `!filter names`).

The default name used is *John Doe*.

Example:
- `!filterset defaultname Missingno`

**Arguments:**

- `<name>` The new nickname to assign.

{% endraw %}
