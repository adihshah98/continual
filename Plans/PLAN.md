# Continual — Platform Plan

## 1. Architecture: one trunk, three layers

```
                  ┌────────────────────────────────────┐
                  │  TRUNK  (build once, serves all 3) │
   production ───▶│  1. Capture — OTel ingest          │
   traffic        │  2. Episode store                  │
                  │  3. Flow segmentation              │
                  │  4. Weak-tier filter               │
                  │  5. Replay harness                 │
                  └──────────────┬─────────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        ▼                        ▼                        ▼
┌───────────────┐      ┌───────────────────┐    ┌────────────────────┐
│ L1  HARNESS   │      │ L2  HUMAN SIGNAL  │    │ L3  VERIFIED       │
│               │      │                   │    │     OUTCOME        │
│ prompts,tools │      │ edits, retries,   │    │ downstream state   │
│ workflow,     │      │ accepts →         │    │ change → reward    │
│ memory        │      │ training data     │    │                    │
│               │      │                   │    │                    │
│ gate: replay  │      │ gate: frozen      │    │ gate: same, plus   │
│               │      │ holdout + McNemar │    │ reward-hack audit  │
│               │      │                   │    │                    │
│ needs: none   │      │ needs: a feedback │    │ needs: STRONG      │
│               │      │ surface + ~300 ep │    │ verifier           │
│ ships: wk 1   │      │ ships: month 3    │    │ ships: month 4+    │
└───────────────┘      └───────────────────┘    └────────────────────┘
                              │                          │
                              └──────────┬───────────────┘
                                         ▼
                              ┌────────────────────────┐
                              │  TRAINING PLATFORM     │
                              │  (shared by L2 and L3) │
                              │                        │
                              │  dataset builder,      │
                              │  job runner, eval      │
                              │  gate, promote/        │
                              │  rollback, CLI         │
                              │                        │
                              │  L2 → SFT/DPO          │
                              │  L3 → SFT + RL         │
                              └────────────────────────┘
```



### 1.1 What is shared, and what is not


| Component                   | L1  | L2  | L3  | Note                                          |
| --------------------------- | --- | --- | --- | --------------------------------------------- |
| OTel capture, sampling, PII | ✓   | ✓   | ✓   | Identical problem                             |
| Episode store + schema      | ✓   | ✓   | ✓   | Same object                                   |
| Flow segmentation           | ✓   | ✓   | ✓   | L1 clusters failures; L2/L3 scope the model   |
| **Weak-tier filter**        | ✓   | ✓   | ✓   | L1's failure detector *is* L2's SFT filter    |
| **Replay harness**          | ✓   | ✓   | ✓   | L1's whole gate; L2/L3's offline eval         |
| Training platform           | —   | ✓   | ✓   | **The L2/L3 shared surface (§1.3)**           |
| Human-feedback extraction   | —   | ✓   | —   | Needs a product surface that produces a trail |
| **Strong verifier**         | —   | —   | ✓   | Adversarial. The unsolved problem             |
| Reward-hacking audit        | —   | —   | ✓   | Hand-read 30 rollouts, per Phase 0 §6.5.4     |


### 1.2 L2's real shape: a platform, not a service

The customer signal is unambiguous (`SLM/Update.MD`): RocketLawyer, HappyRobot,
and Ramp all said model ownership is the moat, they want to be **actively
involved** in training, and several were already hand-rolling the loop.

So L2 is **"give devs a platform where they can train the model"** — not
"we train a model for you." Concretely:


| Decision                         | Who owns it                                |
| -------------------------------- | ------------------------------------------ |
| Which base model                 | **Customer**                               |
| Which technique (SFT / DPO / RL) | **Customer**                               |
| What goes in the dataset         | **Customer**, from our filtered candidates |
| Hyperparameters                  | Customer, with our defaults                |
| When it ships                    | **Customer** — ratchet, never auto-promote |
| Whether the eval gate passed     | **Us** — this is the product               |




**Design implications, all load-bearing:**

- **CLI-first.** Most of the surface lives where engineers already work.
- **Exportable artifact at every step.** Dataset, adapter, eval report.
- **No auto-promotion, ever.** Ratchet 5 → 25 → 50 → 100%, or retreat to 0.
- **Bring-your-own-compute is a first-class path**, not an enterprise upsell.

---



## 2. Competitive position by layer

Detail in `GTM Plan.md` §1.3 and §2. Architectural summary only:


