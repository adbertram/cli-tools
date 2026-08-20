"""Project model for DeepSeek Harness sessions."""
from typing import Optional

from .base import CLIModel


class Project(CLIModel):
    """A dsh project: one working directory with session logs.

    dsh groups sessions into `<sessions root>/<projectKey(cwd)>/`. That key
    replaces `/`, `\\`, and `:` with `-`, which is intentionally lossy, so the
    real path is read from each session log's header `cwd` field rather than
    decoded from the directory name.
    """

    name: str
    full_path: str
    encoded_path: str
    session_count: int
    subagent_session_count: int = 0
    last_activity: Optional[str] = None
