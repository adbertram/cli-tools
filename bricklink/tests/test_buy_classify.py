"""Classifier unit tests for BrickLink buy ajax responses."""

from bricklink_cli.buy.classify import ResponseClass, classify_response


def test_empty_403_is_throttle():
    result = classify_response(status_code=403, content=b"")
    assert result.classification == ResponseClass.THROTTLE


def test_ok_json_return_code_zero():
    body = b'{"returnCode":0,"returnMessage":"","list":[]}'
    result = classify_response(status_code=200, content=body)
    assert result.classification == ResponseClass.OK_JSON
    assert result.return_code == 0


def test_bl_error_return_code_nonzero():
    body = b'{"returnCode":1,"returnMessage":"Invalid Parameter"}'
    result = classify_response(status_code=200, content=body)
    assert result.classification == ResponseClass.BL_ERROR
    assert result.return_code == 1


def test_waf_202_is_throttle():
    result = classify_response(
        status_code=202,
        content=b"<html>challenge</html>",
        headers={"x-amzn-waf-action": "challenge"},
    )
    assert result.classification == ResponseClass.THROTTLE


def test_503_is_throttle():
    result = classify_response(status_code=503, content=b"")
    assert result.classification == ResponseClass.THROTTLE


def test_shared_policy_empty_403():
    import requests
    from cli_tools_shared.http_session import RequestsRetryPolicy

    r = requests.Response()
    r.status_code = 403
    r._content = b""
    assert RequestsRetryPolicy().is_retryable_response(r)
    assert RequestsRetryPolicy.is_empty_forbidden(r)
