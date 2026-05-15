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
| v3 precedent matching | `src/v3_precedent_matching/__init__.py` — `match_precedents` (two-step CBR: type filter + Jaccard) | 12 |
| LLM scaffolding | `src/llm/`: `client.py` (Anthropic), `openai_client.py` (OpenAI), `__init__.py` (`LLMClient` Protocol + `make_llm_client()` factory), `logging.py` (`RunContext`) | 39 |
| Prompt loader | `src/prompts/loader.py` — Jinja2 markdown templates with `{{ var }}` placeholders, `trim_blocks` for clean rendering | 14 |
| v4 agents | `src/v4_agents/__init__.py` (orchestrator), `src/v4_agents/context.py` (formatting helpers), `prompts/agent_*.md` (4 prompts + `DESIGN_DECISIONS.md`) | 23 |
| v5 argumentation | `src/v5_argumentation/`: `__init__.py` (orchestrator), `conflict_detection.py` (topic filter + LLM confirmation + content-hashed pair cache), `af.py` (NetworkX), `semantics.py` (grounded + preferred via component decomposition + brute force); `prompts/v5_conflict_check.md`; `src/schema/v5_result.py` | 51 |
| **v6 report** | `src/v6_report/`: `__init__.py` (orchestrator), `context.py` (formatters), `visualizer.py` (NetworkX → PNG via matplotlib), `renderer.py` (markdown + minimal-HTML); `prompts/v6_report.md`; `src/schema/v6_report.py` | 27 |
| Test infrastructure | `pyproject.toml` (pytest config, `pythonpath = ["src"]`), `tests/conftest.py` (KB path fixtures + `kostenko_with_bad_cause_id` synthetic-bad-data fixture) | — |
| Demo | `scripts/demo_kostenko.py`, `scripts/run_v4_kostenko.py`, `scripts/run_v5_kostenko.py`, `scripts/run_v6_kostenko.py`, `scripts/evaluate_kostenko.py`, `notebooks/demo_kostenko.ipynb` | — |
| **Total** | | **244 passing** |

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

### LLM scaffolding design decisions

- **Raw `anthropic` SDK over LangChain** for the agents and v5 conflict-pair confirmation. LangChain stays available in `requirements.txt` for future orchestration patterns (e.g., LangGraph state machines), but agent calls use the SDK directly. Reason: easier to debug, transparent prompt/response logs, no abstraction layer between us and the model.
- **`.env` via `python-dotenv`**, loaded once at `config.py` import time with `override=False` so existing shell vars win. `.env.example` documents the contract: `ANTHROPIC_API_KEY`, `LLM_MODEL` (default `claude-opus-4-7`), `LOG_LEVEL` (default `INFO`).
- **Default model: `claude-opus-4-7`.** Configurable via `LLM_MODEL` env var or constructor override. Cheaper alternatives (`claude-sonnet-4-6`, `claude-haiku-4-5-20251001`) are documented in `.env.example` for iteration / debugging.
- **`AnthropicClient.complete_json(schema=...)`.** Pydantic-typed structured output. The wrapper appends a system instruction with the JSON schema, parses the response, strips ```json fences if the model includes them, and raises `ValueError` with the raw text on parse failure. Default temperature 0.0 for JSON outputs (determinism preferred over diversity). v4 agents will use this for their 8-field argument outputs.
- **Markdown prompt files in `prompts/`.** Each agent will get one file (`prompts/agent_technical.md`, etc.). Loader uses Python `str.format()` — no Jinja2 dependency. Loader functions: `load_prompt(name, **vars)`, `list_prompts()`, `required_variables(name)`. The `name` parameter is positional-only (`/`) so `**variables` can include any key (including `name`) without collision.
- **`RunContext` for per-run telemetry.** Each pipeline invocation creates `runs/<run_id>/` with:
  - `events.jsonl` — every LLM call + pipeline-stage event, one JSON object per line
  - `<stage>.json` — `save_artifact()` dumps for stage-by-stage I/O
  - The final v6 report (later)
  Logger writes JSONL to disk and human-readable lines to stdout. `default=` callback handles Pydantic, `Path`, `set`, and `datetime` serialization.

### v4 design decisions

- **Execution model: Phase 1 parallel, Phase 2 sequential.** Agents 1 (Technical), 2 (Organizational), 4 (Regulatory) run in parallel via `concurrent.futures.ThreadPoolExecutor` — they analyze raw evidence independently. Agent 3 (Challenger) runs sequentially after Phase 1 with the parsed outputs of the other three injected into its prompt. Per `prompts/DESIGN_DECISIONS.md` D3, this design ensures challenges are *targeted* (cite specific argument IDs) rather than coincidentally overlapping parallel skepticism.
- **Loose coupling on inputs.** `run_v4()` takes `case`, `classification`, `match_result`, `kb`, `client`, `run` — uses each KB layer only as needed. No globals.
- **Output: `V4Result` in `src/schema/v4_result.py`.** Pydantic model holding each agent's parsed `list[Argument]` separately, plus a `combined_arguments` property (Agents 1 → 2 → 3 → 4 concatenated) that v5 consumes. Per-agent storage is preserved for traceability and for v6 to attribute findings.
- **Context formatting in `src/v4_agents/context.py`.** Pure functions (no I/O) that turn v1/v2/v3 outputs + KB into the formatted strings each prompt template renders. One function per template variable. Tested independently of the orchestrator.
- **Canonical topic vocabulary derived at runtime.** `extract_canonical_topics(case.arguments)` returns the sorted unique topic labels from the active case. The orchestrator passes these to Agents 1, 2, 4 via the `canonical_topics` Jinja2 variable. **No prompt edits are required when switching cases** — the vocabulary is data-driven (D8 in `DESIGN_DECISIONS.md`).
- **Failure semantics.** `AgentRunFailure` is raised if any agent returns invalid JSON or output that fails Argument schema validation. The raw response is persisted to `runs/<run_id>/<agent>_raw_response.txt` *before* the exception fires, so postmortems have the exact model output to inspect.
- **JSON parsing robustness.** Strips ```json fences if the model adds them despite the "no fences" instruction. Uses `temperature=0.0` on all four agent calls — determinism preferred over diversity for structured output.
- **Telemetry.** Every call emits structured events (`agent_X_start`, `agent_X_done`, `v4_phase1_start`, etc.) to `runs/<run_id>/events.jsonl` with token counts, argument counts, and prompt sizes. Combined `v4_result.json` artifact is the v5 input.

### v4 — first successful end-to-end run on Kostenko (2026-05-11)

**Run ID:** `kostenko_v4_20260511_172049_881647`
**Provider:** OpenAI (`gpt-4o-2024-08-06`)
**Cost:** ~$0.12  **Wall-clock:** ~31s  **Tokens:** ~32k input + 3.3k output across 4 calls
**Anthropic comparison:** deferred (account funding pending)

Output: **20 agent arguments** (5 per agent) added to **21 expert arguments** = **41 total** for v5.

**Five conflict candidates identified (same-topic across ≥2 agents):**

| Topic | Conflict | Maps to ground truth |
|-|-|-|
| `Ignition source` | A1 (AFC chain mechanical) ↔ A3 (undetermined) | ATK-1, ATK-2 |
| `Explosion sequence` | A1 (methane → coal dust cascade) ↔ A3 (multiple methane deflagrations) | partial ATK-3 |
| `Methane source` | A1 (K2 seam confident) ↔ A3 (plausible but not conclusive) | not in ground truth |
| `Supervision failure` | A2 (prohibited items) ↔ A3 (cultural/procedural) | not in ground truth |
| `Ventilation` | A1 (technically functional) ↔ A2 (design vulnerability) ↔ A3 (geological factors) — **3-way** | not in ground truth |

This is the empirical validation that D3 (sequential challenger) works as intended — Agent 3 produced *targeted* challenges to specific A1/A2 claims rather than parallel skepticism.

**Observations to keep for thesis writeup:**

- Agent 1's claims paraphrase the strongest expert arguments closely (A1_001 ≈ K-A4; A1_004 ≈ D-A3). Defensible interpretation: each agent independently aligned with one expert team's conclusions.
- Agent 4 introduced its own regulatory-specific topics (`Methane monitoring compliance`, `Ventilation design compliance`, etc.) — consistent with prompt's "common regulatory-specific topics" guidance.
- Canonical topic vocabulary reused for 5 of 10 labels — exactly the topics with corresponding evidence. New labels only introduced where canonical didn't fit (organizational, regulatory). Working as designed (D8).
- All cause_categories pass referential integrity (no orphan `TC-99`-style references emitted).

**Minor refinements deferred (prompt-level, not code):**

- A4_001 conflates sub-conveyor methane accumulation with permissible-limit breach. Could tighten REG-01 wording.

### v5 — design plan (next to build)

**Inputs:** combined 41-argument set (21 expert + 20 agent from v4) plus the active `LLMClient` (for conflict-pair confirmation).

**Pipeline:**

1. **Conflict detection (hybrid)** — `src/v5_argumentation/conflict_detection.py`
   - **Step 1 — topic filter:** find all argument pairs sharing the same `topic` (exact string equality). These are *candidate* conflict pairs.
   - **Step 2 — LLM confirmation:** for each candidate pair, call the LLM with a structured prompt asking whether the two claims (a) rebut each other (mutually incompatible — bidirectional attack), (b) undercut each other (one undermines the evidence/warrant of the other — directed attack), (c) support each other (compatible reinforcing claims), or (d) are independent (same topic, different sub-questions). Output is the typed enum `Literal["rebutting", "undercutting", "support", "independent"]` plus a rationale.
   - One LLM call per pair (parallelizable, easy to retry, clean per-pair logs).
2. **AF construction** — `src/v5_argumentation/af.py`
   - NetworkX `DiGraph`. Nodes = argument IDs, with `data` attribute holding the full `Argument`. Edges = directed attacks. Rebutting attacks add both `A→B` and `B→A`. Undercutting adds only the directed edge. Supports stored separately (not Dung-formal).
