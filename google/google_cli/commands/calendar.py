"""Google Calendar commands."""
COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "search": ["custom"],
    "today": ["custom"],
}

import typer
from datetime import datetime, timedelta
from typing import Optional, List
from googleapiclient.errors import HttpError
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_error
from cli_tools_shared.filters import apply_filters as _client_side_filter_reference
from ..filter_translator import translate_calendar_filters

app = typer.Typer(help="Access Google Calendar events")

@app.command("list")
def calendar_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of events to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    days: int = typer.Option(7, "--days", "-d", help="Number of days to look ahead"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List upcoming calendar events."""
    try:
        client = get_client(profile=profile)
        service = client.get_calendar_service()

        # Get events from now to N days ahead
        now = datetime.utcnow().isoformat() + 'Z'
        end_date = (datetime.utcnow() + timedelta(days=days)).isoformat() + 'Z'

        list_params = {
            'calendarId': 'primary',
            'timeMin': now,
            'timeMax': end_date,
            'maxResults': limit,
            'singleEvents': True,
            'orderBy': 'startTime'
        }

        # Translate filters to API parameters (supports both standard and native formats)
        if filter:
            filter_params = translate_calendar_filters(filter)
            list_params.update(filter_params)

        events_result = service.events().list(**list_params).execute()

        events = events_result.get('items', [])

        if not events:
            print_error("No upcoming events found")
            raise typer.Exit(1)

        # Default properties
        default_props = ['id', 'summary', 'start', 'end', 'location']
        props_to_include = properties if properties else default_props

        # Format events
        formatted_events = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))

            full_event = {
                'id': event['id'],
                'summary': event.get('summary', 'No title'),
                'start': start,
                'end': end,
                'location': event.get('location', ''),
                'description': event.get('description', ''),
                'status': event.get('status', ''),
                'htmlLink': event.get('htmlLink', ''),
            }

            # Filter to requested properties
            if properties:
                full_event = {k: v for k, v in full_event.items() if k in props_to_include}

            formatted_events.append(full_event)

        if table:
            table_cols = [p for p in ['summary', 'start', 'location'] if p in props_to_include or not properties]
            table_headers = {'summary': 'Event', 'start': 'Start Time', 'location': 'Location'}
            print_table(formatted_events, table_cols, [table_headers.get(c, c.title()) for c in table_cols])
        else:
            print_json(formatted_events)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

@app.command("get")
def calendar_get(
    event_id: str = typer.Argument(..., help="Event ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get a specific calendar event."""
    try:
        client = get_client(profile=profile)
        service = client.get_calendar_service()

        event = service.events().get(
            calendarId='primary',
            eventId=event_id
        ).execute()

        if table:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            data = [{
                'summary': event.get('summary', 'No title'),
                'start': start,
                'location': event.get('location', ''),
            }]
            print_table(data, ['summary', 'start', 'location'], ['Event', 'Start Time', 'Location'])
        else:
            print_json(event)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

@app.command("search")
def calendar_search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Search calendar events."""
    try:
        client = get_client(profile=profile)
        service = client.get_calendar_service()

        events_result = service.events().list(
            calendarId='primary',
            q=query,
            maxResults=limit,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])

        if not events:
            print_error("No events found")
            raise typer.Exit(1)

        # Default properties
        default_props = ['id', 'summary', 'start', 'end', 'location']
        props_to_include = properties if properties else default_props

        # Format events
        formatted_events = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))

            full_event = {
                'id': event['id'],
                'summary': event.get('summary', 'No title'),
                'start': start,
                'end': end,
                'location': event.get('location', ''),
                'description': event.get('description', ''),
                'status': event.get('status', ''),
                'htmlLink': event.get('htmlLink', ''),
            }

            # Filter to requested properties
            if properties:
                full_event = {k: v for k, v in full_event.items() if k in props_to_include}

            formatted_events.append(full_event)

        if table:
            table_cols = [p for p in ['summary', 'start', 'location'] if p in props_to_include or not properties]
            table_headers = {'summary': 'Event', 'start': 'Start Time', 'location': 'Location'}
            print_table(formatted_events, table_cols, [table_headers.get(c, c.title()) for c in table_cols])
        else:
            print_json(formatted_events)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

@app.command("today")
def calendar_today(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List today's calendar events."""
    try:
        client = get_client(profile=profile)
        service = client.get_calendar_service()

        # Get events for today
        now = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = now + timedelta(days=1)

        events_result = service.events().list(
            calendarId='primary',
            timeMin=now.isoformat() + 'Z',
            timeMax=end_of_day.isoformat() + 'Z',
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])

        if not events:
            print_error("No events today")
            raise typer.Exit(1)

        # Format events
        formatted_events = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))

            formatted_events.append({
                'id': event['id'],
                'summary': event.get('summary', 'No title'),
                'start': start,
                'end': end,
                'location': event.get('location', ''),
            })

        if table:
            print_table(
                formatted_events,
                ['summary', 'start', 'location'],
                ['Event', 'Start Time', 'Location']
            )
        else:
            print_json(formatted_events)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))
