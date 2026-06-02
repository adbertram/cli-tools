"""Campaigns commands for Mailchimp CLI."""
import re
import typer
from typing import List, Optional
from urllib.parse import urlparse

from cli_tools_shared.filters import apply_filters, apply_limit, apply_properties_filter
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_error, print_info

from ..client import get_client

app = typer.Typer(help="Manage email campaigns")

SPONSOR_SECTION_LINK_PATTERN = re.compile(
    r'Messages from our Sponsors.*?<a[^>]+href=["\']([^"\']+)["\']',
    re.IGNORECASE | re.DOTALL
)


def _normalize_domain(domain: str) -> str:
    value = domain.strip().lower()
    if value.startswith("http://"):
        value = value[7:]
    if value.startswith("https://"):
        value = value[8:]
    value = value.split("/", 1)[0]
    if value.startswith("www."):
        value = value[4:]
    return value.rstrip(".")


def extract_sponsor_domains_from_html(html: str, sponsor_domains: List[str]) -> List[str]:
    normalized_domains = [_normalize_domain(domain) for domain in sponsor_domains]
    sponsor_match = SPONSOR_SECTION_LINK_PATTERN.search(html)
    if not sponsor_match:
        return []

    href = sponsor_match.group(1)
    host = _normalize_domain(urlparse(href).netloc or href)
    return [
        domain for domain in normalized_domains
        if host == domain or host.endswith(f".{domain}")
    ]


def _campaign_sponsor_domains(client, campaign_id: str, sponsor_domains: Optional[List[str]]) -> List[str]:
    if not sponsor_domains:
        return []
    content = client.get_campaign_content(campaign_id)
    html = content.get("html", "")
    return extract_sponsor_domains_from_html(html, sponsor_domains)


