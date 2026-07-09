# X CLI

## DESCRIPTION

The `x` CLI provides command-line access to X API tweet operations and X Developer Console workflows. Use it when agents or terminal automation need JSON-first tweet management or browser-session-backed API credit workflows.

## Installation

```bash
cd x
uv sync --dev
uv pip install -e .
```

## Authentication

Tweet commands use X API OAuth 1.0a credentials:

```bash
x auth profiles create api --auth-type custom
x auth login --profile api --credential-type custom
x auth profiles select api
```

Developer Console actions, including API credits, use a saved browser session:

```bash
x auth profiles create browser --auth-type browser_session
x auth login --profile browser --credential-type browser_session
x auth profiles select browser
```

## Credits

X API credits are purchased through the saved X Developer Console browser
session. After browser-session auth is complete, `x credits add` runs
headlessly against that CLI-owned profile, submits payment when `--yes` is
supplied, and returns purchase-success evidence from X.

If X has no default payment method, the command completes Stripe Embedded
Checkout using a configured LastPass credit-card item and billing fields:

```bash
export X_CREDIT_CARD_LASTPASS_ITEM_ID=LASTPASS_ITEM_ID
export X_BILLING_ADDRESS_LINE1="123 Example St"
export X_BILLING_CITY="Exampleville"
export X_BILLING_STATE="IN"
export X_BILLING_POSTAL_CODE="47725"
export X_BILLING_COUNTRY="US"
export X_BILLING_PHONE="8125550100"
```

```bash
# Preview without submitting payment
x credits add 25.00 --dry-run

# Purchase credits
x credits add 25.00 --profile browser --yes
```

After `x auth login --profile browser --credential-type browser_session`, the
saved CLI browser profile is the auth source of truth; do not switch to Codex's
in-app browser, Computer Use, or another visible browser to finish the same
workflow.

## Tweets

```bash
x tweet post "Hello from the X CLI"
x tweet list --limit 10
x tweet get TWEET_ID
x tweet delete TWEET_ID
```

## Cache

```bash
x cache --help
```
