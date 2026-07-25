"""Regression coverage for the public CLI installer entry point."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
PUBLIC_WRAPPER = REPO_ROOT / "_repo/scripts/install-cli-tool.sh"


def test_public_installer_delegates_to_canonical_installer(tmp_path):
    public_dir = tmp_path / "_repo/scripts"
    canonical_dir = tmp_path / "_repo/skills/cli-tool/scripts"
    public_dir.mkdir(parents=True)
    canonical_dir.mkdir(parents=True)

    wrapper = public_dir / "install-cli-tool.sh"
    shutil.copy2(PUBLIC_WRAPPER, wrapper)

    canonical = canonical_dir / "install-cli-tool.sh"
    canonical.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'ARGS:%s\\n' \"$*\"\n"
        "printf '%s\\n' 'CANONICAL_STDERR' >&2\n"
        "exit 17\n"
    )
    canonical.chmod(0o755)

    result = subprocess.run(
        [str(wrapper), "--force-refresh", "pluralsight-author"],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 17
    assert result.stdout == "ARGS:--force-refresh pluralsight-author\n"
    assert result.stderr == "CANONICAL_STDERR\n"
