# Prompt Comparison, Batch 2: Claim-Basis Examination v2 Across Four New Causes of Action

> English version of [`docs/zh/prompt-comparison-claim-basis-batch2.md`](../zh/prompt-comparison-claim-basis-batch2.md).

> **Test date:** 2026-08-09 · Methodology and contamination controls as in
> [batch 1](prompt-comparison-claim-basis-batch1.md): facts taken only from the parties'
> statements in paragraphs 1 and 2 of the real judgments, excluding the court's findings; the
> answer judgment temporarily removed from the corpus during testing and restored afterwards.
>
> Four causes of action, in order: consumer loan (TPSV 114 台上 2246), restitution of unjust
> enrichment (TPSV 114 台上 1715), tort (TPSV 114 台上 1131), employment dispute
> (TPSV 114 台上 2097).
>
> **The prompts themselves were not modified** — batch 1's `stage1_prompt.txt` and
> `stage1_prompt_claimbasis_v2_EXPERIMENTAL.txt` were reused, per the instruction to accumulate
> samples before discussing design changes.

---

## Case-by-case results

### Case 002 — consumer loan / settlement agreement circumventing the interest ceiling

**The court's actual reasoning.** The lower court found the settlement agreement was calculated
on the whole NT$9m and therefore substantively circumvented the interest ceilings in Civil Code
arts. 205/206, making it **wholly void**, so the lender could not claim under it.

| | Current version | Experimental v2 |
|---|---|---|
| Did the defendant (the winning side) reach the correct conclusion (wholly void)? | ✅ Yes, via the evasion-of-law doctrine under art. 71 | ✅ Same, via art. 71, and honestly flagged one citation (109 台上 2736) as not found locally and pending verification |
| Did the plaintiff (the losing side) have a complete alternative strategy? | ❌ Only asserted partial invalidity under the proviso to art. 111; no fallback | ✅ **An explicit extra layer:** even if the settlement is wholly void, a claim can still be brought independently on the original loan relationship (arts. 474/478) for the unpaid principal of NT$1,373,074 on the third tranche plus interest within the 16% ceiling — so voiding the settlement does not extinguish the whole claim |

**Assessment.** Both versions hit the core conclusion equally. The difference is in the
**completeness of the losing side's alternative argument**: the scaffold version thought one step
further about what remains if the primary argument fails. For practising lawyers the value is
real — even when you expect to lose the main point, you prepare the fallback that limits the
loss, and the current version misses that entirely.

### Case 003 — restitution of unjust enrichment / apportionment among co-owners — **the strongest hit in this batch**

**The court's actual reasoning (grounds for remand).** The lower court failed to establish
whether **other unit owners** in the building had likewise exceeded their allocated share, and
concluded too readily that the defendant's unjust enrichment accrued entirely to the plaintiff —
"not in accordance with law", hence remand. Unjust enrichment should be claimed by all injured
co-owners in proportion to their shares, not taken by the plaintiff alone.

| | Current version | Experimental v2 |
|---|---|---|
| Did the plaintiff reach the core of the remand — that other co-owners exist and the enrichment may not accrue solely to it? | ❌ **Not touched at all.** Claimed the full amount with no awareness of the apportionment problem | ✅ **Hit precisely.** Step 3 states: "the defendant's most likely rebuttal is … that the rent-equivalent enrichment from the 46/1344 excess occupation should in theory be shared among all co-owners unable to exercise their use and profit rights, in proportion to their respective shares, rather than accruing entirely to the plaintiff." It proactively grepped to Supreme Court 115 台上 789 (apportionment of unjust enrichment among multiple co-owners by share) as support, and **adjusted the pleading strategy accordingly**, narrowing the amount claimed to the loss corresponding to the plaintiff's own share to reduce the risk of dismissal |

**Assessment.** This is not the weak signal of "citing the same article". The scaffold version's
plaintiff **derived, with no knowledge of the answer, essentially the same specific legal problem
the Supreme Court remanded on** — then found supporting authority and changed litigation strategy
because of it. Neither current-version output touched the angle. The strongest evidence in this
batch.

### Case 004 — tort / fraud plus unlawful deposit-taking under the Banking Act

**The court's actual reasoning (grounds for remand).** The lower court dismissed the plaintiff on
the basis that it had contracted with a foreign developer and had been informed of the investment
risk, **without examining whether the conduct constituted deemed deposit-taking under art. 29-1 of
the Banking Act** — i.e. unlawfully conducting banking business. Remanded for further examination.

