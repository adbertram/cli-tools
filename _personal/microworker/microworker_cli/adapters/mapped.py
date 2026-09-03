"""The adapter -> merge seam: a mapped task, plus what the mapping could not read.

An adapter is the only code that ever sees a site's raw record, so it is the
only code that can tell "this site published no price" from "this site
published a price in a shape this adapter does not understand". Both leave
`pay_amount` and `pay_currency` null in the task contract, and that is correct
-- a price is never invented, and a regex is never widened to swallow a format
nobody has seen live. But they are different facts, and collapsing them is how
a site changing its price format ($1.50 becoming $1.5, or USD 1.50) hides
behind a run that stores every price as null and still exits 0.

THE FACT TRAVELS BESIDE THE TASK, NOT INSIDE IT. `MappedTask.task` is the
contract record the ledger stores; `MappedTask.unparsed_payment` is an
observation about THIS mapping, not a property of the task, so it is not a
contract field, not a `tasks` column, and never smuggled through `raw`.
`merge` sums it per site, prints the per-site counts in its summary, and
records them on the run's `run_sites` rows.

WHAT COUNTS AS UNPARSED is one rule, `is_unparsed_payment`, shared by every
adapter that parses a published price. Splitting that rule per adapter is how
two adapters end up disagreeing about what "the site said nothing" means.
"""

from __future__ import annotations

from typing import Any, NamedTuple


class MappedTask(NamedTuple):
    """One adapter result: the contract record, and whether its price was readable.

    `unparsed_payment` is True only when the site published a payment value
    this adapter could not turn into `pay_amount`. An adapter whose site
    publishes no payment string to parse at all reports False, which is a fact
    about that site rather than a default.
    """

    task: dict
    unparsed_payment: bool


def is_unparsed_payment(published: Any, amount: float | None) -> bool:
    """Did the site publish a price this adapter failed to read?

    `published` is the site's own payment value, exactly as its CLI returned
    it; `amount` is what the adapter's parser made of it.

    Three cases, and only the third is a parse failure:
      - a parsed amount: read, whatever its shape was.
      - nothing published: an explicit JSON null, or a blank/whitespace-only
        string, is the site leaving the price field empty. That is "no price",
        not "a price I could not read", and counting it would bury a real
        format change under noise from every unpriced listing. (A record
        missing the key entirely never reaches here: every adapter lists its
        payment field in `RAW_KEYS` and raises a `ClientError` first.)
      - anything else: the site said something the parser refused -- another
        currency, another separator, a range, a bare number where a string was
        expected. That is the case this whole seam exists to surface.
    """
    if amount is not None:
        return False
    if published is None:
        return False
    if isinstance(published, str) and not published.strip():
        return False
    return True
