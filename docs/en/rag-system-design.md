# RAG System Design: Academic Basis, Industry Practice, and Implementation Spec

> English version of [`docs/zh/rag-system-design.md`](../zh/rag-system-design.md).

> **Date:** 2026-08-06
> **Position:** technical appendix — the retrieval-augmented generation architecture for the
> in-house legal database, consolidating key findings from the literature and industry
> practice into concrete specifications for the plaintiff / defendant / judge agent
> architecture.

---

## 1. Purpose and scope

This report answers one question: **how do you design a RAG system specifically for Taiwanese
legal documents (judgments, statutes, pleadings) whose retrieval accuracy is good enough to
support adversarial simulation and pleading drafting?** Three parts: literature review,
industry practice, and design specification for this project's three-agent architecture.

---

## 2. Literature review

### 2.1 Primary reference

Reuter, M., Lingenberg, T., Liepiņa, R., Lagioia, F., Lippi, M., Sartor, G., Passerini, A., &
Sayin, B. (2025). *Towards Reliable Retrieval in RAG Systems for Large Legal Datasets*.
arXiv:2510.06999.

A collaboration between TU Darmstadt, the University of Florence, the Bologna law faculty and
the University of Trento, this paper studies retrieval reliability for legal RAG empirically,
running on LegalBench-RAG — a public benchmark for legal RAG retrieval covering general
contracts, M&A agreements, NDAs and privacy policies.

### 2.2 Finding 1: Document-Level Retrieval Mismatch (DRM)

The paper defines and quantifies a failure mode not previously formalized: **the retrieved
passage comes from entirely the wrong source document**, even though it is superficially
similar to the query. Two properties of legal documents make this especially severe:

1. **Lexical redundancy.** Legal language is full of boilerplate clauses, formal definitions
   and terms of art. Documents of the same type may differ only in a handful of key variables
   (party names, dates) with near-identical structure otherwise.
2. **Hierarchical structure.** Legal documents are organized in nested sections with dense
   cross-references, and standard chunking ignores that hierarchy, severing logical
   connections.

On the NDA dataset, a standard RAG pipeline showed a DRM error rate **above 95%** — in the
overwhelming majority of cases the retriever returned content that looked right but came from a
different contract entirely. The authors attribute this to NDAs' highly formulaic language,
which confuses retrievers relying on semantic similarity or keyword matching.

**Implication here:** Taiwanese judgments share a highly uniform structured style (fixed
formulae such as 「按…定有明文」, 「查」, 「本院判斷如下」), which is the same problem the paper
found in NDAs. **DRM should be treated as the primary design threat, not an edge case.**

### 2.3 Finding 2: Summary-Augmented Chunking (SAC)

To mitigate DRM, the paper proposes a lightweight technique: **generate a short document-level
summary (about 150 characters in their setup) and prepend it to every chunk cut from that
document before vectorizing and indexing.** The mechanism is to inject "what this document is
about overall" into each otherwise isolated chunk, steering the retriever toward identifying
the correct source document first.

With SAC, the DRM error rate **falls substantially — roughly halving** — and the improvement
carries through to passage-level precision and recall, showing that fixing document-level
mismatch also improves finer-grained retrieval quality.

The paper compared generic summaries against summaries written to a legal-expert-designed
template and reached a **counter-intuitive conclusion: the generic summaries retrieved
better.** Their analysis is that generic summaries strike a better balance between
inter-document distinctiveness and alignment with broad query semantics, whereas the
expert-designed summaries — more precise from a legal standpoint, better at foregrounding
legally distinguishing variables — pack information so densely and structurally that they
burden the embedding model's semantic compression, and that precision does not necessarily
translate into better retrieval.

**Implication here:** SAC is extremely cheap (one extra LLM summarization call per document)
and drops straight into an existing pipeline, so it should be standard procedure when building
the judgment database. And the summarization stage should avoid over-engineered legal
templates, preferring the generic strategy until measured data shows customization actually
helps.

### 2.4 Finding 3: Chunking must follow document structure

The paper and the prior work it cites (Ferraris et al., 2024, on chunking methods for legal
text) agree that fixed-size chunking ignores hierarchical structure and cuts logically complete
passages in half, producing semantically incomplete fragments. Suggested alternatives:

- **Recursive character splitting** — split along natural boundaries such as paragraphs and
  punctuation. This was the paper's own baseline and performed stably.
- **Parent-document retrieval** — retrieve at fine granularity for precision, but return the
  full section or article containing that passage to the generation model, combining precise
  location with complete context.

### 2.5 Finding 4: Hybrid search helps at one level and hurts at another

The paper tested combining BM25 (mature sparse keyword retrieval) with dense vector retrieval
at the passage level. The result: **adding BM25 did improve document-level identification
(reducing DRM) but simultaneously reduced passage-level precision and recall.** The analysis:
summary text is itself structured and distinctive, which suits keyword matching, whereas the
chunked document body is natural-language narrative with no directly matchable keywords, so
semantic similarity locates relevant passages more effectively than keyword overlap. Factoring
in BM25's additional compute cost, they settled on dense retrieval alone as the primary method.

