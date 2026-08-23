from types import SimpleNamespace

from gemini_cli.commands import research


class _Interactions:
    def __init__(self) -> None:
        self._polls = iter(
            [
                SimpleNamespace(status="in_progress", output_text=None),
                SimpleNamespace(status="completed", output_text="# Final research\n\nCited result."),
            ]
        )

    def create(self, **_kwargs):
        return SimpleNamespace(id="interaction-123")

    def get(self, _interaction_id: str):
        return next(self._polls)


def test_non_stream_progress_uses_stderr_and_final_report_uses_stdout(
    capsys, monkeypatch
) -> None:
    client = SimpleNamespace(client=SimpleNamespace(interactions=_Interactions()))
    monkeypatch.setattr(research.time, "sleep", lambda _seconds: None)

    research._run_polling_research(
        client,
        prompt="Research topic",
        agent=research.DEFAULT_AGENT,
        timeout=60,
    )

    captured = capsys.readouterr()
    assert captured.out.strip() == "# Final research\n\nCited result."
    assert "Status: in_progress" not in captured.out
    assert "Status: in_progress" in captured.err
    assert "Research complete!" in captured.err
