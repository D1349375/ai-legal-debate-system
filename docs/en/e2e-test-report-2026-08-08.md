# Phase 1.5 End-to-End Test — 2026-08-08

> English version of [`docs/zh/e2e-test-report-2026-08-08.md`](../zh/e2e-test-report-2026-08-08.md).

> **Test date:** 2026-08-08 · **Case ID:** `test-2026-08-08-001`. A fictional test case
> constructed to exercise the pipeline; not a real case and not legal advice.

---

## 1. The test case

**Cause of action:** breach of contract (non-payment of the purchase price).

**Facts.** On 2026-03-01 the parties signed a contract for the sale of industrial machinery for
NT$2,000,000, payable within 30 days of receipt. The plaintiff delivered on 2026-03-15 and the
defendant's employee signed the delivery note. Six months later no payment has been made. The
plaintiff sent several email demands in June 2026; the defendant replied that "some parts were
missing on delivery, we are taking stock and have not yet confirmed the loss", but has never
produced a defect schedule, an inspection report or any record of examination, and has never
given written notice asserting a defect in the goods.

**Relief sought:** payment of NT$2,000,000 plus statutory interest at 5% per annum from the day
after service of the complaint until satisfaction.

---

## 2. Pipeline record

### Step 1 — case input and stance retrieval terms

Persisted successfully.

### Step 2 — Stage 1, blind independent judgment

**Plaintiff.** Asserts the price claim under Civil Code art. 367, delay interest under
arts. 229/233/203, and that the defendant, having failed to examine and notify under art. 356,
is deemed to have accepted the goods and lost the basis for a defect defence. Cites Supreme
Court 115 台上 192 (a claim for payment of goods).

**Defendant.** Does not contest formation or delivery, but asserts parts were missing on
delivery and that under art. 264 (simultaneous performance) and the warranty provisions from
art. 354 onward it may withhold payment to the value of the shortfall. Argues the shortfall was
a defect not immediately discoverable (art. 356(3)) and that notice was given by email after
discovery, within the exclusion period. **Discloses its own weakness honestly**: concedes that
"to date we have only said by email that we are taking stock, and have produced no defect
schedule, inspection report or examination record" is a significant evidentiary gap. Cites
Supreme Court 115 台上 474 (general principles of the simultaneous performance defence).

### Step 3 — judicial issue confirmation and questioning

**Five matters found not substantively in dispute:** contract formation and amount; delivery and
signed receipt; non-payment past the due date; that the defendant sent an email but produced no
specific evidence; and that the defendant does not contest validity or the existence of a basis
for the claim.

**Four questions**, each anchored with `based_on`.

### Step 4 — Stage 2, questioning exchange

**Plaintiff** adds a three-stage "examine → discover → notify" argument, contending that the
email's own wording ("taking stock", "not yet confirmed") is an admission that neither
examination nor discovery was complete, so no art. 356 notice could have taken effect; and
questions the email's timing under the good-faith principle (art. 148).

**Defendant** responds to the judge's first two questions by **honestly conceding that the case
record contains no such detail and declining to fabricate figures**, explaining how verification
cuts both ways for its own argument. On question 4 it advances a new argument: the test for the
simultaneous performance defence is whether the plaintiff has fully performed, not who the
contract text says pays first, citing Supreme Court 115 台上 324 by analogy for narrowing the
scope of the defence.

### Step 5 — Stage 3, closing

**Plaintiff (the decisive verification step).** Against the defendant's citation of 324, the
plaintiff **proactively grepped and read the full judgment**
(`corpus/judgments/TPSV,115,台上,324,20260528,1.txt`) and found the case is in fact a damages
claim whose issue was whether email evidence not subjected to oral argument constitutes a
surprise ruling under art. 278(2) of the Code of Civil Procedure — entirely unrelated to the
art. 356 notice-specificity issue here. **The opposing citation's persuasive force was
successfully undercut.**

**Defendant.** Narrows its position, no longer withholding the full amount, and asserts a
deduction limited to the identifiable shortfall, invoking art. 98 (ascertaining true intent)
against the plaintiff's three-stage argument.

### Step 6 — mechanical aggregation (`aggregate.py`)

```json
{
  "weak_points": [
    {"side": "defendant", "falsifier": "if no physical evidence can be produced, concede payment in full; if it can, maintain the partial deduction"},
    {"side": "plaintiff", "falsifier": "if the defendant can identify the scope of the shortfall and produce physical evidence, concede that portion"}
  ],
  "position_drift": {"plaintiff": 0.8889, "defendant": 0.6}
}
```

