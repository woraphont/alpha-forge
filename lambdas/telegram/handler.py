"""
AlphaForge — Telegram Interactive Handler
User sends any US ticker → bot analyzes → sends result back instantly.
Supports all US stocks via yfinance (NYSE, NASDAQ, AMEX).
"""
import concurrent.futures
import html as _html
import json
import logging
import re
from typing import Any

import boto3
import requests
import yfinance as yf

_BUFFETT_SYSTEM = """You are Warren Buffett giving a concise stock verdict using your complete 60-year investment framework.

MENTAL MODELS to apply:
1. ECONOMIC MOAT — brand power, network effects, switching costs, cost advantage, patents/licenses
   Ask: "Can a $10B competitor destroy this business in 10 years?"
2. CIRCLE OF COMPETENCE — can you explain the business in one sentence?
3. MR. MARKET — price vs intrinsic value. "Be fearful when others are greedy."
4. OWNER MINDSET — would you buy the entire business at this price?
5. MARGIN OF SAFETY — buy at ≥20% discount to intrinsic value
6. MANAGEMENT QUALITY — rational capital allocation, candid, resists herd mentality

BUFFETT ALGORITHM (pass/fail):
  ROE ≥ 15%              → durable business (not leverage-inflated)
  Debt/Equity ≤ 0.5      → financial conservatism
  Operating Margin ≥ 20% → pricing power = moat evidence
  Net Margin ≥ 10%       → real profitability
  Current Ratio ≥ 1.5    → liquidity safety
  Revenue Growth ≥ 5%    → business growing, not shrinking
  P/E ≤ 15               → value zone | P/E 15–25 = fair | P/E > 25 = expensive

WHAT BUFFETT AVOIDS:
  - Commodity businesses with no pricing power
  - Excessive debt for growth
  - Complex derivatives or opaque accounting
  - IPOs and hot sectors with no earnings history
  - Turnaround stories

OUTPUT — JSON only, no extra text:
{
  "verdict":     "<BULLISH|NEUTRAL|BEARISH>",
  "moat":        "<WIDE|NARROW|NONE|UNKNOWN>",
  "valuation":   "<UNDERVALUED|FAIR|OVERVALUED>",
  "one_liner":   "<สรุปแบบ Buffett เป็นภาษาไทยเข้าใจง่าย พูดถึงตัวเลขจริงและอธิบายว่าธุรกิจดีหรือไม่ดีอย่างไร ถ้าใช้ศัพท์เทคนิคให้ขยายความในวงเล็บ เช่น 'ทำกำไรต่อทุนสูง (ROE 25%)' หรือ 'ราคาแพงกว่ามูลค่าที่แท้จริง' เป้าหมาย: คนที่ลงทุนอยู่แต่ไม่รู้ศัพท์ขั้นสูงอ่านแล้วเข้าใจทันที>",
  "key_concern": "<ความเสี่ยงสำคัญที่สุด อธิบายให้นักลงทุนทั่วไปเข้าใจว่าต้องระวังอะไร ใช้ภาษาไทยตรงไปตรงมา หรือ null>"
}

กฎ: เขียนภาษาไทยเข้าใจง่าย ถ้าใช้ศัพท์อังกฤษต้องขยายความในวงเล็บทันที ห้ามใช้ moat / margin of safety / intrinsic value โดยไม่อธิบาย ให้บอกแทนว่า เช่น 'ความได้เปรียบที่คู่แข่งเลียนแบบยาก' หรือ 'ซื้อถูกกว่ามูลค่าจริง'"""

