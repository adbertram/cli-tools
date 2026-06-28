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


def test_status_property_selects_dataverse_statuscode_and_outputs_status(monkeypatch):
    captured = {}

    class FakeClient:
        def list_bots(self, select, limit, filter):
            captured["select"] = select
            return [
                {
                    "botid": "agent-123",
                    "name": "Example Agent",
                    "schemaname": "cr83c_exampleAgent",
                    "statecode": 0,
                    "statuscode": 1,
                }
            ]

    monkeypatch.setattr(agent, "get_client", lambda: FakeClient())
    monkeypatch.setattr(agent, "print_json", lambda payload: captured.setdefault("payload", payload))

    agent.list_agents(
        table=False,
        all_fields=False,
        limit=100,
        filter=None,
        properties="name,botid,schemaname,statecode,status",
    )

    assert "status" not in captured["select"]
    assert "statuscode" in captured["select"]
    assert captured["payload"][0]["status"] == "Active"
    assert captured["payload"][0]["statuscode"] == "Active"


def test_empty_knowledge_list_outputs_json_array_by_default(monkeypatch, capsys):
    captured = {}

    class FakeClient:
        def list_knowledge_sources(self, agent_id, source_type=None):
            return []

    monkeypatch.setattr(agent, "get_client", lambda: FakeClient())
    monkeypatch.setattr(agent, "print_json", lambda payload: captured.setdefault("payload", payload))

    agent.knowledge_list(
        agent_id="00000000-0000-0000-0000-000000000000",
        agent_id_option=None,
        source_type=None,
        table=False,
        limit=100,
        filter=None,
        properties=None,
    )

    assert captured["payload"] == []
    assert capsys.readouterr().out == ""


def test_empty_knowledge_list_keeps_message_for_table(monkeypatch, capsys):
    captured = {}

    class FakeClient:
        def list_knowledge_sources(self, agent_id, source_type=None):
            return []

    monkeypatch.setattr(agent, "get_client", lambda: FakeClient())
    monkeypatch.setattr(agent, "print_json", lambda payload: captured.setdefault("payload", payload))

    agent.knowledge_list(
        agent_id="00000000-0000-0000-0000-000000000000",
        agent_id_option=None,
        source_type=None,
        table=True,
        limit=100,
        filter=None,
        properties=None,
    )

    assert "payload" not in captured
    assert capsys.readouterr().out == "No knowledge sources found for this agent.\n"


def test_empty_tool_list_outputs_json_array_by_default(monkeypatch, capsys):
    captured = {}

    class FakeClient:
        def list_tools(self, agent_id, category=None):
            return []

    monkeypatch.setattr(agent, "get_client", lambda: FakeClient())
    monkeypatch.setattr(agent, "print_json", lambda payload: captured.setdefault("payload", payload))

    agent.tool_list(
        agent_id="00000000-0000-0000-0000-000000000000",
        category=None,
        table=False,
        limit=100,
        filter=None,
        properties=None,
    )

    assert captured["payload"] == []
    assert capsys.readouterr().out == ""


def test_empty_tool_list_keeps_message_for_table(monkeypatch, capsys):
    captured = {}

    class FakeClient:
        def list_tools(self, agent_id, category=None):
            return []

    monkeypatch.setattr(agent, "get_client", lambda: FakeClient())
    monkeypatch.setattr(agent, "print_json", lambda payload: captured.setdefault("payload", payload))

    agent.tool_list(
        agent_id="00000000-0000-0000-0000-000000000000",
        category=None,
        table=True,
        limit=100,
        filter=None,
        properties=None,
    )

    assert "payload" not in captured
    assert capsys.readouterr().out == "No agent tools found for this agent.\n"
