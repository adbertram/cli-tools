"""Narrow repair of installed n8n maintenance paths; also executed on the server."""
import ast
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


NAMES = {"N8N_BIN", "N8N_INSTALL_PREFIX"}
OLD_PREFIX = "/usr/local"


def assignments(source):
    tree = ast.parse(source)
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in NAMES for t in node.targets):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name) or node.targets[0].id in found:
                raise ValueError("Unexpected or duplicate maintenance assignment")
            found[node.targets[0].id] = node
    if set(found) != NAMES:
        raise ValueError("Missing maintenance assignment")
    return found


def replacement(source, prefix):
    nodes = assignments(source)
    lines = source.splitlines(keepends=True)
    for name, node in nodes.items():
        if node.lineno != node.end_lineno or node.col_offset != 0:
            raise ValueError("Unexpected maintenance assignment layout")
        value = node.value
        valid = isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value in (
            OLD_PREFIX if name == "N8N_INSTALL_PREFIX" else OLD_PREFIX + "/lib/node_modules/n8n/bin/n8n",
            prefix if name == "N8N_INSTALL_PREFIX" else prefix + "/lib/node_modules/n8n/bin/n8n",
        )
        if name == "N8N_BIN" and isinstance(value, ast.JoinedStr):
            valid = ast.dump(value, include_attributes=False) == ast.dump(ast.parse('f"{N8N_INSTALL_PREFIX}/lib/node_modules/n8n/bin/n8n"', mode="eval").body, include_attributes=False)
        if not valid:
            raise ValueError("Unexpected maintenance assignment value")
        line = lines[node.lineno - 1]
        lines[node.lineno - 1] = line[:value.col_offset] + repr(prefix if name == "N8N_INSTALL_PREFIX" else prefix + "/lib/node_modules/n8n/bin/n8n") + line[value.end_col_offset:]
    result = "".join(lines)
    compile(result, "maintenance", "exec")
    return result


def sync(paths, prefix, verify=None):
    originals = {}
    for path in paths:
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.resolve() != path or path.stat().st_uid != os.getuid():
            raise ValueError(f"Invalid target or ownership: {path}")
        original = path.read_bytes()
        updated = replacement(original.decode("utf-8"), prefix).encode("utf-8")
        originals[path] = (original, updated, stat.S_IMODE(path.stat().st_mode))
    backups = []
    changed = []
    try:
        for path, (original, updated, mode) in originals.items():
            if original == updated:
                continue
            fd, backup = tempfile.mkstemp(prefix=path.name + ".prefix-backup-", dir=path.parent)
            with os.fdopen(fd, "wb") as handle:
                handle.write(original)
            os.chmod(backup, mode)
            backups.append(backup)
            changed.append(path)
            path.write_bytes(updated)
        for path, (_, updated, _) in originals.items():
            if path.read_bytes() != updated or replacement(path.read_text(), prefix).encode() != updated:
                raise ValueError(f"Verification failed: {path}")
        if verify:
            verify()
    except Exception:
        for path in changed:
            path.write_bytes(originals[path][0])
        raise
    return {"changed": [str(p) for p in changed], "backups": backups}


def main(prefix):
    home = Path.home()
    cli_python = home / ".local/share/uv/tools/n8n-cli/bin/python"
    manager_root = home / ".n8n/nodes/node_modules/n8n-nodes-n8n-manager/cli"
    expected = Path("/opt/cli-tools/n8n/n8n_cli/commands/server.py")
    manager = manager_root / "n8n_cli/commands/server.py"
    manager_python = manager_root / ".venv/bin/python"
    import json

    def inspect(python, cwd):
        code = "import json, n8n_cli.commands.server as s; print(json.dumps([s.__file__,s.N8N_INSTALL_PREFIX,s.N8N_BIN]))"
        result = subprocess.run([str(python), "-c", code], cwd=cwd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def verify():
        for python, cwd, target in ((cli_python, "/", expected), (manager_python, manager_root, manager)):
            if inspect(python, cwd) != [str(target), prefix, prefix + "/lib/node_modules/n8n/bin/n8n"]:
                raise ValueError(f"Installed import verification failed: {target}")

    if inspect(cli_python, "/")[0] != str(expected) or inspect(manager_python, manager_root)[0] != str(manager):
        raise ValueError("Unexpected installed maintenance module path")
    print(json.dumps(sync([expected, manager], prefix, verify)))


if __name__ == "__main__":
    main(sys.argv[1])
