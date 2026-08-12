# Documentation

Every document exists in both languages: **English under `en/`**, Traditional Chinese under
`zh/`. The Chinese originals remain authoritative where the two differ — the system reasons in
Chinese over Chinese legal materials, so that is what the project actually works from.

## Architecture and technical design

| Document | What it covers |
|---|---|
| [**Architecture**](en/architecture.md) · [zh](zh/architecture.md) | The three engines, the distillation/retrieval separation, the end-to-end flow, engineering status, and the known technical risks. Start here |
| [RAG system design](en/rag-system-design.md) · [zh](zh/rag-system-design.md) | Engine 1's academic basis and implementation spec: document-level retrieval mismatch (DRM), summary-augmented chunking (SAC), per-agent retrieval strategy, traceability |
| [Stance-isolated RAG spec](en/stance-isolated-rag-spec.md) · [zh](zh/stance-isolated-rag-spec.md) | The merged specification for differentiated plaintiff / defendant / judge retrieval, unified from two earlier overlapping documents so they cannot drift apart |
| [Multi-agent homogenization](en/multi-agent-homogenization.md) · [zh](zh/multi-agent-homogenization.md) | Why multi-agent systems collapse into one voice, and the countermeasures: tool permission isolation, a heterogeneous model matrix, adversarial protocol |
| [Corpus contamination and validation](en/corpus-contamination-and-validation.md) · [zh](zh/corpus-contamination-and-validation.md) | Distillation contamination risks (anchoring bias, data contamination) and a five-layer automated validation scheme exploiting the ground truth judgments carry |
| [Full courtroom expansion plan](en/full-courtroom-expansion-plan.md) · [zh](zh/full-courtroom-expansion-plan.md) | Phase 4 material: civil and criminal dual mode, the four-stage courtroom SOP, and the live-transcript UI concept |

## Testing and evaluation

These are the honest record of what the pipeline did on real fact patterns — including the bugs
the tests exposed and the limits they revealed.

| Document | What it covers |
|---|---|
| [E2E test, 2026-08-08](en/e2e-test-report-2026-08-08.md) · [zh](zh/e2e-test-report-2026-08-08.md) | Full Phase 1.5 run on a contract dispute. The verification gate intercepted an unverified citation; one side caught the other citing a real judgment for the wrong proposition |
| [E2E test, 2026-08-09](en/e2e-test-report-2026-08-09.md) · [zh](zh/e2e-test-report-2026-08-09.md) | First run after the Stage 1–3 upgrade. Three independent mechanisms agreed a cited precedent did not exist, and the test exposed a serious pre-existing regex bug affecting over half the corpus |
| [Prompt comparison, batch 1](en/prompt-comparison-claim-basis-batch1.md) · [zh](zh/prompt-comparison-claim-basis-batch1.md) | A/B comparison of the claim-basis examination scaffold against the current Stage 1 prompt, scored against the court's actual reasoning |
| [Prompt comparison, batch 2](en/prompt-comparison-claim-basis-batch2.md) · [zh](zh/prompt-comparison-claim-basis-batch2.md) | Four more causes of action — including an honest disclosure that one case's prompt was contaminated and its result should be discounted |

The rendered comparison dossier is at
[`zh/prompt-comparison-dossier.html`](zh/prompt-comparison-dossier.html).

## A note on the Chinese originals

Some documents reference internal planning files and knowledge-base pages that are not published
with this repository. Those references are marked as such rather than silently removed, so the
reasoning chain stays legible even where a source is not public.

Commercial planning material — monetization analysis, the market roadmap, and the design-partner
interview script — is deliberately not part of this repository.
