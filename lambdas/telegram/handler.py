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
import time
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
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

_BUFFETT_SYSTEM_MAX = """You are Warren Buffett giving a detailed pre-trade verdict. MAX MODE — analyze the data provided. Do NOT invent numbers not given. Do NOT name competitors unless you are certain. Do NOT compute DCF from scratch — use the P/E and FCF data given.

BUFFETT ALGORITHM (evaluate each criterion given — skip if N/A):
  ROE ≥ 15%: high = durable advantage | low = commodity business
  Debt/Equity ≤ 0.5: high = fragile | low = fortress balance sheet
  Operating Margin ≥ 20%: high = pricing power | low = no moat evidence
  Net Margin ≥ 10%: real after-tax profitability
  Current Ratio ≥ 1.5: short-term safety
  Revenue Growth ≥ 5%: business expanding
  EPS Growth ≥ 8%: earnings compounding
  P/E: ≤15=value, 15-25=fair, >25=expensive

OUTPUT — JSON only, single-line strings, no internal newlines:
{
  "verdict":             "<BULLISH|NEUTRAL|BEARISH>",
  "moat":                "<WIDE|NARROW|NONE|UNKNOWN>",
  "valuation":           "<UNDERVALUED|FAIR|OVERVALUED>",
  "moat_analysis":       "<2-3 ประโยคภาษาไทย: แหล่งที่มา moat จากข้อมูลที่มี และความยั่งยืน — อ้างตัวเลขจริงที่ให้มา>",
  "fundamental_verdict": "<2-3 ประโยคภาษาไทย: สรุปตัวเลขที่ผ่านและไม่ผ่าน Buffett algorithm และความหมายเชิงคุณภาพ>",
  "valuation_verdict":   "<2-3 ประโยคภาษาไทย: P/E และ FCF บอกอะไรเกี่ยวกับ valuation และ margin of safety โดยประมาณ>",
  "action":              "<2 ประโยคภาษาไทย: Buffett จะซื้อ/ถือ/รอ และเงื่อนไขที่จะเปลี่ยนใจ>",
  "key_concern":         "<1-2 ความเสี่ยงเฉพาะของบริษัทนี้ ภาษาไทย>"
}
กฎ: single-line strings เท่านั้น ห้าม \\n ภายใน value อ้างตัวเลขที่ให้มาเท่านั้น ห้ามแต่งข้อมูลใหม่"""

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

OUTPUT — JSON only, no extra text, no newlines inside strings:
{
  "regime":     "<RISK_ON|RISK_OFF|DELEVERAGING>",
  "cycle":      "<EARLY_EXPANSION|MID_EXPANSION|LATE_EXPANSION|CONTRACTION|DELEVERAGING>",
  "season":     "<A_GROWTH_INFLATION|B_GROWTH_DISINFLATION|C_STAGFLATION|D_DEFLATION>",
  "macro_take": "<ประโยคเดียว ไม่เกิน 25 คำ ภาษาไทย — บอก regime ปัจจุบันและผลต่อหุ้นนี้ ถ้าใช้ศัพท์ให้ขยายในวงเล็บสั้นๆ>",
  "key_risk":   "<ประโยคเดียว ไม่เกิน 15 คำ ภาษาไทย — ความเสี่ยง macro หลัก หรือ null>"
}

กฎเหล็ก: macro_take ต้องเป็น 1 ประโยคเท่านั้น ห้ามขึ้นบรรทัดใหม่ ห้ามใช้เลข 1. 2. 3. ห้ามเกิน 25 คำ"""

_DALIO_SYSTEM_MAX = """You are Ray Dalio giving a detailed macro context for a stock. MAX MODE — use the data provided. Do NOT state specific Fed funds rates or yield curve values unless given in the prompt.

FOUR SEASONS (identify current from macro context given):
  Season A: Rising Growth + Rising Inflation → stocks + commodities
  Season B: Rising Growth + Falling Inflation → stocks + bonds (best for equities)
  Season C: Falling Growth + Rising Inflation → commodities + TIPS (stagflation, worst)
  Season D: Falling Growth + Falling Inflation → bonds + gold

SECTOR ROTATION: Technology/Financials/ConsDisc = Early Expansion | Industrials/Materials = Mid | Energy/Commodities/Healthcare = Late | Utilities/Staples = Contraction | Gold/Cash = Deleveraging

OUTPUT — JSON only, single-line strings, no internal newlines:
{
  "regime":              "<RISK_ON|RISK_OFF|DELEVERAGING>",
  "cycle":               "<EARLY_EXPANSION|MID_EXPANSION|LATE_EXPANSION|CONTRACTION|DELEVERAGING>",
  "season":              "<A_GROWTH_INFLATION|B_GROWTH_DISINFLATION|C_STAGFLATION|D_DEFLATION>",
  "cycle_analysis":      "<2-3 ประโยคภาษาไทย: บริษัทนี้อยู่จุดไหนของ cycle — อ้างข้อมูล D/E, beta, sector จาก prompt>",
  "sector_positioning":  "<2-3 ประโยคภาษาไทย: sector นี้ได้เปรียบ/เสียเปรียบใน season ปัจจุบัน และทำไม>",
  "portfolio_action":    "<2 ประโยคภาษาไทย: สัดส่วนใน All-Weather portfolio และ trigger ที่จะเปลี่ยน>",
  "macro_take":          "<1 ประโยค ≤20 คำ ภาษาไทย: สรุป macro verdict>",
  "key_risk":            "<1 ประโยค ภาษาไทย: ความเสี่ยง macro หลัก>"
}
กฎ: single-line strings เท่านั้น ห้าม \\n ภายใน value ใช้เฉพาะข้อมูลที่ให้มาใน prompt"""

_SMART_ROUTER_SYSTEM = """You are AlphaForge — an AI investment advisor.

