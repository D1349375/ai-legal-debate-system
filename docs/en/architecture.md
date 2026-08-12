# Architecture

> English version of [`docs/zh/architecture.md`](../zh/architecture.md).

The system combines two existing engineering foundations — a zero-tolerance content
verification pipeline and a multi-agent structured debate engine — with a distilled
`taiwan-legal-pleading` skill that carries the drafting conventions of Taiwanese litigation
documents.

The point is not template filling. **Before anything is drafted, a plaintiff's counsel agent
and a defendant's counsel agent rehearse the dispute against each other**, surfacing the
compliance gaps and the case's weakest points. Only then is a draft produced.

---

## 1. Three engines

### Engine 1 — knowledge and zero-tolerance verification

Addresses the first characteristic failure of legal AI: inventing statutes and case numbers
that sound plausible.

- **Statutes.** Full text of five civil-side statutes (Civil Code, Company Act, Labor
  Standards Act, Consumer Protection Act, Criminal Code), parsed programmatically from the
  Ministry of Justice database (`law.moj.gov.tw`). Deliberately not AI-summarized — an early
  attempt using a fetch tool that passed content through a small summarizing model was
  rejected as unacceptable for verification purposes, and replaced with raw HTML retrieval and
  programmatic parsing so the article text is preserved verbatim.
- **Judgments.** Supreme Court civil judgments, checked first against the local seed corpus as
  a fast path, falling back to a live query of the Judicial Yuan judgment search system (FJUD)
  when there is no local hit — so verification is not limited to whatever happens to be in the
  local corpus.
- **The cache is never the authority.** `corpus/` is an acceleration layer for comparison.
  Statute text is always re-checked against the official source rather than trusted from
  cache.

Implementation: `engine/verify.py`, modelled on a `draft → fact_checked → published` three-state
governance flow.

### Engine 2 — multi-agent adversarial simulation

Addresses the second failure: agents that merely agree with each other behind different
personas.

- **Plaintiff's counsel agent** — the strongest available claim, its legal basis, and the
  measure of damages.
- **Defendant's counsel agent** — exclusion clauses, procedural defects, gaps in the
  opponent's evidence.
- **Judge agent** — presides, organizes the contested issues, questions both sides.

Round 1 is blind; round 2 is structured rebuttal in which each side must engage the
opponent's strongest argument and state its own falsifier. Aggregation is mechanical, in plain
code that the model cannot override (`engine/aggregate.py`).

The countermeasures against agents collapsing into one voice are analysed in
[multi-agent homogenization](multi-agent-homogenization.md), with retrieval-side isolation
specified in [the stance-isolated RAG spec](stance-isolated-rag-spec.md).

### Engine 3 — pleading distillation

Addresses the third failure: output that reads nothing like a filed document.

Distilled know-how falls into three areas:

- **Structural heuristics.** A clear separation of the statement of claim, the basis of the
  claim, the facts and reasoning, and the evidence schedule — with the facts-and-reasoning
  section advancing by strict legal syllogism.
- **Expression DNA.** Orthodox connectives and openings (`按…定有明文`, `次查…`, `再查…`,
  `揆諸前揭最高法院判例意旨…`), avoiding both colloquial Chinese and translationese.
- **Negative rules and courtroom decorum.** Emotive phrasing is automatically corrected into
  professional legal rhetoric — "the other side is shameless and won't pay" becomes "the
  defendant's argument is plainly an evasion of responsibility and is without merit" — and the
  court of jurisdiction and the amount in dispute are always annotated.

---

## 2. Distillation and retrieval must stay separate

**Distillation extracts only the abstract regularity of *how to write*; it never memorizes
*what was decided*.** SKILL.md retains structure, register and syllogistic logic. Complete
judgment text is never embedded.

Putting whole judgments into the prompt as few-shot examples would cause two problems:
anchoring bias, where the agent fits new facts into remembered old patterns; and data
contamination, which would invalidate any later attempt to measure accuracy against those same
judgments — a student sitting an exam whose answers they have memorized.

Three corpora therefore stay completely isolated: the distillation corpus, the corpus retrieved
live via RAG, and the validation test set. Full treatment in
[corpus contamination and validation](corpus-contamination-and-validation.md).

