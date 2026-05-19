# powerpoint-slide-recorder Agent Instructions

Read `README.md` before changing this CLI.

This is a local macOS recording tool. It records narrated PowerPoint slides with one command:

```bash
powerpoint-slide-recorder record
```

Important behavior:

- JSON is the default stdout format.
- Progress, diagnostics, and errors must go to stderr.
- Do not add authentication commands; the tool has no remote service or credentials.
- Do not add `--prepare-only`; the supported action is recording.
- Keep cue marker support optional through `--cue-marker`.
- Keep PowerPoint cleanup behavior covered by tests when editing recorder lifecycle code.

Required validation:

```bash
python3 -m unittest discover -s tests -v
powerpoint-slide-recorder --help
powerpoint-slide-recorder record --help
```
