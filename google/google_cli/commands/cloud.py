"""Google Cloud commands."""
COMMAND_CREDENTIALS = {
    "projects": ["custom"],
    "credentials": ["custom"],
    "services": ["custom"],
}

import typer
from typing import Optional, List
from googleapiclient.errors import HttpError
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_error
from cli_tools_shared.filters import apply_filters
from ..filter_translator import translate_cloud_project_filters

app = typer.Typer(help="Manage Google Cloud resources")
projects_app = typer.Typer(help="Manage Google Cloud projects")
app.add_typer(projects_app, name="projects")

credentials_app = typer.Typer(help="Manage project credentials (service accounts, API keys, OAuth clients)")
app.add_typer(credentials_app, name="credentials")

services_app = typer.Typer(help="Manage Google Cloud API services")
app.add_typer(services_app, name="services")


def _normalize_project(project: dict) -> dict:
    """Return the CLI-facing shape for a Cloud project."""
    normalized = dict(project)
    normalized["id"] = project["projectId"]
    return normalized


@projects_app.command("list")
def projects_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of projects to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List Google Cloud projects."""
    try:
        client = get_client(profile=profile)
        service = client.get_cloud_resource_manager_service()

        query = translate_cloud_project_filters(filter) if filter else ""

        all_projects = []
        page_token = None

        while len(all_projects) < limit:
            kwargs = {}
            if query:
                kwargs["query"] = query
            if page_token:
                kwargs["pageToken"] = page_token

            results = service.projects().search(**kwargs).execute()
            projects = results.get("projects", [])
            all_projects.extend(projects)

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        all_projects = [_normalize_project(project) for project in all_projects[:limit]]

        if properties:
            all_projects = [{k: v for k, v in p.items() if k in properties} for p in all_projects]

        if table:
            table_cols = properties[:4] if properties else ['displayName', 'projectId', 'state']
            table_headers = [c for c in table_cols]
            print_table(all_projects, table_cols, table_headers)
        else:
            print_json(all_projects)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@projects_app.command("get")
def projects_get(
    project_id: str = typer.Argument(..., help="Project ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get a Google Cloud project by ID."""
    try:
        client = get_client(profile=profile)
        service = client.get_cloud_resource_manager_service()

        project = _normalize_project(
            service.projects().get(name=f"projects/{project_id}").execute()
        )

        if table:
            print_table([project], ['displayName', 'projectId', 'state'],
                       ['displayName', 'projectId', 'state'])
        else:
            print_json(project)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@projects_app.command("create")
