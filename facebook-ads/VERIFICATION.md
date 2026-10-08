# Verification

Verified locally on October 8, 2026 with official facebook-business 26.0.2 and default Graph API v26.0. Discovery covers 1,105 generated schema classes, including 362 callable resources and 1,503 generated API operations. Every generated operation is constructed offline through the actual SDK. Generic Graph access covers operations outside that generated catalog; SDK dispatch coverage is not a claim of exhaustive live endpoint execution.

The offline suite passes 104 tests. Tests and independent adversarial probes cover actual SDK transport, full response preservation, multipart handles, video host routing, batch errors and omitted responses, cursor cycles, malformed response shapes, strict JSON, finite timing controls, secret redaction, authentication failure, and mutation/retry controls. Reuse and consolidation review findings were corrected. Installation and generated command metadata checks pass.

The shared compliance run passes 377 checks. Nine failures and two setup errors remain because no Marketing API token is authenticated. These are not waived or reported as passing. No campaign mutation, ad spend, or live provider acceptance has been verified.

Finish authorization with a Meta user/system-user token carrying the required permissions and ad-account access:

```bash
facebook-ads auth login --profile default
facebook-ads auth status --profile default
facebook-ads accounts list --parent me --limit 1
```

Enter the token only at the hidden prompt; the CLI stores it through the secret manager. Then rerun `_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name facebook-ads` from the repository root. See README for permission and API scope details.
