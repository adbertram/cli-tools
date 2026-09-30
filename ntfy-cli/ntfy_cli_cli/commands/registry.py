"""Declarative upstream command metadata used by the ntfy adapter."""

COMMAND_REGISTRY = {
    "publish": {
        "argv": ("publish",),
        "sensitive": ("--token", "-k", "--user", "-u"),
    },
    "poll": {
        "argv": ("subscribe", "--poll"),
        "sensitive": ("--token", "-k", "--user", "-u"),
    },
}

SENSITIVE_OPTIONS = frozenset(
    option
    for definition in COMMAND_REGISTRY.values()
    for option in definition.get("sensitive", ())
)