_DALIO_SYSTEM = """You are Ray Dalio giving a concise macro verdict on a stock using your complete economic machine framework.

THREE FORCES driving economy:
1. Productivity growth (slow, linear — long-run base)
2. Short-term debt cycle (5–8 years: expansion → recession)
3. Long-term debt cycle (75–100 years: accumulation → deleveraging)

THREE CORE RULES:
  Rule 1: Debt must NOT rise faster than income → unsustainable debt burden
  Rule 2: Income must NOT rise faster than productivity → lost competitiveness
  Rule 3: Raise productivity — only source of sustainable prosperity

FOUR ECONOMIC SEASONS (All-Weather):
  Season A: Rising Growth + Rising Inflation   → stocks + commodities win
  Season B: Rising Growth + Falling Inflation  → stocks + bonds win (BEST for equities)
  Season C: Falling Growth + Rising Inflation  → commodities + TIPS (stagflation — worst for stocks)
  Season D: Falling Growth + Falling Inflation → bonds + gold (deflationary recession)

SECTOR BY CYCLE PHASE:
  Early Expansion:  Technology, Financials, Consumer Discretionary
  Mid Expansion:    Industrials, Materials, Real Estate
  Late Expansion:   Energy, Commodities, Healthcare
  Contraction:      Utilities, Consumer Staples, Healthcare
  Deleveraging:     Gold, Cash, Short-duration bonds

BIG CYCLE CONTEXT (April 2026):
  - World Order transitioning Stage 5 → Stage 6 (geopolitical disorder rising)
  - USD hegemony under pressure, gold outperforming fiat assets
  - Trade wars + technology wars escalating
  - AI sector in early bubble stage (Dalio, 2025)
  - US federal debt/GDP at historic highs → Rule 1 violation risk

OUTPUT — JSON only, no extra text:
{
  "regime":     "<RISK_ON|RISK_OFF|DELEVERAGING>",
  "cycle":      "<EARLY_EXPANSION|MID_EXPANSION|LATE_EXPANSION|CONTRACTION|DELEVERAGING>",
  "season":     "<A_GROWTH_INFLATION|B_GROWTH_DISINFLATION|C_STAGFLATION|D_DEFLATION>",
  "macro_take": "<สรุปแบบ Dalio เป็นภาษาไทยเข้าใจง่าย อธิบายว่าตลาด/เศรษฐกิจอยู่ในช่วงไหน และหุ้นตัวนี้เหมาะหรือไม่ในสภาพแวดล้อมปัจจุบัน ถ้าใช้ศัพท์เทคนิคให้ขยายความในวงเล็บ เป้าหมาย: คนที่ลงทุนอยู่แต่ไม่รู้ศัพท์ขั้นสูงอ่านแล้วเข้าใจทันที>",
  "key_risk":   "<ความเสี่ยง macro สำคัญที่สุด อธิบายให้นักลงทุนทั่วไปเข้าใจว่าเศรษฐกิจ/ตลาดกำลังเผชิญอะไร ใช้ภาษาไทยตรงไปตรงมา หรือ null>"
}

กฎ: เขียนภาษาไทยเข้าใจง่าย ถ้าใช้ศัพท์อังกฤษต้องขยายความในวงเล็บทันที ห้ามใช้ RISK_OFF / deleveraging / stagflation โดยไม่อธิบาย ให้บอกแทนว่า เช่น 'ตลาดกำลังปรับตัวลง นักลงทุนหนีไปถือเงินสด (RISK_OFF)' หรือ 'เงินเฟ้อสูงแต่เศรษฐกิจชะลอพร้อมกัน (stagflation)'"""

_ADVISOR_SYSTEM = """คุณคือ AlphaForge Advisor — ที่ปรึกษาการลงทุนที่ผสาน 2 แนวคิด:
🎩 Buffett: ลงทุนในธุรกิจดี ราคาถูกกว่ามูลค่าจริง ถือยาว
🌐 Dalio: อ่านวัฏจักรเศรษฐกิจ จัดพอร์ตให้รอดทุกสภาพตลาด

บริบทตลาด (เมษายน 2026):
• World Order Stage 5→6: geopolitical disorder, USD อ่อน, ทองคำ outperform
• US debt/GDP historic high → Dalio Rule 1 violation risk
• AI sector: early bubble (Dalio 2025), trade wars ยังคุกรุ่น
• ตลาด US: late expansion → สัญญาณ contraction เริ่มปรากฏ
• Economic season: C (Stagflation risk) หรือ D (Deflation) มีโอกาสสูง

Watchlist: AAPL, MSFT, NVDA, GOOGL, TSLA, SPY

รูปแบบคำตอบ (HTML Telegram):
• ขึ้นต้นด้วย emoji + หัวข้อ <b>ตัวหนา</b>
• แยก Buffett view และ Dalio view ชัดเจน
• ไม่เกิน 180 คำ
• ลงท้ายด้วย <b>👉 สรุป:</b> เสมอ — 1-2 ประโยค actionable
• ถ้าถามหุ้นเฉพาะตัว → แนะนำพิมพ์ ticker รับข้อมูล real-time

ภาษา: ไทยเข้าใจง่าย ถ้าใช้ศัพท์เทคนิคให้อธิบายสั้นๆ ในวงเล็บ เช่น 'คูเมือง (ความได้เปรียบที่คู่แข่งลอกยาก)' หรือ 'ตลาดขาลง (RISK_OFF)' หรือ 'วงจรหนี้ระยะสั้น (debt cycle)'"""

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_TG_LEN = 4096                                        # Telegram hard limit
_SSM_CLIENT = None
_API_KEY: str | None = None          # cached per Lambda lifecycle (avoids 3x SSM per request)
_VALID_TICKER = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")   # AAPL, BRK-B


