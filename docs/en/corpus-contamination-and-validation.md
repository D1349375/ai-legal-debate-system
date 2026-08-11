# In-House Legal Database: Distillation Contamination Risk and Value Validation

> English version of [`docs/zh/corpus-contamination-and-validation.md`](../zh/corpus-contamination-and-validation.md).

> **Date:** 2026-08-06
> **Position:** technical appendix — assessing two critical risks in building an in-house
> judgment database.
> **Questions addressed:**
> 1. If a skill is distilled from public judgments, will the counsel agents acquire an
>    "impression" of those judgments and become biased?
> 2. How can the value of the adversarial and pleading output be validated without hiring
>    lawyers to review it manually?

---

## 1. Background

The next phase runs the existing system over public Taiwanese judgments and builds a database
from the results, as the data foundation for the adversarial engine and the pleading
distillation engine. Technically that immediately raises two easily overlooked issues, either
of which can undermine the system's credibility and the validity of later validation:
**whether the distillation corpus contaminates agent judgment**, and **how to validate output
value cheaply.**

---

## 2. Question 1: will the counsel agents "remember" the judgments used for distillation?

### 2.1 The risk depends on *how* you distil, not *whether* you distil

What matters is whether judgments are used to extract **abstract regularities** or fed to the
agent directly as **case templates**. These are two entirely different technical paths with
different risk profiles.

### 2.2 Case A: distilling only style and structural regularity (low risk)

The Nuwa distillation methodology takes a large body of material and extracts abstract
regularities — mental models, decision heuristics, expression DNA. What ends up written into
SKILL.md is a **description of rules** (for example: open a statutory citation with the
formula 「按…定有明文」; advance the facts-and-reasoning section by legal syllogism), not the
judgment text itself.

Under this model the agent reads "how this kind of document should be written", not "what a
court decided in a specific case". Because the distilled content is already abstracted and
de-cased, the agent holds no traceable memory of any individual judgment, and contamination
risk is low.

### 2.3 Case B: stuffing whole judgments into the prompt as few-shot examples (high risk)

If dozens of complete judgments are put into the system prompt as examples so the agent learns
adversarial logic or pleading style, two problems follow:

**(1) Anchoring bias.** The agent tends to fit new case facts into the old patterns it
remembers. Even where the new case's decisive facts differ, surface similarity can produce a
false analogy and an imprecise adversarial strategy or legal conclusion.

**(2) Data contamination.** This is more serious and more easily missed. If you later want to
use *these same judgments* to test the adversarial system's accuracy — feeding in a judgment's
fact description, running the simulation, and checking whether the predicted outcome matches
the court's — but those judgments were already in the prompt for the agent to see, the test
result is meaningless. It is a student sitting an exam whose answers they have memorized: the
score looks good and reflects nothing about reasoning ability. This would directly destroy the
credibility of the automated validation mechanism described in §3.

### 2.4 Recommended architecture: separate distillation from retrieval

To keep the expressive quality benefits of distillation while avoiding memory contamination:

| Stage | How material is used | Resident in the prompt? |
|---|---|---|
| **Distillation** (building the skill) | Extract structure, register, syllogistic logic as abstract rules, written into SKILL.md | Yes, but the content is already de-cased |
| **Production** (live adversarial work and generation) | When case support is needed, retrieve relevant judgment passages via RAG at the moment of use | No — used and discarded, never resident in the system prompt |
| **Validation** (testing accuracy) | Use judgments **never touched by distillation or retrieval** as an independent test set | Not applicable; they serve only as an external scoring baseline |

The core principle: **distil only "how to write", never memorize "what was decided"; when case
support is needed, retrieve it live and discard it, never leaving it resident in the prompt;
and judgments used for validation must be completely isolated from those used for training or
distillation, or the test results are invalid.**

---

## 3. Question 2: validating the value of the output cheaply

### 3.1 The key insight: judgments carry their own answer key

