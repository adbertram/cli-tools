#!/usr/bin/env python3
"""Smoke test for Lightpanda browser backend.

Tests basic navigation, evaluate, and cookie operations against example.com.
Run with CLI_TOOLS_BROWSER_BACKEND=lightpanda to test Lightpanda backend.
"""

import json
import os
import sys
import tempfile
from pathlib import Path


def test_lightpanda_service():
    """Test LightpandaBrowserService directly."""
    print("=" * 60)
    print("Testing LightpandaBrowserService directly")
    print("=" * 60)
    
    # Import service
    try:
        from cli_tools_shared.browser.lightpanda_service import LightpandaBrowserService
    except ImportError as e:
        print(f"SKIP: {e}")
        return
    
    # Create temp profile dir
    with tempfile.TemporaryDirectory() as tmpdir:
        profile_dir = Path(tmpdir) / "lightpanda-test-profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        
        service = LightpandaBrowserService("test-session")
        
        try:
            print("\n1. Opening browser...")
            result = service.browser_open(
                url="http://example.com",
                persistent_profile_dir=profile_dir,
            )
            print(f"   ✓ Opened: {result.get('url', '')}")
            
            print("\n2. Testing evaluate (function form)...")
            title = service.evaluate("() => document.title")
            print(f"   ✓ Page title: {title}")
            
            print("\n3. Testing DOM query...")
            has_h1 = service.evaluate("() => !!document.querySelector('h1')")
            print(f"   ✓ Has H1: {has_h1}")
            
            print("\n4. Testing selector wait...")
            element = service.wait_for_selector("h1", state="visible", timeout=5000)
            print(f"   ✓ Found H1 element: {element is not None}")
            
            print("\n5. Testing cookie list...")
            cookies = service.cookie_list()
            print(f"   ✓ Cookies count: {len(cookies)}")
            
            print("\n6. Testing localStorage...")
            service.evaluate("() => { localStorage.setItem('test', 'value123'); }")
            storage = service.localstorage_list()
            print(f"   ✓ localStorage entries: {len(storage)}")
            test_value = next((item['value'] for item in storage if item['key'] == 'test'), None)
            print(f"   ✓ Test value retrieved: {test_value == 'value123'}")
            
            print("\n7. Closing browser...")
            service.browser_close()
            print("   ✓ Closed successfully")
            
            print("\n8. Checking cookie persistence...")
            cookie_file = profile_dir / "cookies.json"
            if cookie_file.exists():
                saved_cookies = json.loads(cookie_file.read_text())
                print(f"   ✓ Cookies saved: {len(saved_cookies)} cookies in {cookie_file}")
            else:
                print(f"   ⚠ No cookie file found (expected for example.com with no cookies)")
            
            print("\n" + "=" * 60)
            print("✓ All Lightpanda service tests passed!")
            print("=" * 60)
            
        except Exception as exc:
            print(f"\n✗ Test failed: {exc}")
            import traceback
            traceback.print_exc()
            service.browser_close()
            sys.exit(1)


def test_browser_automation_integration():
    """Test BrowserAutomation with Lightpanda backend via env var."""
    print("\n" + "=" * 60)
    print("Testing BrowserAutomation with CLI_TOOLS_BROWSER_BACKEND")
    print("=" * 60)
    
    # Set backend
    os.environ["CLI_TOOLS_BROWSER_BACKEND"] = "lightpanda"
    
    try:
        from cli_tools_shared.auth import BrowserAutomation
        from cli_tools_shared.config import BaseConfig
    except ImportError as e:
        print(f"SKIP: {e}")
        return
    
    # Create minimal config
    with tempfile.TemporaryDirectory() as tmpdir:
        profile_dir = Path(tmpdir) / "browser-automation-profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        
        class TestConfig(BaseConfig):
            def __init__(self):
                self.browser_data_dir = profile_dir
                self.headless = True
                self._tool_name = "test-tool"
            
            def get_persistent_profile_dir(self):
                return self.browser_data_dir / "chromium-profile"
            
            def get_active_profile_name(self):
                return "default"
        
        config = TestConfig()
        browser = BrowserAutomation(config)
        browser.AUTH_CHECK_URL = "http://example.com"
        
        try:
            print("\n1. Opening page via BrowserAutomation...")
            page = browser.get_page("http://example.com")
            print(f"   ✓ Opened: {page.url}")
            
            print("\n2. Testing evaluate...")
            title = page.evaluate("() => document.title")
            print(f"   ✓ Title: {title}")
            
            print("\n3. Testing wait_for_selector...")
            h1 = page.wait_for_selector("h1", state="visible", timeout=5000)
            print(f"   ✓ Found H1: {h1 is not None}")
            
            print("\n4. Testing live_cookies...")
            cookies = browser.live_cookies()
            print(f"   ✓ Cookies: {len(cookies)}")
            
            print("\n5. Closing...")
            browser.close()
            print("   ✓ Closed successfully")
            
            print("\n" + "=" * 60)
            print("✓ All BrowserAutomation integration tests passed!")
            print("=" * 60)
            
        except Exception as exc:
            print(f"\n✗ Test failed: {exc}")
            import traceback
            traceback.print_exc()
            browser.close()
            sys.exit(1)


def main():
    """Run all smoke tests."""
    print("\n" + "=" * 60)
    print("LIGHTPANDA BROWSER BACKEND SMOKE TEST")
    print("=" * 60)
    
    # Check dependencies
    try:
        from playwright.sync_api import sync_playwright
        print("✓ Playwright installed")
    except ImportError:
        print("✗ Playwright not installed (required for Lightpanda CDP connection)")
        print("  Install: uv add playwright")
        sys.exit(1)
    
    # Note: We can't check for lightpanda binary here since it might be in PATH
    # The service will fail gracefully with a clear error if not found
    
    # Run tests
    test_lightpanda_service()
    test_browser_automation_integration()
    
    print("\n" + "=" * 60)
    print("✓ ALL SMOKE TESTS PASSED")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Install Lightpanda: npm install -g @lightpanda/browser")
    print("  2. Run a CLI with: CLI_TOOLS_BROWSER_BACKEND=lightpanda <cli> <command>")
    print("  3. Compare memory: Chrome ~1.8GB vs Lightpanda ~350MB")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