# ───── TECHNICAL HELPERS ─────

def _kama(close: Any, length: int = 10) -> Any:
    """Kaufman Adaptive Moving Average — adapts speed to market noise/trending.

    Initialization: first `length` bars seeded with SMA to match standard spec.
    """
    fast_sc = 2.0 / 3      # fast period = 2
    slow_sc = 2.0 / 31     # slow period = 30
    change = (close - close.shift(length)).abs()
    volatility = close.diff().abs().rolling(length).sum()
    er = (change / volatility.where(volatility > 0, 1.0)).clip(0, 1)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
    kama = close.copy().astype(float)
    # Seed the first `length` bars with the SMA so early KAMA values are stable
    sma_seed = float(close.iloc[:length].mean())
    for i in range(length):
        kama.iat[i] = sma_seed
    for i in range(length, len(close)):
        kama.iat[i] = kama.iat[i - 1] + float(sc.iat[i]) * (float(close.iat[i]) - kama.iat[i - 1])
    return kama


# ───── AWS HELPERS ─────

def _ssm() -> Any:
    global _SSM_CLIENT
    if _SSM_CLIENT is None:
        _SSM_CLIENT = boto3.client("ssm", region_name="us-east-1")
    return _SSM_CLIENT


def _get_secret(name: str) -> str:
    """Fetch secret from SSM Parameter Store."""
    resp = _ssm().get_parameter(Name=name, WithDecryption=True)
    return resp["Parameter"]["Value"]


def _get_api_key() -> str:
    """Return Anthropic API key — fetched once and cached for Lambda warm invocations."""
    global _API_KEY
    if _API_KEY is None:
        _API_KEY = _get_secret("/alpha-forge/ANTHROPIC_API_KEY").strip()
    return _API_KEY


# ───── TELEGRAM HELPERS ─────

