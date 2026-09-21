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

### 2.1 Ingest path — OTLP front door, SDK for fidelity, batch import for backfill

Customers reach the trunk three ways, and the difference is load-bearing.

**(A) OTLP endpoint.** The trunk exposes an OTLP/HTTP receiver. A customer
points their existing OpenTelemetry exporter at it with one environment
variable (`OTEL_EXPORTER_OTLP_ENDPOINT`). Zero code change. Works with whatever
instrumentation they already run.

**(B) Continual SDK.** A thin wrapper over the customer's LLM client that emits
spans with content, tool schemas, tool results, model parameters and a session
ID guaranteed present. Exports over OTLP to the same endpoint. Specified in
detail in §2.6.

**(C) Batch import.** A one-time CLI load of a design partner's *existing*
observability export (LangSmith, Braintrust, Arize) into the same raw-span
store, for a partner who has history worth backfilling before either (A) or
(B) has accumulated any. Specified in detail in §2.7.

All three land in the same place — normalized `CanonicalSpan` records passing
through validate → redact → the raw store (§2.4). The difference is what
arrives, and by what path.

**Why (A) and (B) both.** OpenTelemetry's GenAI semantic conventions make
message content opt-in — `gen_ai.input.messages` and `gen_ai.output.messages`
are gated behind an experimental opt-in flag, and most vendor instrumentation
truncates or omits them by default, because prompts are large and contain PII.
A default OTLP trace therefore carries model name, token counts and latency,
but not the prompt.

That is enough to *count* failures. It is not enough to *replay* one. Replay
requires reconstructing the exact model input; an episode missing its tool
schemas replays against a different input than production saw, which is worse
than not replaying at all, because it looks like it worked.

Since replay is Stage 1's gate and L2/L3's offline eval (`PLAN.md` §1.1),
fidelity is not optional. But requiring the SDK before any value is delivered
contradicts `PLAN.md` Stage 2's "delivers value in week one." Hence both, with
the gap made explicit rather than hidden — see §2.2.

**Sequencing.** OTLP receiver first — it is Stage 1's critical path (§4,
Task Sequence). The SDK is specified against what a real customer's OTLP
traffic turns out to be missing (§2.6), so it ships as a Stage 1 *exit*
deliverable, not a Stage 1 blocker. Batch import (§2.7) is conditional on a
specific design partner's existing tooling and is built per-vendor, on demand.

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

### 2.6 SDK — guaranteeing replay-required fields by construction

§2.1(B)'s summary, expanded. The SDK exists to close exactly the gap §2.1
names: default OTel capture is enough to count failures, not to replay them.
Its whole job is that every span it emits already satisfies every field §5.3
requires for `replayable` — there is no `observe_only` case for a call the SDK
wrapped, by construction.

**Shape.** A thin wrapper around the customer's LLM client (OpenAI-shaped
first, since that interface is what most agent frameworks proxy), plus a
session context manager. It does not reimplement transport: it configures a
standard `opentelemetry-sdk` `TracerProvider` with an OTLP/HTTP exporter
pointed at the same receiver endpoint as §2.1(A), so no new server-side code
is needed to accept it — it is a better-instrumented OTLP client, not a
second protocol.

**API surface, minimal:**

- `continual_sdk.init(endpoint=None, tenant=None)` — reads
  `OTEL_EXPORTER_OTLP_ENDPOINT` / a tenant token env var if not passed
  explicitly, mirroring §2.1(A)'s zero-config convention.
- `continual_sdk.session(session_id=None)` — a context manager. Every span
  emitted inside it carries `continual.session_id`, which is first in the
  trunk's own resolution precedence (§5.2) — so an SDK-wrapped call's session
  is never inferred, only ever explicit or generated once per conversation.
- `continual_sdk.wrap(client)` — returns a wrapped client. Each traced call
  emits one span carrying, unconditionally: `gen_ai.request.model`,
  `gen_ai.input.messages` and `gen_ai.output.messages` in full (no truncation
  — §5.3 treats truncation as absence), `gen_ai.request.temperature` /
  `top_p`, the tool definitions as presented, and tool call results verbatim.
  This list is exactly the §5.3 table; the SDK is defined as the thing that
  always supplies it.

