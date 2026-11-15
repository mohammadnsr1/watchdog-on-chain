import pytest

from wdchain.evidence.canonical import (
    CanonicalizationError,
    canonical_bytes,
    canonicalize_text,
    parse_json_strict,
)
from wdchain.evidence.merkle import keccak256


def test_key_order_and_whitespace_do_not_change_hash():
    a = '{"b":1,"a":{"y":2,"x":[1,2]},"c":"text"}'
    b = '{ "c" : "text",\n  "a" : { "x" : [ 1 , 2 ],  "y" : 2 },\t"b": 1 }\n'
    ca, cb = canonicalize_text(a), canonicalize_text(b)
    assert ca == cb == b'{"a":{"x":[1,2],"y":2},"b":1,"c":"text"}'
    assert keccak256(ca) == keccak256(cb)


def test_dict_insertion_order_irrelevant():
    assert canonical_bytes({"z": 1, "a": 2}) == canonical_bytes({"a": 2, "z": 1})


def test_utf8_output_not_escaped_and_escapes_normalized():
    assert canonicalize_text('{"s":"\\u00e9"}') == canonicalize_text('{"s":"é"}')
    assert canonicalize_text('{"s":"é"}') == '{"s":"é"}'.encode("utf-8")


def test_different_values_hash_differently():
    assert keccak256(canonicalize_text('{"a":1}')) != keccak256(canonicalize_text('{"a":2}'))


@pytest.mark.parametrize("bad", ['{"a": NaN}', '{"a": Infinity}', '{"a": 1e400}'])
def test_non_finite_numbers_rejected(bad):
    with pytest.raises(CanonicalizationError):
        canonicalize_text(bad)


def test_duplicate_keys_rejected():
    with pytest.raises(CanonicalizationError):
        parse_json_strict('{"a": 1, "a": 2}')