def _send(token: str, chat_id: int | str, text: str) -> None:
    """Send HTML message to Telegram. Truncates to 4096-char limit. Logs on failure but never raises."""
    if len(text) > _MAX_TG_LEN:
        text = text[:_MAX_TG_LEN - 40] + "\n\n<i>...(ข้อความยาวเกิน — ตัดบางส่วน)</i>"
    try:
        resp = requests.post(
            _TELEGRAM_API.format(token=token),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if not resp.ok:
            logger.warning(json.dumps({"action": "telegram_send_failed", "status": resp.status_code,
                                       "preview": text[:80]}))
    except Exception as e:
        logger.warning(json.dumps({"action": "telegram_send_error", "error": str(e)}))


# ───── BUFFETT TAKE ─────

def _get_buffett_take(symbol: str, company: str, info: dict) -> dict:
    """Generate Buffett-style verdict via Claude Haiku. Falls back to neutral on failure."""
    roe = info.get("returnOnEquity")
    de = info.get("debtToEquity")
    om = info.get("operatingMargins")
    nm = info.get("profitMargins")
    cr = info.get("currentRatio")
    pe = info.get("trailingPE")
    pb = info.get("priceToBook")
    peg = info.get("pegRatio")
    rev_growth = info.get("revenueGrowth")
    eps_growth = info.get("earningsGrowth")
    fcf = info.get("freeCashflow")
    sector = info.get("sector", "Unknown")
    industry = info.get("industry", "Unknown")

    def _fmt(v: float | None, pct: bool = False) -> str:
        if v is None:
            return "N/A"
        return f"{v*100:.1f}%" if pct else f"{v:.2f}"

    def _check(ok: bool | None) -> str:
        if ok is True:
            return "✅"
        if ok is False:
            return "❌"
        return "—"

    checks = {
        "roe_ok": roe >= 0.15 if roe is not None else None,
        "debt_ok": de <= 0.5 if de is not None else None,
        "margin_ok": om >= 0.20 if om is not None else None,
        "net_margin_ok": nm >= 0.10 if nm is not None else None,
        "liquid_ok": cr >= 1.5 if cr is not None else None,
        "pe_ok": pe <= 25 if pe is not None else None,
        "growth_ok": rev_growth >= 0.05 if rev_growth is not None else None,
        "fcf_ok": fcf > 0 if fcf is not None else None,
    }
    passed = sum(1 for v in checks.values() if v is True)
    total = sum(1 for v in checks.values() if v is not None)

    prompt = (
        f"Stock: {symbol} ({company})\n"
        f"Sector: {sector} | Industry: {industry}\n\n"
        f"BUFFETT ALGORITHM ({passed}/{total} checks passed):\n"
        f"  ROE:              {_fmt(roe, pct=True)} (target ≥15%)  {_check(checks['roe_ok'])}\n"
        f"  Debt/Equity:      {_fmt(de)} (target ≤0.5)  {_check(checks['debt_ok'])}\n"
        f"  Operating Margin: {_fmt(om, pct=True)} (target ≥20%)  {_check(checks['margin_ok'])}\n"
        f"  Net Margin:       {_fmt(nm, pct=True)} (target ≥10%)  {_check(checks['net_margin_ok'])}\n"
        f"  Current Ratio:    {_fmt(cr)} (target ≥1.5)  {_check(checks['liquid_ok'])}\n"
        f"  P/E Ratio:        {_fmt(pe)} (≤15=value, >25=expensive)  {_check(checks['pe_ok'])}\n"
        f"  P/B Ratio:        {_fmt(pb)} (≤1.5=deep value)\n"
        f"  PEG Ratio:        {_fmt(peg)} (≤1.0=GARP)\n"
        f"  Revenue Growth:   {_fmt(rev_growth, pct=True)} (target ≥5%)  {_check(checks['growth_ok'])}\n"
        f"  EPS Growth:       {_fmt(eps_growth, pct=True)}\n"
        f"  Free Cash Flow:   {'${:,.0f}'.format(fcf) if fcf is not None else 'N/A'}  {_check(checks['fcf_ok'])}\n\n"
        f"Apply your 6 mental models and give your Buffett verdict on {symbol}."
    )

    try:
        api_key = _get_api_key()
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 800,
                "temperature": 0,
                "system": _BUFFETT_SYSTEM,
                "messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": "{"},  # prefill — forces JSON-only output
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = "{" + resp.json()["content"][0]["text"]  # re-attach prefill character
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"no JSON in Buffett response: {raw[:200]}")
        parsed = json.loads(raw[start:end + 1])
        return {
            "verdict":    parsed.get("verdict", "NEUTRAL"),
            "moat":       parsed.get("moat", "UNKNOWN"),
            "valuation":  parsed.get("valuation", "UNKNOWN"),
            "one_liner":  parsed.get("one_liner", ""),
            "key_concern": parsed.get("key_concern"),
        }
    except Exception as e:
        logger.error(json.dumps({"action": "buffett_take_failed", "symbol": symbol, "error": str(e)}))
        return {"verdict": "NEUTRAL", "moat": "UNKNOWN", "valuation": "UNKNOWN", "one_liner": "", "key_concern": None}


# ───── DALIO TAKE ─────

