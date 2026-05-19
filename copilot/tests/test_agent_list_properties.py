from copilot_cli.commands import agent


def test_format_bot_for_display_exposes_logical_name_alias():
    formatted = agent.format_bot_for_display(
        {
            "botid": "agent-123",
            "name": "Example Agent",
            "schemaname": "cr83c_exampleAgent",
        }
    )

    assert formatted["schemaname"] == "cr83c_exampleAgent"
    assert formatted["schemaName"] == "cr83c_exampleAgent"
    assert formatted["logicalName"] == "cr83c_exampleAgent"


def test_logical_name_property_selects_dataverse_schema_name():
    assert agent.AGENT_FIELD_ALIASES["logicalName"] == "schemaname"
