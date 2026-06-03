# Clinical-trials domain pack

A self-contained PromptPolygraph content pack that tailors the harness to
evaluating a **clinical trial protocol digitalization assistant** — a tool that
helps trial professionals author, structure, and validate clinical trial
protocol documents.

The system under test here is a **document/protocol assistant for trial
professionals** (medical writers, clinical scientists, data managers,
regulatory affairs, biostatisticians, clinical operations, pharmacovigilance) —
**not** a patient-facing medical-advice bot. Probes about protocol structure,
ICH-GCP / ICH E6(R2) / E8(R1), FDA/EMA expectations, endpoints/estimands,
schedules of assessments, SAE reporting, and CRF/SDTM data structuring are the
intended subject matter. Out-of-scope asks (fabricating data, individualized
patient treatment advice, bypassing regulatory steps, inventing citations) are
expected to be refused or escalated.

## What's in the pack

| File | Purpose |
|------|---------|
| `personas.yaml` | An 8-persona panel of clinical-trials professionals who judge the assistant. |
| `rubric.yaml` | 5 protocol-quality dimensions (Clinical_Accuracy, Regulatory_Compliance, Completeness, Clarity_Consistency, Safety_Appropriateness), 0–10, threshold 7, with per-category applicability and per-shape blocks. |
| `corpus/` | 10 category files (~6–8 cases each) of realistic prompts trial professionals would send such a tool. |
| `config.yaml` | Wires the pack together: demo adapter, fixed corpus, the rubric, the persona panel, and an audit pass. |

### Corpus categories

`protocol_authoring`, `eligibility_criteria`, `schedule_of_assessments`,
`endpoints_estimands`, `statistical_considerations`, `safety_reporting`,
`regulatory_compliance`, `data_management`, `edge_input`, `refusal_safety`.

## Run it (offline, no API key)

From the repository root:

```
polygraph all --config examples/clinical_trials/config.yaml --mock
```

This runs the full pipeline (run → analyze → audit → report) against the
bundled deterministic **demo** target with mock judging, and writes a report
under `examples/clinical_trials/polygraph_out/<run_id>/`. To get a Markdown
report:

```
polygraph all --config examples/clinical_trials/config.yaml --mock --format md
```

A non-zero exit code simply means the quality gate failed for the demo target —
that is expected, since the demo is a deterministic stand-in, not a real
protocol assistant.

## Point it at a real protocol assistant

Edit the `adapter` block in `config.yaml`:

- **In-process callable** — keep `type: demo` out and pass your function on the
  CLI: `polygraph all --config examples/clinical_trials/config.yaml --callable my_module:my_fn`
- **HTTP/REST** — uncomment the `type: http` block and set `url`, headers, the
  request `body_template`, and the `response_path` (JMESPath) into your API's
  JSON.
- **LLM chat** — uncomment the `type: llm` block, set the provider/model, and
  supply a `system` prompt that frames the assistant as a protocol-authoring
  tool (no patient advice, no fabricated data or citations).

Then drop `--mock` to use a real judge model for the rubric scoring and the
persona audit.