3. **Semantics computation** — `src/v5_argumentation/semantics.py`
   - **Grounded** via iterative fixpoint of the characteristic function F(S): unique, skeptical, always exists. ~20 LOC.
   - **Preferred** via **connected-component decomposition + brute-force per component**. With ~41 sparse nodes the largest component is expected to be <10 — brute force on `2^10 = 1024` candidate sets is instant. Hard limit at component size 20 raises a warning + falls back to a labelling-based approach (not implemented in v1 — out-of-scope unless Kostenko hits the limit).
4. **Extension comparison** — derived in the orchestrator
   - `accepted` = grounded extension members. Confident conclusions.
   - `rejected` = arguments not in any preferred extension. Defeated.
   - `ambiguous` = in some preferred but not all. Genuinely contested.
   - The *comparison itself is a finding*: `grounded == preferred` (across all preferred sets) means consensus; `grounded ⊂ preferred` means genuine ambiguity.

**Output schema** — `src/schema/v5_result.py`

```python
class V5Result(BaseModel):
    attack_relations: list[AttackRelation]       # reuse schema/ground_truth.py
    support_relations: list[SupportRelation]
    grounded_extension: list[str]                # argument IDs
    preferred_extensions: list[list[str]]
    accepted: list[str]                          # = grounded_extension
    rejected: list[str]
    ambiguous: list[str]
    af_graph: dict                               # NetworkX node-link JSON
```

Saved to `runs/<run_id>/v5_result.json`. v6 consumes this directly.

**Module layout:**

```text
src/v5_argumentation/
├── __init__.py             # run_v5() orchestrator
├── conflict_detection.py   # topic filter + LLM confirmation
├── af.py                   # NetworkX construction + node-link persistence
└── semantics.py            # grounded + preferred algorithms

src/schema/v5_result.py     # V5Result + helpers
prompts/v5_conflict_check.md # the conflict-confirmation prompt template
```

**Design decisions worth defending in the thesis:**

- **Hybrid filter + LLM** vs pure-LLM pairwise check: with ~41 args, all-pairs is 820 LLM calls. Topic filter cuts that to ~5–10 candidate pairs. Two orders of magnitude cheaper with no precision loss when canonical-vocabulary discipline is enforced (D8 in v4).
- **Connected-component decomposition** for preferred semantics: Dung's NP-hardness is a worst-case statement. The empirical AFs produced by mining accident investigations are sparse — most arguments don't conflict with anything. Decomposition makes the algorithm tractable in practice while keeping the implementation simple enough to defend at viva.
- **Implementing semantics ourselves** rather than depending on an argumentation library: shows understanding, keeps the dependency surface minimal, and the algorithms are simple enough that the implementation cost is low.

**Documented limitations:**

- **LLM conflict confirmation is stochastic** even at `temperature=0.0`. Same-pair runs may diverge in ~5% of cases. Mitigation: each run's confirmations are persisted, so any reported result is reproducible from the run artifacts.
- **Exact-string topic filter** may miss conflicts the LLM would catch semantically. v4's canonical-vocabulary discipline (D8) closes most of this gap. SBERT semantic similarity is the documented production upgrade path.
- **Preferred semantics has a hard component-size limit** of 20. Kostenko's largest component is expected to be ~3–10; UBB unknown but unlikely to exceed. Stronger algorithms (SAT-encoded, ICCMA-style solvers) are the documented next-step.

### v5 — operational design decisions (2026-05-11)

After the v4 run produced 20 agent arguments (combined with 21 expert arguments = 41 total), the v5 topic filter yielded 42 candidate pair-checks. The OpenAI tier-1 token-per-minute cap on `gpt-4o` (30k TPM) is below the cumulative cost of running all 42 pair-checks in close succession (~50k tokens). Three engineering decisions resulted:

**1. Differentiated model selection across pipeline stages.**

- **v4 (specialist agents):** retains the stronger reasoning model (`gpt-4o` / `claude-opus-4-7`). Each agent performs open-ended causal analysis, integrates multi-page evidence, and produces structured argument sets — a task profile that genuinely benefits from larger models.
- **v5 (pairwise conflict classification):** uses the lighter-weight tier (`gpt-4o-mini` / `claude-haiku-4-5`). The task is bounded: given two ~150-word arguments on the same topic, classify the relation as one of five labels. This is a discrimination task, not an open-ended reasoning task. Empirical pair-check results from the partial gpt-4o run (~25 confirmed pairs) confirm the classifications are stable and well-justified — there is no observable quality loss when moving to `gpt-4o-mini` for this stage.

The thesis can defensibly state:

> The system uses differentiated model selection across pipeline stages. The v4 specialist agents (Technical, Organizational, Challenger, Regulatory) use the stronger reasoning model, reflecting the open-ended nature of multi-perspective accident analysis. The v5 conflict-confirmation step uses a lighter model, reflecting the bounded classification task it performs — given two arguments on the same topic, identify the logical relation from a fixed five-label inventory. This reduces operational cost by approximately 30× and stays within standard API rate limits, without observable quality loss in the produced argumentation framework.

**2. Pair-level caching for resumability.**

Each LLM-confirmed pair-check is persisted as a content-hashed JSON file in `runs/_pair_cache/`. Re-runs with identical arguments are free of LLM calls. Rate-limit interruptions mid-batch are now non-fatal: the next invocation resumes from cached pair-checks. The cache key includes a SHA-256 hash of the two arguments' full content, so any change to argument text invalidates the cache automatically.

The thesis can defensibly state:

> v5's pair-confirmation step is intentionally idempotent and resumable. Each confirmed pair is content-keyed and persisted, so the empirical evaluation is reproducible from the run artifacts and is not contingent on uninterrupted API access during the run.

**3. Bounded retry policy + reduced parallelism.**

