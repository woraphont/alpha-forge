"""
AlphaForge — LLM Pattern Recognition with Buffett Framework (v2)
Full Warren Buffett investment analysis — micro/company level.

Sources:
  - buffett-perspective (github.com/will2025btc/buffett-perspective):
      Buffett cognitive framework (6 mental models) as system prompt
  - ai-investor (github.com/Bilovodskyi/ai-investor):
      Buffett Algorithm (ROE, D/E, Operating Margin, DCF, Owner Earnings)
  - "The Warren Buffett Way" (Hagstrom, 2004)
  - "Warren Buffett's Investment Criteria" (pictureperfectportfolios.com)
  - Berkshire Hathaway Annual Letters (1977–2024)

Complements dalio_macro.py (macro regime) with company-level fundamentals.
Uses ai_router TaskTier.COMPLEX → Claude Haiku 4.5.
Phase 4: migrate to AWS Bedrock Claude.
"""
import json
import logging
from typing import Any

import pandas as pd

from ai.ai_router import route, TaskTier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Warren Buffett system prompt (v2, research-backed)
# ---------------------------------------------------------------------------
_BUFFETT_SYSTEM = """You are Warren Buffett analyzing a stock using your complete 60-year investment framework.

═══════════════════════════════════════════════════════
 FRAMEWORK 1 — SIX MENTAL MODELS
═══════════════════════════════════════════════════════
1. ECONOMIC MOAT: Does this business have durable competitive advantages?
   - Wide moat sources: brand power, network effects, switching costs,
     cost advantages, regulatory licenses, patents
   - Ask: "Can a competitor with $10B destroy this business in 10 years?"

2. CIRCLE OF COMPETENCE: Is this business simple and understandable?
   - Must be explainable on the back of a napkin
   - Avoid complexity that hides risk
   - "If you can't describe what a company does in one sentence, don't buy it"

3. MR. MARKET: Is the price irrational vs. intrinsic value?
   - Mr. Market is a moody business partner, not your guide
   - "Be fearful when others are greedy, greedy when others are fearful"
   - Price ≠ Value — exploit the gap

4. OWNER MINDSET: Would you buy the ENTIRE business at this price?
   - Think like a business owner, not a stock trader
   - Would this cash flow justify a private acquisition price?

5. MARGIN OF SAFETY: Is there enough buffer between price and intrinsic value?
   - Buy at 20–30% discount to intrinsic value minimum
   - "The three most important words in investing: margin of safety"
   - Margin of safety compensates for errors in judgment and bad luck

6. MANAGEMENT QUALITY: Are they allocating capital wisely?
   - Rational: reinvest at high returns, else return to shareholders
   - Candid: acknowledge mistakes, transparent with shareholders
   - Independent: resist "institutional imperative" (blindly copying peers)
   - Track record: consistent performance across economic cycles

═══════════════════════════════════════════════════════
 FRAMEWORK 2 — BUFFETT ALGORITHM (QUANTITATIVE RULES)
═══════════════════════════════════════════════════════
PASS/FAIL CRITERIA:
  ROE ≥ 15% consistently         → strong business (not from excess leverage)
  Debt/Equity ≤ 0.5              → financial conservatism
  Operating Margin ≥ 20%         → pricing power and moat evidence
  Current Ratio ≥ 1.5            → liquidity safety margin
  Net Margin ≥ 10%               → real profitability
  Revenue Growth ≥ 5% (3yr avg)  → business expanding, not declining
  EPS Growth ≥ 8% (5yr avg)      → earnings compounding over time
  Free Cash Flow positive        → earnings are real, not accounting fiction

VALUATION CRITERIA:
  P/E ≤ 15                       → fair value zone
  P/E 15–25                      → moderate premium, requires strong moat
  P/E > 25                       → requires exceptional growth to justify
  P/B ≤ 1.5                      → deep value
  PEG ratio ≤ 1.0                → growth at reasonable price (GARP)

═══════════════════════════════════════════════════════
 FRAMEWORK 3 — OWNER'S EARNINGS (TRUE CASH GENERATION)
═══════════════════════════════════════════════════════
Owner's Earnings = Net Income + Depreciation/Amortization
                   - Capital Expenditure - Working Capital Changes

"What matters is what the owner can take home, not accounting profit."

  Positive owner's earnings + growing trend = genuine wealth creation
  Negative or declining = earnings quality problem → investigate

═══════════════════════════════════════════════════════
 FRAMEWORK 4 — INTRINSIC VALUE ESTIMATION
═══════════════════════════════════════════════════════
Buffett-style DCF:
  1. Project owner's earnings for 10 years (use conservative growth rate)
  2. Apply discount rate = 10-year Treasury yield + equity risk premium (~10%)
  3. Add terminal value (conservative: 3% perpetuity growth)
  4. Discount everything back to present value
  5. Buy only if current price < intrinsic value × 0.70 (30% margin of safety)

"It's better to buy a wonderful company at a fair price than a fair company at a wonderful price."

═══════════════════════════════════════════════════════
 FRAMEWORK 5 — WHAT BUFFETT AVOIDS
═══════════════════════════════════════════════════════
  - Businesses requiring constant reinvestment just to survive
  - Commodity businesses with no pricing power
  - Companies with complex derivatives or opaque accounting
  - Turnarounds (rarely work)
  - IPOs and hot sectors with no earnings history
  - Excessive debt taken on for growth (destroys margin of safety)
  - Management that empire-builds via unrelated acquisitions

═══════════════════════════════════════════════════════
 OUTPUT FORMAT
═══════════════════════════════════════════════════════
Output ONLY a JSON object (no extra text):
{
  "score":       <float 0.0–1.0>,
  "signal":      "<BULLISH|NEUTRAL|BEARISH>",
  "moat":        "<WIDE|NARROW|NONE>",
  "valuation":   "<UNDERVALUED|FAIR|OVERVALUED>",
  "reasoning":   "<2 sentences max — cite specific metric + mental model>",
  "key_concern": "<one sentence on biggest risk or null>"
}

Score guide:
  0.75–1.0 = strong buy (wide moat + undervalued + solid fundamentals passing ≥4/5 checks)
  0.55–0.74 = mild buy (some concerns but fundamentals solid, fair valuation)
  0.40–0.54 = neutral (mixed signals, hold if owned, not a buy)
  0.20–0.39 = mild avoid (weak fundamentals or overvalued, limited moat)
  0.0–0.19  = avoid (no moat + bad financials + speculative / high debt)"""


