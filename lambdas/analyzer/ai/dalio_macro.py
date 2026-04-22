"""
AlphaForge — Dalio Macro Framework (v2)
Ray Dalio's full macro economic machine analysis for individual stocks.

Sources:
  - "Principles for Navigating Big Debt Crises" (Dalio, 2018)
  - "How the Economic Machine Works" (Dalio / Bridgewater)
  - "Principles for Dealing with the Changing World Order" (Dalio, 2021)
  - Reference repo: github.com/bridaniels/Principles_NavigatingBigDebtCrises
  - Big Cycle research: Fortune / Bridgewater, 2025–2026

Complements llm_pattern.py (Buffett micro: company fundamentals)
with macro-level regime + cycle context.

Used in scorer.py as dalio_macro slot (weight 0.05).
Phase 2: add FRED API (CPI, Fed Funds Rate, Yield Curve, DXY) for live macro data.
"""
import json
import logging
from typing import Any

import pandas as pd

from ai.ai_router import route, TaskTier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ray Dalio Macro Framework — system prompt (v2, research-backed)
# ---------------------------------------------------------------------------
_DALIO_SYSTEM = """You are Ray Dalio analyzing a stock using your complete macro economic machine framework.

═══════════════════════════════════════════════════════
 FRAMEWORK 1 — THREE FORCES DRIVING THE ECONOMY
═══════════════════════════════════════════════════════
1. Productivity growth  (slow, linear, long-run determinant)
2. Short-term debt cycle  (5–8 years: expansion → recession → expansion)
3. Long-term debt cycle   (75–100 years: accumulation → deleveraging)

THREE CORE RULES (violations = crisis):
  Rule 1: Debt must NOT rise faster than income (→ unsustainable debt burden)
  Rule 2: Income must NOT rise faster than productivity (→ lost competitiveness)
  Rule 3: Raise productivity — it is the only source of sustainable prosperity

DEBT CLASSIFICATION:
  Good debt  = finances productive assets that generate repayable income
  Bad debt   = finances over-consumption with no repayment capacity

═══════════════════════════════════════════════════════
 FRAMEWORK 2 — DEBT CYCLE STAGES
═══════════════════════════════════════════════════════
DEFLATION DEBT CYCLE (7 stages):
  1. Early        — credit expanding, asset prices rising, policy stimulative     → RISK_ON
  2. Bubble       — speculation peaks, debt-to-income ratio dangerously high       → RISK_ON (late)
  3. Top          — credit tightens, rates rise, asset prices plateau              → RISK_OFF
  4. Depression   — debt defaults, asset prices crash, unemployment spikes         → DELEVERAGING
  5. Beautiful Deleveraging — balanced mix of: cut spending + debt reduction
                              + wealth redistribution + money printing
                              Result: debt/income falls, growth resumes, inflation controlled
                              Duration: typically 7–10 years ("lost decade")       → cautious RISK_ON
  6. Pushing on a String — monetary policy exhausted, rates near zero, limited effect → RISK_OFF
  7. Normalization — debt levels sustainable, growth resumes organically           → RISK_ON

INFLATION DEBT CYCLE (5 stages):
  1. Early        — inflation rising moderately, growth strong                     → RISK_ON (select)
  2. Bubble       — inflation high, commodity boom, currency weakening             → commodities/gold
  3. Top          — hyperinflation risk, capital flight, policy tightening extreme → DELEVERAGING
  4. Depression   — austerity, currency collapse, wealth destruction               → DELEVERAGING
  5. Normalization — currency stabilized, inflation controlled, recovery begins    → gradual RISK_ON

═══════════════════════════════════════════════════════
 FRAMEWORK 3 — FOUR ECONOMIC SEASONS (All-Weather)
═══════════════════════════════════════════════════════
Season A: Rising Growth + Rising Inflation    → stocks + commodities win
Season B: Rising Growth + Falling Inflation   → stocks + bonds win
Season C: Falling Growth + Rising Inflation   → commodities + TIPS win (stagflation)
Season D: Falling Growth + Falling Inflation  → bonds + gold win (deflationary recession)

All-Weather asset bias:
  Rising prices    → commodities, gold, inflation-linked bonds
  Falling prices   → nominal bonds, quality growth stocks
  Rising growth    → equities, corporate bonds
  Falling growth   → long-term bonds, gold, defensive stocks

═══════════════════════════════════════════════════════
 FRAMEWORK 4 — BIG CYCLE (Changing World Order)
═══════════════════════════════════════════════════════
6-Stage Empire Cycle (500-year pattern):
  Stage 1: New Order      — new reserve currency, low debt, strong institutions
  Stage 2: Resource Build — investment, infrastructure, trade expansion
  Stage 3: Peace & Prosperity — peak productivity, rising living standards
  Stage 4: Excess        — debt rises, inequality grows, financialization dominates
  Stage 5: Disorder Begins — debt unsustainable, political conflict, currency risk
  Stage 6: Great Disorder — geopolitical conflict, capital wars, currency devaluation
                             "Might is right" — law of the jungle returns

Five Forces reshaping the world order (2026 context):
  1. Debt/currency/economic power (reserve currency status at risk)
  2. Domestic political power (populism, polarization)
  3. Geopolitical power (military spending cycles)
  4. Natural forces (climate disruption)
  5. Technological power (AI in early bubble stage — Dalio, 2025)

Current macro context (April 2026):
  - World order: transitioning Stage 5 → Stage 6 (Munich Security Conference, Feb 2026)
  - USD hegemony under pressure, gold outperforming fiat assets
  - Trade wars + technology wars escalating
  - AI in early bubble stage — high valuations, not yet bubble burst

═══════════════════════════════════════════════════════
 FRAMEWORK 5 — SECTOR ANALYSIS BY CYCLE PHASE
═══════════════════════════════════════════════════════
Early Expansion:   Technology, Financials, Consumer Discretionary → outperform
Mid Expansion:     Industrials, Materials, Real Estate → outperform
Late Expansion:    Energy, Commodities, Healthcare (defensive) → outperform
Contraction:       Utilities, Consumer Staples, Healthcare → defensive outperform
Deleveraging:      Gold, Cash, Short-duration bonds → preserve capital
Reflation:         Banks, Cyclicals, EM equities → early movers

═══════════════════════════════════════════════════════
 OUTPUT FORMAT
═══════════════════════════════════════════════════════
Output ONLY a JSON object (no extra text):
{
  "score":       <float 0.0–1.0>,
  "regime":      "<RISK_ON|RISK_OFF|DELEVERAGING>",
  "cycle":       "<EARLY_EXPANSION|MID_EXPANSION|LATE_EXPANSION|CONTRACTION|DELEVERAGING|NORMALIZATION>",
  "season":      "<A_GROWTH_INFLATION|B_GROWTH_DISINFLATION|C_STAGFLATION|D_DEFLATION>",
  "big_cycle":   "<STAGE_1_3|STAGE_4|STAGE_5|STAGE_6>",
  "macro_bias":  "<one Dalio-style macro sentence referencing debt cycle and regime>",
  "key_risk":    "<one specific macro risk to this stock/sector or null>"
}

Score guide:
  0.75–1.0 = strong macro tailwind (RISK_ON, early/mid expansion, Season B)
  0.55–0.74 = mild tailwind (mid cycle, moderate debt burden, Season A)
  0.40–0.54 = neutral (mixed signals, late mid-cycle, Season B/D transition)
  0.20–0.39 = mild headwind (late expansion, rising rates, Season C stagflation)
  0.0–0.19  = strong headwind (DELEVERAGING, Stage 5/6, Season D or hyperinflation)"""


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _build_macro_context(symbol: str, df: pd.DataFrame, fundamentals: dict[str, Any]) -> dict[str, Any]:
    """
    Build macro proxy signals from available price + fundamental data.
    Phase 2: replace with FRED API (CPI, Fed Funds Rate, Yield Curve, DXY).
    """
    close = df["Close"]
    volume = df["Volume"]

    # Price momentum (60-day) as macro proxy
    price_60d_change = float((close.iloc[-1] - close.iloc[0]) / close.iloc[0] * 100) if len(close) > 1 else 0.0

    # Volatility proxy (20-day std dev of daily returns)
    returns = close.pct_change().dropna()
    vol_20d = float(returns.tail(20).std() * 100) if len(returns) >= 20 else 0.0

    # Volume trend: rising = accumulation, falling = distribution
    avg_vol_recent = float(volume.tail(10).mean())
    avg_vol_prior = float(volume.head(20).mean()) if len(volume) >= 30 else avg_vol_recent
    vol_trend = "ACCUMULATION" if avg_vol_recent > avg_vol_prior else "DISTRIBUTION"

    # Debt cycle proxies from fundamentals
    sector = fundamentals.get("sector", "Unknown")
    industry = fundamentals.get("industry", "Unknown")
    country = fundamentals.get("country", "US")
    debt_to_equity = fundamentals.get("debt_to_equity")
    pe_ratio = fundamentals.get("pe_ratio")
    revenue_growth = fundamentals.get("revenue_growth")
    operating_margin = fundamentals.get("operating_margin")
    current_ratio = fundamentals.get("current_ratio")
    beta = fundamentals.get("beta")

    def _fmt(v: float | None, pct: bool = False) -> str:
        if v is None:
            return "N/A"
        return f"{v*100:.1f}%" if pct else f"{v:.2f}"

    # Debt burden signal: D/E > 2.0 = late cycle warning
    debt_signal = "HIGH (late-cycle risk)" if debt_to_equity and debt_to_equity > 2.0 else \
                  "MODERATE" if debt_to_equity and debt_to_equity > 0.5 else "LOW (healthy)"

    # P/E signal: >30 = late cycle / bubble risk
    pe_signal = "HIGH (bubble risk)" if pe_ratio and pe_ratio > 30 else \
                "MODERATE" if pe_ratio and pe_ratio > 15 else \
                "LOW (value zone)" if pe_ratio else "N/A"

    return {
        "price_60d_change_pct": round(price_60d_change, 2),
        "volatility_20d_pct": round(vol_20d, 2),
        "volume_trend": vol_trend,
        "sector": sector,
        "industry": industry,
        "country": country,
        "debt_to_equity": _fmt(debt_to_equity),
        "debt_signal": debt_signal,
        "pe_ratio": _fmt(pe_ratio),
        "pe_signal": pe_signal,
        "revenue_growth_pct": _fmt(revenue_growth, pct=True),
        "operating_margin_pct": _fmt(operating_margin, pct=True),
        "current_ratio": _fmt(current_ratio),
        "beta": _fmt(beta),
    }


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_macro(symbol: str, df: pd.DataFrame, fundamentals: dict[str, Any]) -> dict[str, Any]:
    """
    Full macro regime analysis using Ray Dalio's 5-framework approach.

    Args:
        symbol:       Ticker symbol
        df:           OHLCV DataFrame (60d recommended)
        fundamentals: Output from fetcher.fetch_fundamentals()

    Returns:
        dict with keys: score, regime, cycle, season, big_cycle,
                        macro_bias, key_risk, source
    """
    ctx = _build_macro_context(symbol, df, fundamentals)

    prompt = f"""Analyze {symbol} through Ray Dalio's complete macro framework.

STOCK DATA:
  Sector:          {ctx['sector']} | Industry: {ctx['industry']}
  HQ Country:      {ctx['country']}
  60-day return:   {ctx['price_60d_change_pct']:+.1f}%
  Volatility(20d): {ctx['volatility_20d_pct']:.1f}% daily std dev
  Volume trend:    {ctx['volume_trend']} (recent vs prior 20d avg)
  Beta:            {ctx['beta']} (market sensitivity)

DEBT & VALUATION (corporate debt cycle proxies):
  Debt/Equity:     {ctx['debt_to_equity']} → {ctx['debt_signal']}
  P/E Ratio:       {ctx['pe_ratio']} → {ctx['pe_signal']}
  Revenue Growth:  {ctx['revenue_growth_pct']}
  Operating Margin:{ctx['operating_margin_pct']}
  Current Ratio:   {ctx['current_ratio']}

MACRO CONTEXT (April 2026):
  - World Order: Stage 5 → Stage 6 transition (geopolitical disorder rising)
  - USD under pressure, gold outperforming, trade/tech wars escalating
  - AI sector in early bubble stage (Dalio's own assessment, 2025)
  - Federal debt/GDP at historic highs → Rule 1 violation risk

Apply your 5 frameworks:
  1. Which debt cycle stage (deflation 7-stage or inflation 5-stage)?
  2. Which economic season (A/B/C/D) is this company positioned for?
  3. Does this sector outperform or underperform in the current cycle phase?
  4. Big Cycle stage impact — does world order transition affect this company?
  5. Three Core Rules check: is this company's debt rising faster than income?

Note: FRED live data (CPI, yield curve, DXY) not yet available (Phase 2).
      Derive cycle position from company fundamentals + sector knowledge.

Provide your full macro regime verdict for {symbol}."""

    try:
        raw = route(TaskTier.COMPLEX, prompt, system=_DALIO_SYSTEM)
        result = _parse_response(raw)
        logger.info({
            "action": "dalio_macro_scored",
            "symbol": symbol,
            "score": result["score"],
            "regime": result["regime"],
            "cycle": result["cycle"],
            "season": result.get("season"),
            "big_cycle": result.get("big_cycle"),
        })
        return result
    except Exception as e:
        logger.warning({"action": "dalio_macro_failed", "symbol": symbol, "error": str(e)})
        return _neutral_result("ai_error")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_response(raw: str) -> dict[str, Any]:
    """Parse JSON from AI response, fallback to neutral on error."""
    try:
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        parsed = json.loads(clean.strip())
        score = max(0.0, min(1.0, float(parsed.get("score", 0.5))))
        return {
            "score": round(score, 3),
            "regime": parsed.get("regime", "RISK_OFF"),
            "cycle": parsed.get("cycle", "CONTRACTION"),
            "season": parsed.get("season", "D_DEFLATION"),
            "big_cycle": parsed.get("big_cycle", "STAGE_5"),
            "macro_bias": parsed.get("macro_bias", ""),
            "key_risk": parsed.get("key_risk"),
            "source": "dalio_framework_v2",
        }
    except (json.JSONDecodeError, ValueError, KeyError):
        return _neutral_result("parse_error")


def _neutral_result(reason: str) -> dict[str, Any]:
    return {
        "score": 0.5,
        "regime": "RISK_OFF",
        "cycle": "CONTRACTION",
        "season": "D_DEFLATION",
        "big_cycle": "STAGE_5",
        "macro_bias": f"fallback: {reason}",
        "key_risk": None,
        "source": "fallback",
    }
