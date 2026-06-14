import pytest
from typer.testing import CliRunner

from cli_tools_shared.exceptions import ClientError
from weather_cli.client import WeatherClient
from weather_cli.main import app


class FakeConfig:
    base_url = "https://api.open-meteo.com/v1"
    default_zip = None

    def __init__(self, storage_dir):
        self.storage_dir = storage_dir


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = str(payload)
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


ZIP_PAYLOAD = {
    "post code": "90210",
    "country": "United States",
    "country abbreviation": "US",
    "places": [
        {
            "place name": "Beverly Hills",
            "longitude": "-118.4065",
            "state": "California",
            "state abbreviation": "CA",
            "latitude": "34.0901",
        }
    ],
}

FORECAST_PAYLOAD = {
    "latitude": 34.125,
    "longitude": -118.375,
    "generationtime_ms": 0.01,
    "utc_offset_seconds": -25200,
    "timezone": "America/Los_Angeles",
    "timezone_abbreviation": "PDT",
    "elevation": 86.0,
    "current_units": {
        "time": "iso8601",
        "interval": "seconds",
        "temperature_2m": "\u00b0F",
        "relative_humidity_2m": "%",
    },
    "current": {
        "time": "2026-06-08T12:00",
        "interval": 900,
        "temperature_2m": 72.4,
        "relative_humidity_2m": 64,
    },
}

DAILY_FORECAST_PAYLOAD = {
    "latitude": 34.125,
    "longitude": -118.375,
    "generationtime_ms": 0.01,
    "utc_offset_seconds": -25200,
    "timezone": "America/Los_Angeles",
    "timezone_abbreviation": "PDT",
    "elevation": 86.0,
    "daily_units": {
        "time": "iso8601",
        "weather_code": "wmo code",
        "temperature_2m_max": "\u00b0F",
        "temperature_2m_min": "\u00b0F",
        "temperature_2m_mean": "\u00b0F",
        "relative_humidity_2m_mean": "%",
        "relative_humidity_2m_max": "%",
        "relative_humidity_2m_min": "%",
        "precipitation_probability_max": "%",
    },
    "daily": {
        "time": ["2026-06-08", "2026-06-09"],
        "weather_code": [3, 61],
        "temperature_2m_max": [73.3, 71.2],
        "temperature_2m_min": [57.9, 56.1],
        "temperature_2m_mean": [64.9, 63.4],
        "relative_humidity_2m_mean": [72, 74],
        "relative_humidity_2m_max": [89, 91],
        "relative_humidity_2m_min": [59, 63],
        "precipitation_probability_max": [0, 20],
    },
}


def test_get_conditions_uses_zip_location_and_weather_request(monkeypatch, tmp_path):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if url == "https://api.zippopotam.us/us/90210":
            return FakeResponse(ZIP_PAYLOAD)
        if url == "https://api.open-meteo.com/v1/forecast":
            return FakeResponse(FORECAST_PAYLOAD)
        raise AssertionError(url)

    monkeypatch.setattr("weather_cli.client.requests.request", fake_request)

    row = WeatherClient(config=FakeConfig(tmp_path)).get_conditions("90210")

    assert row["zip_code"] == "90210"
    assert row["id"] == "90210"
    assert row["place_name"] == "Beverly Hills"
    assert row["temperature"] == 72.4
    assert row["temperature_unit"] == "\u00b0F"
    assert row["humidity"] == 64
    assert row["humidity_unit"] == "%"
    assert row["zip_lookup"] == ZIP_PAYLOAD
    assert row["forecast"] == FORECAST_PAYLOAD
    assert calls[1]["params"] == {
        "latitude": "34.0901",
        "longitude": "-118.4065",
        "current": "temperature_2m,relative_humidity_2m",
        "temperature_unit": "fahrenheit",
        "timezone": "auto",
    }


def test_get_conditions_rejects_non_five_digit_zip(tmp_path):
    with pytest.raises(ClientError, match="exactly 5 digits"):
        WeatherClient(config=FakeConfig(tmp_path)).get_conditions("90210-1234")


