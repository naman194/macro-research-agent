# Macro Research Agent

Institutional-grade equity research agent for Indian markets. Streamlit dashboard that combines a top-down macro view with multi-framework screening (Quality+Value, GARP, Special Situations, Macro-Thematic) and a Claude-powered research note generator.

## Status

**Phase 1 ✓** Macro dashboard + Quality+Value screener + research note agent. Free data only (NSE, screener.in, FRED, IMF, World Bank).

**Phase 2 ✓** GARP screener (PEG ≤ 1.5, accelerating earnings) + Special Situations screener (live NSE event feed: buybacks, bonus, splits, fund-raising, scored by event weight × proximity) + GDELT news sentiment + RBI press-release + SEBI circular scrapers. Research note agent now ingests sentiment + policy + special-situation context.

**Phase 2.5 ✓** Daily Morning Brief (institutional grade): Pre-market global cues + Indian indices yesterday close + FII/DII flows from NSE + Top gainers/losers + Sectoral heatmap + Top fundamental ideas + Technical/swing setups + Catalysts + Policy + Sentiment + Risk Watch. PDF download with branded header band, styled tables, green/red % coloring. Plus standalone **Technical / Swing Setups** view with trend-pullback (high win-rate) and base-breakout (high R:R) strategies, regime-filtered by Nifty 200DMA bear-market guard.

**Phase 3 (P1 features) ✓** Five additional desk-facing surfaces:
- **Sector Dashboards** (Banks / IT / Auto): sector-tailored KPIs from quarterly results — bank financing margin, IT USDINR sensitivity (90d correlation), auto OPM trends
- **Index Rebalance Predictor**: ranks Nifty 50 + Next 50 universe by free-float mcap, identifies likely additions/deletions at next semi-annual review with passive flow estimates in Rs Cr
- **Macro Economic Calendar**: 30-day lookahead, RBI MPC + Fed FOMC + ECB + BoE meeting dates, India CPI/IIP/WPI/GDP releases, with importance flags
- **Performance Tracker**: forward journal (auto-logs every daily-brief pick to SQLite, tracks realized N-day returns over time) + historical lookback (what current candidates would have returned at 1m/3m/6m/1y)
- **Stock-in-Focus**: highest-scoring screen candidate each day, with 1Y price chart (20/50/200 DMA) embedded in the morning brief PDF, plus relative-multiple DCF range (bear/base/bull)

**Phase 3 (P0 features) ✓** Six institutional-grade additions:
- **Smart Money view**: Block deals (large institutional prints in negotiated window) + Bulk deals (>0.5% float, institutional counterparty flag) + Insider/Promoter PIT disclosures (promoter buys ranked separately, ESOP noise excluded, pledge activity surfaced)
- **F&O Analytics view**: Option chain for indices and 14 most-traded stocks, PCR by OI, Max Pain calculation, support/resistance from highest OI strikes, sentiment classification
- **Results view**: Calendar of upcoming results from NSE events feed + per-ticker quarterly history (revenue/EBITDA/margins/EPS with YoY+QoQ deltas) + shareholding pattern trend (promoter/FII/DII/public quarterly movement)
- **Concall AI view**: Upload concall transcript PDF → Claude produces structured analyst note (management tone, guidance changes, key concerns, Q&A pressure points, verbatim quotes)
- Daily Morning Brief now also includes F&O Read section + Smart Money Tracker section with block deals and promoter activity

**Phase 3 (todo)** Macro-thematic top-down view (policy → sector → constituents), paid data adapters (Tijori / Trendlyne / Smallcase), backtest / hit-rate tracking on past picks, NSE block-deals feed (requires WAF workaround).

## Setup

```bash
cd /Users/naman/macro-research-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — at minimum add ANTHROPIC_API_KEY and FRED_API_KEY
```

## Run

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`.

## Architecture

```
src/
  data/        Pluggable adapters: NSE, screener.in, FRED, IMF, World Bank,
               GDELT (news/sentiment), RBI press releases, SEBI circulars
               + SQLite cache layer with per-type TTLs
  screens/    Quality+Value, GARP, Special Situations (event-driven)
  agent/      Claude-powered research note generator with prompt caching;
              ingests fundamentals + filings + macro + sentiment + policy +
              special-situations into one note
  ui/         Six Streamlit views: Macro, Q+V, GARP, Special Situations,
              Policy & Sentiment, Research Note
```

Adapters are pluggable — paid providers slot in behind the same interface when you add keys.

## Known limitations

- **NSE live quotes are throttled.** `nse_eq` returns empty most of the time without proper cookie handling. The dashboard degrades gracefully: price/52w come from screener.in, and the events feed uses `nse_events` which is reliable but only covers upcoming board meetings (results, dividends, buybacks, fund raising). **Demerger / open-offer / scheme-of-arrangement** lives on a separate NSE URL and isn't yet plumbed in — Phase 3.
- **screener.in tickers may differ from NSE symbols.** Most NIFTY 50 names work; a few (e.g. TATAMOTORS) return 404 — they live at a different slug. Failing tickers are logged and excluded from the screen; the rest still rank correctly.
- **D/E sometimes parses as `None`** for NBFCs and banks because their balance sheet structure differs from non-financial companies. The Q+V screener will reject those names (D/E is a hard filter); GARP allows it through with a wider lens.
- **GDELT can be slow** (45–60s on cold call) and occasionally times out. Cached for 6h on success; on failure the agent gets an empty sentiment block and proceeds.
- **RBI/SEBI scrapers don't extract exact dates** for every item (the listing HTML is inconsistent). Headlines are date-desc by default. Phase 3 to enrich with parsed dates and date-range filtering.
- **First load is slow** (10–60s) — adapters are pulling and caching across 50 tickers + 5 external APIs. Subsequent loads use SQLite cache and are sub-second.
- **Without `ANTHROPIC_API_KEY`** the research note view shows raw fundamentals only. Add the key to `.env` for full Claude-generated institutional notes.
- **Without `FRED_API_KEY`** the US-macro panel is empty. Other macro panels (IMF, World Bank) work without any key.

## Disclaimers

This tool produces research output to support an institutional broker's process; it is **not** investment advice and outputs should be independently verified before any action. Data sourced from public APIs and may be stale, incomplete, or incorrect — always cross-check with primary sources (NSE filings, company annual reports).
