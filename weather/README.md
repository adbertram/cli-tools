# Weather CLI

## DESCRIPTION

The `weather` CLI provides a command-line interface for Weather API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
cd <cli-tools-root>/weather
uv tool install -e . --force --refresh
```

After installation, the `weather` command will be available in your terminal.

## Quick Start

```bash
# Get current conditions by US ZIP code
weather conditions get 90210

# Use DEFAULT_ZIP from ~/.local/share/cli-tools/weather/.env
weather conditions get

# Show table output
weather conditions get 90210 --table

# Check multiple ZIP codes
weather conditions list 90210 10001 --table

# Use Celsius
weather conditions get 90210 --unit celsius

# Get a 7-day forecast
weather forecast get 90210

# Use DEFAULT_ZIP for forecast
weather forecast get

# Get a 3-day forecast for multiple ZIP codes
weather forecast list 90210 10001 --days 3 --table
```

## Commands

### Conditions

```bash
# Get current temperature and humidity for a ZIP code
weather conditions get 90210

# Use DEFAULT_ZIP from runtime config
weather conditions get

# Get table output
weather conditions get 90210 --table

# List current temperature and humidity for multiple ZIP codes
weather conditions list 90210 10001 --limit 2

# List current conditions for DEFAULT_ZIP
weather conditions list

# Filter listed conditions
weather conditions list 90210 10001 --filter "state:eq:California"

# Use Celsius
weather conditions get 90210 --unit celsius

# Restrict output fields
weather conditions get 90210 --properties "zip_code,place_name,temperature,humidity"
```

### Forecast

```bash
# Get a daily forecast for a ZIP code
weather forecast get 90210

# Use DEFAULT_ZIP from runtime config
weather forecast get

# Choose forecast length, from 1 to 16 days
weather forecast get 90210 --days 3

# List forecasts for multiple ZIP codes
weather forecast list 90210 10001 --days 3 --limit 2

# List forecasts for DEFAULT_ZIP
weather forecast list

# Filter listed forecasts
weather forecast list 90210 10001 --filter "state:eq:California"

# Use Celsius
weather forecast get 90210 --unit celsius

# Restrict output fields
weather forecast get 90210 --properties "zip_code,place_name,start_date,end_date,days"
```

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

### JSON Output Example

```bash
weather conditions get 90210 --properties "zip_code,place_name,temperature,temperature_unit,humidity,humidity_unit"
```

```json
{
  "zip_code": "90210",
  "place_name": "Beverly Hills",
  "temperature": 72.4,
  "temperature_unit": "\u00b0F",
  "humidity": 64,
  "humidity_unit": "%"
}
```

### Table Output Example

```bash
weather conditions get 90210 --table
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum ZIP codes to process for `conditions list` and `forecast list` |
| `--filter` | `-f` | Filter list results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--unit` | `-u` | Temperature unit: `fahrenheit` or `celsius` |
| `--days` | `-d` | Forecast days for `forecast` commands, from 1 to 16 |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/weather/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/weather/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default API base URL
BASE_URL=https://api.open-meteo.com/v1

# Optional: default ZIP used when ZIP_CODE is omitted
DEFAULT_ZIP=47725

# Optional: response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

## Cache

```bash
# Clear cached read responses
weather cache clear

# Bypass the cache for one execution
weather --no-cache conditions get 90210

weather --no-cache forecast get 90210 --days 3
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Read Temperature with jq

```bash
weather conditions get 90210 | jq '.temperature'
```

### Export Conditions to JSON File

```bash
weather conditions get 90210 > weather-90210.json
```

### Export Forecast to JSON File

```bash
weather forecast get 90210 --days 7 > weather-90210-forecast.json
```

## Output Contract

`conditions get` returns one condition object. `conditions list` returns a list
of condition objects for the ZIP codes supplied. The default condition record
shape is:

| Field | Description |
|-------|-------------|
| `id` | Stable identifier; same value as `zip_code` |
| `zip_code` | Requested US ZIP code |
| `place_name` | ZIP-code place name from Zippopotam.us |
| `state` | US state name |
| `latitude` | Latitude used for the forecast lookup |
| `longitude` | Longitude used for the forecast lookup |
| `temperature` | Current temperature value |
| `temperature_unit` | Temperature unit returned by Open-Meteo |
| `humidity` | Current relative humidity value |
| `humidity_unit` | Humidity unit returned by Open-Meteo |
| `observed_at` | Current observation timestamp |
| `zip_lookup` | Full Zippopotam.us response payload |
| `forecast` | Full Open-Meteo forecast response payload |

`forecast get` returns one forecast object. `forecast list` returns a list of
forecast objects for the ZIP codes supplied. The default forecast record shape
is:

| Field | Description |
|-------|-------------|
| `id` | Stable identifier; same value as `zip_code` |
| `zip_code` | Requested US ZIP code |
| `place_name` | ZIP-code place name from Zippopotam.us |
| `state` | US state name |
| `latitude` | Latitude used for the forecast lookup |
| `longitude` | Longitude used for the forecast lookup |
| `days_count` | Number of daily forecast entries returned |
| `start_date` | First forecast date |
| `end_date` | Last forecast date |
| `days` | Daily forecast entries with temperature, humidity, precipitation probability, and weather code |
| `zip_lookup` | Full Zippopotam.us response payload |
| `forecast` | Full Open-Meteo forecast response payload |

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
