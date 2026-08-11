# Multi-Agent Homogenization and the Courtroom AI Architecture

> English version of [`docs/zh/multi-agent-homogenization.md`](../zh/multi-agent-homogenization.md).

> **Date:** 2026-08-06
> **Topic:** breaking the "one brain wearing different masks" pathology in multi-agent systems
> — homogeneity and sycophancy — by combining general industry design patterns with an
> architecture specific to a simulated courtroom.
> **Core conclusion:** tool permission isolation, information-asymmetric facets, a
> heterogeneous model matrix and stance-driven RAG together address multi-agent convergence
> and the absence of genuine information gain.

---

## 1. The problem: convergence behind the costume

The most common technical bottleneck in multi-agent development:

> **Every agent ultimately calls the same base LLM API. Different system prompts ("you are
> now the judge / the prosecutor / defence counsel") do not change the fact that one brain is
> talking to itself, which produces sycophantic convergence and repeated information rather
> than genuine adversarial exchange or information gain.**

This report addresses it in two parts: general industry solutions, and a courtroom-specific
architecture.

---

## 2. Five industry design patterns against homogenization

Drawn from current leading multi-agent frameworks (Microsoft AutoGen, CrewAI, LangGraph,
Together AI MoA):

**1. Tool-access isolation.** Restrict which tools each agent holds — the agent that writes
code cannot run tests; the agent that runs tests cannot modify source. *Effect:* different tool
outputs force genuinely different reasoning.

**2. Deterministic circuit breakers.** Never let agents converse without constraint. Insert
plain Python between them to enforce hard JSON schema checks, data reconciliation or logical
interception. *Effect:* deterministic code severs the echo chamber and the sycophancy between
LLMs.

**3. Vector DB partitioning.** Bind each agent to a completely independent vector store — the
market agent reads interviews, the finance agent reads filings, the engineering agent reads
GitHub issues. *Effect:* isolate knowledge at the source so agents genuinely hold different
factual backgrounds.

**4. Heterogeneous model matrix (Mixture-of-Agents).** Mix base models from different vendors —
generation on one, review on another, cold reasoning on a third. *Effect:* different
pretraining corpora and RLHF preferences break single-model bias.

**5. Sampling parameter diversity.** Temperature 0.1 for conservative reviewing agents,
temperature 0.8 for divergent challenging agents.

---

## 3. The four-layer courtroom architecture

```
                   [ raw case file database ]
                             ↓
     ┌───────────────────────┼───────────────────────┐
     ↓ (prosecution facet)    ↓ (public court file)   ↓ (defence facet)
 prosecution agent        judge agent            defence agent
 (Claude 3.5)            (DeepSeek-R1)           (GPT-4o)
 • adverse evidence       • public file only     • favourable evidence
 • winning precedents     • neutral statutes     • acquittal / exclusion
                            and burden of proof     precedents
     │                       │                       │
     └─────────────► [ mandatory R2 adversarial ] ◄──┘
                             ↓
                 [ deterministic mechanical aggregation ]
```

### 3.1 Information asymmetry and private facets ★ the core mechanism

> **Full specification merged into**
> [stance-isolated RAG spec](stance-isolated-rag-spec.md) §2 and §3, which is authoritative and
> includes each agent's complete retrieval spec and the underlying RAG requirements. Only the
> conceptual summary is retained here.

- **Prosecution / plaintiff agent** — statement of claim, prosecution-specific precedents
  ("offence established / strict liability"), evidence adverse to the defendant. **Cannot see
  the defence strategy.**
- **Defence / defendant agent** — the defendant's private statement, defence-specific
  precedents ("presumption of innocence / procedural defect / exclusion"), favourable evidence.
  **Cannot see the prosecution strategy.**
- **Judge agent** — only the public case file formally submitted to the court, blind to either
  side's unfiled private notes.

### 3.2 Heterogeneous model assignment

- **Prosecutor / plaintiff agent:** Claude 3.5 Sonnet — tight logic, sharp prose, emphasis on
  the statutory elements of a claim.
- **Defence counsel / defendant agent:** GPT-4o — persuasive, flexible in interpretation, good
  at finding procedural gaps.
- **Presiding judge agent:** DeepSeek-R1 or a Claude reasoning mode — cold, neutral, forced
  into long-chain reasoning.

### 3.3 Adversarial protocol design

- **R1 (fully isolated blind judgment):** both sides produce their statement of claim or
  defence without visibility of the other.
- **R2 (mandatory engagement plus falsifier clause):**
  - Each side must respond head-on to the opponent's strongest R1 argument. Deflecting to
    weaker points is prohibited.
  - Each side must state its own **falsifier** — the condition under which it would concede
    (e.g. defence must specify "if the plaintiff produces the following objective
    documentation, we abandon this defence").

### 3.4 Stance-driven retrieval

> **Full specification merged into**
> [stance-isolated RAG spec](stance-isolated-rag-spec.md) §3; conceptual summary only here.

- **Prosecution retrieval** automatically appends "offence established" / "appeal dismissed".
- **Defence retrieval** automatically appends "acquitted" / "insufficient evidentiary capacity"
  / "original judgment vacated".
- **Effect:** the two sides argue holding genuinely different real Supreme Court precedents.

---

## 4. Industry practice versus courtroom implementation

| Dimension | General multi-agent practice | Courtroom implementation |
|---|---|---|
| **Tool isolation** | Code writer has no test access; tester cannot modify source | Prosecution can only call the prosecution precedent API; only the judge can issue a decision |
| **Deterministic interception** | Plain Python middleware validates JSON schema | The adjudicating layer uses pure code for mechanical aggregation, which the LLM may not override |
| **Memory / data isolation** | Each agent mounts a different vector store | Prosecution RAG retrieves winning cases; defence RAG retrieves acquittals and exclusions |
| **Heterogeneous models** | Mixing OpenAI + Anthropic + DeepSeek | Prosecutor on Claude 3.5, counsel on GPT-4o, judge on DeepSeek-R1 |
| **Protocol constraint** | LangGraph constrains node transitions | R1 fully isolated blind judgment, plus R2 mandatory engagement with the opponent's strongest argument and a falsifier |

---

## 5. Implementation sequencing

1. **Stage one (MVP):** implement **stance-driven retrieval** and the **R1 blind → R2 mandatory
   rebuttal protocol** first. Both materially improve adversarial quality even on a single
   model.
2. **Stage two (full architecture):** add **information-asymmetric facets** and the
   **Claude + GPT-4o + DeepSeek** heterogeneous scheduling to complete the full-role simulated
   courtroom.

---

*Report generated 2026-08-06.*
