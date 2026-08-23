"""Token accounting shared by every DeepSeek Harness summary model.

dsh reports usage per assistant message as
`{inputTokens, outputTokens, cacheReadTokens, reasoningTokens}`.

`inputTokens` is the UNCACHED input count. Cache reads are counted separately
in `cacheReadTokens` and are NOT included in `inputTokens`. This was verified
against dsh's own rollup in `~/.dsh/storages/session_projcache.json`, whose
`tokenUsage.totals.uncachedInputTokens` equals the sum of `inputTokens` and
whose `cacheReadTokens` equals the sum of `cacheReadTokens`.

This differs from Claude Code, where the recorded input count already includes
cache reads and cache creation. Do not copy the claude-code-sessions effective
formula onto these fields.

`reasoningTokens` is a SUBSET of `outputTokens` (the reasoning portion of the
generated tokens), so it is reported separately and never added to the total.
dsh never records a cache-write count, so none is exposed.
"""
from pydantic import computed_field

from .base import CLIModel

# DeepSeek bills a cache hit at roughly a tenth of an uncached input token.
CACHE_READ_WEIGHT = 0.1


class TokenTotals(CLIModel):
    """Mixin carrying the four dsh usage counters plus a weighted total."""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_reasoning_tokens: int = 0

    @computed_field
    @property
    def effective_tokens(self) -> int:
        """Cost-weighted token total.

        Uncached input and output bill at full rate; cache reads bill at
        CACHE_READ_WEIGHT. Reasoning tokens are already inside output and are
        deliberately not added again.
        """
        return (
            self.total_input_tokens
            + self.total_output_tokens
            + int(self.total_cache_read_tokens * CACHE_READ_WEIGHT)
        )
