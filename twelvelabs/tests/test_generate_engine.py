from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from twelvelabs_cli.client import ClientError, TwelveLabsClient
from twelvelabs_cli.commands import generate
from twelvelabs_cli.commands import indexes


class FakeVideos:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def retrieve(self, *, index_id, video_id):
        self.calls.append({"index_id": index_id, "video_id": video_id})
        return self.response


class FakeVideoResponse:
    def __init__(self, asset_id):
        self.asset_id = asset_id

    def model_dump(self):
        return {"asset_id": self.asset_id}


class FakeSdk:
    def __init__(self, video_response=None):
        self.analyze_calls = []
        self.indexes = SimpleNamespace(videos=FakeVideos(video_response))

    def analyze(self, **kwargs):
        self.analyze_calls.append(kwargs)
        return SimpleNamespace(data="generated text")


def make_client(fake_sdk):
    client = object.__new__(TwelveLabsClient)
    client.client = fake_sdk
    return client


def test_generate_text_should_use_video_id_for_pegasus_1_2():
    fake_sdk = FakeSdk()
    client = make_client(fake_sdk)

    result = client.generate_text(
        video_id="video-123",
        prompt="Describe this video",
        temperature=0.0,
        engine="pegasus1.2",
    )

    assert result == "generated text"
    assert fake_sdk.analyze_calls == [
        {
            "model_name": "pegasus1.2",
            "video_id": "video-123",
            "prompt": "Describe this video",
            "temperature": 0.0,
        }
    ]


def test_generate_text_should_use_asset_id_for_pegasus_1_5():
    fake_sdk = FakeSdk(video_response=FakeVideoResponse(asset_id="asset-123"))
    client = make_client(fake_sdk)

    result = client.generate_text(
        video_id="video-123",
        prompt="Describe this video",
        temperature=0.0,
        engine="pegasus1.5",
        index_id="index-123",
    )

    assert result == "generated text"
    assert fake_sdk.indexes.videos.calls == [
        {"index_id": "index-123", "video_id": "video-123"}
    ]
    assert len(fake_sdk.analyze_calls) == 1
    call = fake_sdk.analyze_calls[0]
    assert call["model_name"] == "pegasus1.5"
    assert call["video"].asset_id == "asset-123"
    assert call["prompt"] == "Describe this video"
    assert call["temperature"] == 0.0
    assert "video_id" not in call


def test_generate_text_should_default_to_pegasus_1_5():
    fake_sdk = FakeSdk(video_response=FakeVideoResponse(asset_id="asset-123"))
    client = make_client(fake_sdk)

    result = client.generate_text(
        video_id="video-123",
        prompt="Describe this video",
        temperature=0.0,
        index_id="index-123",
    )

    assert result == "generated text"
    assert fake_sdk.indexes.videos.calls == [
        {"index_id": "index-123", "video_id": "video-123"}
    ]
    call = fake_sdk.analyze_calls[0]
    assert call["model_name"] == "pegasus1.5"
    assert call["video"].asset_id == "asset-123"
    assert "video_id" not in call


def test_generate_text_should_require_index_id_for_pegasus_1_5():
    client = make_client(FakeSdk())

    with pytest.raises(ClientError, match="Pegasus 1.5 requires index_id"):
        client.generate_text(
            video_id="video-123",
            prompt="Describe this video",
            engine="pegasus1.5",
        )


def test_generate_text_should_reject_unsupported_engine():
    client = make_client(FakeSdk())

    with pytest.raises(ClientError, match="Unsupported Pegasus engine"):
        client.generate_text(
            video_id="video-123",
            prompt="Describe this video",
            engine="marengo3.0",
        )


def test_generate_text_command_should_pass_engine_and_index_id(monkeypatch):
    runner = CliRunner()
    captured = {}

    class FakeClient:
        def generate_text(self, *, video_id, prompt, temperature, engine, index_id):
            captured.update(
                {
                    "video_id": video_id,
                    "prompt": prompt,
                    "temperature": temperature,
                    "engine": engine,
                    "index_id": index_id,
                }
            )
            return "generated text"

    monkeypatch.setattr(generate, "get_client", lambda: FakeClient())

    result = runner.invoke(
        generate.app,
        [
            "text",
            "video-123",
            "--prompt",
            "Describe this video",
            "--temperature",
            "0",
            "--engine",
            "pegasus1.5",
            "--index-id",
            "index-123",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == "generated text\n"
    assert captured == {
        "video_id": "video-123",
        "prompt": "Describe this video",
        "temperature": 0.0,
        "engine": "pegasus1.5",
        "index_id": "index-123",
    }


def test_generate_text_command_should_default_to_pegasus_1_5(monkeypatch):
    runner = CliRunner()
    captured = {}

    class FakeClient:
        def generate_text(self, *, video_id, prompt, temperature, engine, index_id):
            captured.update(
                {
                    "video_id": video_id,
                    "prompt": prompt,
                    "temperature": temperature,
                    "engine": engine,
                    "index_id": index_id,
                }
            )
            return "generated text"

    monkeypatch.setattr(generate, "get_client", lambda: FakeClient())

    result = runner.invoke(
        generate.app,
        [
            "text",
            "video-123",
            "--prompt",
            "Describe this video",
            "--index-id",
            "index-123",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == "generated text\n"
    assert captured == {
        "video_id": "video-123",
        "prompt": "Describe this video",
        "temperature": None,
        "engine": "pegasus1.5",
        "index_id": "index-123",
    }


def test_indexes_create_command_should_default_to_pegasus_1_5(monkeypatch):
    runner = CliRunner()
    captured = {}

    class FakeClient:
        def create_index(self, *, name, engines):
            captured.update({"name": name, "engines": engines})
            return {"id": "index-123", "index_name": name}

    monkeypatch.setattr(indexes, "get_client", lambda: FakeClient())
    monkeypatch.setattr(indexes, "print_success", lambda message: None)
    monkeypatch.setattr(indexes, "print_json", lambda value: None)

    result = runner.invoke(indexes.app, ["create", "default-index"])

    assert result.exit_code == 0
    assert captured == {
        "name": "default-index",
        "engines": [
            {"engine_name": "pegasus1.5", "engine_options": ["visual", "audio"]}
        ],
    }
