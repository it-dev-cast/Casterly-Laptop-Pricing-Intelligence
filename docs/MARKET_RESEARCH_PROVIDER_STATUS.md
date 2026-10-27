# Current status update

Tavily is configured and eight real requests succeeded. Four public test cases returned no sufficiently confirmed exact offers; prices remain review items. See MARKET_LIVE_RESEARCH_RESULTS.json. Historical fallback is now configured in the running local application.

# Market research provider status

Checked 27 October 2026. **Actual live pricing verification is BLOCKED.** Neither server-side Brave nor Tavily credentials are configured in the project environment. No key was fabricated, requested in chat, exposed, or embedded.

| Real case required | Actual HTTP requests | Genuine observed price | Result |
|---|---:|---|---|
| Dell Latitude business laptop | 0 | None | BLOCKED: API key required |
| Samsung Galaxy A54 smartphone | 0 | None | BLOCKED: API key required |
| Intel Xeon Gold 6130 | 0 | None | BLOCKED: API key required |
| DDR4 ECC RAM | 0 | None | BLOCKED: API key required |

`scripts/verify_live_research.py` was actually executed. `docs/MARKET_LIVE_RESEARCH_RESULTS.json` contains four blocked cases and zero live requests. Once credentials are configured, run from backend: `python ../scripts/verify_live_research.py`. It uses real HTTP only, public hardware identities and no customer workbook data. It records provider success/failure, queries, genuine returned URLs/titles, candidate vs confirmed price, condition, source/research timestamps, deterministic calculation and recommendation. Empty/unconfirmed results remain review items. This script does not write to production pricing tables.

## Adapters and validation
- Brave: HTTPS GET to `https://api.search.brave.com/res/v1/web/search`; `X-Subscription-Token`; country/search language/count; description, extra snippets and structured product/schema data.
- Tavily: HTTPS POST to `https://api.tavily.com/search`; bearer key; Indian country preference, raw licensed content and publication date requested. No answer/LLM price generation.
- HTTP 401/403 are nonretryable for that provider; 429/5xx and transport/JSON/shape failures are retryable. Existing bounded attempt count, concurrency and backoff are policy-controlled. Alternative configured providers are tried when primary authentication, results or confirmed offers are inadequate. Results from each actual provider retain that provider's identity.
- Result pages are never directly scraped. Source URLs are evidence, not retrieval instructions. Only an authorized local catalog/feed can enter through the catalog path.
- Search candidates and rejected comparisons retain reasons and technical match metadata. An INR amount in a snippet does not prove a valid product offer. Unknown source dates remain unknown and cause provisional recommendations, not fabricated freshness.

Adapter behavior is verified with explicitly simulated HTTP transports: fallback after a Brave authentication error, Tavily confirmed-content response, malformed payloads, timeouts, bounded failure retry, cancellation, candidate verification and cache reuse. These tests are **not** actual live-provider verification.

## Primary documentation inspected
- [Brave Search API reference](https://api-dashboard.search.brave.com/api-reference/web/search/get): authentication, parameters, result metadata and structured product fields.
- [Tavily Search API reference](https://docs.tavily.com/documentation/api-reference/endpoint/search): bearer authentication, raw-content/publication-date options and result format.

No approved vendor feed was configured in the supplied environment. Candidate source domains already in the application are not claimed as working vendor APIs. The optional approved local catalog path is implemented and tested with synthetic catalog records; vendor authorization and real catalog contents remain a one-time external setup.
