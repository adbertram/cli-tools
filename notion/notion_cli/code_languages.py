"""Notion code-block language support, as data.

Notion's API rejects a ``code`` block whose ``language`` is not in its fixed
supported set with::

    body.children[N].code.language should be `abap`, `abc`, ..., `yaml`,
    or `java/c/c++/c#`, instead was `kql`

Any markdown fence info-string (``` ```kql ```) or raw JSON block can carry an
arbitrary language that Notion does not accept. Forwarding it verbatim 400s the
request -- and on the non-atomic ``replace-section`` path that rejection used to
corrupt the page (partial write + duplicate heading). To make every upload path
safe, the CLI normalizes any unsupported language to Notion's neutral
``"plain text"`` before the block is ever sent.

The supported set lives here as data (a single frozenset) so adding/removing a
language is a data change, not a code change, and so every upload path
(``content set``/``append``/``import``/``replace-section``/``duplicate``/
``database page create``) reads from exactly one source of truth.

Source: Notion API ``code`` block reference, supported language enum
(https://developers.notion.com/reference/block#code).
"""
from __future__ import annotations

# Notion's neutral fallback. Used both as the explicit ``text`` alias target and
# for any language Notion does not accept.
PLAIN_TEXT_LANGUAGE = "plain text"

# Every language string Notion's API accepts for a code block's ``language``
# field. Stored as data so language support is a data edit, not a code edit.
SUPPORTED_CODE_LANGUAGES = frozenset(
    {
        "abap",
        "abc",
        "agda",
        "arduino",
        "ascii art",
        "assembly",
        "bash",
        "basic",
        "bnf",
        "c",
        "c#",
        "c++",
        "clojure",
        "coffeescript",
        "coq",
        "css",
        "dart",
        "dhall",
        "diff",
        "docker",
        "ebnf",
        "elixir",
        "elm",
        "erlang",
        "f#",
        "flow",
        "fortran",
        "gherkin",
        "glsl",
        "go",
        "graphql",
        "groovy",
        "haskell",
        "hcl",
        "html",
        "idris",
        "java",
        "javascript",
        "json",
        "julia",
        "kotlin",
        "latex",
        "less",
        "lisp",
        "livescript",
        "llvm ir",
        "lua",
        "makefile",
        "markdown",
        "markup",
        "matlab",
        "mathematica",
        "mermaid",
        "nix",
        "notion formula",
        "objective-c",
        "ocaml",
        "pascal",
        "perl",
        "php",
        "plain text",
        "powershell",
        "prolog",
        "protobuf",
        "purescript",
        "python",
        "r",
        "racket",
        "reason",
        "ruby",
        "rust",
        "sass",
        "scala",
        "scheme",
        "scss",
        "shell",
        "smalltalk",
        "solidity",
        "sql",
        "swift",
        "toml",
        "typescript",
        "vb.net",
        "verilog",
        "vhdl",
        "visual basic",
        "webassembly",
        "xml",
        "yaml",
        "java/c/c++/c#",
    }
)

# Aliases for common markdown fence info-strings whose literal value is not in
# Notion's enum but maps cleanly to one that is. ``text`` is the canonical case
# (markdown convention -> Notion's "plain text"). Keys are matched
# case-insensitively after trimming.
CODE_LANGUAGE_ALIASES = {
    "text": PLAIN_TEXT_LANGUAGE,
    "plaintext": PLAIN_TEXT_LANGUAGE,
    "txt": PLAIN_TEXT_LANGUAGE,
}


def normalize_code_language(language: object) -> str:
    """Return a Notion-accepted code-block language for ``language``.

    Rules, applied in order:

    1. A missing/empty/non-string language becomes ``"plain text"``.
    2. A known alias (e.g. ``text`` -> ``plain text``) is mapped.
    3. A language already in Notion's supported set is returned unchanged
       (matched case-insensitively; the canonical lowercase form is returned).
    4. Anything else (e.g. ``kql``) is normalized to ``"plain text"`` so the
       block is uploadable instead of 400ing the request.

    This is the single chokepoint for code-language safety and is called on
    every upload path -- both markdown conversion and raw-block enforcement.
    """
    if not isinstance(language, str):
        return PLAIN_TEXT_LANGUAGE

    candidate = language.strip().lower()
    if not candidate:
        return PLAIN_TEXT_LANGUAGE

    if candidate in CODE_LANGUAGE_ALIASES:
        return CODE_LANGUAGE_ALIASES[candidate]

    if candidate in SUPPORTED_CODE_LANGUAGES:
        return candidate

    return PLAIN_TEXT_LANGUAGE
