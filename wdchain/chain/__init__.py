"""Blockchain client layer: configuration and the EvidenceRegistry contract client.

Importing this package does not touch the network. Connecting happens only when a
:class:`~wdchain.chain.registry.RegistryClient` is constructed.
"""

from .config import ChainConfig, ChainConfigError, Deployment, load_config
from .registry import RegistryClient, Role, TxResult, compute_step_key

__all__ = [
    "ChainConfig",
    "ChainConfigError",
    "Deployment",
    "load_config",
    "RegistryClient",
    "Role",
    "TxResult",
    "compute_step_key",
]
