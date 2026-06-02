import json
from pathlib import Path
import zlib
from zipfile import ZipFile

from PIL import Image
import pytest
from typer.testing import CliRunner

from google_cli.client import ClientError
from google_cli.commands import webstore as webstore_commands
from google_cli.main import app
from google_cli.browser import (
    STORE_LISTING_FIELD_LABELS,
    _assert_listing_is_editable,
    _extract_dashboard_status_text,
    _mark_file_input_script,
    _set_file_input,
    _update_text_fields_script,
)
from google_cli.models.webstore import (
    WebStoreListingUpdateResult,
    WebStoreOperationResult,
    WebStorePackageResult,
    WebStorePublishResult,
    WebStoreStatus,
    WebStoreUploadResult,
)
from google_cli.webstore_client import ChromeWebStoreClient
from google_cli.webstore_listing import parse_listing_file


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(self.text)

    def json(self):
        return self.payload


class CapturingSession:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        return FakeResponse(self.payloads.pop(0))


def make_client(session):
    return ChromeWebStoreClient(access_token="access-token", session=session)


def png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return len(payload).to_bytes(4, "big") + chunk_type + payload + checksum.to_bytes(4, "big")


def write_png(path: Path, width: int, height: int, color_type: int = 2):
    if color_type == 2:
        pixel = b"\xff\xff\xff"
    elif color_type == 6:
        pixel = b"\xff\xff\xff\xff"
    else:
        raise ValueError(f"Unsupported test PNG color type: {color_type}")

    ihdr = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08"
        + bytes([color_type])
        + b"\x00\x00\x00"
    )
    row = b"\x00" + (pixel * width)
    image_data = zlib.compress(row * height)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", image_data)
        + png_chunk(b"IEND", b"")
    )


def write_listing_fixture(root: Path, screenshot_count: int = 5):
    assets = root / "store-assets"
    assets.mkdir()
    screenshot_dir = assets / "screenshots" / "general"
    screenshot_dir.mkdir(parents=True)
    for index in range(1, screenshot_count + 1):
        write_png(screenshot_dir / f"general-{index}.png", 1280, 800)
    write_png(assets / "small-promo-440x280.png", 440, 280)
    write_png(assets / "marquee-promo-1400x560.png", 1400, 560)
    listing_file = assets / "chrome-webstore-listing.md"
    listing_file.write_text(
        """# Chrome Web Store Listing

## Product Details

Title:

```text
DemoWebClipper
```

Summary:

```text
Capture webpage screenshots and organize visual notes.
```

Detailed description:

```text
Capture webpage screenshots and organize visual notes.
```

Suggested category:

```text
Shopping
```

Language:

```text
English
```

Homepage URL:

```text
https://example.com/
```

Support URL:

```text
https://example.com/support
```

Privacy policy URL:

```text
https://example.com/privacy
```

## Graphic Assets

- Store icon: `icon128.png`
- Screenshots: `store-assets/screenshots/general/`
- Small promo tile: `store-assets/small-promo-440x280.png`
- Marquee promo image: `store-assets/marquee-promo-1400x560.png`
"""
    )
    return listing_file


def test_webstore_command_group_is_registered():
    result = CliRunner().invoke(app, ["webstore", "--help"])

    assert result.exit_code == 0
    for command_name in (
        "list",
        "package",
        "status",
        "upload",
        "upload-extension",
        "publish",
        "release",
        "listing",
        "cancel-submission",
        "rollout",
    ):
        assert command_name in result.stdout


def test_webstore_listing_command_group_is_registered():
    result = CliRunner().invoke(app, ["webstore", "listing", "--help"])

    assert result.exit_code == 0
    assert "update" in result.stdout


def test_listing_update_is_browser_session_gated():
    assert webstore_commands.LISTING_COMMAND_CREDENTIALS["update"] == ["browser_session"]


def test_parse_listing_file_validates_fields_assets_and_dimensions(tmp_path):
    listing_file = write_listing_fixture(tmp_path)

    result = parse_listing_file(listing_file)

    assert result.title == "DemoWebClipper"
    assert result.category == "Shopping"
    assert len(result.screenshots) == 5
    assert [Path(asset.path).name for asset in result.screenshots] == [
        "general-1.png",
        "general-2.png",
        "general-3.png",
        "general-4.png",
        "general-5.png",
    ]
    assert result.small_promo_tile.width == 440
    assert result.marquee_promo_image.height == 560


