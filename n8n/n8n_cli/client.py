"""File-based client for n8n Node.

Unlike typical API clients, this client operates on the local filesystem.
It wraps the parser and generator modules to provide a clean interface.
"""
from pathlib import Path
from typing import List, Optional

from .config import get_config
from .parser import parse_cli_tool, is_cli_tool, ParserError
from .generator import generate_node_package, GeneratorError
from .models import CLIToolMetadata, GeneratedPackage


class ClientError(Exception):
    """Custom exception for client errors."""
    pass


class N8nConverterClient:
    """Client for parsing CLI tools and generating n8n node packages."""

    def __init__(self):
        """Initialize from configuration."""
        self.config = get_config()

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Configuration issue: {', '.join(missing)}. "
                "Run 'n8n auth login' to configure."
            )

        self.tools_dir = self.config.cli_tools_dir
        self.output_dir = self.config.output_dir

    def list_tools(self) -> List[dict]:
        """List available CLI tools that can be converted.

        Returns:
            List of dicts with tool name, description, and path
        """
        tools_path = Path(self.tools_dir)
        tools = []

        for child in sorted(tools_path.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith((".", "_")):
                continue
            if not is_cli_tool(child):
                continue

            # Quick parse for description
            pyproject = child / "pyproject.toml"
            description = ""
            if pyproject.exists():
                import re
                content = pyproject.read_text()
                match = re.search(r'^description\s*=\s*"([^"]+)"', content, re.MULTILINE)
                if match:
                    description = match.group(1)

            tools.append({
                "name": child.name,
                "description": description,
                "path": str(child),
            })

        return tools

    def get_tool(self, tool_name: str) -> CLIToolMetadata:
        """Parse and return metadata for a specific CLI tool.

        Args:
            tool_name: Name of the CLI tool

        Returns:
            CLIToolMetadata with parsed information

        Raises:
            ClientError: If tool cannot be parsed
        """
        try:
            return parse_cli_tool(tool_name, self.tools_dir)
        except ParserError as e:
            raise ClientError(str(e))

    def generate(self, tool_name: str, output_dir: Optional[str] = None, force: bool = False,
                 name_override: Optional[str] = None, display_name_override: Optional[str] = None) -> str:
        """Generate an n8n node package from a CLI tool.

        Args:
            tool_name: Name of the CLI tool to convert
            output_dir: Override output directory
            force: Overwrite existing package
            name_override: Override the package/node name (useful to avoid name conflicts)
            display_name_override: Override the display name shown in n8n UI

        Returns:
            Path to the generated package

        Raises:
            ClientError: If generation fails
        """
        try:
            metadata = parse_cli_tool(tool_name, self.tools_dir)
        except ParserError as e:
            raise ClientError(f"Failed to parse '{tool_name}': {e}")

        target_dir = output_dir or self.output_dir
        Path(target_dir).mkdir(parents=True, exist_ok=True)

        try:
            return generate_node_package(
                metadata, target_dir, force=force, tools_dir=self.tools_dir,
                name_override=name_override, display_name_override=display_name_override,
            )
        except GeneratorError as e:
            raise ClientError(str(e))

    def list_generated(self) -> List[GeneratedPackage]:
        """List previously generated n8n node packages.

        Returns:
            List of GeneratedPackage models
        """
        output_path = Path(self.output_dir)
        if not output_path.exists():
            return []

        packages = []
        for child in sorted(output_path.iterdir()):
            if not child.is_dir():
                continue
            pkg_json = child / "package.json"
            if not pkg_json.exists():
                continue

            import json
            try:
                pkg_data = json.loads(pkg_json.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            # Only include n8n community node packages
            keywords = pkg_data.get("keywords", [])
            if "n8n-community-node-package" not in keywords:
                continue

            cli_name = child.name

            # Count resources and operations from the node file
            resources = 0
            operations = 0
            nodes_dir = child / "nodes"
            if nodes_dir.exists():
                for node_dir in nodes_dir.iterdir():
                    if node_dir.is_dir():
                        for ts_file in node_dir.glob("*.node.ts"):
                            content = ts_file.read_text()
                            resources = content.count("name: 'Resource'") or content.count("resource: [")
                            operations = content.count("action:")

            packages.append(GeneratedPackage(
                name=pkg_data.get("name", child.name),
                cli_tool=cli_name,
                output_dir=str(child),
                resources=resources,
                operations=operations,
            ))

        return packages


# Module-level client instance - singleton pattern
_client: Optional[N8nConverterClient] = None


def get_client() -> N8nConverterClient:
    """Get or create the global client instance."""
    global _client
    if _client is None:
        _client = N8nConverterClient()
    return _client
