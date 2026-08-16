# Plan: Add the CourseCraft Candidate Audit Command

## Current State

- `coursecraft demos` has record CRUD commands only.
- `coursecraft_project.run_coursecraft_script` is the existing executor seam.
- The CourseCraft proof package owns the audit rules and concise JSON output.

## Implementation Steps

1. Add `coursecraft demos audit-candidate <demo-record-id>` to `commands/demos.py`.
2. Read the demo record and resolve its current `Folder Root`.
3. Invoke the CourseCraft `demo-proof audit-candidate` wrapper through the shared executor seam.
4. Preserve the proof wrapper's stdout, stderr, and exit code.
5. Document the command and refresh the repo-owned `usage.json` map.
6. Reinstall the editable CLI and run command help, a live command, CLI validation, and the full compliance suite.

## Verification Policy

CourseCraft permits one final smoke test. Do not add or run project test files.
Use the CLI compliance suite required by the CLI update workflow.
