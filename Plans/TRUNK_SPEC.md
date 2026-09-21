# Trunk — Design Spec

**Companion to** `PLAN.md` §4 Stage 1. That section names the components; this
one fixes the mechanism. The implementation plan
(`docs/superpowers/plans/2026-09-21-trunk.md`) argues from this document.

Status: **spec.** Decisions below were settled 2026-09-21. Open questions are
marked as such and are deliberately not decided here.

---

## 1. What the trunk is

One sentence: **the trunk turns a customer's production agent traffic into
immutable, replayable episodes, and nothing more.**

Everything downstream — failure clustering (L1), dataset building (L2), RL
rollouts (L3) — reads episodes. Nothing downstream reads raw telemetry. The
trunk is the only component that knows what OpenTelemetry is.

Per `PLAN.md` §1.1, every component here is shared by all three layers. That is
the justification for building it first and building it carefully: a defect in
the trunk is a defect in all three products simultaneously.

### 1.1 Non-goals for Stage 1

Named explicitly so they don't leak into the build:

- **No proxy.** Continual never sits in the traffic path (`PLAN.md` §4). A
  customer outage must never be attributable to us.
- **No realtime.** Episodes appear minutes after traffic, not instantly. No
  streaming materializer.
- **No UI.** The trunk's consumers are downstream code and a CLI, not a
  dashboard.
- **No training.** Stage 3.
- **No flow segmentation or weak-tier filter implementation.** The trunk
  provides the episode they run *over*, and the interface they plug into.
  `PLAN.md` Stage 1 lists both; they are specified in §7 as interfaces with
  deliberately trivial default implementations, so Stage 2 can replace them
  without touching ingest.

---

## 2. Decisions

### 2.1 Ingest path — OTLP front door, SDK for fidelity

Customers reach the trunk two ways, and the difference is load-bearing.

**(A) OTLP endpoint.** The trunk exposes an OTLP/HTTP receiver. A customer
points their existing OpenTelemetry exporter at it with one environment
variable (`OTEL_EXPORTER_OTLP_ENDPOINT`). Zero code change. Works with whatever
instrumentation they already run.

**(B) Continual SDK.** A thin wrapper over the customer's LLM client that emits
spans with content, tool schemas, tool results, model parameters and a session
ID guaranteed present. Exports over OTLP to the same endpoint.

Both paths land in the same receiver. The difference is what arrives.

**Why both.** OpenTelemetry's GenAI semantic conventions make message content
opt-in — `gen_ai.input.messages` and `gen_ai.output.messages` are gated behind
an experimental opt-in flag, and most vendor instrumentation truncates or omits
them by default, because prompts are large and contain PII. A default OTLP
trace therefore carries model name, token counts and latency, but not the
prompt.

That is enough to *count* failures. It is not enough to *replay* one. Replay
requires reconstructing the exact model input; an episode missing its tool
schemas replays against a different input than production saw, which is worse
than not replaying at all, because it looks like it worked.

Since replay is Stage 1's gate and L2/L3's offline eval (`PLAN.md` §1.1),
fidelity is not optional. But requiring the SDK before any value is delivered
contradicts `PLAN.md` Stage 2's "delivers value in week one." Hence both, with
the gap made explicit rather than hidden — see §2.2.

**Sequencing.** OTLP receiver first. The SDK is specified against what a real
customer's OTLP traffic turns out to be missing, so it is not in Stage 1's
critical path and is not specified in detail here.

**Note for the first design partner.** If they already run LangSmith,
Braintrust or Arize, those stores may already hold full content. A batch
importer reading their export is likely a faster path to the first replayable
episodes than the SDK. Ask before building.

### 2.2 Replay tier — a computed property of every episode

Every episode is stamped `replayable` or `observe_only` by a validator that
checks for the fields replay requires (§5.3).

This does three jobs:

1. **Honest capability reporting.** "3% of your episodes are replayable; add
   the SDK at your two agent entry points and that goes to 90%" is a factual
   upgrade conversation, not a sales one.
2. **A poison guard.** L2 dataset building and every eval filter on
   `replayable`. An incompletely captured episode can never enter a training
   set or a holdout. This directly serves the Stage 1 gate: *"a filter keeping
   the wrong 20% poisons the dataset silently with no error message."*
3. **A build signal.** The distribution of missing fields across a real
   customer's traffic is the SDK's requirements document.

### 2.3 Episode assembly — read-time materialization

Ingest appends raw spans and **does not decide what an episode is**. A separate
batch materializer groups spans into episodes and writes episode artifacts.

**The problem.** OpenTelemetry's unit is a span — one operation, with a trace
ID, span ID, parent span ID and a time range — and traces are designed around a
single request. The trunk's unit is an episode, which is multi-turn,
long-lived (minutes to days), spans many trace IDs (each user turn is usually
its own request), has no terminator (the user simply stops), and arrives out of
order (batched exporters flush on their own schedule; retried exports arrive
late).

Nothing in OpenTelemetry bridges that gap.

**Why read-time rather than stateful ingest.**

