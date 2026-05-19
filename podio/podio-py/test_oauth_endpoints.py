#!/usr/bin/env python3
"""
Test script to verify which Podio OAuth endpoints actually work.
Tests both /oauth/token and /oauth/token/v2 for different authentication methods.
"""

import sys
import json
from httplib2 import Http
try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode


def test_endpoint(url, body, description):
    """Test an OAuth endpoint and return the result."""
    print(f"\n{'=' * 70}")
    print(f"Testing: {description}")
    print(f"URL: {url}")
    print(f"Body: {json.dumps(body, indent=2)}")
    print('-' * 70)

    try:
        h = Http(disable_ssl_certificate_validation=True)
        headers = {'content-type': 'application/x-www-form-urlencoded'}
        response, data = h.request(url, "POST", urlencode(body), headers=headers)

        print(f"Status: {response.status}")

        if data:
            try:
                data_str = data.decode('utf-8')
                parsed = json.loads(data_str)
                print(f"Response: {json.dumps(parsed, indent=2)}")
                success = response.status == 200
            except:
                print(f"Response (raw): {data}")
                success = response.status == 200
        else:
            print("Response: (empty)")
            success = False

        print(f"Result: {'✅ SUCCESS' if success else '❌ FAILED'}")
        return success

    except Exception as e:
        print(f"Error: {e}")
        print("Result: ❌ FAILED")
        return False


def main():
    """Run endpoint tests."""

    # Check for credentials
    if len(sys.argv) < 3:
        print("Usage: python test_oauth_endpoints.py <client_id> <client_secret> [username] [password] [app_id] [app_token]")
        print("\nProvide at least client_id and client_secret.")
        print("For password flow: also provide username and password")
        print("For app flow: also provide app_id and app_token")
        sys.exit(1)

    client_id = sys.argv[1]
    client_secret = sys.argv[2]
    username = sys.argv[3] if len(sys.argv) > 3 else None
    password = sys.argv[4] if len(sys.argv) > 4 else None
    app_id = sys.argv[5] if len(sys.argv) > 5 else None
    app_token = sys.argv[6] if len(sys.argv) > 6 else None

    results = {}

    print("\n" + "=" * 70)
    print("PODIO OAUTH ENDPOINT VERIFICATION TEST")
    print("=" * 70)

    # Test 1: Password flow with /oauth/token
    if username and password:
        body = {
            'grant_type': 'password',
            'client_id': client_id,
            'client_secret': client_secret,
            'username': username,
            'password': password
        }
        results['password_v1'] = test_endpoint(
            "https://api.podio.com/oauth/token",
            body,
            "Password Flow - /oauth/token (v1)"
        )

        # Test 2: Password flow with /oauth/token/v2
        results['password_v2'] = test_endpoint(
            "https://api.podio.com/oauth/token/v2",
            body,
            "Password Flow - /oauth/token/v2"
        )

    # Test 3: App flow with /oauth/token
    if app_id and app_token:
        body = {
            'grant_type': 'app',
            'client_id': client_id,
            'client_secret': client_secret,
            'app_id': app_id,
            'app_token': app_token
        }
        results['app_v1'] = test_endpoint(
            "https://api.podio.com/oauth/token",
            body,
            "App Flow - /oauth/token (v1)"
        )

        # Test 4: App flow with /oauth/token/v2
        results['app_v2'] = test_endpoint(
            "https://api.podio.com/oauth/token/v2",
            body,
            "App Flow - /oauth/token/v2"
        )

    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    for test_name, success in results.items():
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{test_name:20s}: {status}")

    print("\n" + "=" * 70)
    print("RECOMMENDATION")
    print("=" * 70)

    if 'password_v1' in results and 'password_v2' in results:
        if results['password_v2']:
            print("Password flow: Use /oauth/token/v2 ✅")
        elif results['password_v1']:
            print("Password flow: Use /oauth/token (v1) ⚠️")
        else:
            print("Password flow: Both endpoints failed ❌")

    if 'app_v1' in results and 'app_v2' in results:
        if results['app_v2']:
            print("App flow: Use /oauth/token/v2 ✅")
        elif results['app_v1']:
            print("App flow: Use /oauth/token (v1) ⚠️")
        else:
            print("App flow: Both endpoints failed ❌")

    print("=" * 70 + "\n")

    # Exit with appropriate code
    if all(results.values()):
        sys.exit(0)  # All tests passed
    elif any(results.values()):
        sys.exit(1)  # Some tests passed
    else:
        sys.exit(2)  # All tests failed


if __name__ == "__main__":
    main()