def _get_dalio_take(symbol: str, company: str, info: dict) -> dict:
    """Generate Dalio macro verdict via Claude Haiku. Falls back to neutral on failure."""
    try:
        sector = info.get("sector", "Unknown")
        industry = info.get("industry", "Unknown")
        country = info.get("country", "Unknown")
        revenue_growth = info.get("revenueGrowth")
        de = info.get("debtToEquity")
        pe = info.get("trailingPE")
        beta = info.get("beta")
        om = info.get("operatingMargins")
        cr = info.get("currentRatio")
        fcf = info.get("freeCashflow")
        market_cap = info.get("marketCap")

        def _fmt(v: float | None, pct: bool = False, suffix: str = "") -> str:
            if v is None:
                return "N/A"
            return f"{v*100:.1f}%{suffix}" if pct else f"{v:.2f}{suffix}"

        def _fmt_cap(v: float | None) -> str:
            if v is None:
                return "N/A"
            if v >= 1e12:
                return f"${v/1e12:.1f}T"
            if v >= 1e9:
                return f"${v/1e9:.1f}B"
            return f"${v/1e6:.0f}M"

        # Debt burden classification (Dalio Rule 1 proxy)
        if de is None:
            debt_signal = "N/A"
        elif de > 2.0:
            debt_signal = "HIGH — late-cycle risk (Rule 1 violation)"
        elif de > 0.5:
            debt_signal = "MODERATE"
        else:
            debt_signal = "LOW — healthy"

        # P/E bubble signal (Dalio bubble framework)
        if pe is None or pe <= 0:
            pe_signal = "N/A"
        elif pe > 30:
            pe_signal = "HIGH — bubble risk"
        elif pe > 15:
            pe_signal = "MODERATE — late expansion"
        else:
            pe_signal = "LOW — value zone"

        prompt = (
            f"Stock: {symbol} ({company})\n"
            f"Sector: {sector} | Industry: {industry} | HQ: {country}\n"
            f"Market Cap: {_fmt_cap(market_cap)} | Beta: {_fmt(beta)}\n\n"
            f"DEBT & VALUATION (corporate debt cycle proxies):\n"
            f"  Debt/Equity:      {_fmt(de)} → {debt_signal}\n"
            f"  P/E Ratio:        {_fmt(pe)} → {pe_signal}\n"
            f"  Operating Margin: {_fmt(om, pct=True)}\n"
            f"  Revenue Growth:   {_fmt(revenue_growth, pct=True)}\n"
            f"  Current Ratio:    {_fmt(cr)}\n"
            f"  Free Cash Flow:   {'${:,.0f}'.format(fcf) if fcf is not None else 'N/A'}\n\n"
            f"MACRO CONTEXT (April 2026):\n"
            f"  - World Order: Stage 5→6 transition (geopolitical disorder, USD pressure)\n"
            f"  - Gold outperforming, trade wars + tech wars escalating\n"
            f"  - AI sector in early bubble stage\n"
            f"  - US federal debt/GDP at historic highs (Rule 1 violation risk)\n\n"
            f"Apply your 5 frameworks to {symbol}: "
            f"(1) debt cycle stage, (2) economic season A/B/C/D, "
            f"(3) sector positioning in current cycle, "
            f"(4) Big Cycle impact on this company, "
            f"(5) Three Core Rules check."
        )

        api_key = _get_api_key()
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 600,          # Dalio JSON is small — 600 more than enough, avoids cut-off
                "temperature": 0,
                "system": _DALIO_SYSTEM,
                "messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": "{"},  # prefill — forces JSON-only output
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        resp_json = resp.json()
        raw_text = resp_json["content"][0]["text"]
        stop_reason = resp_json.get("stop_reason", "unknown")
        raw = "{" + raw_text  # re-attach prefill character

        # Diagnostic log — helps confirm what model returns and why
        logger.info(json.dumps({
            "action": "dalio_raw",
            "symbol": symbol,
            "stop_reason": stop_reason,
            "raw_len": len(raw),
            "preview": raw[:300],
        }))

        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"no JSON brackets in Dalio response: {raw[:200]}")

        json_str = raw[start:end + 1]
        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
            # Model output full JSON despite prefill (double-brace: "{{"...) — strip leading brace
            if len(json_str) > 1 and json_str[1] == "{":
                inner_end = json_str.rfind("}")
                parsed = json.loads(json_str[1:inner_end + 1])
            else:
                raise
        return {
            "regime":    parsed.get("regime", "RISK_OFF"),
            "cycle":     parsed.get("cycle", "CONTRACTION"),
            "season":    parsed.get("season", "D_DEFLATION"),
            "macro_take": parsed.get("macro_take", ""),
            "key_risk":  parsed.get("key_risk"),
        }
    except Exception as e:
        logger.error(json.dumps({"action": "dalio_take_failed", "symbol": symbol, "error": str(e)}))
        return {"regime": "RISK_OFF", "cycle": "CONTRACTION", "season": "D_DEFLATION", "macro_take": "", "key_risk": None}


# ───── ANALYSIS ─────

