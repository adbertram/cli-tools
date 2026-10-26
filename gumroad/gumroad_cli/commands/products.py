"""Product command credentials; create-draft dry-run is offline."""
COMMAND_CREDENTIALS = {
    "list": ["personal_access_token"], "get": ["personal_access_token"],
    "create-draft": ["no_auth"], "update": ["personal_access_token"],
    "publish": ["personal_access_token"],
}
