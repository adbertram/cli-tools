"""Read-only Whop participant CLI."""
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from . import __version__
from .config import get_config
from .commands import account, linked_accounts, campaigns, submissions, earnings

app=create_app(name="whop",help="Read Whop participant account and Content Rewards data",version=__version__)
for name,module in [('account',account),('linked-accounts',linked_accounts),('campaigns',campaigns),('submissions',submissions),('earnings',earnings)]:
    register_commands(app,get_config,module,name=name,help=f"Read {name.replace('-', ' ')}")
app.add_typer(create_auth_app(get_config,tool_name="whop"),name="auth")
app.add_typer(create_cache_app(get_config),name="cache")

def main():
    run_app(app)

if __name__=="__main__":
    main()
