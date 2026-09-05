"""Site-wide shoutout commands for ATA Blog CLI.

The theme prints one ACF options record (`site_ad_settings`) above the body of
every single post through `template-parts/content/block-sitead.php`. That record
holds the sponsor logo, the sponsor text, the click-through link, and the
display/border switches. It is site-wide: there is no per-post variant.

Reads and writes run ACF's own `get_field`/`update_field` through wp-cli over the
WP Engine SSH connection. The ACF REST write path is unusable because
acf-to-rest-api 3.3.4 resolves option field groups with
`acf_get_field_groups(['post_id' => 'options'])`, which returns no groups on ACF
Pro 6.8, so every REST write answers `cant_update_item`. Reading over SSH also
avoids the Cloudflare edge cache, so the post-write readback is always the real
stored value.
"""
import base64
import json
import shlex
import subprocess
from pathlib import Path
from typing import Optional

import typer
from cli_tools_shared.output import command, print_json, print_table

from ..config import get_config

COMMAND_CREDENTIALS = {
    "get": ["custom"],
    "set": ["custom"],
}

app = typer.Typer(help="Manage the site-wide shoutout above post bodies", no_args_is_help=True)

# ACF options record read by template-parts/content/block-sitead.php.
SITE_AD_FIELD = "site_ad_settings"

SSH_TIMEOUT_SECONDS = 60

# Placeholders replaced before each run. PHP source is full of braces, so these
# scripts use replacement rather than str.format().
FIELD_TOKEN = "__ATA_FIELD__"
UPDATES_TOKEN = "__ATA_UPDATES_B64__"

# Shared PHP prelude: resolve the ACF group, then read its raw sub-values into a
# name-indexed array with the types the sub-field definitions declare.
PHP_PRELUDE = """<?php
$name = '__ATA_FIELD__';
$groupKey = get_option('_options_' . $name);
if (!$groupKey) {
    fwrite(STDERR, "ACF field key not found for " . $name . "\\n");
    exit(1);
}
$group = acf_get_field($groupKey);
if (!is_array($group) || $group['type'] !== 'group' || !is_array($group['sub_fields'])) {
    fwrite(STDERR, "ACF field " . $name . " is not a group field\\n");
    exit(1);
}
function ata_read_site_ad($name, $group) {
    $raw = get_field($name, 'option', false);
    if (!is_array($raw)) {
        fwrite(STDERR, "ACF field " . $name . " returned no stored values\\n");
        exit(1);
    }
    $out = array();
    foreach ($group['sub_fields'] as $sub) {
        $value = array_key_exists($sub['key'], $raw) ? $raw[$sub['key']] : null;
        if ($sub['type'] === 'true_false') {
            $out[$sub['name']] = (bool) intval($value);
        } elseif ($sub['type'] === 'image') {
            $out[$sub['name']] = ($value === null || $value === '') ? null : (int) $value;
        } else {
            $out[$sub['name']] = (string) $value;
        }
    }
    return $out;
}
"""

PHP_READ = PHP_PRELUDE + """
$current = ata_read_site_ad($name, $group);
$current['logo_url'] = $current['logo'] ? wp_get_attachment_url($current['logo']) : null;
echo json_encode($current);
"""

PHP_WRITE = PHP_PRELUDE + """
$updates = json_decode(base64_decode('__ATA_UPDATES_B64__'), true);
if (!is_array($updates) || count($updates) === 0) {
    fwrite(STDERR, "No sub-field updates were supplied\\n");
    exit(1);
}
$before = ata_read_site_ad($name, $group);
$merged = $before;
foreach ($updates as $key => $value) {
    if (!array_key_exists($key, $merged)) {
        fwrite(STDERR, "Unknown sub-field: " . $key . "\\n");
        exit(1);
    }
    $merged[$key] = $value;
}
$payload = $merged;
if ($payload['logo'] === null) {
    $payload['logo'] = '';
}
update_field($groupKey, $payload, 'option');
$after = ata_read_site_ad($name, $group);
$after['logo_url'] = $after['logo'] ? wp_get_attachment_url($after['logo']) : null;
echo json_encode(array('before' => $before, 'after' => $after));
"""


