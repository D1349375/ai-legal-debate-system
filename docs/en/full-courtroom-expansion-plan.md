# Full-Role AI Moot Court Simulator — Expansion Plan

> English version of [`docs/zh/full-courtroom-expansion-plan.md`](../zh/full-courtroom-expansion-plan.md).

> **Date:** 2026-08-06
> **Module:** a full-role courtroom rehearsal and judicial-reasoning analysis module
> **Position:** a pre-hearing simulation engine providing multi-party exchange between
> plaintiff, defendant, prosecutor and judge, producing a simulated decision and a risk
> analysis of how the court's reasoning is likely to form.
>
> **Scope note:** this is Phase 4 material, outside the current build. The judge role has
> since been pulled forward into the Phase 1 core (see
> [architecture](architecture.md) §4), so this document describes the criminal mode and the
> live UI rather than the three-role civil court already implemented.

---

## 1. Overview

In practice, top firms facing major criminal proceedings or high-value civil disputes hold
expensive moot courts before the hearing.

This module extends the multi-agent debate architecture into a full-role simulator. Based on
the case type — civil or criminal — the system dispatches several AI roles carrying
domain-specific skills, runs a realistic courtroom exchange following standard procedural law,
and has the judge agent issue a simulated decision plus an analysis of how the court's
reasoning formed.

---

## 2. Dual-mode architecture

The system switches role configuration based on the uploaded case file and the pleadings.

```
┌────────────────────────────────────────────────────────────────────────┐
│ Civil Courtroom Simulator                                              │
│                                                                        │
│ • Plaintiff's representative agent: basis of claim, damages            │
│   calculation, allocation of the burden of proof                       │
│ • Defendant's representative agent: defences, exclusion clauses,       │
│   procedural defects, set-off                                          │
│ • Presiding judge agent: manages the hearing, organizes the contested  │
│   issues, questions both sides, issues the simulated decision          │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│ Criminal Courtroom Simulator                                           │
│                                                                        │
│ • Public prosecutor agent: elements of the offence, proof of intent or │
│   negligence, sentencing submissions                                    │
│ • Defence counsel agent: presumption of innocence, reasonable doubt,   │
│   inadmissibility, mitigation                                           │
│ • Presiding judge agent: rules on evidentiary admissibility, conducts  │
│   questioning, issues the simulated ruling                              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Four-stage courtroom SOP protocol

Letting several agents converse freely produces noise. The system instead follows the standard
progression of civil and criminal procedure, which keeps the output structured.

```
[ Step 0: case file input and statute retrieval (verification engine) ]
                        ↓
[ Stage 1: issue organization, statement of claim / defence ]
 • Prosecutor or plaintiff agent states the claim and the alleged facts
 • Defence or defendant agent states the substance of the defence and its legal basis
                        ↓
[ Stage 2: judicial questioning and evidentiary exchange ]
 • Judge agent puts pointed questions to both sides on the contested issues
   (e.g. "what is the defendant's explanation for this message record?")
 • Both sides argue admissibility (unlawfully obtained evidence) and probative weight
                        ↓
[ Stage 3: closing argument, sentencing or damages submissions ]
 • Both sides deliver closing summaries and their sentencing or compensation position
                        ↓
[ Stage 4: simulated decision and reasoning analysis ]
 • Judge agent issues the simulated holding and reasoning
 • System produces a judicial-reasoning risk map and a list of the key additional
   evidence worth obtaining before the hearing
```

---

## 4. Role prompts and skill distillation

Agents do not use generic prompts; each is given professional role DNA through the Nuwa
distillation technique.

1. **Judge agent (`taiwan-judge-perspective`)**
   - *Disposition:* neutral, objective, rigorous, acutely sensitive to how the burden of proof
     is allocated.
   - *Function:* favours neither side, controls the procedure, and produces a holding and
     reasoning in the style of the Taiwanese judiciary.
2. **Public prosecutor agent (`taiwan-prosecutor-perspective`)**
   - *Disposition:* severe, focused on the state's penal authority, pursues the details of the
     offence.
   - *Function:* applies the elements of the relevant criminal provisions precisely and attacks
     gaps in the defence.
3. **Defence / plaintiff's counsel agent (`taiwan-litigator-perspective`)**
   - *Disposition:* protects the client's interests, works the presumption of innocence and
     clause interpretation.
   - *Function:* argues in the orthodox register carried by the `taiwan-legal-pleading` skill.

---

## 5. UI concept: streaming courtroom log

To turn what would otherwise be a minute of waiting on token generation into something worth
watching:

- **Style:** a live courtroom interface rendered as text.
- **Role cards and motion:** when the prosecutor agent speaks, its card is brought forward and
  its argument streams in with a typewriter effect, then the interface switches to the defence
  agent's response.
- **Live issue dashboard:** a sidebar updating the current assessment (for example, plaintiff
  55% versus defendant 45%).

---

## 6. Conclusion and next steps

Suggested build order:

1. **MVP:** civil mode first — two counsel agents plus the judge's decision. Lower difficulty,
   and it covers most common disputes.
2. **v1.5:** criminal mode (prosecutor versus defence counsel) and the streaming courtroom UI.

---

*Report generated 2026-08-06.*
