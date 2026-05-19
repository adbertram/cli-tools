# Cliclick CLI - Claude Instructions

This is a **wrapper CLI** that wraps the `cliclick` command-line tool.

Always read the README.md file first when working with this CLI tool.

## Key Concepts

- **Wrapper type**: This CLI calls an underlying CLI (`cliclick`) via subprocess
- **Auth delegation**: `auth login/logout/status` delegate to `cliclick`'s commands
- **Output parsing**: Raw CLI output is parsed and transformed to JSON/table format

## Underlying CLI

- **Command**: `cliclick`
- **Documentation**: https://github.com/BlueM/cliclick

## Customization Points

1. **`client.py`**: Customize command arguments and parsing in auth/resource methods
2. **`parsers.py`**: Add custom output parsers for specific commands
3. **`commands/auth.py`**: Map to correct auth commands for the underlying CLI

## Architecture

```
cliclick <command>  -->  subprocess.run(cliclick <args>)  -->  parse output  -->  JSON/table
```
