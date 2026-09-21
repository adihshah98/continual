**Input and output:** you send a block of text or JSON as the "state," plus a schema of typed questions. Each question is a yes/no (Noul), a pick from options you list (Choice), or a rating on a scale you define (Score). All questions are evaluated in parallel and come back as structured answers with calibrated confidence, with no string generation and nothing to parse.

---

How it works

### Why it's fast

The speed comes almost entirely from removing the step that dominates LLM latency: token-by-token decoding.

**How an LLM spends its time.** It reads your input in one parallel pass, which is fast. Then it generates the answer one token at a time, and each token needs a full pass through the model that can't start until the previous token exists. That loop is memory-bandwidth bound on GPUs, so even a few lines of JSON can take hundreds of milliseconds to seconds. Reasoning models add a long hidden chain of thought before the answer, which is where the 10–40 second latencies in the benchmark come from. [lilting channel](https://lilting.ch/en/articles/typesafe-ai-jev-system-one-model)

**What Jev does instead.** TypeSafe says Jev outputs all probabilities in parallel instead of autoregressively generating by token. It reads the state once, then produces the probability for every answer option to every question in the same pass. There's no generation loop, no chain of thought, and nothing to parse afterward. One independent analysis describes it as behaving more like a parallel classification head that maps an encoder-style internal representation directly onto a predefined schema. That's the reviewer's characterization, not a TypeSafe statement. Think of the difference as an LLM writing out its answer word by word versus a model reading the input and reading the answer off a dial

**Calibration is trained in**, since the output is directly a probability distribution over your options. RLCD then trains those probabilities to match actual accuracy.

---



It's for high-volume, repeated decisions where the possible answers are known in advance. It's the wrong tool for chat, code generation, or anything needing a written explanation. Examples from the LangChain post and others: 

- Ticket and email triage, urgency scoring, and moderation.
- Model routing, where it picks a cheap or expensive LLM per request.
- "Auto mode" guardrails that gate risky tool calls before they execute.
- Cheap per-step decisions in agent loops, such as browser agents.
- Per-row decisions over huge datasets, where LLM cost is prohibitive.
- Real-time reactive loops where a multi-second LLM call is a non-starter.



Eg

- 🧹 Instant compaction: score every tool call and drop the junk. 
  - **What it is.** Replace the summarization prompt that every coding agent runs at the context ceiling with a Jev pass that scores each tool call for relevance and deletes the dead weight.
- **Model Routing: What it is.** Put Jev in front of your model fleet and let it pick which brain handles each request, with the probabilities left in agent state so you can audit the choice.
- 🔎 RAG precision: retrieve as usual, then delete what does not belong
  - **What it is.** Keep your retriever exactly as it is. Run Jev over every chunk it returns with one yes-or-no question, and drop the ones that fail.
- 🗂️ Map-reduce over documents: 777 judgments for a quarter of a cent
  - **What it is.** One set of questions, every document, all at once. The workload that has been economically impossible with frontier models and mediocre with classical classifiers.

---



Where it can be used

- **Candidate for the weak-tier filter and flow segmentation.** Stage 1 needs a cheap judge running over every stored episode ("did the user retry?", "was this resolved?", "which flow is this?"). That is Jev's sweet spot on cost and latency. Calibrated probabilities would also give you better thresholds and confidence-based stratification for the adjudication samples.

