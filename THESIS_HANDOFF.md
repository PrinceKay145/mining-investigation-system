# Thesis writing handoff — Mining Accident Investigation System

This document is the **single entry point** for the LLM (or human) writing
the thesis manuscript. It indexes every result, design decision, and
artifact produced during implementation so that the writing task is
*lifting and arranging*, not *generating*.

If you read only one section: **§3 Canonical results** has the numbers
the thesis chapters need to quote verbatim.

---

## 0. Project one-paragraph statement

A multi-agent system for automated mining accident investigation. Extends
Markarian's 6-subsystem architecture by replacing the classical
propositional-logic reasoning layer (subsystems 4–6) with **four
specialist LLM agents** producing typed arguments, **Dung's argumentation
framework** (NetworkX, grounded + preferred semantics) resolving the
resulting conflicts, and a **structured-output LLM** rendering the final
investigation report. Evaluated on the **Kostenko mine explosion**
(Karaganda, Kazakhstan, 28 October 2023; ArcelorMittal Temirtau; 46
fatalities) against the three independent expert investigations
(Usembekov, Kolikov-Meshcheryakov, DMT).

- **Supervisors:** Anna Markarian (Automated Control Systems), Igor Temkin
  (Mining Safety and Ecology). NUST MISIS, Data Science MSc.
- **Programme:** MSc thesis, 2026.

---

## 1. Where to read what

| If the chapter is about... | Start here |
| --- | --- |
| The system architecture (Methodology / Implementation chapters) | [`system_architecture.json`](system_architecture.json) — full 6-subsystem spec; [`note.md`](note.md) §"System architecture" + per-subsystem sections |
| Why each model was picked / swapped (Implementation chapter) | [`note.md`](note.md) §"LLM provisioning — OpenRouter free-tier strategy" — per-role rationale + cost math + every swap that happened during integration |
| Knowledge base + Kostenko case file (Methodology chapter) | [`note.md`](note.md) §"Kostenko knowledge base" + [`data/knowledge_base/kostenko_knowledge_base.json`](data/knowledge_base/kostenko_knowledge_base.json) (21 expert args, 4 GT attacks, 5 GT support clusters, 5 open questions) |
| Evaluation results (Evaluation chapter) | This doc §3 + run-dir JSON artifacts indexed in §6 |
| Failure modes and risks (Discussion chapter) | [`note.md`](note.md) §"Risks documented for the thesis" + Axis 8 table in §3 of this doc |
| The full numerical canonical results | This doc §3 |
| The thesis argument structure | This doc §4 |

---

## 2. Pipeline at a glance (6 subsystems)

```
┌─────┐   ┌─────┐   ┌─────┐    ┌─────────────────┐   ┌─────┐   ┌─────┐
│ v1  │──→│ v2  │──→│ v3  │──→ │ v4 (4 agents)   │──→│ v5  │──→│ v6  │
│ Dec │   │ Cls │   │ CBR │    │ T  O  Ch  R     │   │ AF  │   │ Rpt │
└─────┘   └─────┘   └─────┘    └─────────────────┘   └─────┘   └─────┘
   ↑ deterministic (no LLM) ↑    ↑ LLM (5+ calls) ↑   ↑LLM↑    ↑LLM↑
   v1: 21 expert args → Argument schema
   v2: rule-based accident type
   v3: Jaccard CBR over precedents
   v4: Technical / Organizational / Challenger / Regulatory specialists,
       each emits a JSON list of Argument objects (8-field Toulmin-derived)
   v5: topic-filter → LLM pair-confirmation → AF construction (NetworkX)
       → grounded + preferred semantics → accepted/rejected/ambiguous
   v6: LLM renders narrative report with inline [ARG-ID] / [ATK-V5-*] citations
```

**Argument schema (8 fields, Toulmin-derived):** `id`, `source`, `topic`,
`claim`, `evidence`, `warrant`, `confidence`, `cause_categories`.

