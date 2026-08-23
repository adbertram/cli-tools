# Things 3 notes length limit

## Confirmed behavior

Things 3 silently truncated the reproduced todo notes written through
AppleScript to 39,999 ASCII characters. A real `things todos create` invocation
supplied 53,619 ASCII characters and exited successfully, while AppleScript
readback returned exactly 39,999 characters and a different SHA-256 digest.
Because ASCII uses one UTF-16 code unit per character, that observation
establishes a 39,999-unit safe boundary for the reproduced write path. The exact
boundary behavior for non-ASCII text is unverified because probing it would
require another Things mutation.

This is an application/AppleScript write limit, not a shell argument or CLI JSON
limit: Things returned a UUID and accepted the mutation while storing only the
prefix. Cultured Code does not publish this limit in its user documentation, so
39,999 is an empirically confirmed integration limit rather than a documented
vendor contract.

## CLI guarantee

`things todos create --notes` and `things todos update --notes` count UTF-16
code units before any Things read or write. Inputs above 39,999 fail with a
`ClientError` that reports the limit, received code-unit count, Python character
count, and confirms that no Things record was created or updated.

Counting UTF-16 code units matches Things/macOS `NSString` semantics. Most text
uses one unit per character; characters outside the Basic Multilingual Plane,
such as many emoji, use two. An input of 20,000 `😀` characters is therefore
40,000 units and is rejected even though Python's `len()` is 20,000.

## Agent handling

- Do not retry an oversized write unchanged.
- Shorten the notes or split the content across multiple user-approved records.
- Never create, update, or delete a record merely to probe the boundary.
- A zero exit status from an older CLI is not proof that long notes were stored;
  verify existing suspect writes with readback length and digest before relying
  on them.
