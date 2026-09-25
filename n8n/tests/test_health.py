from n8n_cli import health


def test_non_trigger_connected_ignores_sticky_notes_but_flags_executable_nodes(monkeypatch):
    workflow = {
        "nodes": [
            {
                "id": "note-1",
                "name": "Notes - Overview",
                "type": "n8n-nodes-base.stickyNote",
            },
            {
                "id": "code-1",
                "name": "Disconnected Code",
                "type": "n8n-nodes-base.code",
            },
        ],
        "connections": {},
    }

    monkeypatch.setattr(health, "_is_trigger", lambda _node: False)

    findings = health.check_non_trigger_connected(workflow, api=None)

    assert [(finding.node_id, finding.node) for finding in findings] == [
        ("code-1", "Disconnected Code"),
    ]
