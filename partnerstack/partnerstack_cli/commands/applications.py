"""Application (program-application) commands for PartnerStack CLI."""
import json
from typing import List, Optional

import typer

from ..client import AUTH_BASIC, get_client
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import handle_error, print_json, print_table

from ._common import model_to_dict


COMMAND_CREDENTIALS = {
    "create": ["custom"],
}
COMMAND_AUTH_TYPES = {
    "create": AUTH_BASIC,
}


app = typer.Typer(
    help="Create PartnerStack partner applications using Basic auth",
    no_args_is_help=True,
)


_APPLICATIONS_401_REMEDIATION = (
    "POST /api/v2/applications uses PartnerStack Basic auth. Configure the "
    "public/secret key pair with 'partnerstack auth login' before creating applications."
)


@app.command(
    "create",
    epilog=_APPLICATIONS_401_REMEDIATION,
)
def applications_create(
    group_slug: str = typer.Option(
        ...,
        "--group-slug",
        help=(
            "Slug of the group to apply to. Discover valid slugs via "
            "'partnerstack form-templates list' (the form-template's 'group' field). "
            "Documented examples: affiliates, resellers, referral, topsellers (vendor-defined)."
        ),
    ),
    meta: Optional[str] = typer.Option(
        None,
        "--meta",
        help=(
            "Application meta object as a JSON string. Example: "
            "'{\"first_name\":\"Jane\",\"last_name\":\"Doe\","
            "\"email\":\"jane@example.com\",\"business_name\":\"Example LLC\"}'"
        ),
    ),
    meta_field: Optional[List[str]] = typer.Option(
        None,
        "--meta-field",
        help=(
            "Repeatable key=value pair appended to the meta object. "
            "Example: --meta-field first_name=Jane --meta-field email=jane@example.com"
        ),
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Create a partner application against a target program."""
    try:
        meta_payload = _build_meta_payload(meta, meta_field)
        client = get_client(COMMAND_AUTH_TYPES["create"])
        application = client.create_application(group_slug, meta_payload)

        if table:
            data = model_to_dict(application)
            rows = [{"field": key, "value": value} for key, value in data.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(application)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


def _build_meta_payload(meta_json: Optional[str], meta_fields: Optional[List[str]]) -> dict:
    """Combine --meta JSON and --meta-field key=value pairs into a dict."""
    payload: dict = {}
    if meta_json is not None:
        parsed = json.loads(meta_json)
        if not isinstance(parsed, dict):
            raise ClientError("--meta must be a JSON object")
        payload.update(parsed)

    if meta_fields:
        for entry in meta_fields:
            if "=" not in entry:
                raise ClientError(
                    f"Invalid --meta-field '{entry}'. Expected key=value."
                )
            key, value = entry.split("=", 1)
            key = key.strip()
            if not key:
                raise ClientError(f"Invalid --meta-field '{entry}'. Empty key.")
            payload[key] = value

    if not payload:
        raise ClientError(
            "--meta or --meta-field must be provided. PartnerStack requires a non-empty meta object."
        )

    return payload