def test_get_forecast_uses_zip_location_and_daily_weather_request(monkeypatch, tmp_path):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if url == "https://api.zippopotam.us/us/90210":
            return FakeResponse(ZIP_PAYLOAD)
        if url == "https://api.open-meteo.com/v1/forecast":
            return FakeResponse(DAILY_FORECAST_PAYLOAD)
        raise AssertionError(url)

    monkeypatch.setattr("weather_cli.client.requests.request", fake_request)

    row = WeatherClient(config=FakeConfig(tmp_path)).get_forecast("90210", days=2)

    assert row["zip_code"] == "90210"
    assert row["id"] == "90210"
    assert row["place_name"] == "Beverly Hills"
    assert row["days_count"] == 2
    assert row["start_date"] == "2026-06-08"
    assert row["end_date"] == "2026-06-09"
    assert row["days"][0] == {
        "date": "2026-06-08",
        "weather_code": 3,
        "temperature_max": 73.3,
        "temperature_min": 57.9,
        "temperature_mean": 64.9,
        "temperature_unit": "\u00b0F",
        "humidity_mean": 72,
        "humidity_max": 89,
        "humidity_min": 59,
        "humidity_unit": "%",
        "precipitation_probability_max": 0,
        "precipitation_probability_unit": "%",
    }
    assert row["zip_lookup"] == ZIP_PAYLOAD
    assert row["forecast"] == DAILY_FORECAST_PAYLOAD
    assert calls[1]["params"] == {
        "latitude": "34.0901",
        "longitude": "-118.4065",
        "daily": (
            "weather_code,temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
            "relative_humidity_2m_mean,relative_humidity_2m_max,relative_humidity_2m_min,"
            "precipitation_probability_max"
        ),
        "temperature_unit": "fahrenheit",
        "timezone": "auto",
        "forecast_days": 2,
    }


def test_get_forecast_rejects_invalid_day_count(tmp_path):
    with pytest.raises(ClientError, match="between 1 and 16"):
        WeatherClient(config=FakeConfig(tmp_path)).get_forecast("90210", days=17)


def test_conditions_get_outputs_json(monkeypatch):
    class FakeClient:
        def get_conditions(self, zip_code, unit):
            assert zip_code == "90210"
            assert unit == "celsius"
            return {
                "zip_code": "90210",
                "place_name": "Beverly Hills",
                "temperature": 22.4,
                "temperature_unit": "\u00b0C",
                "humidity": 64,
                "humidity_unit": "%",
            }

    monkeypatch.setattr("weather_cli.main.get_client", lambda: FakeClient())
    result = CliRunner().invoke(app, ["conditions", "get", "90210", "--unit", "celsius"])

    assert result.exit_code == 0
    assert '"zip_code": "90210"' in result.stdout
    assert '"humidity": 64' in result.stdout


def test_conditions_get_uses_default_zip_when_argument_omitted(monkeypatch):
    class FakeConfig:
        default_zip = "47725"

    class FakeClient:
        def get_conditions(self, zip_code, unit):
            assert zip_code == "47725"
            assert unit == "fahrenheit"
            return {
                "zip_code": "47725",
                "place_name": "Evansville",
                "temperature": 75.0,
                "humidity": 50,
            }

    monkeypatch.setattr("weather_cli.main.get_config", lambda: FakeConfig())
    monkeypatch.setattr("weather_cli.main.get_client", lambda: FakeClient())
    result = CliRunner().invoke(app, ["conditions", "get"])

    assert result.exit_code == 0
    assert '"zip_code": "47725"' in result.stdout


def test_conditions_get_requires_zip_when_default_missing(monkeypatch):
    class FakeConfig:
        default_zip = None

    monkeypatch.setattr("weather_cli.main.get_config", lambda: FakeConfig())
    result = CliRunner().invoke(app, ["conditions", "get"])

    assert result.exit_code == 1
    assert "Pass ZIP_CODE or set DEFAULT_ZIP" in result.stderr


def test_conditions_list_outputs_json(monkeypatch):
    class FakeClient:
        def list_conditions(self, zip_codes, limit, unit):
            assert zip_codes == ["90210", "10001"]
            assert limit == 1
            assert unit == "fahrenheit"
            return [
                {
                    "id": "90210",
                    "zip_code": "90210",
                    "place_name": "Beverly Hills",
                    "temperature": 72.4,
                    "humidity": 64,
                }
            ]

    monkeypatch.setattr("weather_cli.main.get_client", lambda: FakeClient())
    result = CliRunner().invoke(app, ["conditions", "list", "--limit", "1", "90210", "10001"])

    assert result.exit_code == 0
    assert '"zip_code": "90210"' in result.stdout
    assert result.stdout.strip().startswith("[")


