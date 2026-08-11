# ai-legal-debate-system

**A research prototype that makes two opposing AI counsel argue a civil dispute before an AI judge — then refuses to let any of them cite a statute or precedent that does not verifiably exist.**

[![tests](https://github.com/D1349375/ai-legal-debate-system/actions/workflows/tests.yml/badge.svg)](https://github.com/D1349375/ai-legal-debate-system/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

Legal AI tools fail in two characteristic ways: they invent statutes and case numbers that
sound right, and they produce prose no practising lawyer would file. This prototype attacks
both — a mechanical citation verifier that treats every reference as false until matched
against an authoritative source, and an adversarial structure that surfaces a case's weak
points before anything gets drafted.

Jurisdiction is Taiwan (civil). The corpus is Taiwanese statutes and Supreme Court judgments,
and the reasoning conventions are those of Taiwanese civil procedure.

---

## Scope and legal position, stated up front

**This project will never be a paid consumer-facing pleading service.** Article 127 of
Taiwan's Attorney Act makes drafting litigation documents for the general public for a fee a
criminal offence carrying up to three years' imprisonment. The only positions considered
viable are B2B: a drafting copilot used *inside* a law firm by qualified lawyers, or
technical infrastructure operated by one.

**This is a research prototype, not a product, and not legal advice.** It is at Phase 1 —
core engine validation on a single model. It has not been validated by a practising lawyer,
and its output is not fit to file.

## What it does

Three engines run in sequence:

**1. Knowledge and zero-tolerance verification.** Statute and precedent citations are checked
against authoritative sources — statutes against the Ministry of Justice database
(`law.moj.gov.tw`), judgments against the local seed corpus first as a fast path, falling back
to a live query of the Judicial Yuan's judgment search system (FJUD). **The local corpus is an
acceleration layer, never an authority**: statute text is always re-checked against the
official source rather than trusted from cache.

**2. Multi-agent adversarial simulation.** A plaintiff's counsel agent looks for the strongest
claim and its legal basis; a defendant's counsel agent looks for exclusion clauses, procedural
defects and evidentiary gaps. Round 1 is blind, round 2 is structured rebuttal. The output is
the list of contested issues and the case's most vulnerable points — not a verdict.

**3. Pleading drafting.** A distilled `taiwan-legal-pleading` skill applies the court's
conventional structure: a precise statement of claim (interest, penalty, jurisdiction fully
annotated) and a syllogistic statement of facts and reasoning (legal basis → subsumption of
facts → conclusion).

## Quick start

```bash
git clone https://github.com/D1349375/ai-legal-debate-system.git
cd ai-legal-debate-system
pip install -r requirements.txt
python -m pytest tests/ -v
```

43 tests covering aggregation, persistence, stance-isolated retrieval and the citation
verifier.

The CLI walks a case through the pipeline:

| Command | What it does |
|---|---|
| `case` | Persist a case input |
| `record` | Persist one side's argument, or the judge's questioning, from a JSON file |
| `finalize` | Mechanically collate weak points and divergence statistics, printing the verdict anchors |
| `verify` | Run citation verification against the authoritative sources |
| `verdict` | Persist the judge's written decision |
| `pleading` | Persist the pleading draft |

`ui/legal_workspace_ui.html` is a standalone UI prototype — open it directly in a browser; it
is not wired to the backend.

## The problems this design is built around

**Document-level retrieval mismatch (DRM).** Taiwanese judgments are highly formulaic, so
naive embedding retrieval frequently returns the wrong source judgment — measured error rates
above 95% in early testing. This is the make-or-break issue for whether a lawyer can trust the
tool, and it is addressed with summary-augmented chunking. See
[the RAG system design](docs/en/rag-system-design.md).

**Multi-agent homogenization.** Two agents on one base model with one prompt template
converge, and the "debate" becomes theatre. The countermeasures — tool permission isolation,
a heterogeneous model matrix, adversarial protocol design — are analysed in
[the homogenization report](docs/en/multi-agent-homogenization.md), with the stance-isolated
retrieval specification split out into
[its own document](docs/en/stance-isolated-rag-spec.md).

**Distillation corpus contamination.** Building a legal corpus from judgments carries
anchoring bias and contamination risks. The mitigation exploits the fact that judgments carry
their own ground truth, in a five-layer automated validation scheme — see
[corpus contamination and validation](docs/en/corpus-contamination-and-validation.md).

## Roadmap

```
Phase 0  Corpus and scope        BLOCKED -- needs a lawyer design partner for
                                 20 real de-identified pleadings. This is an
                                 access problem, not an engineering one.
Phase 1  Core engine validation  Current. Single model, three roles (plaintiff's
                                 counsel / defendant's counsel / judge), stance-
                                 driven RAG, four-stage courtroom SOP.
Phase 2  Design partner testing  1-2 friendly lawyers. Go/no-go signal for
                                 Phase 3: does argument convergence appear?
Phase 3  Anti-homogenization     Conditional on the Phase 2 signal. Information
                                 asymmetry, heterogeneous model matrix.
Phase 4  Full courtroom          Out of current scope. Criminal mode, live UI.
```

The governing criterion is **whether a practising Taiwanese lawyer would actually use it** —
not whether it impresses investors.

## Documentation

[**docs/**](docs/README.md) is the index. Everything exists in English (`docs/en/`) and
Traditional Chinese (`docs/zh/`), with the Chinese originals authoritative where they differ.

## Corpus and licensing

`corpus/` contains Taiwanese government legal materials, which are **not covered by this
repository's MIT license**:

- `corpus/statutes/` — full text of five civil-side statutes (Civil Code, Company Act, Labor
  Standards Act, Consumer Protection Act, Criminal Code), parsed programmatically from the
  Ministry of Justice database rather than AI-summarized, each with a `_source.json` recording
  URL, fetch time and amendment date
- `corpus/judgments/` — 1,088 Supreme Court civil judgments and rulings, imported from the
  Judicial Yuan's official monthly open-data packages
- `corpus/pleadings/` — empty; this is the Phase 0 blocker

These are Taiwanese government works redistributed here for verification purposes. The
official sources remain authoritative, and the cache is deliberately treated as an
acceleration layer only.

## License

MIT for the code and original documentation in this repository — see [LICENSE](LICENSE). The
corpus is excluded, as described above.

## Disclaimer

Research prototype. Not legal advice, not a substitute for a qualified lawyer, and not
validated for use in any actual proceeding.
