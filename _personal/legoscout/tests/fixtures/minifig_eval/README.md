# Minifigure detector evaluation fixture

Versioned files in this directory contain only provenance, expected boxes, and
human label decisions. Photo and crop bytes are deliberately disposable and
live under:

`/Users/adam/Dropbox/GitRepos/Agents/LegoScout/agent_workspaces/minifig-eval/`

`manifest.json` paths are relative to that workspace. Each asset records its
SHA-256; the evaluator refuses changed or missing bytes. The three Phase C seed
photos are real K-BID classifier downloads: clean front views containing 3, 3,
and 5 figures. Phase J expands this to 30-50 real listings and adds Adam's hard
case decisions to `labels.json`.

## Detector benchmark

Checkpoint C ran two isolated candidates against the same three-photo,
11-figure fixture on the Mac and `adam-server`. `cv2` was absent on both hosts
before candidate installation. Reports were built by
`python -m legoscout_cli.pricing.minifig_eval report` and passed the cross-host
`verify_host_reports` contract.

Selected backend: **Grounding DINO tiny**

- Model: `IDEA-Research/grounding-dino-tiny`
- Revision: `a2bb814dd30d776dcf7e30523b00659f4f141c71`
- Weights SHA-256: `1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3`
- Prompt: `lego minifigure.`
- Detection threshold: `0.25`
- Benchmark dependencies: Pillow `12.1.1`, Torch `2.13.0`, Transformers
  `5.15.1`
- Production install: `uv sync --group dev`; `pyproject.toml` ships exact
  `torch==2.13.0` and `transformers==5.15.1` and retains its existing Pillow
  requirement. It does not ship YOLO, CLIP, or OpenCV.

Candidate results:

| Host | Grounding recall | Grounding warm mean | YOLO World recall | YOLO warm mean |
|---|---:|---:|---:|---:|
| Mac | 11/11 | 1.203907 s | 8/11 | 0.070514 s |
| adam-server | 11/11 | 1.260246 s | 8/11 | 0.067556 s |

Accuracy and latency were both measured. Grounding won because it recovered all
11 expected figures on both hosts; YOLO missed the three Outrider figures on
both hosts. A speed advantage could not compensate for the repeated recall
failure.

Machine reports:

- Mac: `/Users/adam/Dropbox/GitRepos/Agents/LegoScout/agent_workspaces/minifig-eval/mac-report.json`
- adam-server: `/Users/adam/Dropbox/GitRepos/Agents/LegoScout/agent_workspaces/minifig-eval/adam-server-report.json`

The reports agree on selected backend, model revision, weights hash, dependency
versions, and non-null warm latency. Phase J expands this fixture and reruns the
same benchmark against the labeled 30-50-listing set.
