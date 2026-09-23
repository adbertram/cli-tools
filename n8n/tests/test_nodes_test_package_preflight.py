"""Behavior tests for `n8n nodes test` package preflight.

The report this file pins: a package whose node ships `.node.json` codex metadata
and a `testedBy` credential-test binding is rejected before execution, with
"Found .node.json codex file(s) ... Remove these files" and "Node credentials
contain 'testedBy' field". Both are supported parts of an n8n node package --
`n8n-nodes-base` itself ships 429 `.node.json` files and 42 nodes binding
`testedBy` to a `methods.credentialTest` method -- so neither may block a test.

What is genuinely broken is a binding that cannot RESOLVE: n8n reads a string
`testedBy` out of the node's own `methods.credentialTest` map
(`CredentialsTester.getCredentialTestFunction`), so a binding naming a method the
package never defines fails credential testing with "No testing function found
for this credential." Only that case is reported.

No server contact: the API is a fake, and the SSH boundary answers from a real
fixture of the installed package's files.
"""

import fnmatch
import posixpath
import re
import subprocess

from typer.testing import CliRunner

import n8n_cli.commands.test as test_module
from n8n_cli.commands import nodes as nodes_module


NODE_TYPE = "n8n-nodes-issue-manager-github-app.issueManagerGithubApp"
PACKAGE = "n8n-nodes-issue-manager-github-app"
CRED_TYPE = "issueManagerGithubAppApi"
CRED_ID = "PWAVb31Kd2LS9GLJ"
CREDENTIALS = '{"%s":{"id":"%s","name":"Issue Manager GitHub App"}}' % (CRED_TYPE, CRED_ID)
BINDING = "issueManagerGithubAppApiCredentialTest"

PACKAGE_DIR = f"/home/adam/.n8n/nodes/node_modules/{PACKAGE}"
NODE_DIR = f"{PACKAGE_DIR}/dist/nodes/IssueManagerGithubApp"
CODEX_PATH = f"{NODE_DIR}/IssueManagerGithubApp.node.json"

# Verbatim shape of the codex metadata the installed package ships.
CODEX_JSON = """{
    "node": "n8n-nodes-issue-manager-github-app.issueManagerGithubApp",
    "nodeVersion": "1.0",
    "codexVersion": "1.0",
    "categories": ["Developer Tools"],
    "resources": {
        "primaryDocumentation": [{"url": "https://docs.github.com/en/apps"}]
    }
}
"""


def _node_js(credentials_entry, methods_entry):
    """Compiled node module shaped like tsc output from a generated package."""
    return f"""\"use strict\";
Object.defineProperty(exports, \"__esModule\", {{ value: true }});
class IssueManagerGithubApp {{
    constructor() {{
        this.description = {{
            displayName: 'Issue Manager GitHub App',
            name: 'issueManagerGithubApp',
            group: ['transform'],
            version: 1,
            defaults: {{ name: 'Issue Manager GitHub App' }},
            inputs: ['main'],
            outputs: ['main'],
            credentials: [
                {{
                    name: '{CRED_TYPE}',
                    required: true,
                    {credentials_entry}
                }},
            ],
            properties: [
                {{
                    displayName: 'Resource',
                    name: 'resource',
                    type: 'options',
                    noDataExpression: true,
                    default: 'pullRequest',
                    options: [{{ name: 'Pull Request', value: 'pullRequest' }}],
                }},
            ],
        }};
        this.methods = {{
            credentialTest: {{
                {methods_entry}
            }},
        }};
    }}
    async execute() {{
        return this.helpers.returnJsonArray([]);
    }}
}}
exports.IssueManagerGithubApp = IssueManagerGithubApp;
"""


# The binding the report's package declares, with the method that satisfies it.
RESOLVED_METHOD = f"""async {BINDING}(credential) {{
                    return {{ status: 'OK', message: 'Connection successful!' }};
                }},"""

# The same binding with the method renamed: nothing in the package defines it.
DANGLING_METHOD = """async issueManagerGithubAppApiConnectionTest(credential) {
                    return { status: 'OK', message: 'Connection successful!' };
                },"""