STEP 1 — SELECT FRAMEWORK (do this first, before writing anything):

Read the question and match to ONE rule below. Use the FIRST rule that matches.

RULE 1 — Saylor ONLY:
  Keywords: BTC, Bitcoin, crypto, ซาโตชิ, satoshi, digital gold, store of value, เงินดิจิตอล, สกุลเงินดิจิทัล
  Use: ₿ Saylor

RULE 2 — Bezos ONLY:
  Keywords: Amazon, AWS, flywheel, platform, startup, สตาร์ทอัพ, growth company, บริษัทเติบโต, นวัตกรรม, Day 1, customer obsession, e-commerce
  Use: 📦 Bezos

RULE 3 — Buffett ONLY:
  Keywords: moat, P/E, ROE, ปัจจัยพื้นฐาน, มูลค่าหุ้น, intrinsic value, dividend, ปันผล, ผู้บริหาร, งบการเงิน, valuation, ราคาถูก, ราคาแพง
  Use: 🎩 Buffett

RULE 4 — Dalio ONLY:
  Keywords: เศรษฐกิจ, Fed, ดอกเบี้ย, เงินเฟ้อ, recession, วิกฤต, วัฏจักร, macro, debt cycle, GDP, bond, gold, ทองคำ, currency, เงินบาท
  Use: 🌐 Dalio

RULE 5 — Dalio + Buffett (default, only if no rule above matched):
  Anything else: portfolio, เปรียบเทียบหุ้น, จัดพอร์ต, ควรซื้อหรือขาย, ช่วงนี้น่าลงทุนไหม
  Use: 🌐 Dalio + 🎩 Buffett

STEP 2 — ANSWER using selected framework voice:

🎩 Buffett: ตรงไปตรงมา มองหา moat (ความได้เปรียบที่คู่แข่งลอกยาก) ถือยาว ระวังราคาแพงกว่ามูลค่าจริง

🌐 Dalio: มองเศรษฐกิจเป็น machine อ่านวัฏจักรหนี้ จัดพอร์ตให้รอดทุก season ไม่ทำนาย exact timing

📦 Bezos: คิดระยะยาว 5–20 ปี สนใจ flywheel (กลไกที่ส่งเสริมตัวเอง) ยอมขาดทุนวันนี้เพื่อ moat ในอนาคต

₿ Saylor: Bitcoin = property ที่ดีที่สุดในโลก เงินสดเปล่า = ขาดทุนแน่นอน มอง 10–100 ปี ไม่สน volatility ระยะสั้น

OWNER CONTEXT (apply as filter):
- Time horizon: 10+ ปี, framework หลัก: Dalio macro
- Holdings: US Stocks + Gold, เปิดรับ asset อื่นถ้า macro support
- ห้ามแนะนำ all-in ใน asset เดียว

MACRO CONTEXT (เมษายน 2026):
- World Order Stage 5→6, USD อ่อน, ทองคำ outperform
- Economic season: C (stagflation) หรือ D (deflation) มีโอกาสสูง

OUTPUT FORMAT (Telegram HTML, ไม่เกิน 200 คำ):
<b>[emoji] [ชื่อ Investor]:</b> [คำตอบภาษาไทยเข้าใจง่าย]
ถ้าใช้ 2 frameworks ให้แยกชัดเจน ขึ้นบรรทัดใหม่แต่ละคน

ลงท้ายเสมอ:
<b>👉 สรุปสำหรับคุณ:</b> [1–2 ประโยค actionable]

