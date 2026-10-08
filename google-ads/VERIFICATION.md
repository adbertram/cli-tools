# Verification

Verified locally on October 8, 2026 with the pinned official Google Ads Python SDK 33.0.0 and default wire API v25. The catalog exposes 111 services and 174 RPCs, including four official long-running Operations methods. The generated coverage manifest is checked against SDK discovery.

The offline suite passes 208 tests. It covers every RPC request descriptor, strict protobuf JSON, complete response envelopes, actual generated SDK transport paging, cycle detection, streaming, partial failures, mutation controls, finite timeouts, and credential import. Installation and generated command metadata checks pass. Independent reuse/consolidation reviews and adversarial transport probes were performed; their reported code defects were corrected and rechecked.

The shared compliance run passes 380 checks. Nine failures and two setup errors remain because the profile lacks Google Ads OAuth authorization. These are not waived or reported as passing. No live API acceptance, campaign mutation, spending, or exhaustive live endpoint execution has been verified.

Existing Google OAuth app credentials were imported through the CLI's secret-manager interface without importing another tool's tokens. Finish authorization with:

```bash
google-ads auth login --profile default
google-ads auth status --profile default
google-ads customers list --limit 1
```

Then rerun `_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name google-ads` from the repository root. Account permissions and Cloud project API access remain provider-controlled. See README for complete scope and authentication details.
