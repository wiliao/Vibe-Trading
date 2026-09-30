"""Machine-readable onboarding contracts for built-in trading connectors.

The contracts deliberately contain no credential values.  They describe the
local dependency, authentication shape, and safe verification operation so the
CLI, MCP tools, and Web UI can all drive the same setup flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.trading.local_plugins import CredentialField, plugin_by_profile_id
from src.trading.types import TradingProfile


@dataclass(frozen=True)
class ConnectorOnboarding:
    """Public setup metadata for one connector implementation."""

    auth_type: str
    credential_fields: tuple[CredentialField, ...] = ()
    dependency: str | None = None
    install_command: str | None = None
    test_operation: str = "account.read"
    setup_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe contract that never contains credential values."""
        return {
            "schema_version": 1,
            "auth_type": self.auth_type,
            "credential_fields": [field.to_dict() for field in self.credential_fields],
            "dependency": self.dependency,
            "install_command": self.install_command,
            "test_operation": self.test_operation,
            "setup_hint": self.setup_hint,
            "secret_storage": "os_keyring" if self.credential_fields else None,
        }


def _field(
    name: str,
    label: str,
    *,
    secret: bool = True,
    required: bool = True,
) -> CredentialField:
    return CredentialField(name=name, label=label, secret=secret, required=required)


_BUILTIN: dict[str, ConnectorOnboarding] = {
    "alpaca": ConnectorOnboarding(
        auth_type="api_key",
        credential_fields=(
            _field("api_key", "API Key ID"),
            _field("secret_key", "Secret Key"),
        ),
        dependency="alpaca-py",
        install_command="pip install alpaca-py keyring",
        setup_hint="Use a paper key for paper profiles and a live key for live profiles.",
    ),
    "futu": ConnectorOnboarding(
        auth_type="local_gateway",
        dependency="futu-api",
        install_command="pip install futu-api",
        setup_hint="Start and sign in to Futu OpenD on this computer before testing.",
    ),
    "longbridge": ConnectorOnboarding(
        auth_type="api_key",
        credential_fields=(
            _field("app_key", "App Key"),
            _field("app_secret", "App Secret"),
            _field("access_token", "Access Token"),
        ),
        dependency="longbridge",
        install_command="pip install longbridge keyring",
        setup_hint="The three LongPort values are stored and resolved as one atomic set.",
    ),
    "tiger": ConnectorOnboarding(
        auth_type="private_key_file",
        credential_fields=(
            _field("tiger_id", "Tiger ID", secret=False),
            _field("private_key_path", "Private Key Path", secret=False),
            _field("account", "Account", secret=False),
        ),
        dependency="tigeropen",
        install_command="pip install tigeropen keyring",
        setup_hint="Only the private-key path is stored; the PEM file remains local.",
    ),
    "ibkr": ConnectorOnboarding(
        auth_type="local_app",
        dependency="ib_async",
        install_command="pip install ib_async",
        setup_hint=(
            "Run a local TWS or IB Gateway session with the API enabled. IBKR "
            "is the only kept connector that can route a Canadian listing, but "
            "Canada live trading is not wired up in this build."
        ),
    ),
    "robinhood": ConnectorOnboarding(
        auth_type="oauth",
        setup_hint=(
            "Connect the Robinhood MCP server over OAuth. US equities only."
        ),
    ),
}


def onboarding_for_profile(profile: TradingProfile) -> ConnectorOnboarding:
    """Resolve the setup contract for a built-in or local plugin profile."""
    if profile.transport == "local_plugin":
        plugin = plugin_by_profile_id(profile.id)
        return ConnectorOnboarding(
            auth_type=plugin.auth_type,
            credential_fields=plugin.credential_fields,
            setup_hint="Operator-installed read-only connector.",
        )
    if profile.transport == "remote_mcp":
        return ConnectorOnboarding(
            auth_type="oauth",
            test_operation="account.read",
            setup_hint="Authorize through the connector OAuth flow.",
        )
    if profile.transport == "local_tws":
        return ConnectorOnboarding(
            auth_type="local_session",
            dependency="ib_async",
            install_command='pip install "vibe-trading-ai[ibkr]"',
            setup_hint="Start TWS or IB Gateway and enable its local API socket.",
        )
    return _BUILTIN.get(
        profile.connector,
        ConnectorOnboarding(auth_type="connector_managed"),
    )


def onboarding_dict(profile: TradingProfile) -> dict[str, Any]:
    """Return the public onboarding contract for ``profile``."""
    return onboarding_for_profile(profile).to_dict()