ศัพท์เทคนิคต้องอธิบายในวงเล็บ ถ้าถามหุ้นเฉพาะตัว → แนะนำพิมพ์ ticker รับข้อมูล real-time"""

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_TG_LEN = 4096                                        # Telegram hard limit
_SSM_CLIENT = None
_DYNAMO = None
_API_KEY: str | None = None          # cached per Lambda lifecycle (avoids 3x SSM per request)
_DYNAMO_TABLE_NAME: str | None = None  # cached — avoids SSM call on every message
_VALID_TICKER = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")   # AAPL, BRK-B
_CNN_FG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
_SCAN_WATCHLIST = ["AAPL", "MSFT", "NVDA", "GOOGL", "TSLA", "SPY", "META", "AMZN", "AMD", "QQQ"]


# ───── FUNDAMENTAL HELPERS ─────

def _normalize_de(raw: float | None) -> float | None:
    """yfinance returns debtToEquity as percentage (3150 = 31.5x). Normalize to ratio."""
    return raw / 100 if raw is not None else None


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


def _get_table_name() -> str:
    """Return DynamoDB table name — from env var (injected by SAM). Cached after first call."""
    global _DYNAMO_TABLE_NAME
    if _DYNAMO_TABLE_NAME is None:
        import os
        _DYNAMO_TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "alpha-signals")
        logger.info(json.dumps({"action": "dynamo_table_resolved", "table": _DYNAMO_TABLE_NAME}))
    return _DYNAMO_TABLE_NAME


# ───── DEDUPLICATION (prevents Telegram webhook retry double-fire) ─────

def _try_claim_message(chat_id: int | str, message_id: int) -> bool:
    """
    Atomic dedup using DynamoDB conditional write.

    Telegram retries webhook updates if Lambda doesn't return 200 within ~30s.
    MAX mode (Sonnet calls) can take 40-60s → triggers retry → 2 identical responses.

    Solution: first invocation atomically inserts (symbol=__DEDUP, timestamp=chat:msg_id).
    If the record already exists → another invocation is handling it → return False → skip.

    Returns True if this invocation should process the message, False if duplicate.
    """
    try:
        table = _dynamo_resource().Table(_get_table_name())
        dedup_key = f"{chat_id}:{message_id}"
        table.put_item(
            Item={
                "symbol": "__DEDUP",
                "timestamp": dedup_key,
                "ttl": int(time.time()) + 300,  # auto-expire in 5 minutes
            },
            ConditionExpression="attribute_not_exists(#ts)",
            ExpressionAttributeNames={"#ts": "timestamp"},
        )
        return True   # Successfully claimed — process this message
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.warning(json.dumps({"action": "duplicate_message_skipped",
                                       "chat_id": str(chat_id), "message_id": message_id}))
            return False  # Already claimed by another invocation — skip
        # On unexpected error, allow processing (better to duplicate than drop)
        logger.error(json.dumps({"action": "dedup_error", "error": str(e)}))
        return True
    except Exception as e:
        logger.error(json.dumps({"action": "dedup_error", "error": str(e)}))
        return True


# ───── FEAR & GREED ─────

def _get_fear_greed() -> dict:
    """Fetch CNN Fear & Greed Index. Returns neutral dict on failure."""
    try:
        resp = requests.get(_CNN_FG_URL, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()
        value = int(data["fear_and_greed"]["score"])
        rating = str(data["fear_and_greed"]["rating"])
        if value <= 25:
            emoji, advice = "😱", "Extreme Fear — โอกาสซื้อ"
        elif value <= 44:
            emoji, advice = "😨", "Fear — ระวัง แต่มีโอกาส"
        elif value <= 55:
            emoji, advice = "😐", "Neutral"
        elif value <= 74:
            emoji, advice = "😏", "Greed — ระวังความโลภ"
        else:
            emoji, advice = "🤑", "Extreme Greed — ขายทำกำไรได้"
        return {"value": value, "rating": rating, "emoji": emoji, "advice": advice, "ok": True}
    except Exception as e:
        logger.warning(json.dumps({"action": "fg_failed", "error": str(e)}))
        return {"value": None, "rating": "UNKNOWN", "emoji": "❓", "advice": "", "ok": False}


# ───── SCAN (DynamoDB latest signals) ─────

def _dynamo_resource() -> Any:
    global _DYNAMO
    if _DYNAMO is None:
        _DYNAMO = boto3.resource("dynamodb", region_name="us-east-1")
    return _DYNAMO


def _get_scan_message() -> str:
    """Query DynamoDB for latest signal per symbol in watchlist."""
    try:
        table = _dynamo_resource().Table(_get_table_name())
    except Exception as e:
        logger.error(json.dumps({"action": "scan_dynamo_failed", "error": str(e)}))
        return "❌ ไม่สามารถเชื่อมต่อฐานข้อมูลได้"

    sig_emoji = {"STRONG_BUY": "🚀", "BUY": "📈", "WATCH": "👀", "NEUTRAL": "➖"}
    lines = ["📊 <b>AlphaForge — สัญญาณล่าสุด</b>\n"]

    strong = []
    for symbol in _SCAN_WATCHLIST:
        try:
            resp = table.query(
                KeyConditionExpression=Key("symbol").eq(symbol),
                ScanIndexForward=False,
                Limit=1,
            )
            items = resp.get("Items", [])
            if items:
                item = items[0]
                sig = item.get("signal", "NEUTRAL")
                score = item.get("score", "0.500")
                ts = item.get("timestamp", "")[:10]  # date only
                emoji = sig_emoji.get(sig, "➖")
                lines.append(f"{emoji} <b>{symbol:<6}</b> <code>{sig:<11}</code> {score}  <i>{ts}</i>")
                if sig == "STRONG_BUY":
                    strong.append(symbol)
            else:
                lines.append(f"➖ <b>{symbol}</b>  ยังไม่มีข้อมูล")
        except Exception:
            lines.append(f"➖ <b>{symbol}</b>  error")

    if strong:
        lines.append(f"\n🔥 <b>STRONG BUY:</b> {', '.join(strong)}")

    fg = _get_fear_greed()
    if fg["ok"]:
        lines.append(f"\n🌡️ Fear & Greed: <b>{fg['value']}</b> — {fg['emoji']} {fg['rating']}")
        lines.append(f"<i>{fg['advice']}</i>")

    lines.append("\n<i>พิมพ์ ticker เพื่อดูวิเคราะห์ละเอียด</i>")
    return "\n".join(lines)


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

def _get_buffett_take(symbol: str, company: str, info: dict, max_mode: bool = False) -> dict:
    """Generate Buffett-style verdict via Claude Haiku/Sonnet. Falls back to neutral on failure."""
    roe = info.get("returnOnEquity")
    de = _normalize_de(info.get("debtToEquity"))  # yfinance returns %, normalize to ratio
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

    system_prompt = _BUFFETT_SYSTEM_MAX if max_mode else _BUFFETT_SYSTEM
    model = "claude-sonnet-4-6" if max_mode else "claude-haiku-4-5-20251001"
    max_tokens = 2000 if max_mode else 800
    # Sonnet at 2000 tokens needs ~30-40s; Lambda Telegram timeout=90s, so 75s gives safe margin
    http_timeout = 75 if max_mode else 45

    def _call_anthropic(sys_prompt: str, usr_content: str, tokens: int) -> tuple[dict, str]:
        """Make one Anthropic API call. Returns (parsed_response_json, stop_reason)."""
        api_key = _get_api_key()
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": tokens,
                "temperature": 0,
                "system": sys_prompt,
                "messages": [
                    {"role": "user", "content": usr_content},
                    {"role": "assistant", "content": "{"},  # prefill — forces JSON-only output
                ],
            },
            timeout=http_timeout,
        )
        if not resp.ok:
            logger.error(json.dumps({
                "action": "buffett_api_error", "symbol": symbol, "max_mode": max_mode,
                "status": resp.status_code, "model": model, "body": resp.text[:500],
            }))
            resp.raise_for_status()
        resp_json = resp.json()
        return resp_json, resp_json.get("stop_reason", "unknown")

    def _parse_buffett_json(raw_text: str, is_max: bool) -> dict:
        raw = "{" + raw_text  # re-attach prefill character
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"no JSON in Buffett response: {raw[:200]}")
        parsed = json.loads(raw[start:end + 1])
        result: dict = {
            "verdict":    parsed.get("verdict", "NEUTRAL"),
            "moat":       parsed.get("moat", "UNKNOWN"),
            "valuation":  parsed.get("valuation", "UNKNOWN"),
            "key_concern": parsed.get("key_concern"),
            "max_mode":   is_max,
            "ok":         True,
            "degraded":   False,
            "error_reason": None,
            "model":      model,
        }
        if is_max:
            result["moat_analysis"]        = parsed.get("moat_analysis", "")
            result["fundamental_verdict"]  = parsed.get("fundamental_verdict", "")
            result["valuation_verdict"]    = parsed.get("valuation_verdict", "")
            result["action"]               = parsed.get("action", "")
            result["one_liner"]            = ""  # not used in max mode
        else:
            result["one_liner"] = parsed.get("one_liner", "")
        return result

    # Compact retry schema (used when first call is truncated or parse fails in MAX mode)
    _COMPACT_BUFFETT_SYSTEM = """You are Warren Buffett. Give a brief stock verdict.
