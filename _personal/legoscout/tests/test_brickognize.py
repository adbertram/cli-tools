from __future__ import annotations

import copy
import importlib
import json
import threading
import time
from pathlib import Path

import pytest
import requests

from legoscout_cli.pricing import json_cache

FIXTURE = Path(__file__).parent / "fixtures" / "brickognize" / "minifig_response.json"


def _brickognize():
    return importlib.import_module("legoscout_cli.pricing.brickognize")


def _response():
    return json.loads(FIXTURE.read_text())


def _crop(path: Path, content: bytes = b"jpeg-crop") -> Path:
    path.write_bytes(content)
    return path


class Response:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self.payload = _response() if payload is None else payload
        self.json_error = json_error
        self.text = json.dumps(self.payload) if payload is not None else ""

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return copy.deepcopy(self.payload)


def test_should_send_exact_legacy_figs_multipart_query_and_metadata(tmp_path):
    brickognize = _brickognize()
    crop = _crop(tmp_path / "crop.jpg")
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    result = brickognize.request_prediction(
        crop,
        top_k=7,
        min_similarity=0.55,
        timeout=12.5,
        post=post,
    )

    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == "https://api.brickognize.com/predict/figs/"
    assert kwargs["params"] == {
        "top_k_items": 7,
        "min_similarity_items": 0.55,
    }
    assert kwargs["files"] == [(
        "query_image",
        ("crop.jpg", b"jpeg-crop", "image/jpeg"),
    )]
    assert kwargs["timeout"] == 12.5
    assert kwargs["headers"] == {
        "User-Agent": "LegoScout/0.1 (+mailto:adam@brickbuddy.io)",
    }
    assert result["response"] == _response()
    assert result["contract"] == {
        "endpoint": url,
        "contract_version": "brickognize-legacy-figs-v1",
        "crop_sha256": (
            "a3f4ba29446c10957d0a44db6e487cecc9be908fee30c599b0dd252b105a2cad"
        ),
        "top_k_items": 7,
        "min_similarity_items": 0.55,
    }


@pytest.mark.parametrize("kwargs, message", [
    ({"top_k": 0}, "top_k"),
    ({"top_k": 51}, "top_k"),
    ({"min_similarity": -0.1}, "min_similarity"),
    ({"min_similarity": 1.1}, "min_similarity"),
    ({"timeout": 0}, "timeout"),
    ({"timeout": float("inf")}, "timeout"),
])
def test_should_validate_request_options_before_io(kwargs, message, tmp_path):
    crop = _crop(tmp_path / "crop.jpg")

    with pytest.raises(_brickognize().BrickognizeConfigurationError,
                       match=message):
        _brickognize().request_prediction(crop, **kwargs)


def test_should_reject_unsupported_crop_mime_before_network(tmp_path):
    crop = _crop(tmp_path / "crop.webp")
    calls = []

    with pytest.raises(_brickognize().BrickognizeConfigurationError,
                       match="JPEG or PNG"):
        _brickognize().request_prediction(
            crop, post=lambda *args, **kwargs: calls.append(args))
    assert calls == []


@pytest.mark.parametrize("mutator, message", [
    (lambda payload: [], "object"),
    (lambda payload: {key: value for key, value in payload.items()
                      if key != "listing_id"}, "listing_id"),
    (lambda payload: {**payload, "bounding_box": {}}, "bounding_box"),
    (lambda payload: {**payload, "items": [{
        key: value for key, value in payload["items"][0].items()
        if key != "id"
    }]}, "item id"),
    (lambda payload: {**payload, "items": [{
        **payload["items"][0], "score": 1.1,
    }]}, "item 0 score"),
    (lambda payload: {**payload, "items": [{
        **payload["items"][0], "external_sites": {},
    }]}, "external_sites"),
])
def test_should_validate_recorded_response_shape(mutator, message):
    payload = mutator(_response())
    with pytest.raises(_brickognize().BrickognizeSchemaError, match=message):
        _brickognize().normalize_response(payload)


def test_should_retry_only_429_and_5xx_twice_then_succeed(tmp_path):
    crop = _crop(tmp_path / "crop.jpg")
    responses = [Response(429, {"detail": "slow"}),
                 Response(503, {"detail": "down"}), Response()]
    sleeps = []

    result = _brickognize().request_prediction(
        crop,
        post=lambda *args, **kwargs: responses.pop(0),
        sleep=sleeps.append,
    )

    assert result["response"] == _response()
    assert responses == []
    assert sleeps == [0.25, 0.5]


def test_should_retry_timeout_twice_then_succeed(tmp_path):
    crop = _crop(tmp_path / "crop.jpg")
    attempts = [requests.Timeout("first"), requests.Timeout("second"), Response()]
    sleeps = []

    def post(*args, **kwargs):
        result = attempts.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    result = _brickognize().request_prediction(
        crop, post=post, sleep=sleeps.append)

    assert result["response"] == _response()
    assert attempts == []
    assert sleeps == [0.25, 0.5]