def projects_create(
    project_id: str = typer.Option(..., "--project-id", help="Unique project ID"),
    display_name: str = typer.Option(..., "--display-name", help="Human-readable project name"),
    parent: Optional[str] = typer.Option(None, "--parent", help="Parent resource (e.g. 'organizations/123' or 'folders/456')"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Create a new Google Cloud project."""
    try:
        client = get_client(profile=profile)
        service = client.get_cloud_resource_manager_service()

        body = {
            "projectId": project_id,
            "displayName": display_name,
        }
        if parent:
            body["parent"] = parent

        operation = service.projects().create(body=body).execute()

        print_success(f"Project '{project_id}' creation initiated")
        print_json(operation)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@projects_app.command("update")
def projects_update(
    project_id: str = typer.Argument(..., help="Project ID to update"),
    display_name: Optional[str] = typer.Option(None, "--display-name", help="New display name"),
    labels: Optional[List[str]] = typer.Option(None, "--labels", help="Labels as key=value pairs"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Update a Google Cloud project."""
    try:
        if not display_name and not labels:
            print_error("Provide at least one of --display-name or --labels")
            raise typer.Exit(1)

        client = get_client(profile=profile)
        service = client.get_cloud_resource_manager_service()

        # Get current project to build update
        project = service.projects().get(name=f"projects/{project_id}").execute()

        update_mask_parts = []

        if display_name:
            project["displayName"] = display_name
            update_mask_parts.append("displayName")

        if labels:
            label_dict = {}
            for label in labels:
                if "=" not in label:
                    print_error(f"Invalid label format '{label}'. Use key=value")
                    raise typer.Exit(1)
                key, value = label.split("=", 1)
                label_dict[key] = value
            project["labels"] = label_dict
            update_mask_parts.append("labels")

        update_mask = ",".join(update_mask_parts)

        result = service.projects().patch(
            name=f"projects/{project_id}",
            body=project,
            updateMask=update_mask,
        ).execute()

        print_success(f"Project '{project_id}' updated")
        print_json(result)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@projects_app.command("delete")
def projects_delete(
    project_id: str = typer.Argument(..., help="Project ID to delete"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation prompt"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Delete a Google Cloud project."""
    try:
        if not confirm:
            typer.confirm(f"Are you sure you want to delete project '{project_id}'?", abort=True)

        client = get_client(profile=profile)
        service = client.get_cloud_resource_manager_service()

        service.projects().delete(name=f"projects/{project_id}").execute()

        print_success(f"Project '{project_id}' marked for deletion")

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


# --- Credentials commands ---

CREDENTIAL_TYPES = ["service-account", "api-key", "oauth-client"]


def _list_service_accounts(client, project: str, limit: int):
    """List service accounts for a project."""
    service = client.get_iam_service()
    accounts = []
    page_token = None

    while len(accounts) < limit:
        kwargs = {"name": f"projects/{project}"}
        if page_token:
            kwargs["pageToken"] = page_token

        result = service.projects().serviceAccounts().list(**kwargs).execute()
        for acct in result.get("accounts", []):
            acct["credentialType"] = "service-account"
            accounts.append(acct)

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return accounts[:limit]


def _list_api_keys(client, project: str, limit: int):
    """List API keys for a project."""
    service = client.get_api_keys_service()
    keys = []
    page_token = None

    while len(keys) < limit:
        kwargs = {"parent": f"projects/{project}/locations/global"}
        if page_token:
            kwargs["pageToken"] = page_token

        result = service.projects().locations().keys().list(**kwargs).execute()
        for key in result.get("keys", []):
            key["credentialType"] = "api-key"
            keys.append(key)

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return keys[:limit]


def _list_oauth_clients(client, project: str, limit: int):
    """List OAuth clients for a project."""
    service = client.get_iam_service()
    clients_list = []
    page_token = None

    while len(clients_list) < limit:
        kwargs = {"parent": f"projects/{project}/locations/global"}
        if page_token:
            kwargs["pageToken"] = page_token

        result = service.projects().locations().oauthClients().list(**kwargs).execute()
        for oc in result.get("oauthClients", []):
            oc["credentialType"] = "oauth-client"
            clients_list.append(oc)

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return clients_list[:limit]


@credentials_app.command("list")
def credentials_list(
    project: str = typer.Option(..., "--project", help="GCP project ID"),
    cred_type: Optional[str] = typer.Option(None, "--type", help="Credential type: service-account, api-key, oauth-client"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of credentials to list"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List project credentials."""
    try:
        if cred_type and cred_type not in CREDENTIAL_TYPES:
            print_error(f"Invalid type '{cred_type}'. Must be one of: {', '.join(CREDENTIAL_TYPES)}")
            raise typer.Exit(1)

        client = get_client(profile=profile)
        results = []

        if cred_type is None or cred_type == "service-account":
            results.extend(_list_service_accounts(client, project, limit))
        if cred_type is None or cred_type == "api-key":
            results.extend(_list_api_keys(client, project, limit))
        if cred_type is None or cred_type == "oauth-client":
            results.extend(_list_oauth_clients(client, project, limit))

        results = results[:limit]

        if filter:
            results = apply_filters(results, filter)
        if properties:
            results = [{k: v for k, v in item.items() if k in properties} for item in results]

        if table:
            table_cols = properties[:3] if properties else ["credentialType", "name", "displayName"]
            print_table(results, table_cols, table_cols)
        else:
            print_json(results)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@credentials_app.command("get")
def credentials_get(
    credential_id: str = typer.Argument(..., help="Credential identifier"),
    project: str = typer.Option(..., "--project", help="GCP project ID"),
    cred_type: str = typer.Option(..., "--type", help="Credential type: service-account, api-key, oauth-client"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get a project credential."""
    try:
        if cred_type not in CREDENTIAL_TYPES:
            print_error(f"Invalid type '{cred_type}'. Must be one of: {', '.join(CREDENTIAL_TYPES)}")
            raise typer.Exit(1)

        client = get_client(profile=profile)

        if cred_type == "service-account":
            service = client.get_iam_service()
            resource_name = credential_id
            if not resource_name.startswith("projects/"):
                resource_name = f"projects/{project}/serviceAccounts/{credential_id}"
            result = service.projects().serviceAccounts().get(name=resource_name).execute()
            result["credentialType"] = "service-account"
        elif cred_type == "api-key":
            service = client.get_api_keys_service()
            resource_name = credential_id
            if not resource_name.startswith("projects/"):
                resource_name = f"projects/{project}/locations/global/keys/{credential_id}"
            result = service.projects().locations().keys().get(name=resource_name).execute()
            result["credentialType"] = "api-key"
        else:
            service = client.get_iam_service()
            resource_name = credential_id
            if not resource_name.startswith("projects/"):
                resource_name = f"projects/{project}/locations/global/oauthClients/{credential_id}"
            result = service.projects().locations().oauthClients().get(name=resource_name).execute()
            result["credentialType"] = "oauth-client"

        if table:
            print_table([result], ["credentialType", "name", "displayName"], ["credentialType", "name", "displayName"])
        else:
            print_json(result)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@credentials_app.command("create")
def credentials_create(
    project: str = typer.Option(..., "--project", help="GCP project ID"),
    cred_type: str = typer.Option(..., "--type", help="Credential type: service-account, api-key"),
    account_id: Optional[str] = typer.Option(None, "--account-id", help="Service account ID (required for service-account)"),
    display_name: Optional[str] = typer.Option(None, "--display-name", help="Display name"),
    description: Optional[str] = typer.Option(None, "--description", help="Description (service-account only)"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Create a project credential."""
    try:
        client = get_client(profile=profile)

        if cred_type == "service-account":
            if not account_id:
                print_error("--account-id is required for service-account")
                raise typer.Exit(1)

            service = client.get_iam_service()
            body = {
                "accountId": account_id,
                "serviceAccount": {},
            }
            if display_name:
                body["serviceAccount"]["displayName"] = display_name
            if description:
                body["serviceAccount"]["description"] = description

            result = service.projects().serviceAccounts().create(
                name=f"projects/{project}",
                body=body,
            ).execute()
            print_success(f"Service account '{account_id}' created")
            print_json(result)

        elif cred_type == "api-key":
            service = client.get_api_keys_service()
            body = {}
            if display_name:
                body["displayName"] = display_name

            result = service.projects().locations().keys().create(
                parent=f"projects/{project}/locations/global",
                body=body,
            ).execute()
            print_success("API key created")
            print_json(result)

        elif cred_type == "oauth-client":
            print_error("OAuth clients cannot be created via API. Use the Google Cloud Console: https://console.cloud.google.com/apis/credentials")
            raise typer.Exit(1)

        else:
            print_error(f"Invalid type '{cred_type}'. Must be one of: service-account, api-key")
            raise typer.Exit(1)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@credentials_app.command("update")
def credentials_update(
    credential_id: str = typer.Argument(..., help="Credential identifier (email, key name, or OAuth client name)"),
    project: str = typer.Option(..., "--project", help="GCP project ID"),
    cred_type: str = typer.Option(..., "--type", help="Credential type: service-account, api-key, oauth-client"),
    display_name: Optional[str] = typer.Option(None, "--display-name", help="New display name"),
    description: Optional[str] = typer.Option(None, "--description", help="New description (service-account only)"),
    add_redirect_uri: Optional[str] = typer.Option(None, "--add-redirect-uri", help="Redirect URI to add (oauth-client only)"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Update a project credential."""
    try:
        client = get_client(profile=profile)

        if cred_type == "service-account":
            if not display_name and not description:
                print_error("Provide at least one of --display-name or --description")
                raise typer.Exit(1)

            service = client.get_iam_service()
            resource_name = credential_id
            if not resource_name.startswith("projects/"):
                resource_name = f"projects/{project}/serviceAccounts/{credential_id}"

            # Get current state
            current = service.projects().serviceAccounts().get(name=resource_name).execute()
            update_mask_parts = []

            if display_name:
                current["displayName"] = display_name
                update_mask_parts.append("displayName")
            if description:
                current["description"] = description
                update_mask_parts.append("description")

            result = service.projects().serviceAccounts().patch(
                name=resource_name,
                body={
                    "serviceAccount": current,
                    "updateMask": ",".join(update_mask_parts),
                },
            ).execute()
            print_success("Service account updated")
            print_json(result)

        elif cred_type == "api-key":
            if not display_name:
                print_error("Provide --display-name to update")
                raise typer.Exit(1)

            service = client.get_api_keys_service()
            resource_name = credential_id
            if not resource_name.startswith("projects/"):
                resource_name = f"projects/{project}/locations/global/keys/{credential_id}"

            body = {"displayName": display_name}

            result = service.projects().locations().keys().patch(
                name=resource_name,
                body=body,
                updateMask="displayName",
            ).execute()
            print_success("API key updated")
            print_json(result)

        elif cred_type == "oauth-client":
            if not add_redirect_uri:
                print_error("Provide --add-redirect-uri for oauth-client updates")
                raise typer.Exit(1)

            service = client.get_iam_service()
            resource_name = credential_id
            if not resource_name.startswith("projects/"):
                resource_name = f"projects/{project}/locations/global/oauthClients/{credential_id}"

            # Get current OAuth client to read existing redirect URIs
            current = service.projects().locations().oauthClients().get(name=resource_name).execute()
            existing_uris = current.get("allowedRedirectUris", [])

            if add_redirect_uri in existing_uris:
                print_error(f"Redirect URI '{add_redirect_uri}' already exists")
                raise typer.Exit(1)

            updated_uris = existing_uris + [add_redirect_uri]

            result = service.projects().locations().oauthClients().patch(
                name=resource_name,
                body={"allowedRedirectUris": updated_uris},
                updateMask="allowedRedirectUris",
            ).execute()
            print_success(f"OAuth client updated with redirect URI '{add_redirect_uri}'")
            print_json(result)

        else:
            print_error(f"Invalid type '{cred_type}'. Must be one of: {', '.join(CREDENTIAL_TYPES)}")
            raise typer.Exit(1)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


# --- Services commands ---


@services_app.command("list")
def services_list(
    project: str = typer.Option(..., "--project", help="GCP project ID or number"),
    state: Optional[str] = typer.Option("ENABLED", "--state", help="Filter by state: ENABLED, DISABLED, or ALL"),
    limit: int = typer.Option(200, "--limit", "-l", help="Maximum number of services to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List API services for a project."""
    try:
        client = get_client(profile=profile)
        service = client.get_service_usage_service()

        all_services = []
        page_token = None

        filter_str = ""
        if state and state.upper() != "ALL":
            filter_str = f"state:{state.upper()}"

        while len(all_services) < limit:
            kwargs = {"parent": f"projects/{project}"}
            if filter_str:
                kwargs["filter"] = filter_str
            if page_token:
                kwargs["pageToken"] = page_token

            results = service.services().list(**kwargs).execute()
            svcs = results.get("services", [])

            for svc in svcs:
                config = svc.get("config", {})
                all_services.append({
                    "name": config.get("name", svc.get("name", "")),
                    "title": config.get("title", ""),
                    "state": svc.get("state", ""),
                })

            page_token = results.get("nextPageToken")
            if not page_token:
                break

        all_services = all_services[:limit]

        if filter:
            all_services = apply_filters(all_services, filter)
        if properties:
            all_services = [{k: v for k, v in s.items() if k in properties} for s in all_services]

        if table:
            table_cols = properties[:4] if properties else ["name", "title", "state"]
            print_table(all_services, table_cols, table_cols)
        else:
            print_json(all_services)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@services_app.command("enable")
def services_enable(
    service_name: str = typer.Argument(..., help="API service name (e.g. gmail.googleapis.com)"),
    project: str = typer.Option(..., "--project", help="GCP project ID or number"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Enable an API service for a project."""
    try:
        client = get_client(profile=profile)
        service = client.get_service_usage_service()

        result = service.services().enable(
            name=f"projects/{project}/services/{service_name}",
            body={},
        ).execute()

        print_success(f"Service '{service_name}' enabled for project '{project}'")
        print_json(result)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@services_app.command("disable")
def services_disable(
    service_name: str = typer.Argument(..., help="API service name (e.g. gmail.googleapis.com)"),
    project: str = typer.Option(..., "--project", help="GCP project ID or number"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation prompt"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Disable an API service for a project."""
    try:
        if not confirm:
            typer.confirm(f"Are you sure you want to disable '{service_name}' for project '{project}'?", abort=True)

        client = get_client(profile=profile)
        service = client.get_service_usage_service()

        result = service.services().disable(
            name=f"projects/{project}/services/{service_name}",
            body={},
        ).execute()

        print_success(f"Service '{service_name}' disabled for project '{project}'")
        print_json(result)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@services_app.command("get")
def services_get(
    service_name: str = typer.Argument(..., help="API service name (e.g. gmail.googleapis.com)"),
    project: str = typer.Option(..., "--project", help="GCP project ID or number"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get details of an API service for a project."""
    try:
        client = get_client(profile=profile)
        service = client.get_service_usage_service()

        result = service.services().get(
            name=f"projects/{project}/services/{service_name}",
        ).execute()

        config = result.get("config", {})
        output = {
            "name": config.get("name", result.get("name", "")),
            "title": config.get("title", ""),
            "state": result.get("state", ""),
        }

        print_json(output)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))
