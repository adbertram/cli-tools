"""Metadata models for parsed CLI tools."""
from typing import Any, List, Optional

from .base import CLIModel


class CredentialField(CLIModel):
    """A credential environment variable used by a CLI tool."""

    env_var: str
    field_name: str = ""  # n8n credential field name (e.g., "apiKey"), computed by parser
    display_name: str
    required: bool = True
    default: Optional[str] = None
    is_secret: bool = False
    comment: Optional[str] = None


class CommandParameter(CLIModel):
    """A parameter on a CLI command (argument or option)."""

    name: str
    cli_flag: Optional[str] = None
    cli_short: Optional[str] = None
    param_type: str = "string"
    python_type: str = "str"
    default: Optional[Any] = None
    required: bool = False
    help_text: Optional[str] = None
    is_argument: bool = False
    is_list: bool = False
    choices: Optional[List[str]] = None


class Command(CLIModel):
    """A CLI command (e.g., order list, inventory get)."""

    name: str
    display_name: str
    help_text: Optional[str] = None
    parameters: List[CommandParameter] = []


class CommandGroup(CLIModel):
    """A group of related commands (e.g., order, inventory)."""

    name: str
    display_name: str
    help_text: Optional[str] = None
    commands: List[Command] = []


class CLIToolMetadata(CLIModel):
    """Complete metadata for a parsed CLI tool."""

    name: str
    display_name: str
    description: str = ""
    version: str = "0.1.0"
    cli_command: str = ""
    command_groups: List[CommandGroup] = []
    credentials: List[CredentialField] = []
    config_fields: List[CredentialField] = []  # Non-auth env vars (e.g., BASE_ID) → top-level node params


class GeneratedPackage(CLIModel):
    """Information about a generated n8n node package."""

    name: str
    cli_tool: str
    output_dir: str
    resources: int = 0
    operations: int = 0
