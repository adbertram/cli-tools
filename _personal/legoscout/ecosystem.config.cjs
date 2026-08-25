// pm2 process definition for the LegoScout deals page on adam-server.
// .cjs extension forces CommonJS regardless of package.json "type": "module".
// `script` is the FIXED uv tool venv path -- `uv tool install --editable
// ... --force` reinstalls into this same path on every deploy, so it
// survives every release even though the release directory itself changes.
module.exports = {
  apps: [
    {
      name: 'legoscout-display',
      script: '/Users/adam/.local/share/uv/tools/legoscout-cli/bin/python',
      args:
        '-m legoscout_cli.main display serve --host 100.117.198.37 --port 8788 ' +
        '--db /Users/adam/GitRepos/legoscout/shared/found_deals.db --no-open',
      interpreter: 'none',
      cwd: __dirname,
    },
  ],
};
