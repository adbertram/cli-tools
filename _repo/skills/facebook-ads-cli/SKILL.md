---
name: facebook-ads-cli
description: >-
  MANDATORY: Use the facebook-ads wrapper for Meta's official Ads CLI service
  operations, including campaigns, ad sets, ads, creatives, catalogs, datasets,
  product feeds, insights, guidance and studies. Native invocation is
  facebook-ads run -- <native arguments>. DO NOT use for CLI implementation,
  testing, updating, troubleshooting, validation or removal; route lifecycle
  work through cli-tool.
---

<objective>
Execute the official Meta Ads CLI through facebook-ads run, preserving the
upstream command surface, arguments, stdin, output and exit status.
</objective>

<project_overrides>
Before acting, run:
```bash
~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh facebook-ads-cli
```
Apply printed instructions. No output means no override; nonzero means stop and
report the broken override rather than silently proceeding.
</project_overrides>

<quick_start>
Read adjacent `usage.json` for the wrapper contract. Read native command help
through `facebook-ads run -- ... --help` before service calls. Never copy the
retired custom SDK/Graph syntax or invent upstream options.

```bash
facebook-ads --help
facebook-ads --version
facebook-ads run -- --version
facebook-ads run -- --help
facebook-ads run -- ads --help
facebook-ads run -- ads campaign list --help
facebook-ads run -- ads creative create --help
facebook-ads run -- auth status
```
</quick_start>

<essential_principles>
- Official dependency is meta-ads==1.2.0, published by Meta on PyPI, executable
  meta. Canonical wrapper installation provisions it privately. Runtime uses
  that exact executable rather than an unrelated PATH command.
- Invoke every native operation as `facebook-ads run -- <native arguments>`.
  Root help/version belong to the wrapper; help/version after the separator
  belong to Meta. The separator protects future/native flags from wrapper parsing.
- Every native command and option passes through without a whitelist. Release
  1.2.0 has 55 native leaf commands; this is upstream CLI coverage, not universal
  Graph API coverage. Native help remains authoritative.
- Upstream owns authentication. It reads ACCESS_TOKEN and account selection via
  AD_ACCOUNT_ID or native --ad-account-id; BUSINESS_ID/--business-id is optional.
  Upstream has auth status only: no auth login, OAuth/browser flow or wrapper
  authentication profiles. Status reports configured-token readiness, not live
  proof of account permissions.
- Use the owning CLI-tools secret-manager skill for reusable tokens. Inject its
  retrieved value into ACCESS_TOKEN for the command without printing it or
  storing it in raw .env files, docs, shell arguments or logs. Existing wrapper
  profiles/secret values are preserved but are not read or rewritten.
- Native global output is --output table|json|plain (-o), with table as native
  default. JSON example: `facebook-ads run -- --output json ads adaccount list`.
  Preserve native output and exit status; do not normalize or truncate data.
- Native flags must be in the positions documented by upstream help. Do not
  invent retired --dry-run/--yes/--profile/filter/property options. Native
  --no-input suppresses prompts. Advertising mutations require user authorization;
  never launch ads or spend as a test.
- Wrapper inherits stdin/TTY, stdout, stderr and signals and executes without a
  shell. It never launches browser login or obtains credentials automatically.
</essential_principles>

<reference_index>
- `usage.json`: wrapper help/version and run passthrough contract.
- [Official Ads CLI overview](https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-cli/ads-cli-overview)
- [Official Meta package](https://pypi.org/project/meta-ads/)
</reference_index>

<success_criteria>
Use native help to select exact command syntax, inject required environment
credentials safely, preserve upstream output/errors, and verify the requested
service outcome without claiming untested account permissions or API coverage.
</success_criteria>