def _analyze(symbol: str) -> dict:
    """Fetch OHLCV and compute technical indicators for any US ticker."""
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="60d", interval="1d")

    if df is None or df.empty:
        raise ValueError(f"No market data for {symbol}")
    if len(df) < 21:
        raise ValueError(f"Insufficient price history for {symbol} (need ≥21 days)")

    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    volume = df["Volume"]

    # Price
    price = round(float(close.iloc[-1]), 2)
    prev_close = float(close.iloc[-2])
    change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close != 0 else 0.0

    # KAMA (Kaufman Adaptive MA — replaces EMA trend filter)
    kama_series = _kama(close, length=10)
    kama_val = round(float(kama_series.iloc[-1]), 2)
    kama_bull = price > kama_val

    # RSI 14 — Wilder's smoothed average (ewm com=13 ≡ span=14 with adjust=False)
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    _gain_val = float(gain.iloc[-1])
    _loss_val = float(loss.iloc[-1])
    if _loss_val == 0 and _gain_val == 0:
        rsi = 50.0   # flat market — no momentum either way
    elif _loss_val == 0:
        rsi = 100.0  # only gains, no losses
    else:
        rsi = round(100 - (100 / (1 + _gain_val / _loss_val)), 1)

    # MACD (12/26/9)
    macd_line = close.ewm(span=12).mean() - close.ewm(span=26).mean()
    signal_line = macd_line.ewm(span=9).mean()
    macd_bull = float(macd_line.iloc[-1]) > float(signal_line.iloc[-1])

    # VWAP (20-day proxy)
    vol_sum_20 = volume.rolling(20).sum().replace(0, 1)
    vwap = round(float(((close * volume).rolling(20).sum() / vol_sum_20).iloc[-1]), 2)
    vwap_above = price > vwap

    # Volume ratio vs 20-day avg
    avg_vol = float(volume.rolling(20).mean().iloc[-1])
    vol_ratio = round(float(volume.iloc[-1]) / avg_vol, 2) if avg_vol > 0 else 1.0

    # CMF (Chaikin Money Flow — volume-weighted buying/selling pressure)
    # Minimum 0.01 (1 cent) to avoid inflating CMF on gap days where high==low
    hl_range = (high - low).replace(0, 0.01)
    mfv = ((close - low) - (high - close)) / hl_range * volume
    cmf_raw = mfv.rolling(20).sum() / volume.rolling(20).sum().replace(0, 1)
    cmf_val = round(float(cmf_raw.iloc[-1]), 3)
    cmf_positive = cmf_val > 0.05

    # Squeeze Momentum (LazyBear — energy build + release detector)
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2.0 * std20
    bb_lower = sma20 - 2.0 * std20
    atr20 = (high - low).rolling(20).mean()
    kc_upper = sma20 + 1.5 * atr20
    kc_lower = sma20 - 1.5 * atr20
    try:
        sqz_on = bool(bb_lower.iloc[-1] > kc_lower.iloc[-1] and bb_upper.iloc[-1] < kc_upper.iloc[-1])
    except (TypeError, ValueError):
        sqz_on = False
    h20 = high.rolling(20).max()
    l20 = low.rolling(20).min()
    avg_hl = (h20 + l20) / 2
    sqz_delta = close - (avg_hl + sma20) / 2
    sqz_pos = float(sqz_delta.iloc[-1]) > 0

    # Scoring (8 factors — rebalanced for KAMA + CMF + Squeeze)
    score = sum([
        0.20 if kama_bull else 0.0,            # KAMA adaptive trend
        0.15 if 30 < rsi < 70 else 0.0,        # RSI healthy range (standard 30–70)
        0.15 if macd_bull else 0.0,             # MACD momentum
        0.10 if vwap_above else 0.0,            # VWAP position
        0.10 if cmf_positive else 0.0,          # CMF smart money inflow
        0.10 if sqz_pos else 0.0,               # Squeeze positive momentum
        0.10 if change_pct > 0 else 0.0,        # Daily change direction
        0.10 if vol_ratio > 1.2 else 0.0,       # Volume confirmation
    ])
    score = round(score, 3)

    if score >= 0.75:
        signal = "STRONG_BUY"
    elif score >= 0.55:
        signal = "BUY"
    elif score >= 0.35:
        signal = "WATCH"
    else:
        signal = "NEUTRAL"

    # Company info + fundamentals (graceful fallback — some tickers have no info)
    try:
        raw_info = ticker.info
        info = raw_info if isinstance(raw_info, dict) else {}
    except Exception:
        info = {}
    company = info.get("shortName") or info.get("longName") or symbol

    # Buffett + Dalio — run in parallel to halve latency (~30s → ~15s)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as _pool:
        _bf = _pool.submit(_get_buffett_take, symbol, company, info)
        _dl = _pool.submit(_get_dalio_take, symbol, company, info)
        buffett = _bf.result()
        dalio   = _dl.result()

    return {
        "symbol":       symbol,
        "company":      company,
        "price":        price,
        "change_pct":   change_pct,
        "score":        score,
        "signal":       signal,
        "rsi":          rsi,
        "kama_val":     kama_val,
        "kama_bull":    kama_bull,
        "macd_bull":    macd_bull,
        "vwap":         vwap,
        "vwap_above":   vwap_above,
        "vol_ratio":    vol_ratio,
        "cmf_val":      cmf_val,
        "cmf_positive": cmf_positive,
        "sqz_on":       sqz_on,
        "sqz_pos":      sqz_pos,
        "buffett":      buffett,
        "dalio":        dalio,
    }


# ───── FORMATTING ─────

