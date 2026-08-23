"""Tests for the globiflow flows export/import command group."""
import base64
import io
import json
import zipfile

from typer.testing import CliRunner

from globiflow_cli import client as client_module
from globiflow_cli.client import GlobiflowClient, ClientError
from globiflow_cli.commands import flows
from globiflow_cli.models import FlowDetail


# --------------------------------------------------------------------------
# Command wiring
# --------------------------------------------------------------------------


def test_export_command_writes_xml_file_and_prints_json(monkeypatch, tmp_path):
    """`flows export` must write the client's XML to the output file and
    report the flow id, path, and byte count on stdout as JSON."""
    runner = CliRunner()

    class _FakeClient:
        def export_flow(self, flow_id):
            assert flow_id == "4321944"
            return "<root><flow>hi</flow></root>"

        def close(self):
            return None

    monkeypatch.setattr(flows, "get_client", lambda: _FakeClient())

    out_path = str(tmp_path / "out.xml")
    result = runner.invoke(flows.app, ["export", "4321944", "--output", out_path])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["flow_id"] == "4321944"
    assert payload["output"] == out_path
    assert payload["bytes"] == len("<root><flow>hi</flow></root>")

    written = open(out_path, encoding="utf-8").read()
    assert written == "<root><flow>hi</flow></root>"


