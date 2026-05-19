# PhotosApp CLI - Claude Instructions

This is a **wrapper CLI** that wraps the `sqlite3` command-line tool.

Always read the README.md file first when working with this CLI tool.

## Key Concepts

- **Wrapper type**: This CLI calls an underlying CLI (`sqlite3`) via subprocess
- **Auth delegation**: `auth login/logout/status` delegate to `sqlite3`'s commands
- **Output parsing**: Raw CLI output is parsed and transformed to JSON/table format

## Underlying CLI

- **Command**: `sqlite3`
- **Documentation**: 

## Customization Points

1. **`client.py`**: Customize command arguments and parsing in auth/resource methods
2. **`parsers.py`**: Add custom output parsers for specific commands
3. **`commands/auth.py`**: Map to correct auth commands for the underlying CLI

## Architecture

```
photos-app <command>  -->  subprocess.run(sqlite3 <args>)  -->  parse output  -->  JSON/table
```
