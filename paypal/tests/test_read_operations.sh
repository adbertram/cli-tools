#!/bin/bash
#
# Comprehensive test suite for PayPal CLI read operations
#
# Tests all read-only commands with all parameter combinations.
# Requires an active PayPal session (run `paypal auth login` first).
#
# Usage:
#   cd <cli-tools-root>/paypal
#   source venv/bin/activate
#   ./tests/test_read_operations.sh
#

set -o pipefail

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
PASSED=0
FAILED=0
SKIPPED=0

# Dynamic data (populated during tests)
ORDER_ID=""
TRACKING_NUMBER=""

# =============================================================================
# Helper Functions
# =============================================================================

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASSED++))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    if [[ -n "$2" ]]; then
        echo -e "       ${RED}Error:${NC} $2"
    fi
    ((FAILED++))
}

log_skip() {
    echo -e "${YELLOW}[SKIP]${NC} $1 - $2"
    ((SKIPPED++))
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# Run a test command and check for success
# Usage: run_test "description" command [args...]
run_test() {
    local description="$1"
    shift
    local cmd="$*"

    # Capture both stdout and stderr
    local output
    local exit_code

    output=$(eval "$cmd" 2>&1)
    exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
        log_pass "$description"
        return 0
    else
        log_fail "$description" "Exit code $exit_code"
        echo "       Command: $cmd"
        echo "       Output: ${output:0:200}..."
        return 1
    fi
}

# Run a test that expects specific exit code
# Usage: run_test_exit "description" expected_exit command [args...]
run_test_exit() {
    local description="$1"
    local expected_exit="$2"
    shift 2
    local cmd="$*"

    local output
    local exit_code

    output=$(eval "$cmd" 2>&1)
    exit_code=$?

    if [[ $exit_code -eq $expected_exit ]]; then
        log_pass "$description"
        return 0
    else
        log_fail "$description" "Expected exit $expected_exit, got $exit_code"
        echo "       Command: $cmd"
        return 1
    fi
}

# Run a test and verify output contains expected text
# Usage: run_test_contains "description" "expected_text" command [args...]
run_test_contains() {
    local description="$1"
    local expected="$2"
    shift 2
    local cmd="$*"

    local output
    local exit_code

    output=$(eval "$cmd" 2>&1)
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        log_fail "$description" "Exit code $exit_code"
        echo "       Command: $cmd"
        return 1
    fi

    if echo "$output" | grep -q "$expected"; then
        log_pass "$description"
        return 0
    else
        log_fail "$description" "Output missing '$expected'"
        echo "       Command: $cmd"
        echo "       Output: ${output:0:200}..."
        return 1
    fi
}

# Run a test and verify output is valid JSON
run_test_json() {
    local description="$1"
    shift
    local cmd="$*"

    local output
    local exit_code

    output=$(eval "$cmd" 2>&1)
    exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        log_fail "$description" "Exit code $exit_code"
        echo "       Command: $cmd"
        return 1
    fi

    if echo "$output" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
        log_pass "$description"
        return 0
    else
        log_fail "$description" "Invalid JSON output"
        echo "       Command: $cmd"
        echo "       Output: ${output:0:200}..."
        return 1
    fi
}

# Extract a value from JSON output
# Usage: extract_json "key" command [args...]
extract_json() {
    local key="$1"
    shift
    local cmd="$*"

    eval "$cmd" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$key', d.get('${key}s', [{}])[0].get('$key', '') if isinstance(d.get('${key}s'), list) and d.get('${key}s') else ''))" 2>/dev/null
}

# =============================================================================
# Test Suite
# =============================================================================

echo ""
echo "=============================================="
echo "PayPal CLI Read Operations Test Suite"
echo "=============================================="
echo ""

# Check we're in the right directory
if [[ ! -f "$PROJECT_DIR/paypal_cli/__init__.py" ]]; then
    echo -e "${RED}Error:${NC} Must run from paypal CLI project directory"
    exit 1
fi

# Check paypal command exists
if ! command -v paypal &> /dev/null; then
    echo -e "${RED}Error:${NC} paypal command not found. Run: source venv/bin/activate"
    exit 1
fi

# =============================================================================
# 1. AUTH STATUS TESTS (2 tests)
# =============================================================================

echo ""
echo "--- Auth Status Tests ---"
echo ""

# Test 1.1: auth status JSON output
run_test_json "auth status - JSON output" "paypal auth status"

# Test 1.2: auth status table output
run_test_contains "auth status - table output (-t)" "Setting" "paypal auth status -t"

# =============================================================================
# 2. ORDERS LIST TESTS (11 tests)
# =============================================================================

echo ""
echo "--- Orders List Tests ---"
echo ""

# Test 2.1: orders list default (JSON)
run_test_json "orders list - default JSON" "paypal orders list"

# Test 2.2: orders list table
run_test_contains "orders list - table output (-t)" "Date\|Order\|Status\|Gross\|Total:" "paypal orders list -t"

# Test 2.3: orders list with days filter
run_test_json "orders list - days filter (-d 7)" "paypal orders list -d 7"

# Test 2.4: orders list with longer days
run_test_json "orders list - days filter (-d 90)" "paypal orders list -d 90"

# Test 2.5: orders list with limit
run_test_json "orders list - limit (-l 5)" "paypal orders list -l 5"

# Test 2.6: orders list with query (all fields)
run_test_json "orders list - query all fields (-q 'a' -s all)" "paypal orders list -q 'a' -s all"

# Test 2.7: orders list with query (lastname)
run_test_json "orders list - query lastname (-q 'a' -s lastname)" "paypal orders list -q 'a' -s lastname"

# Test 2.8: orders list with filter
run_test_json "orders list - filter (-f 'status:Completed')" "paypal orders list -f 'status:Completed'"

# Test 2.9: orders list with properties
run_test_json "orders list - properties (-p order_id -p date)" "paypal orders list -p order_id -p date"

# Test 2.10: orders list combined params
run_test_contains "orders list - combined (-d 14 -l 10 -t)" "Total:" "paypal orders list -d 14 -l 10 -t"

# Test 2.11: orders list query + combined
run_test_contains "orders list - query+combined (-q 'a' -d 30 -l 5 -t)" "Total:" "paypal orders list -q 'a' -d 30 -l 5 -s all -t"

# Capture an order ID for later tests
log_info "Extracting order ID for orders get tests..."
ORDER_ID=$(paypal orders list -l 1 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); orders=d.get('orders',[]); print(orders[0].get('order_id','') if orders else '')" 2>/dev/null)
if [[ -n "$ORDER_ID" ]]; then
    log_info "Found order ID: $ORDER_ID"
else
    log_info "No orders found - orders get tests will be skipped"
fi

# =============================================================================
# 3. ORDERS SEARCH TESTS (9 tests)
# =============================================================================

echo ""
echo "--- Orders Search Tests ---"
echo ""

# Test 3.1: orders search default
run_test_json "orders search - default ('a')" "paypal orders search 'a'"

# Test 3.2: orders search table
run_test_contains "orders search - table (-t)" "Found:" "paypal orders search 'a' -t"

# Test 3.3: orders search by lastname
run_test_json "orders search - by lastname (-s lastname)" "paypal orders search 'a' -s lastname"

# Test 3.4: orders search by email
run_test_json "orders search - by email (-s email)" "paypal orders search '@' -s email"

# Test 3.5: orders search by order prefix
run_test_json "orders search - by order ID (-s order)" "paypal orders search 'O-' -s order"

# Test 3.6: orders search with days
run_test_json "orders search - with days (-d 30)" "paypal orders search 'a' -d 30"

# Test 3.7: orders search with limit
run_test_json "orders search - with limit (-l 5)" "paypal orders search 'a' -l 5"

# Test 3.8: orders search with properties
run_test_json "orders search - with properties (-p order_id -p name)" "paypal orders search 'a' -p order_id -p name"

# Test 3.9: orders search combined
run_test_contains "orders search - combined (-d 60 -l 10 -s all -t)" "Found:" "paypal orders search 'a' -d 60 -l 10 -s all -t"

# =============================================================================
# 4. ORDERS RECENT TESTS (2 tests)
# =============================================================================

echo ""
echo "--- Orders Recent Tests ---"
echo ""

# Test 4.1: orders recent default
run_test_json "orders recent - default JSON" "paypal orders recent"

# Test 4.2: orders recent table
run_test_contains "orders recent - table (-t)" "Total:" "paypal orders recent -t"

# =============================================================================
# 5. ORDERS GET TESTS (2 tests)
# =============================================================================

echo ""
echo "--- Orders Get Tests ---"
echo ""

if [[ -n "$ORDER_ID" ]]; then
    # Test 5.1: orders get default
    run_test_json "orders get - JSON ($ORDER_ID)" "paypal orders get '$ORDER_ID'"

    # Test 5.2: orders get table
    run_test_contains "orders get - table (-t)" "Field\|Value" "paypal orders get '$ORDER_ID' -t"
else
    log_skip "orders get - JSON" "No orders available"
    log_skip "orders get - table" "No orders available"
fi

# =============================================================================
# 6. LABELS LIST TESTS (4 tests)
# =============================================================================

echo ""
echo "--- Labels List Tests ---"
echo ""

# Test 6.1: labels list default
run_test_json "labels list - default JSON" "paypal labels list"

# Test 6.2: labels list table
run_test_contains "labels list - table (-t)" "Date\|Service\|Tracking\|Status\|Cost\|Total:" "paypal labels list -t"

# Test 6.3: labels list with limit
run_test_json "labels list - with limit (-l 5)" "paypal labels list -l 5"

# Test 6.4: labels list combined
run_test_contains "labels list - combined (-l 10 -t)" "Total:" "paypal labels list -l 10 -t"

# Capture a tracking number for later tests
log_info "Extracting tracking number for labels find tests..."
TRACKING_NUMBER=$(paypal labels list -l 1 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); labels=d.get('labels',[]); print(labels[0].get('tracking_number','') if labels else '')" 2>/dev/null)
if [[ -n "$TRACKING_NUMBER" ]]; then
    log_info "Found tracking number: $TRACKING_NUMBER"
else
    log_info "No labels found - labels find tests will be skipped"
fi

# =============================================================================
# 7. LABELS FIND TESTS (2 tests)
# =============================================================================

echo ""
echo "--- Labels Find Tests ---"
echo ""

if [[ -n "$TRACKING_NUMBER" ]]; then
    # Test 7.1: labels find default
    run_test_json "labels find - JSON ($TRACKING_NUMBER)" "paypal labels find '$TRACKING_NUMBER'"

    # Test 7.2: labels find table
    run_test_contains "labels find - table (-t)" "Date\|Service\|Tracking\|Status\|Cost" "paypal labels find '$TRACKING_NUMBER' -t"
else
    log_skip "labels find - JSON" "No labels available"
    log_skip "labels find - table" "No labels available"
fi

# =============================================================================
# Summary
# =============================================================================

echo ""
echo "=============================================="
echo "Test Results Summary"
echo "=============================================="
echo ""

TOTAL=$((PASSED + FAILED + SKIPPED))

echo -e "  ${GREEN}Passed:${NC}  $PASSED"
echo -e "  ${RED}Failed:${NC}  $FAILED"
echo -e "  ${YELLOW}Skipped:${NC} $SKIPPED"
echo -e "  Total:   $TOTAL"
echo ""

if [[ $FAILED -eq 0 ]]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAILED test(s) failed.${NC}"
    exit 1
fi