def test_export_command_defaults_output_to_flow_id_xml(monkeypatch, tmp_path):
    """Without --output, the export file is named flow-<id>.xml in the cwd."""
    runner = CliRunner()

    class _FakeClient:
        def export_flow(self, flow_id):
            return "<root/>"

        def close(self):
            return None

    monkeypatch.setattr(flows, "get_client", lambda: _FakeClient())
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(flows.app, ["export", "123"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["output"] == "flow-123.xml"
    assert (tmp_path / "flow-123.xml").exists()


def test_import_command_reads_file_and_prints_flow(monkeypatch, tmp_path):
    """`flows import` must read the XML file, call import_flow with the app
    id, fetch the new flow, and print its JSON."""
    runner = CliRunner()
    calls = []

    class _FakeClient:
        def import_flow(self, app_id, xml):
            calls.append((app_id, xml))
            return "4406551"

        def get_flow(self, flow_id):
            assert flow_id == "4406551"
            return FlowDetail(id="4406551", name="Imported", enabled=True)

        def close(self):
            return None

    monkeypatch.setattr(flows, "get_client", lambda: _FakeClient())

    in_path = tmp_path / "in.xml"
    in_path.write_text("<root><flow/></root>", encoding="utf-8")

    result = runner.invoke(
        flows.app, ["import", "--app-id", "30529466", "--file", str(in_path)]
    )

    assert result.exit_code == 0, result.output
    assert calls == [("30529466", "<root><flow/></root>")]
    payload = json.loads(result.stdout)
    assert payload["id"] == "4406551"
    assert payload["name"] == "Imported"


def test_import_command_rejects_missing_file(monkeypatch, tmp_path):
    """`flows import` must fail cleanly when the file does not exist."""
    runner = CliRunner()

    class _FakeClient:
        def import_flow(self, app_id, xml):
            raise AssertionError("import_flow must not run for a missing file")

        def close(self):
            return None

    monkeypatch.setattr(flows, "get_client", lambda: _FakeClient())

    result = runner.invoke(
        flows.app,
        ["import", "--app-id", "30529466", "--file", str(tmp_path / "nope.xml")],
    )

    assert result.exit_code == 1
    assert "not found" in result.output


# --------------------------------------------------------------------------
# Client export_flow
# --------------------------------------------------------------------------


def _b64_zip(entries):
    """Build a base64-encoded ZIP whose entries map name -> bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class _FakePage:
    def __init__(self, url="https://workflow-automation.podio.com/flows.php?app=30529466"):
        self.url = url


def _client_with_page(monkeypatch, page):
    client = GlobiflowClient()
    monkeypatch.setattr(client, "ensure_authenticated", lambda path="/": None)
    monkeypatch.setattr(client, "_resolve_flow_app_id", lambda flow_id: "30529466")

    class _FakeBrowser:
        def get_page(self, url=None):
            return page

    monkeypatch.setattr(GlobiflowClient, "browser", property(lambda self: _FakeBrowser()))
    return client


def test_export_flow_extracts_xml_from_zip(monkeypatch):
    """export_flow must decode the base64 ZIP returned by the page and return
    the flow-<id>.xml entry's text."""
    xml = "<root><flowName>My Flow</flowName></root>"
    page = _FakePage()
    page.evaluate = lambda js: _b64_zip({"flow-4321944.xml": xml.encode("utf-8")})

    client = _client_with_page(monkeypatch, page)

    assert client.export_flow("4321944") == xml


def test_export_flow_raises_when_zip_missing_expected_entry(monkeypatch):
    """export_flow must raise when the ZIP lacks flow-<id>.xml."""
    page = _FakePage()
    page.evaluate = lambda js: _b64_zip({"other.xml": b"<root/>"})

    client = _client_with_page(monkeypatch, page)

    try:
        client.export_flow("4321944")
        raise AssertionError("Expected ClientError for missing ZIP entry")
    except client_module.ClientError as e:
        assert "flow-4321944.xml" in str(e)


def test_export_flow_raises_on_empty_response(monkeypatch):
    """export_flow must raise when the page returns no content."""
    page = _FakePage()
    page.evaluate = lambda js: ""

    client = _client_with_page(monkeypatch, page)

    try:
        client.export_flow("4321944")
        raise AssertionError("Expected ClientError for empty export")
    except client_module.ClientError as e:
        assert "empty" in str(e)


# --------------------------------------------------------------------------
# Client import_flow
# --------------------------------------------------------------------------


class _ImportPage:
    """Models the post-import editor page: Save starts disabled, then the
    save-disabled probe reports False, Save navigates to flows.php?node=<id>."""

    def __init__(self, new_id="4406551"):
        self.url = f"https://workflow-automation.podio.com/flows.php?node={new_id}"
        self.waited_selectors = []

    def wait_for_selector(self, selector, timeout=0):
        self.waited_selectors.append(selector)
        return None

    def wait_for_timeout(self, ms):
        return None

    def evaluate(self, js):
        if "saveButton" in js:
            return False  # save button is enabled
        return None


def _import_client(monkeypatch, page):
    client = GlobiflowClient()
    monkeypatch.setattr(client, "ensure_authenticated", lambda path="/": None)

    class _FakeBrowser:
        def get_page(self, url=None):
            return page

    monkeypatch.setattr(GlobiflowClient, "browser", property(lambda self: _FakeBrowser()))
    monkeypatch.setattr(client, "_save_flow", lambda page, timeout=2500: None)
    return client


def test_import_flow_waits_for_save_and_extracts_id(monkeypatch):
    """import_flow must submit the import, wait for the Save control to enable,
    save, and read the new flow id from the redirect URL."""
    page = _ImportPage(new_id="4406551")
    client = _import_client(monkeypatch, page)

    new_id = client.import_flow("30529466", "<root><flow/></root>")

    assert new_id == "4406551"
    assert page.waited_selectors == ["#flowName"]


def test_import_flow_falls_back_to_heading_id(monkeypatch):
    """When the redirect URL has no node= param, import_flow must fall back to
    the flow heading's (ID:<id>) text."""
    page = _ImportPage(new_id="4406551")
    page.url = "https://workflow-automation.podio.com/configureflow.php"

    heading = type(
        "Heading",
        (),
        {
            "count": lambda self: 1,
            "first": property(lambda self: self),
            "text_content": lambda self: "Flow: Imported (ID:4406551)",
        },
    )()

    def _fake_locator(selector):
        if selector == "h4":
            return type(
                "Loc",
                (),
                {"filter": lambda self, has_text=None: heading, "count": lambda self: 1},
            )()
        raise AssertionError(f"unexpected locator: {selector}")

    page.locator = _fake_locator

    client = _import_client(monkeypatch, page)

    assert client.import_flow("30529466", "<root/>") == "4406551"