@app.command("list")
def campaigns_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of campaigns to return"),
    offset: int = typer.Option(0, "--offset", "-o", help="Offset for pagination"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (save, paused, schedule, sending, sent)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    include_rss_child_campaigns: bool = typer.Option(
        False, "--include-rss-child-campaigns", help="Include RSS child campaigns (individual sends from RSS campaigns)"
    ),
    rss_parent_id: Optional[str] = typer.Option(
        None, "--rss-parent-id", help="Filter to only show child campaigns of a specific RSS campaign"
    ),
    sponsor_domain: Optional[List[str]] = typer.Option(
        None, "--sponsor-domain", help="Sponsor domain to detect in campaign sponsor content. Repeat for multiple domains."
    ),
):
    """
    List all campaigns in the account.

    RSS campaigns in Mailchimp create child campaigns for each send. Use
    --include-rss-child-campaigns to include these in the output, or
    --rss-parent-id to filter to a specific RSS campaign's children.

    Examples:
        mailchimp campaigns list
        mailchimp campaigns list --table
        mailchimp campaigns list --status sent
        mailchimp campaigns list --count 20
        mailchimp campaigns list --include-rss-child-campaigns
        mailchimp campaigns list --rss-parent-id CAMPAIGN_ID --table
    """
    try:
        client = get_client()

        kwargs = {}
        if status:
            kwargs["status"] = status

        # If filtering by RSS parent, we need to fetch and filter client-side
        # since the API doesn't support parent_campaign_id filtering
        if rss_parent_id:
            # Fetch more campaigns to ensure we find all children
            result = client.list_campaigns(count=1000, offset=offset, **kwargs)
            all_campaigns = result.get("campaigns", [])
            # Filter to only children of the specified parent
            campaigns = [c for c in all_campaigns if c.get("parent_campaign_id") == rss_parent_id]
            result["campaigns"] = campaigns
            result["total_items"] = len(campaigns)
        elif include_rss_child_campaigns:
            # Include all campaigns, including RSS child campaigns
            result = client.list_campaigns(count=limit, offset=offset, **kwargs)
            campaigns = result.get("campaigns", [])
        else:
            # Default behavior: exclude RSS child campaigns
            result = client.list_campaigns(count=limit, offset=offset, **kwargs)
            all_campaigns = result.get("campaigns", [])
            # Filter out campaigns with parent_campaign_id (RSS children)
            campaigns = [c for c in all_campaigns if not c.get("parent_campaign_id")]

        for campaign in campaigns:
            matched_domains = _campaign_sponsor_domains(client, campaign.get("id"), sponsor_domain)
            if sponsor_domain:
                campaign["sponsor_domains"] = matched_domains

        campaigns = apply_filters(campaigns, filter)
        campaigns = apply_limit(campaigns, limit)
        campaigns = apply_properties_filter(campaigns, properties)

        if table:
            columns = [field.strip() for field in properties.split(",")] if properties else ["id", "type", "status", "settings.subject_line", "create_time"]
            headers = [column.replace("_", " ").replace(".", " ").title() for column in columns]
            if include_rss_child_campaigns or rss_parent_id:
                columns.insert(-1, "parent_id")
                headers.insert(-1, "Parent ID")
            if sponsor_domain:
                columns.append("sponsor_domains")
                headers.append("Sponsor Domains")

            print_table(campaigns, columns, headers)
        else:
            print_json(campaigns)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def campaigns_get(
    campaign_id: str = typer.Argument(..., help="The campaign ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
):
    """
    Get details for a specific campaign.

    Examples:
        mailchimp campaigns get CAMPAIGN_ID
        mailchimp campaigns get CAMPAIGN_ID --table
    """
    try:
        client = get_client()
        campaign = client.get_campaign(campaign_id)

        if table:
            settings = campaign.get("settings", {})
            recipients = campaign.get("recipients", {})
            summary = [{
                "id": campaign.get("id", ""),
                "type": campaign.get("type", ""),
                "status": campaign.get("status", ""),
                "subject": settings.get("subject_line", "N/A"),
                "list_id": recipients.get("list_id", "N/A"),
                "created": campaign.get("create_time", "")[:10],
            }]

            print_table(
                summary,
                ["id", "type", "status", "subject", "list_id", "created"],
                ["ID", "Type", "Status", "Subject", "List ID", "Created"],
            )
        else:
            print_json(campaign)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def campaigns_create(
    campaign_type: str = typer.Option("regular", "--type", "-t", help="Campaign type (regular, plaintext, absplit, rss, variate)"),
    list_id: str = typer.Option(..., "--list-id", "-l", help="The list/audience ID"),
    subject: str = typer.Option(..., "--subject", "-s", help="Email subject line"),
    from_name: str = typer.Option(..., "--from-name", help="From name"),
    reply_to: str = typer.Option(..., "--reply-to", help="Reply-to email address"),
    title: Optional[str] = typer.Option(None, "--title", help="Campaign title (internal)"),
):
    """
    Create a new campaign.

    Example:
        mailchimp campaigns create --list-id LIST_ID \\
            --subject "Monthly Newsletter" \\
            --from-name "ACME Inc" \\
            --reply-to "support@example.com" \\
            --title "January Newsletter"
    """
    try:
        client = get_client()

        data = {
            "type": campaign_type,
            "recipients": {
                "list_id": list_id,
            },
            "settings": {
                "subject_line": subject,
                "from_name": from_name,
                "reply_to": reply_to,
            },
        }

        if title:
            data["settings"]["title"] = title

        result = client.create_campaign(data)
        print_success(f"Created campaign: {result.get('id')}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("send")
def campaigns_send(
    campaign_id: str = typer.Argument(..., help="The campaign ID"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """
    Send a campaign.

    Examples:
        mailchimp campaigns send CAMPAIGN_ID
        mailchimp campaigns send CAMPAIGN_ID --yes
    """
    try:
        if not confirm:
            confirm = typer.confirm(f"Are you sure you want to send campaign {campaign_id}?")
            if not confirm:
                print_info("Cancelled")
                raise typer.Exit(0)

        client = get_client()
        result = client.send_campaign(campaign_id)
        print_success(f"Campaign sent: {campaign_id}")
        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("pause")
def campaigns_pause(
    campaign_id: str = typer.Argument(..., help="The RSS campaign ID"),
):
    """
    Pause an RSS-Driven campaign.

    Only applies to campaigns of type "rss". Stops further scheduled sends
    until resumed.

    Example:
        mailchimp campaigns pause CAMPAIGN_ID
    """
    try:
        client = get_client()
        client.pause_rss_campaign(campaign_id)
        print_success(f"Paused RSS campaign: {campaign_id}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("resume")
def campaigns_resume(
    campaign_id: str = typer.Argument(..., help="The RSS campaign ID"),
):
    """
    Resume a paused RSS-Driven campaign.

    Example:
        mailchimp campaigns resume CAMPAIGN_ID
    """
    try:
        client = get_client()
        client.resume_rss_campaign(campaign_id)
        print_success(f"Resumed RSS campaign: {campaign_id}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("report")
def campaigns_report(
    campaign_id: str = typer.Argument(..., help="The campaign ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    count: int = typer.Option(10, "--count", "-c", help="For RSS campaigns: number of child reports to show"),
    sponsor_domain: Optional[List[str]] = typer.Option(
        None, "--sponsor-domain", help="Sponsor domain to detect in campaign sponsor content. Repeat for multiple domains."
    ),
):
    """
    Get report/analytics for a campaign.

    For RSS campaigns, this shows reports from child campaigns (most recent first).

    Examples:
        mailchimp campaigns report CAMPAIGN_ID
        mailchimp campaigns report CAMPAIGN_ID --table
        mailchimp campaigns report RSS_CAMPAIGN_ID --table --count 20
    """
    try:
        client = get_client()

        # Check if this is an RSS campaign
        campaign = client.get_campaign(campaign_id)
        is_rss = campaign.get("type") == "rss"

        if is_rss:
            # Use sub-reports endpoint for RSS campaigns (single API call)
            result = client.get_campaign_sub_reports(campaign_id, count=count)
            reports = result.get("reports", [])

            if not reports:
                print_info("No child campaign reports found for this RSS campaign.")
                raise typer.Exit(0)

            table_data = []
            for report in reports:
                emails_sent = report.get("emails_sent", 0)
                opens = report.get("opens", {})
                clicks = report.get("clicks", {})
                bounces = report.get("bounces", {})

                open_rate = opens.get("open_rate", 0) * 100
                click_rate = clicks.get("click_rate", 0) * 100
                bounce_rate = (bounces.get("hard_bounces", 0) + bounces.get("soft_bounces", 0)) / emails_sent * 100 if emails_sent > 0 else 0
                unsub_rate = report.get("unsubscribed", 0) / emails_sent * 100 if emails_sent > 0 else 0

                row = {
                    "id": report.get("id", ""),
                    "sent_date": report.get("send_time", "")[:10] if report.get("send_time") else "N/A",
                    "emails": emails_sent,
                    "opens": opens.get("unique_opens", 0),
                    "clicks": clicks.get("unique_clicks", 0),
                    "open_rate": f"{open_rate:.1f}%",
                    "click_rate": f"{click_rate:.1f}%",
                    "bounce_rate": f"{bounce_rate:.1f}%",
                    "unsub_rate": f"{unsub_rate:.2f}%",
                }

                if sponsor_domain:
                    row["sponsor_domains"] = _campaign_sponsor_domains(client, report.get("id"), sponsor_domain)

                table_data.append(row)

            if table:
                columns = ["id", "sent_date", "emails", "opens", "clicks", "open_rate", "click_rate", "bounce_rate", "unsub_rate"]
                headers = ["ID", "Sent", "Emails", "Opens", "Clicks", "Open%", "Click%", "Bounce%", "Unsub%"]
                if sponsor_domain:
                    columns.append("sponsor_domains")
                    headers.append("Sponsor Domains")
                print_table(
                    table_data,
                    columns,
                    headers,
                )
            else:
                print_json({"campaign_id": campaign_id, "type": "rss", "child_reports": table_data})
        else:
            # Regular campaign report
            report = client.get_campaign_report(campaign_id)
            matched_domains = _campaign_sponsor_domains(client, campaign_id, sponsor_domain)

            if table:
                emails_sent = report.get("emails_sent", 0)
                opens = report.get("opens", {})
                clicks = report.get("clicks", {})
                bounces = report.get("bounces", {})

                open_rate = opens.get("open_rate", 0) * 100
                click_rate = clicks.get("click_rate", 0) * 100
                bounce_rate = (bounces.get("hard_bounces", 0) + bounces.get("soft_bounces", 0)) / emails_sent * 100 if emails_sent > 0 else 0
                unsub_rate = report.get("unsubscribed", 0) / emails_sent * 100 if emails_sent > 0 else 0

                summary = [{
                    "campaign_id": report.get("id", ""),
                    "sent": emails_sent,
                    "opens": opens.get("unique_opens", 0),
                    "clicks": clicks.get("unique_clicks", 0),
                    "open_rate": f"{open_rate:.1f}%",
                    "click_rate": f"{click_rate:.1f}%",
                    "bounce_rate": f"{bounce_rate:.1f}%",
                    "unsub_rate": f"{unsub_rate:.2f}%",
                }]
                if sponsor_domain:
                    summary[0]["sponsor_domains"] = ",".join(matched_domains)

                columns = ["campaign_id", "sent", "opens", "clicks", "open_rate", "click_rate", "bounce_rate", "unsub_rate"]
                headers = ["Campaign ID", "Sent", "Opens", "Clicks", "Open%", "Click%", "Bounce%", "Unsub%"]
                if sponsor_domain:
                    columns.append("sponsor_domains")
                    headers.append("Sponsor Domains")
                print_table(
                    summary,
                    columns,
                    headers,
                )
            else:
                if sponsor_domain:
                    report["sponsor_domains"] = matched_domains
                print_json(report)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("content")
def campaigns_content(
    campaign_id: str = typer.Argument(..., help="The campaign ID"),
    html: bool = typer.Option(False, "--html", help="Output only the HTML content"),
    text: bool = typer.Option(False, "--text", help="Output only the plain text content"),
):
    """
    Get the content (HTML/text) for a campaign.

    Examples:
        mailchimp campaigns content CAMPAIGN_ID
        mailchimp campaigns content CAMPAIGN_ID --html
        mailchimp campaigns content CAMPAIGN_ID --text
    """
    try:
        client = get_client()
        content = client.get_campaign_content(campaign_id)

        if html:
            print(content.get("html", ""))
        elif text:
            print(content.get("plain_text", ""))
        else:
            print_json(content)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("children")
def campaigns_children(
    campaign_id: str = typer.Argument(..., help="The parent RSS campaign ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    count: int = typer.Option(100, "--count", "-c", help="Maximum number of child campaigns to return"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (sent)"),
    with_reports: bool = typer.Option(False, "--with-reports", "-r", help="Include report metrics (open/click/bounce/unsub rates)"),
):
    """
    List all child campaigns (individual sends) for an RSS campaign.

    Each time an RSS campaign sends, Mailchimp creates a child campaign.
    This command lists all historical sends for a given RSS campaign.

    Examples:
        mailchimp campaigns children RSS_CAMPAIGN_ID
        mailchimp campaigns children RSS_CAMPAIGN_ID --table
        mailchimp campaigns children RSS_CAMPAIGN_ID --table --with-reports
    """
    try:
        client = get_client()

        kwargs = {}
        if status:
            kwargs["status"] = status

        # Fetch campaigns and filter to children of the specified parent
        result = client.list_campaigns(count=count, offset=0, **kwargs)
        all_campaigns = result.get("campaigns", [])

        # Filter to only children of the specified parent
        children = [c for c in all_campaigns if c.get("parent_campaign_id") == campaign_id]

        # Sort by send_time descending (most recent first)
        children.sort(key=lambda c: c.get("send_time", ""), reverse=True)

        if table:
            table_data = []
            for campaign in children:
                settings = campaign.get("settings", {})
                row = {
                    "id": campaign.get("id", ""),
                    "subject": settings.get("subject_line", "N/A"),
                    "sent": campaign.get("send_time", "N/A")[:10] if campaign.get("send_time") else "N/A",
                    "emails": campaign.get("emails_sent", 0),
                }

                if with_reports:
                    # Fetch report for this campaign
                    report = client.get_campaign_report(campaign.get("id"))
                    emails_sent = report.get("emails_sent", 0)
                    opens = report.get("opens", {})
                    clicks = report.get("clicks", {})
                    bounces = report.get("bounces", {})

                    open_rate = opens.get("open_rate", 0) * 100
                    click_rate = clicks.get("click_rate", 0) * 100
                    bounce_rate = (bounces.get("hard_bounces", 0) + bounces.get("soft_bounces", 0)) / emails_sent * 100 if emails_sent > 0 else 0
                    unsub_rate = report.get("unsubscribed", 0) / emails_sent * 100 if emails_sent > 0 else 0

                    row["unique_opens"] = opens.get("unique_opens", 0)
                    row["unique_clicks"] = clicks.get("unique_clicks", 0)
                    row["open_rate"] = f"{open_rate:.1f}%"
                    row["click_rate"] = f"{click_rate:.1f}%"
                    row["bounce_rate"] = f"{bounce_rate:.1f}%"
                    row["unsub_rate"] = f"{unsub_rate:.2f}%"

                table_data.append(row)

            if with_reports:
                # Show all metrics when reports are requested
                columns = ["id", "sent", "emails", "unique_opens", "unique_clicks", "open_rate", "click_rate", "bounce_rate", "unsub_rate"]
                headers = ["ID", "Sent", "Emails", "Opens", "Clicks", "Open%", "Click%", "Bounce%", "Unsub%"]
            else:
                columns = ["id", "subject", "sent", "emails"]
                headers = ["ID", "Subject", "Sent", "Emails"]

            print_table(table_data, columns, headers)
        else:
            print_json({"campaigns": children, "total_items": len(children)})

    except Exception as e:
        raise typer.Exit(handle_error(e))




COMMAND_CREDENTIALS = {
    "children": [
        "custom"
    ],
    "content": [
        "custom"
    ],
    "create": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "pause": [
        "custom"
    ],
    "report": [
        "custom"
    ],
    "resume": [
        "custom"
    ],
    "send": [
        "custom"
    ]
}