OUTPUT — JSON only, single-line strings:
{"verdict":"<BULLISH|NEUTRAL|BEARISH>","moat":"<WIDE|NARROW|NONE|UNKNOWN>","valuation":"<UNDERVALUED|FAIR|OVERVALUED>","one_liner":"<1 ประโยคภาษาไทย>","key_concern":null}"""

    try:
        resp_json, stop_reason = _call_anthropic(system_prompt, prompt, max_tokens)
        raw_text = resp_json["content"][0]["text"]

        # Check if truncated or malformed
        need_retry = False
        parse_error: str | None = None
        if stop_reason == "max_tokens":
            need_retry = True
            parse_error = f"stop_reason=max_tokens (truncated at {max_tokens} tokens)"
        else:
            try:
                result = _parse_buffett_json(raw_text, max_mode)
                result["stop_reason"] = stop_reason
                return result
            except (json.JSONDecodeError, ValueError) as pe:
                need_retry = True
                parse_error = str(pe)

        if need_retry and max_mode:
            logger.warning(json.dumps({
                "action": "buffett_retry", "symbol": symbol, "reason": parse_error,
                "stop_reason": stop_reason,
            }))
            # Retry with compact schema — simpler, fewer tokens
            retry_resp_json, retry_stop = _call_anthropic(_COMPACT_BUFFETT_SYSTEM, prompt, 600)
            retry_text = retry_resp_json["content"][0]["text"]
            result = _parse_buffett_json(retry_text, False)  # compact schema = normal-mode fields
            result["max_mode"] = max_mode  # preserve max_mode flag
            result["stop_reason"] = retry_stop
            return result
        elif need_retry:
            # Normal mode parse error — fall through to except
            raise ValueError(parse_error or "parse failed")

        # Fallback if we somehow get here without returning
        result = _parse_buffett_json(raw_text, max_mode)
        result["stop_reason"] = stop_reason
        return result

    except Exception as e:
        logger.error(json.dumps({"action": "buffett_take_failed", "symbol": symbol,
                                 "max_mode": max_mode, "error": str(e)}))
        fallback: dict = {
            "verdict": "NEUTRAL", "moat": "UNKNOWN", "valuation": "UNKNOWN",
            "one_liner": "", "key_concern": None, "max_mode": max_mode,
            "ok": False, "degraded": True, "error_reason": str(e), "model": model,
        }
        if max_mode:
            fallback.update({"moat_analysis": "", "fundamental_verdict": "",
                             "valuation_verdict": "", "action": ""})
        return fallback


# ───── DALIO TAKE ─────

def _get_dalio_take(symbol: str, company: str, info: dict, max_mode: bool = False) -> dict:
    """Generate Dalio macro verdict via Claude Haiku (normal) or Sonnet (MAX). Falls back on failure."""
    try:
        sector = info.get("sector", "Unknown")
        industry = info.get("industry", "Unknown")
        country = info.get("country", "Unknown")
        revenue_growth = info.get("revenueGrowth")
        de = _normalize_de(info.get("debtToEquity"))  # yfinance returns %, normalize to ratio
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

        system_prompt = _DALIO_SYSTEM_MAX if max_mode else _DALIO_SYSTEM
        model = "claude-sonnet-4-6" if max_mode else "claude-haiku-4-5-20251001"
        max_tokens = 1500 if max_mode else 350  # MAX: 1500 is sufficient for shorter 2-3 sentence fields
        # Sonnet at 1500 tokens needs ~20-30s; 75s leaves safe margin within Lambda 90s timeout
        http_timeout = 75 if max_mode else 45

        # Compact retry schema for Dalio
        _COMPACT_DALIO_SYSTEM = """You are Ray Dalio. Give a brief macro verdict.
