import json
import sys

from PIL import Image

from legoscout_cli.pricing import contact_sheet


def test_builds_labeled_contact_sheet_without_imagemagick(tmp_path):
    inputs = []
    for index, color in enumerate(("red", "blue"), start=1):
        path = tmp_path / f"photo-{index}.png"
        Image.new("RGB", (80, 60), color).save(path)
        inputs.append(path)
    output = tmp_path / "auctionzip-contact.png"

    result = contact_sheet.build_contact_sheet(
        inputs,
        output,
        labels=["auctionzip|3523EF776C", "auctionzip|349B383E2A"],
        columns=2,
        tile_size=(100, 80),
    )

    assert output.is_file()
    assert result["labels"] == [
        "auctionzip|3523EF776C", "auctionzip|349B383E2A"]
    with Image.open(output) as sheet:
        assert sheet.size == (200, 122)
        assert sheet.getbbox() is not None


def test_cli_reports_json_and_rejects_label_count_mismatch(
        monkeypatch, capsys, tmp_path):
    image = tmp_path / "photo.png"
    Image.new("RGB", (20, 20), "red").save(image)
    output = tmp_path / "sheet.png"
    monkeypatch.setattr(sys, "argv", [
        "contact_sheet", str(image), "--output", str(output),
        "--label", "one", "--label", "two",
    ])

    assert contact_sheet.main() == 1
    assert capsys.readouterr().err == "Error: --label count must match image count\n"
    assert not output.exists()


def test_cli_default_labels_are_emitted_as_json(monkeypatch, capsys, tmp_path):
    image = tmp_path / "photo.png"
    Image.new("RGB", (20, 20), "red").save(image)
    output = tmp_path / "sheet.png"
    monkeypatch.setattr(sys, "argv", [
        "contact_sheet", str(image), "--output", str(output),
    ])

    assert contact_sheet.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["output"] == str(output.resolve())
    assert payload["labels"] == ["photo.png"]
