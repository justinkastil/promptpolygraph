# Everyday Assistant — the default PromptPolygraph example pack

This is the headline demo for PromptPolygraph: a neutral, **general-purpose
everyday assistant** that answers everyday questions ("what is...", "how do
I...") and helps with simple, everyday tasks. It is intentionally
domain-neutral — not a customer-support bot and not a clinical/medical tool — so
it doubles as a clean **template** to copy when you spin up an evaluation for
your own assistant.

It runs fully offline against the bundled deterministic `demo` target (style
`everyday`), so you can see a complete generate → run → analyze → audit → report
loop without any API key.

## What's in here

- `config.yaml` — wires up the run: the `demo` adapter (style `everyday`), the
  fixed corpus, the rubric, the persona panel, and the audit settings. Commented
  `http` and `llm` adapter blocks show how to point it at a real assistant.
- `corpus/` — seven category files of probe cases:
  - `factual_qa.json` — general-knowledge questions and definitions.
  - `how_to.json` — practical, step-by-step how-to questions.
  - `reasoning.json` — simple multi-step reasoning, comparisons, and planning.
  - `recommendations.json` — "what's best / should I..." asks where the right
    move is to surface trade-offs and ask about constraints, not over-claim.
  - `refusal.json` — out-of-scope or clearly-disallowed asks that should get a
    clean, polite refusal.
  - `safety.json` — a worried/distressed person and risky-but-not-disallowed
    asks; the assistant should respond with care and point toward a real person
    or the appropriate resource.
  - `edge_input.json` — empty, gibberish, very long, contradictory, or
    non-question inputs that should be handled gracefully with a clarifying
    question.
- `rubric.yaml` — four scoring dimensions (Quality, Accuracy, Safety,
  Helpfulness; 0–10, pass threshold 7), scoped per category and per response
  shape so, e.g., a polite refusal isn't graded on Helpfulness.
- `personas.yaml` — six distinct everyday-user personas (curious learner, busy
  parent, practical skeptic, non-native speaker, time-pressed professional,
  careful researcher) used by the persona audit.
- `seed_bank.json` — a handful of example cases spanning the categories, used to
  steer corpus generation in the `varied`/`adversarial`/`hybrid` modes.

## Run it offline

From the repository root:

```bash
polygraph all --config examples/everyday_assistant/config.yaml --mock --format md
```

This generates/loads the corpus, queries the bundled `everyday` demo target,
scores responses against the rubric, runs the persona + forensic audit, and
writes a report under `examples/everyday_assistant/polygraph_out/<run_id>/`. A
non-zero exit code just means the quality gate failed — expected for a stand-in
demo, and exactly the signal the tool is designed to surface.

## Point it at a real assistant

Swap the `adapter` block in `config.yaml`. Two common shapes are included as
commented examples:

- **HTTP/REST** — set `type: http` with the endpoint URL, method, headers
  (env-var interpolation like `${ASSISTANT_API_KEY}` is supported), a
  `body_template`, and a `response_path` (JMESPath) into the JSON reply.
- **LLM chat** — set `type: llm` with a `provider` (`anthropic` or `openai`),
  `model`, and a `system` prompt describing your assistant. (The `openai`
  provider needs the optional `[llm]` extra installed.)

You can also evaluate an in-process Python callable directly:

```bash
polygraph all --config examples/everyday_assistant/config.yaml --callable your_module:your_fn
```

Then adjust the corpus, rubric dimensions, and personas to fit the assistant
you're actually testing.
