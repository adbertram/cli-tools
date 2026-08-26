"""An incomplete eBay detail pass cannot report source success."""
from __future__ import annotations

import json
import sys

from legoscout_cli.sources import triage


def test_detail_failure_marks_artifact_blocked(monkeypatch, tmp_path):
    items = [{"item_id": "1"}, {"item_id": "2"}]

    def fake_record(item, _detail):
        if item["item_id"] == "2":
            raise RuntimeError("detail payload is empty")
        return {"listing_key": "ebay|1"}

    monkeypatch.setattr(triage, "_detail", lambda item_id: {"item_id": item_id})
    monkeypatch.setattr(triage, "_record", fake_record)

    artifact, report, failures = triage.fetch_details(
        items, out_dir=str(tmp_path), jobs=2)

    assert failures == [{"item_id": "2", "why": "RuntimeError: detail payload is empty"}]
    assert report["checked"] is False
    assert report["blocked"] is True
    assert report["blocker"] == "1 of 2 kept candidates failed detail fetch"
    assert json.loads(open(artifact, encoding="utf-8").read()) == report


def test_main_exits_nonzero_when_any_detail_fails(monkeypatch, capsys, tmp_path):
    candidate_file = tmp_path / "candidates.json"
    candidate_file.write_text("[]", encoding="utf-8")
    report = {"candidates": [{"item_id": "1"}]}
    failures = [{"item_id": "1", "why": "empty output"}]
    monkeypatch.setattr(triage, "triage", lambda *_args: report)
    monkeypatch.setattr(
        triage, "fetch_details",
        lambda *_args, **_kwargs: (str(tmp_path / "ebay.json"), {}, failures))
    monkeypatch.setattr(sys, "argv", [
        "triage", str(candidate_file), "--fetch-details", "--out", str(tmp_path)])

    assert triage.main() == 1
    assert json.loads(capsys.readouterr().out)["detail_failures"] == failures
