"""Regression tests for --filter on the FreshBooks list commands.

Covers the defect where ``freshbooks customer list --filter organization:like:n8n``
returned ``[]`` and exited 0 for a customer that provably exists, so a caller
read the empty result as "no such customer" instead of as a wrong answer.

Two independent causes are pinned here:

1. ``like`` is SQL LIKE (anchored, ``%`` is the wildcard), so the substring form
   needs ``%n8n%`` or the ``contains`` operator. The command's own ``--help``
   documented the unusable bare form.
2. The command fetched a single page sized to ``--limit`` and filtered that page,
   so a match on a later page reported as no match at all.

Plus the unsupported-field case, which used to return ``[]`` instead of failing.
"""
import json

import pytest
from typer.testing import CliRunner

from freshbooks_cli.commands import customer as customer_commands
from freshbooks_cli.filter_map import search_literal

runner = CliRunner()

N8N = {
    "id": 425417,
    "organization": "n8n GmbH",
    "fname": "N8N",
    "lname": "Billing",
    "email": "billing@n8n.io",
}
OUTPOST = {
    "id": 292143,
    "organization": "Outpost24 Inc.",
    "fname": "Ada",
    "lname": "Lovelace",
    "email": "ap@outpost24.com",
}
SAAS_GROUP = {
    "id": 409091,
    "organization": "SaaS.group GmbH",
    "fname": "Sam",
    "lname": "Group",
    "email": "billing@saas.group",
}


class FakeClient:
    """Stands in for FreshBooksClient and records how it was called."""

    def __init__(self, records):
        self.records = records
        self.calls = []

    def get_clients(self, search_params=None, max_records=None):
        self.calls.append({"search_params": search_params, "max_records": max_records})
        if max_records is None:
            return list(self.records)
        return list(self.records)[:max_records]


@pytest.fixture
def fake_client(monkeypatch):
    """Install a FakeClient and hand it back so tests can assert on its calls."""
    holder = {}

    def install(records):
        client = FakeClient(records)
        monkeypatch.setattr(customer_commands, "get_client", lambda: client)
        holder["client"] = client
        return client

    install.holder = holder
    return install


def run_list(*args):
    result = runner.invoke(customer_commands.app, ["list", *args])
    return result


def ids_from(result):
    assert result.exit_code == 0, result.output
    return [record["id"] for record in json.loads(result.output)]


# ---- like: SQL LIKE semantics, and the forms that actually find n8n ----

def test_like_without_wildcards_is_anchored_not_substring(fake_client):
    """The exact reported command. 'like' is SQL LIKE, so a bare value is an
    anchored case-insensitive exact match and must not match 'n8n GmbH'."""
    fake_client([N8N, OUTPOST, SAAS_GROUP])

    assert ids_from(run_list("--filter", "organization:like:n8n")) == []


def test_like_with_wildcards_finds_n8n(fake_client):
    """organization:like:%n8n% is the documented substring form and must return
    customer 425417."""
    fake_client([N8N, OUTPOST, SAAS_GROUP])

    assert ids_from(run_list("--filter", "organization:like:%n8n%")) == [425417]


def test_contains_finds_n8n(fake_client):
    fake_client([N8N, OUTPOST, SAAS_GROUP])

    assert ids_from(run_list("--filter", "organization:contains:n8n")) == [425417]


def test_like_wildcards_are_case_insensitive(fake_client):
    fake_client([N8N, OUTPOST, SAAS_GROUP])

    assert ids_from(run_list("--filter", "organization:like:%N8N%")) == [425417]


def test_like_wildcards_match_multiple_organizations(fake_client):
    fake_client([N8N, OUTPOST, SAAS_GROUP])

    assert ids_from(run_list("--filter", "organization:like:%GmbH%")) == [425417, 409091]


def test_like_wildcards_find_outpost(fake_client):
    fake_client([N8N, OUTPOST, SAAS_GROUP])

    assert ids_from(run_list("--filter", "organization:like:%Outpost%")) == [292143]


# ---- eq ----

