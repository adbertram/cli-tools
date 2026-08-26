#!/usr/bin/env python3
"""A denial of contamination must not score as contamination.

`facebook|2134912334040252`, a 21.5 lb bulk lot a live scale confirmed genuine,
wrote "100% authentic LEGO brand pieces -- no knockoffs." on 2026-08-18.
`scan()` matched the bare word `knockoff` and returned it as contamination:
quality 79 -> 54, the multiplier 1.07 -> 0.749, `max_price` $92.02 -> $64.41,
and the score fell from a scale-verified 76 to 11 with `divergence_flag` set --
the run's single best deal, buried at the bottom of the table by a seller
GUARANTEEING the exact thing the signal exists to catch.

`contamination`'s five patterns describe the mixed-brand CONDITION, not its
denial, so any of them can be negated the same way. The other signals in this
module do not have this problem: `no_minifigures` lists "no minifigures" as its
own phrase, so the negation is already the pattern. Contamination needed a
general check instead of five new patterns.
"""
from __future__ import annotations

import pytest

from legoscout_cli.scoring.text_signals import scan


# --- the exact regression, and its near neighbours ---------------------------

def test_a_purity_guarantee_is_not_contamination():
    result = scan("100% authentic LEGO brand pieces -- no knockoffs.")

    assert result["contamination"] == []
    assert "knockoff" not in result["matched_terms"]


@pytest.mark.parametrize("text", [
    "not a single knockoff in this lot",
    "zero off-brand pieces, guaranteed genuine",
    "never any mixed brands here",
    "isn't off-brand, all real LEGO",
    "wasn't mixed with any other brand",
    "aren't any non-lego pieces in this bag",
    "without a single off-brand piece",
    "no cheap knockoffs, all genuine",
])
def test_every_negation_word_suppresses_the_match(text):
    assert scan(text)["contamination"] == []


# --- the window is words, not just "immediately before" ----------------------

@pytest.mark.parametrize("text", [
    "not even one off-brand piece in here",
    "no visible signs of any knockoff parts anywhere",
])
def test_a_negation_several_words_back_still_applies(text):
    assert scan(text)["contamination"] == []


def test_a_negation_far_earlier_in_an_unrelated_sentence_does_not_reach_forward():
    """The lookback window must not bleed across sentences."""
    text = ("This box has no visible damage at all. Comes with some off-brand "
            "pieces mixed in from a previous owner's collection.")

    assert scan(text)["contamination"] == ["off-brand"]


# --- a real defect still fires -----------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("This lot includes some knockoff pieces", ["knockoff"]),
    ("off-brand bricks included", ["off-brand"]),
    ("may also include other brands mixed in", ["may include other brands"]),
    ("not all LEGO, some compatible bricks too",
     ["compatible bricks", "not all LEGO"]),
])
def test_a_genuine_contamination_claim_still_matches(text, expected):
    assert sorted(scan(text)["contamination"]) == sorted(expected)


def test_mixed_brands_with_a_denial_elsewhere_still_reports_the_real_one():
    """A negated term next to a real one must not suppress the real one."""
    text = "no knockoffs here, but does include some Mega Bloks pieces"

    result = scan(text)["contamination"]

    assert "Mega Bloks" in result
    assert "knockoff" not in result


# --- other signals are untouched: their negation is already the pattern ------

def test_no_minifigures_is_unaffected_by_the_contamination_change():
    result = scan("Great bulk lot, no minifigures included, all bricks.")

    assert result["no_minifigures"] is True
    assert result["contamination"] == []


def test_the_benign_building_bricks_guard_still_holds():
    result = scan("LEGO building bricks bulk lot, mixed colors.")

    assert result["contamination"] == []
