"""ADID v2 paths (D51): grammar, and compatibility with the frozen v1.0 grammar."""

from __future__ import annotations

import re
import uuid

import pytest

from src.identity.adid import SEGMENT_PATTERN, AdidIdentifier
from src.registry.ids import AdidFormatError, adid_path, new_adid, parse_path, variant_key


def test_three_levels_by_depth():
    fam, inst = new_adid(), new_adid()
    vk = variant_key("White", "XS")
    assert vk == "white_xs"
    assert parse_path(adid_path(fam))["level"] == "family"
    assert parse_path(adid_path(fam, vk))["level"] == "variant"
    assert parse_path(adid_path(fam, vk, inst)) == {"family": fam, "variant": vk, "instance": inst, "level": "instance"}


@pytest.mark.parametrize("bad", [
    "/adid/ts-1000",                                  # v1.0 style code, not a UUID
    f"/adid/{uuid.uuid4()}/white",                    # variant without size
    f"/adid/{uuid.uuid4()}/white_xs/sn-001",          # serial instead of an instance UUID
    f"/adid/{uuid.uuid1()}",                          # UUID v1 (time and MAC)
    "/adid/",
])
def test_invalid_paths_are_refused(bad):
    with pytest.raises(AdidFormatError):
        parse_path(bad)


def test_every_v2_path_is_a_valid_v1_path():
    """Each v2 segment satisfies the frozen v1.0 segment rule, and the frozen
    v1.0 parser reads a v2 path at the same level."""
    for _ in range(200):
        fam, inst = new_adid(), new_adid()
        vk = variant_key("Navy Blue", "XL")
        path = adid_path(fam, vk, inst)
        segments = path.strip("/").split("/")[1:]
        assert SEGMENT_PATTERN.match(segments[0]) and SEGMENT_PATTERN.match(segments[2])
        colour, _, size = segments[1].partition("_")
        assert SEGMENT_PATTERN.match(colour) and SEGMENT_PATTERN.match(size)
        for depth, level in ((1, "family"), (2, "variant"), (3, "instance")):
            partial = "/adid/" + "/".join(segments[:depth])
            assert AdidIdentifier.parse(partial).level == level


def test_v2_grammar_file_exists_and_v1_is_untouched():
    text = open("adid/grammar_v2.ebnf", encoding="utf-8").read()
    assert "PROPOSED, POST-FREEZE" in text
    assert re.search(r"family\s*=\s*uuid4", text) and re.search(r"instance\s*=\s*uuid4", text)
    import hashlib
    v1 = hashlib.sha256(open("adid/grammar.ebnf", "rb").read()).hexdigest()
    assert v1 == "92090c1c58e96efbbcc26d5f34c809114f88b6bb8e1c041dfba1f050a4f271a7"   # D30
