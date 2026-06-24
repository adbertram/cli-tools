"""Google Contacts commands."""
COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
}

import json
import typer
from typing import Optional, List
from googleapiclient.errors import HttpError
from ..client import get_client
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
)
from cli_tools_shared.output import print_error, print_json, print_table, handle_error


app = typer.Typer(help="Access Google Contacts", no_args_is_help=True)

CONTACT_PERSON_FIELDS = (
    "names,emailAddresses,phoneNumbers,organizations,addresses,urls,biographies,metadata"
)
CONTACTS_API_PAGE_SIZE = 1000
PEOPLE_API_SERVICE = "people.googleapis.com"
CONTACT_FILTERABLE_FIELDS = {
    "resourceName",
    "etag",
    "displayName",
    "givenName",
    "familyName",
    "primaryEmail",
    "primaryPhone",
    "organization",
    "title",
}
DEFAULT_TABLE_COLUMNS = ["displayName", "primaryEmail", "organization", "resourceName"]


def _http_error_json(error: HttpError) -> dict:
    content = getattr(error, "content", b"")
    if isinstance(content, bytes):
        content = content.decode("utf-8")
    if not content:
        return {}
    return json.loads(content)


def _people_api_disabled_metadata(error: HttpError) -> Optional[dict]:
    if error.resp.status != 403:
        return None

    try:
        payload = _http_error_json(error)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    for detail in payload.get("error", {}).get("details", []):
        if detail.get("reason") != "SERVICE_DISABLED":
            continue
        metadata = detail.get("metadata", {})
        if metadata.get("service") == PEOPLE_API_SERVICE:
            return metadata
    return None


def _enable_people_api_command(project: str, profile: Optional[str]) -> str:
    command = f"google cloud services enable {PEOPLE_API_SERVICE} --project {project}"
    if profile is not None:
        command += f" --profile {profile}"
    return command


def _handle_people_api_disabled(error: HttpError, profile: Optional[str]) -> bool:
    metadata = _people_api_disabled_metadata(error)
    if metadata is None:
        return False

    consumer = metadata.get("consumer", "")
    project = consumer.removeprefix("projects/") if consumer.startswith("projects/") else ""
    activation_url = metadata.get("activationUrl")

    if project:
        print_error(f"Google People API is disabled for Google Cloud project {project}.")
        print_error(f"Enable it with `{_enable_people_api_command(project, profile)}`, then retry.")
    else:
        print_error("Google People API is disabled for the OAuth client project.")
    if activation_url:
        print_error(f"Google Cloud Console: {activation_url}")
    print_error("If the API was enabled recently, wait a few minutes for propagation before retrying.")
    return True


def _primary(entries: Optional[list[dict]]) -> dict:
    """Return the primary entry, or the first entry when no primary is marked."""
    if not entries:
        return {}
    for entry in entries:
        if entry.get("metadata", {}).get("primary"):
            return entry
    return entries[0]


def _values(entries: Optional[list[dict]], field: str = "value") -> list[str]:
    """Return non-empty string values from repeated People API fields."""
    return [entry[field] for entry in entries or [] if entry.get(field)]


def _organizations(entries: Optional[list[dict]]) -> list[dict]:
    """Return compact organization records for Contacts output."""
    organizations = []
    for entry in entries or []:
        if entry.get("name") or entry.get("title"):
            organizations.append({"name": entry.get("name"), "title": entry.get("title")})
    return organizations


def _properties_to_csv(properties: Optional[List[str]]) -> Optional[str]:
    if not properties:
        return None
    requested = [
        item.strip()
        for value in properties
        for item in value.split(",")
        if item.strip()
    ]
    return ",".join(requested) if requested else None


def normalize_contact(person: dict) -> dict:
    """Normalize a People API Person into the Google Contacts CLI contract."""
    name = _primary(person.get("names"))
    email = _primary(person.get("emailAddresses"))
    phone = _primary(person.get("phoneNumbers"))
    organization = _primary(person.get("organizations"))

    return {
        "resourceName": person["resourceName"],
        "etag": person.get("etag"),
        "displayName": name.get("displayName"),
        "givenName": name.get("givenName"),
        "familyName": name.get("familyName"),
        "primaryEmail": email.get("value"),
        "emailAddresses": _values(person.get("emailAddresses")),
        "primaryPhone": phone.get("value"),
        "phoneNumbers": _values(person.get("phoneNumbers")),
        "organization": organization.get("name"),
        "title": organization.get("title"),
        "organizations": _organizations(person.get("organizations")),
        "addresses": _values(person.get("addresses"), field="formattedValue"),
        "urls": _values(person.get("urls")),
    }


def _list_contacts(service, limit: int, filters: Optional[List[str]]) -> list[dict]:
    if limit < 1:
        raise typer.BadParameter("--limit must be at least 1")

    records = []
    page_token = None

    while True:
        page_size = CONTACTS_API_PAGE_SIZE if filters else min(CONTACTS_API_PAGE_SIZE, limit - len(records))
        params = {
            "resourceName": "people/me",
            "pageSize": page_size,
            "personFields": CONTACT_PERSON_FIELDS,
        }
        if page_token:
            params["pageToken"] = page_token

        response = service.people().connections().list(**params).execute()
        records.extend(
            normalize_contact(person)
            for person in response.get("connections", [])
            if not person.get("metadata", {}).get("deleted")
        )

        page_token = response.get("nextPageToken")
        if not page_token:
            break
        if not filters and len(records) >= limit:
            break

    if filters:
        records = apply_filters(records, filters, allowed_fields=CONTACT_FILTERABLE_FIELDS)
    return records[:limit]


@app.command("list")
def contacts_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of contacts to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., organization:contains:Acme)"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List Google Contacts."""
    try:
        client = get_client(profile=profile)
        service = client.get_people_service()
        records = _list_contacts(service, limit=limit, filters=filter)

        properties_csv = _properties_to_csv(properties)
        if properties_csv:
            records = apply_properties_filter(records, properties_csv)

        if table:
            columns = properties_csv.split(",") if properties_csv else DEFAULT_TABLE_COLUMNS
            print_table(records, columns, [column.title() for column in columns])
        else:
            print_json(records)

    except FilterValidationError as e:
        print_error(str(e))
        raise typer.Exit(1)
    except HttpError as e:
        if _handle_people_api_disabled(e, profile=profile):
            raise typer.Exit(1)
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def contacts_get(
    resource_name: str = typer.Argument(..., help="Contact resource name, for example people/c123"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get a Google Contact by resource name."""
    try:
        client = get_client(profile=profile)
        service = client.get_people_service()
        person = service.people().get(
            resourceName=resource_name,
            personFields=CONTACT_PERSON_FIELDS,
        ).execute()
        record = normalize_contact(person)

        properties_csv = _properties_to_csv(properties)
        if properties_csv:
            record = apply_properties_filter([record], properties_csv)[0]

        if table:
            columns = properties_csv.split(",") if properties_csv else DEFAULT_TABLE_COLUMNS
            print_table([record], columns, [column.title() for column in columns])
        else:
            print_json(record)

    except HttpError as e:
        if _handle_people_api_disabled(e, profile=profile):
            raise typer.Exit(1)
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))