Both sides produced explicit falsifiers, with substantial drift in the citation set —
especially on the plaintiff's side, reflecting the shift in argumentative centre of gravity from
the basis of the claim to the effect of notice.

### Step 7 — judicial assessment of issue strength

The judge correctly kept to "assess issue strength, do not predict the decision": no predictive
phrasing anywhere. It analysed the three issues (basis of claim, delay interest, effect of
notice), identified notice as the only substantively contested one, and gave a pleading priority
recommendation consistent with the mechanical anchors (concentrate on the core issue, treat the
undisputed facts briefly).

### Step 8 — citation verification (`python main.py verify`)

Of 16 citations, **15 published** (12 Civil Code articles plus 3 Supreme Court precedents) and
**1 unparseable** — "Code of Civil Procedure art. 277", because the verification engine covered
only the five civil-side statutes and not the Code of Civil Procedure.

**The machine gate was observed intercepting.** The judge's first `citations_used` included
art. 277, and `record_verdict()` correctly refused to persist it (*"refusing to persist: the
following citations are not verified as published"*). After removing that citation, persistence
succeeded.

### Step 9 — skeleton pleading draft

Built on the field structure of the Judicial Yuan's official civil complaint template, filled
with the plaintiff's final Stage 3 position and reasoning, **without rhetorical polish** (per
the 2026-08-08 decision to defer the `taiwan-legal-pleading` skill to Phase 2). Persisted
successfully.

### Step 10 — final database state

| Table | Rows |
|---|---|
| cases | 1 |
| debate_arguments | 6 (both sides × three stages) |
| court_questions | 4 |
| verdicts | 1 |
| citation_verifications | 16 |
| pleading_drafts | 1 |

All 29 pytest tests passed.

---

## 3. Quality assessment: did the protocol design achieve its intent?

| Design goal | Verified? |
|---|---|
| Stage 1 blind isolation between the two sides | ✅ No trace of cross-contamination in either output |
| Judicial questions anchored by `based_on`, never invented | ✅ All four questions trace to specific Stage 1 sentences |
| The five criteria (no repetition, new angle, direct response, new evidence, varied expression) | ✅ Each round shows identifiable argumentative gain, not paraphrase |
| Honest admission of factual gaps, no fabricated detail | ✅ The defendant answered the judge's detail questions with "not recorded in the case file, requires verification" |
| Can the adversarial protocol catch what a single LLM summarizer cannot? | ✅ **The plaintiff proactively checked the full text of the opposing party's cited precedent and caught a real judgment cited for the wrong proposition** — the most concrete value signal from this run |
| The judge stays within quality control and never predicts an outcome | ✅ No predictive phrasing throughout, and no contradiction of the mechanical anchors |
| The verification gate is mechanically enforced and cannot be bypassed | ✅ One unverified citation was intercepted and refused |

---

## 4. Items to fix or optimize

### High priority

**1. Citation format discipline in the Stage 2/3 templates is under-specified, and produced one
violation.** Needs tightening in the templates.

**2. `engine/verify.py` did not cover the Code of Civil Procedure**, which civil litigation
argument frequently needs to cite — **fixed.**

**3. Sub-article "之N" notation was silently misparsed by the verification engine as an entirely
different article** (found while running two additional cases on 2026-08-08; more serious than
the two items above). Same class of failure as the case-type whitelist gap found the following
day: an enumeration missing real variants.

### Medium priority (performance and workflow, non-blocking)

**4. `verify`'s live verification is sequential** and slow at volume.

**5. Manually collating the opposing party's structured summary in the orchestrator is
laborious.**

### Not requiring a fix, but worth recording

**6. The opposing-citation verification mechanism** has been promoted from a suggestion to a
hard rule.

---

## 5. Two additional cases (2026-08-08): tort and an employment dispute

Two further cases were run for additional validation.

**A practical lesson about execution.** Running `python main.py verify` as a single batch over
28 citations stalled for more than ten minutes with no progress against `law.moj.gov.tw` —
probably temporary rate limiting after a heavy day of requests rather than a timeout failure.
Aborting and re-running in batches of six or seven completed without trouble. In real use, when
a single case carries many citations, the caller of the verification engine — the orchestrator,
or a future automated backend — should batch requests rather than submitting them all at once.
