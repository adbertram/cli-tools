# Copilot CLI - Claude Instructions

Always read the README.md file first when working with this CLI tool. It contains:

- Installation and setup instructions
- Available commands and usage examples
- Environment variable configuration
- API documentation references

## Windows: Azure CLI Subprocess Calls

**CRITICAL**: On Windows, Azure CLI is `az.cmd` (batch file), not `az` (executable). Any `subprocess.run()` call that invokes `az` will fail with `[WinError 2] The system cannot find the file specified`.

**Rule**: NEVER use hardcoded `"az"` in subprocess calls. ALWAYS use `_resolve_az_command()` from `client.py`, which handles Windows resolution:

```python
# WRONG — fails on Windows with [WinError 2]
subprocess.run(["az", "account", "get-access-token", ...])

# CORRECT — works on all platforms
az = _resolve_az_command()
subprocess.run([az, "account", "get-access-token", ...])
```

When adding any new `subprocess.run()` call that invokes `az`, also add a `FileNotFoundError` handler following the pattern in `get_access_token_from_azure_cli()`.

## Documentation Maintenance

When updating this CLI tool, always keep the README.md up to date with any changes to commands, options, or functionality.