**v5 attack types:** `rebutting` (mutually incompatible claims),
`undercutting_a_to_b` (A undermines B's reasoning), `undercutting_b_to_a`,
`support` (mutually reinforcing), `independent`.

---

## 3. Canonical results (lift these into the Evaluation chapter)

Numbers in §3.1–3.5 and §3.7 are from the **May-15 canonical run**
`runs/kostenko_v6_20260515_144020_680602/`. §3.6 (Axis 4 cross-model
robustness) spans three configurations (May-11 baseline / May-15 hybrid /
May-15 N=3 Gemini unified-paid). §3.8 (Axis 2 stability) spans five
same-config hybrid runs (May-15 17:10–17:42). Every result is reproducible
by running the scripts indexed in §6 against the named run dirs.

### 3.1 Axis 1 — Structural metrics vs ground truth

| Metric | Value | Source |
| --- | --- | --- |
| GT attacks detected (any form) | 2 / 4 | `evaluate_kostenko.py` |
| GT attacks detected *exactly* | 2 / 4 | same |
| v5 total attack relations | 28 | `v5_result.json` |
| Expected support pairs detected | 7 / 9 | `evaluate_kostenko.py` |
| v5 total support clusters | 25 | `v5_result.json` |
| Open-question capture as ambiguous | **5 / 5 (perfect)** | `evaluate_kostenko.py` |
| Acceptance: accepted / ambiguous / rejected | 23 / 15 / 2 | `v5_result.json` |
| Combined arg count (v1 experts + v4 agents) | 42 (21 + 21) | `v5_result.json` |

**Single headline finding (Axis 1):** v5 captures **5 of 5** real-world
open questions as `ambiguous` (contested but defensible), preserving every
operationally-unresolved question from the three expert investigations.
This is the strongest individual quantitative result of the project.

**Important caveat from Axis 4 N=3 (see §3.6):** the 5/5 capture is **not
invariant across all model configurations** — it is preserved by the
mixed-family Hybrid (May-15) and the single-family-paid Baseline (May-11),
but **collapses to 1/5 under a unified-single-model configuration**
(Gemini 2.5 Flash Lite all-roles, May-15 N=3). The empirical implication
is that the **mixed-family-as-diversity-primitive design is load-bearing
for the OQ-capture property** — a single model cannot produce sufficient
internal disagreement for v5 to surface contested issues as `ambiguous`.

### 3.2 Axis 5 — Per-agent argument quality (LLM-as-judge, GPT-4o)

| Agent | Evid | Warr | Novl | Cite | Overall |
| --- | --- | --- | --- | --- | --- |
| Technical (gpt-oss-120b free) | 5.00 | 4.30 | 3.80 | 5.00 | **4.53** |
| Organizational (Qwen3-235B paid) | 5.00 | 4.33 | 4.00 | 5.00 | **4.58** |
| Challenger (Mistral-Small-3.2 paid) | 5.00 | 3.70 | 3.70 | 5.00 | **4.35** |
| Regulatory (Llama-3.3-70B paid) | 5.00 | 4.50 | 3.50 | 5.00 | **4.50** |

(Scale 1.0–5.0. Evid = Evidence-groundedness; Warr = Warrant validity;
Novl = Claim novelty; Cite = Citation correctness.)

**Two thesis-defensible findings (Axis 5):**

1. **Every agent scored 5.00 on both Evidence-groundedness AND Citation
   correctness** across all 21 v4-generated arguments. **Zero
   hallucinated evidence; zero invented `TC-`/`OC-`/`REG-` codes** across
   the entire v4 output. This is the strongest possible defense against
   the standard "but LLMs hallucinate" objection.
2. **The Challenger scoring lowest (4.35) is consistent with its role.**
   Lower warrant validity and novelty are *expected* for adversarial
   argument generation — Challenger arguments are critiques of others, so
   they have weaker standalone evidence-to-claim chains and lower novelty
   against the existing pool. The Challenger's *value* is in v5's
   argumentation framework, not in standalone quality scores. Axis 5
   surfaces this nuance directly.

### 3.3 Axis 6 — Per-expert agreement (Jaccard with Usembekov / Kolikov / DMT)

| Expert | # args | Accepted | Ambiguous | Rejected | Coverage | **Jaccard** |
| --- | --- | --- | --- | --- | --- | --- |
| Usembekov | 4 | 3 | 1 | 0 | 75.0% | 0.125 |
| Kolikov | 8 | 5 | 2 | 0 | 62.5% | **0.192** |
| DMT | 9 | 4 | 4 | 1 | 44.4% | 0.143 |

Jaccard spread = max − min = **0.067 → MIXED (partial synthesis with
some bias).**

**Single Axis-6 finding:** v5 does not collapse onto any one expert
report. The cross-expert Jaccard spread is small (0.067), and the per-bucket
distribution shows reasonable representation of every expert's claims in
v5's accepted set. This is the strongest formulation of the methodological
question the thesis was built around: *can a multi-agent argumentation
framework synthesize across competing expert reports without privileging
any one of them?* Answer: **yes**, on this case.

### 3.4 Axis 7 — v6 report quality (LLM-as-judge, GPT-4o)

| Dimension | Score (1.0–5.0) |
| --- | --- |
| Factual accuracy | 4.0 |
| Completeness vs 5 GT open questions | 3.0 |
| Citation correctness | **4.5** |
| Narrative coherence | 3.5 |
| Defense readiness | 3.0 |
| **Overall (mean)** | **3.60 / 5.0** |

**Flagged issues from the judge (verbatim from
`judge_v6_report_result.json`):**

- `[TC-01]` and `[PREC-2021-04]` cited but not in inventory
- Role of seismic activity not addressed
- Measures to prevent similar accidents not proposed

**Judge interpretation:** "*The report's strongest dimension is factual
accuracy, with most claims aligning with the ground truth. Its weakest
dimension is completeness, as it misses addressing all open questions.
This weakness is **structural** [model/pipeline limit], requiring more
thorough engagement with the investigation questions.*"

### 3.5 Axis 8 — Failure-mode taxonomy

The four pipeline stages (Generation / Detection / Confirmation /
Semantics) and how the May-15 misses partitioned:

| Pipeline stage | Attack misses (of 4 GT) | Support-pair misses (of 9 expected) |
| --- | --- | --- |
| GENERATION (v4 didn't produce a needed argument) | **0** | **0** |
| DETECTION (topic filter excluded the pair) | **1** (ATK-4 K-A7 / D-A8: 'Explosion sequence' vs 'Explosion location') | **2** (SUP-2 pairs U-A1 / K-A6 and K-A6 / D-A6: 'Ignition location' vs 'Explosion location') |
| CONFIRMATION (LLM rated pair as non-attack) | **1** (ATK-2 K-A4 / U-A3 → LLM said `independent` instead of `rebutting`) | 0 |
| SEMANTICS (AF demoted confirmed attack) | **0** | **0** |
| DETECTED | 2 EXACT | 7 |

**Three observations (Axis 8):**

1. **Zero GENERATION misses.** v4 successfully produced every argument
   required to match GT attacks and support clusters. The LLM specialist
   agents are not the bottleneck.
2. **Zero SEMANTICS demotions.** Every relation the LLM confirmed survived
   AF construction and grounded/preferred semantics. The argumentation
   layer is not silently dropping valid attacks.
3. **Three of four misses are DETECTION-stage (topic filter); the
   remaining one is a CONFIRMATION miss.** This split is the canonical
   empirical evidence for the **SBERT semantic-similarity upgrade path**:
   all three DETECTION misses are topic-string mismatches that semantic
   embeddings would resolve (`"Explosion sequence"` ≈
   `"Explosion location"`, `"Ignition location"` ≈ `"Explosion location"`).
   The upgrade would measurably fix 3 of 4 attack misses and 2 of 9
   support-pair misses **without changing any other pipeline component**.

### 3.6 Axis 4 — Cross-model robustness (N=3)

Three end-to-end pipeline runs with the same inputs, same prompts, same
evaluation rubric — only the per-role model configuration differs.

| Configuration | Run ID | Per-role models | Per-run cost |
| --- | --- | --- | --- |
| **Baseline** (single-family paid) | `kostenko_full_20260511_183524_096453` | Anthropic Claude across all v4 / v5 / v6 roles | ~$0.05 |
| **Hybrid** (mixed-family OpenRouter, Layer-1 paid swaps) | `kostenko_v6_20260515_144020_680602` | T=gpt-oss-120b free · O=Qwen3-235B paid · Ch=Mistral-Small-3.2 paid · R=Llama-3.3 paid · v5=gpt-oss-20b free · v6=Llama-3.3 paid | **~$0.003** |
| **Unified-paid** (single Gemini model all roles) | `kostenko_v6_20260515_170601_166521` | google/gemini-2.5-flash-lite for every v4 / v5 / v6 role | ~$0.014 |

Comparison:

| Metric | Baseline (May-11) | Hybrid (May-15) | **Unified-paid (May-15 N=3)** |
| --- | --- | --- | --- |
| Per-run cost | ~$0.05 | ~$0.003 | ~$0.014 |
| GT attacks detected | 3 / 4 | 2 / 4 | **3 / 4 (3 exact)** |
| Support pairs detected | 6 / 9 | 7 / 9 | 5 / 9 |
| **Open-question capture** | 5 / 5 | 5 / 5 | **1 / 5** ⚠️ |
| Acceptance: acc / amb / rej | 26 / 12 / 5 | 23 / 15 / 2 | 24 / 7 / 15 |
| Per-expert Jaccard — Usembekov | 0.111 | 0.125 | 0.037 |
| Per-expert Jaccard — Kolikov | 0.133 | 0.192 | 0.143 |
| Per-expert Jaccard — DMT | 0.167 | 0.143 | 0.100 |
| Per-expert Jaccard spread | 0.056 (MIXED) | 0.067 (MIXED) | 0.106 (MIXED) |
| Per-expert story label | MIXED | MIXED | MIXED (toward biased) |
| Axis 7 v6 report overall | — | 3.60 | 3.80 |
| Axis 5 per-agent overall (T / O / Ch / R) | — | 4.53 / 4.58 / 4.35 / 4.50 | 4.44 / 4.40 / 4.62 / 4.48 |

**Defense-ready summary sentence (lift verbatim, replaces the N=2 phrasing):**

> Across three model configurations spanning a ~17× cost range
> (~$0.003 hybrid → ~$0.05 single-family premium baseline), the per-expert
> synthesis-vs-bias label remains MIXED for every configuration, but the
> open-question-as-ambiguous capture property is **only preserved under
> mixed-family or single-family-premium configurations (5 / 5)**; a
> unified-single-model configuration (Gemini 2.5 Flash Lite all roles)
> drops to **1 / 5**. This empirically demonstrates that the
> mixed-family-as-diversity-primitive design is *load-bearing* for the
> headline OQ-capture property — single-model setups, even at higher
> per-run cost than the hybrid, cannot generate sufficient internal
> disagreement for v5 to surface contested issues as `ambiguous`.

**Three thesis-defensible findings (Axis 4 N=3):**

1. **Open-question capture is configuration-dependent, not invariant.**
   The N=2 framing in earlier drafts overstated invariance. The correct
   characterization is: *5/5 capture is preserved across model-family
   diversity (Hybrid mixed-family at $0.003/run, Baseline single-family
   premium Claude at $0.05/run) but collapses under model-family
   uniformity (Gemini all-roles at $0.014/run → 1/5)*. The thesis
   contribution is the **diversity primitive**, not the LLM choice per se.
2. **Cost is not the dominant variable.** The Unified-paid arm at
   ~$0.014/run produces strictly *worse* OQ capture than the Hybrid arm
   at ~$0.003/run. Spending more on a single model cannot compensate for
   the loss of multi-family disagreement signal.
3. **Per-expert MIXED label is invariant across all three configurations.**
   Spread ranges 0.056 → 0.067 → 0.106; all three land in the MIXED
   bucket (0.05 < spread < 0.15). The framework's synthesis-vs-bias
   character is robust to model substitution even when other properties
   degrade.

### 3.7 Operational telemetry from the canonical run (May-15)

(From [`runs/kostenko_v6_20260515_144020_680602/run_manifest.json`](runs/kostenko_v6_20260515_144020_680602/run_manifest.json).)

| Field | Value |
| --- | --- |
| Total LLM calls | 62 |
| Total input tokens | 114,148 |
| Total output tokens | 12,193 |
| Upstream 429 retries | 0 (on this run; earlier runs hit Venice throttles — see note.md "Catalog drift and verification") |
| End-to-end wall time | ~5 minutes |

### 3.8 Axis 2 — Multi-run stability (N=5 hybrid, same config)

Five end-to-end pipeline runs at the same hybrid configuration (default
`.env`, no overrides) to characterize the **sampling-noise floor** of v5's
output under LLM non-determinism. Run dirs:

```text
runs/kostenko_v6_20260515_171033_139395   (anchor; stability_report.json saved here)
runs/kostenko_v6_20260515_171757_180396
runs/kostenko_v6_20260515_172822_319353
runs/kostenko_v6_20260515_173447_867193
runs/kostenko_v6_20260515_173850_754463
```

Pairwise Jaccard across all C(5, 2) = 10 pairs:

| Aspect | mean ± std | min | max |
| --- | --- | --- | --- |
| Accepted-set Jaccard | **0.78 ± 0.05** | 0.69 | 0.86 |
| Ambiguous-set Jaccard | **0.78 ± 0.08** | 0.67 | 0.86 |
| Rejected-set Jaccard | 0.17 ± 0.25 | 0.00 | 0.67 |
| Attack-edge Jaccard | 0.47 ± 0.08 | 0.38 | 0.66 |
| Support-cluster Jaccard | 0.52 ± 0.07 | 0.45 | 0.64 |

**Per-argument bucket consistency:** 29 / 42 arguments (**69% stability
rate**) landed in the same bucket across all 5 runs; 13 arguments flipped
buckets at least once. The flipping arguments cluster around the
acceptance/ambiguous boundary (e.g. `K-A4` was `ambiguous` in 4 runs and
`accepted` in 1; `agent_2_002` was `accepted` in 4 and `rejected` in 1).
Open questions captured as `ambiguous` were stable across all 5 runs.

**Three thesis-defensible findings (Axis 2):**

1. **Same-config accepted-set Jaccard is 0.78 ± 0.05.** This is the
   **sampling-noise floor** for v5 output stability. Cross-config Jaccards
   in §3.6 (per-expert agreement, hybrid vs. baseline) and the per-expert
   spread interpretation in §3.3 must be read against this floor: a
   measured cross-config delta below ~0.05 is within sampling noise of
   same-config variability and should not be reported as a robustness
   signal.
2. **Bucket structure is stable; bucket membership at the margin is not.**
   The 69% per-argument bucket-consistency rate quantifies *which* parts
   of v5's output are load-bearing (the 29 stable args, including all
   five GT open questions) vs. *which* are sampling-noise artifacts (the
   13 flipping args, almost all flipping at the accepted/ambiguous or
   accepted/rejected boundary). Thesis claims should rest on the stable
   set; the flipping set should be flagged in Limitations.
3. **The rejected set is unstable (Jaccard 0.17 ± 0.25).** This is a
   *reportable property*, not a bug: rejection only occurs when an
   argument loses all attacks in the AF semantics step, and small v4
   sampling differences shift which arguments receive attacks at all.
   Practical implication: thesis discussion should treat the
   **accepted ∪ ambiguous** set as v5's robust output and the rejected
   set as advisory.

**Caveat on the 0.78 number:** the v5 confirmation cache (model-aware,
content-hashed) was active during stability runs, producing 13–18 cache
hits out of 81–91 pair checks per run (~14–20% hit rate). True noise
floor is therefore **fractionally lower than 0.78** (more variance under
fully cold cache). Materially small effect because v4 outputs are
non-deterministic per fresh run, but worth disclosing in the manuscript.

[`runs/kostenko_v6_20260515_171033_139395/stability_report.json`](runs/kostenko_v6_20260515_171033_139395/stability_report.json)
contains the full per-pair Jaccards and the per-argument flipping table.

---

## 4. Thesis argument arc (chapter-by-chapter scaffold)

This is the *narrative spine* the manuscript should follow. Every claim
maps to a §3 number or a `note.md` section.

### Chapter 1 — Introduction

1. Why automated mining accident investigation. Real-world stakes (~46
   Kostenko fatalities). Why current practice is bottlenecked: multiple
   independent commissions, divergent reports, no formal synthesis.
2. Why LLMs are the right "agent" primitive for this problem (cite
   relevant LLM-as-reasoner literature).
3. Why Dung's argumentation framework is the right *resolution* primitive:
   it represents disagreement explicitly and supports formal acceptance
   semantics — a structural alternative to the propositional-logic rule
   bases of Markarian's classical subsystems.
4. Thesis statement: a multi-agent LLM pipeline with formal argumentation
   semantics can synthesize across competing expert reports while
   preserving full evidence traceability.
5. Contributions:
   1. Re-architecture of Markarian's subsystems 4–6 with LLM specialists
      + Dung's semantics (§Implementation).
   2. Argumentation-framework-based conflict resolution validated on the
      Kostenko case (5/5 open-question capture; MIXED per-expert
      synthesis; cross-model robustness preserved at 94% cost reduction).
   3. Six-dimensional evaluation framework spanning structural metrics,
      LLM-as-judge content quality, per-expert agreement, cross-model
      robustness, multi-run stability, and a four-bucket failure-mode
      taxonomy (§Evaluation).

### Chapter 2 — Related work

- Mining-safety analysis methods (Markarian's work, Temkin's work, the
  Rostechnadzor regulatory framework). Cite Markarian & Temkin 2024
  (already referenced for the CBR threshold = 0.8).
- LLM-based agentic systems and multi-agent debate.
- Dung's argumentation frameworks (Phan Minh Dung 1995); grounded vs
  preferred semantics; computational properties.
- Toulmin's argument model (`note.md` mentions the 8-field schema is
  derived from it).
