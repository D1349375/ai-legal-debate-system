# Phase 1.5 End-to-End Test — 2026-08-09

> English version of [`docs/zh/e2e-test-report-2026-08-09.md`](../zh/e2e-test-report-2026-08-09.md).

> **Test date:** 2026-08-09 · **Case ID:** `test-2026-08-09-e2e-001`
>
> **A fictional test case.** The facts are drawn from the parties' assertions in Supreme Court
> judgment TPSV 114 台上 1547, excluding the court's findings, and used to validate the
> upgraded Stage 1–9 pipeline. It is not a real case and must not be relied on as legal advice.
>
> **Purpose:** the Stage 1, 2 and 3 templates were all upgraded to the extended claim-basis
> examination form on the same day. Whether the chain still runs end to end, and whether output
> quality suffers now that all three stages are longer, had not been verified.

---

## 1. The test case

**Cause of action:** a consumer loan dispute. (Sourced from TPSV 114 台上 1547; the full
judgment was temporarily moved out of the corpus during the test and restored afterwards, so
the system could not read the answer.)

**Facts.** The plaintiff alleges the defendant borrowed repeatedly — five loans of NT$10m
principal bearing interest at the bank rate, and twelve loans totalling NT$5,401,265 at an
agreed 15% annual rate — and that after partial repayment NT$14,813,529 of principal plus
interest remains outstanding. The defendant contends there was no agreement to 15% interest on
the twelve loans, that six were already repaid, that in 2008 the parties agreed to settle the
entire debt against land consideration (at NT$750,000 per ping, totalling NT$14,867,118), and
that any remaining balance is time-barred.

---

## 2. Full pipeline record (steps 1–10)

- **Step 1.** Case input and stance-specific retrieval terms persisted successfully.
- **Step 2, Stage 1** (blind independent judgment, claim-basis examination form): the plaintiff
  enumerated six candidate bases A–F (principal, interest, alternative statutory interest,
  rebutting datio in solutum, rebutting limitation, appropriation calculation); the defendant
  enumerated four candidates a–d (denying the interest agreement, a repayment defence, the
  primary characterization of the settlement, and limitation in the alternative). Both marked
  the status of each element, producing for the first time specific analysis such as "the
  requirement of actual receipt is not satisfied" and "a quantified alternative comparing the
  appropriated amount against the total outstanding".
- **Step 3, judicial issue confirmation and questioning.** The court correctly identified "an
  offsetting arrangement was agreed in 2008" as a fact not substantively in dispute, and
  **precisely hit the core factual issue on which the real judgment was remanded** — whether
  the NT$750,000 per ping unit price was actually agreed. Six questions were produced, each
  anchored with `based_on`.
- **Step 4, Stage 2** (questioning exchange; new four-step structure of re-examining the
  candidate list → responding item by item → assessing setbacks on the primary path plus an
  internal consistency check → integration): the defendant shifted this round from datio in
  solutum to **settlement** (Civil Code arts. 736/737), and independently found **art. 738**
  (a settlement cannot be reopened absent statutory grounds) to strengthen the primary defence.
  The plaintiff independently found the **appropriation order in arts. 322/323** and quantified
  that even if the offsetting stands, five loans totalling NT$4,920,799 of principal remain
  claimable.
- **The opposing-citation verification rule caught something significant.** Following the rule,
  the defendant grepped the entire corpus for the plaintiff's Stage 1/2 citation to "Supreme
  Court 105 台簡上 33" and **found no file for that case number at all**, preserving the
  objection rather than accepting the citation.
- **Step 5, Stage 3** (closing; new four-step structure of taking stock of both rounds'
  candidates → marking each one's current status → selecting the final candidates plus an
  internal consistency check):
  - **The plaintiff voluntarily withdrew its own Stage 2 citation to "Supreme Court 105 台簡上
    33"**, on the ground that self-verification under the spirit of the rule found no such case
    number. This is the internal consistency mechanism working concretely — self-correction
    rather than waiting to be caught.
  - **The defendant advanced an entirely new legal theory: Civil Code art. 321** (appropriation
    designated by the payer), arguing the 2008 global settlement constituted such a designation
    and therefore displaces the statutory order in arts. 322/323 as a matter of the hierarchy of
    application — directly dismantling the plaintiff's alternative quantification. It grepped
    the text of arts. 321–323 to confirm that the conditional clause "where the payer does not
    make the designation under the preceding article" does support that ordering argument.
  - The defendant also verified the plaintiff's citation to "Supreme Court 115 台簡上 8",
    confirming the judgment exists but concerns the allocation of the burden of proof on the
    underlying relationship of a promissory note, unrelated to the appropriation-order issue,
    and therefore incapable of supporting the plaintiff's point.
- **Step 6, finalize.** Mechanical aggregation worked; `position_drift` was 0.3158 for the
  plaintiff and 0.35 for the defendant.
- **Step 7, judicial assessment of issue strength.** No predictive phrasing anywhere in the text
  ("this court holds", "should be upheld"); the analysis correctly followed the mechanical
  anchors and produced a pleading priority recommendation (formation and scope of the 2008
  offsetting agreement first → limitation defence second → the six-loan repayment issue in the
  middle → the rest briefly).
- **Step 8, citation verification.** See §3; all citations ultimately passed.
- **Step 9, pleading skeleton draft.** Persisted successfully using only published citations,
  honestly labelled "skeleton version, unpolished, requires a lawyer's revision before use".

