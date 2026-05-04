# Implementation Notes

## Input format

This research uses **pre-prepared JSON** as v1 input — not raw PDF or text. The Kostenko investigation reports were manually decomposed into the 8-field argument schema before the pipeline runs.

@todo write a ipynb file to extract data from pdf and create json file for v1 input. ensure it also add `cause_categories` field to each argument. making it see the structure we are working it, so it can efficiently provide our json file 

- **Primary flow (Mode 1 of v1):** loads this JSON directly. This is what thesis evaluation uses.
- **Demonstration flow (Mode 2 of v1):** LLM-assisted extraction from raw text. Exists only to prove the pipeline *can* run end-to-end — not the main evaluation track.

Active file: [data/knowledge_base/kostenko_knowledge_base.json](data/knowledge_base/kostenko_knowledge_base.json)

## Expected JSON structure

Top-level shape:

```json
{
  "metadata": { ... },
  "arguments": [ ... ],
  "argumentation_framework": {
    "attack_relations": [ ... ],
    "support_relations": [ ... ],
    "open_questions": [ ... ]
  }
}
```

`arguments` is the v1 input. `argumentation_framework` holds the manually-annotated ground truth used to evaluate v5 output — it is *not* fed into the pipeline.

### Argument schema (8 fields)

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | Unique identifier, e.g. `U-A1`, `K-A4`, `D-A9` |
| `source` | string | Expert source code (`U`, `K`, `D` for Kostenko) |
| `topic` | string | Short topic label — used by v5 to filter candidate conflicts |
| `claim` | string | The assertion itself |
| `evidence` | string | Data / observations supporting the claim |
| `warrant` | string | Reasoning linking evidence to claim |
| `confidence` | float | Expert's confidence, `0.0`–`1.0` |
| `cause_categories` | list[string] | Taxonomy IDs from Rostechnadzor (e.g. `["TC-02", "OC-01"]`) |

Schema basis: Toulmin's argument model (claim + data/evidence + warrant), extended with `id`/`source`/`topic` for pipeline plumbing, `confidence` for downstream signaling, and `cause_categories` as the bridge to v2/v3.

## Field decisions (resolved 2026-04-20)

**`confidence` = float.** Architecture doc originally listed enum `{high, medium, low}`, but the data already uses floats (0.45–0.95) which are more expressive. v5's Dung semantics ignores confidence entirely — only the v6 report consumes it, so richer values are strictly better.

**`cause_categories` = required list.** This is the structural bridge between v1 and v2/v3:

- v2 aggregates categories across all arguments to classify the accident type
- v3 computes Jaccard overlap against precedents using these categories

Without this field, v2/v3 would have to re-parse free-text claims — defeating the purpose of structured input. Categories come from the Rostechnadzor taxonomy at [data/knowledge_base/rostechnadzor_regulatory_kb_v2.json](data/knowledge_base/rostechnadzor_regulatory_kb_v2.json): 13 technical (`TC-01`–`TC-13`) + 10 organizational (`OC-01`–`OC-10`).

## Current state of Kostenko file

- **21 arguments** present (4 Usembekov + 8 Kolikov-Meshcheryakov + 9 DMT) with all 8 fields including `cause_categories` after the 2026-04-27 backfill (see "Cause-categories backfill" section below)
- Also present: 4 attack relations, 5 support relations, 5 open questions (ground truth for v5 evaluation)
- The earlier "17 arguments" figure in CLAUDE.md and `system_architecture.json` is stale — the file actually contains 21

## Cause-categories backfill (2026-04-27)

The 21 Kostenko arguments were tagged with technical cause categories (`TC-*`) only. Final mapping committed to [data/knowledge_base/kostenko_knowledge_base.json](data/knowledge_base/kostenko_knowledge_base.json):