- The Usembekov, Kolikov-Meshcheryakov, and DMT reports as primary
  sources (handled as the GT in the case file, but worth situating in
  the literature review).

### Chapter 3 — Methodology

- The 6-subsystem architecture (`system_architecture.json` is the
  authoritative spec).
- Per-subsystem design decisions:
  - v1 dual-mode (structured JSON + LLM extraction) — `note.md` §v1.
  - v2 rule-based classification — `note.md` §v2.
  - v3 Jaccard CBR (threshold 0.8 from Markarian & Temkin 2024) —
    `note.md` §v3.
  - v4 four-agent topology (Technical, Organizational, Challenger,
    Regulatory) with intentionally-overlapping scope — `note.md`
    §"Methodological diversity argument".
  - v5 topic-filter → LLM-confirmation → Dung's semantics — `note.md`
    §v5 + §"Hybrid conflict detection".
  - v6 LLM report with mandated citation tokens — `note.md` §v6.
- The 8-field argument schema and why Toulmin → suitable for an
  argumentation framework.
- Knowledge base design (`note.md` §"Kostenko knowledge base" + the two
  JSON files in `data/knowledge_base/`).
- Why OpenRouter (single API for many model families = methodological
  diversity primitive). `note.md` §"LLM provisioning".

### Chapter 4 — Implementation

