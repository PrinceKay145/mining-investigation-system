# v4 Agent Prompt Design — Decisions Log

**Date:** 2026-05-10  
**Status:** First draft — all four prompts written

---

## Architecture Decisions

### D1: Shared template structure
All four prompts follow an identical skeleton: System Role → Context (investigation questions, classification, precedents) → Evidence → Taxonomy → Instructions → Output Format. The only differences are the role framing, the reasoning guidance, and Agent 4's additional regulatory context block.

**Why:** Isolates the independent variable. If agents disagree, it's because their analytical lens produced different conclusions from the same evidence — not because one prompt was structured differently. Cleaner story for the thesis defense.

### D2: All agents see all 21 arguments
No filtering by "relevance" to each agent's domain. Every agent receives the complete evidence set.

**Why:** Filtering introduces designer bias. If we decide Agent 1 shouldn't see organizational evidence, we're pre-determining what counts as "technical" — defeating the purpose of having independent analysts. The role framing guides what each agent focuses on; the evidence is the same for all.

### D3: Sequential execution for Agent 3 (Challenger)
Agents 1, 2, and 4 run in parallel. Agent 3 runs after all three and receives their outputs alongside the raw evidence. Agent 3's prompt includes a dedicated "Analyst Findings to Review" section containing the outputs of all three prior agents.

**Why:** The Challenger's value is in critiquing specific conclusions, not in independently analyzing raw evidence (which would make it a fourth domain analyst with a vaguely skeptical tone). A devil's advocate reviews what others have concluded, then identifies where the reasoning is weak. Without seeing the other agents' claims, Agent 3 can't produce targeted challenges — it can only produce coincidentally overlapping alternative analyses. Sequential execution means Agent 3's conflicts with Agents 1/2/4 are precise and meaningful, which produces higher-quality input for v5.

**Implication for orchestrator:** The v4 orchestrator must call Agents 1, 2, 4 first (parallelizable), collect and serialize their outputs, inject them into Agent 3's prompt as `{{ agent_1_arguments }}`, `{{ agent_2_arguments }}`, `{{ agent_4_arguments }}`, then call Agent 3.

**Additional template variables for Agent 3:**

| Variable | Content |
|---|---|
| `agent_1_arguments` | JSON output from Agent 1 (Technical) |
| `agent_2_arguments` | JSON output from Agent 2 (Organizational) |
| `agent_4_arguments` | JSON output from Agent 4 (Regulatory) |

### D4: Output count guidance — 3 to 7 arguments
Not a hard constraint, but a stated range in each prompt.

**Why:** Too few (1-2) gives v5 nothing to work with. Too many (10+) floods v5 with low-quality claims and creates combinatorial explosion in conflict detection. The range 3-7 per agent yields 12-28 total agent arguments, which combined with the 21 expert arguments gives v5 a manageable argumentation framework of ~33-49 nodes.

### D5: Topic field as conflict detection bridge
All prompts explicitly instruct agents to use matching topic labels when addressing the same investigation question. This is the mechanism v5 uses for the first-pass conflict filter.

**Why:** The v5 pipeline uses topic-based filtering before LLM-assisted conflict confirmation. If agents use different topic labels for the same question ("Ignition source" vs "What caused ignition" vs "Fire origin"), the topic filter misses potential conflicts. Standardizing the instruction — not the vocabulary — gives agents freedom while guiding toward reusable labels.

### D6: Confidence calibration guidance
Each prompt includes a 4-tier calibration guide (0.85-1.0, 0.65-0.84, 0.45-0.64, 0.20-0.44) with domain-appropriate descriptions for each agent type.

**Why:** Without calibration guidance, LLMs tend to cluster confidence at 0.7-0.8 regardless of actual certainty. The explicit tiers with concrete criteria (e.g., "multiple independent measurements converge" for 0.85+) produce more discriminating confidence scores, which v6 can use in the final report.

### D7: Positive claim framing for Agent 3
The Challenger is instructed to frame challenges as positive claims ("The ignition source remains undetermined") rather than negations ("The ignition source is not the angle grinder").

**Why:** Dung's framework operates on arguments, not negations. A negation ("not X") doesn't produce an argument node — it's an attack relation. By requiring positive framing, Agent 3's output can be treated as first-class arguments in the framework, with attack relations discovered by v5 rather than pre-encoded by the prompt.