| Layer  | Competitors                                                                        | Build-in-house?                                            | Our position                                        |
| ------ | ---------------------------------------------------------------------------------- | ---------------------------------------------------------- | --------------------------------------------------- |
| **L1** | Moda, Agnost, Arize Signal, Braintrust Topics, LangSmith Engine, Papaya, AgentCore | **Yes, easily** — replay is a sprint                       | Delivered free in week one to earn the trace access |
| **L2** | **Trajectory ($80M)**, W&B Serverless, Together, HF TRL                            | 50/50 — a platform over Tinker-class compute is real value | Compete on **control + proof**, not on training     |
| **L3** | Adjacent only — RL-env vendors at $200–2,000/task                                  | **Rarely** — this is why that market exists                | **The durable seat**                                |


Three things to hold onto:

1. **Every evals player shipped auto-detection in 2026** — Arize Signal,
  Braintrust Topics, LangSmith Engine. L1 is commoditizing in real time, from
   vendors who already own the ingestion pipe.
2. **Agnost and Moda:** Their stated direction is
  to turn conversational traces *"into custom models that run the agent*  
   *better, faster & cheaper than frontier models."* Same destination, opposite  
   starting point — they own capture, we own training evidence.

---



## 4. Build order

Each stage produces a decision; expensive stages are gated by cheap ones.

### Stage 1 — Trunk *(weeks 1–5)*


| Component          | Notes                                                |
| ------------------ | ---------------------------------------------------- |
| OTel ingest        | No proxy. Continual does not sit in the traffic path |
| Episode store      | Immutable, hash-addressed                            |
| PII redaction      | Non-negotiable before real traffic                   |
| Flow segmentation  | Moda's failure-family framing (`GTM Plan.md` §1.3)   |
| Weak-tier filter   | Port from `tau/build_sft.py`                         |
| **Replay harness** | Re-run a change against stored traces. Pays off 3×   |
| Integrity layer    | Port hash-binding + append-only reads verbatim       |


**Gate:** on real customer traffic, does the filter's keep-set survive a
one-afternoon hand spot-check? *"A filter keeping the wrong 20% poisons the
dataset silently with no error message."*

### Stage 2 — L1, delivered free *(weeks 5–8)*

Failure clustering → root-cause attribution → proposed fix → **replay
validation**. Memory/retrieval fixes scoped per §1.4.

**Why build a commoditizing layer:** it is the price of trace access. It
delivers value in week one while L2's ~300 episodes accumulate, and it answers
*"what do I get before you have enough of my data?"* It is **not** the product
and is never priced as one.

**Gate:** measurable improvement on replay with no regression. If L1 cannot
clear its own replay gate, L2's eval gate will not either — same machinery.

### Stage 3 — Training platform + L2 *(weeks 8–16)*

The shared surface from §1.3: dataset builder, job runner, eval gate,
promote/rollback, CLI. Then L2 on top — extract human-feedback signal (edits,
retries, accepts, escalations) into training candidates.

Ship the **proof**, not just the model: paired McNemar against the incumbent on
a frozen holdout, power limit stated. Nobody in §2 sells that.

**Gate:** does the adapter beat the incumbent on the customer's own frozen
holdout at stated power? Refuse promotion otherwise. **No exceptions** — this
is the entire credibility of the product.

### Stage 4 — Verifier discovery *(parallel, from week 1)*

**The central research question. It does not wait for the trunk.**


| Signal                          | Tier       | Example                                 |
| ------------------------------- | ---------- | --------------------------------------- |
| Downstream system postcondition | **Strong** | Refund posted, ticket closed, CI passed |
| Human edited before shipping    | Medium     | The edit is also the correct answer     |
| Ticket reopened after AI reply  | Medium     | Outcome-linked                          |
| Escalation to a human queue     | Medium     | Negative label, free                    |
| LLM-judge on transcript         | **Weak**   | SFT filter only. **Never an RL reward** |


Method: stratified sampling plus **adjudication rather than labelling**, with a
**non-negotiable uniform random slice** to catch a judge erring in the same
direction as the validator. 20–30 adjudications at onboarding, then
customer-owned batches of 5–15 on drift triggers.

**The gate for the whole business:** on one real customer's traffic, does a
Strong verifier exist, and can we find it in under a week?

- **Yes** → L3 and the SLA are live. That capability is the cheap end of a
market paying $200–$2,000 per hand-built verifier.
- **No** → the product tops out at *"same behavior, cheaper."* Still a
business. **Cut the RL roadmap** and reprice.



### Stage 5 — L3 + continual loop *(month 4+, gated on Stage 4)*

RL on the Strong verifier, plus the reward-hacking audit (hand-read 30
rollouts; watch transfer-terminated successes and idempotent no-ops — Phase 0
§6.5.4 names both exploits). Then the drift detector (per-flow pass-rate, must
survive traffic-mix shift) and shadow-eval gate. Both **NOT BUILT**.

**Sequence note:** Phase 0 §6.5.6 says run the **best-of-N probe first** — $45,
no new code — before committing $566 to GRPO. That discipline carries over:
spend $45 to decide whether to spend $566.

---

