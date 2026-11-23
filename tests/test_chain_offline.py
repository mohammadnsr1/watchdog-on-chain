"""Offline tests for the chain layer: no node, no network, no keys required.

Anything that needs a live chain is marked ``@pytest.mark.chain`` and skipped by default
(see the marker filter in pyproject.toml).
"""

from __future__ import annotations

import json

import pytest

from wdchain.chain.config import (
    ChainConfig,
    ChainConfigError,
    Deployment,
    load_config,
    load_dotenv,
)
from wdchain.chain.registry import (
    HASH_SCHEME_ID,
    Role,
    abi_encode_step_key_args,
    compute_step_key,
    hash_scheme_id,
    step_key_hex,
)
from wdchain.evidence.merkle import HASH_SCHEME, keccak256

# ---------------------------------------------------------------------------------------
# step key encoding
# ---------------------------------------------------------------------------------------

# abi.encode("s", Role.WatchDog, "w0") laid out by hand, one 32-byte word per line:
#   offset of the first string (3 words of head)      = 0x60
#   the role enum as a padded integer                 = 1
#   offset of the second string (head + first tail)   = 0xa0
#   length of "s", then its bytes right-padded
#   length of "w0", then its bytes right-padded
EXPECTED_ENCODING = (
    "0000000000000000000000000000000000000000000000000000000000000060"
    "0000000000000000000000000000000000000000000000000000000000000001"
    "00000000000000000000000000000000000000000000000000000000000000a0"
    "0000000000000000000000000000000000000000000000000000000000000001"
    "7300000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000002"
    "7730000000000000000000000000000000000000000000000000000000000000"
)


def test_abi_encoding_matches_hand_computed_vector():
    assert abi_encode_step_key_args("s", Role.WatchDog, "w0").hex() == EXPECTED_ENCODING


def test_step_key_is_keccak_of_that_encoding():
    assert compute_step_key("s", "watchdog", "w0") == keccak256(bytes.fromhex(EXPECTED_ENCODING))


def test_abi_encoding_matches_eth_abi():
    """Cross-check against an independent ABI encoder (ships with web3)."""
    eth_abi = pytest.importorskip("eth_abi")
    for session, role, step in [
        ("20261007T205057Z", Role.Executor, "w000000"),
        ("s", Role.WatchDog, "w0"),
        ("", Role.Executor, ""),
        ("a" * 31, Role.WatchDog, "b" * 33),  # crosses a 32-byte word boundary
        ("üñî", Role.Executor, "étape"),  # multi-byte UTF-8
    ]:
        expected = eth_abi.encode(["string", "uint8", "string"], [session, int(role), step])
        assert abi_encode_step_key_args(session, role, step) == expected


def test_role_is_part_of_the_key():
    """Rule 2: the two witnesses can never share a storage slot."""
    e = compute_step_key("S", Role.Executor, "w000000")
    w = compute_step_key("S", Role.WatchDog, "w000000")
    assert e != w


def test_step_keys_do_not_collide_across_string_boundaries():
    """Length-prefixed encoding, so ("ab","c") and ("a","bc") differ."""
    assert compute_step_key("ab", Role.Executor, "c") != compute_step_key("a", Role.Executor, "bc")


def test_int_step_ids_are_stringified():
    assert compute_step_key("S", Role.Executor, 3) == compute_step_key("S", Role.Executor, "3")


def test_step_key_hex_shape():
    key = step_key_hex("S", "executor", "w000000")
    assert key.startswith("0x") and len(key) == 66


def test_role_parsing():
    assert Role.parse("watchdog") is Role.WatchDog
    assert Role.parse("WatchDog") is Role.WatchDog
    assert Role.parse(0) is Role.Executor
    assert Role.parse(Role.WatchDog) is Role.WatchDog
    # wdchain's other roles have no on-chain equivalent yet; the error has to say so.
    for unsupported in ["backend", "executor_monitor"]:
        with pytest.raises(ValueError, match="no on-chain equivalent"):
            Role.parse(unsupported)


def test_hash_scheme_id_matches_the_evidence_module():
    assert HASH_SCHEME_ID == HASH_SCHEME
    assert hash_scheme_id() == keccak256(HASH_SCHEME.encode())


# ---------------------------------------------------------------------------------------
# fixture generation
# ---------------------------------------------------------------------------------------