- The system of record is an object store (§2.4): immutable, hash-addressed,
  append-only. Raw spans are naturally append-only. Assembled episodes are not,
  because assembly changes its mind.
- **Late spans stop being a crisis.** Under stateful assembly, a span arriving
  after its episode was closed and hashed forces either dropping real data or
  writing `<hash>-v2`, which makes immutability a convention rather than a
  property. Under read-time, a late span appends and the next materialization
  picks it up.
- **Assembly rules are reversible.** Whether a 30-minute gap is one episode or
  two depends on the customer's product, and the first guess will be wrong.
  Read-time means re-materializing from raw with a new rule; stateful means the
  wrong rule is baked into every episode collected so far.
- **Ingest stays stateless.** No session affinity, no Redis in the hot path.
  The component taking production traffic is the one that should be least
  clever.
- It is the pattern `PLAN.md` §4 already commits to — "port hash-binding +
  append-only reads verbatim": an immutable base with derived views bound by
  hash to what they derived from.

**The cost, stated.** Queries are more complex, and a materialization pipeline
is more machinery than a writer. Accepted, because the alternative's failure
mode lands precisely where `PLAN.md` says the trunk is most fragile.

### 2.4 Storage — object store as system of record

- **Raw spans:** object storage (S3), partitioned `tenant/date/hour`, written
  append-only as newline-delimited JSON. Immutable. Never rewritten.
- **Episodes:** object storage, hash-addressed by content hash. Immutable.
- **Index:** Postgres. Holds only what queries filter and sort on — episode
  hash, tenant, session ID, time bounds, span count, replay tier, flow label,
  filter verdict. Content lives in S3.

This mirrors `lp_ingest`'s existing split (durable artifacts in S3, catalog row
in Postgres) and inherits its conventions (§3).

### 2.5 PII redaction — deferred, but positioned

`PLAN.md` §4 calls PII redaction "non-negotiable before real traffic." For
Stage 1 with a design partner, it is a **Stage 1 exit criterion, not an entry
requirement.**

The redaction hook is nonetheless built **now**, as a pass-through no-op,
positioned between validation and the first write. An empty function in the
right place costs nothing today and makes enabling redaction a configuration
change rather than a re-plumbing of a live pipeline under security-review
deadline pressure.

**Two conditions on the deferral:**

1. Design-partner traffic is real user data. The deferral must be a written
   agreement with that partner about what is stored, not an oversight.
2. Redaction ships before any second customer, and before any traffic the first
   partner has not explicitly cleared.

**Open question, not decided here:** whether production redaction runs
customer-side (in the SDK/collector, strongest posture) or server-side (easier
to fix, we hold raw PII briefly). The hook's position is identical either way,
so the decision is deferrable without cost.

---

## 3. Inherited conventions

The trunk is a new codebase but adopts `lp_ingest`'s conventions verbatim.
They are proven in a repo with the same stack and the same S3-plus-Postgres
shape. No code is copied; the idioms are.

- **Python 3.11+**, `uv` for env and lockfile, `ruff` for lint and format
  (`E,W,F,I,UP,B,SIM,C4`, line length 100, `SIM117` and `SIM105` off).
- **FastAPI** app; `main.py` is `include_router` calls only.
- **Module shape:** `pipeline.py` (orchestrator) · `store.py` (async raw SQL) ·
  `models.py` (Pydantic) · `routes.py` (thin HTTP).
- **DB access:** shared async `psycopg` pool, nested `async with` connection
  then cursor with `row_factory=dict_row`, always parameterized (`%s` + tuple),
  never f-strings into SQL. Rows returned through a `RowModel` subclass so
  `UUID`→str and `datetime`→ISO happen in one typed place.
- **Supavisor rule:** the DB is Supabase behind the Supavisor transaction
  pooler, which has no server-side prepared statements. Every DB entrypoint —
  the pool and `alembic/env.py` — passes `prepare_threshold=None`, or pooled
  connection reuse fails with "prepared statement already exists."
- **Config:** everything through `settings.py` (`pydantic-settings`, reading
  `.env.local`), which also `load_dotenv`s so boto3 sees `AWS_*`. No scattered
  `os.getenv`. Missing credentials raise a clear `RuntimeError` at use time,
  never an import crash.
- **Routes:** thin. Validate, call a store or pipeline function, translate
  exceptions (`logger.exception` → JSON 500). Correct status codes.
- **Docstrings one line, max.** Comments only where something non-obvious is
  happening — a constraint the code cannot show.
- **Tests:** `make check` = lint + format-check + unit tests. Unit tests are
  deterministic logic only — no DB, no network, no S3.

---

## 4. Architecture