def test_eq_matches_exact_organization(fake_client):
    fake_client([N8N, OUTPOST, SAAS_GROUP])

    assert ids_from(run_list("--filter", "organization:eq:n8n GmbH")) == [425417]


def test_eq_matches_email(fake_client):
    fake_client([N8N, OUTPOST, SAAS_GROUP])

    assert ids_from(run_list("--filter", "email:eq:billing@n8n.io")) == [425417]


def test_eq_returns_empty_for_a_value_that_does_not_exist(fake_client):
    fake_client([N8N, OUTPOST, SAAS_GROUP])

    assert ids_from(run_list("--filter", "organization:eq:Nope Inc.")) == []


# ---- an unsupported field must fail loudly, not report "no matches" ----

def test_unknown_field_fails_instead_of_returning_empty(fake_client):
    fake_client([N8N, OUTPOST, SAAS_GROUP])

    result = run_list("--filter", "company:contains:n8n")

    assert result.exit_code == 1
    assert "company" in result.output
    assert "organization" in result.output


# ---- --limit must cap results returned, not rows searched ----

def test_limit_does_not_hide_a_match_on_a_later_page(fake_client):
    """--limit 3 used to size the single fetched page, so a match outside the
    first 3 records reported as no match."""
    filler = [
        {"id": 1000 + i, "organization": f"Filler {i}", "fname": "F", "lname": "F", "email": ""}
        for i in range(30)
    ]
    client = fake_client(filler + [OUTPOST])

    assert ids_from(run_list("--limit", "3", "--filter", "organization:contains:Outpost")) == [292143]
    assert client.calls[0]["max_records"] is None


def test_limit_caps_the_number_of_filtered_results(fake_client):
    fake_client([N8N, OUTPOST, SAAS_GROUP])

    assert len(ids_from(run_list("--limit", "1", "--filter", "organization:contains:m"))) == 1


def test_limit_without_filter_still_bounds_the_fetch(fake_client):
    client = fake_client([N8N, OUTPOST, SAAS_GROUP])

    assert len(ids_from(run_list("--limit", "2"))) == 2
    assert client.calls[0]["max_records"] == 2


# ---- server-side narrowing must only ever return a superset ----

def test_single_filter_narrows_server_side(fake_client):
    client = fake_client([N8N, OUTPOST, SAAS_GROUP])

    run_list("--filter", "organization:contains:n8n")

    assert client.calls[0]["search_params"] == [("search[organization_like]", "n8n")]


def test_multiple_filters_do_not_narrow_server_side(fake_client):
    """Multiple --filter flags are OR. AND-ing their search parameters at the API
    would drop real matches, so no narrowing is sent."""
    client = fake_client([N8N, OUTPOST, SAAS_GROUP])

    ids = ids_from(
        run_list(
            "--filter", "organization:contains:n8n",
            "--filter", "organization:contains:Outpost",
        )
    )

    assert ids == [425417, 292143]
    assert client.calls[0]["search_params"] is None


@pytest.mark.parametrize(
    "operator,value,expected",
    [
        ("eq", "n8n GmbH", "n8n GmbH"),
        ("like", "n8n", "n8n"),
        ("like", "%n8n%", "n8n"),
        ("like", "n8n%", "n8n"),
        ("like", "%n8n", "n8n"),
        ("ilike", "%n8n%", "n8n"),
        ("contains", "n8n", "n8n"),
        ("startswith", "n8n", "n8n"),
        ("endswith", "GmbH", "GmbH"),
        # An interior wildcard has no single contiguous literal, so narrowing on
        # "google" would exclude the real match "gooXgle".
        ("like", "goo%gle", None),
        ("like", "%", None),
        # Negation and set operators have no guaranteed literal at all.
        ("ne", "n8n", None),
        ("nin", "n8n", None),
        ("in", "n8n", None),
        ("gt", "5", None),
        ("null", None, None),
        ("notnull", None, None),
    ],
)
def test_search_literal_only_returns_guaranteed_substrings(operator, value, expected):
    assert search_literal(operator, value) == expected
