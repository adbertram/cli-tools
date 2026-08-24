#!/usr/bin/env python3
"""Deterministic text signal extraction for LEGO Scout deal scoring.

Everything a regex can decide is decided here, not by a model. The same listing
text always produces the same signals, which is what makes a score reproducible
and lets the whole ledger be rescored without a single model call.

The model's job is what needs eyes -- colours, visible themes, minifig density,
boxed sets, weight from photos. It never sees a point value and never returns
one. See `<skill>/references/observation-contract.md`.
"""

from __future__ import annotations

import re

# Each signal is a list of (label, pattern). The label is what lands in
# `matched_terms` as evidence, so it is written for a human reading the ledger.
_PATTERNS: dict[str, list[tuple[str, str]]] = {
    "no_minifigures": [
        ("no minifigures", r"\bno\s+mini[\s-]?figu?r?e?s?\b"),
        ("no minifigs", r"\bno\s+mini[\s-]?figs?\b"),
        ("no figures", r"\bno\s+figures?\b"),
        ("without minifigures", r"\bwithout\s+(any\s+)?mini[\s-]?fig"),
        ("minifigures not included", r"\bmini[\s-]?figu?r?e?s?\s+(are\s+)?not\s+included\b"),
    ],
    # Deliberately narrow. "25 pounds" is a weight, not a pricing model -- the
    # 2026-07 maintenance note calls this out explicitly as the case to not
    # match. Only phrasing that says the SELLER prices by weight counts.
    "by_the_pound": [
        ("by the pound", r"\bby\s+the\s+(pound|lb)s?\b"),
        ("per pound", r"\bper\s+(pound|lb)s?\b"),
        ("priced by weight", r"\bpriced?\s+by\s+(the\s+)?weight\b"),
        ("sold by weight", r"\bsold\s+by\s+(the\s+)?weight\b"),
    ],
    # A stated PIECE COUNT on a bulk lot is a pick-over marker: counting is what
    # a seller does AFTER sorting a lot, and sorted lots lose the minifigs and
    # good sets while pricing like inventory. A pounds-denominated listing
    # ("15 lbs of LEGO") is the honest garage-clearout shape this signal must
    # NOT catch -- the number-unit pair decides, exactly as `by_the_pound`'
    # narrow matching does. Floored at three digits (>= 100 pieces) so a set's
    # "62 pieces" never fires; a picked-through bulk lot is advertised in the
    # hundreds or thousands. Up to two filler words may sit between the count
    # and the unit ("1000 Miscellaneous Pieces", the 2026-08-24 Facebook lot
    # that scored 85 on colours alone because nothing read its stated count).
    "piece_count_advertised": [
        ("stated piece count",
         r"\b(?:\d{3,}|\d{1,3}(?:,\d{3})+)[\s\-]*\+?[\s\-]*"
         r"(?:(?:\w+\s+){0,2}?(?:pieces?|pcs|pc))\b\.?"),
        ("piece count field",
         r"\bpieces?\s*:\s*(?:\d{3,}|\d{1,3}(?:,\d{3})+)\b"),
    ],
    "contamination": [
        ("Friends", r"\blego\s+friends\b|\bfriends\s+(theme|sets?|lot)\b"),
        ("Mega Bloks", r"\bmega\s?bloks?\b"),
        ("Mega Construx", r"\bmega\s?construx\b"),
        ("Kre-O", r"\bkre[\s-]?o\b"),
        ("non-LEGO", r"\bnon[\s-]?lego\b"),
        ("not all LEGO", r"\bnot\s+all\s+lego\b"),
        ("mixed brands", r"\bmixed\s+brands?\b"),
        ("off-brand", r"\boff[\s-]?brand\b"),
        ("compatible bricks", r"\bcompatible\s+(bricks?|blocks?)\b"),
        ("knockoff", r"\bknock[\s-]?offs?\b"),
        ("may include other brands", r"\bmay\s+(also\s+)?include\s+(other|non[\s-]?lego)"),
    ],
    "star_wars": [
        ("Star Wars", r"\bstar\s?wars\b"),
        ("UCS", r"\bucs\b"),
        ("Millennium Falcon", r"\bmillennium\s+falcon\b"),
    ],
    "castle": [
        ("Castle", r"\bcastle\b"),
        ("Knights", r"\bknights?\b"),
        ("Kingdoms", r"\bkingdoms?\b"),
    ],
    "technic": [
        ("Technic", r"\btechnic\b"),
    ],
    "duplo": [
        ("Duplo", r"\bduplo\b"),
    ],
    "minifigs_mentioned": [
        ("minifigures", r"\bmini[\s-]?figu?r?e?s?\b"),
        ("minifigs", r"\bmini[\s-]?figs?\b"),
    ],
    "retired": [
        ("retired", r"\bretired\b"),
        ("discontinued", r"\bdiscontinued\b"),
        ("vintage", r"\bvintage\b"),
        ("rare/hard to find", r"\bhard\s+to\s+find\b"),
    ],
}

