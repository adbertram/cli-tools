import json
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from elevenlabs_cli.main import app
from test_pronunciation_dictionaries import FakeResponse, configure_test_config


runner = CliRunner()


@pytest.fixture
def requests_log(monkeypatch):
    configure_test_config(monkeypatch)
    log = []

    def fake_request(method, url, **kwargs):
        log.append({"method": method, "url": url, **kwargs})
        return FakeResponse(content=b"not-really-audio")

    monkeypatch.setattr("requests.request", fake_request)
    # Non-mp3 format bypasses ffprobe so fake bytes are accepted.
    return log


def test_sound_effects_create_request_and_result(requests_log, tmp_path):
    out = tmp_path / "sfx.pcm"
    result = runner.invoke(
        app,
        ["sound-effects", "create", "glass", "--output", str(out), "--duration", "2",
         "--prompt-influence", "0.5", "--loop", "--model", "eleven_text_to_sound_v2",
         "--output-format", "pcm_44100"],
    )
    assert result.exit_code == 0, result.output
    call = requests_log[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/v1/sound-generation")
    assert call["params"] == {"output_format": "pcm_44100"}
    assert call["json"] == {
        "text": "glass", "duration_seconds": 2.0, "prompt_influence": 0.5,
        "loop": True, "model_id": "eleven_text_to_sound_v2",
    }
    assert call["headers"]["xi-api-key"] == "test-key"
    assert out.read_bytes() == b"not-really-audio"
    data = json.loads(result.stdout)
    assert data["output"] == str(out)
    assert data["bytes"] == len(b"not-really-audio")
    assert data["format"] == "pcm_44100"
    assert data["text"] == "glass"


def test_sound_effects_defaults_send_only_text(requests_log, tmp_path):
    out = tmp_path / "sfx.pcm"
    result = runner.invoke(app, ["sound-effects", "create", "x", "--output", str(out), "--output-format", "pcm_44100"])
    assert result.exit_code == 0, result.output
    assert requests_log[0]["json"] == {"text": "x"}


def test_music_compose_request_and_result(requests_log, tmp_path):
    out = tmp_path / "m.pcm"
    result = runner.invoke(
        app,
        ["music", "compose", "calm", "--seconds", "10", "--model", "music_v2", "--instrumental",
         "--seed", "7", "--output-format", "pcm_44100", "--output", str(out)],
    )
    assert result.exit_code == 0, result.output
    call = requests_log[0]
    assert call["url"].endswith("/v1/music")
    assert call["params"] == {"output_format": "pcm_44100"}
    assert call["json"] == {
        "prompt": "calm", "music_length_ms": 10000, "model_id": "music_v2",
        "force_instrumental": True, "seed": 7,
    }
    assert json.loads(result.stdout)["music_length_ms"] == 10000


@pytest.mark.parametrize("seconds", ["2.9", "601"])
def test_music_seconds_out_of_range_rejected(requests_log, tmp_path, seconds):
    result = runner.invoke(app, ["music", "compose", "x", "--seconds", seconds, "--output", str(tmp_path / "m.mp3")])
    assert result.exit_code != 0
    assert requests_log == []


def test_sound_effects_duration_out_of_range_rejected(requests_log, tmp_path):
    result = runner.invoke(app, ["sound-effects", "create", "x", "--duration", "31", "--output", str(tmp_path / "s.mp3")])
    assert result.exit_code != 0
    assert requests_log == []


@pytest.mark.parametrize(
    "args",
    [["sound-effects", "create", "x"], ["music", "compose", "x", "--seconds", "5"]],
)
def test_refuses_overwrite_without_force(requests_log, tmp_path, args):
    out = tmp_path / "exists.pcm"
    out.write_bytes(b"old")
    base = args + ["--output", str(out), "--output-format", "pcm_44100"]
    result = runner.invoke(app, base)
    assert result.exit_code != 0
    assert "--force" in result.output
    assert out.read_bytes() == b"old"
    assert requests_log == []
    forced = runner.invoke(app, base + ["--force"])
    assert forced.exit_code == 0, forced.output
    assert out.read_bytes() == b"not-really-audio"


def test_empty_audio_rejected(monkeypatch, tmp_path):
    configure_test_config(monkeypatch)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: FakeResponse(content=b""))
    out = tmp_path / "e.mp3"
    result = runner.invoke(app, ["sound-effects", "create", "x", "--output", str(out)])
    assert result.exit_code != 0
    assert "empty" in result.output
    assert not out.exists()


def test_mp3_that_does_not_decode_rejected(requests_log, tmp_path):
    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe not installed")
    out = tmp_path / "bad.mp3"
    result = runner.invoke(app, ["sound-effects", "create", "x", "--output", str(out)])
    assert result.exit_code != 0
    assert "ffprobe" in result.output
    assert not out.exists()


def test_valid_mp3_reports_duration(monkeypatch, tmp_path):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    src = tmp_path / "src.mp3"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", "-b:a", "64k", str(src)], check=True
    )
    configure_test_config(monkeypatch)
    monkeypatch.setattr("requests.request", lambda method, url, **kwargs: FakeResponse(content=src.read_bytes()))
    out = tmp_path / "ok.mp3"
    result = runner.invoke(app, ["music", "compose", "x", "--seconds", "3", "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert 0.9 < json.loads(result.stdout)["probed_duration_seconds"] < 1.3