```
  customer agent
       │
       ├── (A) existing OTel exporter ──┐   one env var, zero code
       │                                 │
       └── (B) continual SDK ────────────┤   guaranteed content + session_id
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │  OTLP/HTTP receiver  │  stateless
                              │  POST /v1/traces     │
                              └──────────┬───────────┘
                                         │
                                    normalize          OTLP protobuf/JSON
                                         │             → canonical span dict
                                         ▼
                                     validate          per-span required fields
                                         │
                                         ▼
                                 redact (no-op)        §2.5 — positioned, empty
                                         │
                                         ▼
                        raw/tenant=<t>/date=<d>/hour=<h>/<uuid>.jsonl    (S3)
                                         │                      immutable, append-only
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │    materializer      │  batch, idempotent
                              │  group by session    │
                              │  order by start time │
                              │  close on idle gap   │
                              └──────────┬───────────┘
                                         │
                         ┌───────────────┴───────────────┐
                         ▼                               ▼
          episodes/<hash>.json  (S3)            episodes row  (Postgres)
          immutable, hash-addressed             the queryable index
                         │
                         ▼
              tier: replayable | observe_only
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
    flow segment    weak-tier filter    replay harness
    (interface)     (interface)         (Stage 1 gate)
```

---

## 5. The episode

### 5.1 Identity and immutability

An episode's ID is the SHA-256 of its canonical serialization. Content-
addressed: the same spans always produce the same ID, and any change produces a
different one. Re-materializing unchanged input is therefore a no-op, which is
what makes the materializer safely idempotent and re-runnable.

The episode records the hashes of the raw span records it was built from. That
is the hash-binding `PLAN.md` §4 calls for: every derived artifact names its
inputs, so any episode can be audited back to raw bytes.

### 5.2 Assembly rules

- **Grouping key:** `(tenant_id, session_id)`. Session ID is read from the
  first available of: an explicit `continual.session_id` attribute, OTel's
  `session.id`, `gen_ai.conversation.id`, or the trace ID (which degrades to
  one-episode-per-trace when nothing better exists).
- **Ordering:** by span start time, ties broken by span ID for determinism.
- **Closing:** a session closes after `episode_idle_timeout_s` (default 1800)
  with no new spans, or at `episode_max_duration_s` (default 86400) from the
  first span, whichever comes first. The max-duration bound prevents a
  never-idle session from producing an episode that grows forever.
- **Late spans:** a span arriving for an already-materialized episode is
  included in the next materialization, which produces a *new* episode with a
  *new* hash. The prior episode is superseded, not amended — the index tracks
  which hash is current per session, and the superseded artifact is retained.

Every rule above is a configured value, not a literal, because §2.3's whole
argument is that these will be wrong at first.

### 5.3 Replay-required fields

An episode is `replayable` when **every** LLM-call span in it carries all of:

| Field | Why replay needs it |
| --- | --- |
| `gen_ai.request.model` | The model to re-invoke |
| `gen_ai.input.messages` | The exact input, untruncated |
| `gen_ai.output.messages` | The production output to compare against |
| `gen_ai.request.temperature`, `top_p` | Sampling params change the output |
| tool definitions as presented | A different tool set is a different input |
| tool call results verbatim | Replay must feed back what production fed back |

Anything else is `observe_only`. The validator records *which* fields were
missing, per episode — that record is the SDK's requirements document (§2.2).

**Truncation counts as missing.** A truncated prompt is not a prompt. If
instrumentation marks a field truncated, or content exceeds the configured
capture limit, the field is absent for tier purposes.

---

## 6. The Stage 1 gate

From `PLAN.md` §4:

> On real customer traffic, does the filter's keep-set survive a one-afternoon
> hand spot-check?

The trunk must therefore make that spot-check cheap. Concretely, it ships a CLI
that samples N episodes stratified by filter verdict and flow, renders each as
readable text, and records a human verdict alongside the machine one — so the
afternoon produces a measured agreement rate, not an impression.

This is the trunk's own acceptance test, not a Stage 2 feature.

---

## 7. Interfaces left open

Both are named in `PLAN.md` Stage 1 and both are properly Stage 2 work. The
trunk defines the seam and ships a trivial default, so Stage 2 replaces an
implementation rather than modifying the pipeline.

**Flow segmentation** — `segment(episode) -> str`. Default returns
`"unsegmented"`.

**Weak-tier filter** — `classify(episode) -> Verdict{keep: bool, reason: str,
confidence: float | None}`. Default keeps everything with reason
`"no-filter-configured"`. Ported from `tau/build_sft.py` in Stage 2.

`JEV.md` §"Where it can be used" proposes Jev for both: a fixed question schema
over every episode with known answer sets, where calibrated probabilities would
improve stratified adjudication sampling. Both run *after* materialization, so
adopting Jev touches neither ingest nor the store.

---

## 8. Out of scope, deliberately

| Not building | Why | When |
| --- | --- | --- |
| Streaming materialization | No consumer needs sub-minute episodes | If a live L1 view demands it |
| Span-level query API | Downstream reads episodes, not spans | If L1 needs a live recent-window view |
| Multi-region storage | One design partner | At enterprise deals |
| Auth beyond a per-tenant token | Design partner only | Before customer two |
| Retention and deletion policy | No data old enough to matter | With the PII work (§2.5) |
| SDK (Python, TypeScript) | Specified against real OTLP gaps | Stage 1 exit, week 2+ |