def test_parse_listing_file_converts_screenshots_to_required_size(tmp_path):
    listing_file = write_listing_fixture(tmp_path, screenshot_count=1)
    original = tmp_path / "store-assets" / "screenshots" / "general" / "general-1.png"
    write_png(original, 700, 886)

    result = parse_listing_file(listing_file)

    assert len(result.screenshots) == 1
    converted = result.screenshots[0]
    assert converted.width == 1280
    assert converted.height == 800
    assert Path(converted.path).name == "general-1-1280x800.png"
    assert Path(converted.path).is_file()
    with Image.open(converted.path) as image:
        assert image.mode == "RGB"


def test_parse_listing_file_converts_alpha_screenshot_even_at_required_size(tmp_path):
    listing_file = write_listing_fixture(tmp_path, screenshot_count=1)
    original = tmp_path / "store-assets" / "screenshots" / "general" / "general-1.png"
    write_png(original, 1280, 800, color_type=6)

    result = parse_listing_file(listing_file)

    assert len(result.screenshots) == 1
    converted = result.screenshots[0]
    assert converted.width == 1280
    assert converted.height == 800
    assert Path(converted.path).name == "general-1-1280x800.png"
    assert Path(converted.path).is_file()
    with Image.open(converted.path) as image:
        assert image.mode == "RGB"


def test_parse_listing_file_converts_relative_listing_path(tmp_path, monkeypatch):
    listing_file = write_listing_fixture(tmp_path, screenshot_count=1)
    original = tmp_path / "store-assets" / "screenshots" / "general" / "general-1.png"
    write_png(original, 700, 886)
    monkeypatch.chdir(tmp_path)

    result = parse_listing_file(Path("store-assets/chrome-webstore-listing.md"))

    assert len(result.screenshots) == 1
    assert Path(result.screenshots[0].path).is_absolute()
    assert Path(result.screenshots[0].path).name == "general-1-1280x800.png"


def test_parse_listing_file_rejects_missing_screenshot_directory(tmp_path):
    listing_file = write_listing_fixture(tmp_path)
    screenshot_dir = tmp_path / "store-assets" / "screenshots" / "general"
    for path in screenshot_dir.iterdir():
        path.unlink()
    screenshot_dir.rmdir()

    try:
        parse_listing_file(listing_file)
    except Exception as exc:
        assert "Screenshot directory does not exist" in str(exc)
    else:
        raise AssertionError("Expected missing screenshot directory to fail listing parsing.")


def test_parse_listing_file_rejects_more_than_five_screenshots(tmp_path):
    listing_file = write_listing_fixture(tmp_path, screenshot_count=6)

    try:
        parse_listing_file(listing_file)
    except Exception as exc:
        assert "Screenshot directory must contain no more than 5 PNG files" in str(exc)
    else:
        raise AssertionError("Expected too many screenshots to fail listing parsing.")


def test_parse_listing_file_accepts_uppercase_png_extension(tmp_path):
    listing_file = write_listing_fixture(tmp_path, screenshot_count=0)
    screenshot_dir = tmp_path / "store-assets" / "screenshots" / "general"
    write_png(screenshot_dir / "general-1.PNG", 1280, 800)

    result = parse_listing_file(listing_file)

    assert [Path(asset.path).name for asset in result.screenshots] == ["general-1.PNG"]


def test_parse_listing_file_orders_screenshots_naturally(tmp_path):
    listing_file = write_listing_fixture(tmp_path, screenshot_count=0)
    screenshot_dir = tmp_path / "store-assets" / "screenshots" / "general"
    write_png(screenshot_dir / "general-10.png", 1280, 800)
    write_png(screenshot_dir / "general-2.png", 1280, 800)

    result = parse_listing_file(listing_file)

    assert [Path(asset.path).name for asset in result.screenshots] == [
        "general-2.png",
        "general-10.png",
    ]


