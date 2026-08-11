# Documentation

Every document exists in both languages. The **English version under `en/` is the one to
read**; `zh/` holds the Traditional Chinese originals, which remain authoritative where the
two differ — the system reasons in Chinese over Chinese legal materials, so the Chinese text
is what the project actually works from.

## Architecture and technical design

| Document | What it covers |
|---|---|
| [Product development report](en/product-development-report.md) | The three-engine architecture, commercial positioning, the four critical risks, and the strategic roadmap |
| [RAG system design](en/rag-system-design.md) | Engine 1's academic basis and implementation spec: document-level retrieval mismatch (DRM), summary-augmented chunking (SAC), per-agent retrieval strategy, traceability |
| [Stance-isolated RAG spec](en/stance-isolated-rag-spec.md) | The merged specification for differentiated plaintiff / defendant / judge retrieval, unified from two earlier overlapping documents so they cannot drift apart |
| [Multi-agent homogenization](en/multi-agent-homogenization.md) | Why multi-agent systems collapse into one voice, and the countermeasures: tool permission isolation, a heterogeneous model matrix, adversarial protocol |
| [Corpus contamination and validation](en/corpus-contamination-and-validation.md) | Distillation contamination risks (anchoring bias, data contamination) and a five-layer automated validation scheme exploiting the ground truth judgments carry |
| [Full courtroom expansion plan](en/full-courtroom-expansion-plan.md) | Civil and criminal dual mode, the four-stage courtroom SOP, and live-transcript UI design |

## Testing and evaluation

| Document | What it covers |
|---|---|
| [E2E test report, 2026-08-08](en/e2e-test-report-2026-08-08.md) | Phase 1.5 end-to-end run |
| [E2E test report, 2026-08-09](en/e2e-test-report-2026-08-09.md) | First run after the full Stage 1–3 scaffold |
| [Prompt comparison, batch 1](en/prompt-comparison-claim-basis-batch1.md) | A/B comparison of the claim-basis examination method |
| [Prompt comparison, batch 2](en/prompt-comparison-claim-basis-batch2.md) | Cases 002–005 |

The rendered comparison dossier is at
[`zh/prompt-comparison-dossier.html`](zh/prompt-comparison-dossier.html).

## Product and planning

| Document | What it covers |
|---|---|
| [Product roadmap](en/product-roadmap.md) | Short, medium and long term: from a pleading generator to an AI case workflow |
| [New direction assessment](en/new-direction-assessment.md) | Evaluation of the "AI lawyer case workspace" alternative direction |
| [Lawyer interview questions](en/lawyer-interview-questions.md) | The Phase 2 design-partner validation instrument |
| [Document integration plan](en/document-integration-plan.md) | How the appendices were cross-integrated, which positions needed correcting, and the resulting updated roadmap |

## A note on the Chinese originals

Some documents reference internal planning files and knowledge-base pages that are not
published with this repository. Those references have been marked as such rather than
silently removed, so the reasoning chain stays legible even where a source is not public.