**Implication here:** hybrid retrieval is not "stack everything for best results" — it has to
be split by level. **Structured fields requiring exact matching** (statute numbers, judgment
case numbers, party names) suit keyword or exact matching; **natural-language narrative**
(fact descriptions, the court's reasoning) is primarily semantic vector retrieval.

### 2.6 Finding 5: Directions for further improvement

The paper's conclusions list promising extensions not validated in its experiments: hierarchical
summarization (summaries at paragraph, section and document granularity), query optimization
(transformation, expansion and routing, to bridge the gap between a user's plain-language
question and formal legal terminology), and adding a **reranking** stage after retrieval so a
stronger model rescores the initial candidates before generation.

---

## 3. Industry practice

### 3.1 Clues from Lawsnote's architecture

Per public information, Lawsnote AI uses a "vector / index hybrid" search engine combined with
knowledge graph techniques over legal data: the system interprets the user's question, retrieves
relevant statutes, judgments and administrative interpretations from the legal database, then
passes those together with the question to an LLM for generation.

Read against the literature, a reasonable inference is that Lawsnote's hybrid search applies to
**structured fields** (statute and judgment numbers, parties) for exact matching, with the
**knowledge graph** handling relationships between legal concepts and provisions — rather than
indiscriminately mixing keyword and vector retrieval over full judgment text. That does not
contradict the paper's finding that BM25 reduced passage-level precision; the two are simply
hybrid retrieval applied at different layers of the system, which is a sensible design.

### 3.2 User feedback as a design input

Earlier research gathered concrete feedback from law-student users of existing legal AI tools:
AI output should annotate which specific line of practical authority each citation corresponds
to, and should prioritize precedents of higher binding authority (Supreme Court positions)
rather than ranking purely by relevance.

Both echo the **provenance and traceability** principle the literature emphasizes: legal
professionals require a transparent, verifiable reasoning trail that traces a generated answer
back to a specific clause in a source document, and that is one of the key criteria for judging
a legal RAG system's reliability.

---

## 4. Product architecture specification

### 4.1 Layered database architecture

| Layer | Contents | Retrieval method | Basis |
|---|---|---|---|
| Structured exact-query layer | Statute numbers, judgment case numbers, parties, dates | Exact match | The literature's finding that hybrid retrieval outperforms on structured fields but not at passage level |
| Semantic retrieval layer | Fact descriptions and the court's reasoning passages | Vector retrieval plus SAC summary augmentation | §2.2–2.3, the DRM problem and the SAC remedy |
| Issue statistics layer | A structured table of "issue type → proportion accepted by courts" | Direct table aggregation, not typical RAG | The automated validation data already planned in the project's verification chapter |

### 4.2 Chunking design

- **Judgments:** structure-aware chunking along their intrinsic fields (cause of action,
  holding, facts and reasoning, contested issues, the court's determination) rather than fixed
  size, so logically complete passages are not cut in half.
- **Statutes:** the article is the base chunk, retaining its containing chapter as parent
  context for parent-document retrieval.
- **SAC on every document:** before chunking, generate a short summary of the whole document
  (starting with the generic strategy that performed best in the literature, around 150
  characters as a starting point, adjusted against measured results) and prepend it to every
  chunk before vectorization.

### 4.3 Per-agent retrieval strategy

> **Full specification merged into**
> [stance-isolated RAG spec](stance-isolated-rag-spec.md) §3–4 (including the
> information-asymmetric private facet design and its integration with the homogenization
> report). Conceptual summary only here.

The three agents have different query intents and should not share one retrieval path:

- **Plaintiff's counsel agent:** targets statutes and winning precedents related to the basis
  of the claim, with query transformation applied first to translate the user's plain-language
  account into a legal-elements query — a concrete application of the query optimization
  direction in §2.6.
- **Defendant's counsel agent:** same case facts, queried in the opposite direction for
  defences, exclusion clauses and procedural defects. Plaintiff and defendant must run
  retrieval independently and never share one retrieval result, which also reduces cross-agent
  memory contamination.
- **Judge agent:** not passage retrieval, but a query against the historical outcome
  distribution for the identified issues (the issue statistics layer in §4.1) — an aggregate
  query rather than semantic retrieval.

### 4.4 Traceability and metadata

Following §2.6 and §3.2, every chunk must carry full metadata alongside its SAC summary:
judgment case number, court level, judgment date, and the position of the corresponding passage
in the source document. Every sentence generated must be traceable to a specific source. This
directly answers the "citation attribution is opaque" complaint users raised about existing
tools.

### 4.5 Reranking

Per the paper's suggested direction in §2.6, add a reranking model to rescore the initial vector
retrieval candidates before passing them to generation. Implementation cost is relatively low
(off-the-shelf open-source or commercial rerankers exist) and it can be integrated into the
existing pipeline without waiting for other mechanisms to be validated.

---

## 5. Implementation summary

1. **Build the SAC pipeline first** — standard procedure for both the judgment and statute
   databases: generate a generic summary before chunking and prepend it to each chunk.
2. **Handle structured fields and semantic content separately** — exact matching for statute
   and judgment numbers, semantic vector retrieval for reasoning passages. No indiscriminate
   hybrid retrieval.
3. **Design query logic per agent role** — the plaintiff, defendant and judge agents need
   separately designed retrieval targets and transformations, not one shared pipeline.
4. **Adopt traceable metadata throughout** — a launch prerequisite rather than a later
   optimization, because it addresses a known market pain point directly.
5. **Add a reranking layer** — high value for the effort and adoptable early, ahead of more
   complex architectural work such as knowledge graph integration.

---

*Report generated 2026-08-06.*