| Source | Argument range | Tags used (frequency) |
|-|-|-|
| Usembekov | U-A1..U-A4 | TC-02 (×2), TC-04 (×2), TC-05, TC-06 |
| Kolikov | K-A1..K-A8 | TC-01 (×4), TC-02, TC-03, TC-05, TC-07, TC-08 |
| DMT | D-A1..D-A9 | TC-01 (×3), TC-02 (×2), TC-04, TC-05, TC-06, TC-07, TC-08, TC-10 (×2) |

Three arguments (U-A1, U-A3, D-A4) carry **TC-04 (chemical ignition)** in addition to a primary tag. Reasoning: each substantively engages with chemical ignition sources (aerosol cans, synthetic oils, resin reactions). Tagging TC-04 makes them retrievable when v3's Jaccard CBR matches against precedents involving chemical ignition — e.g. PREC-2021-02 (Berezovskaya flotation-reagent fire, tagged TC-04).

### Why no organizational tags (OC-*)

None of the 21 Kostenko arguments make organizational claims — all are technical. The Kolikov-Meshcheryakov commission name might suggest organizational analysis, but K-A1–K-A8 are all technical (gas-dynamics, methane source, ignition source, electrical equipment, explosion mechanics).

This is a **conscious tagging choice with downstream implications**: v3 Jaccard matching against organizational-heavy precedents (e.g. PREC-2021-04 Listviazhnaya — tagged OC-01, OC-04) will produce low overlap scores. That's correct behavior — the Kostenko *evidence as currently extracted* doesn't support organizational claims, so we shouldn't fabricate matches. If future agents (especially Agent 2 — organizational and human factors) generate organizational claims from the same evidence, those agent-produced arguments will get OC-* tags and Jaccard against Listviazhnaya will rise. That's the system working correctly.

Adding OC-* tags to the existing expert-extracted arguments would require re-reading the original PDFs for organizational content — a separate task, not a simple tagging exercise.

## KB architecture — the "organized evidence room"

Mental model: the KB is what a human investigator would naturally build after being handed a stack of expert reports, regulations, and past cases — an organized space so the reasoning agents can find what they need. Three clean layers, each serving a different query pattern:

### Layer 1 — Domain knowledge (case-agnostic)

Regulations, cause taxonomy (`TC-*` / `OC-*`), accident type definitions. Never mentions any specific case. Loaded once, reused across every investigation.

Location: [data/knowledge_base/rostechnadzor_regulatory_kb_v2.json](data/knowledge_base/rostechnadzor_regulatory_kb_v2.json) → `domain_knowledge` block.

### Layer 2 — Precedent cases (indexed, case-agnostic)

Past accidents with known causes and outcomes. Each precedent carries a `similarity_profile` so v3 can compute Jaccard overlap against any new case at runtime — no manual per-case annotation needed.

Location: same file → `accident_precedents` block. Currently 11 Rostechnadzor cases (10 avarii + 1 group accident); architected to grow.

### Layer 3 — Active case workspace (populated per investigation)

The 21 Kostenko arguments plus their ground-truth attacks / supports / open questions. Loaded fresh for each investigation — this is what v1 ingests.

Location: [data/knowledge_base/kostenko_knowledge_base.json](data/knowledge_base/kostenko_knowledge_base.json).

## `similarity_profile` schema

Each precedent in Layer 2 carries this structured fingerprint, which v3 consumes for CBR matching. Values are boolean, categorical, numeric, or `null` (unknown / not published).

```json
{
  "accident_type": "methane_explosion | underground_gas_fire | coal_dust_explosion | gas_outburst | rock_burst | endogenous_fire | surface_fire | slope_failure | unknown",
  "work_type": "underground_development | underground_extraction | surface_processing | open_pit | unknown",
  "underground": true,
  "longwall_face_involved": true,
  "methane_involved": true,
  "companion_seam_involved": true,
  "goaf_accumulation": true,
  "coal_dust_involved": false,
  "spontaneous_combustion_involved": false,
  "ignition_source_identified": false,
  "ignition_type": "mechanical | electrical | chemical | unknown | none",
  "ventilation_failure": false,
  "degasification_failure": false,
  "outburst_hazard": false,
  "geological_hazard": false,
  "seismic_event": false,
  "roof_failure": false,
  "monitoring_failure": false,
  "data_falsification": false,
  "naryad_violation": false,
  "insufficient_supervision": true,
  "qualification_failure": false,
  "fatalities": 0,
  "mass_casualty": false
}
```

