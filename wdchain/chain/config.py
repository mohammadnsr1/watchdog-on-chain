"""Chain configuration: RPC endpoint, registry address, per-role signing keys.

Everything comes from environment variables, never from a committed file (CLAUDE.md rule 12):

===========================  ==========================================================
``WDCHAIN_RPC_URL``          JSON-RPC endpoint (anvil default ``http://127.0.0.1:8545``)
``WDCHAIN_EXECUTOR_KEY``     private key that signs *executor* evidence commits
``WDCHAIN_WATCHDOG_KEY``     private key that signs *WatchDog* evidence commits
``WDCHAIN_REGISTRY_ADDRESS`` optional; overrides the deployment file
``WDCHAIN_DEPLOYMENT``       optional; path to the deployment JSON (default
                             ``deployments/anvil.json``, written by the deploy script)
``WDCHAIN_ABI_PATH``         optional; Foundry artifact (default
                             ``out/EvidenceRegistry.sol/EvidenceRegistry.json``)
===========================  ==========================================================

The two roles use *different* keys on purpose: executor and WatchDog are independent witnesses
(rule 2), so their commits must be attributable to different addresses on-chain.

``.env`` is read if present (git-ignored); see ``.env.example``. Real environment variables win.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DEPLOYMENT = REPO_ROOT / "deployments" / "anvil.json"
DEFAULT_ABI_PATH = REPO_ROOT / "out" / "EvidenceRegistry.sol" / "EvidenceRegistry.json"
DEFAULT_RPC_URL = "http://127.0.0.1:8545"
DEFAULT_ENV_FILE = REPO_ROOT / ".env"

ROLE_KEY_VARS = {"executor": "WDCHAIN_EXECUTOR_KEY", "watchdog": "WDCHAIN_WATCHDOG_KEY"}


class ChainConfigError(RuntimeError):
    """Configuration is missing or unusable. The message says exactly what to set."""


def load_dotenv(path: Optional[Path] = None) -> Dict[str, str]:
    """Read simple ``KEY=value`` lines from ``.env`` without overriding real env vars.

    Supports ``#`` comments, blank lines, an optional ``export`` prefix and quoted values.
    Returns the variables that were applied.
    """
    path = Path(path) if path is not None else DEFAULT_ENV_FILE
    applied: Dict[str, str] = {}
    if not path.is_file():
        return applied
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, sep, value = line.partition("=")
        if not sep:
            continue
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value
            applied[name] = value
    return applied


@dataclass(frozen=True)
class Deployment:
    """What the deploy script recorded about a deployed registry."""

    address: str
    chain_id: Optional[int] = None
    deploy_block: Optional[int] = None
    source: Optional[str] = None

    @classmethod
    def read(cls, path: Path) -> "Deployment":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ChainConfigError(
                f"deployment file not found: {path}\n"
                f"Deploy the contract first:\n"
                f"  forge script contracts/script/DeployEvidenceRegistry.s.sol:DeployEvidenceRegistry "
                f"--rpc-url $WDCHAIN_RPC_URL --private-key $WDCHAIN_EXECUTOR_KEY --broadcast\n"
                f"or set WDCHAIN_REGISTRY_ADDRESS."
            ) from exc
        except json.JSONDecodeError as exc:
            raise ChainConfigError(f"{path}: invalid JSON: {exc}") from exc
        address = data.get("address")
        if not address:
            raise ChainConfigError(f"{path}: no 'address' field")
        return cls(
            address=address,
            chain_id=data.get("chainId"),
            deploy_block=data.get("deployBlock"),
            source=str(path),
        )


@dataclass(frozen=True)
class ChainConfig:
    rpc_url: str
    registry_address: str
    abi_path: Path
    deployment: Optional[Deployment] = None
    _keys: Optional[Dict[str, str]] = None

    def key_for_role(self, role: str) -> str:
        """Private key for ``role`` ('executor' or 'watchdog'). Raises if it is not set."""
        role = role.lower()
        var = ROLE_KEY_VARS.get(role)
        if var is None:
            raise ChainConfigError(
                f"no signing key is configured for role {role!r}; "
                f"on-chain roles are {sorted(ROLE_KEY_VARS)}"
            )
        key = (self._keys or {}).get(role) or os.environ.get(var, "")
        if not key:
            raise ChainConfigError(
                f"{var} is not set, so {role} evidence cannot be signed.\n"
                f"Copy .env.example to .env (local anvil test keys) or export {var}."
            )
        return _normalize_key(key, var)

    def load_abi(self) -> list:
        """Read the contract ABI from the Foundry build artifact.

        The ABI (application binary interface) is the JSON description of the contract's
        functions and events; web3.py needs it to encode calls and decode results.
        """
        try:
            artifact = json.loads(self.abi_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ChainConfigError(
                f"contract artifact not found: {self.abi_path}\n"
                f"Build the contracts first:  forge build"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ChainConfigError(f"{self.abi_path}: invalid JSON: {exc}") from exc
        abi = artifact.get("abi") if isinstance(artifact, dict) else None
        if not abi:
            raise ChainConfigError(f"{self.abi_path}: no 'abi' field in the artifact")
        return abi


def _normalize_key(key: str, var: str) -> str:
    """Accept a key with or without the ``0x`` prefix; reject anything malformed."""
    k = key.strip()
    if k.lower().startswith("0x"):
        k = k[2:]
    if len(k) != 64:
        raise ChainConfigError(
            f"{var} must be a 32-byte hex private key (64 hex characters, '0x' optional); "
            f"got {len(k)} characters"
        )
    try:
        bytes.fromhex(k)
    except ValueError as exc:
        raise ChainConfigError(f"{var} is not valid hex: {exc}") from exc
    return "0x" + k


def load_config(
    *,
    rpc_url: Optional[str] = None,
    registry_address: Optional[str] = None,
    deployment_path: Optional[Path] = None,
    abi_path: Optional[Path] = None,
    env_file: Optional[Path] = None,
    require_keys: bool = False,
) -> ChainConfig:
    """Build a :class:`ChainConfig` from arguments, then ``.env``, then environment variables.

    Explicit arguments win. With ``require_keys``, both role keys must be present and valid.
    """
    load_dotenv(env_file)

    rpc = rpc_url or os.environ.get("WDCHAIN_RPC_URL") or DEFAULT_RPC_URL

    deployment: Optional[Deployment] = None
    address = registry_address or os.environ.get("WDCHAIN_REGISTRY_ADDRESS")
    if not address:
        path = Path(
            deployment_path or os.environ.get("WDCHAIN_DEPLOYMENT") or DEFAULT_DEPLOYMENT
        )
        deployment = Deployment.read(path)
        address = deployment.address

    abi = Path(abi_path or os.environ.get("WDCHAIN_ABI_PATH") or DEFAULT_ABI_PATH)

    keys: Dict[str, str] = {}
    for role, var in ROLE_KEY_VARS.items():
        value = os.environ.get(var, "")
        if value:
            keys[role] = _normalize_key(value, var)
        elif require_keys:
            raise ChainConfigError(
                f"{var} is not set, so {role} evidence cannot be signed.\n"
                f"Copy .env.example to .env (local anvil test keys) or export {var}."
            )

    return ChainConfig(
        rpc_url=rpc,
        registry_address=address,
        abi_path=abi,
        deployment=deployment,
        _keys=keys or None,
    )