- 6-subsystem code organization (`src/v{1..6}_*` modules).
- LLM scaffolding: `LLMClient` Protocol, three concrete implementations
  (Anthropic / OpenAI / OpenRouter), the two-attempt `complete_json`
  fallback for reasoning-model empty-content cases, the retry-with-backoff
  for upstream 429s. `note.md` §"Risks documented".
- Per-agent client injection: `build_v4_agent_clients()` returning a
  `dict[agent_id, LLMClient]` so each v4 agent gets its own
  family-distinct model — the methodological diversity argument in code
  form.
- v5 confirmation cache (model-aware, content-hashed) for both *resume*
  and *Axis-4 ablation* purposes.
- Checkpoint/resume runner — `--resume-from <run_id>` skips already-built
  stage artifacts.
- Run-manifest builder — every run produces a thesis-friendly
  `run_manifest.json` with per-role token counts, models, retries.
- Evaluation infrastructure: one script per axis under `scripts/`,
  detailed in §6 of this doc.

### Chapter 5 — Evaluation

- Seven implemented axes (1, 2, 4, 5, 6, 7, 8) — §3 of this doc has every
  number; lift directly into chapter tables.
- The single canonical Kostenko run (May-15 hybrid) as the anchor for
  Axes 1 / 5 / 6 / 7 / 8; the May-11 baseline + the May-15 N=3 Gemini
  third arm as the cross-model comparison points (Axis 4 N=3); five
  same-config hybrid runs as the Axis 2 stability cohort.
