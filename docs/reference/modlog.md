---
title: ModLog
parent: Command reference
nav_order: 26
permalink: /reference/modlog/
---

# ModLog

Browse and manage modlog cases. To manage modlog settings, use `!modlogset`.

For a task-by-task guide, see [Moderation]({{ '/moderation/' | relative_url }}).

{% raw %}
<a id="case"></a>
### !case

`!case <number>`

**Who:** everyone

Show the specified case.

<a id="casesfor"></a>
### !casesfor

`!casesfor <member>`

**Who:** everyone

Display cases for the specified member.

<a id="listcases"></a>
### !listcases

`!listcases <member>`

**Who:** everyone

List cases for the specified member.

<a id="reason"></a>
### !reason

`!reason [case] <reason>`

**Who:** everyone

Specify a reason for a modlog case.

Please note that you can only edit cases you are
the owner of unless you are a mod, admin or server owner.

If no case number is specified, the latest case will be used.

{% endraw %}