def test_fixture_is_deterministic_and_verifies_locally():
    from scripts.make_merkle_fixture import build_fixture
    from wdchain.evidence.merkle import from_hex, leaf_from_digest, verify_proof

    a = build_fixture(7)
    b = build_fixture(7)
    assert a == b, "same inputs must give the same fixture bytes"
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    assert a["hash_scheme"] == HASH_SCHEME
    assert a["n_chunks"] == 7 == len(a["chunks"])
    root = from_hex(a["root"])
    for chunk in a["chunks"]:
        leaf = leaf_from_digest(from_hex(chunk["digest"]))
        assert leaf == from_hex(chunk["leaf"])
        assert verify_proof([from_hex(h) for h in chunk["proof"]], root, leaf)


def test_fixture_odd_leaf_has_a_shorter_proof():
    """7 leaves: the last one is carried up a level, so its proof is shorter."""
    from scripts.make_merkle_fixture import build_fixture

    chunks = build_fixture(7)["chunks"]
    assert len(chunks[6]["proof"]) < len(chunks[0]["proof"])


def test_fixture_rejects_empty_tree():
    from scripts.make_merkle_fixture import build_fixture

    with pytest.raises(ValueError):
        build_fixture(0)


# ---------------------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_chain_env(monkeypatch):
    """Keep the developer's real environment out of these tests."""
    for var in [
        "WDCHAIN_RPC_URL",
        "WDCHAIN_EXECUTOR_KEY",
        "WDCHAIN_WATCHDOG_KEY",
        "WDCHAIN_REGISTRY_ADDRESS",
        "WDCHAIN_DEPLOYMENT",
        "WDCHAIN_ABI_PATH",
    ]:
        monkeypatch.delenv(var, raising=False)


ANVIL_KEY_0 = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
ANVIL_KEY_1 = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"


def _deployment(tmp_path, address="0x5FbDB2315678afecb367f032d93F642f64180aa3"):
    path = tmp_path / "anvil.json"
    path.write_text(json.dumps({"chainId": 31337, "address": address, "deployBlock": 1}))
    return path


def test_missing_deployment_file_names_the_fix(tmp_path):
    with pytest.raises(ChainConfigError, match="deployment file not found"):
        load_config(deployment_path=tmp_path / "nope.json", env_file=tmp_path / "none.env")


def test_missing_keys_name_the_variable(tmp_path, monkeypatch):
    with pytest.raises(ChainConfigError, match="WDCHAIN_EXECUTOR_KEY"):
        load_config(deployment_path=_deployment(tmp_path), env_file=tmp_path / "none.env",
                    require_keys=True)

    monkeypatch.setenv("WDCHAIN_EXECUTOR_KEY", ANVIL_KEY_0)
    with pytest.raises(ChainConfigError, match="WDCHAIN_WATCHDOG_KEY"):
        load_config(deployment_path=_deployment(tmp_path), env_file=tmp_path / "none.env",
                    require_keys=True)


def test_malformed_key_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("WDCHAIN_EXECUTOR_KEY", "0xdeadbeef")  # too short
    monkeypatch.setenv("WDCHAIN_WATCHDOG_KEY", ANVIL_KEY_1)
    with pytest.raises(ChainConfigError, match="64 hex characters"):
        load_config(deployment_path=_deployment(tmp_path), env_file=tmp_path / "none.env")

    monkeypatch.setenv("WDCHAIN_EXECUTOR_KEY", "z" * 64)
    with pytest.raises(ChainConfigError, match="not valid hex"):
        load_config(deployment_path=_deployment(tmp_path), env_file=tmp_path / "none.env")


def test_keys_load_with_and_without_0x(tmp_path, monkeypatch):
    monkeypatch.setenv("WDCHAIN_EXECUTOR_KEY", ANVIL_KEY_0[2:])  # no prefix
    monkeypatch.setenv("WDCHAIN_WATCHDOG_KEY", ANVIL_KEY_1)
    config = load_config(deployment_path=_deployment(tmp_path), env_file=tmp_path / "none.env",
                         require_keys=True)
    assert config.key_for_role("executor") == ANVIL_KEY_0
    assert config.key_for_role("watchdog") == ANVIL_KEY_1
    assert config.key_for_role("executor") != config.key_for_role("watchdog")


def test_roles_without_a_key_are_named_clearly(tmp_path, monkeypatch):
    monkeypatch.setenv("WDCHAIN_EXECUTOR_KEY", ANVIL_KEY_0)
    monkeypatch.setenv("WDCHAIN_WATCHDOG_KEY", ANVIL_KEY_1)
    config = load_config(deployment_path=_deployment(tmp_path), env_file=tmp_path / "none.env")
    with pytest.raises(ChainConfigError, match="no signing key"):
        config.key_for_role("backend")