# Generic brick words that must NOT be read as contamination on their own. The
# contract calls these out by name: a lot titled "LEGO building bricks" is a
# LEGO lot, not a mixed-brand risk.
_BENIGN = re.compile(r"\b(building|toy)\s+(bricks?|blocks?)\b", re.I)

# A negation word within ~4 words BEFORE a contamination term flips its meaning:
# "100% authentic LEGO -- no knockoffs" is a purity GUARANTEE, not evidence of
# one. On a 2026-08-18 Facebook run, exactly that sentence scored `["knockoff"]`
# as contamination on a 21.5 lb lot that a live scale confirmed was genuine,
# dropping quality 79->54, the multiplier 1.07->0.749, and the score from a
# scale-verified 76 to 11 -- the run's best bulk lot buried at the bottom of the
# table. `\bno knockoffs\b` would only catch that one phrasing; a seller writes
# "not a single knockoff", "zero off-brand pieces", "never any mixed brands",
# and a denial with an apostrophe as "isn't off-brand". The window is words, not
# characters, so it survives "no cheap knockoffs" and "not even one off-brand
# piece" without also reaching back across an unrelated earlier sentence.
_NEGATION_WORDS = r"(?:no|not|never|zero|isn't|aren't|wasn't|weren't|without)"
_NEGATION_LOOKBACK = re.compile(
    _NEGATION_WORDS + r"(?:\s+\w+){0,4}\s+$", re.I)


def _negated(text: str, match_start: int) -> bool:
    """True when a negation word precedes this match within a few words."""
    window_start = max(0, match_start - 60)
    return bool(_NEGATION_LOOKBACK.search(text[window_start:match_start]))

_COMPILED = {
    signal: [(label, re.compile(pattern, re.I)) for label, pattern in pairs]
    for signal, pairs in _PATTERNS.items()
}


def scan(text: str) -> dict:
    """Extract every text-derived scoring signal from listing text.

    `text` should be the title plus whatever description/notes the source
    exposed, concatenated. Returns facts only -- no scores, no point values.
    """
    if not isinstance(text, str):
        raise TypeError(f"scan() needs a string, got {type(text).__name__}")

    hits: dict[str, list[str]] = {}
    for signal, pairs in _COMPILED.items():
        if signal == "contamination":
            # Every other signal already encodes negation in its own pattern
            # ("no minifigures" is its own listed phrase). Contamination's
            # patterns describe the CONDITION, not its denial, so a denial
            # ("no knockoffs") needs an explicit check rather than a new regex
            # per term -- see `_negated()`.
            matched = [label for label, rx in pairs
                      if any(not _negated(text, m.start()) for m in rx.finditer(text))]
        else:
            matched = [label for label, rx in pairs if rx.search(text)]
        if matched:
            hits[signal] = matched

    no_minifigures = "no_minifigures" in hits
    # "no minifigs" also matches the bare minifigure pattern; an explicit denial
    # wins over the mention that contains it.
    minifigs_mentioned = "minifigs_mentioned" in hits and not no_minifigures

    themes = [t for t in ("star_wars", "castle", "technic", "duplo") if t in hits]

    contamination = hits.get("contamination", [])
    if not contamination and _BENIGN.search(text):
        contamination = []

    return {
        "no_minifigures": no_minifigures,
        "minifigs_mentioned": minifigs_mentioned,
        "by_the_pound": "by_the_pound" in hits,
        "piece_count_advertised": "piece_count_advertised" in hits,
        "contamination": contamination,
        "themes": themes,
        "retired": "retired" in hits,
        "matched_terms": sorted({label for labels in hits.values() for label in labels}),
    }


def listing_text(record: dict) -> str:
    """The SELLER's words, and only those.

    Deliberately excludes `notes`, `cost_per_lb_note`, and `risks_unknowns`:
    those hold our own analysis prose, and scanning them turns the pipeline's
    own output into an input. A note reading "landed $2.26/lb" was matching the
    by-the-pound rule and gutting the score of a lot Adam had actually bought.

    `observations.description` is the listing body a source worker captured, so
    it counts. Anything a source worker adds later belongs there, not in `notes`.
    """
    parts: list[str] = []
    title = record.get("title")
    if isinstance(title, str):
        parts.append(title)
    observations = record.get("observations")
    if isinstance(observations, dict):
        description = observations.get("description")
        if isinstance(description, str):
            parts.append(description)
    return "\n".join(parts)


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(scan(" ".join(sys.argv[1:])), indent=2))
