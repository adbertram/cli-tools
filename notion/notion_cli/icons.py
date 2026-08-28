"""Notion page icon parsing, as one shared contract.

Notion's API stores a page icon as either an emoji object or an external file
object::

    {"type": "emoji", "emoji": "\U0001F680"}
    {"type": "external", "external": {"url": "https://..."}}

The ``emoji`` field must hold the literal emoji CHARACTER. Sending a shortcode
NAME there is rejected with an opaque 400::

    body failed validation. Fix one: body.icon.emoji should be "\U0001F600",
    "\U0001F603", ...

The CLI documents ``--icon`` as ``emoji:rocket``, so this module owns the one
translation from a CLI ``--icon`` value to the Notion icon object, resolving a
shortcode name to its character before the request is ever built. An unknown
shortcode fails here, locally, naming the bad shortcode -- it is never forwarded
to the API to produce that opaque 400.

Accepted ``--icon`` forms:

* ``emoji:<shortcode>``      -- ``emoji:rocket``  -> ``\U0001F680``
* ``emoji:<character>``      -- ``emoji:\U0001F4C4``       -> ``\U0001F4C4``
* ``<character>``            -- ``\U0001F4CB``       -> ``\U0001F4CB``
* ``url:<url>``              -- ``url:https://example.com/icon.png``

Shortcode names come from the ``emoji`` package's alias table (CLDR names plus
GitHub-style aliases), which is why shortcode support is a dependency rather
than a hand-maintained table: the alias set is thousands of entries and changes
with each Unicode release.
"""
from __future__ import annotations

import emoji as emoji_lib

EMOJI_PREFIX = "emoji:"
URL_PREFIX = "url:"

ACCEPTED_FORMS = (
    "Use 'emoji:<shortcode>' (e.g. 'emoji:rocket'), a literal emoji character "
    "(e.g. '\U0001F680'), or 'url:https://...'."
)


class IconFormatError(ValueError):
    """Raised when an ``--icon`` value cannot be turned into a Notion icon object."""


def _shortcode_candidates(name: str) -> list[str]:
    """Return the shortcode spellings to try, most literal first."""
    candidates = [name]
    lowered = name.lower()
    for variant in (lowered, lowered.replace(" ", "_"), lowered.replace("-", "_")):
        if variant not in candidates:
            candidates.append(variant)
    return candidates


def shortcode_to_character(name: str) -> str:
    """Resolve an emoji shortcode name to its literal character.

    Raises:
        IconFormatError: the shortcode is not a known emoji name or alias.
    """
    for candidate in _shortcode_candidates(name):
        resolved = emoji_lib.emojize(f":{candidate}:", language="alias")
        if emoji_lib.is_emoji(resolved):
            return resolved

    raise IconFormatError(
        f"Unknown emoji shortcode: '{name}'. "
        "Pass a known shortcode name (e.g. 'emoji:rocket', 'emoji:clipboard') "
        "or the literal emoji character (e.g. '--icon \U0001F680')."
    )


def parse_icon(value: str) -> dict:
    """Build a Notion icon object from a CLI ``--icon`` value.

    Raises:
        IconFormatError: the value is not one of the accepted forms, or names an
            emoji shortcode that does not exist.
    """
    icon = value.strip()

    if icon.startswith(URL_PREFIX):
        url = icon[len(URL_PREFIX):].strip()
        if not url:
            raise IconFormatError(f"Icon URL is empty: '{value}'. {ACCEPTED_FORMS}")
        return {"type": "external", "external": {"url": url}}

    if icon.startswith(EMOJI_PREFIX):
        name = icon[len(EMOJI_PREFIX):].strip()
        if not name:
            raise IconFormatError(f"Emoji shortcode is empty: '{value}'. {ACCEPTED_FORMS}")
        if emoji_lib.is_emoji(name):
            return {"type": "emoji", "emoji": name}
        return {"type": "emoji", "emoji": shortcode_to_character(name)}

    if emoji_lib.is_emoji(icon):
        return {"type": "emoji", "emoji": icon}

    raise IconFormatError(f"Invalid icon format: '{value}'. {ACCEPTED_FORMS}")