# An imported credential test, the shape n8n-nodes-base uses: the definition is
# the map key, not a method body in this file.
IMPORTED_METHOD = "postgresConnectionTest: credentialTest_1.postgresConnectionTest,"


def _package(node_js, *, codex=True):
    files = {
        f"{NODE_DIR}/IssueManagerGithubApp.node.js": node_js,
        f"{PACKAGE_DIR}/dist/credentials/{CRED_TYPE}.credentials.js": (
            "class IssueManagerGithubAppApi {\n"
            "    constructor() {\n"
            "        this.name = 'issueManagerGithubAppApi';\n"
            "    }\n"
            "}\n"
            "exports.IssueManagerGithubAppApi = IssueManagerGithubAppApi;\n"
        ),
    }
    if codex:
        files[CODEX_PATH] = CODEX_JSON
    return files


def resolved_package():
    """The report's package: codex metadata plus a binding that resolves."""
    return _package(_node_js(f"testedBy: '{BINDING}',", RESOLVED_METHOD))


def _posix_ere(pattern):
    """Translate the POSIX class the CLI's grep pattern uses into Python's.

    The scan runs `grep -E '<pattern>'` on the server, so the fake has to read a
    POSIX ERE; `[[:space:]]` means whitespace there and a literal character set
    here, which would silently match nothing.
    """
    return pattern.replace("[[:space:]]", r"\s")


class FakeInstalledPackage:
    """The package tree on the n8n server, searched by the CLI's own commands.

    Every shell command the CLI issues (`sudo find`, `sudo grep`) is answered
    from the fixture files themselves, so the fixture models a real package
    rather than one command's idea of it.
    """

    def __init__(self, files):
        self.files = files
        self.commands = []

    def __call__(self, command, timeout=120):
        self.commands.append(command)
        if " -name " in command:
            glob = re.search(r'-name\s+"([^"]+)"', command).group(1)
            hits = [
                path for path in self.files
                if fnmatch.fnmatch(posixpath.basename(path), glob)
            ]
            return self._result(command, sorted(hits))
        files = self.files
        includes = re.search(r"--include='([^']+)'", command)
        if includes:
            files = {
                path: text for path, text in files.items()
                if fnmatch.fnmatch(posixpath.basename(path), includes.group(1))
            }
        # The pattern is the last quoted argument (`--include='*.js'` comes first,
        # and the pre-fix CLI's `grep -r "testedBy"` quotes only its pattern).
        quoted = re.findall(r"""['"]([^'"]*)['"]""", command)
        pattern = quoted[-1] if quoted else None
        assert pattern, f"unrecognised server command: {command}"
        matcher = re.compile(_posix_ere(pattern))
        hits = [
            line
            for text in files.values()
            for line in text.splitlines()
            if matcher.search(line)
        ]
        return self._result(command, hits)

    @staticmethod
    def _result(command, lines):
        stdout = "\n".join(lines) + ("\n" if lines else "")
        return subprocess.CompletedProcess(
            args=command, returncode=0 if lines else 1, stdout=stdout, stderr="",
        )


class FakeTestApi:
    """Records the temp workflow `nodes test` builds; talks to nothing."""

    def __init__(self):
        self.created_workflows = []
        self.activated = []
        self.deleted = []

    def resolve_node_type(self, node_name):
        return NODE_TYPE

    def create_workflow(self, name, nodes, connections):
        workflow = {
            "id": f"wf-{len(self.created_workflows) + 1}",
            "name": name,
            "nodes": nodes,
            "connections": connections,
            "active": False,
        }
        self.created_workflows.append(workflow)
        return workflow

    def activate_workflow(self, workflow_id):
        self.activated.append(workflow_id)
        return {}

    def deactivate_workflow(self, workflow_id):
        return {}

    def delete_workflow(self, workflow_id):
        self.deleted.append(workflow_id)
        return {}

    def trigger_webhook(self, webhook_path, data=None):
        return {}

    def get_executions(self, **kwargs):
        return [{"id": 23208, "status": "success", "finished": True}]

    def get_node_type(self, node_type):
        if node_type != NODE_TYPE:
            return None
        return {
            "name": NODE_TYPE,
            "displayName": "Issue Manager GitHub App",
            "version": 1,
            "defaultVersion": 1,
            "credentials": [{"name": CRED_TYPE}],
            "properties": [
                {
                    "name": "resource",
                    "displayName": "Resource",
                    "type": "options",
                    "required": True,
                    "default": "pullRequest",
                    "options": [{"name": "Pull Request", "value": "pullRequest"}],
                },
            ],
        }

    def list_credentials(self):
        return [{"id": CRED_ID, "name": "Issue Manager GitHub App", "type": CRED_TYPE}]


