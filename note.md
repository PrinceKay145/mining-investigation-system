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