**Final database state:** 1 case, 6 debate arguments, 6 court questions, 1 verdict, 34
deduplicated citation verifications, 1 pleading draft. **All 34 pytest tests passed** (4 more
than before the upgrade).

---

## 3. Problems found and fixed during the test

### 3.1 ✅ Fixed: gap in the `JUDGMENT_CITATION_RE` case-type whitelist (serious)

The original regex recognized only three case types (台上 / 台簡抗 / 台抗), while the local corpus
actually contains seven (台上 / 台再 / 台抗 / 台簡上 / 台簡抗 / 台簡聲 / 台聲). Verifying "Supreme
Court 115 台簡上 8" triggered `unparseable` — **台簡上 is a well-represented type in the corpus, so
every previous verification involving it was silently affected.**

Replaced with structural matching (leading 台 plus 1–3 non-numeric characters) rather than
enumeration. This is the same class of error as the earlier "sub-article 之N" bug — a whitelist
missing real variants — and four regression tests now lock it down, covering 台再, 台簡聲 and 台聲.

### 3.2 ✅ Validated: live FJUD verification correctly intercepted a fabricated citation

The plaintiff's Stage 1/2 citation to "Supreme Court 105 台簡上 33" produced an unambiguous
`not_found` under the verification flow (no local hit → live FJUD query; FJUD returned 20
keyword-similar results, none of them a Supreme Court decision). That agrees with the
defendant's grep of the local corpus in Stages 2/3, and with the plaintiff's own decision to
withdraw the citation in Stage 3.

**Three independent mechanisms — LLM self-checking, opposing-party cross-checking, and
mechanical FJUD verification — reached the same conclusion.** This is the most solid piece of
validation evidence from this run.

### 3.3 ⚠️ Identified, not fixed: `citation_text` uses exact string matching with no normalization

`_assert_all_published` in `db.py` checks published status by **exact string match** on
`citation_text`, not by the parsed (statute, article) tuple. In this run, "Civil Code art. 129"
and "Civil Code art. 129(1)(2)" were treated as **two separate verification records** despite
pointing at the same provision — the judge's `citations_used` used the short form while the
earlier verification used the full form, so `record_verdict` was rejected on first attempt and
the short form had to be verified separately.

**Not in scope for this round** (which prioritized the Stage 2/3 upgrade and the known FJUD and
regex problems), but recorded as the next candidate item: to be more tolerant,
`upsert_citation` and `_assert_all_published` should compare on the normalized `(law_name,
article_no)` produced by `parse_citation()` rather than the raw string, avoiding both redundant
verification and potential false rejection when the same provision is cited at different levels
of precision.

---

## 4. Comparison against the real judgment (114 台上 1547)

**Why the real case was remanded:** the lower court adopted the plaintiff's appropriation
calculation basis outright (NT$3,691,347, derived from the total sale price less tax) without
properly examining whether the defendant's asserted NT$750,000 per ping basis was well founded
— the witness testimony the defendant put forward had not been adequately weighed. The judgment
was vacated and remanded.

**How the system did:**

- ✅ **It hit the core factual dimension of the real issue.** The judge's fourth Stage 2 question
  ("the defendant is asked to explain the specific evidence that the NT$750,000 per ping unit
  price was agreed between the parties") and the whole exchange kept circling whether that
  calculation basis was agreed — closely matching what the remand focused on. This was produced
  from the parties' assertions alone, with no court analysis supplied.
- ⚠️ **It could not reproduce the judgment's specific reasoning.** The real decision turns on a
  concrete evidentiary evaluation — whether the probative weight of the defendant's witness
  testimony was adequately considered — whereas the fact input here deliberately described only
  "relevant witnesses were present" in general terms, omitting witness identities and their
  relationships to the parties to avoid unnecessary realism. The system therefore could not, and
  should not, reproduce the court's specific evaluation of a particular witness's credibility.
  **This is not a failure; it is a capability boundary created by input granularity**, recorded
  honestly.
- ➕ **It produced an argument the real case never contained.** The defendant's Stage 3 theory —
  that art. 321 payer-designated appropriation takes precedence over the statutory order in
  arts. 322/323 — appears nowhere in the real judgment, which resolved the appropriation dispute
  at the fact-finding level (the calculation basis) without reaching the question of statutory
  ordering. **Whether that is a valuable argument real counsel missed, or an unnecessary
  complication of a simple factual dispute, is genuinely open and requires a practising lawyer
  to judge. It should not be claimed as a strength by the system's own author**, and is recorded
  as a specific case to put to a design partner.

---

## 5. Conclusions

1. **The full pipeline runs end to end after the Stage 1/2/3 upgrade.** All ten steps worked,
   and the machine gates (write-once persistence, the verification gate) correctly intercepted
   both failure paths tested (unverified citation, case-type parse failure).
2. **The internal consistency mechanism was observed working for the first time in an
   integration test:** the plaintiff withdrew its own earlier questionable citation proactively
   rather than waiting to be caught. That is concrete evidence for the Stage 2/3 design addition,
   not an abstract claim.
3. **The test incidentally exposed a serious pre-existing bug** — the case-type whitelist gap,
   affecting precedent verification for over half the corpus — now fixed and locked by regression
   tests. Further confirmation that continuously stress-testing with real cases surfaces this
   class of problem better than trying to enumerate them in advance.
4. **There is early evidence the system identifies the core of the real contested issue**, but it
   cannot reproduce judicial determinations that depend on fine-grained facts such as witness
   credibility. That boundary should be stated honestly to users and lawyers, not overstated.
5. One **unfixed candidate item** was found (exact-string citation matching being too strict),
   recorded for later assessment.