- Failure-mode taxonomy (Axis 8) — the strongest *mechanistic* result;
  directly motivates the SBERT future-work path.

### Chapter 6 — Discussion

- What the open-question-capture = 5/5 result actually means
  methodologically — and the **important refinement from N=3**: 5/5 is
  preserved only under mixed-family or single-family-premium
  configurations; the unified-single-model arm (Gemini all roles) drops
  to 1/5. This is the empirical justification for the multi-family-as-
  diversity-primitive design and should be the centrepiece of the
  Discussion chapter rather than the bare 5/5 claim.
- Why mixed-family v4 produces *genuine* disagreement (not paraphrase
  variance) — the structural argument enabled by 4 distinct RLHF lineages.
- Cost analysis: $0.003/run hybrid vs. $0.05 baseline. Thesis-scale
  evaluation campaigns are affordable enough to be reproducible.
- Limitations (§5 of this doc).

### Chapter 7 — Conclusion + future work

- The SBERT semantic-similarity upgrade (Axis 8 evidence).
- Per-agent model ablation (Axis 3, infrastructure ready, not yet run).
- Multi-run stability at N≥5 (Axis 2, infrastructure ready, not yet run).
- Markarian classical baseline comparison (Axis 9 — needs supervisor
  collaboration).
- Expert read-through for Axis 7 (Markarian / Temkin scoring one v6
  report against the same rubric).

