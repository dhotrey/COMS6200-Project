# Decision: OpenAI via Cloudflare AI Gateway (planned for M6)

Date: 27 August 2026
Status: **Accepted; starter implemented** — live gateway verification pending.
The `agent/` starter now routes Responses requests through the provider-specific
Cloudflare gateway endpoint, using BYOK and a local gateway token.

## Context

After Fault Catalogue v1 is complete, the project will add an OpenAI
tool-calling diagnosis agent (M6). The team needs a controlled path for API
calls that supports visibility and spend controls without embedding secrets in
the repository.

## Decision

LLM traffic will use the OpenAI Responses API **through Cloudflare AI Gateway**:

```
LLM Agent
    |
    | OpenAI Responses API
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
| Formal experimental episodes | **Must disable / bypass response caching** |

Reason: repeated research trials must represent independent model executions,
not cached responses.

Exact model identifiers and reasoning configurations will be frozen separately
before formal LLM experiments. The team currently intends to evaluate the
GPT-5.6 family and may optionally compare reasoning configurations; that
comparison is **secondary**. The primary research comparison remains:

- LLM troubleshooting **vs**
- deterministic scripted troubleshooting baseline

## Secrets (M6 onwards)

Server-side secrets will live only in:

`~/COMS6200-Project/.env`

with mode `0600`, ignored by Git. Placeholders only in `.env.example`.
Do not commit real `OPENAI_API_KEY` or Cloudflare tokens.

## Non-goals for this decision record

- Do not implement the LLM agent here.
- Do not configure Cloudflare runtime here.
- Do not store or transmit the OpenAI API key as part of M5B.

## Starter implementation (10 September 2026)

See `agent/README.md` for actual configuration. The root `.env.example` lists
gateway variables; the OpenAI key stays in Cloudflare BYOK. Gateway response
caching is bypassed. The starter adds conversational output, Cloudflare D1
history, Logfire and per-call metrics; formal experiments and structured scoring
remain out of scope. D1 uses a separate account API token with D1 Write access;
the local SQLite history was not migrated. Artificial tool latency defaults to
1–10 seconds and must be disabled for actual timing measurements.
