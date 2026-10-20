# FreeLLMAPI integration

## Decision

ResearchAgentLab supports two separate routes:

- **Simple Mode** is an in-process RAL router over the signed-in user's own Gemini and Groq keys. It requires no separately installed gateway.
- **Advanced Mode** integrates FreeLLMAPI as an optional user-owned OpenAI-compatible gateway, not as a shared multi-user credential pool.

The Advanced Mode integration contract is pinned to FreeLLMAPI `v0.13.4` (`716948f`). FreeLLMAPI documents itself as local-first and single-user, does not provide multi-tenant authentication, and warns against treating the project as a production service. A shared RAL gateway would therefore collapse user credential and quota boundaries. It is intentionally not implemented. Simple Mode does not change that decision: it decrypts only the current user's direct-provider keys at request construction and never copies them into FreeLLMAPI or a global pool.

## Simple Mode

Select `Automatic (your Gemini + Groq keys)` in **Models and cost** after saving either or both keys under **Your API keys**. The bounded policies are:

- `simple:balanced`: alternate the first provider between calls, then use the other as a bounded fallback;
- `simple:gemini-first`: Gemini, then Groq;
- `simple:groq-first`: Groq, then Gemini.

Each route uses a fixed configured model (`GEMINI_MODEL` or `GROQ_MODEL`). RAL attempts each configured provider at most once inside one routing attempt, preserves failure categories without provider response text, and records the actual successful provider/model plus fallback count and trail. Existing outer retry bounds still apply; no unbounded fallback chain is introduced.

Simple Mode is for exploratory and ordinary workflow inference where model substitution is acceptable. It must not be selected for protocol-frozen, confirmatory, or safety-evaluation calls that require an exact model identity. Those runs must continue to select an exact direct provider/model, or an exact Advanced Mode request with verified route evidence.

Free-tier access is controlled by each provider account. RAL does not create credits, detect whether billing is enabled, or guarantee that a model remains free. It does not silently add paid providers or use the operator's key as a Simple Mode fallback.

Usage logs apply the published paid-tier token rates for the configured Gemini and Groq models as a conservative cost-equivalent estimate. A free-tier account may be charged `$0`, but RAL cannot infer the account's billing tier from an API response. The estimate is therefore a guardrail, not an invoice or a promise of free usage.

## Advanced Mode trust boundary

Each RAL user may save exactly one FreeLLMAPI configuration:

- gateway base URL;
- unified bearer token;
- selected model or routing policy.

The URL and token are serialized together and encrypted with the same AES-GCM, user/provider-bound storage used for direct BYOK credentials. They are never returned to another user, logged, or placed in a URL. Removing the credential removes both values.

Hosted RAL disables FreeLLMAPI until the operator sets `FREELLMAPI_ALLOWED_HOSTS`. It then accepts only an allowlisted public HTTPS gateway origin, optionally ending in `/v1`. It rejects URL credentials, query strings, fragments, non-`/v1` paths, unlisted hosts, and addresses resolving to loopback, private, link-local, reserved, multicast, or unspecified networks. A local/self-hosted RAL installation may use `http://localhost:3001/v1`, matching FreeLLMAPI's local-first design.

The mandatory allowlist plus DNS validation narrows SSRF exposure but cannot make a user-operated public service trustworthy. Operators should use dedicated gateway hostnames and an authenticated egress layer rather than allow broad shared domains.

## Advanced Mode request path

FreeLLMAPI is called only through `models/providers.py`:

```text
signed-in user
  -> encrypted per-user gateway credential
  -> APIModel policy/retry boundary
  -> FreeLLMAPIProvider
  -> POST {base_url}/chat/completions
```

The adapter uses the OpenAI SDK's raw-response surface so that it can retain:

- selected provider/model or virtual route;
- actual provider/model from `X-Routed-Via`;
- gateway failover count from `X-Fallback-Attempts`;
- redacted failover trail from `X-Fallback-Trail`;
- RAL retry count;
- input/output token usage;
- sanitized operational failures.

Successful-call provenance is stored in `api_usage_log`; failed/retried provider events are stored separately in `provider_route_events`. Gateway cost is marked unknown and recorded as `$0` rather than fabricating a price. FreeLLMAPI can contain paid keys, so `$0` is not a claim that the upstream call was free.