def _invoke_nodes_test(monkeypatch, api, server):
    """Drive the real `n8n nodes test` boundary against a fixture package."""
    monkeypatch.setattr(test_module, "get_n8n_api_client", lambda: api)
    monkeypatch.setattr(test_module, "run_on_server_raw", server)
    monkeypatch.setattr(test_module.time, "sleep", lambda seconds: None)
    return CliRunner().invoke(
        nodes_module.app,
        [
            "test",
            "issue-manager-github-app",
            "--resource", "pullRequest",
            "--credentials", CREDENTIALS,
            "--node-type", NODE_TYPE,
            "--timeout", "60",
        ],
    )


def test_should_proceed_when_the_package_ships_codex_metadata_and_a_credential_test_binding(monkeypatch):
    """The report's package: `.node.json` codex metadata + a resolvable testedBy."""
    api = FakeTestApi()
    server = FakeInstalledPackage(resolved_package())

    result = _invoke_nodes_test(monkeypatch, api, server)

    assert result.exit_code == 0, result.output
    assert api.activated == ["wf-1"], "the node must reach activation and execution"
    assert "codex" not in result.output
    assert "testedBy" not in result.output
    assert "prevent it from appearing in the n8n UI" not in result.output


def test_should_proceed_when_the_package_ships_codex_metadata_only(monkeypatch):
    """Codex metadata alone is never a defect."""
    api = FakeTestApi()
    server = FakeInstalledPackage(
        _package(_node_js("// no credential test declared", "// no tests"))
    )

    result = _invoke_nodes_test(monkeypatch, api, server)

    assert result.exit_code == 0, result.output
    assert api.activated == ["wf-1"]


def test_should_proceed_when_tested_by_is_an_inline_credential_test_request(monkeypatch):
    """`testedBy` also accepts an ICredentialTestRequest object."""
    api = FakeTestApi()
    node_js = _node_js(
        "testedBy: {\n"
        "                        request: { baseURL: '={{$credentials.baseUrl}}', url: '/user' },\n"
        "                    },",
        "// no methods needed for an inline request",
    )
    server = FakeInstalledPackage(_package(node_js))

    result = _invoke_nodes_test(monkeypatch, api, server)

    assert result.exit_code == 0, result.output
    assert api.activated == ["wf-1"]


def test_should_proceed_when_the_credential_test_method_is_imported(monkeypatch):
    """The definition is a map key when the method comes from a sibling module."""
    api = FakeTestApi()
    node_js = _node_js("testedBy: 'postgresConnectionTest',", IMPORTED_METHOD)
    server = FakeInstalledPackage(_package(node_js))

    result = _invoke_nodes_test(monkeypatch, api, server)

    assert result.exit_code == 0, result.output
    assert api.activated == ["wf-1"]


def test_should_proceed_when_the_method_is_declared_in_a_methods_module(monkeypatch):
    """n8n-nodes-base's Oracle/MySQL shape: `async function NAME(...)` plus
    `exports.NAME = NAME:` in the sibling `methods/credentialTest.js`."""
    api = FakeTestApi()
    files = _package(_node_js("testedBy: 'oracleDBConnectionTest',", "// spread from methods/"))
    files[f"{NODE_DIR}/methods/credentialTest.js"] = (
        '"use strict";\n'
        'Object.defineProperty(exports, "__esModule", { value: true });\n'
        "exports.oracleDBConnectionTest = oracleDBConnectionTest;\n"
        "async function oracleDBConnectionTest(credential) {\n"
        "    return { status: 'OK', message: 'Connection successful!' };\n"
        "}\n"
    )
    server = FakeInstalledPackage(files)

    result = _invoke_nodes_test(monkeypatch, api, server)

    assert result.exit_code == 0, result.output
    assert api.activated == ["wf-1"]