Most machine learning projects need to hire experts to annotate data before output quality can
be validated — exactly the extra cost the user was worried about. This project has a structural
advantage: **the court has already made a final determination on every judgment — who won, the
damages awarded, which side's argument was accepted, and on which statutory basis — and all of
it is already written in the judgment.**

So no lawyer needs to be hired to re-score anything. The real outcome serves directly as
automated ground truth, and the gap between system prediction and actual court outcome measures
the output's value.

### 3.2 Layered validation, cheapest first

**3.2.1 Outcome accuracy (fully automated, zero cost).** Extract the fact description from a
judgment, run the adversarial simulation, record the system's prediction of who prevails and
the damages range, and compare against the actual outcome. Fully computed in code, no human
involvement.

**3.2.2 Issue hit rate (automated, zero cost).** Taiwanese judgments usually contain an explicit
"the contested issues before this court are as follows" passage, which is itself the court's
official answer key. Compare the issue list the adversarial agents produced against the court's
actual list and compute a hit rate. A higher rate means the adversarial engine's issue
identification is closer to real judicial practice. This is text comparison, requiring no legal
expertise.

**3.2.3 Citation authenticity check (automated, zero cost).** Programmatically verify every
statute number and judgment case number cited during the adversarial process and in the pleading
output against the official statute database and the Judicial Yuan judgment system, confirming
the citation exists and the content matches. This is the same idea as the "RAG eliminates
hallucination" claim Lawsnote markets — pure data comparison engineering, no legal judgment
involved, fully automatable.

**3.2.4 LLM-as-judge double-blind cross-evaluation (low cost, not human).** The Nuwa skill
project validates its own distillation quality by having two independent AI agents cross-evaluate
double-blind across several dimensions (stance consistency, style distinctiveness, source
transparency, structural completeness) rather than relying on human review. The same design can
be applied here with dimensions for adversarial quality and pleading professionalism, assigning
another independent LLM as judge, run in large batches at near-zero marginal cost and scalable
to any number of cases.

**3.2.5 Human lawyer sampling on boundary cases (small cost, only where needed).** Once the four
layers above have run, they surface a small number of samples where the automated metrics look
anomalous or the LLM cross-evaluation lands in an ambiguous middle band. Only that filtered set
of genuinely contentious boundary cases — an estimated 5%–10% of the total — needs a human
lawyer. This compresses "review every sample" into "review only the hard ones", while retaining
human professional judgment as the final quality gate.

### 3.3 Cost-benefit summary

| Layer | Basis | Human needed? | Marginal cost |
|---|---|---|---|
| Outcome accuracy | The judgment's actual result | No | ≈ 0 |
| Issue hit rate | The judgment's "contested issues" passage | No | ≈ 0 |
| Citation authenticity | Official statute and judgment databases | No | ≈ 0 |
| LLM double-blind evaluation | An independent LLM agent's scoring | No | Low (API cost) |
| Boundary case calibration | Human lawyer review | Yes | Low (5%–10% sample only) |

---

## 4. Recommendations and next steps

1. **Enforce de-casing strictly during distillation.** SKILL.md keeps structure, register and
   logical rules only; no complete judgment text is embedded, so the agent forms no attachment
   to any specific case.
2. **Build an independent test set, completely isolated from the training and distillation
   corpus.** Reserve judgments that never enter distillation or RAG retrieval, reserved for
   validation, so contamination cannot distort the results.
3. **Build the fully automated validation pipeline first (3.2.1–3.2.3).** These three metrics
   involve no subjective judgment and are solvable in engineering, so they should enter CI early
   and produce quantitative scores on every iteration.
4. **Use LLM-as-judge instead of large-scale human review**, following the double-blind method
   the Nuwa skill has already validated, as the quality gate between purely automated metrics
   and human lawyer review.
5. **Concentrate lawyer time on boundary cases only** — the small set neither automated metrics
   nor LLM scoring can resolve — keeping what could have been an expensive manual review cost
   within a controllable range.

---

*Report generated 2026-08-06.*