def _run_wp(wp_command: str, script: Optional[str] = None) -> str:
    """Run a wp-cli command on the WP Engine host and return its stdout."""
    config = get_config()
    identity_file = Path(config.wpengine_ssh_identity_file).expanduser()
    if not identity_file.is_file():
        raise typer.BadParameter(f"SSH identity file does not exist: {identity_file}")

    destination = f"{config.wpengine_ssh_user}@{config.wpengine_ssh_host}"
    remote = f"cd {shlex.quote(config.wpengine_site_path)} && {wp_command}"
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-i", str(identity_file), destination, remote],
        input=script if script is not None else "",
        capture_output=True,
        text=True,
        timeout=SSH_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{wp_command} failed: {result.stderr.strip()}")
    return result.stdout


def _run_php(script: str) -> dict:
    """Run a PHP script through wp-cli on the WP Engine host and return its JSON."""
    return json.loads(_run_wp("wp eval-file -", script))


def _flush_page_cache() -> str:
    """Flush the WP Engine page cache and the WordPress object cache."""
    return _run_wp("wp page-cache flush && wp cache flush").strip()


def _read_site_ad(field: str = SITE_AD_FIELD) -> dict:
    """Return the stored site-wide shoutout record."""
    return _run_php(PHP_READ.replace(FIELD_TOKEN, field))


def _write_site_ad(updates: dict, field: str = SITE_AD_FIELD) -> dict:
    """Apply sub-field updates and return the before/after records."""
    payload = base64.b64encode(json.dumps(updates).encode("utf-8")).decode("ascii")
    script = PHP_WRITE.replace(FIELD_TOKEN, field).replace(UPDATES_TOKEN, payload)
    return _run_php(script)


def _print_record(record: dict, table: bool) -> None:
    """Print a record, deriving table columns from the ACF sub-fields it holds."""
    if table:
        columns = list(record)
        headers = [column.replace("_", " ").title() for column in columns]
        print_table([record], columns, headers)
    else:
        print_json(record)


@app.command("get")
@command
def get_site_shoutout(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
) -> None:
    """Get the site-wide shoutout shown above every post body.

    Examples:
        ata-blog shoutouts site get
        ata-blog shoutouts site get --table
    """
    try:
        record = _read_site_ad()
    except Exception as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1)

    _print_record(record, table)


@app.command("set")
@command
def set_site_shoutout(
    text: Optional[str] = typer.Option(None, "--text", help="Shoutout HTML shown next to the logo"),
    link: Optional[str] = typer.Option(None, "--link", help="Logo click-through URL"),
    logo: Optional[int] = typer.Option(None, "--logo", help="Logo media attachment ID from `ata-blog media upload`"),
    display: Optional[bool] = typer.Option(None, "--display/--no-display", help="Show or hide the placement"),
    border: Optional[bool] = typer.Option(None, "--border/--no-border", help="Show or hide the dashed bottom border"),
    cache_clear: bool = typer.Option(True, "--cache-clear/--no-cache-clear", help="Flush the WP Engine page cache after the write"),
    table: bool = typer.Option(False, "--table", "-t", help="Display the new record as table"),
) -> None:
    """Create or update the site-wide shoutout shown above every post body.

    Only the supplied options change. Every other sub-field keeps its stored
    value. The command reads the record back after the write and reports it.

    Examples:
        ata-blog shoutouts site set --text 'Audit AD with <a href="https://example.com">Example</a>.'
        ata-blog shoutouts site set --logo 27000 --link https://example.com/product
        ata-blog shoutouts site set --no-display
    """
    supplied = {"text": text, "link": link, "logo": logo, "display": display, "border": border}
    updates = {key: value for key, value in supplied.items() if value is not None}
    if not updates:
        typer.echo(
            "Error: supply at least one of --text, --link, --logo, --display/--no-display, "
            "or --border/--no-border",
            err=True,
        )
        raise typer.Exit(1)

    try:
        result = _write_site_ad(updates)
    except Exception as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1)

    after = result["after"]
    for key, value in updates.items():
        if after[key] != value:
            typer.echo(
                f"Error: readback mismatch for {key}: requested {value!r}, stored {after[key]!r}",
                err=True,
            )
            raise typer.Exit(1)

    if cache_clear:
        try:
            _flush_page_cache()
        except Exception as error:
            typer.echo(f"Error: write succeeded but cache flush failed: {error}", err=True)
            raise typer.Exit(1)

    typer.echo(f"Site shoutout updated: {', '.join(sorted(updates))}", err=True)
    _print_record(after, table)