def test_should_warn_but_still_test_when_a_binding_names_a_missing_method(monkeypatch):
    """The one genuinely dangling case: the named method exists nowhere.

    `@n8n/n8n-nodes-langchain` ships exactly this (`Agent/V1/AgentV1.node.js`
    declares `testedBy: 'mysqlConnectionTest'` with no such method anywhere in the
    package), and its node still executes — so a dangling binding is reported and
    the test run continues.
    """
    api = FakeTestApi()
    server = FakeInstalledPackage(_package(_node_js(f"testedBy: '{BINDING}',", DANGLING_METHOD)))

    result = _invoke_nodes_test(monkeypatch, api, server)

    assert result.exit_code == 0, result.output
    assert api.activated == ["wf-1"], "a dangling binding must not block the node test"
    assert BINDING in result.output
    assert PACKAGE in result.output
    assert "methods.credentialTest" in result.output
    assert result.output.count("testedBy: ") == 1, "only the dangling binding is reported"


def test_should_proceed_when_the_server_scan_times_out(monkeypatch):
    """An unreachable scan is not evidence of a defective package."""
    api = FakeTestApi()

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ssh", timeout=30)

    result = _invoke_nodes_test(monkeypatch, api, timeout)

    assert result.exit_code == 0, result.output
    assert api.activated == ["wf-1"]
    assert "Skipping credential-test binding check" in result.output


def test_scan_separates_declared_bindings_from_defined_methods(monkeypatch):
    """The scan reads the compiled shapes n8n itself ships."""
    server = FakeInstalledPackage(resolved_package())
    monkeypatch.setattr(test_module, "run_on_server_raw", server)

    bindings, defined = test_module._scan_installed_package(PACKAGE)

    assert bindings == {BINDING}
    assert defined == {BINDING}
    assert not any(command.startswith("sudo find") for command in server.commands), (
        "codex metadata is supported, so the package scan must not look for it"
    )


def test_scan_stops_after_the_binding_grep_when_a_package_declares_none(monkeypatch):
    """No binding means nothing to resolve, and no second round trip."""
    server = FakeInstalledPackage(
        _package(_node_js("// no credential test declared", "// no tests"))
    )
    monkeypatch.setattr(test_module, "run_on_server_raw", server)

    assert test_module._scan_installed_package(PACKAGE) == (set(), set())
    assert len(server.commands) == 1


def test_dangling_binding_message_names_the_binding(monkeypatch):
    """The message must name both the binding and the package it cannot resolve in."""
    server = FakeInstalledPackage(_package(_node_js(f"testedBy: '{BINDING}',", DANGLING_METHOD)))
    monkeypatch.setattr(test_module, "run_on_server_raw", server)

    issues = test_module._check_credential_test_bindings(PACKAGE)

    assert len(issues) == 1
    assert f"testedBy: {BINDING}" in issues[0]
    assert PACKAGE in issues[0]


def test_binding_value_that_is_not_an_identifier_is_reported_without_reaching_the_shell(monkeypatch):
    """A `testedBy` value that cannot name a method is a dangling binding, and it
    is never interpolated into the sudo grep pattern."""
    api = FakeTestApi()
    value = "issue-manager-github-app-credential-test"
    server = FakeInstalledPackage(_package(_node_js(f"testedBy: '{value}',", RESOLVED_METHOD)))

    result = _invoke_nodes_test(monkeypatch, api, server)

    assert result.exit_code == 0, result.output
    assert api.activated == ["wf-1"]
    assert f"testedBy: {value}" in result.output
    assert all(value not in command for command in server.commands)