def test_registry_address_env_var_skips_the_deployment_file(tmp_path, monkeypatch):
    monkeypatch.setenv("WDCHAIN_REGISTRY_ADDRESS", "0x000000000000000000000000000000000000dEaD")
    config = load_config(deployment_path=tmp_path / "missing.json", env_file=tmp_path / "none.env")
    assert config.registry_address.endswith("dEaD")
    assert config.deployment is None


def test_defaults_and_deployment_fields(tmp_path):
    config = load_config(deployment_path=_deployment(tmp_path), env_file=tmp_path / "none.env")
    assert config.rpc_url == "http://127.0.0.1:8545"
    assert config.deployment.chain_id == 31337
    assert config.deployment.deploy_block == 1


def test_deployment_without_address_is_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"chainId": 31337}))
    with pytest.raises(ChainConfigError, match="no 'address'"):
        Deployment.read(path)


def test_missing_abi_artifact_says_to_build(tmp_path):
    config = ChainConfig(
        rpc_url="http://127.0.0.1:8545",
        registry_address="0x000000000000000000000000000000000000dEaD",
        abi_path=tmp_path / "out" / "EvidenceRegistry.json",
    )
    with pytest.raises(ChainConfigError, match="forge build"):
        config.load_abi()


def test_dotenv_does_not_override_real_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n"
        "\n"
        f"export WDCHAIN_EXECUTOR_KEY={ANVIL_KEY_0}\n"
        f'WDCHAIN_WATCHDOG_KEY="{ANVIL_KEY_1}"\n'
        "WDCHAIN_RPC_URL=http://from-dotenv:8545\n"
    )
    monkeypatch.setenv("WDCHAIN_RPC_URL", "http://from-environment:8545")
    applied = load_dotenv(env)
    assert "WDCHAIN_RPC_URL" not in applied, "a real env var wins over .env"
    config = load_config(deployment_path=_deployment(tmp_path), env_file=env, require_keys=True)
    assert config.rpc_url == "http://from-environment:8545"
    assert config.key_for_role("executor") == ANVIL_KEY_0


# ---------------------------------------------------------------------------------------
# anchor log
# ---------------------------------------------------------------------------------------


def test_anchor_log_appends_with_one_header(tmp_path):
    from wdchain.cli.anchor_session import LOG_COLUMNS, append_log_row

    row = {
        "session_id": "S", "role": "watchdog", "n_steps": 3,
        "tx_hash": "0xabc", "block": 7, "gas_used": 123456,
        "wall_time_iso": "2026-11-22T00:00:00+00:00",
    }
    append_log_row(tmp_path, row)
    append_log_row(tmp_path, {**row, "n_steps": 1, "block": 8})

    lines = (tmp_path / "anchor_log.csv").read_text().strip().splitlines()
    assert lines[0] == ",".join(LOG_COLUMNS)
    assert len(lines) == 3
    assert lines[1].startswith("S,watchdog,3,0xabc,7,123456,")


def test_session_index_with_a_foreign_hash_scheme_is_refused(tmp_path):
    from wdchain.cli.anchor_session import load_session_index

    (tmp_path / "session_index.json").write_text(
        json.dumps({"session_id": "S", "hash_scheme": "sha256-v9", "roles": {}})
    )
    with pytest.raises(ChainConfigError, match="different scheme"):
        load_session_index(tmp_path)


def test_missing_session_index_says_to_commit_first(tmp_path):
    from wdchain.cli.anchor_session import load_session_index

    with pytest.raises(ChainConfigError, match="wdchain-commit-session"):
        load_session_index(tmp_path)


# ---------------------------------------------------------------------------------------
# live-chain tests (skipped by default)
# ---------------------------------------------------------------------------------------


@pytest.mark.chain
def test_python_and_solidity_agree_on_step_keys():
    """Requires anvil + a deployed registry. Run with: pytest -m chain"""
    from wdchain.chain.registry import RegistryClient

    client = RegistryClient()
    for session, role, step in [
        ("20261007T205057Z", Role.Executor, "w000000"),
        ("20261007T205057Z", Role.WatchDog, "pick_u_orange"),
    ]:
        assert client.compute_step_key_onchain(session, role, step) == compute_step_key(
            session, role, step
        )
