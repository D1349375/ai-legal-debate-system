# Stance-Isolated RAG Retrieval: Merged Technical Specification

> English version of [`docs/zh/stance-isolated-rag-spec.md`](../zh/stance-isolated-rag-spec.md).

> **Date:** 2026-08-06
> **Purpose:** this document merges two previously separate write-ups that described the same
> module, unifying them into a single specification so that future implementation work does
> not consult two documents that have drifted apart:
>
> - [`multi-agent-homogenization.md`](multi-agent-homogenization.md) §3.1 and §3.4
>   (information asymmetry and private facets; stance-driven RAG retrieval)
> - [`rag-system-design.md`](rag-system-design.md) §4.3 (per-agent differentiated retrieval
>   strategy)
>
> Both original reports retain their full content; the overlapping sections now point here
> (see the mapping table at the end).

---

## 1. What this module is for

It answers one question: **how do the plaintiff's counsel, defendant's counsel and judge
agents retrieve stance-asymmetric, informationally unequal content from the same judgment
database — rather than all three retrieving the same material and paraphrasing it behind
different personas?** This is one of the core mechanisms preventing the "one brain wearing
different masks" pathology in multi-agent systems.

---

## 2. Core design principle: information asymmetry and private facets

- **Prosecution / plaintiff agent** — can access only the statement of claim, a
  prosecution-specific precedent set ("offence established / strict liability"), and evidence
  adverse to the defendant. **Cannot see the defence's strategy.**
- **Defence / defendant agent** — can access only the defendant's private statement, a
  defence-specific precedent set ("presumption of innocence / procedural defect / exclusion"),
  and favourable evidence. **Cannot see the prosecution's strategy.**
- **Judge agent** — can access only the public case file formally submitted to the court, and
  is blind to either side's unfiled private notes.

Each is bound to an independent retrieval facet, so the echo-chamber effect is blocked at the
data-source layer rather than by a system prompt asking the model to "play a different role".

---

## 3. Per-agent retrieval specification

### 3.1 Plaintiff's counsel agent

- **Retrieval direction:** statutes and winning precedents related to the **basis of the
  claim**.
- **Query transformation:** the user's plain-language account of the dispute is first
  translated into a legal-elements query before retrieval, bridging the semantic gap between
  everyday narrative and formal legal terminology.
- **Stance-driven keywords:** automatically appends favourable-precedent terms such as
  "offence established" / "claim established" / "appeal dismissed".
- **Data access scope:** the prosecution/plaintiff RAG facet only (private); retrieval results
  are never shared with the defendant agent.

### 3.2 Defendant's counsel agent

- **Retrieval direction:** the same case facts, queried in the opposite direction — precedents
  on defences, exclusion clauses and procedural defects.
- **Query logic:** the plaintiff and defendant agents must each run retrieval independently and
  must not share a single retrieval result. This also reduces cross-agent memory contamination.
- **Stance-driven keywords:** automatically appends "acquitted" / "insufficient evidentiary
  capacity" / "original judgment vacated".
- **Data access scope:** the defence RAG facet only (private).

### 3.3 Judge agent

- **Retrieval mode:** not typical passage retrieval. The judge queries the statistical
  distribution of historical outcomes for the contested issues already identified (the issue
  statistics layer) — essentially an aggregate query rather than semantic retrieval.
- **Data access scope:** only the public case file formally submitted to the court, ignoring
  both sides' unfiled private notes.

---

## 4. The underlying RAG engineering this isolation rests on

The three private facets still sit on one underlying judgment database, which must meet the
following requirements for this module to mean anything:

- **Layered database architecture:** a structured exact-match layer (statute numbers, judgment
  case numbers), a semantic retrieval layer (fact descriptions and the court's reasoning
  passages, via vector retrieval plus SAC summary augmentation), and an issue statistics layer
  for the judge agent's aggregate queries.
- **SAC (summary-augmented chunking) applied to every judgment:** generate a short summary per
  document and prepend it to every chunk before vectorization, mitigating the document-level
  retrieval mismatch (DRM) caused by the highly formulaic phrasing of Taiwanese judgments
  (stock formulae such as "按…定有明文" and "查").
- **Traceable metadata:** every chunk must carry the judgment case number, court level,
  judgment date, and the position of the corresponding passage in the source document. This is
  especially critical here — precedents cited by either side must be verifiable by the opposing
  agent and by the judge, or "stance-driven RAG" degenerates into two sides talking past each
  other with no way to cross-check.

---

## 5. Relationship to the heterogeneous model matrix (supplementary, not core)

Stance-isolated retrieval creates asymmetry at the **data source** layer. The heterogeneous
model matrix proposed in the homogenization report (prosecutor on Claude, defence counsel on
GPT-4o, judge on DeepSeek-R1) creates asymmetry at the **model bias** layer. The two are
complementary but independent, belong to different technical decisions, and should not be
bundled into this module's implementation — even on a single model, the stance isolation design
here still holds and is still necessary.

---

## 6. Mapping to the original documents

| Original document | Original section | Status |
|---|---|---|
| [Multi-agent homogenization](multi-agent-homogenization.md) | §3.1 information asymmetry and private facets | Merged into §2 here; the original now points here |
| [Multi-agent homogenization](multi-agent-homogenization.md) | §3.4 stance-driven RAG retrieval | Merged into §3 here; the original now points here |
| [RAG system design](rag-system-design.md) | §4.3 per-agent differentiated retrieval | Merged into §3 and §4 here; the original now points here |

All other sections of both reports remain independent and are unaffected by this merge: the
homogenization report's tool permission isolation, deterministic state machine, heterogeneous
model matrix and adversarial protocol; and the RAG report's literature review, full layered
database design, chunking strategy and reranking mechanism.
