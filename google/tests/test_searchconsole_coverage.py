from __future__ import annotations

import json
import zipfile

from typer.testing import CliRunner

from google_cli.main import app


SAMPLE_FILES = {
    "Metadata.csv": "Property,Value\nSitemap,All known pages",
    "Chart.csv": (
        "Date,Not indexed,Indexed,Impressions\n"
        "2026-07-20,,,39391\n"
        "2026-07-23,3488,1297,42226\n"
        "2026-10-11,783,1325,28623\n"
    ),
    "Critical issues.csv": (
        "Reason,Source,Validation,Pages\n"
        "Page with redirect,Website,Not Started,145\n"
        "Not found (404),Website,Not Started,128\n"
        "Excluded by ‘noindex’ tag,Website,Not Started,110\n"
        '"Duplicate, Google chose different canonical than user",'
        "Google systems,Not Started,2\n"
    ),
    "Non-critical issues.csv": "Reason,Source,Validation,Pages",
}

DRILLDOWN_FILES = {
    "Metadata.csv": (
        "Property,Value\n"
        "Sitemap,All known pages\n"
        "Issue,Crawled - currently not indexed"
    ),
    "Chart.csv": (
        "Date,Affected pages\n"
        "2026-07-23,2\n"
        "2026-10-11,2\n"
    ),
    "Table.csv": (
        "URL,Last crawled\n"
        "http://example.com//one/,2026-10-11\n"
        "https://example.com/two/,2026-10-10\n"
    ),
}


def _write_directory(tmp_path, files):
    export_dir = tmp_path / "coverage-export"
    export_dir.mkdir()
    for name, content in files.items():
        (export_dir / name).write_text(content, encoding="utf-8")
    return export_dir