## Scientific routing rule

`auto`, `auto:*`, and `fusion` are explicitly variable routing policies. They are suitable only where model substitution is allowed and the actual route is retained.

Any other model string is treated as an exact-model request. The response is rejected if `X-Routed-Via` is missing or identifies a different model. This failure does not fall back to a local model or another provider. Frozen/confirmatory work must use an exact model and retain the resulting route evidence; automatic routing is not a substitute for a frozen model identity.

## Advanced Mode UI and API

In **Settings -> Your API keys**:

1. choose `FreeLLMAPI (your gateway)`;
2. enter the gateway address and unified token;
3. save;
4. select FreeLLMAPI in **Models and cost**;
5. choose an explicit model or an allowed virtual route.

`GET /api/freellmapi/models` reads `/v1/models` using only the current user's stored gateway credential. No server-global FreeLLMAPI token or upstream key pool exists.

## Deployment status

The adapters, direct-key and gateway credential isolation, Simple Mode fallback, URL policy, routing provenance, exact-model fail-closed behavior, migrations, API surface, and UI are covered by local mocked tests. No live FreeLLMAPI gateway or upstream provider request was made during implementation, because no user-owned gateway credential was available. Simple Mode likewise has not yet made a live provider request.

A production deployment remains conditional on one bounded canary against a user-owned, access-controlled FreeLLMAPI `v0.13.4` instance. The canary should request one non-sensitive prompt, verify `/v1/models`, verify `X-Routed-Via` and fallback headers, confirm the persisted route row, then stop. Do not deploy a shared public gateway for unrelated users.

## Provider eligibility (reviewed 2026-10-18)

RAL does not enable or register upstream providers. The user configures them in their own FreeLLMAPI instance and remains responsible for the provider/model terms. Until a provider-specific live canary and terms review are recorded, hosted use remains conditional or unverified.

| Provider | Status for hosted BYOK | Basis |
| --- | --- | --- |
| Google Gemini | Conditionally suitable | An official free tier exists, but its content may be used to improve Google products; paid-tier handling differs. Do not send confidential/unpublished material through the free tier without informed user choice. |
| Groq | Conditionally suitable | An official free plan and published limits exist. The current services agreement governs business/developer use and prohibits resale/distribution except as approved; the user's own credential must not be pooled or resold. |
| OpenRouter | Conditionally suitable | Free models have low quotas and are explicitly described as unsuitable for production. Model-specific terms flow through to users, and paid/BYOK behavior can incur fees. Paid routes require separate explicit opt-in. |
| Cerebras | Unverified | No sufficiently clear current official free-tier/commercial-production entitlement was established in this review. Keep disabled by default for hosted use. |
| Mistral | Unverified | No sufficiently clear current official free-tier/commercial-production entitlement was established in this review. Keep disabled by default for hosted use. |

Sources: [Gemini pricing/data use](https://ai.google.dev/gemini-api/docs/pricing), [Groq billing](https://console.groq.com/docs/billing-faqs), [Groq terms](https://console.groq.com/docs/legal/services-agreement), [OpenRouter pricing and limits](https://openrouter.ai/pricing), and [OpenRouter terms](https://openrouter.ai/terms).

## Capability boundary

RAL currently uses non-streaming chat completions. Its structured tasks validate returned text with RAL's existing parsers and schemas; it does not trust a catalog label as proof of JSON/tool support. Tool calling is not part of the current RAL provider contract, so this adapter does not claim or expose it. `/v1/models` proves only that the gateway lists a model, not that the configured key is healthy or that the model meets a research stage's context, schema, or reliability requirements.

## Upstream references

- [README and operating scope](https://github.com/tashfeenahmed/freellmapi/blob/v0.13.4/README.md)
- [Security model](https://github.com/tashfeenahmed/freellmapi/blob/v0.13.4/SECURITY.md)
- [REST API and routing headers](https://github.com/tashfeenahmed/freellmapi/blob/v0.13.4/docs/en/api/01-rest-api.md)
- [v0.13.4 release](https://github.com/tashfeenahmed/freellmapi/releases/tag/v0.13.4)
