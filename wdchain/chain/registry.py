"""Thin client for the ``EvidenceRegistry`` contract.

Responsibilities: compute step keys exactly as Solidity does, send signed commits from the
right per-role key, and read commits and proof checks back.

Blockchain primer used throughout:

* A **transaction** is a signed message that changes chain state. It costs **gas**, needs a
  **nonce** (a per-address counter that stops replays) and is identified by its **hash**.
* Sending is asynchronous: ``send_raw_transaction`` returns a hash, and the **receipt**
  (block number, gas used, success flag) arrives once the transaction is mined.
* A **view** call changes nothing, is answered by the local node and costs no gas, so
  :meth:`RegistryClient.verify_chunk_onchain` is free and needs no key.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, List, Optional, Sequence, Union

from eth_hash.auto import keccak

from .config import ChainConfig, ChainConfigError, load_config

HASH_SCHEME_ID = "keccak256-oz-sorted-v1"
_WORD = 32


class Role(IntEnum):
    """On-chain witness roles. The values must match the Solidity ``enum Role``."""

    Executor = 0
    WatchDog = 1

    @classmethod
    def parse(cls, value: Union[str, int, "Role"]) -> "Role":
        if isinstance(value, Role):
            return value
        if isinstance(value, int):
            return cls(value)
        key = str(value).strip().lower().replace("-", "_")
        for role in cls:
            if role.name.lower() == key:
                return role
        raise ValueError(
            f"role {value!r} has no on-chain equivalent; the registry knows "
            f"{[r.name for r in cls]} (wdchain's 'backend' and 'executor_monitor' roles are "
            f"committed off-chain only)"
        )


# --- ABI encoding (kept independent of web3 so step keys can be computed offline) ----------


def _encode_uint(value: int) -> bytes:
    return int(value).to_bytes(_WORD, "big")


def _encode_string_tail(text: str) -> bytes:
    """ABI tail of a dynamic string: 32-byte length, then UTF-8 bytes right-padded."""
    data = text.encode("utf-8")
    pad = (-len(data)) % _WORD
    return _encode_uint(len(data)) + data + b"\x00" * pad


def abi_encode_step_key_args(session_id: str, role: Role, step_id: str) -> bytes:
    """``abi.encode(string sessionId, Role role, string stepId)``.

    Two dynamic strings and one enum. The head holds the offset of the first string, the role
    as a padded integer and the offset of the second string; the tails follow. Length-prefixed
    ABI encoding is used (never ``abi.encodePacked``) so that ("ab","c") and ("a","bc") cannot
    produce the same key.
    """
    tail_session = _encode_string_tail(session_id)
    tail_step = _encode_string_tail(step_id)
    head_size = 3 * _WORD
    head = (
        _encode_uint(head_size)
        + _encode_uint(int(role))
        + _encode_uint(head_size + len(tail_session))
    )
    return head + tail_session + tail_step


def compute_step_key(session_id: str, role: Union[str, int, Role], step_id: Union[str, int]) -> bytes:
    """Storage key for a step's evidence: ``keccak256(abi.encode(sessionId, role, stepId))``.

    Must equal ``EvidenceRegistry.computeStepKey``. Step ids are strings on-chain, so integer
    ids from the ``by_field`` segmenter are stringified exactly as ``str()`` renders them.
    """
    return keccak(abi_encode_step_key_args(str(session_id), Role.parse(role), str(step_id)))


def step_key_hex(session_id: str, role: Union[str, int, Role], step_id: Union[str, int]) -> str:
    return "0x" + compute_step_key(session_id, role, step_id).hex()


def hash_scheme_id(scheme: str = HASH_SCHEME_ID) -> bytes:
    """``keccak256`` of the scheme id string, as stored with every commit."""
    return keccak(scheme.encode("utf-8"))


# --- client --------------------------------------------------------------------------------


@dataclass
class TxResult:
    """What a sent transaction produced."""

    tx_hash: str
    block_number: int
    gas_used: int
    status: int
    step_keys: List[str]

    @property
    def ok(self) -> bool:
        return self.status == 1


@dataclass
class CommitRecord:
    """A stored commit as read back from the chain."""

    root: str
    committer: str
    time: int
    hash_scheme: str

    @property
    def exists(self) -> bool:
        return int(self.committer, 16) != 0


class RegistryClient:
    """Connected client. Constructing it opens an RPC connection."""

    def __init__(self, config: Optional[ChainConfig] = None, *, timeout: int = 120):
        try:
            from web3 import Web3
            from eth_account import Account
        except ImportError as exc:  # pragma: no cover - depends on install
            raise ChainConfigError(
                "web3 and eth-account are required for on-chain work; install them with "
                "`pip install -e '.[dev]'`"
            ) from exc

        self.config = config or load_config()
        self.timeout = timeout
        self._Account = Account
        self.w3 = Web3(Web3.HTTPProvider(self.config.rpc_url, request_kwargs={"timeout": 30}))
        if not self.w3.is_connected():
            raise ChainConfigError(
                f"cannot reach a chain at {self.config.rpc_url}\n"
                f"Start one with:  anvil\n"
                f"or set WDCHAIN_RPC_URL."
            )
        self.address = self.w3.to_checksum_address(self.config.registry_address)
        self.contract = self.w3.eth.contract(address=self.address, abi=self.config.load_abi())
        if self.w3.eth.get_code(self.address) in (b"", "0x", b"0x"):
            raise ChainConfigError(
                f"no contract code at {self.address} on {self.config.rpc_url}\n"
                f"The chain may have been restarted since it was deployed. Redeploy with "
                f"forge script contracts/script/DeployEvidenceRegistry.s.sol:DeployEvidenceRegistry "
                f"--rpc-url $WDCHAIN_RPC_URL --private-key $WDCHAIN_EXECUTOR_KEY --broadcast"
            )

    # --- accounts ---------------------------------------------------------------------

    def account_for_role(self, role: Union[str, int, Role]):
        """Local signing account for a role. The private key never leaves this process."""
        role = Role.parse(role)
        return self._Account.from_key(self.config.key_for_role(role.name.lower()))

    def address_for_role(self, role: Union[str, int, Role]) -> str:
        return self.account_for_role(role).address

    # --- writes -----------------------------------------------------------------------

    def _send(self, fn, account) -> TxResult:
        """Build, sign and send a transaction, then wait for its receipt."""
        tx: Dict[str, Any] = {
            "from": account.address,
            # The nonce is this address's transaction counter; "pending" includes
            # transactions already sent but not yet mined.
            "nonce": self.w3.eth.get_transaction_count(account.address, "pending"),
            "chainId": self.w3.eth.chain_id,
        }
        # build_transaction estimates the gas limit by simulating the call, so a commit that
        # would revert (e.g. already committed) fails here, before anything is sent.
        built = fn.build_transaction(tx)
        signed = account.sign_transaction(built)
        raw = getattr(signed, "raw_transaction", None)
        if raw is None:  # web3.py < 7 spelled it rawTransaction
            raw = signed.rawTransaction
        tx_hash = self.w3.eth.send_raw_transaction(raw)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=self.timeout)
        return TxResult(
            tx_hash=tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash),
            block_number=receipt["blockNumber"],
            gas_used=receipt["gasUsed"],
            status=receipt.get("status", 1),
            step_keys=[],
        )

    def commit(
        self,
        session_id: str,
        role: Union[str, int, Role],
        step_id: Union[str, int],
        root: Union[str, bytes],
        scheme: str = HASH_SCHEME_ID,
    ) -> TxResult:
        """Anchor one step root, signed by that role's key."""
        role = Role.parse(role)
        account = self.account_for_role(role)
        fn = self.contract.functions.commit(
            str(session_id), int(role), str(step_id), _to_bytes32(root), hash_scheme_id(scheme)
        )
        result = self._send(fn, account)
        result.step_keys = [step_key_hex(session_id, role, step_id)]
        return result

    def commit_batch(
        self,
        session_id: str,
        role: Union[str, int, Role],
        step_ids: Sequence[Union[str, int]],
        roots: Sequence[Union[str, bytes]],
        scheme: str = HASH_SCHEME_ID,
    ) -> TxResult:
        """Anchor many step roots for one role in a single transaction."""
        role = Role.parse(role)
        if len(step_ids) != len(roots):
            raise ValueError(f"{len(step_ids)} step ids but {len(roots)} roots")
        if not step_ids:
            raise ValueError("commit_batch needs at least one step")
        account = self.account_for_role(role)
        fn = self.contract.functions.commitBatch(
            str(session_id),
            int(role),
            [str(s) for s in step_ids],
            [_to_bytes32(r) for r in roots],
            hash_scheme_id(scheme),
        )
        result = self._send(fn, account)
        result.step_keys = [step_key_hex(session_id, role, s) for s in step_ids]
        return result

    # --- reads (free, no key needed) ---------------------------------------------------

    def get_commit(
        self, session_id: str, role: Union[str, int, Role], step_id: Union[str, int]
    ) -> CommitRecord:
        root, committer, when, scheme = self.contract.functions.commits(
            compute_step_key(session_id, role, step_id)
        ).call()
        return CommitRecord(
            root="0x" + bytes(root).hex(),
            committer=committer,
            time=int(when),
            hash_scheme="0x" + bytes(scheme).hex(),
        )

    def is_committed(self, session_id: str, role: Union[str, int, Role], step_id: Union[str, int]) -> bool:
        return self.contract.functions.isCommitted(
            compute_step_key(session_id, role, step_id)
        ).call()

    def verify_chunk_onchain(
        self,
        session_id: str,
        role: Union[str, int, Role],
        step_id: Union[str, int],
        chunk_digest: Union[str, bytes],
        proof: Sequence[Union[str, bytes]],
    ) -> bool:
        """Ask the contract whether this chunk belongs to the anchored step."""
        return self.contract.functions.verifyChunk(
            compute_step_key(session_id, role, step_id),
            _to_bytes32(chunk_digest),
            [_to_bytes32(p) for p in proof],
        ).call()

    def compute_step_key_onchain(
        self, session_id: str, role: Union[str, int, Role], step_id: Union[str, int]
    ) -> bytes:
        """The contract's own step key, for checking that Python agrees with Solidity."""
        return bytes(
            self.contract.functions.computeStepKey(
                str(session_id), int(Role.parse(role)), str(step_id)
            ).call()
        )


def _to_bytes32(value: Union[str, bytes]) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
    else:
        text = str(value).strip()
        if text.lower().startswith("0x"):
            text = text[2:]
        data = bytes.fromhex(text)
    if len(data) != 32:
        raise ValueError(f"expected 32 bytes, got {len(data)}")
    return data


def utc_now_iso() -> str:
    """UTC timestamp for log rows, in the same shape as the sessions' ``wall_time_iso``."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "+00:00"
