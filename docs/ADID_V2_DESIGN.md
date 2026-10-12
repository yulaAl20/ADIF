# ADID v2: proposed post-freeze identity design

**Status:** proposed, post-freeze (decisions.md D51–D53, 2026-10-12)
**Evaluated version:** ADID v1.0 (`adid/grammar.ebnf`), which is unchanged and hash-checked against D30
**Run record:** `runs/registry_eval_20261012T105859Z.json`

---

## 0. Boundary: what is the contribution, and what is the demonstration

The research contribution is the framework's three parts:

1. **ADID**: identity and hierarchical resolution.
2. **CDM**: canonical product data and its JSON-LD representation.
3. **Hybrid interoperability gateway**: maps heterogeneous manufacturer data through a calibrated four-stage cascade.

The website (`src/web`) and the registry service (`src/registry`) are an **implementation and demonstration** of those three parts. They are not a further contribution.

The evaluated version stays frozen:

- The matching evaluation (D34) ran on v1.0. Nothing here changes the cascade, the CDM, the alias vocabulary, the value signatures, the thresholds or the calibrator.
- `/admin` recomputes the D30 hashes so the boundary is checkable (D53).
- `config/calibrator.json` shows "same content (line endings)": the D30 hash was taken from the CRLF copy on the Windows machine that froze the study; the repository copy is LF and otherwise byte-identical (D58).

ADID v2 is a **proposed revision** of the identity specification. It is documented and tested here. It has not been substituted into the evaluated specification. Adopting it formally would mean revising Chapter 3 and re-running the identity evaluation, which has been done on synthetic data (§9). The matching evaluation does not need re-running, because it never depended on the identifier.

## 1. Why a v2

The supervisor's brief asked for globally unique identifiers, attributes held as metadata, public lookup, discovery and stability. Measured against that brief, v1.0 has four limits:

- **The family segment is a style code.** It is unique only within one manufacturer's namespace (`dpp.{manufacturer}` host), and it changes if the style is renamed.
- **The instance segment is a serial number.** Serials are unique only within a GTIN or a factory.
- **The variant segment is computed from live attributes.** Correcting "navy" to "navy blue" changes the address. Across 528 v1.0 addresses, none survived one round of corrections (E4).
- **The v1.0 resolver returned structure only.** No passport was stored or served (issue 2).

ADID v2 keeps v1.0's **three levels and depth rule**. It changes only what fills two segments, and it freezes the third at issuance.

## 2. Identifier model

| Level | Path | Segment | Issued from | Changes after issuance? |
|---|---|---|---|---|
| Family | `/adid/{familyUUID}` | random UUID v4 | registration of a new `productFamily` | No |
| Variant | `/adid/{familyUUID}/{colour}_{size}` | `slug(colour)_slug(size)`, unique within the family | colour and size **at registration** | No. Later colour or size corrections update the record, not the segment |
| Instance | `/adid/{familyUUID}/{colour}_{size}/{instanceUUID}` | random UUID v4 | registration of a `serialNumber` | No |

**The variant is globally distinguishable** because its full path combines a globally unique family UUID with a colour–size segment that is unique within that family. The variant also gets its own UUID, exposed as public metadata (`variantId`). A bare variant UUID at depth 1 redirects (301) to the canonical path.

**Why version 4 UUIDs.** They carry 122 random bits and nothing else. Versions 1, 6 and 7 leak time (and for v1, hardware). Versions 3 and 5 derive from names, which would put attribute dependence back. The collision probability for 10¹² families is about 10⁻¹³.

**Batch is CDM data, not identity.** This restores D22's option 3 and supersedes D44.

- A serialised item carries `batchNumber` and the other batch fields in its record.
- An unserialised variant lists every lot seen.
- The **lot query** (`/lot/{batchNumber}`, `/portal/lot`) lists everything recorded under one lot. It is restricted to the owning manufacturer and to authorities.

**Alternate identifiers** are stored alongside the record:

- GTIN on the variant, and GTIN + serial (SGTIN) on the instance. These are also indexed at the root for `/01/…` resolution.
- `family_code` (registrar + style code).
- `sku`.
- The v1.0-style readable `alias` (`registrar/style/colour_size`). Aliases are never removed. After a correction the old alias keeps resolving, and the new one is added beside it.

## 3. Grammar and compatibility

`adid/grammar_v2.ebnf`:

```
adid-path = "/adid/" family [ "/" variant [ "/" instance ] ] ;
family    = uuid4 ;
variant   = colour "_" size ;      (* unchanged from v1.0 *)
instance  = uuid4 ;
```

**Compatibility with the frozen v1.0 grammar:**

- **Path: compatible.** A lowercase UUID satisfies v1.0's `segment` rule (alphanumeric, then alphanumeric or `-`). Every v2 path is therefore a valid v1.0 `adid-path`.
- **Tested.** `tests/unit/test_adid_v2.py` checks 200 generated paths at each depth against the frozen v1.0 parser (`AdidIdentifier.parse`). It also asserts that the v1.0 grammar file still has its D30 hash.
- **Host: one deliberate difference.** v1.0 fixes `dpp.{manufacturer}`. v2 allows any registry resolver host, because the family UUID no longer needs the manufacturer name for uniqueness.
- **Still owed:** a GS1 Digital Link syntax validation of linked URIs and a reading of EN 18219. Neither conformance claim is made.

## 4. Resolution and interoperability

| Request | Answer |
|---|---|
| `GET /adid/{family}[/{variant}[/{instance}]]`, browser | Product page (HTML) |
| Same URI with `Accept: application/ld+json`, or `?view=dpp` | JSON-LD passport (CDM vocabulary). `@id` = the ADID URI. Inherits family, then variant, then instance data |
| Same URI, any other client | JSON registry record |
| `GET /01/{gtin}[/21/{serial}]` | 303 to the variant or instance path |
| `GET /alias/{registrar}/{style}/{colour_size}` | 303 to the path |
| An ADID held on another registry node | 307 to that node, located through the root index by family UUID |
| `GET /id/{uuid}/neighbourhood`, `/history`, `/verify`, `/related` | Record tools, kept out of `/adid/` so the identifier namespace stays clean |

## 5. Neighbourhood (D49, revised)

| Group | Source | Who sees it |
|---|---|---|
| Up | `variantOf` / `instanceOf` (the path spells the same thing) | Everyone |
| Down | The inverse relations | Variants: everyone. Instances: owner and authorities |
| Siblings | Other children of the same parent | Same rule as Down |
| Same lot | Restricted `batchNumber` facet | Owner and authorities |
| Similar | Normalised category and colour, other families, any manufacturer | Everyone (families and variants only) |

## 6. Registry topology

The topology is a **root index plus nodes** (D45, unchanged in principle):

- The root maps a family UUID, and each public GS1 key, to its home node.
- A family's variants and instances share the family's node, because their paths begin with the family UUID.
- `Federation.move` re-homes a whole family subtree. Paths do not change, histories move byte for byte, and the old node keeps `moved` tombstones.

| | Centralised | Prefix-delegated (DOI) | **Root index + nodes (built)** | Fully distributed |
|---|---|---|---|---|
| Identifier carries meaning | No | Registrar prefix | **No** | No |
| Survives a node moving | n/a | Re-point the prefix | **Yes: E4, 242 entities moved, 100% still resolve** | Yes |
| Root cost | n/a | Per prefix | **About 200 bytes per placement (E6)** | n/a |
| Control point | Operator | Prefix authority | Root (holds no product data) | Diffuse |

## 7. Change control (D53)

| Object | Editable? | Behaviour, as implemented |
|---|---|---|
| ADID identifier and path | No | Issued once and never reassigned. No form field or endpoint accepts it. Withdrawal leaves a tombstone (HTTP 410) |
| Product attributes | Yes | Owner only. Each save is a new revision sealed into the hash chain. Earlier revisions are viewable with a field-by-field diff (`/id/{uuid}/v/{n}`) |
| Published DPP | Yes, under policy | Generated from the current record. `adid:recordVersion` identifies the revision, and corrections are traceable through the history |
| Barcode / serial binding | Restricted | Can be added, never removed or reassigned. `gtin`, `serialNumber`, `batchNumber` and `productFamily` are read-only in the portal. Errors are fixed by the documented withdraw-and-replace procedure (`replaced_by`) |
| Manufacturer template | Yes | Saving under an existing name adds a revision. Restoring copies an old revision forward. Private to the registrar |
| Shared CDM vocabulary | Not through the manufacturer UI | Governed separately as a versioned release (`cdm_v1.0`). The edit form offers only existing CDM fields |
| Frozen research modules | No, for the evaluated version | Hashes are recomputed on `/admin` against D30. A mismatch is shown, not hidden |