### D8: Canonical topic vocabulary in Agents 1, 2, 4 prompts
Each prompt's "Critical rules for the `topic` field" section now lists the 10 topic labels already used in the Kostenko evidence — `Ignition source`, `Ignition location`, `Spontaneous combustion`, `Explosion location`, `Explosion sequence`, `Explosion type`, `Gas-dynamic event`, `Methane source`, `Ventilation`, `Electrical equipment`. Agents are told to reuse these verbatim where applicable. Agents 2 and 4 additionally receive curated lists of organizational/regulatory topics they may introduce when those don't fit (e.g., `Supervision failure`, `Methane monitoring compliance`).

**Why:** v5's first-pass topic filter uses exact string equality (`"Ignition source" != "Source of ignition"`). Without a canonical vocabulary, parallel-running agents would naturally produce semantic variants and v5 would miss real conflicts. Extracting the vocabulary from existing data — rather than inventing one — is defensible: the labels are already grounded in the evidence.

### D9: Agent 3 must inherit `cause_categories` when challenging
Agent 3's prompt now includes an explicit rule: when challenging a claim from Agents 1/2/4, copy that claim's `cause_categories` rather than picking new ones. Gap-identification arguments (no analyst addressed Z) choose the category that most directly governs the unaddressed question.

**Why:** Challenges sit in the same causal territory as the claims they review. A challenge to a TC-02 mechanical-ignition claim is itself about TC-02 — the disagreement is over the conclusion, not the category at issue. Mismatched categories on challenge arguments would degrade v3 Jaccard precedent matching (different categories → different precedent overlaps for what should be co-located arguments).

---

## Template Variables

Each prompt expects these variables via `load_prompt(name, **vars)`:

| Variable | Agents 1,2,4 | Agent 3 only | Agent 4 only | Content |
|---|---|---|---|---|
| `investigation_questions` | ✓ | ✓ | ✓ | The 7 investigation questions from case metadata |
| `accident_classification` | ✓ | ✓ | ✓ | v2 output: accident type + cause profile |
| `precedent_matches` | ✓ | ✓ | ✓ | v3 output: ranked precedent cases with overlap scores |
| `evidence_arguments` | ✓ | ✓ | ✓ | All 21 Kostenko arguments (JSON) |
| `cause_taxonomy` | ✓ | ✓ | ✓ | Full TC + OC taxonomy with descriptions |
| `regulatory_requirements` | — | — | ✓ | Regulations from rostechnadzor_regulatory_kb_v2.json |
| `agent_1_arguments` | — | ✓ | — | JSON output from Agent 1 (Technical) |
| `agent_2_arguments` | — | ✓ | — | JSON output from Agent 2 (Organizational) |
| `agent_4_arguments` | — | ✓ | — | JSON output from Agent 4 (Regulatory) |

---

## Expected Conflict Zones

Based on the Kostenko evidence, these are the topics where we expect agents to produce conflicting claims (which v5 will then resolve):

1. **Ignition source** — Agent 1 will likely pick a specific mechanism; Agent 3 will likely challenge the specificity. Mirrors the real ATK-1/ATK-2 conflicts.

2. **Explosion type** — Agent 1 may distinguish methane vs. coal dust; Agent 3 may challenge the distinction. Mirrors ATK-3.

3. **Root cause attribution** — Agent 1 (technical mechanism) vs. Agent 2 (organizational enabler). This is the designed overlap — same topic, different causal framing.

4. **Methane accumulation mechanism** — Agent 1 (physical source) vs. Agent 4 (degasification non-compliance). Complementary more than conflicting, but may produce different emphasis.

5. **Ventilation adequacy** — Agent 1 (technically functional) vs. Agent 2 (organizationally inadequate design). The experts already split on this: ventilation was technically working but the design may have been inadequate for the methane hazard.

---

## What's NOT in These Prompts (By Design)

- **No inter-agent awareness for Agents 1, 2, 4:** These three prompts don't mention other agents or their roles. Agent 3 is the exception — it explicitly receives and critiques the other agents' outputs. This is by design: Agents 1/2/4 produce independent analyses, Agent 3 provides critical review.
- **No attack/support instructions:** Agents don't produce attack or support relations. They produce arguments only. v5 detects relations.
- **No ground truth hints:** No prompt references the existing argumentation framework (ATK-1 through ATK-4, SUP-1 through SUP-5). Agents must reach their own conclusions.
- **No explicit adversarial framing:** Even Agent 3 is not told to "disagree" or "argue against." It's told to think critically and propose alternatives. This implements Liang et al.'s "moderate disagreement" finding.