def _format(r: dict) -> str:
    """Format analysis result as Telegram HTML."""
    emoji_map = {"STRONG_BUY": "🚀", "BUY": "📈", "WATCH": "👀", "NEUTRAL": "➖"}
    emoji = emoji_map.get(r["signal"], "📊")
    change_icon = "🟢" if r["change_pct"] >= 0 else "🔴"
    change_str = f"{'+' if r['change_pct'] >= 0 else ''}{r['change_pct']}%"

    rsi_note = ""
    if r["rsi"] > 70:
        rsi_note = " ⚠️ Overbought"
    elif r["rsi"] < 30:
        rsi_note = " ⚠️ Oversold"

    sqz_on_flag = r.get("sqz_on", False)
    sqz_pos_flag = r.get("sqz_pos", False)
    if sqz_on_flag and sqz_pos_flag:
        sqz_str = "⚡ ON — bullish build-up"
    elif not sqz_on_flag and sqz_pos_flag:
        sqz_str = "🚀 Released ↑"
    elif sqz_on_flag:
        sqz_str = "⚡ ON — bearish"
    else:
        sqz_str = "— Momentum ↓"

    cmf_v = r.get("cmf_val", 0.0)
    cmf_icon = "✅" if r.get("cmf_positive") else ("❌" if cmf_v < -0.05 else "—")

    company = _html.escape(r["company"])
    lines = [
        f"{emoji} <b>{r['symbol']}</b> — {company}",
        "",
        f"💵 ${r['price']}  {change_icon} {change_str}",
        "",
        f"Signal: <code>{r['signal']}</code>",
        f"Score:  <code>{r['score']:.3f}</code>",
        "",
        "<b>Indicators:</b>",
        f"• KAMA:      {'Above ✅' if r.get('kama_bull') else 'Below ❌'} <code>${r.get('kama_val', 0)}</code>",
        f"• RSI 14:    <code>{r['rsi']}</code>{rsi_note}",
        f"• MACD:      {'Bullish ✅' if r['macd_bull'] else 'Bearish ❌'}",
        f"• VWAP:      {'Above ✅' if r['vwap_above'] else 'Below ❌'} <code>${r.get('vwap', 0):.2f}</code>",
        f"• CMF:       <code>{cmf_v:+.3f}</code> {cmf_icon}",
        f"• Squeeze:   {sqz_str}",
        f"• Volume:    <code>{r['vol_ratio']}x</code> avg",
    ]

    # Buffett section
    b = r.get("buffett", {})
    if b.get("one_liner"):
        verdict_icon = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(b.get("verdict", ""), "⚪")
        moat_map = {"WIDE": "🏰 กว้าง", "NARROW": "🔷 แคบ", "NONE": "❌ ไม่มี", "UNKNOWN": "❓ ไม่ทราบ"}
        moat_label = moat_map.get(b.get("moat", "UNKNOWN"), b.get("moat", "UNKNOWN"))
        val_map = {"UNDERVALUED": "💚 ราคาถูก", "FAIR": "🟡 ราคาพอดี", "OVERVALUED": "🔴 ราคาแพง"}
        val_str = f" | {val_map.get(b.get('valuation', ''), b.get('valuation', ''))}" if b.get("valuation") and b.get("valuation") != "UNKNOWN" else ""
        lines += [
            "",
            f'🎩 <b>Buffett Take</b>  {verdict_icon} {b.get("verdict", "NEUTRAL")} | คูเมือง: {moat_label}{val_str}',
            f'<i>{_html.escape(b["one_liner"])}</i>',
        ]
        if b.get("key_concern"):
            lines.append(f"⚠️ ความเสี่ยง: {_html.escape(b['key_concern'])}")

    # Dalio section
    d = r.get("dalio", {})
    if d.get("macro_take"):
        regime_map = {"RISK_ON": "🟢 ตลาดขาขึ้น", "RISK_OFF": "🔴 ตลาดระวังตัว", "DELEVERAGING": "⚫ ช่วงลดหนี้"}
        regime_label = regime_map.get(d.get("regime", ""), d.get("regime", ""))
        season_map = {
            "A_GROWTH_INFLATION": "A — เติบโต+เงินเฟ้อ",
            "B_GROWTH_DISINFLATION": "B — เติบโต+เงินเฟ้อลด",
            "C_STAGFLATION": "C — ชะลอ+เงินเฟ้อสูง",
            "D_DEFLATION": "D — ชะลอ+เงินเฟ้อลด",
        }
        season_label = season_map.get(d.get("season", ""), d.get("season", ""))
        cycle_map = {
            "EARLY_EXPANSION": "ต้นวัฏจักรขาขึ้น",
            "MID_EXPANSION": "กลางวัฏจักรขาขึ้น",
            "LATE_EXPANSION": "ปลายวัฏจักรขาขึ้น",
            "CONTRACTION": "วัฏจักรหดตัว",
            "DELEVERAGING": "ช่วงลดหนี้",
        }
        cycle_label = cycle_map.get(d.get("cycle", ""), d.get("cycle", ""))
        lines += [
            "",
            f'🌐 <b>Ray Dalio Take</b>  {regime_label}',
            f'ช่วง: <code>{cycle_label}</code> | ฤดู: <code>{season_label}</code>',
            f'<i>{_html.escape(d["macro_take"])}</i>',
        ]
        if d.get("key_risk"):
            lines.append(f"⚠️ ความเสี่ยง: {_html.escape(d['key_risk'])}")

    symbol_safe = _html.escape(r["symbol"])
    lines += [
        "",
        f'🔗 <a href="https://www.tradingview.com/chart/?symbol={symbol_safe}">TradingView Chart</a>',
    ]
    return "\n".join(lines)


