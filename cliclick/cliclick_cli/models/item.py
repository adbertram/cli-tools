"""Models for Cliclick CLI.

Provides typed models for:
- Position: Mouse coordinates (x, y)
- Color: RGB color values
- Script: Automation script metadata
- ExecutionResult: Command execution outcome
"""
from typing import List, Optional

from pydantic import Field

from .base import CLIModel


class Position(CLIModel):
    """Mouse position coordinates."""

    x: int
    y: int


class Color(CLIModel):
    """RGB color value from screen."""

    r: int
    g: int
    b: int


class Script(CLIModel):
    """A cliclick automation script.

    Scripts are stored as plain text .cliclick files in the package's
    scripts directory. They contain cliclick commands, one per line.
    """

    name: str = Field(frozen=True)
    path: str = Field(frozen=True)
    description: Optional[str] = None
    variables: List[str] = []  # Template variables found in script
    command_count: int = 0


class ExecutionResult(CLIModel):
    """Result of executing a cliclick command or script."""

    success: bool
    output: str
    error: Optional[str] = None
    duration_ms: Optional[float] = None
    commands_executed: int = 1


# ==================== Factory Functions ====================


def create_position(x: int, y: int) -> Position:
    """Create a Position model from coordinates."""
    return Position(x=x, y=y)


def create_color(r: int, g: int, b: int) -> Color:
    """Create a Color model from RGB values."""
    return Color(r=r, g=g, b=b)


def create_script(name: str, path: str, **kwargs) -> Script:
    """Create a Script model from metadata."""
    return Script(name=name, path=path, **kwargs)


def create_execution_result(
    success: bool,
    output: str,
    error: Optional[str] = None,
    duration_ms: Optional[float] = None,
    commands_executed: int = 1,
) -> ExecutionResult:
    """Create an ExecutionResult model."""
    return ExecutionResult(
        success=success,
        output=output,
        error=error,
        duration_ms=duration_ms,
        commands_executed=commands_executed,
    )