---

## 3. End-to-end flow

1. **Input.** The user describes the dispute in plain language and uploads the relevant
   contract or correspondence.
2. **Statute and precedent matching.** The system pulls current Taiwanese statutes and relevant
   Supreme Court authority through the verification engine.
3. **Adversarial simulation.** The plaintiff agent advances an argument; the defendant agent
   rebuts on an exclusion clause in round 2. The system marks the case's two largest
   evidentiary weaknesses and the evidence that would close them.
4. **Drafting.** The `taiwan-legal-pleading` skill produces a first draft in the Judicial
   Yuan's format.

---

## 4. Engineering status

- **Phase 0 corpus: 2 of 3 complete.** The five statutes (`corpus/statutes/`) and the Supreme
  Court civil judgments (`corpus/judgments/`, via the official open-data API) are in place.
  **The one remaining blocker is `corpus/pleadings/`** — 20 real de-identified pleadings, which
  is an access problem rather than an engineering one, and needs a lawyer design partner.
- **Phase 1.1 (project skeleton) and 1.3 (statute/precedent verification engine) are complete
  and tested.** `database/schema.py`, `database/db.py`, `engine/aggregate.py`,
  `engine/verify.py` and all six `main.py` subcommands are implemented, with the test suite
  passing — including integration tests that actually hit the official sites — and a full
  end-to-end smoke test run (case input → three-stage exchange on both sides → judicial
  questioning → mechanical collation → verification → decision → pleading), covering the
  failure paths for write-once persistence and the verification gate.
- **Phase 1.2 (`taiwan-legal-pleading` distillation) is blocked** on the Phase 0 pleading
  corpus.
- **Phase 1.4 (the legal-debate orchestrator skill, four-stage prompt templates) has not
  started** — this is the only part requiring an agent runtime to actually play the plaintiff,
  defendant and judge roles.

**Architecture correction (confirmed 2026-08-06).** The judge role was pulled into the Phase 1
core (three roles — plaintiff's representative, defendant's representative, judge — on a single
model), rather than being the later flagship expansion the courtroom report describes. The
heterogeneous model matrix and information-asymmetric facets are deferred to Phase 3, triggered
by observing argument convergence during Phase 2 lawyer testing — not by a date arriving.

---

## 5. Known technical risks

**Document-level retrieval mismatch (DRM).** Taiwanese judgments are highly formulaic, so
naive retrieval frequently returns the wrong source judgment — measured above 95% in the
literature on comparable material. This determines whether a lawyer can trust the tool at all.
Addressed with summary-augmented chunking; see [the RAG system design](rag-system-design.md).

**Legal compliance constraint.** Article 127 of Taiwan's Attorney Act makes drafting litigation
documents for the general public for a fee a criminal offence carrying up to three years'
imprisonment. This is the reason the project is shaped as an internal tool for qualified
lawyers rather than a consumer service, and it is a hard constraint on the architecture, not a
market preference.

**Fact finding.** The system can argue law; it cannot gather physical evidence. If the input
facts are incomplete, the adversarial output and the draft are correspondingly worthless —
garbage in, garbage out.

**Token cost.** A single multi-agent exchange plus precedent retrieval consumes roughly
300,000–500,000 tokens.

**Output quality validation.** No lawyer is needed to review every sample: the judgment already
states who prevailed, the damages, and the contested issues, so it serves directly as ground
truth for automated comparison (outcome accuracy, issue hit rate, citation authenticity), with
only the 5–10% of boundary cases the automated metrics cannot resolve going to a human. This is
an optional addition rather than a launch requirement, but it accelerates earning a design
partner's initial trust. See
[corpus contamination and validation](corpus-contamination-and-validation.md).

---

## 6. Reference architectures reused

- `DebateSystem/engine` — pure-function mechanical aggregation and the R1/R2 two-round protocol
  — is the direct prototype for engine 2, followed file by file during Phase 1.1.
- The `draft → fact_checked → published` three-state governance from the Startup Guide project
  is the prototype for engine 1's verification flow, implemented in Phase 1.3.
- The `huashu-nuwa` skill performs the `taiwan-legal-pleading` distillation, once the Phase 0
  pleading corpus is available.
