# Minifigure evaluation fixture contract

This directory commits the **contract and human labels**, not marketplace image
binaries. The disposable assets, detector output, identifier output, crops, and
labeling queue live under:

`/Users/adam/Dropbox/GitRepos/Agents/LegoScout/agent_workspaces/minifig-eval/`

## Dataset identity

- `manifest.json` is dataset version 1 and has the immutable ID
  `minifig-eval-33-real-listings-v1`.
- It contains exactly **33 distinct real marketplace listings** from eBay,
  HiBid, K-BID, and ShopGoodwill.
- Every row records its listing URL, source image URL, provenance run, consent
  basis, disposable relative asset path, image dimensions, and SHA-256.
- The three original Phase C K-BID seed rows retain their manually reviewed
  detector boxes for detector-benchmark reproducibility. Those values are not
  Phase J identity or quantity labels. The other 30 rows deliberately do not
  copy detector proposals into expected fields.
- `labels.json` is the only Phase J source of truth for human decisions. Its
  `dataset_id`, `manifest_version`, and canonical `manifest_sha256` must match
  the manifest exactly. It intentionally remains empty until Adam labels it.

The image binaries are intentionally untracked. Re-collect them from the
manifest provenance when needed; never weaken the hashes to make a different
asset pass.

## Workspace artifacts

The full release command expects these already-generated, same-order artifacts,
each bound to the same canonical manifest digest:

- `detections.json` — `minifig_detection` output for all 33 manifest keys.
- `identifications.json` — `minifig_identification` proposals for those keys.
- `assets/...` — the disposable listing photos named by the manifest.

Identification artifacts also carry the exact detection-artifact digest, and
their embedded detections must match upstream crop IDs, photo IDs, crop refs,
boxes, and source-photo hashes. Reports carry the exact detection and
identification artifact digests. It atomically writes:

- `labeling-queue.json` — model proposals plus null human-decision fields.
- the report path passed to `--output`.

## Human-label gate

Run:

```bash
legoscout minifig eval \
  --manifest tests/fixtures/minifig_eval/manifest.json \
  --labels tests/fixtures/minifig_eval/labels.json \
  --workspace /Users/adam/Dropbox/GitRepos/Agents/LegoScout/agent_workspaces/minifig-eval \
  --output /Users/adam/Dropbox/GitRepos/Agents/LegoScout/agent_workspaces/minifig-eval/eval-report.json \
  --approval /path/to/adam-created-approval.json \
  --host-report /path/to/mac-verification.json \
  --host-report /path/to/adam-server-verification.json \
  --crop-root /Users/adam/Dropbox/GitRepos/Agents/LegoScout/agent_workspaces/minifig-eval/crops \
  --stage all
```

The expected current result is non-zero `blocked`, because `labels.json`
contains no fabricated decisions and no approval is committed. Use
`labeling-queue.json` only as a visual
review aid. For every proposal, Adam must independently create one decision in
`labels.json` with these exact keys:

```json
{
  "listing_key": "source|id",
  "expected_boxes": [[0.1, 0.1, 0.2, 0.4]],
  "expected_quantity": 1,
  "groups": [
    {
      "match_group_id": "figgroup-v1-...",
      "expected_fig_no": "sw0001",
      "obscure": false
    }
  ],
  "hard_case": true,
  "reviewed_at": "2026-08-25T00:00:00Z"
}
```

`expected_fig_no` may be `null` only when the correct identity is genuinely
unknown. Label 10–15 of the 33 listings as hard cases and human-review every
remaining listing. Do not copy `proposed_boxes`, `proposed_quantity`, or
`proposed_fig_no` into labels without human inspection.

After labeling, the parent session must wait for Adam's explicit approval, then
create a separate receipt with this exact shape:

```json
{
  "version": 1,
  "kind": "minifig_eval_human_approval",
  "approver": "Adam Bertram",
  "decision": "approved",
  "approved_at": "<UTC timestamp of Adam's response>",
  "manifest_sha256": "<canonical manifest SHA-256>",
  "labels_sha256": "<exact labels-file byte SHA-256>"
}
```

Evaluation code validates but never creates this receipt. Any labels-file byte
change invalidates it. This is a small procedural human checkpoint bound to the
reviewed bytes, not a claim of cryptographic authorship or unforgeability; the
parent must not create it before Adam responds.

## Locked evaluation bars

`--stage` accepts only `all`, `detect`, `identify`, or `quantity`. `all` applies:

- detection recall >= 90% at IoU >= 0.50;
- verified-ID precision >= 85%;
- wrong-ID escape rate < 5%;
- exact-quantity lot rate >= 90%;
- every human-labeled obscure case routes to unknown with a retained crop.

The obscure-crop bar has no implicit workspace fallback. `--crop-root` must be
supplied explicitly, and each retained file must remain under that root, use the
exact detector crop ID as its basename, and match the recorded crop SHA-256.

A zero denominator never passes. Incomplete labels produce a valid blocked
report and non-zero exit. Malformed manifests, labels, or proposal batches
produce no report. Threshold failures produce a valid failed report and
non-zero exit.

Only `--stage all` on the immutable canonical ID with exactly 33 labels, 10–15
hard cases, finite detector/identifier timings, a matching approval, and
verified Mac plus adam-server detector benchmark reports can return `passed`.
Regenerate those reports with the benchmark command after this schema change; each
report now carries the exact detector-seed dataset ID/run/manifest digest and the
winner's model revision, weights digest, dependency versions, and finite
per-image timings. Evaluation derives that three-row seed manifest from the
canonical 33-row release manifest and requires an exact digest match, while also
binding the exact identifier request contract and local identifier timings.
Focused stages and
noncanonical fixtures report `non_gating`. `detect` loads only detections;
`identify` and `quantity` load only identifications. Queue generation is
best-effort (`--no-queue` disables it) and never defeats stage isolation.

## Recorded detector benchmark evidence (2026-08-25)

Both host reports selected `grounding-dino-tiny` with recall 11/11 (value
1.0) on the three-row detector-seed manifest:

| Host | Pillow | Torch | Transformers | Load s | Warm mean s |
|---|---|---|---|---|---|
| mac | 12.3.0 | 2.13.0 | 5.15.1 | 1.168 | 1.306 |
| adam-server | 12.3.0 | 2.13.0 | 5.15.1 | 1.213 | 1.218 |

Shared constants on both hosts: model revision
`a2bb814dd30d776dcf7e30523b00659f4f141c71`, weights SHA-256
`1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3`,
Python 3.11.15 arm64, OpenCV absent. Cross-host verification artifact:
`phase-j-cross-host-verification.json` (`status: success`, hosts mac +
adam-server). The adam-server run used its isolated benchmark runtime at
`~/.local/share/legoscout-benchmarks/phase-j-detector-v1`; production
tooling there remains Torch/Transformers-free.
