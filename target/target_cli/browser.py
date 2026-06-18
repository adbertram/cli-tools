import contextlib
import os
import subprocess
import time
from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError
from cli_tools_shared.output import print_info, print_success
from playwright.sync_api import sync_playwright

class TargetBrowser(BrowserAutomation):
    """Browser automation for Target."""

    SESSION_NAME = "target"
    LOGIN_URL = "https://www.target.com/login"
    AUTH_CHECK_URL = "https://www.target.com"
    AUTH_URL_PATTERN = r"/login|/register"
    AUTH_SUCCESS_SELECTOR = 'button[data-test="@web/AccountLink"]'
    AUTH_LOGIN_FORM_SELECTOR = 'input[type="password"]'

    def authenticate(self, force: bool = False):
        if not force and self.is_authenticated():
            return

        profile_dir = self._get_persistent_profile_dir()
        profile_dir.mkdir(parents=True, exist_ok=True)
        
        # Get credentials
        print_info("Fetching Target credentials from LastPass...")
        try:
            username = subprocess.check_output(["lpass", "show", "--username", "Shopping/target.com"], text=True).strip()
            password = subprocess.check_output(["lpass", "show", "--password", "Shopping/target.com"], text=True).strip()
        except subprocess.CalledProcessError:
            raise BrowserAutomationError("Failed to fetch target credentials from LastPass.")

        print_info("Launching background Chrome to bypass bot protection...")
        # Use a random port to avoid conflicts
        port = "9222"
        
        proc = subprocess.Popen([
            "open", "-n", "-g", "-a", "Google Chrome", "--args",
            f"--remote-debugging-port={port}",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}"
        ])
        
        time.sleep(5)  # Wait for Chrome to open and CDP to be ready
        
        try:
            with sync_playwright() as p:
                print_info("Connecting to background Chrome...")
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                
                print_info(f"Navigating to {self.LOGIN_URL}...")
                page.goto(self.LOGIN_URL, wait_until="networkidle")
                
                if page.locator(self.AUTH_LOGIN_FORM_SELECTOR).is_visible(timeout=5000):
                    print_info("Logging in...")
                    page.fill('input[name="username"]', username)
                    page.fill('input[name="password"]', password)
                    page.click('button[type="submit"]')
                    
                    # Wait for login to complete
                    page.wait_for_selector(self.AUTH_SUCCESS_SELECTOR, timeout=30000)
                    print_success("Logged in successfully.")
                else:
                    print_info("Already logged in.")
                    
                context.storage_state() # Ensure state is flushed to disk
        finally:
            print_info("Cleaning up background Chrome...")
            # Use lsof to find and kill the Chrome process listening on the CDP port
            os.system(f"lsof -i :{port} -t | xargs kill -9 >/dev/null 2>&1")
        
        self._auth_verified_at = time.time()

    @contextlib.contextmanager
    def cdp_session(self):
        """Context manager to yield a Playwright Page connected via CDP to background Chrome."""
        profile_dir = self._get_persistent_profile_dir()
        profile_dir.mkdir(parents=True, exist_ok=True)
        port = "9222"
        
        proc = subprocess.Popen([
            "open", "-n", "-g", "-a", "Google Chrome", "--args",
            f"--remote-debugging-port={port}",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}"
        ])
        
        time.sleep(5)  # Wait for Chrome to open and CDP to be ready
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                yield page
                context.storage_state() # Flush any storage changes to disk
        finally:
            os.system(f"lsof -i :{port} -t | xargs kill -9 >/dev/null 2>&1")