OUTPUT — JSON only, single-line strings:
{"regime":"<RISK_ON|RISK_OFF|DELEVERAGING>","cycle":"<EARLY_EXPANSION|MID_EXPANSION|LATE_EXPANSION|CONTRACTION|DELEVERAGING>","season":"<A_GROWTH_INFLATION|B_GROWTH_DISINFLATION|C_STAGFLATION|D_DEFLATION>","macro_take":"<1 ประโยคภาษาไทย>","key_risk":null}"""

        def _call_dalio_api(sys_prompt: str, tokens: int) -> tuple[dict, str]:
            """Make one Anthropic API call for Dalio. Returns (resp_json, stop_reason)."""
            api_key = _get_api_key()
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": tokens,
                    "temperature": 0,
                    "system": sys_prompt,
                    "messages": [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": "{"},  # prefill — forces JSON-only output
                    ],
                },
                timeout=http_timeout,
            )
            if not resp.ok:
                logger.error(json.dumps({
                    "action": "dalio_api_error", "symbol": symbol, "max_mode": max_mode,
                    "status": resp.status_code, "model": model, "body": resp.text[:500],
                }))
                resp.raise_for_status()
            resp_json = resp.json()
            return resp_json, resp_json.get("stop_reason", "unknown")

        def _parse_dalio_json(raw_text: str, is_max: bool) -> dict:
            raw = "{" + raw_text  # re-attach prefill character
            logger.info(json.dumps({
                "action": "dalio_raw", "symbol": symbol, "model": model,
                "raw_len": len(raw), "preview": raw[:300],
            }))
            start, end = raw.find("{"), raw.rfind("}")
            if start == -1 or end == -1:
                raise ValueError(f"no JSON brackets in Dalio response: {raw[:200]}")
            json_str = raw[start:end + 1]
            try:
                parsed = json.loads(json_str)
            except json.JSONDecodeError:
                if len(json_str) > 1 and json_str[1] == "{":
                    inner_end = json_str.rfind("}")
                    parsed = json.loads(json_str[1:inner_end + 1])
                else:
                    raise
            res: dict = {
                "regime":    parsed.get("regime", "RISK_OFF"),
                "cycle":     parsed.get("cycle", "CONTRACTION"),
                "season":    parsed.get("season", "D_DEFLATION"),
                "macro_take": parsed.get("macro_take", ""),
                "key_risk":  parsed.get("key_risk"),
                "max_mode":  is_max,
                "ok":        True,
                "degraded":  False,
                "error_reason": None,
                "model":     model,
            }
            if is_max:
                res["cycle_analysis"]     = parsed.get("cycle_analysis", "")
                res["sector_positioning"] = parsed.get("sector_positioning", "")
                res["portfolio_action"]   = parsed.get("portfolio_action", "")
            return res

        resp_json, stop_reason = _call_dalio_api(system_prompt, max_tokens)
        raw_text = resp_json["content"][0]["text"]

        need_retry = False
        parse_error: str | None = None
        if stop_reason == "max_tokens":
            need_retry = True
            parse_error = f"stop_reason=max_tokens (truncated at {max_tokens} tokens)"
        else:
            try:
                result = _parse_dalio_json(raw_text, max_mode)
                result["stop_reason"] = stop_reason
                return result
            except (json.JSONDecodeError, ValueError) as pe:
                need_retry = True
                parse_error = str(pe)

        if need_retry and max_mode:
            logger.warning(json.dumps({
                "action": "dalio_retry", "symbol": symbol, "reason": parse_error,
                "stop_reason": stop_reason,
            }))
            retry_resp_json, retry_stop = _call_dalio_api(_COMPACT_DALIO_SYSTEM, 400)
            retry_text = retry_resp_json["content"][0]["text"]
            result = _parse_dalio_json(retry_text, False)  # compact = normal-mode fields
            result["max_mode"] = max_mode
            result["stop_reason"] = retry_stop
            return result
        elif need_retry:
            raise ValueError(parse_error or "parse failed")

        # Fallback if somehow not returned yet
        result = _parse_dalio_json(raw_text, max_mode)
        result["stop_reason"] = stop_reason
        return result

    except Exception as e:
        logger.error(json.dumps({"action": "dalio_take_failed", "symbol": symbol,
                                 "max_mode": max_mode, "error": str(e)}))
        fallback: dict = {
            "regime": "RISK_OFF", "cycle": "CONTRACTION", "season": "D_DEFLATION",
            "macro_take": "", "key_risk": None, "max_mode": max_mode,
            "ok": False, "degraded": True, "error_reason": str(e), "model": model,
        }
        if max_mode:
            fallback.update({"cycle_analysis": "", "sector_positioning": "", "portfolio_action": ""})
        return fallback


# ───── ANALYSIS ─────

def _analyze(symbol: str, max_mode: bool = False) -> dict:
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

    # Buffett + Dalio + Fear&Greed — run in parallel to minimize latency
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as _pool:
        _bf = _pool.submit(_get_buffett_take, symbol, company, info, max_mode)
        _dl = _pool.submit(_get_dalio_take, symbol, company, info, max_mode)
        _fg = _pool.submit(_get_fear_greed)
        buffett    = _bf.result()
        dalio      = _dl.result()
        fear_greed = _fg.result()

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
        "fear_greed":   fear_greed,
        "max_mode":     max_mode,
    }


# ───── TICKER SUMMARY (rule-based — no extra AI call) ─────

def _generate_ticker_summary(r: dict) -> str:
    """
    Synthesize Buffett + Dalio + Technical + F&G into a 1–2 line actionable summary.
    Rule-based — runs on structured data already fetched, no extra AI call.
    """
    signal   = r.get("signal", "NEUTRAL")
    b        = r.get("buffett", {})
    d        = r.get("dalio", {})
    fg       = r.get("fear_greed", {})

    verdict   = b.get("verdict", "NEUTRAL")
    valuation = b.get("valuation", "UNKNOWN")
    regime    = d.get("regime", "RISK_OFF")
    fg_value  = fg.get("value")  # 0–100

    # ── Core recommendation matrix ──────────────────────────────────────────
    if signal == "STRONG_BUY" and verdict == "BULLISH" and regime == "RISK_ON":
        core = "🚀 ทุก signal align (Technical + Buffett + Macro) — ซื้อสะสมได้เลย ตั้ง stop-loss ไว้ด้วย"
    elif signal == "STRONG_BUY" and verdict == "BULLISH":
        core = "📈 Technical + Buffett แข็งแกร่ง แต่ macro ต้องระวัง — เข้าได้แต่ทยอยซื้อทีละส่วน"
    elif signal == "STRONG_BUY" and regime == "RISK_ON":
        core = "📈 Technical แรง macro เอื้อ แต่ Buffett ยังไม่ชัด — เข้าเทคนิคได้ ระวัง overvalued"
    elif signal == "STRONG_BUY":
        core = "📊 Technical แรงมาก แต่ปัจจัยอื่นผสม — เล่นสั้นได้ ไม่เหมาะถือยาว"
    elif signal == "BUY" and verdict == "BULLISH" and regime == "RISK_ON":
        core = "🟢 สัญญาณดีทุกด้าน — รอ pullback เล็กน้อยแล้วเข้า หรือซื้อสะสมได้"
    elif signal == "BUY" and verdict == "BULLISH":
        core = "🟡 Buffett ชอบ แต่ macro กดดัน — สะสมช้าๆ อย่า all-in"
    elif signal == "BUY" and regime == "RISK_ON":
        core = "🟡 Technical + macro โอเค แต่ปัจจัยพื้นฐานยังผสม — ถือได้ถ้ามีอยู่แล้ว"
    elif signal == "BUY":
        core = "🟡 Technical พอใช้ได้ แต่ภาพรวมยังไม่แข็งแกร่ง — ระวังความเสี่ยง"
    elif signal == "WATCH" and verdict == "BULLISH":
        core = "👀 ปัจจัยพื้นฐานดี แต่ technical ยังไม่พร้อม — ตั้ง alert รอ breakout"
    elif signal == "WATCH":
        core = "👀 ยังไม่ถึงเวลาเข้า — รอสัญญาณ technical ชัดขึ้นก่อน"
    elif verdict == "BEARISH" or regime == "DELEVERAGING":
        core = "🔴 ทั้ง fundamental และ macro เป็นลบ — หลีกเลี่ยง หรือลดสัดส่วนถ้ามีอยู่"
    else:
        core = "➖ ไม่น่าสนใจในตอนนี้ — มีตัวเลือกที่ดีกว่าในตลาด"

    # ── Valuation modifier ──────────────────────────────────────────────────
    val_note = ""
    if valuation == "UNDERVALUED" and signal in ("STRONG_BUY", "BUY"):
        val_note = " ราคายังถูกกว่ามูลค่าจริง ✅"
    elif valuation == "OVERVALUED":
        val_note = " ⚠️ ราคาแพงกว่ามูลค่าจริง — ซื้อน้อยลงหรือรอราคาลง"

    # ── Fear & Greed modifier ───────────────────────────────────────────────
    fg_note = ""
    if fg_value is not None:
        if fg_value <= 25:
            fg_note = "\n💡 Extreme Fear ในตลาด = โอกาสทอง สำหรับนักลงทุนระยะยาวที่มีความกล้า"
        elif fg_value >= 75:
            fg_note = "\n⚠️ Extreme Greed ในตลาด = ความเสี่ยงสูง พิจารณาลดขนาด position"

    return f"<b>👉 สรุปสำหรับคุณ:</b> {core}{val_note}{fg_note}"


# ───── FORMATTING ─────

def _format(r: dict) -> list[str]:
    """
    Format analysis result as Telegram HTML.

    Returns list[str]:
      - Normal mode → 1 message (all content fits in 4096 chars)
      - MAX mode    → 2 messages: [Technical Dashboard, AI Deep Analysis]
        Necessary because MAX AI content (7 long fields) routinely exceeds the
        Telegram 4096-char hard limit when combined with technical indicators.
    """
    emoji_map = {"STRONG_BUY": "🚀", "BUY": "📈", "WATCH": "👀", "NEUTRAL": "➖"}
    emoji = emoji_map.get(r["signal"], "📊")
    change_icon = "🟢" if r["change_pct"] >= 0 else "🔴"
    change_str = f"{'+' if r['change_pct'] >= 0 else ''}{r['change_pct']}%"
    max_badge = "  ⚡ <b>MAX</b>" if r.get("max_mode") else ""
    symbol_safe = _html.escape(r["symbol"])
    company = _html.escape(r["company"])
    max_mode = r.get("max_mode", False)

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

    # ── Part 1: Technical Dashboard ───────────────────────────────────────────
    tech_lines = [
        f"{emoji} <b>{r['symbol']}</b> — {company}{max_badge}",
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

    # ── Degraded badge for MAX mode tech dashboard ────────────────────────────
    b_degraded = r.get("buffett", {}).get("degraded", False)
    d_degraded = r.get("dalio", {}).get("degraded", False)
    if max_mode and b_degraded and d_degraded:
        max_badge = "  ⚡ <b>MAX</b> <i>(AI degraded)</i>"
        # Update the first line of tech_lines to use this badge
        tech_lines[0] = f"{emoji} <b>{r['symbol']}</b> — {company}{max_badge}"

    # ── Part 2: AI Deep Analysis ──────────────────────────────────────────────
    ai_lines: list[str] = []

    if max_mode:
        ai_lines.append(f"⚡ <b>MAX Analysis — {r['symbol']}</b>")

    # Buffett section
    b = r.get("buffett", {})
    if b.get("verdict") or b.get("degraded"):
        if max_mode and b.get("degraded"):
            # Honest degraded rendering — do NOT show silent NEUTRAL
            err_short = (b.get("error_reason") or "unknown error")[:60]
            ai_lines += [
                "",
                f'🎩 <b>Buffett Take</b>  ⚠️ <b>MAX DEGRADED</b>',
                f'<i>AI ไม่สามารถวิเคราะห์ได้ ({_html.escape(err_short)}) — ลองใหม่หรือใช้ normal mode</i>',
            ]
        else:
            verdict_icon = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(b.get("verdict", ""), "⚪")
            moat_map = {"WIDE": "🏰 กว้าง", "NARROW": "🔷 แคบ", "NONE": "❌ ไม่มี", "UNKNOWN": "❓ ไม่ทราบ"}
            moat_label = moat_map.get(b.get("moat", "UNKNOWN"), b.get("moat", "UNKNOWN"))
            val_map = {"UNDERVALUED": "💚 ราคาถูก", "FAIR": "🟡 ราคาพอดี", "OVERVALUED": "🔴 ราคาแพง"}
            val_str = (f" | {val_map.get(b.get('valuation', ''), b.get('valuation', ''))}"
                       if b.get("valuation") and b.get("valuation") != "UNKNOWN" else "")
            ai_lines += [
                "",
                f'🎩 <b>Buffett Take</b>  {verdict_icon} {b.get("verdict", "NEUTRAL")} | คูเมือง: {moat_label}{val_str}',
            ]
            if max_mode and b.get("ok"):
                if b.get("moat_analysis"):
                    ai_lines.append(f'<b>🏰 Moat:</b> <i>{_html.escape(b["moat_analysis"])}</i>')
                if b.get("fundamental_verdict"):
                    ai_lines.append(f'<b>📊 ปัจจัยพื้นฐาน:</b> <i>{_html.escape(b["fundamental_verdict"])}</i>')
                if b.get("valuation_verdict"):
                    ai_lines.append(f'<b>💰 Valuation:</b> <i>{_html.escape(b["valuation_verdict"])}</i>')
                if b.get("action"):
                    ai_lines.append(f'<b>👉 Buffett จะทำอะไร:</b> <i>{_html.escape(b["action"])}</i>')
            else:
                if b.get("one_liner"):
                    ai_lines.append(f'<i>{_html.escape(b["one_liner"])}</i>')
            if b.get("key_concern"):
                ai_lines.append(f"⚠️ ความเสี่ยง: {_html.escape(b['key_concern'])}")

    # Dalio section
    d = r.get("dalio", {})
    if d.get("regime") or d.get("degraded"):
        if max_mode and d.get("degraded"):
            # Honest degraded rendering for Dalio
            err_short = (d.get("error_reason") or "unknown error")[:60]
            ai_lines += [
                "",
                f'🌐 <b>Ray Dalio Take</b>  ⚠️ <b>MAX DEGRADED</b>',
                f'<i>AI ไม่สามารถวิเคราะห์ได้ ({_html.escape(err_short)}) — ลองใหม่หรือใช้ normal mode</i>',
            ]
        else:
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
            ai_lines += [
                "",
                f'🌐 <b>Ray Dalio Take</b>  {regime_label}',
                f'ช่วง: <code>{cycle_label}</code> | ฤดู: <code>{season_label}</code>',
            ]
            if max_mode and d.get("ok"):
                if d.get("cycle_analysis"):
                    ai_lines.append(f'<b>📉 วัฏจักร:</b> <i>{_html.escape(d["cycle_analysis"])}</i>')
                if d.get("sector_positioning"):
                    ai_lines.append(f'<b>🏭 Sector:</b> <i>{_html.escape(d["sector_positioning"])}</i>')
                if d.get("portfolio_action"):
                    ai_lines.append(f'<b>💼 All-Weather:</b> <i>{_html.escape(d["portfolio_action"])}</i>')
            else:
                if d.get("macro_take"):
                    ai_lines.append(f'<i>{_html.escape(d["macro_take"])}</i>')
            if d.get("key_risk"):
                ai_lines.append(f"⚠️ ความเสี่ยง: {_html.escape(d['key_risk'])}")

    # Fear & Greed
    fg = r.get("fear_greed", {})
    if fg.get("ok") and fg.get("value") is not None:
        ai_lines += [
            "",
            f'🌡️ <b>Fear & Greed:</b> {fg["value"]} — {fg["emoji"]} {fg["rating"]}',
            f'<i>{fg["advice"]}</i>',
        ]

    # สรุปสำหรับคุณ + TradingView (always in ai_lines so they stay together)
    ai_lines += [
        "",
        _generate_ticker_summary(r),
        "",
        f'🔗 <a href="https://www.tradingview.com/chart/?symbol={symbol_safe}">TradingView Chart</a>',
    ]

    if max_mode:
        # Split into 2 messages: tech dashboard → AI deep analysis
        return ["\n".join(tech_lines), "\n".join(ai_lines)]
    else:
        # Normal mode: single message
        return ["\n".join(tech_lines + ai_lines)]


# ───── SMART ROUTER ─────

def _handle_question(text: str, max_mode: bool = False) -> str:
    """Route question to relevant investor framework(s) and answer in their voice."""
    model = "claude-sonnet-4-6" if max_mode else "claude-haiku-4-5-20251001"
    max_tokens = 3000 if max_mode else 1024

    # MAX mode: lift word-count cap and reinforce depth + สรุปสำหรับคุณ
    system = _SMART_ROUTER_SYSTEM
    if max_mode:
        # Remove the 200-word limit so Sonnet can think fully
        system = _SMART_ROUTER_SYSTEM.replace(
            "OUTPUT FORMAT (Telegram HTML, ไม่เกิน 200 คำ):",
            "OUTPUT FORMAT (Telegram HTML — MAX MODE, ละเอียดมากขึ้น ไม่จำกัดความยาว):",
        )
        system += (
            "\n\n⚡ MAX MODE — คำสั่งพิเศษ:"
            "\n1. อธิบายแต่ละ framework อย่างละเอียด ยกตัวอย่างจริง ใช้ตัวเลขและข้อมูลเฉพาะเจาะจง"
            "\n2. ถ้าใช้ 2 frameworks ให้แยกหัวข้อชัดเจนและอธิบายแต่ละมุมมองอย่างลึก"
            "\n3. สรุปสำหรับคุณ ต้องมีเสมอ ต้องเป็น 2–3 ประโยค actionable advice ที่ชัดเจน"
            "\n   รูปแบบ: <b>👉 สรุปสำหรับคุณ:</b> [คำแนะนำที่ทำได้จริง + เงื่อนไขที่ควรระวัง]"
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
                "model": model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": text}],
            },
            timeout=45,
        )
        resp.raise_for_status()
        answer = resp.json()["content"][0]["text"].strip()
        frameworks = [f for f in ["Dalio", "Buffett", "Bezos", "Saylor"] if f in answer]
        logger.info(json.dumps({"action": "smart_router", "frameworks": frameworks,
                                "max_mode": max_mode, "q": text[:60]}))
        return answer
    except Exception as e:
        logger.warning(json.dumps({"action": "smart_router_failed", "error": str(e)}))
        return "❌ ไม่สามารถตอบได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง"


_HELP_TEXT = (
    "👋 <b>AlphaForge Bot v2.0</b>\n\n"
    "วิเคราะห์หุ้น US แบบ Real-time ด้วย AI\n"
    "Warren Buffett 🎩 + Ray Dalio 🌐 + Fear &amp; Greed 🌡️\n\n"
    "<b>Commands:</b>\n"
    "/scan — สัญญาณล่าสุดทุก watchlist\n"
    "/top  — เหมือน /scan (alias)\n"
    "/help — วิธีใช้\n\n"
    "<b>พิมพ์ ticker เพื่อวิเคราะห์:</b>\n"
    "<code>AAPL</code>  <code>NVDA</code>  <code>TSLA</code>\n"
    "<code>META</code>  <code>AMZN</code>  <code>AMD</code>\n"
    "<code>QQQ</code>   <code>SPY</code>   <code>BRK-B</code>\n\n"
    "<b>⚡ MAX MODE</b> — วิเคราะห์ลึกสุด (ใช้ Claude Sonnet):\n"
    "<code>max AAPL</code>  <code>max NVDA</code>\n"
    "<code>max ช่วงนี้น่าลงทุนไหม?</code>\n\n"
    "<b>ถามคำถามได้เลย:</b>\n"
    "• ช่วงนี้น่าลงทุนไหม?\n"
    "• NVDA กับ AMD ตัวไหนน่าสนใจกว่า?\n"
    "• วางแผน port ยังไงดีกับตลาดแบบนี้?\n"
    "• Bitcoin ตอนนี้ดีไหม?"
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
        message_id = message.get("message_id", 0)
        original_text = (message.get("text") or "").strip()[:500]  # cap to prevent abuse
        text = original_text.upper()

        if not chat_id or not text:
            return {"statusCode": 200, "body": "ok"}

        # ── Deduplication guard ───────────────────────────────────────────────
        # Telegram retries webhook if Lambda doesn't return 200 within ~30s.
        # MAX mode (Sonnet calls) can take 40-60s → triggers retry → double response.
        # Atomic DynamoDB conditional write ensures only ONE invocation processes each message.
        if not _try_claim_message(chat_id, message_id):
            return {"statusCode": 200, "body": "ok"}
        # ─────────────────────────────────────────────────────────────────────

        token = _get_secret("/alpha-forge/TELEGRAM_BOT_TOKEN").strip()

        # Detect MAX mode prefix: "max AAPL" or "max ช่วงนี้น่าลงทุน?"
        max_mode = False
        if text.startswith("MAX "):
            max_mode = True
            text = text[4:].strip()                        # strip "MAX " from uppercase
            original_text = original_text[4:].strip()     # strip from original too

        # Commands
        if text.startswith("/"):
            if text in ("/START", "/HELP"):
                _send(token, chat_id, _HELP_TEXT)
            elif text in ("/SCAN", "/TOP"):
                _send(token, chat_id, "🔍 กำลังดึงสัญญาณล่าสุด...")
                scan_msg = _get_scan_message()
                _send(token, chat_id, scan_msg)
                logger.info(json.dumps({"action": "scan_requested"}))
            else:
                _send(token, chat_id, "❓ ไม่รู้จัก command นี้\nพิมพ์ /help เพื่อดูวิธีใช้")
            return {"statusCode": 200, "body": "ok"}

        # Ticker → วิเคราะห์
        if _VALID_TICKER.match(text):
            symbol = text
            mode_label = "⚡ MAX MODE — " if max_mode else ""
            _send(token, chat_id, f"⏳ {mode_label}กำลังวิเคราะห์ <b>{symbol}</b>...")
            result = _analyze(symbol, max_mode=max_mode)
            for part in _format(result):
                _send(token, chat_id, part)
            logger.info(json.dumps({"action": "analyzed", "symbol": symbol,
                                    "signal": result["signal"], "max_mode": max_mode}))
            return {"statusCode": 200, "body": "ok"}

        # คำถามทั่วไป → Conversational advisor
        thinking_msg = "⚡ MAX MODE — กำลังคิดอย่างละเอียด..." if max_mode else "💭 กำลังคิด..."
        _send(token, chat_id, thinking_msg)
        answer = _handle_question(original_text, max_mode=max_mode)
        _send(token, chat_id, answer)
        logger.info(json.dumps({"action": "advisor", "question": original_text[:50], "max_mode": max_mode}))

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
