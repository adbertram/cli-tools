#!/usr/bin/env python3
"""Test script for Podio CLI retry logic."""

import os
import sys
from dotenv import load_dotenv

# Add pypodio2 to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'podio-py'))

from pypodio2 import api, RetryConfig

# Load environment variables
load_dotenv()

def test_default_retry():
    """Test with default retry configuration."""
    print("Testing with default retry configuration (3 retries, exponential backoff)...")

    client = api.OAuthClient(
        api_key=os.getenv('PODIO_CLIENT_ID'),
        api_secret=os.getenv('PODIO_CLIENT_SECRET'),
        login=os.getenv('PODIO_USERNAME'),
        password=os.getenv('PODIO_PASSWORD')
    )

    # Test a simple API call
    try:
        # Get spaces (workspaces)
        spaces = client.Space.find_all()
        print(f"✓ Successfully retrieved {len(spaces)} spaces")
        print(f"  First space: {spaces[0]['name']}")
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def test_custom_retry():
    """Test with custom retry configuration."""
    print("\nTesting with custom retry configuration (5 retries, faster backoff)...")

    # Create custom retry config with more aggressive retry settings
    retry_config = RetryConfig(
        max_retries=5,
        base_delay=0.5,
        max_delay=30.0,
        exponential_base=2.0,
        jitter=True,
        retry_on_rate_limit=True
    )

    client = api.OAuthClient(
        api_key=os.getenv('PODIO_CLIENT_ID'),
        api_secret=os.getenv('PODIO_CLIENT_SECRET'),
        login=os.getenv('PODIO_USERNAME'),
        password=os.getenv('PODIO_PASSWORD'),
        retry_config=retry_config
    )

    # Test a simple API call
    try:
        # Get the Topics app
        app = client.Application.find(int(os.getenv('PODIO_TOPICS_APP_ID')))
        print(f"✓ Successfully retrieved app: {app['config']['name']}")
        print(f"  App ID: {app['app_id']}")
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def test_no_retry():
    """Test with retries disabled."""
    print("\nTesting with retries disabled (max_retries=0)...")

    retry_config = RetryConfig(max_retries=0)

    client = api.OAuthClient(
        api_key=os.getenv('PODIO_CLIENT_ID'),
        api_secret=os.getenv('PODIO_CLIENT_SECRET'),
        login=os.getenv('PODIO_USERNAME'),
        password=os.getenv('PODIO_PASSWORD'),
        retry_config=retry_config
    )

    # Test a simple API call
    try:
        # Get items from Topics app
        items = client.Item.filter(int(os.getenv('PODIO_TOPICS_APP_ID')), {'limit': 5})
        print(f"✓ Successfully retrieved {items['total']} total items (showing 5)")
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


if __name__ == '__main__':
    print("=" * 60)
    print("Podio CLI Retry Logic Test Suite")
    print("=" * 60)

    results = []

    # Run tests
    results.append(("Default Retry", test_default_retry()))
    results.append(("Custom Retry", test_custom_retry()))
    results.append(("No Retry", test_no_retry()))

    # Print summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {test_name}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")

    sys.exit(0 if passed == total else 1)