# ---------------------------------------------------------------------------
# Quantitative pre-scorer (Buffett Algorithm)
# ---------------------------------------------------------------------------

def _score_fundamentals(fundamentals: dict[str, Any]) -> dict[str, Any]:
    """
    Pre-score fundamentals using Buffett Algorithm rules.
    Returns structured summary for LLM context.
    """
    checks: dict[str, bool | None] = {}

    roe = fundamentals.get("roe")
    checks["roe_ok"] = roe >= 0.15 if roe is not None else None

    de = fundamentals.get("debt_to_equity")
    checks["low_debt"] = de <= 0.5 if de is not None else None

    om = fundamentals.get("operating_margin")
    checks["margin_ok"] = om >= 0.20 if om is not None else None

    cr = fundamentals.get("current_ratio")
    checks["liquid_ok"] = cr >= 1.5 if cr is not None else None

    nm = fundamentals.get("net_margin")
    checks["net_margin_ok"] = nm >= 0.10 if nm is not None else None

    rev_growth = fundamentals.get("revenue_growth")
    checks["growth_ok"] = rev_growth >= 0.05 if rev_growth is not None else None

    pe = fundamentals.get("pe_ratio")
    checks["pe_ok"] = pe <= 25 if pe is not None else None

    owner_earnings = fundamentals.get("owner_earnings")
    checks["fcf_ok"] = owner_earnings > 0 if owner_earnings is not None else None

    # Pre-score: count passing checks
    known = [v for v in checks.values() if v is not None]
    pre_score = (sum(known) / len(known)) if known else 0.5

    # Valuation signal
    if pe is not None:
        valuation_hint = "UNDERVALUED" if pe <= 15 else "OVERVALUED" if pe > 25 else "FAIR"
    else:
        valuation_hint = "UNKNOWN"

    def _fmt(v: float | None, pct: bool = False) -> str:
        if v is None:
            return "N/A"
        return f"{v*100:.1f}%" if pct else f"{v:.2f}"

    return {
        "pre_score": round(pre_score, 3),
        "checks": checks,
        "checks_passed": sum(1 for v in checks.values() if v is True),
        "checks_total": len([v for v in checks.values() if v is not None]),
        "valuation_hint": valuation_hint,
        "roe_pct": _fmt(roe, pct=True),
        "debt_to_equity": _fmt(de),
        "operating_margin_pct": _fmt(om, pct=True),
        "net_margin_pct": _fmt(nm, pct=True),
        "current_ratio": _fmt(cr),
        "pe_ratio": _fmt(pe),
        "revenue_growth_pct": _fmt(rev_growth, pct=True),
        "owner_earnings": owner_earnings,
    }


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_pattern(symbol: str, df: pd.DataFrame, fundamentals: dict[str, Any]) -> dict[str, Any]:
    """
    Full Buffett-framework analysis: mental models + quantitative algorithm.

    Args:
        symbol:       Ticker symbol
        df:           OHLCV DataFrame (recent price history)
        fundamentals: Output from fetcher.fetch_fundamentals()

    Returns:
        dict with keys: score (float 0.0–1.0), signal, moat, valuation,
                        reasoning, key_concern, source
    """
    fund = _score_fundamentals(fundamentals)
    sector = fundamentals.get("sector", "Unknown")

    # Price context: last 5 closes
    recent_closes = df["Close"].tail(5).round(2).tolist()
    price_trend = "UP" if recent_closes[-1] > recent_closes[0] else "DOWN"
    price_change_pct = (recent_closes[-1] - recent_closes[0]) / recent_closes[0] * 100

    prompt = f"""Analyze {symbol} ({sector} sector) from Warren Buffett's complete framework.

PRICE DATA (last 5 days):
  Closes: {recent_closes}
  5-day trend: {price_trend} ({price_change_pct:+.1f}%)

FUNDAMENTAL METRICS — Buffett Algorithm ({fund['checks_passed']}/{fund['checks_total']} checks passed):
  ROE:               {fund['roe_pct']}        (target ≥ 15%)  {'✅' if fund['checks'].get('roe_ok') else '❌' if fund['checks'].get('roe_ok') is False else '—'}
  Debt/Equity:       {fund['debt_to_equity']}      (target ≤ 0.5)  {'✅' if fund['checks'].get('low_debt') else '❌' if fund['checks'].get('low_debt') is False else '—'}
  Operating Margin:  {fund['operating_margin_pct']}  (target ≥ 20%)  {'✅' if fund['checks'].get('margin_ok') else '❌' if fund['checks'].get('margin_ok') is False else '—'}
  Net Margin:        {fund['net_margin_pct']}        (target ≥ 10%)  {'✅' if fund['checks'].get('net_margin_ok') else '❌' if fund['checks'].get('net_margin_ok') is False else '—'}
  Current Ratio:     {fund['current_ratio']}      (target ≥ 1.5)  {'✅' if fund['checks'].get('liquid_ok') else '❌' if fund['checks'].get('liquid_ok') is False else '—'}
  P/E Ratio:         {fund['pe_ratio']}          (≤15 = value, >25 = expensive)  {'✅' if fund['checks'].get('pe_ok') else '❌' if fund['checks'].get('pe_ok') is False else '—'}
  Revenue Growth:    {fund['revenue_growth_pct']}   (target ≥ 5%)  {'✅' if fund['checks'].get('growth_ok') else '❌' if fund['checks'].get('growth_ok') is False else '—'}
  Owner Earnings:    {fund['owner_earnings']}
  Pre-score:         {fund['pre_score']} | Valuation hint: {fund['valuation_hint']}

Apply your 5 frameworks:
  1. Six Mental Models — especially moat, margin of safety, owner mindset
  2. Quantitative checks — how many of the 8 Buffett Algorithm criteria pass?
  3. Owner's Earnings — is real cash generation positive and growing?
  4. Intrinsic Value — is the current price at a discount (margin of safety)?
  5. What Buffett Avoids — any red flags (high debt, no pricing power, opaque)?

Provide your complete Buffett verdict for {symbol}."""

    try:
        raw = route(TaskTier.COMPLEX, prompt, system=_BUFFETT_SYSTEM)
        result = _parse_response(raw)
        logger.info({
            "action": "llm_pattern_scored",
            "symbol": symbol,
            "score": result["score"],
            "signal": result["signal"],
            "moat": result.get("moat"),
            "valuation": result.get("valuation"),
            "checks_passed": fund["checks_passed"],
        })
        return result
    except Exception as e:
        logger.warning({"action": "llm_pattern_failed", "symbol": symbol, "error": str(e)})
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
            "signal": parsed.get("signal", "NEUTRAL"),
            "moat": parsed.get("moat", "UNKNOWN"),
            "valuation": parsed.get("valuation", "UNKNOWN"),
            "reasoning": parsed.get("reasoning", ""),
            "key_concern": parsed.get("key_concern"),
            "source": "buffett_framework_v2",
        }
    except (json.JSONDecodeError, ValueError, KeyError):
        return _neutral_result("parse_error")


def _neutral_result(reason: str) -> dict[str, Any]:
    return {
        "score": 0.5,
        "signal": "NEUTRAL",
        "moat": "UNKNOWN",
        "valuation": "UNKNOWN",
        "reasoning": f"fallback: {reason}",
        "key_concern": None,
        "source": "fallback",
    }
