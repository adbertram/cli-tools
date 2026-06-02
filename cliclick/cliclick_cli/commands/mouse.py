"""Mouse control commands for cliclick CLI wrapper."""
import typer
from typing import Optional

from ..client import get_client, ClientError
from cli_tools_shared.output import print_json, print_table, print_success, print_error, handle_error

app = typer.Typer(help="Mouse control commands", no_args_is_help=True)


@app.command("click")
def mouse_click(
    x: int = typer.Argument(..., help="X coordinate"),
    y: int = typer.Argument(..., help="Y coordinate"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output from cliclick"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode (no actual click)"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position after"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Click at screen coordinates.

    Example:
        cliclick mouse click 100 200
        cliclick mouse click 500 300 --test
    """
    try:
        client = get_client()
        result = client.click(x, y, verbose=verbose, test_mode=test, restore=not no_restore)

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "x", "value": str(x)},
                {"field": "y", "value": str(y)},
                {"field": "duration_ms", "value": f"{result.duration_ms:.2f}" if result.duration_ms else "N/A"},
            ]
            if result.output:
                rows.append({"field": "output", "value": result.output})
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("double-click")
def mouse_double_click(
    x: int = typer.Argument(..., help="X coordinate"),
    y: int = typer.Argument(..., help="Y coordinate"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Double-click at screen coordinates.

    Example:
        cliclick mouse double-click 100 200
    """
    try:
        client = get_client()
        result = client.double_click(x, y, verbose=verbose, test_mode=test, restore=not no_restore)

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "x", "value": str(x)},
                {"field": "y", "value": str(y)},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("right-click")
def mouse_right_click(
    x: int = typer.Argument(..., help="X coordinate"),
    y: int = typer.Argument(..., help="Y coordinate"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Right-click at screen coordinates.

    Example:
        cliclick mouse right-click 100 200
    """
    try:
        client = get_client()
        result = client.right_click(x, y, verbose=verbose, test_mode=test, restore=not no_restore)

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "x", "value": str(x)},
                {"field": "y", "value": str(y)},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("triple-click")
def mouse_triple_click(
    x: int = typer.Argument(..., help="X coordinate"),
    y: int = typer.Argument(..., help="Y coordinate"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Triple-click at screen coordinates.

    Example:
        cliclick mouse triple-click 100 200
    """
    try:
        client = get_client()
        result = client.triple_click(x, y, verbose=verbose, test_mode=test, restore=not no_restore)

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "x", "value": str(x)},
                {"field": "y", "value": str(y)},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("move")
def mouse_move(
    x: int = typer.Argument(..., help="X coordinate"),
    y: int = typer.Argument(..., help="Y coordinate"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Move mouse to screen coordinates.

    Example:
        cliclick mouse move 500 300
    """
    try:
        client = get_client()
        result = client.move(x, y, verbose=verbose, test_mode=test, restore=not no_restore)

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "x", "value": str(x)},
                {"field": "y", "value": str(y)},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("drag-start")
def mouse_drag_start(
    x: int = typer.Argument(..., help="X coordinate"),
    y: int = typer.Argument(..., help="Y coordinate"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Start a drag operation (mouse down) at coordinates.

    Example:
        cliclick mouse drag-start 100 100
    """
    try:
        client = get_client()
        result = client.drag_start(x, y, verbose=verbose, test_mode=test, restore=not no_restore)

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "x", "value": str(x)},
                {"field": "y", "value": str(y)},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("drag-move")
def mouse_drag_move(
    x: int = typer.Argument(..., help="X coordinate"),
    y: int = typer.Argument(..., help="Y coordinate"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Continue a drag operation to new coordinates.

    Example:
        cliclick mouse drag-move 200 200
    """
    try:
        client = get_client()
        result = client.drag_move(x, y, verbose=verbose, test_mode=test, restore=not no_restore)

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "x", "value": str(x)},
                {"field": "y", "value": str(y)},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("drag-end")
def mouse_drag_end(
    x: int = typer.Argument(..., help="X coordinate"),
    y: int = typer.Argument(..., help="Y coordinate"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    End a drag operation (mouse up) at coordinates.

    Example:
        cliclick mouse drag-end 300 300
    """
    try:
        client = get_client()
        result = client.drag_end(x, y, verbose=verbose, test_mode=test, restore=not no_restore)

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "x", "value": str(x)},
                {"field": "y", "value": str(y)},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("position")
def mouse_position(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get current mouse position.

    Example:
        cliclick mouse position
        cliclick mouse position --table
    """
    try:
        client = get_client()
        position = client.get_position()

        if table:
            rows = [
                {"field": "x", "value": str(position.x)},
                {"field": "y", "value": str(position.y)},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(position.model_dump())

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("color-at")
def mouse_color_at(
    x: int = typer.Argument(..., help="X coordinate"),
    y: int = typer.Argument(..., help="Y coordinate"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get screen color at coordinates.

    Returns RGB values (0-255) for the pixel at the given coordinates.

    Example:
        cliclick mouse color-at 100 200
    """
    try:
        client = get_client()
        color = client.get_color_at(x, y)

        if table:
            rows = [
                {"field": "r", "value": str(color.r)},
                {"field": "g", "value": str(color.g)},
                {"field": "b", "value": str(color.b)},
                {"field": "hex", "value": f"#{color.r:02x}{color.g:02x}{color.b:02x}"},
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            data = color.model_dump()
            data["hex"] = f"#{color.r:02x}{color.g:02x}{color.b:02x}"
            print_json(data)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
