from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from google_lighthouse_cli.client import GoogleLighthouseClient
from google_lighthouse_cli.main import app


runner = CliRunner()


def lighthouse_report(url: str) -> dict:
    return {
        "requestedUrl": url,
        "finalDisplayedUrl": url,
        "fetchTime": "2026-05-07T19:00:00.000Z",
        "categories": {
            "performance": {"score": 0.91},
            "accessibility": {"score": 0.98},
            "best-practices": {"score": 0.89},
            "seo": {"score": 1.0},
        },
        "audits": {
            "first-contentful-paint": {"numericValue": 1010.1},
            "largest-contentful-paint": {"numericValue": 1500.2},
            "total-blocking-time": {"numericValue": 12.3},
            "cumulative-layout-shift": {"numericValue": 0.012},
            "speed-index": {"numericValue": 1200.4},
            "interactive": {"numericValue": 1700.5},
        },
    }


def test_run_audit_invokes_lighthouse_and_saves_artifacts(tmp_path, monkeypatch):
    commands: list[list[str]] = []

    def fake_run(command, capture_output, text, timeout):
        commands.append(command)
        output_base = Path(command[command.index("--output-path") + 1])
        output_base.with_suffix(".report.json").write_text(
            json.dumps(lighthouse_report("https://example.com/")),
            encoding="utf-8",
        )
        output_base.with_suffix(".report.html").write_text("<html>report</html>", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("google_lighthouse_cli.client.subprocess.run", fake_run)
    monkeypatch.setattr("google_lighthouse_cli.client.utc_timestamp", lambda: "2026-05-07T19:00:00Z")
    monkeypatch.setattr("google_lighthouse_cli.client.new_audit_id", lambda url: "20260507T190000Z-example-com")

    client = GoogleLighthouseClient(data_dir=tmp_path)
    summary = client.run_audit("https://example.com/", form_factor="desktop", chrome_flags="--headless=new")

    assert summary.id == "20260507T190000Z-example-com"
    assert summary.url == "https://example.com/"
    assert summary.final_url == "https://example.com/"
    assert summary.scores.performance == 91
    assert summary.scores.accessibility == 98
    assert summary.scores.best_practices == 89
    assert summary.scores.seo == 100
    assert summary.metrics.first_contentful_paint_ms == 1010.1
    assert Path(summary.artifacts.json_report).is_file()
    assert Path(summary.artifacts.html_report).is_file()
    assert commands == [
        [
            "npx",
            "--yes",
            "--package",
            "lighthouse@13.2.0",
            "lighthouse",
            "https://example.com/",
            "--quiet",
            "--output=json",
            "--output=html",
            "--output-path",
            str(tmp_path / "20260507T190000Z-example-com" / "20260507T190000Z-example-com"),
            "--chrome-flags=--headless=new",
            "--form-factor=desktop",
            "--screenEmulation.disabled",
        ]
    ]


def test_list_audits_supports_filter_limit_and_properties(tmp_path):
    audit_dir = tmp_path / "20260507T190000Z-example-com"
    audit_dir.mkdir()
    (audit_dir / "summary.json").write_text(
        json.dumps(
            {
                "id": "20260507T190000Z-example-com",
                "url": "https://example.com/",
                "final_url": "https://example.com/",
                "created_at": "2026-05-07T19:00:00Z",
                "form_factor": "desktop",
                "scores": {
                    "performance": 91,
                    "accessibility": 98,
                    "best_practices": 89,
                    "seo": 100,
                },
                "metrics": {
                    "first_contentful_paint_ms": 1010.1,
                    "largest_contentful_paint_ms": 1500.2,
                    "total_blocking_time_ms": 12.3,
                    "cumulative_layout_shift": 0.012,
                    "speed_index_ms": 1200.4,
                    "time_to_interactive_ms": 1700.5,
                },
                "artifacts": {
                    "json": str(audit_dir / "20260507T190000Z-example-com.report.json"),
                    "html": str(audit_dir / "20260507T190000Z-example-com.report.html"),
                },
            }
        ),
        encoding="utf-8",
    )

    client = GoogleLighthouseClient(data_dir=tmp_path)
    audits = client.list_audits(
        limit=1,
        filters=["url:eq:https://example.com/"],
    )

    assert len(audits) == 1
    assert audits[0].id == "20260507T190000Z-example-com"
    assert audits[0].scores.performance == 91


def test_cli_list_supports_properties(tmp_path, monkeypatch):
    audit_dir = tmp_path / "20260507T190000Z-example-com"
    audit_dir.mkdir()
    (audit_dir / "summary.json").write_text(
        json.dumps(
            {
                "id": "20260507T190000Z-example-com",
                "url": "https://example.com/",
                "final_url": "https://example.com/",
                "created_at": "2026-05-07T19:00:00Z",
                "form_factor": "desktop",
                "scores": {
                    "performance": 91,
                    "accessibility": 98,
                    "best_practices": 89,
                    "seo": 100,
                },
                "metrics": {
                    "first_contentful_paint_ms": 1010.1,
                    "largest_contentful_paint_ms": 1500.2,
                    "total_blocking_time_ms": 12.3,
                    "cumulative_layout_shift": 0.012,
                    "speed_index_ms": 1200.4,
                    "time_to_interactive_ms": 1700.5,
                },
                "artifacts": {
                    "json": str(audit_dir / "20260507T190000Z-example-com.report.json"),
                    "html": str(audit_dir / "20260507T190000Z-example-com.report.html"),
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_LIGHTHOUSE_DATA_DIR", str(tmp_path))

    result = runner.invoke(app, ["audits", "list", "--properties", "id,scores.performance"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"id": "20260507T190000Z-example-com", "scores.performance": 91}]
    assert result.stderr == ""


def test_cli_run_outputs_summary_json(tmp_path, monkeypatch):
    def fake_run_audit(self, url, form_factor, chrome_flags, timeout_seconds):
        return {
            "id": "20260507T190000Z-example-com",
            "url": url,
            "final_url": url,
            "created_at": "2026-05-07T19:00:00Z",
            "form_factor": form_factor,
            "scores": {
                "performance": 91,
                "accessibility": 98,
                "best_practices": 89,
                "seo": 100,
            },
            "metrics": {
                "first_contentful_paint_ms": 1010.1,
                "largest_contentful_paint_ms": 1500.2,
                "total_blocking_time_ms": 12.3,
                "cumulative_layout_shift": 0.012,
                "speed_index_ms": 1200.4,
                "time_to_interactive_ms": 1700.5,
            },
            "artifacts": {
                "json": str(tmp_path / "report.json"),
                "html": str(tmp_path / "report.html"),
            },
        }

    monkeypatch.setattr("google_lighthouse_cli.commands.audits.GoogleLighthouseClient.run_audit", fake_run_audit)

    result = runner.invoke(app, ["audits", "run", "https://example.com/", "--form-factor", "desktop"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["scores"]["performance"] == 91
    assert result.stderr == ""


def test_get_audit_returns_saved_summary(tmp_path):
    audit_dir = tmp_path / "20260507T190000Z-example-com"
    audit_dir.mkdir()
    (audit_dir / "summary.json").write_text(
        json.dumps(
            {
                "id": "20260507T190000Z-example-com",
                "url": "https://example.com/",
                "final_url": "https://example.com/",
                "created_at": "2026-05-07T19:00:00Z",
                "form_factor": "desktop",
                "scores": {
                    "performance": 91,
                    "accessibility": 98,
                    "best_practices": 89,
                    "seo": 100,
                },
                "metrics": {
                    "first_contentful_paint_ms": 1010.1,
                    "largest_contentful_paint_ms": 1500.2,
                    "total_blocking_time_ms": 12.3,
                    "cumulative_layout_shift": 0.012,
                    "speed_index_ms": 1200.4,
                    "time_to_interactive_ms": 1700.5,
                },
                "artifacts": {
                    "json": str(audit_dir / "20260507T190000Z-example-com.report.json"),
                    "html": str(audit_dir / "20260507T190000Z-example-com.report.html"),
                },
            }
        ),
        encoding="utf-8",
    )

    client = GoogleLighthouseClient(data_dir=tmp_path)
    detail = client.get_audit("20260507T190000Z-example-com")

    assert detail.id == "20260507T190000Z-example-com"
    assert detail.scores.performance == 91