def _write_zip(tmp_path, files):
    export_zip = tmp_path / "coverage-export.zip"
    with zipfile.ZipFile(export_zip, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return export_zip


def _invoke(path, *extra_args):
    return CliRunner().invoke(
        app,
        ["searchconsole", "coverage", "parse", str(path), *extra_args],
    )


def test_parse_zip_outputs_structured_payload(tmp_path):
    export_zip = _write_zip(tmp_path, SAMPLE_FILES)

    result = _invoke(export_zip)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["source"] == str(export_zip)
    assert payload["metadata"] == [{"property": "Sitemap", "value": "All known pages"}]
    assert payload["latest"] == {
        "date": "2026-10-11",
        "not_indexed": 783,
        "indexed": 1325,
        "impressions": 28623,
    }
    assert payload["chart"][0] == {
        "date": "2026-07-20",
        "not_indexed": None,
        "indexed": None,
        "impressions": 39391,
    }
    assert payload["critical_issues"][2]["reason"] == "Excluded by ‘noindex’ tag"
    assert payload["critical_issues"][3]["reason"] == (
        "Duplicate, Google chose different canonical than user"
    )
    assert payload["non_critical_issues"] == []
    assert payload["totals"] == {"critical_pages": 385, "non_critical_pages": 0}


def test_parse_directory_input(tmp_path):
    export_dir = _write_directory(tmp_path, SAMPLE_FILES)

    result = _invoke(export_dir)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["latest"]["not_indexed"] == 783
    assert payload["latest"]["indexed"] == 1325


def test_parse_non_critical_issues(tmp_path):
    files = dict(SAMPLE_FILES)
    files["Non-critical issues.csv"] = (
        "Reason,Source,Validation,Pages\n"
        "Page indexed without content,Google systems,N/A,2\n"
    )

    result = _invoke(_write_zip(tmp_path, files))

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["non_critical_issues"] == [{
        "reason": "Page indexed without content",
        "source": "Google systems",
        "validation": "N/A",
        "pages": 2,
    }]
    assert payload["totals"]["non_critical_pages"] == 2


def test_parse_table_output(tmp_path):
    export_zip = _write_zip(tmp_path, SAMPLE_FILES)

    result = _invoke(export_zip, "--table")

    assert result.exit_code == 0, result.output
    assert "Page with redirect" in result.stdout
    assert "783" in result.stdout
    assert "Impressions" in result.stdout


def test_parse_missing_file_fails(tmp_path):
    files = dict(SAMPLE_FILES)
    del files["Chart.csv"]

    result = _invoke(_write_zip(tmp_path, files))

    assert result.exit_code != 0
    assert "Chart.csv" in result.output


def test_parse_missing_header_fails(tmp_path):
    files = dict(SAMPLE_FILES)
    files["Chart.csv"] = (
        "Date,Indexed,Impressions\n"
        "2026-10-11,1325,28623\n"
    )

    result = _invoke(_write_zip(tmp_path, files))

    assert result.exit_code != 0
    assert "Not indexed" in result.output


def test_parse_bad_numeric_value_fails(tmp_path):
    files = dict(SAMPLE_FILES)
    files["Chart.csv"] = (
        "Date,Not indexed,Indexed,Impressions\n"
        "2026-10-11,not-a-number,1325,28623\n"
    )

    result = _invoke(_write_zip(tmp_path, files))

    assert result.exit_code != 0
    assert "row 2" in result.output
    assert "Not indexed" in result.output


def test_parse_invalid_date_fails(tmp_path):
    files = dict(SAMPLE_FILES)
    files["Chart.csv"] = (
        "Date,Not indexed,Indexed,Impressions\n"
        "10/11/2026,783,1325,28623\n"
    )

    result = _invoke(_write_zip(tmp_path, files))

    assert result.exit_code != 0
    assert "YYYY-MM-DD" in result.output


def test_parse_duplicate_member_name_fails(tmp_path):
    export_zip = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(export_zip, "w") as archive:
        for name, content in SAMPLE_FILES.items():
            archive.writestr(name, content)
        archive.writestr("nested/Chart.csv", SAMPLE_FILES["Chart.csv"])

    result = _invoke(export_zip)

    assert result.exit_code != 0
    assert "more than one Chart.csv" in result.output


def test_parse_drilldown_outputs_url_rows(tmp_path):
    export_zip = _write_zip(tmp_path, DRILLDOWN_FILES)

    result = _invoke(export_zip)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["kind"] == "drilldown"
    assert payload["issue"] == "Crawled - currently not indexed"
    assert payload["latest"] == {"date": "2026-10-11", "affected_pages": 2}
    assert payload["chart"] == [
        {"date": "2026-07-23", "affected_pages": 2},
        {"date": "2026-10-11", "affected_pages": 2},
    ]
    assert payload["table"] == [
        {"url": "http://example.com//one/", "last_crawled": "2026-10-11"},
        {"url": "https://example.com/two/", "last_crawled": "2026-10-10"},
    ]
    assert payload["totals"] == {"row_count": 2, "unique_url_count": 2}


def test_parse_drilldown_directory_input(tmp_path):
    export_dir = _write_directory(tmp_path, DRILLDOWN_FILES)

    result = _invoke(export_dir)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["kind"] == "drilldown"
    assert payload["totals"]["row_count"] == 2


def test_parse_drilldown_table_output(tmp_path):
    export_zip = _write_zip(tmp_path, DRILLDOWN_FILES)

    result = _invoke(export_zip, "--table")

    assert result.exit_code == 0, result.output
    assert "Crawled - currently not indexed" in result.stdout
    assert "http://example.com//one/" in result.stdout
    assert "Last Crawled" in result.stdout


def test_parse_drilldown_missing_table_fails(tmp_path):
    files = dict(DRILLDOWN_FILES)
    del files["Table.csv"]

    result = _invoke(_write_zip(tmp_path, files))

    assert result.exit_code != 0
    assert "Drilldown export" in result.output
    assert "Table.csv" in result.output


def test_parse_drilldown_missing_url_header_fails(tmp_path):
    files = dict(DRILLDOWN_FILES)
    files["Table.csv"] = "Page,Last crawled\nhttps://example.com/,2026-10-11\n"

    result = _invoke(_write_zip(tmp_path, files))

    assert result.exit_code != 0
    assert "Table.csv" in result.output
    assert "URL" in result.output


def test_parse_drilldown_invalid_last_crawled_fails(tmp_path):
    files = dict(DRILLDOWN_FILES)
    files["Table.csv"] = "URL,Last crawled\nhttps://example.com/,10/11/2026\n"

    result = _invoke(_write_zip(tmp_path, files))

    assert result.exit_code != 0
    assert "Last crawled" in result.output
    assert "YYYY-MM-DD" in result.output