**Language and sequencing.** Python first — it is what the exit-criteria list
in the implementation plan names. TypeScript is deferred until a design
partner's stack needs it; nothing in this design is Python-specific enough to
make that port hard later.

**Why it still ships after the trunk, not with it.** The SDK's own
requirements — which fields real instrumentation omits, in what proportion,
across which frameworks — are read off the `missing_fields` distribution
§2.2 makes every `observe_only` episode record. Building it before that data
exists means guessing at a spec instead of reading one off real traffic. That
argument is unchanged from §2.1; this section only fixes what gets built once
the data says to build it.

### 2.7 Batch import — one-time historical backfill

§2.1(C)'s summary, expanded. Some design partners already run an
observability tool — LangSmith, Braintrust, Arize — that has been capturing
full request/response content for months before Continual exists for them.
Waiting on OTLP traffic (§2.1(A)) or an SDK rollout (§2.6) to accumulate
replayable episodes throws that history away for no reason; it can be read
once and imported.

**Mechanism.** A CLI reads a vendor's export file and a **per-vendor
adapter** maps its records to `CanonicalSpan` — the exact same normalized
shape `normalize_otlp_json` produces from OTLP (Task 4). The imported batch
is then pushed through the identical validate → redact → raw-store write
path a live OTLP delivery uses (§2.1, §2.4). There is no separate storage
format, no separate materializer, and no separate replay-tier logic for
imported data: it becomes ordinary raw spans, and everything downstream
(assembly, tiering, the Stage 1 gate) cannot tell the difference. This is the
same principle §2.3 already commits to for late spans — the trunk has one
path from "spans exist" to "episode," and import is just another producer of
spans, not a parallel pipeline.

**Adapter interface:** `parse_export(path: Path) -> Iterator[CanonicalSpan]`,
one function per vendor. Same shape as the Stage 2 seams in §7 — a narrow,
swappable interface, because the number of vendors worth supporting is
unknown and each is a small, isolated addition.

**Provenance.** Imported spans carry
`continual.import.source = "batch:<vendor>"` in `resource_attributes`, so a
materialized episode — and the spot-check CLI (§6) — can always tell backfill
from live traffic. This matters because a backfilled episode's `replayable`
tier depends entirely on how complete the *source vendor's* capture was, not
on anything Continual controls; conflating the two in a spot-check would
misattribute a vendor's gaps to the trunk's own ingest.

**Scope, deliberately narrow.** This section specifies the harness — the CLI,
the shared write path, the adapter interface — as a generic, Stage-1-adjacent
capability. It does **not** pre-build adapters for every vendor. Per §2.1(C),
each vendor adapter is built for a specific design partner's actual export,
on demand — the same "ask before building" discipline as before, now aimed at
a defined seam instead of an open-ended idea.

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
  customer agent          design partner's
       │                  existing observability store
       ├── (A) existing OTel exporter ──┐   one env var, zero code
       │                                 │
       ├── (B) continual SDK ────────────┤   guaranteed content + session_id
       │                                 │
       │    (C) batch import ────────────┼───┐  one-time CLI load, §2.7
       │        (offline, not an agent   │   │  vendor export → CanonicalSpan
       │         code path)              │   │  (LangSmith / Braintrust / Arize)
       │                                 ▼   ▼
                              ┌──────────────────────┐
                              │  OTLP/HTTP receiver  │  stateless   (A), (B) only
                              │  POST /v1/traces     │
                              └──────────┬───────────┘
                                         │
                                    normalize          OTLP protobuf/JSON
                                         │             → canonical span dict
                                         │◀── (C) adapter output joins here,
                                         │        already a CanonicalSpan list
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
| SDK — building it now | Specified in §2.6 against real OTLP gaps; TypeScript specifically | Python: Stage 1 exit, week 2+. TypeScript: when a partner's stack needs it |
| Batch import — per-vendor adapters | The harness (CLI, shared write path) is Stage-1-adjacent and specified in §2.7; each vendor's `parse_export` is not pre-built | Per design partner, on demand — "ask before building" |
