# Documentation

Every document exists in Traditional Chinese under `zh/`. English versions live under `en/`,
and the table below marks which are available — the rest are in progress. Where both exist,
the Chinese original remains authoritative: the system reasons in Chinese over Chinese legal
materials, so that is what the project actually works from.

## Architecture and technical design

| Document | English | What it covers |
|---|---|---|
| Product development report | [zh](zh/product-development-report.md) — English pending | The three-engine architecture, commercial positioning, the four critical risks, and the strategic roadmap |
| RAG system design | [**en**](en/rag-system-design.md) · [zh](zh/rag-system-design.md) | Engine 1's academic basis and implementation spec: document-level retrieval mismatch (DRM), summary-augmented chunking (SAC), per-agent retrieval strategy, traceability |
| Stance-isolated RAG spec | [**en**](en/stance-isolated-rag-spec.md) · [zh](zh/stance-isolated-rag-spec.md) | The merged specification for differentiated plaintiff / defendant / judge retrieval, unified from two earlier overlapping documents so they cannot drift apart |
| Multi-agent homogenization | [**en**](en/multi-agent-homogenization.md) · [zh](zh/multi-agent-homogenization.md) | Why multi-agent systems collapse into one voice, and the countermeasures: tool permission isolation, a heterogeneous model matrix, adversarial protocol |
| Corpus contamination and validation | [**en**](en/corpus-contamination-and-validation.md) · [zh](zh/corpus-contamination-and-validation.md) | Distillation contamination risks (anchoring bias, data contamination) and a five-layer automated validation scheme exploiting the ground truth judgments carry |
| Full courtroom expansion plan | [zh](zh/full-courtroom-expansion-plan.md) — English pending | Civil and criminal dual mode, the four-stage courtroom SOP, and live-transcript UI design |

## Testing and evaluation

| Document | English | What it covers |
|---|---|---|
| E2E test report, 2026-08-08 | [zh](zh/e2e-test-report-2026-08-08.md) — English pending | Phase 1.5 end-to-end run |
| E2E test report, 2026-08-09 | [zh](zh/e2e-test-report-2026-08-09.md) — English pending | First run after the full Stage 1–3 scaffold |
| Prompt comparison, batch 1 | [zh](zh/prompt-comparison-claim-basis-batch1.md) — English pending | A/B comparison of the claim-basis examination method |
| Prompt comparison, batch 2 | [zh](zh/prompt-comparison-claim-basis-batch2.md) — English pending | Cases 002–005 |

The rendered comparison dossier is at
[`zh/prompt-comparison-dossier.html`](zh/prompt-comparison-dossier.html).

## Product and planning

| Document | English | What it covers |
|---|---|---|
| Product roadmap | [zh](zh/product-roadmap.md) — English pending | Short, medium and long term: from a pleading generator to an AI case workflow |
| New direction assessment | [zh](zh/new-direction-assessment.md) — English pending | Evaluation of the "AI lawyer case workspace" alternative direction |
| Lawyer interview questions | [zh](zh/lawyer-interview-questions.md) — English pending | The Phase 2 design-partner validation instrument |
| Document integration plan | [zh](zh/document-integration-plan.md) — English pending | How the appendices were cross-integrated, which positions needed correcting, and the resulting updated roadmap |

## A note on the Chinese originals

Some documents reference internal planning files and knowledge-base pages that are not
published with this repository. Those references are marked as such rather than silently
removed, so the reasoning chain stays legible even where a source is not public.
