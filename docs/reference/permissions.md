---
title: Permissions
parent: Command reference
nav_order: 28
permalink: /reference/permissions/
---

# Permissions

Customise permissions for commands and cogs.

For a task-by-task guide, see [Server setup]({{ '/admin/' | relative_url }}).

{% raw %}
<a id="permissions"></a>
### !permissions

`!permissions`

**Who:** everyone

Command permission management tools.

<a id="permissions-acl"></a>
### !permissions acl

`!permissions acl`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!permissions yaml`

Manage permissions with YAML files.

<a id="permissions-acl-getserver"></a>
### !permissions acl getserver

`!permissions acl getserver`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!permissions acl getguild`

Get a YAML file detailing all rules in this server.

<a id="permissions-acl-setserver"></a>
### !permissions acl setserver

`!permissions acl setserver`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!permissions acl setguild`

Set rules for this server with a YAML file.

**WARNING**: This will override reset *all* rules in this
server to the rules specified in the uploaded file.

<a id="permissions-acl-updateserver"></a>
### !permissions acl updateserver

`!permissions acl updateserver`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!permissions acl updateguild`

Update rules for this server with a YAML file.

This won't touch any rules not specified in the YAML
file.

<a id="permissions-acl-yamlexample"></a>
### !permissions acl yamlexample

`!permissions acl yamlexample`

**Who:** server owners, or anyone with the administrator permission

Sends an example of the yaml layout for permissions

<a id="permissions-addserverrule"></a>
### !permissions addserverrule

`!permissions addserverrule <allow_or_deny> <cog_or_command> <who_or_what...>`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!permissions addguildrule`

Add a rule to a command in this server.

`<allow_or_deny>` should be one of "allow" or "deny".

`<cog_or_command>` is the cog or command to add the rule to.
This is case sensitive.

`<who_or_what...>` is one or more users, channels or roles the rule is for.

<a id="permissions-canrun"></a>
### !permissions canrun

`!permissions canrun <user> <command>`

**Who:** everyone

Check if a user can run a command.

This will take the current context into account, such as the
server and text channel.

<a id="permissions-clearserverrules"></a>
### !permissions clearserverrules

`!permissions clearserverrules`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!permissions clearguildrules`

Reset all rules in this server.

<a id="permissions-explain"></a>
### !permissions explain

`!permissions explain`

**Who:** everyone

Explain how permissions works.

<a id="permissions-removeserverrule"></a>
### !permissions removeserverrule

`!permissions removeserverrule <cog_or_command> <who_or_what...>`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!permissions removeguildrule`

Remove a server rule from a command.

`<cog_or_command>` is the cog or command to remove the rule
from. This is case sensitive.

`<who_or_what...>` is one or more users, channels or roles the rule is for.

<a id="permissions-setdefaultserverrule"></a>
### !permissions setdefaultserverrule

`!permissions setdefaultserverrule <allow_or_deny> <cog_or_command>`

**Who:** server owners, or anyone with the administrator permission · **Also:** `!permissions setdefaultguildrule`

Set the default rule for a command in this server.

This is the rule a command will default to when no other rule
is found.

`<allow_or_deny>` should be one of "allow", "deny" or "clear".
"clear" will reset the default rule.

`<cog_or_command>` is the cog or command to set the default
rule for. This is case sensitive.

{% endraw %}