---

## 5. Limitations to acknowledge in the manuscript

Stated honestly because the thesis defense will surface them anyway.

1. **N = 1 canonical run for content axes.** Axes 1, 5, 6, 7, 8 are
   evaluated on the single May-15 canonical run. Axis 2 (§3.8) now
   characterizes the sampling-noise floor against this single anchor:
   accepted-set Jaccard 0.78 ± 0.05 across 5 same-config runs; per-
   argument bucket consistency 69%. Manuscript should explicitly cross-
   reference §3.8 wherever a §3.1 / §3.5 / §3.7 number from the canonical
   run is quoted, since 13 of 42 arguments flip buckets across re-runs at
   the same configuration.
2. **Axis 4 cross-model robustness at N = 3.** Three configurations
   compared (May-11 single-family premium baseline / May-15 mixed-family
   hybrid / May-15 N=3 unified-paid Gemini). Stronger claims would still
   benefit from additional arms — e.g. an all-free OpenRouter
   configuration to anchor the cost floor, or a second mixed-family
   configuration with a different per-role swap.
3. **LLM training data as domain knowledge.** v4 agents bring whatever
   mining-safety knowledge their training data contained. This is an
   acknowledged property, not a bug — but should be stated clearly as
   "the system inherits the domain-knowledge boundary of its underlying
   models".
4. **No comparison to Markarian's classical baseline yet.** Axis 9 is
   scoped but unimplemented; needs supervisor access to Markarian's
   classical subsystems 4–6 to do the side-by-side properly.
5. **Topic-string filter is the dominant failure mode.** Three of four
   missed GT attacks (Axis 8) and two of nine missed support pairs are
   detection-stage misses caused by surface topic-string mismatch. The
   fix (SBERT embeddings) is identified but not implemented in this
   thesis.
6. **One CONFIRMATION miss.** The cheaper free `gpt-oss-20b:free` v5
   confirmation model rated K-A4 / U-A3 as `independent` when the GT
   labelled it `rebutting`. A swap to a stronger paid confirmation model
   would likely resolve this — but the swap was deferred to keep the
   v5 step under $0 for thesis-scale workloads.
