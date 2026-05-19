#!/usr/bin/env bash
# Test: List pending reminders across all workspaces
# Expected: Only Devolutions should have pending (in_progress) reminders
#
# Prerequisites:
#   slack auth login                         (ATA Learning - default profile)
#   slack auth login --profile ps-authors    (PS Authors workspace)
#   slack auth login --profile devolutions   (Devolutions workspace)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"
source .venv/bin/activate

ORIGINAL_DEFAULT=""
FAILED=0

# Capture which profile is currently the default
ORIGINAL_DEFAULT=$(slack auth profiles list 2>/dev/null | python3 -c "
import sys, json
for p in json.load(sys.stdin):
    if p.get('is_default'):
        print(p['name'])
        break
")

display_name() {
    case "$1" in
        default)      echo "ATA Learning" ;;
        ps-authors)   echo "PS Authors" ;;
        devolutions)  echo "Devolutions" ;;
        *)            echo "$1" ;;
    esac
}

echo "=== Reminders List - All Workspaces ==="
echo "Original default profile: $ORIGINAL_DEFAULT"
echo ""

for PROFILE in default ps-authors devolutions; do
    DISPLAY=$(display_name "$PROFILE")
    echo "--- $DISPLAY ($PROFILE) ---"

    # Set this profile as default
    if ! slack auth profiles set-default "$PROFILE" > /dev/null 2>&1; then
        echo "  SKIP: Could not set profile '$PROFILE' as default (not authenticated?)"
        echo ""
        continue
    fi

    # Clear cached client state
    slack cache clear > /dev/null 2>&1 || true

    # List in_progress reminders (JSON), extract count
    OUTPUT=$(slack reminders list --state in_progress --limit 200 2>&1) || {
        echo "  ERROR: reminders list failed"
        echo "  $OUTPUT"
        echo ""
        FAILED=1
        continue
    }

    echo "$OUTPUT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
counts = data.get('counts', {})
items = data.get('items', [])
saved = sum(1 for i in items if i.get('source') == 'saved')
reminders = sum(1 for i in items if i.get('source') == 'reminder')
print(f'  Total in_progress: {len(items)} (saved: {saved}, reminders: {reminders})')
print(f'  Saved API total: {counts.get(\"saved_count\", 0)}')
print(f'  Reminders API total: {counts.get(\"reminder_count\", 0)}')
"
    echo ""
done

# Restore original default
if [ -n "$ORIGINAL_DEFAULT" ]; then
    slack auth profiles set-default "$ORIGINAL_DEFAULT" > /dev/null 2>&1
    echo "Restored default profile: $ORIGINAL_DEFAULT"
fi

exit $FAILED
