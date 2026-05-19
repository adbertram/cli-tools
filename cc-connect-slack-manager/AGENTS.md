# cc-connect-slack-manager Agent Instructions

This CLI manages the always-on Slack bridge.

Read `README.md` before changing commands or models.

Configuration source:
- Runtime config is owned by the bridge configuration file documented in `README.md`.
- The runtime config owns the LaunchAgent label, cc-connect paths, Slack app ID, bot user ID, DM channel ID, and Keychain service names.

Never print Slack token values. The CLI may report whether required Keychain services exist.

