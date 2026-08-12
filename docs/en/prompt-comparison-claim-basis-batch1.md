# Prompt Comparison: Current Stage 1 vs. Claim-Basis Examination (v2 experimental)

> English version of [`docs/zh/prompt-comparison-claim-basis-batch1.md`](../zh/prompt-comparison-claim-basis-batch1.md).

> **Test date:** 2026-08-09 · **Case:** `test-2026-08-09-claimbasis-001`, drawn from the parties'
> assertions in Supreme Court 114 台上 1069 (a claim for construction payment). **Facts are taken
> only from the judgment's paragraphs 1 and 2 — the parties' own statements — excluding the
> court's findings and the outcome.** A fictional test case, not legal advice.
>
> **Purpose:** to answer the challenge "what makes our issue analysis better than just asking an
> LLM?" The approach is to make a *single* agent's internal reasoning rigorous first, and only
> then decide whether to put it into a multi-agent workflow — not the other way round.

This compares the current free-form `templates/stage1_prompt.txt` against a new
`templates/stage1_prompt_claimbasis_v2_EXPERIMENTAL.txt`, which imposes a mandatory four-step
claim-basis examination scaffold. Both were run once per side on the same facts, and scored for
issue coverage against the court's actual reasoning as the answer key.

---

## 1. Methodology and contamination controls

- **Case selection.** From the 1,088-judgment corpus, a construction payment case (TPSV 114 台上
  1069) with a self-contained fact pattern, a clear basis of claim, and layered defences.
