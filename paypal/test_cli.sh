#!/bin/zsh
# Test script for PayPal CLI

PAYPAL="<cli-tools-root>/paypal/venv/bin/paypal"

echo "=== Testing PayPal CLI ==="
echo ""

echo ">>> paypal --help"
$PAYPAL --help
echo ""
echo "EXIT CODE: $?"
echo ""

echo ">>> paypal auth status"
$PAYPAL auth status
echo ""
echo "EXIT CODE: $?"
echo ""

echo ">>> paypal orders list"
$PAYPAL orders list 2>&1
echo ""
echo "EXIT CODE: $?"
echo ""

echo ">>> paypal labels list"
$PAYPAL labels list 2>&1
echo ""
echo "EXIT CODE: $?"
echo ""

echo "=== Tests Complete ==="