def test_listing_update_command_passes_listing_data_to_browser(monkeypatch, tmp_path, capsys):
    listing_file = write_listing_fixture(tmp_path)
    calls = []

    class FakeBrowser:
        def close(self):
            calls.append(("close",))

    class FakeConfig:
        def get_browser(self):
            return FakeBrowser()

    monkeypatch.setattr(webstore_commands, "get_config", lambda profile=None: FakeConfig())
    monkeypatch.setattr(
        webstore_commands,
        "update_webstore_listing",
        lambda browser, publisher_id, item_id, listing: (
            calls.append((publisher_id, item_id, listing)) or WebStoreListingUpdateResult(
                item_id=item_id,
                dashboard_url="https://chrome.google.com/webstore/devconsole/pub-123/ext-123/edit",
                updated_fields=["title", "summary"],
                uploaded_assets=listing.screenshots,
                save_status="saved",
            )
        ),
    )

    webstore_commands.update_listing(
        listing_file=listing_file,
        publisher_id="pub-123",
        item_id="ext-123",
        table=False,
        profile=None,
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["item_id"] == "ext-123"
    assert payload["save_status"] == "saved"
    assert calls[0][0:2] == ("pub-123", "ext-123")
    assert calls[0][2].title == "DemoWebClipper"
    assert calls[-1] == ("close",)


def test_store_listing_text_fields_are_dashboard_editable_fields():
    assert list(STORE_LISTING_FIELD_LABELS) == [
        "description",
        "homepage_url",
        "support_url",
    ]


def test_listing_editability_rejects_review_locked_statuses():
    class FakeService:
        def __init__(self, status):
            self.status = status

        def evaluate(self, script):
            return f"""
Store Listing
Publisher:
example-user
DemoWebClipper
Status: {self.status}
ID: mjcpgmoefpffompneljbkkndhconnnff
"""

    for status in (
        "Pending review",
        "In review",
        "Under review",
        "Submitted for review",
        "Review in progress",
    ):
        with pytest.raises(ClientError, match="not editable while review is in progress"):
            _assert_listing_is_editable(FakeService(status))


def test_text_field_update_rejects_disabled_review_field():
    from playwright.sync_api import sync_playwright

    fields = [{"name": "description", "labels": ("Description",), "value": "new value"}]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.set_content(
                """
                <label for="description">Description</label>
                <textarea id="description" disabled>old value</textarea>
                """
            )
            with pytest.raises(Exception, match="not editable"):
                page.evaluate(_update_text_fields_script(fields))
        finally:
            browser.close()


def test_file_upload_sets_each_listing_asset_individually(tmp_path):
    first = tmp_path / "one.png"
    second = tmp_path / "two.png"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    calls = []

    class FakeLocator:
        def set_input_files(self, path):
            calls.append(path)

    class FakePage:
        def __init__(self):
            self.selectors = []

        def evaluate(self, script):
            return True

        def locator(self, selector):
            self.selectors.append(selector)
            return FakeLocator()

        def wait_for_timeout(self, timeout):
            pass

    page = FakePage()

    _set_file_input(page, "screenshots", [str(first), str(second)])

    assert calls == [str(first), str(second)]
    assert page.selectors == [
        'input[type="file"][data-cws-upload-marker="cws-upload-screenshots"]',
        'input[type="file"][data-cws-upload-marker="cws-upload-screenshots"]',
    ]


def marked_file_inputs(html: str, section_name: str) -> list[dict]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.set_content(html)
            page.evaluate(_mark_file_input_script(section_name, "asset-marker"))
            return page.evaluate(
                """() => Array.from(document.querySelectorAll('input[type="file"]')).map((input, index) => ({
                    index,
                    id: input.id,
                    marked: input.getAttribute('data-cws-upload-marker'),
                }))"""
            )
        finally:
            browser.close()


def test_file_input_marker_targets_nearest_promo_section():
    marked = marked_file_inputs(
        """
        <section>
          <div>
            <div class="promo-grid">
              <article>
                <h3>Small promo tile</h3>
                <p>440x280 Canvas</p>
                <input id="small" type="file" accept=".png,.jpg,.jpeg">
              </article>
              <article>
                <h3>Marquee promo tile</h3>
                <p>1400x560 Canvas</p>
                <input id="marquee" type="file" accept=".png,.jpg,.jpeg">
              </article>
            </div>
          </div>
        </section>
        """,
        "small promo",
    )

    assert marked == [
        {"index": 0, "id": "small", "marked": "asset-marker"},
        {"index": 1, "id": "marquee", "marked": None},
    ]


def test_file_input_marker_ignores_hidden_template_input():
    marked = marked_file_inputs(
        """
        <section>
          <article>
            <h3>Small promo tile</h3>
            <div hidden>
              <input id="template" type="file" accept=".png,.jpg,.jpeg">
            </div>
            <div>
              <input id="active" type="file" accept=".png,.jpg,.jpeg">
            </div>
          </article>
        </section>
        """,
        "small promo",
    )

    assert marked == [
        {"index": 0, "id": "template", "marked": None},
        {"index": 1, "id": "active", "marked": "asset-marker"},
    ]


def test_file_input_marker_clears_stale_markers():
    marked = marked_file_inputs(
        """
        <section>
          <article>
            <h3>Old upload control</h3>
            <input id="stale" type="file" data-cws-upload-marker="asset-marker">
          </article>
          <article>
            <h3>Small promo tile</h3>
            <input id="active" type="file" accept=".png,.jpg,.jpeg">
          </article>
        </section>
        """,
        "small promo",
    )

    assert marked == [
        {"index": 0, "id": "stale", "marked": None},
        {"index": 1, "id": "active", "marked": "asset-marker"},
    ]


def test_extract_dashboard_status_text_parses_pending_review():
    body_text = """
Store Listing
Publisher:
example-user
DemoWebClipper
Status: Pending review
ID: mjcpgmoefpffompneljbkkndhconnnff
"""

    assert _extract_dashboard_status_text(body_text) == "Pending review"


def test_package_command_creates_webstore_zip_with_manifest_at_root(tmp_path):
    extension_dir = tmp_path / "extension"
    extension_dir.mkdir()
    (extension_dir / "manifest.json").write_text(
        json.dumps({"manifest_version": 3, "name": "DemoWebClipper", "version": "1.2.3"})
    )
    (extension_dir / "popup.html").write_text("<html></html>")
    (extension_dir / "package.json").write_text("{}")
    (extension_dir / "tests").mkdir()
    (extension_dir / "tests" / "extension.test.js").write_text("test")
    (extension_dir / "scripts").mkdir()
    (extension_dir / "scripts" / "release.js").write_text("script")
    (extension_dir / "dist").mkdir()
    (extension_dir / "dist" / "old.zip").write_bytes(b"old")
    (extension_dir / "_temp").mkdir()
    (extension_dir / "_temp" / "scratch.txt").write_text("scratch")
    (extension_dir / "agent_workspaces").mkdir()
    (extension_dir / "agent_workspaces" / "report.json").write_text("{}")
    (extension_dir / "store-assets").mkdir()
    (extension_dir / "store-assets" / "listing.md").write_text("listing")
    output_dir = tmp_path / "release"

    result = CliRunner().invoke(
        app,
        [
            "webstore",
            "package",
            str(extension_dir),
            "--output-dir",
            str(output_dir),
            "--exclude",
            "scripts/**",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "zip_path": str(output_dir / "DemoWebClipper-1.2.3.zip"),
        "manifest_name": "DemoWebClipper",
        "manifest_version": "1.2.3",
        "file_count": 2,
        "files": ["manifest.json", "popup.html"],
    }
    with ZipFile(payload["zip_path"]) as release_zip:
        assert release_zip.namelist() == ["manifest.json", "popup.html"]


def test_package_command_runs_verify_command_before_creating_zip(tmp_path):
    extension_dir = tmp_path / "extension"
    extension_dir.mkdir()
    marker = tmp_path / "verified.txt"
    (extension_dir / "manifest.json").write_text(
        json.dumps({"manifest_version": 3, "name": "DemoWebClipper", "version": "1.2.3"})
    )

    result = CliRunner().invoke(
        app,
        [
            "webstore",
            "package",
            str(extension_dir),
            "--output-dir",
            str(tmp_path / "release"),
            "--verify-command",
            f"python -c \"from pathlib import Path; Path('{marker}').write_text('ok')\"",
        ],
    )

    assert result.exit_code == 0
    assert marker.read_text() == "ok"


def test_package_command_rejects_remote_hosted_scripts(tmp_path):
    extension_dir = tmp_path / "extension"
    extension_dir.mkdir()
    (extension_dir / "manifest.json").write_text(
        json.dumps({"manifest_version": 3, "name": "DemoWebClipper", "version": "1.2.3"})
    )
    (extension_dir / "popup.html").write_text(
        '<script src="https://cdn.example.com/remote.js"></script>'
    )

    result = CliRunner().invoke(
        app,
        [
            "webstore",
            "package",
            str(extension_dir),
            "--output-dir",
            str(tmp_path / "release"),
        ],
    )

    assert result.exit_code == 1
    assert "Remote hosted script source found in popup.html" in result.stderr


def test_release_command_packages_uploads_and_publishes(monkeypatch, tmp_path):
    extension_dir = tmp_path / "extension"
    extension_dir.mkdir()
    (extension_dir / "manifest.json").write_text(
        json.dumps({"manifest_version": 3, "name": "DemoWebClipper", "version": "1.2.3"})
    )
    calls = []

    class FakeClient:
        def upload_package(self, publisher_id, item_id, package):
            calls.append(("upload", publisher_id, item_id, package.name))
            assert Path(package).exists()
            return WebStoreUploadResult(
                name="publishers/pub-123/items/ext-123",
                item_id="ext-123",
                crx_version="1.2.3",
                upload_state="UPLOAD_STATE_SUCCESS",
            )

        def publish_item(
            self,
            publisher_id,
            item_id,
            publish_type,
            deploy_percentage,
            skip_review,
        ):
            calls.append(
                (
                    "publish",
                    publisher_id,
                    item_id,
                    publish_type,
                    deploy_percentage,
                    skip_review,
                )
            )
            return WebStorePublishResult(
                name="publishers/pub-123/items/ext-123",
                item_id="ext-123",
                state="ITEM_STATE_PENDING_REVIEW",
            )

    monkeypatch.setattr(webstore_commands, "get_client", lambda profile=None: FakeClient())

    result = CliRunner().invoke(
        app,
        [
            "webstore",
            "release",
            str(extension_dir),
            "--output-dir",
            str(tmp_path / "release"),
            "--publisher-id",
            "pub-123",
            "--item-id",
            "ext-123",
            "--publish-type",
            "STAGED_PUBLISH",
            "--deploy-percentage",
            "25",
            "--skip-review",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "package": {
            "zip_path": str(tmp_path / "release" / "DemoWebClipper-1.2.3.zip"),
            "manifest_name": "DemoWebClipper",
            "manifest_version": "1.2.3",
            "file_count": 1,
            "files": ["manifest.json"],
        },
        "upload": {
            "name": "publishers/pub-123/items/ext-123",
            "item_id": "ext-123",
            "crx_version": "1.2.3",
            "upload_state": "UPLOAD_STATE_SUCCESS",
        },
        "publish": {
            "name": "publishers/pub-123/items/ext-123",
            "item_id": "ext-123",
            "state": "ITEM_STATE_PENDING_REVIEW",
        },
    }
    assert calls == [
        ("upload", "pub-123", "ext-123", "DemoWebClipper-1.2.3.zip"),
        ("publish", "pub-123", "ext-123", "STAGED_PUBLISH", 25, True),
    ]


def test_upload_extension_command_packages_and_uploads(monkeypatch, tmp_path):
    extension_dir = tmp_path / "extension"
    extension_dir.mkdir()
    (extension_dir / "manifest.json").write_text(
        json.dumps({"manifest_version": 3, "name": "DemoWebClipper", "version": "1.2.3"})
    )

    class FakeClient:
        def upload_package(self, publisher_id, item_id, package):
            assert publisher_id == "pub-123"
            assert item_id == "ext-123"
            assert package == tmp_path / "release" / "DemoWebClipper-1.2.3.zip"
            return WebStoreUploadResult(
                name="publishers/pub-123/items/ext-123",
                item_id="ext-123",
                crx_version="1.2.3",
                upload_state="UPLOAD_STATE_SUCCESS",
            )

    monkeypatch.setattr(webstore_commands, "get_client", lambda profile=None: FakeClient())

    result = CliRunner().invoke(
        app,
        [
            "webstore",
            "upload-extension",
            str(extension_dir),
            "--output-dir",
            str(tmp_path / "release"),
            "--publisher-id",
            "pub-123",
            "--item-id",
            "ext-123",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "package": {
            "zip_path": str(tmp_path / "release" / "DemoWebClipper-1.2.3.zip"),
            "manifest_name": "DemoWebClipper",
            "manifest_version": "1.2.3",
            "file_count": 1,
            "files": ["manifest.json"],
        },
        "upload": {
            "name": "publishers/pub-123/items/ext-123",
            "item_id": "ext-123",
            "crx_version": "1.2.3",
            "upload_state": "UPLOAD_STATE_SUCCESS",
        },
    }


def test_status_command_reads_ids_from_environment(monkeypatch):
    class FakeClient:
        def fetch_status(self, publisher_id, item_id):
            assert publisher_id == "pub-from-env"
            assert item_id == "ext-from-env"
            return WebStoreStatus(
                name="publishers/pub-from-env/items/ext-from-env",
                item_id="ext-from-env",
                taken_down=False,
                warned=False,
            )

    monkeypatch.setenv("CWS_PUBLISHER_ID", "pub-from-env")
    monkeypatch.setenv("CWS_EXTENSION_ID", "ext-from-env")
    monkeypatch.setattr(webstore_commands, "get_client", lambda profile=None: FakeClient())

    result = CliRunner().invoke(app, ["webstore", "status"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "name": "publishers/pub-from-env/items/ext-from-env",
        "item_id": "ext-from-env",
        "public_key": None,
        "published_item_revision_status": None,
        "submitted_item_revision_status": None,
        "last_async_upload_state": None,
        "taken_down": False,
        "warned": False,
    }


def test_list_command_reads_configured_item_and_outputs_array(monkeypatch):
    class FakeClient:
        def fetch_status(self, publisher_id, item_id):
            assert publisher_id == "pub-from-env"
            assert item_id == "ext-from-env"
            return WebStoreStatus(
                name="publishers/pub-from-env/items/ext-from-env",
                item_id="ext-from-env",
                taken_down=False,
                warned=False,
            )

    monkeypatch.setenv("CWS_PUBLISHER_ID", "pub-from-env")
    monkeypatch.setenv("CWS_EXTENSION_ID", "ext-from-env")
    monkeypatch.setattr(webstore_commands, "get_client", lambda profile=None: FakeClient())

    result = CliRunner().invoke(
        app,
        ["webstore", "list", "--properties", "item_id,warned"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"item_id": "ext-from-env", "warned": False}]


def test_status_command_reads_ids_from_profile_env(monkeypatch):
    class FakeClient:
        def fetch_status(self, publisher_id, item_id):
            assert publisher_id == "pub-from-profile"
            assert item_id == "ext-from-profile"
            return WebStoreStatus(
                name="publishers/pub-from-profile/items/ext-from-profile",
                item_id="ext-from-profile",
                taken_down=False,
                warned=False,
            )

    class FakeConfig:
        def _get(self, name):
            return {
                "CWS_PUBLISHER_ID": "pub-from-profile",
                "CWS_EXTENSION_ID": "ext-from-profile",
            }.get(name)

    monkeypatch.delenv("CWS_PUBLISHER_ID", raising=False)
    monkeypatch.delenv("CWS_EXTENSION_ID", raising=False)
    monkeypatch.setattr(webstore_commands, "get_config", lambda profile=None: FakeConfig())
    monkeypatch.setattr(webstore_commands, "get_client", lambda profile=None: FakeClient())

    result = CliRunner().invoke(app, ["webstore", "status"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["item_id"] == "ext-from-profile"


def test_fetch_status_uses_v2_endpoint_and_returns_model():
    session = CapturingSession(
        {
            "name": "publishers/pub-123/items/ext-123",
            "itemId": "ext-123",
            "publishedItemRevisionStatus": {
                "state": "ITEM_STATE_PUBLISHED",
                "distributionChannels": [
                    {"deployPercentage": 100, "crxVersion": "1.2.3"}
                ],
            },
            "takenDown": False,
            "warned": False,
        }
    )
    client = make_client(session)

    result = client.fetch_status("pub-123", "ext-123")

    assert isinstance(result, WebStoreStatus)
    assert result.item_id == "ext-123"
    assert result.published_item_revision_status.state == "ITEM_STATE_PUBLISHED"
    assert session.requests == [
        {
            "method": "GET",
            "url": "https://chromewebstore.googleapis.com/v2/publishers/pub-123/items/ext-123:fetchStatus",
            "headers": {"Authorization": "Bearer access-token"},
        }
    ]


def test_upload_package_uses_upload_endpoint_and_zip_bytes(tmp_path):
    package_path = tmp_path / "extension.zip"
    package_path.write_bytes(b"zip-bytes")
    session = CapturingSession(
        {
            "name": "publishers/pub-123/items/ext-123",
            "itemId": "ext-123",
            "crxVersion": "1.2.4",
            "uploadState": "UPLOAD_STATE_SUCCESS",
        }
    )
    client = make_client(session)

    result = client.upload_package("pub-123", "ext-123", package_path)

    assert isinstance(result, WebStoreUploadResult)
    assert result.upload_state == "UPLOAD_STATE_SUCCESS"
    assert session.requests == [
        {
            "method": "POST",
            "url": "https://chromewebstore.googleapis.com/upload/v2/publishers/pub-123/items/ext-123:upload",
            "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/zip",
            },
            "data": b"zip-bytes",
        }
    ]


def test_publish_item_sends_publish_type_rollout_and_skip_review():
    session = CapturingSession(
        {
            "name": "publishers/pub-123/items/ext-123",
            "itemId": "ext-123",
            "state": "ITEM_STATE_PENDING_REVIEW",
        }
    )
    client = make_client(session)

    result = client.publish_item(
        "pub-123",
        "ext-123",
        publish_type="STAGED_PUBLISH",
        deploy_percentage=25,
        skip_review=True,
    )

    assert isinstance(result, WebStorePublishResult)
    assert result.state == "ITEM_STATE_PENDING_REVIEW"
    assert session.requests == [
        {
            "method": "POST",
            "url": "https://chromewebstore.googleapis.com/v2/publishers/pub-123/items/ext-123:publish",
            "headers": {"Authorization": "Bearer access-token"},
            "json": {
                "publishType": "STAGED_PUBLISH",
                "deployInfos": [{"deployPercentage": 25}],
                "skipReview": True,
            },
        }
    ]


def test_rollout_uses_set_published_deploy_percentage_endpoint():
    session = CapturingSession({})
    client = make_client(session)

    result = client.set_published_deploy_percentage("pub-123", "ext-123", 100)

    assert isinstance(result, WebStoreOperationResult)
    assert result.action == "setPublishedDeployPercentage"
    assert result.success is True
    assert session.requests == [
        {
            "method": "POST",
            "url": "https://chromewebstore.googleapis.com/v2/publishers/pub-123/items/ext-123:setPublishedDeployPercentage",
            "headers": {"Authorization": "Bearer access-token"},
            "json": {"deployPercentage": 100},
        }
    ]


def test_publish_command_outputs_publish_result(monkeypatch):
    class FakeClient:
        def publish_item(
            self,
            publisher_id,
            item_id,
            publish_type,
            deploy_percentage,
            skip_review,
        ):
            assert publisher_id == "pub-123"
            assert item_id == "ext-123"
            assert publish_type == "STAGED_PUBLISH"
            assert deploy_percentage == 25
            assert skip_review is True
            return WebStorePublishResult(
                name="publishers/pub-123/items/ext-123",
                item_id="ext-123",
                state="ITEM_STATE_PENDING_REVIEW",
            )

    monkeypatch.setattr(webstore_commands, "get_client", lambda profile=None: FakeClient())

    result = CliRunner().invoke(
        app,
        [
            "webstore",
            "publish",
            "--publisher-id",
            "pub-123",
            "--item-id",
            "ext-123",
            "--publish-type",
            "STAGED_PUBLISH",
            "--deploy-percentage",
            "25",
            "--skip-review",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "name": "publishers/pub-123/items/ext-123",
        "item_id": "ext-123",
        "state": "ITEM_STATE_PENDING_REVIEW",
    }


def test_upload_command_passes_package_path(monkeypatch, tmp_path):
    package_path = tmp_path / "extension.zip"
    package_path.write_bytes(b"zip-bytes")

    class FakeClient:
        def upload_package(self, publisher_id, item_id, package):
            assert publisher_id == "pub-123"
            assert item_id == "ext-123"
            assert package == Path(package_path)
            return WebStoreUploadResult(
                name="publishers/pub-123/items/ext-123",
                item_id="ext-123",
                crx_version="1.2.4",
                upload_state="UPLOAD_STATE_SUCCESS",
            )

    monkeypatch.setattr(webstore_commands, "get_client", lambda profile=None: FakeClient())

    result = CliRunner().invoke(
        app,
        [
            "webstore",
            "upload",
            "--publisher-id",
            "pub-123",
            "--item-id",
            "ext-123",
            str(package_path),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "name": "publishers/pub-123/items/ext-123",
        "item_id": "ext-123",
        "crx_version": "1.2.4",
        "upload_state": "UPLOAD_STATE_SUCCESS",
    }
