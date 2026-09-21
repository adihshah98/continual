# GTM Plan — Continual Learning Platform

**Companion to** `continual/platform/PLAN.md` (architecture and build order).
This document covers positioning, segmentation, competition, and sequencing.

Status: **plan.** Market facts are sourced and dated. Strategic claims are
labelled as judgment. Phase 0 numbers link to
`SLM/Plans/phase0/TECHNICAL_REPORT.md`.

Last updated 2026-09-20.

---

## 0. 10s pitch

Agent Harness: Your AI agent fails silently: wrong answers, stuck loops, unhappy users, with no error thrown. We read your production traces, find why it's failing, and ship tested fixes to your prompts and tools, so your agent gets better every week

Eg. A food delivery company uses an AI agent for support. A customer writes, "My order never arrived," and the agent replies, "I've escalated this to our team, they'll reach out within 24 hours." But the handoff tool returns `200 OK` with an empty queue field, so no ticket lands anywhere. Dashboards are green, and the agent said the right words. Then the customer chats in again two days later, angrier, and the agent starts from scratch. The symptom is a cluster of repeat contacts that begin with "I already told you about this." A harness layer notices that pattern, traces it back to the handoff calls, and proposes a guard: never say "escalated" unless the ticket ID comes back, plus a new eval case. The model isn't wrong; the plumbing is.

Model training: Your model stays frozen after launch. We turn user edits and automatic checks like passing tests and closed tickets into training signal, retrain your model on it, and only ship updates that pass your evals. It gets better with use.

Eg. A law firm uses an AI assistant to redline vendor contracts. It keeps suggesting a 12-month liability cap. Associates keep changing it to 24 months for large deals, and stop bothering with pushback on small ones. The right call depends on deal size, counterparty, and what the firm has been willing to accept. That's tacit judgment, not a fact in a document, so retrieval only helps so much.

The training signal is those repeated edits. Where verifiers exist, they add more: for example, checking that every case the assistant cites exists and supports the point made. The model trains on both, and the firm's evals confirm it didn't get worse elsewhere before the update ships. Over time its first-draft redlines look more like what this firm's partners would have written.

---



## 1. The three layers, corrected

The working framing was:

> 1. Improve the agent (prompts, tools, harness)
> 2. Improve the model from human signals (But give devs a platform where they can train the model etc)
> 3. Improve the model from verifiers built on traces

That is directionally right. Four corrections make it load-bearing.

### 1.1 Layer 3 is not "the scalable version of Layer 2"

They differ in **kind**, not in scale.


|              | Layer 2 — human signal       | Layer 3 — verified outcome                        |
| ------------ | ---------------------------- | ------------------------------------------------- |
| Measures     | What a user *preferred*      | What *happened in the world*                      |
| Fails when   | Users accept wrong answers   | No outcome is observable                          |
| Tier ceiling | Medium at best               | **Strong** — the only tier licensing RL or an SLA |
| Adversarial? | No — offline preference data | **Yes** — an optimizer attacks it                 |




### 1.3 Competition

New-age

- **Moda** (`moda.dev`, YC W2026) — turns production traces into verified
improvements across **prompts, tools, skills, evals, and memory**. Six failure
families (tools, memory, workflow, prompt, model behavior, product logic).
Validates by **replaying fixes against historical production data**. Claims 94%
root-cause attribution, +19% quality, −12% cost, −24% latency. **Explicitly no
model training** — it optimizes the harness around an existing model.
- **Agnost** (`agnost.ai`, YC S26, ~$250K pre-seed from Entrepreneurs First) —
*product analytics for conversational agents.* Reads every conversation to
surface feature requests, bugs, frustration, and churn signals. Three lines of
code or an OTel exporter. Google, Exa, Corgi as users; 1M+ events/day.

Evals Players

- [https://arize.com/compare/signal-vs-langsmith-engine-vs-braintrust-topics/](https://arize.com/compare/signal-vs-langsmith-engine-vs-braintrust-topics/)
  - All evals players launched this in 2026
    - Arize already ships **Signal**, which *"continuously reviews production traces to find recurring trajectory failures you do not, then turns them into evidence."* That's the auto-detect layer, already live, from a vendor that owns the ingestion pipe and the customer relationship.
    - Braintrust Topics
    - Langsmith Engine already proposes fixes and opens GitHub PRs

---



## 2. Market pull vs. competition vs. build/buy

Judgment, stated as judgment. Evidence in the right-hand column.


|                     | **Layer 1 — Harness**                                                         | **Layer 2 — Human signal**                                                                             | **Layer 3 — Verified outcome**                               |
| ------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------ |
| **Pull**            | High — everyone has this pain                                                 | High — but limited number of companies needing it.                                                     |                                                              |
|                     |                                                                               |                                                                                                        |                                                              |
| **Competition**     | **Crowded** — Moda, Agnost, Arize Signal, LangSmith Engine, Papaya, AgentCore | **Very well funded** — Trajectory $80M                                                                 | **Adjacent, not direct** — RL-env vendors at $200–2,000/task |
| **Build in-house?** | **Yes, easily** — replay is a sprint                                          | 50-50? Would be good to provide a platform that automates a bunch of the work on top of Tinker for you |                                                              |
| **Moat**            | Thin — taxonomy is copyable                                                   | Medium — infra + governance                                                                            | **Strong** — finding it is the hard part                     |
| **Commoditizing?**  | **Fast** — incumbents own ingestion                                           | Medium — training is a rate card                                                                       | **No**                                                       |


---



## 5. Sequencing — and the tension in it



### 5.3 Verifier discovery — from week one, in parallel

**This is the company's central research question and it does not wait for the
trunk.** From `TECHNICAL_REPORT.md` §7: *"the product question is not 'does
fine-tuning on traces work' — it is 'can we find the verifiable signal in a
customer's traffic.'"*

Find where a human already touches the output:


| Signal                          | Tier       | Example                                 |
| ------------------------------- | ---------- | --------------------------------------- |
| Downstream system postcondition | **Strong** | Refund posted, ticket closed, CI passed |
| Human edited before shipping    | Medium     | The edit is also the correct answer     |
| Ticket reopened after AI reply  | Medium     | Outcome-linked                          |
| Escalation to a human queue     | Medium     | Negative label, free                    |
| LLM-judge on transcript         | **Weak**   | SFT filter only. **Never an RL reward** |


Method: stratified sampling plus **adjudication rather than labelling**, with a
**non-negotiable uniform random slice** to catch a judge erring in the same
direction as the validator. Target 20–30 adjudications at onboarding, then
customer-owned batches of 5–15 on drift triggers.

**The gate for the entire business:** on one real customer's traffic, does a
Strong-tier verifier exist, and can we find it in under a week?

- **Yes** → the RL rung and the SLA are live; §2.2 says that capability is
worth more than the training platform around it.
- **No** → the product tops out at *"same behavior, cheaper."* Still a
business — price and pitch it differently, and **cut the RL roadmap.**



### 5.5 Pricing

Open question, deliberately. Three candidates:


| Model                         | Aligns with            | Problem                             |
| ----------------------------- | ---------------------- | ----------------------------------- |
| Per trace ingested            | Observability norms    | Prices the commodity, not the value |
| Per validated improvement     | **The proof artifact** | Lumpy; needs a trusted gate         |
| Per workload under management | Predictable            | Prices access, not outcome          |


**Lean per-validated-improvement.** It is the only one that prices the thing
nobody else sells — a paired significance test against a frozen holdout — and
it makes the gate a revenue event rather than a cost centre. Moda is reportedly
ingestion plus per-fix, which is the same instinct.

---

