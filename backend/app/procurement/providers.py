"""Licensed search-provider adapters for market research.

Only search APIs that return results under the provider's licence are used. The application never
fetches or scrapes the result pages themselves: a price is captured only when it appears in the
text the provider returned (title / snippet / extracted content), and it is stored as a
candidate. Automatic verification requires an exact licensed structured/full-content offer; snippets alone cannot be auto-verified.

Credentials are read from environment variables (never stored in the database):
  CLPI_BRAVE_API_KEY   Brave Search API (https://api.search.brave.com)
  CLPI_TAVILY_API_KEY  Tavily Search API (https://api.tavily.com)
Microsoft retired the Bing Web Search API in August 2025, so no Bing adapter is provided.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from ..config import get_settings


class ProviderError(RuntimeError):
    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    provider: str
    extra: dict = field(default_factory=dict)


class Provider:
    name = "base"
    label = "Base"
    env_var = ""

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.transport = transport

    def api_key(self) -> str | None:
        return None

    def configured(self) -> bool:
        return bool(self.api_key())

    def search(self, query: str, *, count: int, country: str) -> list[SearchHit]:  # pragma: no cover
        raise NotImplementedError

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=get_settings().research_http_timeout, transport=self.transport,
                            follow_redirects=False, headers={"User-Agent": "CasterlyPricingIntelligence/1.0"})

    @staticmethod
    def _raise_for(resp: httpx.Response, name: str) -> None:
        if resp.status_code == 200:
            return
        retry = resp.status_code == 429 or resp.status_code >= 500
        if resp.status_code in (401, 403):
            raise ProviderError(f"{name} rejected the API key (HTTP {resp.status_code})", retryable=False)
        raise ProviderError(f"{name} returned HTTP {resp.status_code}", retryable=retry)


class BraveProvider(Provider):
    name, label, env_var = "brave", "Brave Search API", "CLPI_BRAVE_API_KEY"
    URL = "https://api.search.brave.com/res/v1/web/search"

    def api_key(self) -> str | None:
        return get_settings().brave_api_key

    def search(self, query: str, *, count: int, country: str) -> list[SearchHit]:
        try:
            with self._client() as c:
                resp = c.get(self.URL, params={"q": query, "count": count, "country": country.upper(),
                                               "search_lang": "en", "extra_snippets": "true"},
                             headers={"Accept": "application/json", "X-Subscription-Token": self.api_key() or ""})
        except httpx.HTTPError as e:
            raise ProviderError(f"Brave request failed: {type(e).__name__}", retryable=True) from e
        self._raise_for(resp, "Brave")
        try:
            data = resp.json()
        except ValueError as e:
            raise ProviderError("Brave returned invalid JSON", retryable=True) from e
        if not isinstance(data, dict) or not isinstance(data.get("web", {}), dict):
            raise ProviderError("Brave response shape is invalid", retryable=True)
        results = (data.get("web") or {}).get("results", [])
        if not isinstance(results, list):
            raise ProviderError("Brave results must be an array", retryable=True)
        out = []
        for r in results:
            if not isinstance(r, dict) or not r.get("url"):
                continue
            snippets = [str(r.get("description") or "")] + [s for s in (r.get("extra_snippets") or []) if isinstance(s, str)]
            out.append(SearchHit(title=str(r.get("title") or "")[:500], url=str(r["url"])[:2000],
                                 snippet=" … ".join(snippets)[:4000], provider=self.name,
                                 extra={"age": r.get("age"), "page_age": r.get("page_age"), "product": r.get("product"), "schemas": r.get("schemas")}))
        return out


class TavilyProvider(Provider):
    name, label, env_var = "tavily", "Tavily Search API", "CLPI_TAVILY_API_KEY"
    URL = "https://api.tavily.com/search"

    def api_key(self) -> str | None:
        return get_settings().tavily_api_key

    def search(self, query: str, *, count: int, country: str) -> list[SearchHit]:
        body = {"query": query, "max_results": count, "search_depth": "basic", "include_answer": False, "include_raw_content": "text", "include_published_date": True}
        if country.upper() == "IN":
            body["country"] = "india"
        try:
            with self._client() as c:
                resp = c.post(self.URL, json=body, headers={"Authorization": f"Bearer {self.api_key() or ''}"})
        except httpx.HTTPError as e:
            raise ProviderError(f"Tavily request failed: {type(e).__name__}", retryable=True) from e
        self._raise_for(resp, "Tavily")
        try:
            data = resp.json()
        except ValueError as e:
            raise ProviderError("Tavily returned invalid JSON", retryable=True) from e
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise ProviderError("Tavily response shape is invalid", retryable=True)
        out = []
        for r in data.get("results") or []:
            if not isinstance(r, dict) or not r.get("url"):
                continue
            out.append(SearchHit(title=str(r.get("title") or "")[:500], url=str(r["url"])[:2000],
                                 snippet=str(r.get("content") or "")[:4000], provider=self.name,
                                 extra={"published_date": r.get("published_date"), "raw_content": str(r.get("raw_content") or "")[:50000]}))
        return out


PROVIDERS: dict[str, type[Provider]] = {"brave": BraveProvider, "tavily": TavilyProvider}


def get_provider(name: str, transport: httpx.BaseTransport | None = None) -> Provider:
    cls = PROVIDERS.get(name)
    if cls is None:
        raise ProviderError(f"Unknown research provider '{name}'", retryable=False)
    return cls(transport)


def status() -> list[dict]:
    out = []
    for name, cls in PROVIDERS.items():
        p = cls()
        out.append({"name": name, "label": p.label, "configured": p.configured(), "env_var": p.env_var,
                    "note": None if p.configured() else f"Set {p.env_var} on the server to enable live research."})
    out.append({"name": "bing", "label": "Bing Web Search API", "configured": False, "env_var": None,
                "note": "Retired by Microsoft in August 2025; not supported."})
    return out


def default_provider() -> str | None:
    s = get_settings()
    if s.research_provider and s.research_provider in PROVIDERS and get_provider(s.research_provider).configured():
        return s.research_provider
    for name in PROVIDERS:
        if get_provider(name).configured():
            return name
    return None


# --------------------------------------------------------------------------- query generation

def queries_for(category: str, spec: dict, label: str, n: int) -> list[str]:
    q: list[str] = []
    if category == "server_cpu":
        model = spec.get("model") or label
        vendor = spec.get("vendor") or ""
        q.append(f"{vendor} {model} used refurbished processor India price")
        q.append(f"{model} {spec.get('sspec') or ''} server CPU price India".replace("  ", " "))
        q.append(f"{model} processor wholesale lot India")
    elif category == "server_ram":
        mt = spec.get("module_type") or "ECC"
        mfr = spec.get("manufacturer") or ""
        q.append(f"{mfr} {spec.get('capacity_gb')}GB {spec.get('ddr')} {spec.get('speed_mts')} ECC {mt} used server RAM India price"
                 .strip())
        if spec.get("part_number"):
            q.append(f"{spec['part_number']} price India")
        q.append(f"{spec.get('capacity_gb')}GB {spec.get('ddr')} {spec.get('speed_mts')} {mt} refurbished server memory India")
    else:
        brand = (spec.get("brand") or "").title()
        model = spec.get("model_text") or spec.get("model") or label
        cfg = " ".join(x for x in [spec.get("cpu") or spec.get("apple_chip") or
                                   (f"{spec['cpu_generation']}th gen" if spec.get("cpu_generation") else None),
                                   f"{spec['ram_gb']}GB" if spec.get("ram_gb") else None,
                                   f"{spec['storage_gb']}GB" if spec.get("storage_gb") else None] if x)
        kind = {"smartphone": "phone", "tablet": "tablet", "monitor": "monitor", "desktop": "desktop",
                "docking_station": "docking station"}.get(category, "laptop")
        q.append(f"{brand} {model} {cfg} refurbished India price".replace("  ", " ").strip())
        q.append(f"{brand} {model} used {kind} buyback wholesale India".replace("  ", " ").strip())
        q.append(f"{brand} {model} {cfg} second hand price India".replace("  ", " ").strip())
    seen, out = set(), []
    for s in q:
        s = " ".join(s.split())
        if s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:n]
