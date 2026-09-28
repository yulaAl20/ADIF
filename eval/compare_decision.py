"""Second design iteration: strict cascade vs evidence-aware reranking (D54).

Runs the same enabled stages under both decision rules on the **development**
schemas and reports precision, recall and F1 per schema, plus every column the
two rules decide differently. It refuses the sealed held-out directory, exactly
as the grid search does: the decision logic is designed on development data
only, and is evaluated on held-out data only after it is frozen.

    python -m eval.compare_decision                       # semantic stage off
    python -m eval.compare_decision --real-model          # with all-MiniLM-L6-v2 cached

Without ``--real-model`` the semantic stage is switched off for BOTH rules,
never replaced by the stub embedder: a hash-based similarity is noise, and a
comparison that contains it compares nothing.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.grid_search import _refuse_sealed
from src.config import effective_fingerprint
from eval.metrics import mapping_f1
from eval.runner import build_context, discover_schemas, load_gold_standard, load_overlay, run_schema

CONDITIONS = {
    "cascade": "config/ablation/full_cascade_value.yaml",
    "rerank": "config/ablation/rerank_v2.yaml",
    "rerank_aliases_v1_1": "config/ablation/rerank_v2_aliases_v1_1.yaml",
}


def run(schemas_dir: Path, gold_dir: Path, real_model: bool) -> dict[str, Any]:
    """Score both decision rules on every development schema that has a gold standard."""
    _refuse_sealed(schemas_dir)
    out: dict[str, Any] = {"conditions": {}, "differences": [], "alias_correction_differences": []}
    decisions: dict[str, dict[str, dict[str, str]]] = {}
    for name, overlay in CONDITIONS.items():
        cfg = load_overlay(overlay_path=overlay)
        if not real_model:
            cfg.matching.stages.semantic.enabled = False
        context = build_context(cfg, real_model=real_model)
        per_schema, totals = {}, {"p": [], "r": [], "f1": []}
        for path in discover_schemas(schemas_dir):
            gold_path = gold_dir / f"{path.stem}.json"
            if not gold_path.is_file():
                continue
            gold = load_gold_standard(gold_path).mappings
            result, _ = run_schema(path, context)
            p, r, f1 = mapping_f1(result, gold)
            per_schema[path.stem] = {"precision": p, "recall": r, "f1": f1}
            for key, val in zip(("p", "r", "f1"), (p, r, f1)):
                totals[key].append(val)
            decisions.setdefault(path.stem, {})[name] = {
                rec.raw_header: (rec.target_field, rec.deciding_stage.value, gold.get(rec.raw_header, "?"),
                                 rec.notes or "")
                for rec in result.records
            }
        n = max(1, len(totals["f1"]))
        out["conditions"][name] = {
            "overlay": overlay,
            "stages": cfg.enabled_stages(),
            "decision": cfg.matching.arbitration,
            "embedder": context.embedder_name,
            "fingerprint": effective_fingerprint(cfg, None if context.embedder_name == "none" else context.embedder_name),
            "macro": {k: round(sum(v) / n, 4) for k, v in (("precision", totals["p"]), ("recall", totals["r"]), ("f1", totals["f1"]))},
            "per_schema": per_schema,
        }
    for schema, by_rule in decisions.items():
        for header, (c_target, c_stage, gold, _) in by_rule["cascade"].items():
            r_target, r_stage, _, note = by_rule["rerank"][header]
            a_target, a_stage, _, a_note = by_rule["rerank_aliases_v1_1"][header]
            if a_target != r_target:
                out["alias_correction_differences"].append({
                    "schema": schema, "column": header, "gold": gold,
                    "rerank_v1_0_aliases": f"{r_target} ({r_stage})",
                    "rerank_v1_1_aliases": f"{a_target} ({a_stage})", "why": a_note,
                })
            if c_target != r_target:
                out["differences"].append({
                    "schema": schema, "column": header, "gold": gold,
                    "cascade": f"{c_target} ({c_stage})", "rerank": f"{r_target} ({r_stage})",
                    "better": "rerank" if r_target == gold else "cascade" if c_target == gold else "neither",
                    "why": note,
                })
    return out


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(prog="python -m eval.compare_decision")
    parser.add_argument("--schemas", type=Path, default=Path("data/dev"))
    parser.add_argument("--gold", type=Path, default=Path("goldstandard"))
    parser.add_argument("--real-model", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("runs"))
    args = parser.parse_args(argv)
    result = run(args.schemas, args.gold, args.real_model)
    for name, cond in result["conditions"].items():
        print(f"{name:8} {cond['stages']} decision={cond['decision']} embedder={cond['embedder']}")
        print(f"         macro P/R/F1 = {cond['macro']['precision']:.3f} / {cond['macro']['recall']:.3f} / {cond['macro']['f1']:.3f}")
        for schema, m in cond["per_schema"].items():
            print(f"           {schema:32} {m['precision']:.3f} {m['recall']:.3f} {m['f1']:.3f}")
    print(f"\n{len(result['differences'])} columns decided differently:")
    for d in result["differences"]:
        print(f"  [{d['better']:7}] {d['schema']}: {d['column']!r}  gold={d['gold']}  cascade={d['cascade']}  rerank={d['rerank']}")
    print(f"\n{len(result['alias_correction_differences'])} columns changed by the v1.1 alias correction:")
    for d in result["alias_correction_differences"]:
        print(f"  {d['schema']}: {d['column']!r}  gold={d['gold']}  v1.0={d['rerank_v1_0_aliases']}  v1.1={d['rerank_v1_1_aliases']}")
    record = {
        "status": "DEVELOPMENT (design-time comparison on development schemas; NOT an evaluation result)",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "real_model": args.real_model,
        **result,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"dev_decision_compare_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"\nRecord: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