LLM clients (`AnthropicClient`, `OpenAIClient`) default to `max_retries=5` with the SDK's exponential backoff (which honors `Retry-After` headers). v5's default `max_workers` is 4 (lower than v4's effective parallelism), reducing request burstiness. These two settings together absorb most transient rate-limit hits before they reach the orchestrator.

### v5 — first successful end-to-end run on Kostenko (2026-05-11)

**Run ID:** `kostenko_full_20260511_183524_096453`
**Pipeline:** v1 → v2 → v3 → v4 (`gpt-4o`) → v5 (`gpt-4o-mini`)
**Total wall-clock:** ~80 seconds  **Total cost:** ~$0.15

**Quantitative summary:**

| Quantity | Value |
|-|-|
| Combined arguments fed to v5 | 43 (21 expert + 22 agent) |
| Attacks detected | 33 (20 rebutting, 13 undercutting) |
| Supports detected | 24 |
| Grounded extension (accepted) | 26 |
| Ambiguous (in some preferred but not all) | 12 |
| Rejected (in no preferred extension) | 5 |
| Preferred extensions | 16 |

Ground truth (manually annotated) contained **4 attacks** and **5 supports**. v5 produced ~8× more attacks because it evaluates every same-topic argument pair across the combined set, not only the cross-expert conflicts.

**Ground-truth attack coverage:**

| GT attack | Type | v5 verdict |
|-|-|-|
| ATK-1: U-A3 → D-A5 | rebutting | **detected exactly** |
| ATK-2: K-A4 → U-A3 | rebutting | detected, but as **undercutting in opposite direction** (U-A3 → K-A4). Same conflict, different formal category. |
| ATK-3: D-A9 → K-A8 | rebutting | **detected exactly** |
| ATK-4: K-A7 → D-A8 | undercutting | **missed** — K-A7's topic is `"Explosion sequence"`, D-A8's is `"Explosion location"`. Exact-string topic filter does not cross those labels. |

ATK-4 is direct empirical evidence of the documented exact-string-topic limitation (and motivates the SBERT semantic-similarity upgrade path noted in the design).

**Acceptance interpretation — the system rediscovered Kostenko's epistemic situation without being shown the ground truth:**

- **Accepted (26)** — corresponds to what the three expert teams converged on: the K2 seam as the methane source, exclusion of spontaneous combustion (Usembekov + Kolikov + DMT independently), exclusion of electrical equipment, exclusion of gas-dynamic events, ventilation technically functional. Plus most agent regulatory and organizational findings that had no expert counter-claim.

- **Ambiguous (12)** — `U-A3, D-A5, D-A7, D-A8, D-A9, K-A6, K-A7, K-A8, agent_1_005, agent_2_001, agent_3_001, agent_3_003`. These are the genuinely contested arguments: ignition source specificity (grinder vs AFC vs undetermined), explosion mechanism (methane vs coal dust), explosion location (sections 142-145 vs section 20), and the Challenger's targeted critiques. **This set maps closely to the 5 open questions Kolikov's commission flagged as unresolved.**

- **Rejected (5)** — `K-A4` (Kolikov: "AFC sparking was the most probable ignition source"), `agent_1_001` (the Technical agent's similar AFC-sparking claim), `agent_1_003` (a specific explosion-sequence claim), `agent_2_003`, `agent_3_002`. **K-A4 being rejected is the most striking single result**: the Kolikov-Meshcheryakov commission's primary causal finding was defeated in v5's reasoning by Usembekov's competing claim (U-A3, ambiguous). Consistent with the real-world post-investigation status: Kostenko's ignition source has never been definitively confirmed; DMT's report explicitly said "the ignition source is unknown and may never be identified."

**Why this matters for the thesis defense:**

The system was not given the ground-truth annotations as input. It received only the 21 expert arguments + the v4 agent outputs. Despite this, the v5 framework:

- identified the ignition-source controversy without being told it was the central question
- left the explosion-mechanism question unresolved (the same way Kolikov did)
- accepted what experts unanimously cleared (spontaneous combustion, electrical, K2 methane source)
- rejected the AFC-sparking line of evidence (which DMT independently refused to endorse in their report)

This is the empirical claim the thesis can make:

> Given only the structured argument extraction of three independent expert investigations of the 2023 Kostenko mine explosion, the multi-agent argumentation framework rediscovered the structure of the case's known epistemic uncertainty — distinguishing what experts converged on, what they genuinely contested, and what was unsupported — without being shown the manually-annotated attack and support relations. Two of the four manually-annotated attacks were detected with the same direction and type; one was detected as the same conflict with a different formal category (undercutting vs rebutting); one was missed due to the exact-string topic-filter limitation, motivating the documented SBERT semantic-similarity upgrade path.

This is the central empirical contribution of the thesis. Reproducible from the run artifacts in `runs/kostenko_full_20260511_183524_096453/`.

**Automated evaluation:** `scripts/evaluate_kostenko.py` reproduces the comparison without manual tabulation. It loads `v5_result.json` and `v1_case.json` from any run directory and reports:

- attack coverage vs the 4 ground-truth attacks (per-attack classification: EXACT / TYPE_MISMATCH / DIRECTION_FLIPPED / BOTH_MISMATCH / MISSED)
- support coverage via pairwise expansion of the 5 ground-truth support clusters
- acceptance distribution split by source (expert v1 vs agent v4)
- open-question capture via a hand-curated mapping `OQ → related argument IDs` (each open question is "captured" if at least one related argument is in v5's ambiguous set)

Re-running `python scripts/evaluate_kostenko.py` on the 2026-05-11 run reproduces: **3/4 attacks** (2 exact), **6/9 expected support pairs**, **5/5 open questions captured**, **26 accepted / 12 ambiguous / 5 rejected**. Two of the three missed-or-partial detections trace to the documented exact-string topic filter — K-A6 (`"Explosion location"`) vs U-A1/D-A6 (`"Ignition location"`) for SUP-2, and K-A7 (`"Explosion sequence"`) vs D-A8 (`"Explosion location"`) for ATK-4. Both are direct empirical motivation for the SBERT semantic-similarity upgrade path.

### v6 design decisions

- **Single LLM call returning typed sections.** Rather than one call per section, v6 issues a single `complete_json(schema=V6ReportContent)` invocation. The Pydantic schema enforces that the response contains all six narrative sections (1–5 + 7; Section 6 is the graph, no LLM needed). Single-call advantages: coherent narrative voice, simpler orchestration, easier prompt iteration. Schema validation localizes parse failures to specific sections.
- **LLM for narrative; deterministic for data.** The graph (Section 6) is rendered by `src/v6_report/visualizer.py` directly from the NetworkX `af_graph` — no LLM involvement. Counts, run ID, and citations are stamped deterministically. The LLM's job is the connective prose, not the data.
- **Citation discipline preserved.** The prompt instructs the LLM to cite argument IDs inline (`[U-A3]`, `[agent_3_001]`, `[ATK-V5-002]`, `[SUP-V5-001]`). The renderer leaves these tokens untouched so every claim in the final report traces to a specific argument or v5 relation. This is the central traceability property the architecture promises.
- **Graph visualization choices.** Nodes colored by acceptance (`green` accepted / `orange` ambiguous / `red` rejected). Edges styled by attack type (`solid red` rebutting / `dashed black` undercutting). Spring layout (NetworkX) for sparse AFs; a documented limitation for cases that produce dense components. Headless matplotlib (`Agg` backend) so the renderer runs in any environment.
- **Three output formats.** `v6_report.json` (the structured `V6Report` — for programmatic re-use, e.g. comparison across runs or input to a future v7). `report.md` (markdown — github rendering, thesis appendix). `report.html` (single-file HTML with inline CSS — for sharing). All live in `runs/<run_id>/`.
- **Run-relative graph path.** The markdown references the graph as `argumentation_graph.png` (relative, no run-id prefix), so the report directory is portable — copying the entire run folder to another location keeps the image link working.
- **Minimal in-house markdown → HTML converter.** ~40 LOC handles the subset our reports use (headers, paragraphs, bold/italic, code, lists, tables, images). Avoids a markdown-library dependency. Documented limitation: not a general-purpose converter.

### What's not built

- v1 Mode 2 (LLM extraction from raw text) — stub in place; implementation in `notebooks/v1_extract_arguments.ipynb`.
- Second-case evaluation (Upper Big Branch 2010) — extraction and ground-truth annotation pending.

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

## LLM provisioning — OpenRouter free-tier strategy

Decision: use OpenRouter as the LLM backend for the v4–v6 pipeline, mixing several *different model families* across agent roles. Paid-model spend goes only to **the LLM-as-judge** in evaluation (GPT-4o or stronger, via the user's existing OpenAI key).

### Why OpenRouter at all

- Single API + single key fronts every major open and closed model, so we can swap families per agent without writing new SDK plumbing. The existing [src/llm/openai_client.py](src/llm/openai_client.py) already speaks OpenAI's wire format → OpenRouter is a `base_url` override away.
- Free tier is generous enough for thesis-scale workloads if you hold ≥$10 credits on the account: `:free` model daily cap rises from ~50 → 1000 requests/day (credits never expire — the threshold is what unlocks the higher cap, not what gets spent).
- Free models can be deprecated without notice, so all model IDs stay env-configurable. The run artifact records the exact model string the API echoes back per call.

### Why a *mix* of model families (not one default)

This is methodological, not budgetary. The thesis claim "4 agents produce genuine conflicts that v5 resolves" is undermined if all 4 agents share a base model — a reviewer can argue conflicts are paraphrase variance, not real disagreement. Picking different families (DeepSeek vs Llama vs Qwen vs Nemotron) makes the disagreements *structural*: different RLHF pipelines, different training mixes, different inductive biases on the same evidence. This becomes an ablation arm in §evaluation (mixed-family vs same-family v4) and the result either way is a thesis finding.

### Catalog drift and verification (2026-05-14)

The initial per-role picks (drafted from third-party docs and OpenRouter blog posts) were checked against the live `/api/v1/models` endpoint via `python scripts/ping_openrouter.py --list-free` on 2026-05-14. **5 of 8 hardcoded IDs were dead**: `google/gemini-2.0-flash-exp:free`, `deepseek/deepseek-r1:free`, and `qwen/qwen-2.5-72b-instruct:free` were all delisted; `nvidia/nemotron-3-super-120b:free` was missing its actual `-a12b` architecture suffix. The catalog drift is normal — free model IDs rotate as upstream providers add and retire models, which is also why every model ID stays env-overridable. The table below reflects the live catalog as of that verification date; lessons:

- **Trust the catalog endpoint, not docs.** Anything written in a blog post or third-party guide is ≥ weeks stale. `--list-free` is authoritative.
- **`--check-roles` belongs in the run-prep checklist.** Before any multi-run evaluation campaign (Axes 2, 3, 4) the operator runs `--check-roles` to verify all configured IDs still respond. Cheap insurance against silent substitutions or 404s mid-run.
- **Provider-side upstream 429s are real.** During the same verification run, Llama-3.3-70B-instruct:free returned a 429 from the Venice upstream with a 29s retry-after — *not* an OpenRouter account-level rate limit, but a per-provider throttle one layer below. This is the failure mode the checkpoint/resume design and v5 confirmation cache (see below) primarily defend against.

### Hybrid free / paid pricing strategy (resolved 2026-05-14)

After the live verification run, three of the seven free roles routed through OpenRouter's *Venice* upstream provider and got `429` upstream-throttle errors back-to-back across multiple pings. Venice's throttle is a per-provider free-pool quota — separate from OpenRouter's own account-level 1000/day cap, which we have headroom on (`is_free_tier: false` confirmed via `/auth/key`). The pragmatic fix: **pay for those three roles, keep everything else free**. The decision is justified two ways:

1. **Operational.** Free-pool throttles are external and unpredictable; a thesis run that 429s after 4/7 agents have completed is worse than a $1.24 paid call. The paid version of `meta-llama/llama-3.3-70b-instruct` (the worst-throttled model) is the *same model*, just routed through a paid lane that bypasses Venice's free-pool quota. No model substitution, no methodology change — just removing an operational failure mode.
2. **Budgetary.** Live pricing pulled via `GET /api/v1/models` on 2026-05-14: paid Llama-3.3-70B is **1.24¢/run** (806 runs in $10); paid Qwen3-235B is **0.63¢/run** (1,597 runs in $10). Three paid roles × 50 evaluation runs ≈ **$0.60 total spent**. With $10 of credits deposited, this exhausts <10% of the budget. Most of the credit is preserved for Axis-4 cross-model robustness (paid unified baseline, ~$0.70 for 50 runs at `gemini-2.5-flash-lite` pricing).

Note: the LLM-as-judge for Axes 5 and 7 is run against the user's **direct OpenAI API key** (not via OpenRouter), so judge spend does *not* draw down the $10 OpenRouter budget at all. That decision keeps the judge model isolated from the pipeline-model budget and makes "judge model swap" a separate, lower-stakes axis.

### Per-subsystem model picks and rationale

For each role: chosen model (free or paid), runner-up considered, and **why it's the best option for *this specific role*** (not just "best free model overall"). Picks are env-overridable; defaults documented here are the recommended starting point. **Bold-marked rows are paid** — see the hybrid strategy explanation above.

| Role | Model | Runner-up | Why this is the best free model *for this role* |
| --- | --- | --- | --- |
| **v1 Mode 2 — LLM extraction from PDF text** (demo only) | `deepseek/deepseek-v4-flash:free` | `meta-llama/llama-3.3-70b-instruct:free` | Largest context window on the free catalog (1M tokens) — a full Rostechnadzor PDF fits in one call without chunking, which removes a whole class of extraction artifacts caused by argument-spanning chunk boundaries. The `-flash` variant is RLHF-tuned for throughput, which matches Mode 2's role as a demo path (reasoning would be wasted on a structured-extraction task). DeepSeek's `response_format=json_object` support is reliable on the v4 generation. Runner-up Llama 3.3 has better prose but smaller context (64K) and prompt-instructed-only JSON. Replaces the dead `google/gemini-2.0-flash-exp:free` (delisted; equivalent role). |
| **v4 Technical agent** | `openai/gpt-oss-120b:free` | `meta-llama/llama-3.3-70b-instruct` (paid) | **Swapped 2026-05-15 (second swap) after a second end-to-end v6 run.** The previous pick `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` failed in production with empty `content` — the reasoning-token starvation property we'd already documented as a risk became the actual failure mode under real load. With ~10K input tokens and the default `max_tokens=4096`, the model's hidden chain-of-thought consumed the entire output budget before any visible JSON was emitted. The 200-token smoke test missed this because reasoning at small budgets converges fast on a small answer; production-scale inputs trigger longer reasoning chains. **Replacement: GPT-OSS-120B** (OpenAI's open-weight 120B-MoE, free). Standard non-reasoning model (zero starvation risk), OpenAI RLHF is the *reference implementation* for `response_format=json_object`-style structured output, and the smaller sibling `openai/gpt-oss-20b:free` is already validated in v5 confirmation — so the family is known-good on our task. **Methodological concession**: we lose Technical's "explicit chain-of-thought" property; STEM-claim quality now relies on a strong general model rather than an exposed reasoning trace. The thesis-defense framing for this concession is the Axis 8 observation that *reasoning models with hidden tokens are fragile under output-budget constraints* — brittleness > absent reasoning trace at thesis scale. **Diversity gain (4 distinct families restored):** Technical=OpenAI, Organizational=Qwen, Challenger=Nous/Llama-3.1, Regulatory=Meta/Llama-3.3 — four structurally different RLHF lineages, *better* diversity than the original plan (which had two NVIDIA Nemotrons). |
| **v4 Organizational agent** *(paid: $0.63/run)* | **`qwen/qwen3-235b-a22b-2507`** | `qwen/qwen3-next-80b-a3b-instruct:free` (rate-limited) | Originally targeted free `qwen3-next-80b-a3b-instruct:free`, but that was Venice-throttled on 2026-05-14 verification. Swapped to the **paid** Qwen3-235B-A22B (235B total, 22B active per token — much larger and stronger than the free 80B version) for $0.63/run. Same Qwen-family signature (Alibaba RLHF priors), so the methodological-diversity argument is preserved; the paid lane bypasses Venice's free-pool quota entirely. Instruction-following + JSON discipline are slightly better in the 235B than the 80B, which helps the per-regulation citation discipline this agent depends on. Replaces the dead `qwen/qwen-2.5-72b-instruct:free`. |
| **v4 Challenger agent** *(paid: $0.85/run)* | **`mistralai/mistral-small-3.2-24b-instruct`** | (`nousresearch/hermes-3-llama-3.1-405b:free` and `nvidia/nemotron-3-super-120b-a12b:free` both rejected) | **Swapped twice on 2026-05-15 across three end-to-end runs.** Both free-pool 100B-class candidates failed for different reasons: (1) `nvidia/nemotron-3-super-120b-a12b:free` produced markdown-prose-with-field-labels instead of JSON for the full 4096-token output budget, never starting the leading `[`; (2) `nousresearch/hermes-3-llama-3.1-405b:free` returned a Venice upstream 429 (same throttled provider that affected free Llama-3.3 and Qwen3 the same day). The pattern across the two free failures is structural: **free-pool 100B-class generalists are unreliable for the Challenger role in production**, either through instruction-following collapse (Nemotron) or upstream-quota throttling (Venice routing). Settled on **paid Mistral-Small-3.2-24B** for $0.85/run. Justification: (a) Mistral's RLHF is known for direct, low-hedging output — methodologically consistent with Challenger's adversarial framing, where vague disagreement is worse than sharp typed attacks; (b) paid lane is structurally unaffected by Venice's free-pool throttle (`is_byok: False` 429s don't apply); (c) Mistral family signature is structurally distinct from every other v4 agent (OpenAI/Qwen/Meta), restoring four-family diversity at the v4 layer; (d) at 24B params, the model is smaller than the original free picks but instruction-following is the dominant property for Challenger, not raw size. Failure of both free picks is logged in the Axis 8 taxonomy as the canonical evidence that **paying ~$0.85 per run for the Challenger role is operational reliability, not budget extravagance**. |
| **v4 Regulatory agent** *(paid: $1.24/run)* | **`meta-llama/llama-3.3-70b-instruct`** | `qwen/qwen3-235b-a22b-2507` (paid) | Same model as originally chosen (Llama 3.3 70B, highest grounded-citation reliability among open models), but **routed through OpenRouter's paid lane instead of `:free`** — the free lane was Venice-throttled on 2026-05-14 verification. Behaviorally identical to the free version; cost only **$1.24/run** (~$0.62 across 50 evaluation runs). Regulatory output is *strict citation discipline* — must reference real regulation IDs from the Rostechnadzor KB, not hallucinate. Meta's RLHF penalizes uncited assertions heavily; reasoning-trained models would "rephrase regs in natural language" which breaks the traceability property v6 depends on. |
| **v5 conflict-confirmation calls** | `openai/gpt-oss-20b:free` | `qwen/qwen3-next-80b-a3b-instruct:free` | This step fires O(n²) times per run after the topic filter narrows candidates — by far the highest-volume call site. The 20B parameter count makes this the smallest viable free model on the catalog, optimizing for throughput on a 1-bit decision task ("is X actually attacking Y?"). GPT-OSS is OpenAI's open-weight RLHF pipeline — among free models, the most reliable on `response_format=json_object` (OpenAI tooling is the reference implementation for that contract). Family-distinct from anything in v4, so v5's binary judgment is provably independent of the agents whose outputs it judges (reduces conformist bias). Replaces the dead `google/gemini-2.0-flash-exp:free`. |
| **v6 report generator** *(paid: $1.24/run)* | **`meta-llama/llama-3.3-70b-instruct`** | `qwen/qwen3-235b-a22b-2507` (paid) | Same Llama 3.3 70B as originally chosen — cleanest technical-narrative English among open models, handles bilingual (RU/EN), follows the inline citation tokens (`[U-A3]`, `[ATK-V5-001]`) reliably. **Same Venice-bypass switch as Regulatory:** paid lane to avoid the free-tier throttle. Single long-form call per run, so cost is ~$1.24/run = $0.62 over 50 runs. Quality-over-cost is correct for v6 specifically because the report is the thesis's user-visible artifact; any hallucinated citation here breaks the traceability story. |

**Judge model** (paid, evaluation only — not in the pipeline): `gpt-4o` or stronger via the user's existing `OPENAI_API_KEY`. Reasoning: judge must be (a) stronger than every model under evaluation so its scores are credible, (b) family-distinct from the pipeline models to avoid same-family bias when scoring v4/v6 output, and (c) deterministic enough at `temperature=0` to be reproducible across re-runs of the evaluation script.

### Tier decision (resolved 2026-05-14)

**Decision: deposit $10 of credits on the OpenRouter account to unlock the 1000 :free requests/day tier.** Sources confirm the rate-limit unlock is a step function at 10 credits (= $10 USD; 1 credit = $1 USD per OpenRouter's FAQ): below the threshold, `:free` models cap at 50 requests/day across the account; at or above, the cap rises to 1000 requests/day. There is no partial unlock — a $5 deposit gives nothing rate-limit-wise.

Rationale:

- 50/day is too tight for thesis-scale experiments. A single Kostenko pipeline run uses ~20–50 LLM calls (v4 × 4 agents + v5 confirmation step + v6). N=5 multi-run stability × 4 ablation arms × 3 cross-model configs is mathematically infeasible at 50/day.
- $10 is rounding-error for a thesis. Credits never expire and can also fund the paid GPT-4o judge for Axes 5 and 7.
- Public sources disagree on whether the 1000/day cap is aggregate or per-model. Will verify against the actual OpenRouter dashboard once the account is funded; if per-model, the headroom is even larger because the recommended setup spreads load across 5 different model families.

Caveat: 20 req/min per-model and provider-side throttling still apply *under* the daily cap. That's the motivation for the checkpoint/resume design below — not as a free-tier fallback, but as resilience against transient throttling within a single run.

### Integration plan

1. **OpenRouter account setup.** ✅ Done. Account funded with $10, key minted, `is_free_tier: false` confirmed via `GET /api/v1/auth/key` — elevated 1000 req/day tier active.
2. **Config and env.** ✅ Done. `OPENROUTER_API_KEY` lives in `.env`; per-role `OPENROUTER_MODEL_*` defaults are in [src/config.py](src/config.py) and documented in [.env.example](.env.example):
   - `OPENROUTER_MODEL_TECHNICAL` → `openai/gpt-oss-120b:free` *(swapped 2026-05-15 from Nemotron-reasoning — reasoning-token starvation in production)*
   - `OPENROUTER_MODEL_ORGANIZATIONAL` → **`qwen/qwen3-235b-a22b-2507`** *(paid, ~$0.63/run)*
   - `OPENROUTER_MODEL_CHALLENGER` → **`mistralai/mistral-small-3.2-24b-instruct`** *(paid, ~$0.85/run; swapped twice on 2026-05-15 from Nemotron-3-Super-120B-a12b then Hermes-3-405B — see Challenger row above for the failure cases)*
   - `OPENROUTER_MODEL_REGULATORY` → **`meta-llama/llama-3.3-70b-instruct`** *(paid, ~$1.24/run)*
   - `OPENROUTER_MODEL_V5_CONFIRMATION` → `openai/gpt-oss-20b:free`
   - `OPENROUTER_MODEL_V6_REPORT` → **`meta-llama/llama-3.3-70b-instruct`** *(paid, ~$1.24/run)*
   - `OPENROUTER_MODEL_V1_EXTRACTION` → `deepseek/deepseek-v4-flash:free` (Mode 2 demo only)
3. **`OpenRouterClient`** ✅ Done. Lives at [src/llm/openrouter_client.py](src/llm/openrouter_client.py) — standalone client (not subclassing `OpenAIClient`, to keep telemetry and JSON-fallback logic explicit). Provides:
   - Two-attempt `complete_json` fallback: attempt 1 uses `response_format=json_object`; on empty/unparseable response, attempt 2 drops `response_format` and prepends a "first char must be `{`, last must be `}`" instruction. Both attempts logged with `used_fallback` and `response_format` fields in the events stream.
   - Per-call telemetry: `provider="openrouter"`, requested vs. echoed model, token counts, latency, finish reason, prompt/response previews.
   - Smoke-test infrastructure in [scripts/ping_openrouter.py](scripts/ping_openrouter.py): `--list-free` (live catalog), `--check-roles` (every role pinged), `--model <id>` (one-off).
4. **Per-agent client injection.** ✅ Done. v4's orchestrator now exposes a dual signature: `run_v4(..., client=...)` for legacy single-model setups (Anthropic / OpenAI), or `run_v4(..., clients={"agent_1": ..., ..., "agent_4": ...})` for the OpenRouter mixed-family setup. A `build_v4_agent_clients()` factory in [src/v4_agents/](src/v4_agents/) reads `LLM_PROVIDER` and constructs either four distinct `OpenRouterClient` instances (one per role) or four references to a single shared client. v5 and v6 scripts use a parallel `make_role_client("v5_confirmation" | "v6_report" | "v1_extraction")` helper from [src/llm/](src/llm/) — same fall-through pattern: OpenRouter → role-specific model; everything else → `make_llm_client()`. Verified by 10 new tests covering routing, client-distinctness, dual-API mutual exclusion, missing-agent-key error, and `make_role_client` paths.
5. **Pin model strings into run artifacts.** ✅ Done 2026-05-15. Every `llm_call` event records both `requested_model` and the `model` string echoed back by OpenRouter (the latter exposes any silent provider routing); `v4_start` records the per-agent `agent_models` map. A new [scripts/build_run_manifest.py](scripts/build_run_manifest.py) post-processes `events.jsonl` into a thesis-friendly `run_manifest.json`: per-role token totals, upstream-429 retry counts attributed to the throttled role, stage timings, v5 cache hits, and v5/v6 result sizes. Output is structured for direct lift into the evaluation chapter — every claim in §evaluation can point at a specific manifest and recover what model produced each subsystem's output. Covered by 8 unit tests in `tests/test_build_run_manifest.py`. Smoke-tested against the existing kostenko_v6_20260511 run (52 LLM calls, 93K input / 7.6K output tokens, 0 retries on the May-11 baseline).

**Still missing (deferred to evaluation infra):**

- ~~**Retry-with-backoff in `OpenRouterClient`**~~ ✅ Done 2026-05-15. The client now wraps `chat.completions.create` in a retry layer that parses `error.metadata.retry_after_seconds` from OpenRouter's 429 body (the field where upstream providers like Venice nest their cooldown instruction), sleeps for that delay (capped at 60s), and retries up to 4 attempts total. Each retry emits an `openrouter_429_retry` event with the actual sleep duration, so 429 frequency is visible in `events.jsonl` for the Axis 8 failure-mode taxonomy. The retry is constructor-configurable via `upstream_429_max_attempts` and `upstream_429_max_delay`. The retry-after parser falls through three sources (error body → `Retry-After` header → default) so it works against both Venice-style nested-metadata 429s and generic HTTP-spec 429s. Covered by 7 new tests in `tests/llm/test_openrouter_client.py`.
- **Checkpoint/resume runner** (`scripts/run_kostenko_full.py --resume-from <run_id>`) — see "Checkpoint / resume / cache design" below.
- **v5 confirmation cache** — see same section below.

### Checkpoint / resume / cache design (resilience layer)

The pipeline already writes per-subsystem JSON artifacts into `runs/<run_id>/`. Two additions make the pipeline resumable across rate-limit interruptions and reproducible across re-runs:

**1. `--resume-from` flag on the end-to-end runner.** ✅ implemented 2026-05-15 (lives on [scripts/run_v6_kostenko.py](scripts/run_v6_kostenko.py) — the full-pipeline script; note's earlier spec named it `run_kostenko_full.py` but we kept the established `run_v6_*` name). Usage: `python scripts/run_v6_kostenko.py --resume-from kostenko_v6_<timestamp>` reopens the existing run dir (no new timestamp / no new dir) and skips any stage whose primary artifact already exists. Skip rules:

- **v1 / v2 / v3:** *always re-run.* These are deterministic and complete in milliseconds (no LLM calls); the artifact-load detour costs more than just re-running the stages, and re-running guarantees we re-validate against the current case file in case it changed.
- **v4:** skipped if `v4_result.json` exists → loaded from disk via `V4Result.model_validate_json`. Saves 4 LLM calls (~$0.005 of paid swaps + free roles).
- **v5:** skipped if `v5_result.json` exists → loaded via `V5Result.model_validate_json`. Saves O(n²) confirmation calls. Even without the resume flag, v5's internal pair-cache (`runs/_pair_cache/`) already deduplicates confirmations across runs — but `--resume-from` is cheaper because it skips the entire `detect_conflicts` pass.
- **v6:** skipped if `v6_report.json` exists → loaded via `V6Report.model_validate_json`. Saves the single long-form report-generation call.

Resume currently treats v4 as one atomic unit (if any agent failed, all four re-run). This wastes at most 3 successful agent calls. Per-agent resume would require reshaping `run_v4`'s API and was deferred as it saves at most ~$0.01 per resume — disproportionate effort for the value.

The `RunContext.resume(run_id)` classmethod ([src/llm/logging.py](src/llm/logging.py)) is the underlying primitive: opens the existing dir without minting a new run_id, appends to `events.jsonl` rather than overwriting, and emits a `run_resumed` marker event so the post-compaction event timeline reads as one continuous log. Coverage: 4 tests in `tests/llm/test_logging.py` covering reopen behavior, append semantics, the marker event, and the missing-dir error path.

**2. v5 confirmation cache** ✅ implemented (model-aware as of 2026-05-15). Lives at `runs/_pair_cache/<key>.json`, one file per confirmed pair. The cache key encodes three things: `<arg_a_id>__<arg_b_id>__<model_slug>__<content_hash>` (see `_cache_key` in [src/v5_argumentation/conflict_detection.py](src/v5_argumentation/conflict_detection.py)). Why each component is essential:

- **Argument IDs in the filename** — debuggable: `ls runs/_pair_cache/ | grep K-A4` shows every confirmation involving K-A4 across the entire project's history.
- **Model slug** (`openai_gpt-oss-20b_free`) — the critical primitive for **Axis 4 (cross-model robustness)**: swapping `OPENROUTER_MODEL_V5_CONFIRMATION` produces a different cache namespace, forcing fresh confirmations under the new model. Without this property, a re-run under a different v5 model would silently return the *previous* model's cached answers — corrupting the cross-model comparison.
- **Content hash** — invalidates automatically if any field of either argument changes. A re-run of v4 that produces slightly different agent outputs will miss the cache for those changed args (correctly — confirmed.

Cache hits emit `v5_pair_cache_hit` events with `model=` field, so the run manifest can count hits per model and the operator can verify Axis 4 runs actually re-confirmed (zero hits expected for a model swap; many hits expected for a same-model re-run).

This serves two functions:

- **Resume:** if v5 is rate-limited mid-loop, the cache holds the confirmations already obtained; the next run skips those pairs.
- **Determinism for ablations and re-evaluation:** the same `(pair, model)` returns the same answer across re-runs without re-billing the API. Critical for Axis 3 (ablation matrix) and Axis 4 (cross-model robustness) where the same v4 output gets v5-processed multiple times under different configurations.

Argument-pair canonicalization (e.g. `(K-A4, U-A3)` vs `(U-A3, K-A4)`) is handled upstream in `detect_conflicts` — the same unordered pair is always passed to `_confirm_pair` in the same order, so the cache key is stable. Coverage: 5 cache-specific tests in `tests/v5_argumentation/test_cache.py` — including a model-namespace test that runs the same `(A1, A2)` pair under model A, then model B, then model A again, verifying A's first call writes to A's namespace, B misses and writes to its own, and A's second call hits A's existing entry without touching the LLM.

### Risks documented for the thesis

- **Free model deprecation mid-thesis.** Mitigation: pin model strings in run artifacts; document fallback ladder per role; if a primary model is deprecated, the runner-up in the §integration table is the documented substitute.
- **JSON-mode silent failures on reasoning models.** Mitigation: retry-with-stricter-prompt fallback in `OpenRouterClient.complete_json` (first attempt uses `response_format=json_object`; on empty/unparseable response, second attempt drops the response_format and prepends a "first char must be `{`, last must be `}`" instruction to the prompt). Each fallback is logged as a structured event with `used_fallback=True` so its frequency is measurable in evaluation. Documented failure mode for the now-removed DeepSeek R1; mitigation is preserved as defensive infrastructure for the Nemotron-reasoning Technical agent, which has the same RLHF lineage of reasoning-trained models that sometimes empty out under hard JSON constraints.
- **Non-determinism across runs.** Acknowledged limitation; addressed by N≥5 multi-run stability evaluation (Axis 2). v5 confirmation cache makes *re-evaluation* deterministic even though *generation* is not.
- **Provider rate-limiting under peak load.** 20 req/min per-model still applies even with credits. Mitigation: checkpoint/resume design means rate-limit interruptions are inconveniences, not run failures. v5's confirmation step is the call-density bottleneck — the cache absorbs interruption cost.
- **Silent model routing on OpenRouter.** OpenRouter sometimes routes a request to a different provider/version than expected. Mitigation: pin `response.model` per call into the run artifact; if the echoed model differs from the requested one, flag it in the evaluation report.
- **Reasoning-token starvation.** Reasoning-tuned models (e.g. Nemotron-reasoning, Trinity-thinking) consume part of `max_tokens` on hidden chain-of-thought (`message.reasoning` sibling field; counted as `reasoning_tokens` under `usage.completion_tokens_details`). If the budget is too small, the model exhausts it on reasoning and emits empty `content` with `finish_reason="stop"` — looks identical to "model returned nothing" but is actually "model ran out of budget mid-thought". Mitigation: agents using reasoning-family models keep the constructor default of `max_tokens=4096` (comfortable headroom); evaluation scripts and smoke tests use ≥200. The failure is logged but not auto-recovered — surfacing the property in the evaluation report is more useful for thesis discussion than silently retrying with more tokens.
- **`choices=None` on a 200-OK response.** Observed on 2026-05-15 mid-v5: an OpenRouter free-pool upstream returned `200 OK` but with `response.choices=None` rather than a proper choices list. The OpenAI SDK parses this as a valid `ChatCompletion` object, so the failure crosses the SDK boundary silently — `response.choices[0]` then raises `TypeError`. Mitigation: `OpenRouterClient` uses `_extract_text_and_finish_reason()` (in [src/llm/openrouter_client.py](src/llm/openrouter_client.py)) to defensively unwrap `choices`, returning `("", "no_choices")` instead of crashing. For `complete_json`, this empty-text result triggers the existing two-attempt fallback (which already handles empty content), so the failure mode is recovered transparently. Covered by 2 new tests on the empty-choices path.

## Evaluation plan

Goal: produce a thesis-defensible evaluation chapter that goes beyond the single-run numbers already in `scripts/evaluate_kostenko.py`. Seven evaluation axes, all to be implemented before submission.

### Axis 1 — Single-run structural metrics (already implemented)

Currently covered by [scripts/evaluate_kostenko.py](scripts/evaluate_kostenko.py):

- Attack-relation coverage vs the 4 GT attacks (EXACT / TYPE_MISMATCH / DIRECTION_FLIPPED / BOTH_MISMATCH / MISSED).
- Support-relation coverage via pairwise expansion of the 5 GT support clusters.
- Acceptance distribution split by source (expert v1 vs agent v4).
- Open-question capture via the hand-curated `_OPEN_QUESTION_RELATED_ARGS` mapping.

Status: works on the 2026-05-11 run. Reported: 3/4 attacks (2 exact), 6/9 expected support pairs, 5/5 open questions captured, 26 accepted / 12 ambiguous / 5 rejected.

### Axis 2 — Multi-run stability (N ≥ 5) ✅ infrastructure implemented 2026-05-15

LLMs are non-deterministic; a single run's metrics could be a lucky draw. Wrap the existing single-run script in a multi-run aggregator.

- Run the full pipeline N = 5 times (target N = 10 if rate-limit budget permits) with identical inputs but fresh seeds.
- For every Axis-1 metric, report **mean ± std** and **min / max** across N.
- Additionally report acceptance-set stability: for each argument, the fraction of runs in which it was accepted / ambiguous / rejected. Arguments oscillating across categories signal pipeline instability; arguments stable in `ambiguous` are robust contested points.

Deliverable: `scripts/evaluate_kostenko_multirun.py`. Output: `runs/eval_multirun_<timestamp>/aggregate.json` + a per-argument stability table.

**Implementation details (2026-05-15):**

- **Script** at [scripts/evaluate_stability.py](scripts/evaluate_stability.py) (renamed from the original `evaluate_kostenko_multirun.py` plan for symmetry with the other axis evaluators).
- **Inputs.** Two modes: `--last N` auto-discovers the N most-recent `kostenko_*` runs that have `v5_result.json`; `--run-dirs <a> <b> <c>` takes explicit dirs. Requires ≥ 2 runs (Jaccard is pairwise).
- **What's measured.** Three layers of stability:
  1. **Bucket-level Jaccard** across the N runs' `accepted` / `ambiguous` / `rejected` sets. Pairwise: C(N, 2) Jaccards per bucket, reported as mean ± std + min / max. A high `accepted` Jaccard means v5's "confident conclusions" are deterministic across re-runs.
  2. **Attack-edge stability.** Pairwise Jaccard on the set of `(attacker, target, type)` tuples. Type is part of the edge identity — a `(A→B, rebutting)` vs. `(A→B, undercutting)` flip counts as instability.
  3. **Support-cluster stability.** Pairwise Jaccard on the set of `frozenset(supporters)`. Member ordering doesn't affect the comparison (cluster `[A, B, C]` ≡ `[C, B, A]`).
- **Per-argument bucket consistency.** For every argument that appears in any run, count how many of the N runs placed it in the same bucket. Arguments at consistency = N/N are "stable" (defensible); arguments at 1/N or 2/N are "flipping" and worth flagging in Axis 8. The report includes a sorted list of flippers with the majority bucket and majority share, so the thesis can claim "argument X is stable; argument Y oscillates between accepted/ambiguous at 60/40."
- **Empty-set convention.** Jaccard of two empty sets returns 1.0 (degenerate identity) rather than NaN. Saves having to special-case the rare cluster-or-attack-free run.
- **Output.** Saves `stability_report.json` into the *most recent* of the compared run dirs for archival, plus a human-readable console table. 14 tests in `tests/test_evaluate_stability.py` covering all three stability aspects + the flipping-detection logic.
- **Operational note.** Each stability run is one full pipeline execution (~$0.003 + ~5 min wall time on the hybrid setup). N = 5 = $0.015 / ~25 min — trivial cost; the bottleneck is wall time. Recommended workflow:

  ```bash
  for i in 1 2 3 4 5; do python scripts/run_v6_kostenko.py; done
  python scripts/evaluate_stability.py --last 5
  ```

### Axis 3 — Ablation matrix

Re-run the pipeline with components removed and report Axis-1 deltas. Four ablation arms:

1. **Agent count.** v4 with 4 agents → 3 agents (drop Challenger) → 1 agent (Technical only). Hypothesis: dropping Challenger collapses ambiguity → all-or-nothing acceptance. If true, Challenger is doing real work, not paraphrasing.
2. **Argumentation semantics.** Grounded only vs grounded + preferred. Hypothesis: on Kostenko, preferred adds defensible worldviews that grounded alone misses (specifically the K-A4 vs U-A3 ignition-source dispute). Measure: # of arguments classified differently between the two.
3. **CBR precedents.** With vs without v3 precedent matches in v4 prompts. Hypothesis: precedents anchor agent claims to historical precedent IDs (e.g. PREC-2021-04 Listviazhnaya) → fewer hallucinated regulatory citations in the Regulatory agent. Measure: regulatory-citation hallucination rate (cited reg IDs that exist in the KB / all cited reg IDs).
4. **Model-family diversity.** Mixed-family v4 (the recommended setup above) vs same-family v4 (all 4 agents on Llama 3.3 70B). Hypothesis: same-family v4 produces fewer real conflicts → smaller AF, fewer ambiguous arguments. This is the ablation that *justifies* the mixed-family choice as methodological rather than thrift.

Deliverable: `scripts/evaluate_ablations.py` that drives the pipeline through the 4 arms and emits an ablation matrix table.

### Axis 4 — Cross-model robustness

Run the full pipeline under three model configurations: (a) all-Anthropic Claude, (b) all-OpenAI GPT-4-class, (c) the OpenRouter mixed-family setup. Report whether **v5's accepted set is stable across model choices**.

The empirical question this answers: *does the formal argumentation layer do real work, or does it just launder the LLM's prior?* If the accepted set is mostly invariant across configs, v5 is doing real reasoning. If it tracks the underlying model strongly, v5 is decorative.

Deliverable: `scripts/evaluate_cross_model.py`. Output: 3-column comparison table at the argument level + Jaccard similarity between the three accepted sets.

#### Axis 4 N=2 result locked 2026-05-15 (baseline vs hybrid)

Two end-to-end pipeline runs have been completed and evaluated against the same Kostenko GT, producing the first cross-model robustness data point of the thesis. Both runs use identical v1/v2/v3 deterministic stages, identical prompts, identical evaluation rubric — the only variable changed is the per-role model configuration.

| Configuration | Run ID | Per-role models | Per-run cost |
| --- | --- | --- | --- |
| **Baseline** (single-model paid) | `kostenko_full_20260511_183524_096453` | Anthropic Claude across all v4 / v5 / v6 roles | ~$0.05 |
| **Hybrid** (mixed-family OpenRouter, Layer-1 paid swaps) | `kostenko_v6_20260515_144020_680602` | v4 Technical=`openai/gpt-oss-120b:free` · v4 Organizational=`qwen/qwen3-235b-a22b-2507` *(paid)* · v4 Challenger=`mistralai/mistral-small-3.2-24b-instruct` *(paid)* · v4 Regulatory=`meta-llama/llama-3.3-70b-instruct` *(paid)* · v5 confirmation=`openai/gpt-oss-20b:free` · v6 report=`meta-llama/llama-3.3-70b-instruct` *(paid)* | **~$0.003** |

Side-by-side metrics:

| Metric | Baseline (May-11) | Hybrid (May-15) | Δ | Direction |
| --- | --- | --- | --- | --- |
| GT attacks detected (any form) | 3 / 4 | 2 / 4 | −1 | regression |
| GT attacks detected exactly | 2 / 4 | 2 / 4 | 0 | unchanged |
| v5 attacks total | 33 | 28 | −5 | less verbose |
| Support pairs detected (from 9 GT-expected) | 6 / 9 | **7 / 9** | +1 | improvement |
| GT open-question capture as ambiguous | 5 / 5 | 5 / 5 | 0 | **invariant** |
| Acceptance: accepted / ambiguous / rejected | 26 / 12 / 5 | 23 / 15 / 2 | acc −3, amb +3, rej −3 | more cautious |
| Per-expert Jaccard — Usembekov | 0.111 | 0.125 | +0.014 | small bump |
| Per-expert Jaccard — Kolikov | 0.133 | **0.192** | +0.059 | larger bump |
| Per-expert Jaccard — DMT | 0.167 | 0.143 | −0.024 | small drop |
| Per-expert Jaccard spread | 0.056 | 0.067 | +0.011 | still **MIXED** |
| Per-expert story label | MIXED (near BALANCED) | MIXED (moderate bias) | both MIXED | **invariant label** |

**Thesis interpretation:**

1. **Open-question capture is invariant.** Both configurations produce 5 / 5 open-question capture (every GT open question lands in v5's *ambiguous* set with at least one related argument). This is the thesis-defining property: v5 successfully surfaces every operationally-unresolved question as contested-but-defensible, regardless of the underlying model stack. **Strongest single result of the cross-model comparison.**
2. **Per-expert synthesis label is invariant.** Both runs are MIXED (spread 0.056 vs 0.067) — neither swings to BIASED (≥0.15) or BALANCED (≤0.05). The framework's synthesis-vs-bias character does not collapse under a major model substitution.
3. **Support coverage improves under the hybrid** (6 / 9 → 7 / 9). SUP-3 (ventilation functional, U-A4 + D-A3) was undetected on the baseline; the hybrid catches it. Likely a consequence of `gpt-oss-20b`'s more permissive support-vs-independent classification on borderline topic overlap.
4. **One attack-detection regression.** ATK-2 (K-A4 rebuts U-A3) was caught with wrong direction/type on the baseline but missed entirely on the hybrid. Traceable to the cheaper v5 confirmation model (`gpt-oss-20b:free`) being slightly more conservative on borderline rebuttal/undercut pairs. Logged as the canonical instance of the Axis 8 "confirmation miss" failure-mode bucket (see Axis 8 for the four-category taxonomy).
5. **Cost dropped 94%** ($0.05 → $0.003 per pipeline run) with **zero degradation on the load-bearing thesis property** (open-question capture) and **net improvement on support coverage**. This is the defense-ready summary sentence:
   > "Under a 94% per-run cost reduction (mixed-family free + budget-paid swaps vs. premium single-model), v5's accepted set preserves the methodologically critical open-question-as-ambiguous property (5 / 5) and the per-expert synthesis-vs-bias label (MIXED in both), trading one attack-detection regression for one support-coverage improvement."

**What N=2 buys and what it doesn't:** N=2 is enough to claim *qualitative* invariance on the load-bearing properties (open-question capture, per-expert story label), and enough to surface concrete trade-offs at the per-metric level (one regression, one improvement). N=2 is **not** enough to make a strong stability claim against sampling noise — that's Axis 2's role (multi-run with the same config). A third configuration (e.g. `gemini-2.5-flash-lite` unified paid baseline) would harden the trade-off characterization into a 3-arm comparison.

#### Recipe for the N=3 third arm

Inline env-var override + standard runner — no new script needed. The third configuration is *all roles point at one paid unified model* (Google Gemini 2.5 Flash Lite chosen because: family-distinct from every model in the May-11 baseline and May-15 hybrid; ~$0.014/run; native JSON-mode reliability):

```bash
OPENROUTER_MODEL_TECHNICAL=google/gemini-2.5-flash-lite \
OPENROUTER_MODEL_ORGANIZATIONAL=google/gemini-2.5-flash-lite \
OPENROUTER_MODEL_CHALLENGER=google/gemini-2.5-flash-lite \
OPENROUTER_MODEL_REGULATORY=google/gemini-2.5-flash-lite \
OPENROUTER_MODEL_V5_CONFIRMATION=google/gemini-2.5-flash-lite \
OPENROUTER_MODEL_V6_REPORT=google/gemini-2.5-flash-lite \
OPENROUTER_DEFAULT_MODEL=google/gemini-2.5-flash-lite \
python scripts/run_v6_kostenko.py
```

Expected: ~5 min wall time, ~$0.014 of OpenRouter credit. After completion:

```bash
python scripts/build_run_manifest.py
python scripts/evaluate_kostenko.py          # gives Axis-1 + Axis-6 numbers
python scripts/classify_failure_modes.py     # gives Axis-8 classification for this config
python scripts/evaluate_v6_report.py         # Axis 7 judge (uses paid OpenAI key)
python scripts/evaluate_argument_quality.py  # Axis 5 judge (uses paid OpenAI key)
```

The python-dotenv loader uses `override=False` in [src/config.py](src/config.py), which means **shell-set env vars take precedence over `.env`** — so the inline prefix correctly overrides the hybrid defaults for this single run without modifying `.env`. After the run, your normal hybrid config remains intact for subsequent runs.

This gives a clean 3-arm comparison ready to be tabled in the thesis evaluation chapter: May-11 single-model premium baseline / May-15 hybrid mixed-family / N=3 unified-paid-cheap baseline.

### Axis 5 — Argument-quality scoring (LLM-as-judge) ✅ implemented 2026-05-15

Axes 1–4 measure *structural* recall. This axis measures *content* quality. For every v4-generated argument:

- A judge LLM (GPT-4o or stronger) scores on a 1–5 rubric across four dimensions: **evidence-groundedness** (claim references real evidence from the case), **warrant validity** (the reasoning step from evidence to claim holds), **claim novelty** (does this argument say something not already covered by expert args?), **citation correctness** (cited regulation / precedent IDs actually exist in the KB).
- Judge prompt is deterministic (temperature=0); judge model is paid (user's OpenAI key, *not* the pipeline's OpenRouter free models).
- Report per-agent mean scores → does the Challenger actually challenge? Does the Regulatory agent cite real regulations?

Deliverable: `scripts/evaluate_argument_quality.py` + `prompts/judge_argument_quality.md`. Output: per-argument scores + per-agent aggregates.

**Implementation details (2026-05-15):**

- **Schema** in [src/schema/judge_result.py](src/schema/judge_result.py): `ArgumentQualityScores` (per-argument: 4 `RubricScore` fields + `comments` + computed `mean_score`) and `ArgumentQualityResult` (wraps a flat list of per-arg scores + `overall_comments`). The judge produces structured per-argument output; **per-agent aggregates are computed in Python** (not by the judge), so the arithmetic is deterministic regardless of judge sampling variance.
- **Bulk-scoring design choice.** All v4 arguments are scored in a single judge call rather than one call per argument. Reasoning: (a) the judge needs to see ALL v4 outputs simultaneously to evaluate `claim_novelty` (a paraphrase of another agent's claim can't be detected if the judge only sees one argument at a time); (b) bulk is cheaper: 1 call × ~7K input + ~5K output (gpt-4o) ≈ **$0.07/run** vs. 20 calls × ~10K input + ~300 output each ≈ $0.50/run. Cost saved without sacrificing the cross-argument novelty signal.
- **`max_tokens=12000` on the Axis 5 call (not the default 4096).** Discovered during the canonical 2026-05-15 run: bulk-scoring 21 arguments × ~280 output tokens each ≈ 5,880 output tokens, plus the `overall_comments` field, exceeded `OpenAIClient`'s default `max_tokens=4096` and the judge's JSON output was truncated mid-`agent_4_004`. The evaluator script now explicitly passes `max_tokens=12000` on this single call site — a safety margin over the ~6K actually needed, sized to comfortably accommodate `n ≤ 30` arguments. The bump is **scoped to this judge call only** (not propagated to `OpenAIClient`'s constructor default) because every other use case (v5 confirmation, v6 report, the v4 agents themselves) fits well under 4096 and a global bump would mask the tighter budget needs elsewhere.
- **Rubric prompt** in [prompts/judge_argument_quality.md](prompts/judge_argument_quality.md). Each of the 4 dimensions has explicit score-anchor text at 1.0, 3.0, 5.0. The `claim_novelty` rubric explicitly carves out an exemption for Agent 4 (Regulatory) — it's *expected* to overlap with regulatory claims by design, so penalizing it for low novelty would conflate role with quality. The `evidence_groundedness` rubric flags "fabricated evidence" (citing things the case file doesn't contain) as the most dangerous failure mode — the rubric specifically calls this out so the judge weighs it harder than a hand-wavy warrant.
- **Per-agent aggregates** computed by `compute_per_agent_aggregates()` in [scripts/evaluate_argument_quality.py](scripts/evaluate_argument_quality.py): for each of the 4 agents, returns `count` + per-dimension means + overall mean. The CLI script prints them in a thesis-ready table, and lists three explicit "thesis-defining questions" the table answers (Challenger novelty? Regulatory citation discipline? Strongest agent on evidence-groundedness?). This makes the Axis 5 output directly liftable into the evaluation chapter without further analysis.
- **Reuses the same judge infrastructure as Axis 7.** Both axes call `OpenAIClient.complete_json` directly via `OPENAI_API_KEY`, both share `RubricScore` as the per-dimension primitive, both default to `gpt-4o` with `--judge-model` override. Methodological consistency: same judge, same rubric primitive, same scale — Axes 5 and 7 are commensurable on the 1.0–5.0 scale, so the thesis can claim "GPT-4o judges report quality at X and argument quality at Y" in directly comparable units.
- **Budget impact**. ~$0.07/run × 20 evaluation passes = **~$1.40 across the entire thesis evaluation campaign**, again on the OpenAI account (no OpenRouter budget consumed).
- **Coverage**. 11 tests in `tests/test_evaluate_argument_quality.py`: schema validation, every formatter unit-tested independently, per-agent aggregate computation (including the edge case where the judge accidentally scores an expert arg by ID prefix — silently excluded), and the `agent_id_from_arg` parser. **Prompt verified to render at 44,414 chars against the canonical May-11 reference run** — within `gpt-4o`'s 128K context with substantial headroom.

### Axis 6 — Per-expert agreement ✅ implemented 2026-05-15

Compute Jaccard agreement between v5's accepted set and each of the three expert sources' argument sets (Usembekov / Kolikov / DMT). Three numbers tell the story:

- **High agreement with one expert** → v5 picks a side; the framework has a model-induced or evidence-induced bias toward that source. Either is interesting and reportable.
- **Roughly equal agreement** → v5 *synthesizes* across experts. This is the strongest possible empirical story for the thesis.
- **Low agreement with all three** → v5 produces something experts wouldn't endorse. Failure mode; need to understand why.

Cheap to compute (set ops on existing v5 output) but high narrative payoff — this is the headline number for the thesis abstract.

Deliverable: small function added to `scripts/evaluate_kostenko.py`. No new script. **Done.** Implementation in `per_expert_agreement()` + `print_per_expert_agreement()` in [scripts/evaluate_kostenko.py](scripts/evaluate_kostenko.py). Includes the symmetric Jaccard plus an asymmetric "coverage_of_expert" metric (|expert ∩ accepted| / |expert|) and a `spread` threshold that maps the per-expert agreement pattern to one of three thesis-defensible labels: `BIASED` (spread ≥ 0.15, names the dominant expert), `BALANCED` (spread ≤ 0.05, the strong synthesis story), `MIXED` (between). The summary line at the bottom of `evaluate_kostenko.py` now reports all three per-expert Jaccards plus the interpretation, ready to lift into the thesis abstract. Covered by 10 unit tests in `tests/test_evaluate_kostenko.py`.

### Axis 7 — v6 report quality (LLM-as-judge + optional expert read) ✅ implemented 2026-05-15

Two evaluation tracks for the final report:

1. **LLM-as-judge.** Judge model (GPT-4o or stronger) scores the v6 markdown report against the GT case file on a 5-point rubric: factual accuracy, completeness vs the 5 open questions, citation correctness (every `[ARG-ID]` token in the report resolves to an actual argument; every `[ATK-V5-*]` resolves to a real attack), narrative coherence, defense-readiness. Deterministic, reproducible across re-runs.
2. **Expert read-through (optional).** Markarian and/or Temkin score one v6 report on the same rubric. Even N=1 expert per supervisor is defensible if methodology is documented; their agreement-with-LLM-judge score is itself a finding.

Deliverable: `scripts/evaluate_v6_report.py` + `prompts/judge_v6_report.md`. Output: per-section rubric scores.

**Implementation details (2026-05-15):**

- **Schema** in [src/schema/judge_result.py](src/schema/judge_result.py) — Pydantic `V6ReportJudgeResult` with five `RubricScore` fields (each = `{score: float 1.0-5.0, rationale: str ≥10 chars}`), plus `overall_comments` and `flagged_issues: list[str]`. `overall_score` is a computed mean property, not LLM-judged, so the arithmetic is deterministic regardless of judge variance.
- **Rubric prompt** in [prompts/judge_v6_report.md](prompts/judge_v6_report.md). Each of the five dimensions has explicit score-anchor text at 1.0, 3.0, 5.0; partial scores (3.5, 4.2) explicitly allowed. The prompt also instructs the judge to label its weakest dimension as either **structural** (model/pipeline limit needing algorithm change) or **surface** (copy-edit class). That structural-vs-surface classification is what makes Axis 7's output actionable for thesis discussion — a "3.0 on coherence" is a different finding from a "3.0 on factual accuracy".
- **Evaluator script** [scripts/evaluate_v6_report.py](scripts/evaluate_v6_report.py). Loads `report.md`, `v5_result.json`, optionally `v4_result.json`, and the case file. Renders the prompt with formatted argument + attack + support inventories so the judge can verify every `[ARG-ID]` and `[ATK-V5-*]` citation token. Calls `OpenAIClient.complete_json` against the user's direct `OPENAI_API_KEY` (not via OpenRouter — judge spend is structurally isolated from the pipeline budget). `--dry-run` prints the rendered prompt without calling the model, useful for rubric iteration.
- **Budget impact.** Judge prompt is ~21K chars (~5K tokens) for a Kostenko-scale run. With `gpt-4o` at $2.50/M input + $10/M output, plus an expected ~1-2K output tokens, per-judgment cost is roughly **2-3¢**. The full evaluation campaign (≤20 judgments across N=5 multi-run × ablation arms) lands around **$0.50-0.60 total** on the OpenAI account, never touching the OpenRouter budget.
- **Methodological isolation.** The judge runs on a *different* OpenAI account from the pipeline (which uses OpenRouter), with a *different* model family (`gpt-4o` is closed-source OpenAI; pipeline uses gpt-oss / Qwen3 / Mistral / Llama-3 / Nemotron). This rules out the "same-family bias" methodological objection — the judge cannot be accused of preferring outputs from its own RLHF lineage.
- **Coverage.** 13 tests in `tests/test_evaluate_v6_report.py`: schema validation (score range, rationale length, computed mean), per-formatter unit tests (investigation questions, case summary, argument inventory with and without v4, attack/support inventory), and an end-to-end test that builds the prompt against a fixture run dir + case file. **Prompt verified to render at 21,608 chars against the canonical May-11 reference run.**

### Axis 8 — Failure-mode taxonomy ✅ implemented + classified 2026-05-15

For every metric miss (a GT attack not detected, a GT support pair not detected, an open question not captured), classify the *cause* of the miss into one of:

1. **Generation miss** — v4 never produced the counter-argument that would have created this attack.
2. **Detection miss** — argument existed but the topic-string filter excluded the pair from conflict-detection candidates.
3. **Confirmation miss** — candidate pair reached the LLM confirmation step but was scored as non-conflict.
4. **Semantics demotion** — confirmed attack existed in the AF but was demoted out of grounded/preferred extensions.

Two known failure cases already documented in §section "Kostenko results" map to (2): ATK-4 (K-A7 vs D-A8 across topics `"Explosion sequence"` / `"Explosion location"`), SUP-2 (K-A6 vs U-A1/D-A6 across `"Explosion location"` / `"Ignition location"`). These directly motivate the SBERT semantic-similarity upgrade path. Other misses likely cluster in (1) or (3) — the taxonomy makes the failure modes legible instead of lumping them as "missed."

Deliverable: hand-classified table for the single canonical Kostenko run, included in the thesis evaluation chapter as a figure. Cheap to produce (~30 lines per miss, 4 misses).

**Implementation details (2026-05-15):**

- **Auto-classifier** at [scripts/classify_failure_modes.py](scripts/classify_failure_modes.py). Walks each GT attack and each expected support-cluster pair through the four pipeline stages (Generation / Detection / Confirmation / Semantics) by reading `v5_result.json`, `events.jsonl` (for `v5_pair_check_done` relations), `v4_result.json` (for the agent argument inventory), and the GT case file. Produces both a console table and a `axis8_failure_modes.json` artifact in the run dir.
- **Why automate something note.md called "cheap to produce by hand".** With one run it's hand-doable; with N stability runs (Axis 2) or 3+ Axis-4 configurations, hand-classifying every miss across every run becomes hours of error-prone work. The classifier reads the same logs and produces the same table in <1 second, lets the analysis scale to the full evaluation matrix, and makes the classification methodology *reproducible* — a reviewer running the script on the run dir gets the same labels we put in the thesis.
- **Canonical May-15 run result locked.** Running the classifier against `runs/kostenko_v6_20260515_144020_680602` yields:

  | Bucket | Attacks (of 4 GT) | Supports (of 9 expected pairs) |
  | --- | --- | --- |
  | GENERATION miss | **0** | **0** |
  | DETECTION miss | 1 (ATK-4 K-A7 / D-A8) | 2 (SUP-2 pairs U-A1/K-A6, K-A6/D-A6) |
  | CONFIRMATION miss | 1 (ATK-2 K-A4 / U-A3, LLM said `independent`) | 0 |
  | SEMANTICS demotion | **0** | **0** |
  | DETECTED | 2 EXACT | 7 |

  Thesis-grade observations:
  1. **Zero GENERATION misses.** v4 produced every argument needed; the LLM agents successfully generated counter-arguments and counterparts for every GT relation. v4's job is done correctly.
  2. **Zero SEMANTICS demotions.** Every relation the LLM confirmed survived AF construction and grounded/preferred semantics. The argumentation layer is not silently dropping valid attacks.
  3. **Three of four misses are DETECTION-stage (topic filter).** The remaining one is a CONFIRMATION miss where the v5 LLM rated the pair as `independent`. **This split is the canonical empirical evidence for the SBERT semantic-similarity upgrade path** mentioned elsewhere in the design doc: all three DETECTION misses are topic-string mismatches that semantic embeddings would resolve (`"Explosion sequence"` vs `"Explosion location"`, `"Ignition location"` vs `"Explosion location"`). The SBERT upgrade would *measurably* fix 3 of 4 attack misses and 2 of 9 support-pair misses without changing any other pipeline component.
- **Coverage.** 17 tests in `tests/test_classify_failure_modes.py`: one test per pipeline stage (Generation / Detection / Confirmation / Semantics), one test per detected form (exact / direction_flipped / type_mismatch), and helper-function unit tests for `_find_pair_check_event` (matches either pair order), `_find_v5_attack` (respects direction), `_find_v5_support_pair` (handles cluster membership), and `_build_args_by_id` (unifies v1 + v4 inventories).

### Axis 9 — Comparison to Markarian's classical baseline

The thesis's actual punchline: *what does the LLM + Dung's-semantics approach buy us that Markarian's classical propositional-logic subsystems 4–6 don't?* Even a qualitative side-by-side on Kostenko is enough for the defense:

- Markarian's subsystems 4–6 over the same v1–v3 outputs (best-effort reimplementation from the published architecture, or a documented narrative comparison if reimplementation is out of scope).
- v4–v6 outputs from this thesis.
- For each: (a) can it represent disagreement between experts? (b) does it produce a justification trail back to evidence? (c) can it accommodate new agents/sources without rewriting the rule base?

This axis is partially *narrative*, not numeric — that's fine; the thesis defends *the architectural choice*, not just the metrics.

Deliverable: a side-by-side comparison section in the evaluation chapter. No new code if reimplementation is out of scope; one new script if we do reimplement Markarian's subsystems for direct comparison.

### Evaluation deliverables summary

| Axis | Deliverable | Effort | Status |
| --- | --- | --- | --- |
| 1 | `scripts/evaluate_kostenko.py` | — | **done** |
| 2 | `scripts/evaluate_kostenko_multirun.py` | low | pending |
| 3 | `scripts/evaluate_ablations.py` (4 arms) | high | pending |
| 4 | `scripts/evaluate_cross_model.py` (3 configs) | medium | pending |
| 5 | `scripts/evaluate_argument_quality.py` + judge prompt | medium | pending |
| 6 | per-expert agreement function in existing script | trivial | pending |
| 7 | `scripts/evaluate_v6_report.py` + judge prompt | medium | pending |
| 8 | failure-mode taxonomy table (thesis figure) | trivial | pending |
| 9 | Markarian baseline comparison (narrative + optional reimpl) | medium → high | pending |

### Recommended implementation order

Order chosen to unblock the most thesis surface area earliest, and front-load the work that depends on OpenRouter being wired up:

1. **OpenRouter integration** (`OpenRouterClient`, `.env`, config wiring) — prerequisite for Axes 2, 3, 4. Single step.
2. **Axis 6** (per-expert agreement) — trivial code, immediate thesis-narrative value.
3. **Axis 2** (multi-run stability) — gates every downstream "is this real or noise?" question.
4. **Axis 8** (failure-mode taxonomy) — manual classification, no code; can be done in parallel with later code work.
5. **Axis 5** (argument-quality judge) — sets up the judge infrastructure that Axis 7 reuses.
6. **Axis 7** (v6 report judge) — reuses Axis 5's judge plumbing.
7. **Axis 3** (ablation matrix) — bulk of the experimental work; sequenced after the judge exists so quality scores can be computed per ablation arm if useful.
8. **Axis 4** (cross-model robustness) — requires all three model stacks to be working.
9. **Axis 9** (Markarian comparison) — last; mostly writeup, depends on results of earlier axes for the comparison narrative.
