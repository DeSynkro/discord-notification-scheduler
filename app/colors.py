import re

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def effective_color(item) -> str | None:
    """The one color for a schedule item: its selected color, or a legacy embed color."""
    if item is None:
        return None
    if isinstance(item, dict):
        color = item.get("color")
        embed = item.get("embed")
    else:
        color = getattr(item, "color", None)
        embed = getattr(item, "embed", None)

    if not color:
        if isinstance(embed, dict):
            color = embed.get("color")
        elif embed is not None:
            color = getattr(embed, "color", None)

    if isinstance(color, str) and _HEX_COLOR.match(color):
        return color.upper()
    return None