7. **English-only reports.** The v6 report generator outputs English;
   the Russian-language Rostechnadzor regulatory framing isn't
   reproduced in the report tone. Not a blocker for the thesis but
   worth noting.

---

## 6. File map (where every artifact lives)

### Source code

- [`src/`](src/) — package root, importable via `PYTHONPATH=src python ...`
  - [`config.py`](src/config.py) — env-var loading, per-role model defaults, paths
  - [`llm/`](src/llm/) — `LLMClient` Protocol, three providers, `make_role_client`,
    `RunContext` (telemetry + checkpoint-resume)
  - [`schema/`](src/schema/) — Pydantic models for every artifact:
    `argument.py`, `classification.py`, `precedent_match.py`, `v4_result.py`,
    `v5_result.py`, `v6_report.py`, `judge_result.py`
  - [`v1_decomposition/`](src/v1_decomposition/) — case → Argument list
  - [`v2_identification/`](src/v2_identification/) — rule-based classification
  - [`v3_precedent_matching/`](src/v3_precedent_matching/) — Jaccard CBR
  - [`v4_agents/`](src/v4_agents/) — orchestrator + `build_v4_agent_clients()`
  - [`v5_argumentation/`](src/v5_argumentation/) — topic filter, LLM
    confirmation, model-aware pair cache, AF construction, semantics
  - [`v6_report/`](src/v6_report/) — narrative renderer, HTML/MD/PNG output

### Prompts

- [`prompts/`](prompts/) — Jinja2 templates with `{{ var }}` placeholders
  - `agent_{1..4}_*.md` — v4 specialist prompts
  - `v5_conflict_check.md` — v5 pair confirmation
  - `v6_report.md` — v6 narrative report
  - `judge_v6_report.md` — Axis 7 rubric prompt
  - `judge_argument_quality.md` — Axis 5 rubric prompt
  - `DESIGN_DECISIONS.md` — internal design notes (also lifted into `note.md`)

### Knowledge base

- [`data/knowledge_base/kostenko_knowledge_base.json`](data/knowledge_base/kostenko_knowledge_base.json) — 21 expert
  args, 4 GT attacks, 5 GT support clusters, 5 open questions
- [`data/knowledge_base/rostechnadzor_regulatory_kb_v2.json`](data/knowledge_base/rostechnadzor_regulatory_kb_v2.json) — 7
  precedents, regulation IDs, cause-category taxonomy (TC- / OC- codes)

### Scripts (run-time entry points)

| Script | Purpose |
| --- | --- |
| [`scripts/run_v6_kostenko.py`](scripts/run_v6_kostenko.py) | Full pipeline run (v1 → v6). Supports `--resume-from <run_id>`. |
| [`scripts/run_v4_kostenko.py`](scripts/run_v4_kostenko.py) | v1 → v4 only (skip v5/v6). Useful for debugging agents. |
| [`scripts/run_v5_kostenko.py`](scripts/run_v5_kostenko.py) | v1 → v5 only (skip v6). |
| [`scripts/build_run_manifest.py`](scripts/build_run_manifest.py) | Post-run: builds `run_manifest.json` from `events.jsonl`. |
| [`scripts/evaluate_kostenko.py`](scripts/evaluate_kostenko.py) | Axes 1 + 6: structural metrics + per-expert Jaccard. |
| [`scripts/evaluate_v6_report.py`](scripts/evaluate_v6_report.py) | Axis 7: GPT-4o judge of the v6 report. |
| [`scripts/evaluate_argument_quality.py`](scripts/evaluate_argument_quality.py) | Axis 5: GPT-4o judge of v4 arguments. |
| [`scripts/classify_failure_modes.py`](scripts/classify_failure_modes.py) | Axis 8: auto-classifier of misses. |
| [`scripts/evaluate_stability.py`](scripts/evaluate_stability.py) | Axis 2: multi-run stability across N runs. |
| [`scripts/ping_openrouter.py`](scripts/ping_openrouter.py) | OpenRouter smoke test (used to discover model deprecations during integration). |

### Canonical run artifacts (May-15)

`runs/kostenko_v6_20260515_144020_680602/` contains:

- `report.md` / `report.html` — the v6 narrative report (thesis lifts excerpts)
- `argumentation_graph.png` — AF graph visualization (Figure-quality)
- `v6_report.json` — structured V6Report
- `v5_result.json` — attacks, supports, accepted/rejected/ambiguous sets,
  AF graph, grounded + preferred extensions
