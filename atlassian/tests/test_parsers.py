from atlassian_cli.parsers import extract_items_from_snapshot


def test_extract_items_from_snapshot_reads_program_metadata():
    html = """
    <html>
      <head>
        <title>Atlassian Affiliate Program</title>
        <meta name="description" content="Join the Atlassian affiliate program." />
        <link rel="canonical" href="https://www.flexoffers.com/affiliate-programs/atlassian-affiliate-program/" />
      </head>
    </html>
    """

    assert extract_items_from_snapshot(html) == [
        {
            "id": "atlassian-affiliate-program",
            "name": "Atlassian Affiliate Program",
            "status": "active",
            "description": "Join the Atlassian affiliate program.",
        }
    ]
