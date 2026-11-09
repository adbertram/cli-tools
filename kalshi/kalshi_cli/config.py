"""Configuration for the Kalshi CLI.

Kalshi demo and production use separate credentials, so each environment has its own
auth profile: the active/default profile is production, the profile named ``demo``
is the demo exchange. The key ID is sent in clear in every request header, so it is
plain profile state; only the private key is a secret-manager secret.
"""

from cli_tools_shared.config import (
    BaseConfig,
    config_getter,
    read_cli_tool_secret,
    resolve_tool_dir,
    secret_manager_set_command,
)
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import print_info

from .signing import Signer, decode_private_key


class Config(BaseConfig):
    DIST_NAME = "kalshi-cli"
    CREDENTIAL_TYPES = [CredentialType.CUSTOM]
    CUSTOM_REQUIRED_FIELDS = ["KEY_ID", "PRIVATE_KEY"]
    CUSTOM_ALL_FIELDS = ["KEY_ID", "PRIVATE_KEY"]
    CUSTOM_LOGIN_PROMPTS = [("KEY_ID", "Kalshi API key ID", False)]
    CUSTOM_SENSITIVE_FIELDS = ["PRIVATE_KEY"]
    AUTH_SETUP_INSTRUCTIONS = (
        "Create an API key at https://kalshi.com/account/profile (API Keys > Create New API Key).\n"
        "Kalshi shows the private key once, so save it to a file and keep the Key ID.\n"
        "Store the key file first: base64 -i key.pem | tr -d '\\n' | secrets.sh set kalshi-private-key (demo: kalshi-demo-private-key).\n"
        "Production credentials go in the default profile. Demo credentials are separate:\n"
        "create them at https://demo.kalshi.co and log in with: kalshi auth login --profile demo"
    )

    def __init__(self, profile=None):
        super().__init__(tool_dir=resolve_tool_dir(self.DIST_NAME), profile=profile)

    @property
    def key_id(self):
        return self._get("KEY_ID")

    @property
    def private_key(self):
        return self._get("PRIVATE_KEY")

    def test_connection(self) -> dict:
        """Validate the saved key pair with a signed balance request on this profile's exchange."""
        from .client import KalshiClient

        env = "demo" if self.profile_name == "demo" else "prod"
        try:
            with KalshiClient(env=env, signer=Signer(self.key_id, decode_private_key(self.private_key))) as client:
                client.balance()
            return {"api_test": "passed", "environment": env}
        except ClientError as exc:
            return {"api_test": f"failed: {exc}", "environment": env}

    @property
    def profile_name(self) -> str:
        return self.profile_name_for_path(self.env_file_path)


def login_handler(config: Config, force: bool) -> None:
    """Link the private key Adam stored in the secret manager to this profile.

    A PEM spans several lines and the secret manager returns multi-line values
    hex-encoded, so the key is stored as one line of base64 with `secrets.sh set`.
    This handler validates the stored key and writes the profile placeholder.
    """
    if config.private_key and not force:
        print_info("Private key already linked. Use --force to re-validate it.")
        return
    secret_name = config._secret_name_for_field("PRIVATE_KEY")
    secret = read_cli_tool_secret(secret_name)
    if not secret:
        raise ClientError(
            f"Secret '{secret_name}' is not stored. Store the private key file first:\n"
            f"base64 -i /path/to/kalshi-private-key.pem | tr -d '\\n' | {secret_manager_set_command(secret_name)}"
        )
    Signer(config.key_id or "validate", decode_private_key(secret))
    config._set("PRIVATE_KEY", secret)
    print_info(f"Private key linked from secret '{secret_name}'.")


get_config = config_getter(Config)