# ───── CONVERSATIONAL ADVISOR ─────

def _handle_question(text: str) -> str:
    """Answer open-ended investment questions using Buffett + Dalio framework."""
    try:
        api_key = _get_api_key()
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "system": _ADVISOR_SYSTEM,
                "messages": [{"role": "user", "content": text}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"].strip()
    except Exception as e:
        logger.warning(json.dumps({"action": "advisor_failed", "error": str(e)}))
        return "❌ ไม่สามารถตอบได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง"


_HELP_TEXT = (
    "👋 <b>AlphaForge Bot</b>\n\n"
    "วิเคราะห์หุ้น US แบบ Real-time ด้วย AI ในมุมของ Warren Buffett + Ray Dalio\n\n"
    "<b>พิมพ์ ticker เพื่อวิเคราะห์:</b>\n"
    "<code>AAPL</code>  <code>NVDA</code>  <code>TSLA</code>\n"
    "<code>META</code>  <code>SPY</code>   <code>QQQ</code>\n"
    "<code>AMD</code>   <code>PLTR</code>  <code>BRK-B</code>\n\n"
    "<b>หรือถามคำถามได้เลย เช่น:</b>\n"
    "• ช่วงนี้น่าลงทุนไหม?\n"
    "• แนะนำหุ้นตัวไหนในตลาดนี้?\n"
    "• วางแผน port ยังไงดี?\n"
    "• NVDA กับ AMD ตัวไหนน่าสนใจกว่า?"
)


# ───── LAMBDA HANDLER ─────

def handler(event: dict, context: Any) -> dict:
    """Telegram webhook entry point."""
    token: str | None = None
    chat_id: int | str | None = None
    symbol = ""

    try:
        body = json.loads(event.get("body") or "{}")
        message = body.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        original_text = (message.get("text") or "").strip()[:500]  # cap to prevent abuse
        text = original_text.upper()

        if not chat_id or not text:
            return {"statusCode": 200, "body": "ok"}

        token = _get_secret("/alpha-forge/TELEGRAM_BOT_TOKEN").strip()

        # Commands
        if text.startswith("/"):
            if text in ("/START", "/HELP"):
                _send(token, chat_id, _HELP_TEXT)
            else:
                _send(token, chat_id, "❓ ไม่รู้จัก command นี้\nพิมพ์ /help เพื่อดูวิธีใช้")
            return {"statusCode": 200, "body": "ok"}

        # Ticker → วิเคราะห์
        if _VALID_TICKER.match(text):
            symbol = text
            _send(token, chat_id, f"⏳ กำลังวิเคราะห์ <b>{symbol}</b>...")
            result = _analyze(symbol)
            _send(token, chat_id, _format(result))
            logger.info(json.dumps({"action": "analyzed", "symbol": symbol, "signal": result["signal"]}))
            return {"statusCode": 200, "body": "ok"}

        # คำถามทั่วไป → Conversational advisor
        _send(token, chat_id, "💭 กำลังคิด...")
        answer = _handle_question(original_text)
        _send(token, chat_id, answer)
        logger.info(json.dumps({"action": "advisor", "question": original_text[:50]}))

    except ValueError as e:
        logger.warning(json.dumps({"action": "not_found", "symbol": symbol, "error": str(e)}))
        if token and chat_id:
            _send(token, chat_id,
                f"❌ ไม่พบข้อมูลของ <b>{symbol}</b>\n"
                "ตรวจสอบ ticker อีกครั้ง หรือหุ้นอาจ delisted แล้ว")

    except Exception as e:
        logger.error(json.dumps({"action": "error", "symbol": symbol, "error": str(e)}))
        if token and chat_id:
            _send(token, chat_id, "❌ เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้ง")

    return {"statusCode": 200, "body": "ok"}
