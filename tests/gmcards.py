"""Card helpers for the GameManager tests. harness.card_buttons skips DynamicItem buttons (SessionButton, VoteButton,
RequestButton, InstallButton), so this version unwraps them."""
from harness import discord


def card_buttons(target) -> list:
    view = getattr(target, "view", target)
    if view is None or not hasattr(view, "walk_children"):
        return []
    found = []
    for item in view.walk_children():
        inner = getattr(item, "item", item)
        if isinstance(inner, discord.ui.Button):
            found.append(inner)
    return found


def action_buttons(target) -> list:
    """Buttons that do something (not link buttons)."""
    return [b for b in card_buttons(target) if not b.url]


def custom_ids(target) -> list:
    return [b.custom_id for b in action_buttons(target)]