def test_conditions_list_uses_default_zip_when_arguments_omitted(monkeypatch):
    class FakeConfig:
        default_zip = "47725"

    class FakeClient:
        def list_conditions(self, zip_codes, limit, unit):
            assert zip_codes == ["47725"]
            assert limit == 100
            assert unit == "fahrenheit"
            return [
                {
                    "id": "47725",
                    "zip_code": "47725",
                    "place_name": "Evansville",
                    "temperature": 75.0,
                    "humidity": 50,
                }
            ]

    monkeypatch.setattr("weather_cli.main.get_config", lambda: FakeConfig())
    monkeypatch.setattr("weather_cli.main.get_client", lambda: FakeClient())
    result = CliRunner().invoke(app, ["conditions", "list"])

    assert result.exit_code == 0
    assert '"zip_code": "47725"' in result.stdout


def test_forecast_get_outputs_json(monkeypatch):
    class FakeClient:
        def get_forecast(self, zip_code, days, unit):
            assert zip_code == "90210"
            assert days == 3
            assert unit == "celsius"
            return {
                "zip_code": "90210",
                "place_name": "Beverly Hills",
                "days_count": 3,
                "days": [
                    {
                        "date": "2026-06-08",
                        "temperature_max": 23.0,
                        "humidity_mean": 72,
                    }
                ],
            }

    monkeypatch.setattr("weather_cli.main.get_client", lambda: FakeClient())
    result = CliRunner().invoke(app, ["forecast", "get", "90210", "--days", "3", "--unit", "celsius"])

    assert result.exit_code == 0
    assert '"zip_code": "90210"' in result.stdout
    assert '"days_count": 3' in result.stdout
    assert '"humidity_mean": 72' in result.stdout


def test_forecast_get_uses_default_zip_when_argument_omitted(monkeypatch):
    class FakeConfig:
        default_zip = "47725"

    class FakeClient:
        def get_forecast(self, zip_code, days, unit):
            assert zip_code == "47725"
            assert days == 7
            assert unit == "fahrenheit"
            return {
                "zip_code": "47725",
                "place_name": "Evansville",
                "days_count": 7,
                "days": [],
            }

    monkeypatch.setattr("weather_cli.main.get_config", lambda: FakeConfig())
    monkeypatch.setattr("weather_cli.main.get_client", lambda: FakeClient())
    result = CliRunner().invoke(app, ["forecast", "get"])

    assert result.exit_code == 0
    assert '"zip_code": "47725"' in result.stdout


def test_forecast_list_outputs_json(monkeypatch):
    class FakeClient:
        def list_forecasts(self, zip_codes, limit, days, unit):
            assert zip_codes == ["90210", "10001"]
            assert limit == 1
            assert days == 2
            assert unit == "fahrenheit"
            return [
                {
                    "id": "90210",
                    "zip_code": "90210",
                    "place_name": "Beverly Hills",
                    "state": "California",
                    "days_count": 2,
                }
            ]

    monkeypatch.setattr("weather_cli.main.get_client", lambda: FakeClient())
    result = CliRunner().invoke(app, ["forecast", "list", "--limit", "1", "--days", "2", "90210", "10001"])

    assert result.exit_code == 0
    assert '"zip_code": "90210"' in result.stdout
    assert result.stdout.strip().startswith("[")


def test_forecast_list_uses_default_zip_when_arguments_omitted(monkeypatch):
    class FakeConfig:
        default_zip = "47725"

    class FakeClient:
        def list_forecasts(self, zip_codes, limit, days, unit):
            assert zip_codes == ["47725"]
            assert limit == 100
            assert days == 7
            assert unit == "fahrenheit"
            return [
                {
                    "id": "47725",
                    "zip_code": "47725",
                    "place_name": "Evansville",
                    "state": "Indiana",
                    "days_count": 7,
                }
            ]

    monkeypatch.setattr("weather_cli.main.get_config", lambda: FakeConfig())
    monkeypatch.setattr("weather_cli.main.get_client", lambda: FakeClient())
    result = CliRunner().invoke(app, ["forecast", "list"])

    assert result.exit_code == 0
    assert '"zip_code": "47725"' in result.stdout
