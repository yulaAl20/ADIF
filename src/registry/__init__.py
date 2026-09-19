"""ADID registry — the resolution layer for ADID v2 (D51, proposed post-freeze).

Resolves the three research identity levels with globally unique, opaque
identifiers and explicit registry relationships:

    family    /adid/{familyUUID}
    variant   /adid/{familyUUID}/{colour}_{size}     (variant UUID kept as metadata)
    instance  /adid/{familyUUID}/{colour}_{size}/{instanceUUID}

ADID v2 is a proposed post-freeze design. The evaluated specification is
ADID v1.0 (adid/grammar.ebnf, unchanged); every v2 path is also a valid v1.0
path (tests/unit/test_adid_v2.py). Product data lives in CDM records behind the
identifier, versioned; identifiers are issued once and never reassigned.

Modules:
    ids          UUID minting, ADID v2 paths (adid_path, parse_path, variant_key)
    gs1          GTIN normalisation and GS1 Digital Link URIs (interoperability)
    policy       information sections and field-level access tiers
    store        the SQLite registry: entities, alternate IDs, relations,
                 hash-chained history
    federation   root index and multi-node resolution
    registration gateway output → family / variant / instance registrations
    api          the public resolver / registrant REST API
"""