- **Fact input.** Only the fact descriptions from paragraph 1 (plaintiff's assertions) and
  paragraph 2 (defendant's defences). **Nothing** from paragraph 3 (the lower court's findings),
  paragraph 4 (the Supreme Court's determination), or the holding — so the answer cannot leak
  into the input.
- **Contamination control.** During the test the full judgment and its `_source.json` were
  **temporarily moved out of** `corpus/judgments/`, so a subagent grepping for stance terms could
  not retrieve the answer itself. Restored afterwards.
- **Execution.** Four independent, mutually isolated subagents unaware of each other's existence:
  current-version plaintiff, current-version defendant, experimental plaintiff, experimental
  defendant. Identical fact input, identical stance retrieval terms, identical corpus access,
  identical output JSON schema.
- **Scoring.** Compared against paragraphs 3 and 4 to see whether each version reached the key
  legal points the court actually relied on.

---

## 2. The court's actual reasoning (the answer key)

1. **Payment review / acceptance as a condition.** The lower court found items 1–4 and 5–8 were
   completed (supervisor sign-off, witness testimony, referral to accounting for payment) and
   that an audit found no impropriety, so the "contractor misconduct" clause did not apply. For
   items 5–8 it found **the appellant deliberately failed to carry out the acceptance and payment
   procedure, so under Civil Code art. 101(1) the condition is deemed fulfilled** — acceptance is
   deemed complete and payment is due. This is one of the decisive legal bases of the outcome.
2. **Limitation defence on item 5.** The lower court established that item 5 was actually
   performed until 2018-05-11, that the plaintiff's demand on 2019-06-18 went unanswered, and that
   suit was filed on 2019-11-20, **so the two-year limitation had not run** — a completion date
   and accrual point different from what the defendant asserted (2015-12-31), showing this issue
   turns heavily on precise factual verification.
3. **Unjust enrichment set-off** (the part remanded, and the core of the outcome). The lower court
   dismissed this defence on the basis that the items were unrelated to the works in question and
   therefore raised no unjust enrichment obligation. **The Supreme Court held that the lower court
   had not examined the matter closely enough and had been "unduly hasty" in rejecting the set-off
   defence, and remanded** — expressly recognizing that forfeiture under the misconduct clause and
   unjust enrichment set-off are **two independent legal relationships requiring separate
   examination**; difficulty establishing the first is no reason to reject the second along with
   it.

---

## 3. Point-by-point comparison

| The court's actual focus | Current version (baseline) | Experimental v2 (claim-basis scaffold) |
|---|---|---|
| ① Basis of the contractor's remuneration claim (arts. 490/505) | ✅ Both sides cited it | ✅ Both sides cited it |
| ② Characterizing acceptance as a condition, and whether art. 101(1) deems it fulfilled | ❌ **Not raised.** The plaintiff version characterized review and acceptance as an agreement on the time for performance rather than a condition precedent — a different reasoning path that reaches a similar conclusion but **misses the specific legal mechanism the court used** | ✅ **Hit directly.** Step 1 of the plaintiff version lists the candidate: "whether, under arts. 234 and 101(1), the employer's delay in acceptance or improper obstruction of the condition means the condition is deemed fulfilled". Step 3 develops it: "if acceptance is a contractually stipulated condition precedent and the defendant delayed it without justification, one may assert acceptance is deemed complete or that the employer is in default of acceptance" — **closely matching the court's actual reasoning** |
| ③ The item 5 limitation defence requires precise dates | ✅ Both sides flagged the need to verify the demand and filing dates; no significant gap | ✅ Both flagged it, and marked it explicitly as a structured "evidence unclear / information insufficient, requires verification" state |
| ④ Misconduct forfeiture and unjust enrichment set-off are independent legal relationships | ✅ The defendant version handled set-off as an alternative claim — right direction | ✅ Handled likewise, and **additionally stated in terms** that "this alternative path does not depend on whether the contractual misconduct clause is valid; the legal relationships are independent … (d) must not be skipped merely because (c) appears sufficient" — turning the very error the Supreme Court later identified into an **explicit prior check** |
| ⑤ Detecting internal contradiction in the opponent's argument (the defendant simultaneously argues item 5's acceptance was never completed *and* uses its completion date to start the limitation clock) | ❌ Not raised by either baseline output | ✅ **The plaintiff version caught it unprompted:** "the defendant argues on one hand that item 5's acceptance procedure was never completed … while on the other hand asserting a completion date of 2015-12-31 as the limitation start point; the two are in logical tension". **The defendant version independently self-corrected**, separating item 5's argumentative path from items 1–4 and 6–8 to avoid the contradiction. Both directions hit; neither baseline output touched it |

---

## 4. Conclusion, with honest limits

**The result favours the experimental version, on concrete and checkable evidence.** It did not
regress on ①③④, and on ② and ⑤ it reached points the baseline missed entirely — ② corresponding
directly to the statutory provision the Supreme Court actually relied on (art. 101(1)), and ⑤
being a logical-contradiction detection that both experimental outputs found independently and
neither baseline output did. This is not an impression; it is a line-by-line comparison against
the judgment text.

**What this test cannot show:**

1. **n = 1.** Not a statistically meaningful conclusion — a concrete, checkable positive signal
   that needs repetition across more cases before it can be upgraded to "this scaffold
   systematically improves issue coverage".
2. **No citation authenticity or substantive check was run.** Neither version's
   `cited_precedents` — the experimental defendant cited four precedents at once — has been through
   `engine/verify.py` to confirm existence, nor read in full to confirm the cause of action
   actually supports the proposition. That is the next step, and a good reasoning analysis is not
   a reason to skip verification.
3. **The baseline is not weak.** The baseline plaintiff produced a high-quality move — citing a
   precedent and then proactively distinguishing it on the facts (114 台上 1105) — and the baseline
   defendant handled the alternative unjust enrichment defence correctly in outline. The difference
   is that the experimental version is more rigorous on coverage and internal consistency, not that
   the baseline is poor.
4. **Only Stage 1 was tested.** Whether the scaffold improves quality once wired into Stage 2
   (mandatory rebuttal), Stage 3 (closing) and the judge's issue-strength assessment — or whether
   longer reasoning dilutes information density downstream — remains unverified.

---

## 5. Recommended next steps

1. **Do not swap `stage1_prompt.txt` for the experimental version on n = 1.** Run the same method
   on two or three more causes of action (tort, employment disputes, matching the Phase 1.5
   coverage) and see whether the ② and ⑤ advantages reproduce, rather than being a lucky case.
2. **Design matching claim-basis versions of `stage2_prompt.txt` and `stage3_prompt.txt`.** The
   underlying observation is right: secure single-agent output quality per round first, then
   discuss what the multi-round protocol adds. Stages 2 and 3 — mandatory engagement with the
   opponent's strongest argument plus a falsifier — arguably need this structured examination even
   more, to prevent evasion.
3. **Only merge the v2 scaffold into the production `stage1_prompt.txt` once the advantage is
   stable across cases** (rather than maintaining a permanent parallel branch), and run a full
   Phase 1.5 end-to-end afterwards to confirm behaviour across all four stages.
4. If a more rigorous version of this comparison is wanted later, fix this method into a
   repeatable script rather than pasting prompts by hand each time.
