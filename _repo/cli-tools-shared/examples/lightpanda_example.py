#!/usr/bin/env python3
"""
Simple example: Using Lightpanda backend with BrowserAutomation.

This example demonstrates how to use the Lightpanda browser backend
as a drop-in replacement for Chrome/browser-harness. No code changes
required - just set the environment variable.

Usage:
    # With Chrome (default)
    python example_lightpanda.py

    # With Lightpanda
    CLI_TOOLS_BROWSER_BACKEND=lightpanda python example_lightpanda.py
"""

import os
import sys
import tempfile
from pathlib import Path


def main():
    print("=" * 60)
    backend = os.environ.get("CLI_TOOLS_BROWSER_BACKEND", "default (Chrome)")
    print(f"Browser backend: {backend}")
    print("=" * 60)
    
    # Import required classes
    try:
        from cli_tools_shared.auth import BrowserAutomation
        from cli_tools_shared.config import BaseConfig
    except ImportError as e:
        print(f"Error importing cli-tools-shared: {e}")
        print("Run from the cli-tools repo root with dependencies installed")
        sys.exit(1)
    
    # Create minimal config with temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        profile_dir = Path(tmpdir) / "example-profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        
        class ExampleConfig(BaseConfig):
            def __init__(self):
                self.browser_data_dir = profile_dir
                self.headless = True
                self._tool_name = "example"
            
            def get_persistent_profile_dir(self):
                return self.browser_data_dir / "chromium-profile"
            
            def get_active_profile_name(self):
                return "default"
        
        # Create browser automation instance
        config = ExampleConfig()
        browser = BrowserAutomation(config)
        browser.AUTH_CHECK_URL = "http://example.com"
        
        try:
            print("\n1. Opening http://example.com...")
            page = browser.get_page("http://example.com")
            print(f"   URL: {page.url}")
            
            print("\n2. Getting page title...")
            title = page.evaluate("() => document.title")
            print(f"   Title: '{title}'")
            
            print("\n3. Checking for H1 element...")
            has_h1 = page.evaluate("() => !!document.querySelector('h1')")
            print(f"   Has H1: {has_h1}")
            
            if has_h1:
                h1_text = page.evaluate("() => document.querySelector('h1').textContent")
                print(f"   H1 text: '{h1_text}'")
            
            print("\n4. Getting cookies...")
            cookies = browser.live_cookies()
            print(f"   Cookie count: {len(cookies)}")
            
            print("\n5. Testing wait_for_selector...")
            h1_element = page.wait_for_selector("h1", state="visible", timeout=5000)
            print(f"   Found H1: {h1_element is not None}")
            
            print("\n6. Closing browser...")
            browser.close()
            print("   ✓ Closed successfully")
            
            print("\n" + "=" * 60)
            print("✓ Example completed successfully!")
            print("=" * 60)
            
            if backend == "lightpanda":
                print("\nLightpanda backend notes:")
                print("  - Lower memory usage (~350MB vs ~1.8GB)")
                print("  - Slightly slower (~3.6s vs ~2.6s for DOM scrape)")
                print("  - May fail on sites with bot detection")
                print("  - Cookies saved to JSON file")
            
        except Exception as e:
            print(f"\n✗ Error: {e}")
            import traceback
            traceback.print_exc()
            browser.close()
            sys.exit(1)


if __name__ == "__main__":
    main()