## 8. Access, governance and wording (D52)

- **One application with role-based access control and manufacturer-level isolation:**
    - `/` and `/registry`: public.
    - `/portal`: authenticated manufacturers, each seeing only its own records and templates.
    - `/admin`: the registry operator.
    - The same server enforces every rule, through the policy in `config/registry.yaml`.
- **Account approval is prototype governance, not official accreditation.**
- **Wording rules for the site:**
    - It must not imply a legally designated DPP authority, certification, guaranteed compliance, fully accurate mapping, an official universal identifier, or unbreakable QR codes.
    - `tests/unit/test_web.py::test_site_avoids_overclaiming_phrases` checks the public pages.

## 9. Evaluation of ADID v2 (E1–E8)

The data is synthetic: five registrars on two nodes, 100 families, 883 variants and 2,649 instances, seeded with 2026. Ground truth comes from the generator. The run was on 2026-10-12 in the development workspace. **Re-run on the NFR-3 laptop before citing timings:**

```
python -m eval.registry_eval --sizes 1000 10000 50000
```

| Property | Result |
|---|---|
| E1 Uniqueness | 0 duplicates in 3,632 IDs, all UUID v4; every GTIN bound to exactly one variant |
| E2 Resolvability | 100% for ADIDs, GTINs and SGTINs. HTTP local p50 4.0 ms; cross-node (one 307) p50 7.6 ms |
| E3 Discovery | Variants of a family: P = R = 1.00 (883). Items in a lot, authority: P = R = 1.00 (2,649). Colour + size: registry search R 0.973 against exact-string R 0.275. Category across nodes: 1.00 for both |
| E4 Stability | **v2 paths unchanged after corrections: 704 of 704. v1.0 paths: 0 of 528.** Old v2 paths open the corrected record: 100%. Old v1.0 paths resolve through the retained alias: 100%. After 6 families (242 entities) moved and a node re-hosted: paths 100% unchanged, 100% resolvable, histories verify 100% |
| E5 Interoperability | 0 JSON-LD → RDF errors in 150 passports; 145 of 145 GS1 Digital Links well-formed; 0 CDM type/format errors |
| E6 Scalability | 766 / 7,601 / 38,294 entities. 1,070–1,300 registrations/s; resolve p50 0.15–0.22 ms; search p50 0.14–2.3 ms; about 4 kB per entity |
| E7 Privacy | 0 restricted fields or instance links in 3,632 public views. Public instance search and public lot queries blocked. 0 of 10,000 random guesses resolved |
| E8 Governance | 200 of 200 tampering attempts detected (metadata, alternate ID, relation, history rewrite, history deletion); 0 false positives in 500 |

**How to read these results:**

- Several results hold by design, not by measurement: UUID uniqueness, hash-chain detection, and v1.0's 0%, since every correction touched colour or size. They verify the implementation.
- The informative comparisons are E4 (v2 against v1.0 under identical corrections) and E3 Q2 (normalised search against exact matching).
- The noise model and the normaliser share an author. The 2.7% still missed is the "Grey"/"Gray" spelling variant, which surface normalisation cannot fix.
- An earlier run (`runs/registry_eval_20261012T063720Z.json`) measured an intermediate design: pure UUIDs at every level, with batch as an entity. That design was superseded by D51 the same day. It is kept for the record and is not to be cited as ADID v2.

## 10. Limitations

1. ADID v2 is a proposal. The thesis's evaluated identity specification remains v1.0 unless Chapter 3 is formally revised.
2. The v2 evaluation uses synthetic data, with no Sri Lankan manufacturer's catalogue (issue 4).
3. The variant segment freezes the colour and size *as first registered*. After a correction, the path shows the original values, by design, and the record shows the current ones. This must be explained to users.
4. Variants without colour and size cannot be issued (v1.0 rule kept); such rows register at family level only.
5. Discovery normalises surface forms only, not synonyms.
6. The hash chain detects tampering but does not prevent it. There are no signatures or verifiable credentials.
7. The root index is a single, unreplicated SQLite file. Federation is shown in-process and by redirect, not across real networks.
8. GS1 Digital Link and EN 18219 conformance are not claimed.
9. The resolver host `id.adir.example` is illustrative. Who would run a real root is a governance question the thesis raises but does not settle.
