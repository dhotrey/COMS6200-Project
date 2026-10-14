# Decision: OpenAI via Cloudflare AI Gateway

Date: 27 August 2026
Status: **Accepted and implemented.**
The `agent/` application routes OpenAI Responses and Decisions requests through
the provider-specific Cloudflare gateway endpoint, using BYOK and a local
gateway token.

## Context

The project uses an OpenAI tool-calling diagnosis agent and automated semantic
judge. The team needs a controlled path for API
calls that supports visibility and spend controls without embedding secrets in
the repository.

## Decision

Diagnosis and optional explanations use the OpenAI Responses API; automatic
four-level grading uses the OpenAI Decisions API (`gpt-6-luna`). Both use
**Cloudflare AI Gateway**:

```
LLM Agent / Semantic Judge
           |
           | Responses / Decisions
           v
 Cloudflare AI Gateway
           |
           v
       OpenAI API
```

Cloudflare AI Gateway is intended to provide:

- request analytics
- token usage visibility
- latency visibility
- error monitoring
- cost monitoring
- rate / spend controls where configured

## Experiment policy — caching

| Mode | Caching |
| --- | --- |
| Development / smoke testing | Optional (may use gateway caching) |
| Repeated experimental trials | Gateway response caching bypassed |

The completed sweep bypassed gateway response caching with `cf-aig-skip-cache`,
disabled provider storage with `store=false`, and left provider prompt caching
on. Cached input tokens were recorded. Each trial used a new conversation after
a network restart.

The completed comparison is `evidence/experiments/sweep/sweep-2026-10/`: the
scripted baseline and six models, 525 final trials. The earlier protocol-v1
runner, which pins `gpt-5.6-sol` at effort `medium` on `main6s8h` only, was not
the collected dataset and remains disarmed.

## Secrets (M6 onwards)

Server-side secrets will live only in:

`~/COMS6200-Project/.env`

with mode `0600`, ignored by Git. Placeholders only in `.env.example`.
Do not commit real `OPENAI_API_KEY` or Cloudflare tokens.

## Non-goals for this decision record

- Do not implement the LLM agent here.
- Do not configure Cloudflare runtime here.
- Do not store or transmit the OpenAI API key as part of M5B.

## Final implementation

See `agent/README.md` for actual configuration. The root `.env.example` lists
gateway variables; the OpenAI key stays in Cloudflare BYOK. Gateway response
caching is bypassed. The application includes conversational output, automatic
Decisions grading, Cloudflare D1 history, Logfire and per-call metrics. D1 uses
a separate account API token with D1 Write access; the local SQLite history was
not migrated. The completed 525-trial sweep was graded through this Decisions
path, and its stored results are preserved rather than regraded. Artificial tool
latency must remain disabled for timing measurements.
