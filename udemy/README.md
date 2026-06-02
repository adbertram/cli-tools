# Udemy CLI

Command-line access to Udemy instructor courses. Course list/get commands use the Udemy Instructor API. Course management read/update commands use an authenticated browser session because Udemy does not provide an API for those manage pages.

## Installation

```bash
uv tool install -e <cli-tools-root>/udemy --force --refresh
```

## Quick Start

```bash
# Authenticate with Udemy
udemy auth login

# List instructor courses
udemy courses list

# Get a specific course
udemy courses get COURSE_ID

# Read all non-curriculum manage-page fields
udemy courses management 4902274

# Update manage-page fields from JSON
udemy courses update 4902274 --file updates.json
```

## Commands

### Authentication

Udemy issues the token from the API Clients page in your user profile:
https://www.udemy.com/user/edit-api-clients/

```bash
# Save a bearer token
udemy auth login
udemy auth login --force

# Save only the Instructor API bearer token
udemy auth login --credential-type personal_access_token

# Save only the browser session used by manage-page commands
udemy auth login --credential-type browser_session

# Check authentication status
udemy auth status
udemy auth status --table

# Clear stored credentials
udemy auth logout
```

### Profiles

```bash
# List all profiles
udemy auth profiles list

# Show active profile
udemy auth profiles get default

# Select active profile
udemy auth profiles select PROFILE_NAME

# Create a new profile
udemy auth profiles create PROFILE_NAME

# Use a specific profile
udemy auth login --profile PROFILE_NAME
udemy auth profiles select PROFILE_NAME
```

### Cache

```bash
# Clear cached responses
udemy cache clear
```

### Courses

```bash
# List courses as JSON
udemy courses list

# List courses as a table
udemy courses list --table

# Limit results
udemy courses list --limit 10

# Select output fields
udemy courses list --properties "id,title,url"

# Get a specific course
udemy courses get COURSE_ID
udemy courses get COURSE_ID --table

# Get all browser-backed management fields except curriculum
udemy courses management 4902274

# Update browser-backed management fields except curriculum
udemy courses update 4902274 --file updates.json
```

`--filter` is present for CLI consistency. Udemy does not document server-side course filters for this endpoint, so using `--filter` returns a clear error instead of silently filtering client-side.

`courses management` returns these sections:

| Section | Data Included |
|---------|---------------|
| `goals` | Requirements, learning objectives, intended learners |
| `basics` | Title, subtitle, description HTML, locale, level, category, subcategory, topics, promo asset, category/locale options |
| `pricing` | Paid/free state, backup price tier, price tiers, deals price range |
| `promotions` | Referral code, coupon metadata, active coupons, expired coupons |
| `communications` | Welcome and congratulations messages |
| `availability` | Instructor availability status and valid status values |
| `accessibility` | Accessibility settings and valid on/off values |
| `captions` | Course caption metadata, translations, published captions, draft captions, translation availability values |
| `feedback` | Quality status and Udemy review criteria feedback |
| `students` | Student list metadata and first page of student rows |

`curriculum` is intentionally rejected by the update command.

Udemy blocks these manage-page JSON requests from headless Chromium, so `courses management` and `courses update` use the saved browser session in headed Chrome.

### Course Management Update JSON

The update file must be a JSON object. Include only the sections you want to update.

```json
{
  "goals": {
    "requirements_data": {
      "items": [
        "A Windows 10 or later computer logged in as a local administrator"
      ]
    },
    "what_you_will_learn_data": {
      "items": [
        "Install PowerShell Core",
        "Write your first PowerShell script",
        "Build and run Pester tests",
        "Build a real-world PowerShell module"
      ]
    },
    "who_should_attend_data": {
      "items": [
        "System administrators new to PowerShell"
      ]
    }
  },
  "basics": {
    "title": "PowerShell for Sysadmins: Getting Started (v7+)",
    "headline": "Getting Started",
    "description": "<p>Course description HTML</p>",
    "locale": "en_US",
    "instructional_level_id": 1,
    "category_id": 294,
    "subcategory_id": 138,
    "labels_json": "{\"approved_labels\":{\"ids\":[6746],\"primary\":6746},\"proposed_labels\":{\"ids\":[],\"primary\":null}}",
    "promo_asset": 44737590
  },
  "pricing": {
    "price_money": {
      "amount": 24.99,
      "currency": "usd"
    }
  },
  "communications": [
    {
      "message_type": "welcome",
      "content": "<p>Welcome message HTML</p>"
    }
  ],
  "availability": {
    "status": 1,
    "respond_time_frame": "12 hours",
    "available_date": null,
    "apply_to_all_courses": false
  },
  "accessibility": {
    "are_captions_provided": "on",
    "is_audio_description_included": "off",
    "is_course_content_accessible": "on"
  },
  "captions": [
    {
      "locale": "de_DE",
      "availability": "restricted"
    }
  ],
  "promotions": [
    {
      "code": "CODETEST123456",
      "discount_value": 12.99,
      "discount_strategy": "long_discount",
      "start_time": "2026-04-20T18:30:00.000Z"
    }
  ]
}
```

Valid availability statuses are `1` (`AVAILABLE`), `2` (`NOT_AVAILABLE`), and `3` (`UNSPECIFIED`). Valid response windows are `12 hours`, `24 hours`, `48 hours`, `2-4 days`, and `1 week`. Caption translation availability must be `public` or `restricted`.

## Output Formats

JSON is the default output format. Use `--table` for human-readable output.

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display table output |
| `--limit` | `-l` | Maximum number of courses |
| `--filter` | `-f` | Standard filter syntax; returns an error for courses because Udemy does not document course filters |
| `--properties` | `-p` | Comma-separated fields to include |
| `--version` | `-v` | Show version and exit |

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/udemy/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/udemy/.env`:

```bash
ACTIVE=true
PERSONAL_ACCESS_TOKEN=your_udemy_instructor_api_bearer_token
BASE_URL=https://www.udemy.com/instructor-api/v1
BROWSER_SESSION=udemy
```

`BROWSER_SESSION` names the browser session used for browser-backed course management commands.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Course IDs and Titles

```bash
udemy courses list --properties "id,title" | jq '.[]'
```

### Export Courses to JSON

```bash
udemy courses list --limit 200 > courses.json
```

## Models

This CLI uses Pydantic models for type-safe data handling. All commands return strongly-typed models.

### Available Models

| Model | Description | Required Fields |
|-------|-------------|-----------------|
| `Course` | Instructor-taught course | `id`, `title`, `url` |

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - pydantic

## License

MIT