v3 must treat `null` as a non-match, not a false match (e.g. the two 2022 entries where Rostechnadzor did not publish details).

## Known limitations (to acknowledge in thesis writeup)

- **CBR depth.** 11 Rostechnadzor precedents is thin for meaningful case-based reasoning. The architecture is designed so adding more cases strictly improves agent performance with **no code change** — a new precedent just needs a populated `similarity_profile`. Production systems would benefit from hundreds of cases (e.g. MSHA's US database).
- **Domain knowledge outside the KB.** Layer 1 holds regulations and taxonomies but not mining engineering textbook content (methane explosive range, ventilation physics, equipment specs). Agents rely on LLM training data for this. A production system would need a curated domain knowledge sub-layer.

## Parked design questions (resolved by existing data)

Both were raised during early design and are effectively settled by what is already in the data — noted here so they are not relitigated:

- **Regulatory scope.** The regulatory layer covers all 8 Rostechnadzor accident types, not just methane / explosion. Already reflected in `accident_type_definitions` and `regulatory_requirements`.
- **Case-relevance mapping.** Precedents are pre-indexed via `similarity_profile`; v3 computes relevance at runtime via Jaccard overlap. No per-case manual annotation required.

## Implementation status (as of 2026-04-27)

### What's built (foundation)

| Layer | Files | Tests |
|-|-|-|
| Schema (data contracts) | `src/schema/`: `taxonomy.py`, `argument.py`, `precedent.py`, `ground_truth.py`, `classification.py`, `precedent_match.py` | 38 |
| KB (loader + store) | `src/kb/`: `loader.py`, `store.py` | 19 |
| Project config | `src/config.py` | 6 |
| v1 facade | `src/v1_decomposition/__init__.py` — Mode 1 (`decompose_from_json`) + Mode 2 stub (`decompose_from_text` raising `NotImplementedError`) | 5 |
| v2 identification | `src/v2_identification/__init__.py` — `classify`, `build_cause_to_type_index` | 10 |
| **v3 precedent matching** | `src/v3_precedent_matching/__init__.py` — `match_precedents` (two-step CBR: type filter + Jaccard) | 12 |
| Test infrastructure | `pyproject.toml` (pytest config, `pythonpath = ["src"]`), `tests/conftest.py` (KB path fixtures + `kostenko_with_bad_cause_id` synthetic-bad-data fixture) | — |
| **Total** | | **90 passing** |

The v1 facade is intentionally thin — it wraps `kb.loader.load_case_file` rather than reimplementing it, so there is one canonical loader (the KB layer) and v1's job is just to expose it as the official pipeline entry point with the two-mode contract documented.

### v1 design decisions

- **Two-mode API declared from day 1.** `decompose_from_text` exists with a `NotImplementedError` body so downstream code can be written against the final API today, and Mode 2's notebook implementation can be wired in without changing imports.
- **Single-file module.** `v1_decomposition/__init__.py` holds both modes. Will split into `mode1.py` / `mode2.py` only when Mode 2 grows beyond a handful of LOC.
- **Mode 2 stub points users at the workflow.** The `NotImplementedError` message names both the working alternative (`decompose_from_json`) and the in-progress workbench (`notebooks/v1_extract_arguments.ipynb`) so failures are self-documenting.

### v2 design decisions

- **KB-derived `cause_id → accident_type` mapping.** No hand-coded table. The mapping is built at runtime from the regulatory KB itself: each `Regulation` provides a Cartesian product of its `relevant_cause_categories` × `applies_to_accident_types`, and these pairs accumulate into the index. Adding regulations or changing `applies_to_accident_types` automatically updates v2 with no code change.
- **`"all"` sentinel excluded.** Regulations whose `applies_to_accident_types == ["all"]` (REG-08 naryad system, REG-09 production control, REG-11 owner liability) are skipped because they apply to every type and so do not disambiguate. A consequence: causes that appear *only* in `"all"`-type regulations (notably **OC-01**, only present in REG-09) carry no votes for type classification. This is deliberate — those organizational causes are universal rather than diagnostic of a specific accident type.
- **Loose coupling on input.** `classify()` takes a `regulations: dict[str, Regulation]` rather than the full `KnowledgeBase`. Caller passes either `kb.regulations` or `regulatory_kb_data.regulations`. Keeps v2 unaware of the KB-store class.
- **Voting model + secondary threshold.** Each cause-category occurrence in any argument votes for every accident type the index links it to. Most-voted = primary; runners-up at ≥ `secondary_threshold` × top_count = secondary (default 0.5). The threshold is a function parameter so callers can tune for their case (strict for unambiguous accidents, permissive for cascading events).
- **Output schema in `schema/classification.py`.** v2 returns a Pydantic `ClassificationResult` with `primary_type`, `secondary_types`, `cause_profile`, `type_votes`, and an `all_cause_categories` property that exposes the v3-Jaccard input set.

### v2 — Kostenko classification (verified)

Predicted in advance, then verified empirically — the numbers match exactly:

```text
Primary:    methane_explosion
Secondary:  ['underground_gas_fire']
Cause profile: {'TC-01': 7, 'TC-02': 5, 'TC-03': 1, 'TC-04': 3, 'TC-05': 3,
                'TC-06': 2, 'TC-07': 2, 'TC-08': 2, 'TC-10': 2}
Type votes:    methane_explosion: 25, underground_gas_fire: 20,
               surface_fire: 3, endogenous_fire: 3, gas_outburst: 2,
               coal_dust_explosion: 2
```

This matches the ground truth (methane fire that escalated into a methane explosion with subsequent coal dust propagation). The `surface_fire: 3` background is noise from TC-04 (chemical ignition) being type-ambiguous in the regulations — it appears in both REG-05 (underground methane/gas fire) and REG-14 (surface fire / hot work). Not a bug; just a transparency artifact of the KB-derived mapping.

### v3 design decisions

- **Two-step algorithm per architecture spec.** Step 1: filter precedents by accident type matching v2's `primary_type` or any `secondary_types`. Step 2: score each survivor by Jaccard overlap on cause_categories — `|shared| / |union|`.
- **Output schema in `schema/precedent_match.py`.** Returns a `PrecedentMatchResult` containing the ranked `matches` plus funnel telemetry (`total_precedents`, `filtered_count`) so callers / v6 can report "11 precedents in KB → 2 passed type filter → top match Listviazhnaya".
- **Each match records `matched_via`** (`"primary"` or `"secondary"`) so v6 can distinguish "this is a direct precedent for the dominant accident type" from "this is a precedent for a secondary accident type". Useful nuance in the report.
- **Threshold parameter** for the caller. Default 0.0 keeps every type-matched precedent (good for inspection); v6 will likely raise it (e.g. 0.3) for the public report so only meaningful matches surface.
- **`similarity_profile` not used in scoring.** The 25-flag profile sits on every precedent but Kostenko (and any case file) doesn't carry one. Folding it in as a tie-breaker would require either authoring a TC-* → profile mapping or having case files declare their own profile. Documented as a future enhancement.
- **Loose coupling on input.** `match_precedents()` takes a `list[Precedent]` directly (e.g. `kb.precedents`), not the whole KnowledgeBase.

### v3 — Kostenko ranking (verified)

```text
Total precedents in KB: 11
Passed type filter:     2

Ranked matches:
  1. PREC-2021-04 Listviazhnaya  (methane_explosion, primary)
     overlap_score: 0.0909  shared: ['TC-01']
  2. PREC-2024-01 Alardinskaya   (underground_gas_fire, secondary)
     overlap_score: 0.0769  shared: ['TC-01']
```

The ranking is correct (Listviazhnaya is the closest precedent — a methane explosion at a longwall coal mine), but the absolute Jaccard scores are low. This is a direct consequence of the deliberate tagging choice from the 2026-04-27 backfill: **Kostenko args carry only TC-* tags, while Listviazhnaya and Alardinskaya carry both TC and OC tags.** The union of cause sets is therefore inflated, the intersection is just TC-01, and Jaccard collapses to 1/11 and 1/13.

This is documented as a known artifact of current data, not an algorithm flaw. Two paths forward (either improves scores without code change):

1. **Add OC-* tags to Kostenko arguments** — requires re-reading the original PDFs for organizational content. A separate task.
2. **Add more precedents tagged similarly to Kostenko** — pure-TC methane explosions (e.g. detailed UBB extraction) would raise overlap with Listviazhnaya and reduce the OC-imbalance.

For thesis defense framing: the **ranking is correct on day one**; absolute scores will improve as the KB grows and as evidence extraction deepens. This is the system's designed scalability behavior.

### What's not built

- v4 (4 specialist agents), v5 (Dung's AF), v6 (LLM report) — the thesis contribution
- LLM scaffolding: `.env`, anthropic client wrapper, prompt management, structured logging
- v1 Mode 2 (LLM extraction) — stub in place; implementation in `notebooks/v1_extract_arguments.ipynb`

## Implementation roadmap

Ordered for unblocking and effort efficiency:

1. **Backfill `cause_categories` permanently into [data/knowledge_base/kostenko_knowledge_base.json](data/knowledge_base/kostenko_knowledge_base.json).** One-time data task. After this, the conftest backfill fixture is removed and the KB is the sole source of truth.
2. **v1 facade module** in `src/v1_decomposition/` — ~30 LOC wrapping `load_case_file`. Mode 2 (LLM extraction) deferred as demonstration only.
3. **v2 (identification) + v3 (precedent matching).** Both deterministic. v2 = aggregate `cause_categories` across all arguments → match against `accident_type_definitions`. v3 = Jaccard overlap of `cause_categories` against precedent `cause_categories`, plus `similarity_profile` boolean overlap as secondary signal. Ground truth obvious for both (Kostenko → `methane_explosion`).
4. **LLM scaffolding** — `.env` for API keys, anthropic client wrapper, prompt template loader, structured logging. Needed before v4 because 4 agents × multi-call interactions = manageable only with proper telemetry.
5. **v4 — 4 specialist agents.** Technical, Organizational, Challenger, Regulatory. Each gets RAG access to the KB and produces output in the same 8-field schema. Bulk of the thesis work.
6. **v5 — Dung's argumentation framework.** NetworkX `DiGraph`. Mostly algorithmic (grounded fixpoint, preferred maximal admissible sets). LLM only for confirming candidate conflict pairs from the topic-based filter.
7. **v6 — report generation.** LLM populates 7 report sections from v5 structured output. Markdown + HTML rendering.
8. **End-to-end Kostenko run + evaluation.** Compare v5 output against the 4 attack relations / 5 support relations / 5 open questions in the ground-truth `argumentation_framework`. Quantitative metrics on conflict detection accuracy.

Stretch (only after thesis-critical path is solid):

- **UBB second test case.** Extract from MSHA / McAteer / WV reports for generalizability evidence.
- **v1 Mode 2 demo.** LLM-assisted extraction from raw report text, evaluated against manual ground truth.

## Thesis weighting

- **v1–v3 are scaffolding** — defensive, deterministic, low novelty. Keep them simple and correct; no polish.
- **v4–v5 are the contribution.** Multi-agent LLM debate + Dung's semantics for conflict resolution is the original work. This is where time and writeup detail belong.
- **v6 + evaluation prove it works.** Critical for defense; not novel methodology.

The earlier-than-expected progress on v1 (because `kb/loader.py` already does it) means more budget for v4–v5.
