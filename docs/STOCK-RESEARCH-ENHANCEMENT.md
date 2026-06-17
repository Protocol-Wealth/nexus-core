# Stock-Idea Analysis — Capability Review & Enhancement Scaffold

> Status: **planning / scoping** (no production code shipped by this doc).
> Audience: nexus-core maintainers + the Claude Code / Claude.ai analyst workflow.
> Companion runnable artifact: [`examples/stock_research_agent.py`](../examples/stock_research_agent.py).

This document answers one question: **what does it take to let Claude Code (or
Claude.ai), talking to the hosted `nexusmcp.site/mcp` server, evaluate an
individual stock idea end-to-end** — the way an analyst would when pressure-
testing a name surfaced by an outside research service (CML Pro and the like)?

It is a review of the current surface, a gap analysis against the **MBOUM** and
**MarketStack** API keys (plus the keyless **SEC EDGAR** path) the engine
already holds, an architecture for the missing capabilities, the Claude Code
connection + analysis playbook that works **today**, and a scoped plan for a
CML-vs-EMF **backtest harness** (the follow-on). Every recommendation here was
adversarially verified for compliance, repo-boundary, and feasibility; the
**gates** those checks surfaced are in [§7](#7-gates--sequencing) and are
load-bearing — read them before writing any code.

---

## 1. What an AI analyst can do with nexus-core today

Talking to `nexusmcp.site/mcp`, an AI client can do **five** things on a US
equity. The regime/score lens is the strongest of them; everything else is thin.

| # | Capability | Tools | Shape today |
|---|-----------|-------|-------------|
| 1 | **Macro regime context** | `current_regime`, `regime_signals`, `get_economic_series` | Live 5-state EMF regime (GROWTH / TRANSITION / HARD_ASSET / DEFLATION / REPRESSION) + confidence + days-in-regime + per-signal explainability (Gold/SPX anchor, real rates, DXY, VIX-with-hysteresis, BBB spreads, 30Y futures, curve); FRED point reads. |
| 2 | **EMF durability score** | `score_asset` | The primary equity-research artifact: the 8-check framework (CROIC, Piotroski F-Score, Hurst, Lambda decay, Perez phase, Regime alignment, Sector tailwind, ASAN) → a confidence **tier** (HIGH / MODERATE / LOW / BELOW / NOT_APPLICABLE) + per-check pass/fail/value/threshold. Internally pulls SEC EDGAR companyfacts + price history, but surfaces only the verdicts, not the statements. |
| 3 | **Price** | `get_quote`, `get_quotes`, `get_price_history` | `get_quote` is **price-only** (last price + a freshness label — no change/%/volume/market-cap/52w/bid-ask). `get_price_history` is **daily OHLCV only**. |
| 4 | **Options** | `option_price`, `covered_call`, `cash_secured_put`, `collar` | **Black-Scholes illustrations only**, on a vol estimated from ~90d of historical stdev. **No real equity chain / strikes / OI / IV.** (The full real-chain + IV/skew/term-structure/MTM suite exists but is **crypto-only**, via 13 Deribit tools.) |
| 5 | **Portfolio/planning math** | 23 planning tools | Monte Carlo, `optimize_allocation`, `correlation_matrix`, `risk_metrics`, `portfolio_xray` — over de-identified **asset-class** portfolios, not equity-level holdings. |

**Net:** the analyst gets a regime-aware, graded durability assessment plus a bare
price. A research-service pick can be run through the **EMF quality + regime
lens**, but cannot be checked against **valuation, sell-side consensus, forward
estimates, real options positioning, ownership flows, or sentiment** — exactly the
legs an outside growth/quant service leans on.

---

## 2. The data we already pay for but don't use

The engine holds keys for **MBOUM** and **MarketStack** (plus keyless **SEC
EDGAR**). Today the keyed market providers are squeezed through a 2-method
provider abstraction (`MarketDataProvider`: `get_quote` + `get_price_history`).

> **FMP/FinanceToolkit is retired** (2026-06-17). An earlier draft of this plan
> proposed an `FmpResearchData` impl over the FinanceToolkit adapter; that vendor
> is no longer used and the `financials/` module + `[financials]` extra were
> removed. The supported research sources are **MBOUM** (primary), **MarketStack**
> (EOD + corporate actions), **SEC EDGAR** (keyless fundamentals/insider), and
> other free/already-keyed feeds (FRED, etc.). Wherever this doc once said "FMP,"
> read MBOUM + EDGAR.

- **MBOUM** (`MBOUM_API_KEY`) — proxies Yahoo Finance and exposes a *rich*
  surface: `…/stock/modules` (statistics, key-statistics, financial-data,
  recommendation-trend, upgrade-downgrade-history, insider-transactions,
  institutional-holdings, profile), `…/stock/financials`, `…/analyst-ratings`,
  `…/price-targets`, `…/markets/options` (chain **with greeks + IV**),
  `…/markets/screener`, `…/markets/news`, `…/markets/calendar/earnings`,
  `iv-rank-percentile` / `unusual-options-activity`, technical `indicators/*`.
  **nexus-core calls exactly two of these:** `/v1/markets/stock/quotes` and
  `/v2/markets/stock/history` — and the quote adapter even *discards*
  `marketCap`/`PE`/`52w` it already receives.
- **MarketStack** (`MARKETSTACK_API_KEY`) — EOD OHLCV + `…/dividends`,
  `…/splits`, `…/tickerinfo`, indices. Used only for `get_quote` +
  `get_price_history` (EOD). Its `dividends`/`splits` endpoints are what a
  total-return backtest needs.
- **SEC EDGAR** (keyless) — `score_asset` already fetches companyfacts (XBRL
  income/balance/cashflow) internally to compute CROIC + F-Score, and the
  `edgartools_wrapper` (coded, currently unimported) can read Form 4 / filings.
  This is the keyless fallback for `fundamentals_statements` + `insider_activity`
  — it answers with **zero API keys**, so those P0 surfaces don't depend on any
  vendor at all.

> ⚠️ **None of the MBOUM research endpoints above are exercised anywhere in the
> repo.** The only proven MBOUM calls are `/quotes` and `/history`, and even the
> existing provider's docstring warns its envelope shape is *inferred*. The
> endpoint paths, response shapes, field names, **and the operator's plan-tier
> entitlement** (financials/options/screener/13F are typically higher tiers) are
> **unconfirmed**. A one-shot **live-key probe of each endpoint is task #0** of any
> implementation — see [§7](#7-gates--sequencing).

---

## 3. Gap matrix (prioritized for stock-idea analysis)

`P0` = on the critical path for a fundamentals + quality + consensus + regime
brief and/or fixes the EMF score's own quality. `P1` = high-value buy-case leg.
`P2` = corroborating / secondary.

| Pri | Capability | Where the data lives | Why it matters |
|-----|-----------|----------------------|----------------|
| **P0** | **Fundamental statements as a tool** (revenue, margins, debt, FCF, EPS) | EDGAR (already fetched internally) · MBOUM `/financials` | `score_asset` consumes these (CROIC/F-Score) but never surfaces them. Lowest-cost P0 — EDGAR data is already in-process. |
| **P0** | **Valuation** (P/E, P/S, EV/EBITDA, div yield, DCF) | MBOUM key-statistics/financial-data · ratios computed from EDGAR statements | `score_asset` answers "is it durable?" never "is it cheap?". The whole growth-leader debate is valuation/expectations. |
| **P0** | **Analyst consensus** (EPS/rev estimates, price-target hi/lo/median, #analysts) | MBOUM `analyst-ratings`+`price-targets`+`recommendation-trend` | The "expectations" leg and the natural complement to the confidence tier (durability vs. street expectations). Absent today. |
| **P0** | **Populate ASAN Check 8 inputs** (market_cap, ROE, op-margin, rev-growth) | MBOUM financial-data/statistics modules | These fields are **read** by Check 8 (`structural_advantage.py`) but **never produced** by `build_fundamentals`, so for most non-SaaS large caps Check 8 → insufficient_data, degrading the very tier the workflow anchors on. Fixing the score's own quality is P0. |
| **P0** | **Real equity options chain** (strikes/expiries/OI/IV/greeks) | MBOUM `/v1/markets/options` | Current equity overlays are BS fictions on historical-stdev vol; a real chain also lets them use true IV. The quant/options heritage of outside services lives here. |
| **P1** | **Equity IV / vol skew / IV-rank / term structure / unusual activity** | MBOUM `iv-rank-percentile`, etc.; skew/term-structure computable via existing `engine/pricing/{skew,option_chain}.py` | The single biggest options signal — and the analytics already exist (fed only by Deribit/crypto today). |
| **P1** | **Analyst rating actions** (consensus grade, up/downgrade feed) | MBOUM `recommendation-trend`+`upgrade-downgrade-history` | Momentum-of-opinion; same source as P0 consensus, cheap to add alongside. |
| **P1** | **Earnings calendar + surprise history** (beat/miss, next date) | MBOUM earnings module + `calendar/earnings` | Forward catalyst dates + beat/miss track record gate timing/conviction. |
| **P1** | **Equity screener / batch EMF ranking** | MBOUM `/screener` · compute (batch `score_asset`) | Turns nexus from a one-ticker checker into a universe filter / idea-sourcer. |
| **P1** | **News pipeline + FinBERT sentiment** | MBOUM `/news` → `ai/sentiment/finbert_wrapper.py` (real but **unwired**) | Zero sentiment/news/catalyst signal today; the FinBERT classifier just needs a news source piped in. |
| **P1** | **Richer quote** (day change/%, volume, mkt-cap, 52w, P/E, yield) | MBOUM `/quotes` envelope **already returns these; adapter discards them** | Cheapest possible win — the data already arrives and is thrown away. |
| **P1** | **Company profile / metadata** (description, sector/industry, share count) | MBOUM profile · MarketStack tickerinfo | Orientation + peer set; also supplies the share-count/market-cap Check 8 needs. |
| **P2** | Institutional 13F + insider/Congress trades | MBOUM institutional-holdings/insider modules · EDGAR Form 4/13F | Smart-money corroboration; not on the critical path. |
| **P2** | Short interest (days-to-cover, % of float) | MBOUM statistics module (dedicated endpoint 404s) | Crowding/squeeze risk; one-field add. |
| **P2** | Intraday / sub-daily history | MBOUM `/history` (1m..1h) — provider accepts `interval`, MCP hardcodes `1d` | Near-free unlock; low priority for a fundamentals brief. |
| **P2** | Dividends / corporate actions | MarketStack `/dividends`+`/splits` · MBOUM | Total-return + income context; **required for a fair backtest** (see §6). |
| **P2** | Non-XBRL fundamentals fallback (ETFs/foreign) | MBOUM / yfinance | Widens coverage beyond US-XBRL single stocks (already works). |
| **P2** | SEC filing text / Item 1A risk factors | EDGAR (`edgartools_wrapper.py`, coded, unimported) · MBOUM sec-filings | Qualitative deep-dive; heavier read-and-reason surface. |
| **P2** | Technical indicators (RSI/MACD/SMA as values) | MBOUM `indicators/*` · compute from history | Hurst already covers trend persistence; convenience add. |
| **P2** | Backtest harness (regime-conditioned / picks track-record) | compute (`planning/backtest` is `__init__`-only) | Needed to fair-score an outside service's calls — the follow-on; see §6. |

**Headline:** exposing any of this is a **code** change, not a config flag —
`MarketDataProvider` has no room for research data. The right seam (verified
against the repo) is a **new sibling `ResearchDataProvider` protocol**, modeled
exactly on the existing `MacroDataProvider`/FRED precedent (a second data domain
that got its own protocol rather than overloading `get_quote`).

---

## 4. Enhancement architecture (the equity-research vertical)

Add an equity-research vertical that **mirrors the existing macro/market verticals
exactly** and reuses, never duplicates, the engines.

### 4.1 Provider layer — `src/nexus_core/data/research.py` (+ subpackage)

A new `runtime_checkable` **`ResearchDataProvider`** protocol returning new
**pydantic-v2 boundary models** (never bolting fields onto `Quote`/`PriceBar`):

```python
class ResearchDataProvider(Protocol):
    def get_key_statistics(self, symbol: str) -> KeyStatistics | None: ...
    def get_fundamentals(self, symbol, *, period="annual", limit=5) -> FundamentalsStatements | None: ...
    def get_analyst_consensus(self, symbol: str) -> AnalystConsensus | None: ...
    def get_earnings_estimates(self, symbol: str) -> EarningsEstimates | None: ...
    def get_option_chain(self, symbol, *, expiry=None) -> EquityOptionChain | None: ...
    def get_iv_surface(self, symbol, *, target_days=30) -> EquityIvSurface | None: ...
    def screen(self, criteria: ScreenCriteria) -> list[ScreenResult]: ...
    def get_insider_activity(self, symbol, *, limit=50) -> InsiderActivity | None: ...
    def get_institutional_holders(self, symbol, *, limit=25) -> InstitutionalHolders | None: ...
    def get_company_news(self, symbol, *, limit=20) -> CompanyNews | None: ...
    def is_configured(self) -> bool: ...
```

Concrete impls follow the existing `data/market/` adapter shape (sync `httpx` via
`data/http.fetch_json`, `is_configured()` credential check, env-keyed):

- **`MboumResearchData`** — **primary** keyed impl; taps the unused MBOUM surface
  in §2 (statistics, financials, analyst-ratings, price-targets, options chain,
  screener, news, earnings, institutional/insider modules). This is the single
  source for the analyst/estimates/options/screener legs (no second vendor — FMP
  is retired).
- **`EdgarResearchData`** — **keyless** fundamentals + Form-4/13F fallback reusing
  `data/edgar/{fundamentals,edgartools_wrapper}` so `fundamentals`/`insider`
  still answer with **zero keys**. Also the source for the keyless P0 wins (§7).
- **`MarketStackResearchData`** (optional) — corporate actions (`dividends`/
  `splits`) + EOD where MBOUM is unavailable; mainly used by the backtest's
  total-return adapter, not the live research tools.
- **`CompositeResearchData`** / **`CachedResearchData`** — direct analogues of
  `data/market/{composite,cache}.py` (ordered per-method fallback EDGAR→MBOUM,
  raise-as-miss; TTL buckets: fundamentals ~6h, analyst ~1h, options ~5m).

### 4.2 MCP tools + HTTP routes

Ten single-purpose tools + one composite, registered via a
`_register_research_tools(mcp, research, …)` block guarded by `if research is not
None`, all `_RO_OPEN` (live upstream) except pure-compute option math (`_RO_CLOSED`),
every response through `_ok`/`_err` so `disclaimers.TERSE` attaches uniformly:

`analyst_consensus` · `earnings_estimates` · `fundamentals_statements` ·
`key_statistics` · `equity_option_chain` · `equity_iv_skew` · `screen_equities` ·
`insider_activity` · `institutional_holders` · `company_news` — plus the
highest-leverage **`stock_research_dossier(ticker)`**: wired exactly like
`score_asset` (injected context factory), fusing `current_regime` + the reused
`score_asset` 8-check + `key_statistics`/`fundamentals`/`analyst_consensus`/
`earnings_estimates`, with `composite.py`'s **per-section fallback** (a missing /
keyless section degrades to a null section named in `sections_unavailable`, never
raises — regime/score answer even with zero research keys).

REST twins land behind a `build_research_router(*, research)` factory wired in
`create_app()` next to `build_score_router` (`GET /api/research/{fundamentals,
key-statistics,analyst,estimates,options,options/{sym}/iv-skew,insiders,
institutional,news,screen,dossier}` — sync handlers, explicit `Cache-Control`,
**503 (not 500)** when the provider can't satisfy).

**Equity options reuse the engine, but it is *not* a free adapter** (verified):
`engine/pricing/skew.py` is **call-side only** (covered-call-writer framing) and
`ChainQuote.premium` is denominated in the settlement's native unit (coin for
inverse, USD for linear), built for Deribit. Equity chains are **two-sided**
(the put smirk is the signal equity analysts want), USD-settled, with vendor IV/
greeks supplied. So the correct move is to **genuinely generalize `vol_skew`/
`option_chain` to be settlement- and side-agnostic in `engine/pricing/`** (keeps
math in the engine) and add a put wing — **not** write new skew math at the route
layer (which the boundaries forbid). Budget this as real engine work.

### 4.3 Boundary compliance (all verified against `CLAUDE.md` hard-NOs)

SPDX header on every new `.py`; sync handlers + sync `httpx`; **no new regime
state** (regime is consumed, never extended; the 5-state model + thresholds are
untouched); read-only / GET-only / no write routes; **no client data / PII** (the
only persons ever named are public-company insiders from Form 4 and 13F filers);
disclaimers sourced from `disclaimers.py` only; **confidence tiers stay
non-verdicts and third-party analyst data is explicitly attributed, never
relabeled** into a nexus buy/sell call; degrade-to-503 when keys absent (EDGAR
keyless fallback keeps fundamentals/insider answering); license-name comment on
any new dep; hermetic tests via `create_app(enable_mcp=False, research=<fake>)` +
recorded fixtures + a FastMCP test client; `docs/ARCHITECTURE.md` updated in the
same PR (the `build_server`/`create_app` signature gains a `research` param —
that touches the engine contract).

> **Determinism caveat to honor:** ASAN Check 8 inputs sourced from a *keyed*
> provider must be **best-effort enrichment** — absence still yields
> `insufficient_data`, never a silent tier shift, so the same ticker can't score
> differently on a keyed vs keyless deploy. Do **not** let key-presence change the
> calibrated thresholds. The score is a published, patent-anchored calibration.

---

## 5. Using Claude Code / Claude.ai with nexusmcp.site — **today**

This works now, against the shipped read-only tools — no scaffold required. The
runnable reference is [`examples/stock_research_agent.py`](../examples/stock_research_agent.py).

### 5.1 Connect

- **Claude Code (personal):** `claude mcp add --transport http nexus-core https://nexusmcp.site/mcp/`
- **Claude Code (team, durable):** commit a project-root `.mcp.json`:

  ```json
  {
    "mcpServers": {
      "nexus-core": { "type": "http", "url": "https://nexusmcp.site/mcp/" }
    }
  }
  ```

  `type` **must** be `http` (Streamable HTTP); the hosted endpoint is public,
  read-only, no key/OAuth. Verify with `/mcp` (should show `connected`, ~52
  tools), then prompt Claude to call `describe` (catalog + **symbology**) and
  `health` (per-upstream status).
- **Claude.ai (web/desktop):** Settings → Connectors → *Add custom connector* →
  `https://nexusmcp.site/mcp/`. Desktop without the web connector bridges via
  `npx -y mcp-remote https://nexusmcp.site/mcp/`.
- **Symbology trap** (from `describe`/`llms.txt`): the **same asset uses
  different ids per tool family** — equities/ETFs/indices use Yahoo tickers
  (`AAPL`, `^GSPC`); crypto *quotes* use a CoinGecko id (`bitcoin`, **not**
  `BTC-USD`); crypto *scoring* uses a Yahoo-style pair (`BTC-USD`); crypto
  *options* use a Deribit code (`BTC`). Rate limit is 60 req/min per IP
  (`/health` + `/mcp` exempt); a full dossier is well under that.

### 5.2 The analysis playbook

| Step | Tools | Works today? |
|------|-------|--------------|
| 0. Orient + macro frame | `describe`, `health`, `current_regime`, `regime_signals` | ✅ |
| 1. EMF durability — the spine | `score_asset` | ✅ |
| 2. Price + trend | `get_quote`, `get_price_history` | ✅ (price-only quote) |
| 3. Macro/curve cross-check | `get_economic_series`, `correlation_matrix` | ✅ (no equity valuation tool) |
| 4. Analyst consensus + targets | `analyst_consensus`*, price targets | ⛔ needs scaffold |
| 5. Estimates + surprises + catalyst | `earnings_estimates`*, calendar | ⛔ needs scaffold |
| 6. Real IV / skew / chain | `equity_iv_skew`*, `equity_option_chain`* | ⛔ needs scaffold (crypto-only today) |
| 7. News / sentiment / ownership | `company_news`*, `insider_activity`* | ⛔ needs scaffold |
| 8. Synthesis vs regime + score | `current_regime`, `score_asset` (model-side) | ✅ — gaps labelled, not filled |

The **`stock-idea-dossier`** skill = this playbook with a required **REGIME×SCORE
cross-check** that names one of four cells — (a) durable & aligned, (b) right
regime / fails rubric, (c) good company / wrong regime, (d) no edge — and renders
the steps-4–7 buy-case legs as explicit *"— not available from nexus-core today"*
lines until the scaffold lands. Today it returns a complete **regime + durability
+ price** dossier with honest gaps; after the scaffold the same call additionally
returns consensus, estimates, real IV/skew, and sentiment/ownership — same
regime×score spine, same not-advice framing.

---

## 6. The CML-vs-EMF backtest harness (the follow-on)

The operator will provide a directory of outside-service articles with buy and
sell/exit calls, to (a) build a fair track record and (b) compare that research's
selection vs the EMF lens. **This harness is gated** — see [§7](#7-gates--sequencing)
— but the design is settled and the point-in-time replay is already feasible
against current code (`RegimeClassifier.classify()` is **pure + `as_of`-aware**).

**Placement:** a **new `src/nexus_core/research/` subpackage** behind a new
`[research]` extra — *not* `planning/backtest/` (which is reserved for
zipline/alphalens planning-strategy backtests). It imports the engine **read-only**
and exposes **no MCP/REST tool**.

- **Corpus schema** (`research/cml/models.py`, pydantic v2): `CmlCall{call_id,
  ticker, call_type(buy|add|trim|sell|avoid), call_date, thesis_summary(≤600-char
  ORIGINAL paraphrase), thematic_tag, conviction, is_inferred_exit,
  linked_buy_call_id, source:SourceMeta{… content_sha256, extraction_method/model,
  license_note}}` + `CmlCorpus` with load-time invariants. `is_inferred_exit` is
  the most important flag — reconstructed (vs. published) exits must be marked so
  results report **both with and without** them.
- **Ingestion** (auditable, human-gated): operator drops files under
  `corpus/articles/` (**gitignored**) → hash → **LLM-assisted paraphrase-only
  extraction** (prompt pinned + version-stamped; raw response persisted for
  replay) → normalize/resolve tickers (`symbol_overrides.json` for delisted/
  acquired) → reconcile buy↔sell linkage + inferred exits → **mandatory human
  accept/edit/reject review** → freeze to `corpus.json` + `MANIFEST.json`. The
  harness **never fetches** the source content itself.
- **Backtest engine**: a `TotalReturnSeries` adapter (PriceBar is OHLCV-only — no
  adj-close — so this must read MarketStack adjusted EOD / `/dividends` + `/splits`
  or yfinance auto-adjust, **bypassing** the composite); **dual-mode exits**
  (published-only vs. a pre-committed uniform policy) + a ride-forever upper bound
  so buy-and-hold-the-winner bias is visible; **full-corpus survivorship**
  (delisted names terminate at last price / acquisition value, never silently
  dropped); stated equal-dollar sizing; benchmarks SPY + QQQ/IWF + the pick's GICS
  sector ETF; metrics = hit-rate + avg/**median** forward return at 1/3/6/12mo +
  alpha/beta + Sharpe/Sortino + max-DD + sell-call timing value, with **bootstrap
  CIs on small N**.
- **Regime conditioning** (the EMF overlay): `regime_replay.signals_as_of(date)`
  reconstructs the ~7 macro signals from FRED/price history and calls the pure
  `classify(…, as_of=call_date)`; `score_at_call_date` runs `build_scoring_context`
  through a PIT market wrapper truncating history to `≤ call_date`. **Hard limit
  to print in every report:** EDGAR companyfacts is served **as-of-now**
  (restated), so CROIC/F-Score/Perez carry residual look-ahead; only the
  price-derived checks (Hurst, Sector tailwind, Regime alignment) are clean PIT.
- **Comparison rubric:** cross-tab the service's buy/sell vs the EMF tier at
  call-date; hit-rate conditioned on EMF agreement; per-check pattern of the
  picks; regime alignment of the calls; sell-call value vs EMF tier-change; and
  the headline counterfactual — **does layering the EMF filter on the calls add or
  subtract alpha?** Always with the artifact-mismatch caveat (a *call* vs a graded
  *tier*; decade-hold vs regime-adaptive horizon).

**What the follow-on handoff prompt must provide:** (a) the legally-obtained
article directory under `corpus/articles/`; (b) the **exit policy** (published
removal log *or* a pre-committed uniform exit rule — the single biggest fairness
lever); (c) ticker overrides for renamed/delisted/acquired names; (d) benchmark +
sizing choices if not the defaults; (e) the extraction model to use.

---

## 7. Gates & sequencing

The adversarial review returned **compliance: needs-work; boundaries: pass w/ 2
blockers; feasibility: pass w/ cautions.** None are fatal, but three gates are
**load-bearing and must clear in order.**

### Gate A — Vendor data-redistribution rights *(blocks the public surface)*
nexus-core's whole point is a **public, keyless** API. Re-serving **MBOUM-derived**
research data (fundamentals, analyst consensus, price targets, 13F, options chains,
news) to anonymous third parties is exactly the licensed data vendors gate — the
current de-minimis last-price/OHLCV re-serve is a different risk class. **Before any
research route ships publicly:** review the **MBOUM** (and MarketStack) commercial
ToS for downstream-redistribution rights and add an explicit data-redistribution
clause to `attribution.md`/`NOTICE` — **or** gate the research routes to a
**non-public** deployment. Note that the keyless **EDGAR** legs (fundamentals,
Form 4/13F) are public-record data and carry no vendor-redistribution constraint —
which is the other reason the EDGAR-only P0 wins can ship first.

### Gate B — Endpoint reality *(blocks implementation)*
The MBOUM research endpoints are **assumed, not verified** (zero references in the
repo; the existing provider's own docstring flags its envelope as inferred). **Task
#0** is a one-shot **live-key probe** of each endpoint — confirm path, envelope,
field names, **and plan-tier entitlement** — before any modeling work, or the impl
is coded against a fictional API. Same for MarketStack `/dividends` + `/splits`.

### Gate C — Backtest is regulated performance content *(blocks the harness)*
A CML-vs-EMF backtest constructs **hypothetical-performance + competitor-comparison**
content about PW's *own* framework. nexus-core is operated by an SEC-registered RIA
and cites SEC Rule 206(4)-1. Before the harness is **built** (not deferred to the
follow-on): (1) a **hard, code-enforced boundary** — separate `[research]` package
with **no import path** to the MCP/REST registry + a CI guard asserting no
`research/backtest` symbol is reachable from `build_server`/`create_app`; (2)
explicit **CCO sign-off** that backtest output is **internal-research-only and not
advertising**; (3) **documented copyright/IP review** of the corpus (the operator's
CML Pro license/ToS must permit extraction + a derivative dataset + competitive
benchmarking) — paraphrase-only ≤600 chars, raw articles gitignored.

Other must-honor cautions: the **composite dossier must not editorialize across
sections** at the server layer (the a/b/c/d verdict-row stays prompt-side); add a
composite-level disclaimer that it's an assembly of independent data points + a
non-verdict tier; surface forward targets/estimates with **projection-flavored**
caveat language; keep the `describe`/`llms.txt` "research" category strictly
factual (no "comprehensive research / top picks" phrasing — route through 206(4)-1
review like the website AI files); frame `screen_equities` output as **candidates,
not a buy list**; cold backtest runs over many tickers × dates will stress the
MBOUM/MarketStack plan quotas — cost-estimate first.

### Recommended order of work

1. **Now (this scaffold, gate-free):** the Claude Code connection + the
   `stock_research_agent.py` reference + this doc. Uses only shipped read-only
   tools; ships today.
2. **Gate B probe**, then the **P0 provider layer + EDGAR-keyless `fundamentals_
   statements` + the richer-quote + ASAN Check-8 fix** (the Check-8 fix and the
   keyless fundamentals need **no vendor key**, so they clear Gate A on their own).
3. **Gate A clears →** keyed P0/P1 tools (`key_statistics`, `analyst_consensus`,
   `earnings_estimates`, real `equity_option_chain` + the generalized
   `equity_iv_skew`), then `screen_equities`, news/sentiment, the dossier.
4. **Gate C clears →** the `research/` backtest harness scaffold, then the
   operator's corpus follow-on.

This sequencing lets the EMF score get **better** (Check-8, surfaced fundamentals)
and the analyst workflow get **honest gaps filled** without waiting on the vendor
and compliance gates that only the keyed/public and backtest pieces actually need.

---

*Apache-2.0 · USPTO #64/034,229 (defensive) · OIN member. This is a planning
document; it ships no production tool. New work preserves the public-surface
contract: no auth on read endpoints, no public write routes, no client data, no
breaking changes to existing response shapes, confidence tiers are never verdicts.*
