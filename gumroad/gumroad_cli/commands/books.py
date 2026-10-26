"""No Gumroad auth; book commands enforce the separately owned Notion token at execution."""
COMMAND_CREDENTIALS = {'inspect': ['no_auth'], 'build-pdf': ['no_auth'], 'build-epub': ['no_auth']}