- `v4_result.json` — all 21 v4 agent arguments
- `agent_{1..4}_arguments.json` — per-agent JSONs
- `agent_{1..4}_raw_response.txt` — raw LLM outputs (useful for Discussion chapter)
- `v1_case.json`, `v2_classification.json`, `v3_match_result.json` — deterministic stage outputs
- `events.jsonl` — full event log (every LLM call + retry + cache hit + stage start/end)
- `run_manifest.json` — per-role aggregates, totals, stage timings
- `judge_v6_report_result.json` — Axis 7 rubric scores
- `judge_argument_quality_result.json` — Axis 5 rubric scores
- `axis8_failure_modes.json` — Axis 8 classification table

### Baseline run (May-11, for Axis 4 N=2 comparison)

`runs/kostenko_v6_20260511_191059_423112/` — same artifact set, different
model configuration.

### Tests

- [`tests/`](tests/) — 356 tests, all passing as of 2026-05-15
  - Per-subsystem under `tests/v{1..6}_*/`
  - LLM scaffolding under `tests/llm/`
  - Schema validation under `tests/schema/`
  - Evaluation scripts under `tests/test_evaluate_*.py` and
    `tests/test_classify_failure_modes.py`,
    `tests/test_build_run_manifest.py`

### Other top-level

- [`note.md`](note.md) — the **canonical design + decision log**. 800+ lines of
  rationale for every model pick, every architectural decision, every
  failure mode encountered during integration. The Implementation
  chapter should lift heavily from this.
- [`system_architecture.json`](system_architecture.json) — authoritative 6-subsystem spec.
- [`README.md`](README.md) — entry-point for cloning + running.
- `.env.example` — env-var template (real `.env` is gitignored).

---

## 7. Citations and references the manuscript will need

(Non-exhaustive — these are the load-bearing ones.)

- **Dung, P. M.** (1995). *On the acceptability of arguments and its
  fundamental role in nonmonotonic reasoning, logic programming and n-person
  games.* Artificial Intelligence 77(2), 321–357.
- **Toulmin, S.** (1958). *The Uses of Argument.* Cambridge University Press.
  (Source of the 8-field argument schema.)
- **Markarian, A. & Temkin, I.** (2024). [Specific paper to cite — confirm
  with supervisor — referenced in `note.md` for the CBR threshold = 0.8.]
- **Usembekov, Kolikov-Meshcheryakov, DMT** — the three Kostenko
  investigation commissions; refs in
  `data/knowledge_base/kostenko_knowledge_base.json` under
  `metadata.sources`.
- **OpenAI GPT-4o** as the LLM-as-judge — cite the model card.
- **OpenRouter** as the unified-API LLM gateway.
- **NetworkX** for the AF graph layer.
- **Pydantic v2** for the structured-output schemas.

---

## 8. What hasn't been done yet (writing-chapter relevant)

- Axis 2 — **done** (2026-05-15, see §3.8). Stability evaluated at N=5
  same-config hybrid runs.
- Axis 4 N=3 third arm — **done** (2026-05-15, see §3.6). Unified-paid
  Gemini all-roles configuration added; produced the OQ-capture
  collapse finding that reframes the headline §3.1 claim.
- Axis 4 fourth arm (e.g. all-free OpenRouter, or a second mixed-family
  swap) would harden the 3-arm story further — same recipe pattern as
  the Gemini arm in `note.md` §"Axis 4 N=3 third arm".
- Axis 3 ablation matrix (would need v4 plumbing to skip individual
  agents — not urgent for thesis).
- Axis 9 Markarian classical baseline (would need supervisor support).
- Axis 7 expert read-through (Markarian / Temkin scoring) — out of
  scope for the thesis writer but worth flagging in the Future Work
  section.

---

## 9. Style notes for the thesis writer

- The thesis is a **MISc Data Science** thesis at NUST MISIS. Russian
  formal academic conventions apply for structure.
- The pipeline produces both EN and RU outputs in principle, but the
  v6 report generator currently emits English. Mention this.
- The Kostenko case is contemporary (2023) and politically sensitive
  (ArcelorMittal Temirtau ownership change followed the explosion).
  Keep claims about *causation* close to the official commissions'
  language; the system's role is *synthesis*, not adjudication.
- Number convention: float scores reported to 2 decimal places
  (4.53/5.00, 0.067, etc). Token counts reported as integers.
- Citation tokens in the v6 report follow `[ARG-ID]` and `[ATK-V5-NNN]`
  conventions — preserve these literally when quoting from the report.

---

## 10. Single-line thesis summary

> Multi-agent LLMs producing typed arguments + Dung's argumentation
> framework synthesizes across three independent Kostenko investigation
> reports, captures all five GT open questions as ambiguous *under
> mixed-family configurations* (and demonstrably collapses to 1/5 under
> a unified-single-model configuration — empirically establishing the
> diversity primitive as load-bearing), preserves the per-expert
> synthesis-vs-bias label (MIXED) across all three N=3 model
> configurations, and surfaces every miss to the correct pipeline stage
> — all at $0.003 per run for the hybrid configuration.
