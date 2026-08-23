#!/usr/bin/env bash
# Test: List pending reminders across all workspaces
# Expected: Only Devolutions should have pending (in_progress) reminders
#
# Prerequisites:
#   slack auth login                         (Default workspace)
#   slack auth login --profile partner       (Partner workspace)
#   slack auth login --profile demo          (Demo workspace)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"
source .venv/bin/activate

ORIGINAL_ACTIVE=""
FAILED=0

# Capture which profile is currently active
ORIGINAL_ACTIVE=$(slack auth profiles list 2>/dev/null | python3 -c "
import sys, json
for p in json.load(sys.stdin):
    if p.get('active'):
        print(p['name'])
        break
")

display_name() {
    case "$1" in
        default)      echo "Default Workspace" ;;
        partner)      echo "Partner Workspace" ;;
        demo)         echo "Demo Workspace" ;;
        *)            echo "$1" ;;
    esac
}

echo "=== Reminders List - All Workspaces ==="
echo "Original active profile: $ORIGINAL_ACTIVE"
echo ""

for PROFILE in default partner demo; do
    DISPLAY=$(display_name "$PROFILE")
    echo "--- $DISPLAY ($PROFILE) ---"

    # Select this profile as active
    if ! slack auth profiles select "$PROFILE" > /dev/null 2>&1; then
        echo "  SKIP: Could not select profile '$PROFILE' as active (not authenticated?)"
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

# Restore original active profile
if [ -n "$ORIGINAL_ACTIVE" ]; then
    slack auth profiles select "$ORIGINAL_ACTIVE" > /dev/null 2>&1
    echo "Restored active profile: $ORIGINAL_ACTIVE"
fi

exit $FAILED