def test_should_not_retry_4xx_or_schema_errors(tmp_path):
    crop = _crop(tmp_path / "crop.jpg")
    calls = []

    def bad_request(*args, **kwargs):
        calls.append(1)
        return Response(400, {"detail": "bad request"})

    with pytest.raises(_brickognize().BrickognizeHTTPError, match="400"):
        _brickognize().request_prediction(crop, post=bad_request)
    assert calls == [1]

    calls.clear()

    def bad_schema(*args, **kwargs):
        calls.append(1)
        return Response(200, {"items": []})

    with pytest.raises(_brickognize().BrickognizeSchemaError):
        _brickognize().request_prediction(crop, post=bad_schema)
    assert calls == [1]


def test_should_include_content_endpoint_contract_and_params_in_cache_key():
    module = _brickognize()
    base = module.cache_key(
        b"crop", top_k=10, min_similarity=.5,
        endpoint=module.ENDPOINT, contract_version=module.CONTRACT_VERSION)
    variations = {
        module.cache_key(
            b"other", top_k=10, min_similarity=.5,
            endpoint=module.ENDPOINT,
            contract_version=module.CONTRACT_VERSION),
        module.cache_key(
            b"crop", top_k=9, min_similarity=.5,
            endpoint=module.ENDPOINT,
            contract_version=module.CONTRACT_VERSION),
        module.cache_key(
            b"crop", top_k=10, min_similarity=.6,
            endpoint=module.ENDPOINT,
            contract_version=module.CONTRACT_VERSION),
        module.cache_key(
            b"crop", top_k=10, min_similarity=.5,
            endpoint=module.ENDPOINT + "v2",
            contract_version=module.CONTRACT_VERSION),
        module.cache_key(
            b"crop", top_k=10, min_similarity=.5,
            endpoint=module.ENDPOINT,
            contract_version=module.CONTRACT_VERSION + "-v2"),
    }
    assert len(variations) == 5
    assert base not in variations


def test_should_resolve_cache_hits_before_creating_executor(tmp_path):
    module = _brickognize()
    crop = _crop(tmp_path / "crop.jpg")
    cache_path = str(tmp_path / "cache.json")
    key = module.cache_key(
        crop.read_bytes(), top_k=10, min_similarity=.5,
        endpoint=module.ENDPOINT, contract_version=module.CONTRACT_VERSION)
    envelope = {
        "contract": {
            "endpoint": module.ENDPOINT,
            "contract_version": module.CONTRACT_VERSION,
            "crop_sha256": module.crop_sha256(crop.read_bytes()),
            "top_k_items": 10,
            "min_similarity_items": .5,
        },
        "response": _response(),
    }
    json_cache.update(cache_path, {key: envelope})

    def executor(*args, **kwargs):
        raise AssertionError("executor must not be created for cache hits")

    rows = module.predict_many(
        [str(crop)], cache_path=cache_path,
        post=lambda *args, **kwargs: pytest.fail("network called"),
        executor_factory=executor,
    )

    assert rows == [{
        "path": str(crop),
        "status": "success",
        "reason": None,
        "cached": True,
        "prediction": envelope,
    }]


def test_should_fail_loudly_on_corrupt_cache_before_scheduler(tmp_path):
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("{torn", encoding="utf-8")
    crop = _crop(tmp_path / "crop.jpg")

    with pytest.raises(json_cache.CorruptCache):
        _brickognize().predict_many(
            [str(crop)], cache_path=str(cache_path))


def test_should_bound_concurrency_to_two_and_preserve_input_order(tmp_path):
    module = _brickognize()
    paths = [_crop(tmp_path / f"crop-{index}.jpg", f"crop-{index}".encode())
             for index in range(6)]
    lock = threading.Lock()
    state = {"active": 0, "maximum": 0, "calls": 0}

    def post(*args, **kwargs):
        with lock:
            state["active"] += 1
            state["calls"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
        time.sleep(.02)
        with lock:
            state["active"] -= 1
        return Response()

    rows = module.predict_many(
        [str(path) for path in paths],
        workers=2,
        cache_path=str(tmp_path / "cache.json"),
        post=post,
    )

    assert state == {"active": 0, "maximum": 2, "calls": 6}
    assert [row["path"] for row in rows] == [str(path) for path in paths]
    assert all(row["status"] == "success" for row in rows)
    assert all(row["cached"] is False for row in rows)


@pytest.mark.parametrize("workers", [0, -1, 3])
def test_should_reject_workers_outside_one_or_two(workers, tmp_path):
    with pytest.raises(_brickognize().BrickognizeConfigurationError,
                       match="workers"):
        _brickognize().predict_many(
            [], workers=workers, cache_path=str(tmp_path / "cache.json"))