| | Current version | Experimental v2 |
|---|---|---|
| Did it focus on art. 29-1 deemed deposit-taking as the real core? | ⭘ Partly — the plaintiff version did cite arts. 29 and 29-1 and found a closely similar precedent (115 台上 311); a decent showing | ✅ More complete — the plaintiff version additionally raised **Company Act art. 23(2)** as an independent objective liability route not requiring proof of fraudulent intent; the defendant version located the issue precisely on whether the defendant personally received the funds, an element of art. 29-1, almost exactly matching the uncertainty in the remand |

**Assessment.** Worth recording that the current version performed well here — it is not weak in
every case. The scaffold still added an independent alternative basis of claim and a more precise
location of the genuinely contested element.

### Case 005 — employment dispute / does abuse of disciplinary power amount to infringement of personality rights? ⚠️ methodologically flawed, see below

**The court's actual reasoning.** Whether the dismissal was lawful and whether there was an abuse
of disciplinary power gravely infringing personality rights are **two questions with different
elements**; conflating them was the ground for remand.

| | Current version | Experimental v2 |
|---|---|---|
| Did it clearly separate the two? | ❌ The plaintiff version treated "the dismissal was unlawful" as directly establishing entitlement to solatium, without separate examination; the defendant version dealt with it in one line — and that line was already present in the case facts as the defendant's original defence, not derived | ✅ Both versions separated and examined the two explicitly and in detail, honestly noting that the evidence on solatium was thinner and that no directly supporting precedent was found in the corpus |

**⚠️ Honest disclosure of a methodological flaw.** In step 3 of this case's scaffold prompt, **a
case-specific hint was added**: "check in particular whether 'unlawful dismissal procedure or
grounds' and 'abuse of disciplinary power infringing personality rights' have identical elements —
do not conflate them." That is very close in shape to stating the answer — it is not a general
examination discipline but a pointer at this case's specific legal question. **The positive result
here therefore cannot count as evidence for the general four-step scaffold; its evidential value
is heavily diluted by that hint.** In future rounds, case-specific hints should be pulled back to
general principles (like the structural reminder used in cases 002–004 about not bundling multiple
itemized amounts or candidate paths), and this style of naming the specific legal issue should not
recur.

---

## Combined conclusions, batches 1 and 2 (five cases)

1. **Across five cases the scaffold version never once missed something the current version
   caught** — a one-way advantage so far. But n = 5 is still not a statistical conclusion, and
   observing no counterexample is not evidence that none exists.
2. **The strongest evidence comes from case 003 and the original case 001.** In both, the scaffold
   version derived a specific legal problem closely matching the court's actual grounds for
   remand (case 001 hitting art. 101(1) deemed fulfilment; case 003 hitting apportionment of
   unjust enrichment among co-owners), each accompanied by proactively located supporting
   authority. Not vague coincidence.
3. **Case 002 shows a different kind of advantage.** Not hitting the article the court used, but
   preparing an additional fallback for the losing side — meaning the scaffold's value is not only
   in predicting who wins but in making each side's argument more complete, which matches this
   project's positioning as an issue organizer: whoever wins, secure the argument quality of both
   sides first.
4. **Case 005's positive result must be discounted** because of the flawed prompt, and should not
   count toward evidence that the general scaffold works.
5. **Cost observation.** Scaffold outputs are consistently longer (noticeably more reasoning text
   and more greps in most cases). The actual token and time cost difference has not been
   quantified; that is the next piece of homework.
6. **Echoing the previously recorded self-citation verification gap.** Several outputs — the
   defendant versions in cases 002 and 005 especially — show that when a grep returns large volumes
   of irrelevant results (a search for "no merit" hitting the 250-result cap), the agent honestly
   reports not adopting them as citations. This confirms the current retrieval is noisy and
   imprecise, supporting the recorded direction that citation sources should not be decided by
   local grep alone.

## Recommended next steps

- Treat case 005 as a contaminated sample. To count it formally, rerun without the case-specific
  hint.
- Five samples is a meaningful improvement over "n = 1, no conclusion", and the two precise hits on
  remand grounds (cases 001 and 003) are not weak evidence. Still, add at least two or three more
  cases — with all hints reduced to general structural principles and no case-specific naming —
  before formally considering merging the scaffold into the production `stage1_prompt.txt`.
- Quantify the token and runtime cost difference, to inform whether full adoption is worth it.
