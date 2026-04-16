# AlphaForge — Claude Code Instructions

## ⚠️ READ FIRST — ทุกครั้งก่อนเริ่มทำงาน
คุณคือ Senior Cloud/AI Engineer ที่ดูแล project AlphaForge
อ่านไฟล์เหล่านี้ก่อนเสมอ:
1. `CLAUDE.md` (ไฟล์นี้)
2. Obsidian: `00-Gateway/PROJECT_CONTEXT.md` (ถ้ามี)
3. Obsidian: `00-Gateway/RULES.md` (ถ้ามี)

## Project Summary
**AlphaForge** — US Stock Market signal engine บน AWS Serverless
ผสาน Multi-AI Router + FinBERT + LLM Pattern Recognition + Fear & Greed Index
เป้าหมาย: < $5/เดือน รวม AI APIs

Roadmap alignment:
- Day 1–40   → SAA-C03 Phase 1 (AWS Foundation)
- Day 41–80  → SAA-C03 Phase 2 (Signal Engine)
- Day 81–120 → Terraform (IaC Layer)
- Day 121–150→ AI Engineering (Bedrock + FinBERT + RAG)

## Tech Stack
Language:   Python 3.12 (type hints required on ALL functions)
Cloud:      AWS Lambda, DynamoDB, S3, CloudFront, API GW, EventBridge, SSM, CloudWatch
IaC:        SAM (lambdas + API + events)  +  Terraform (infra, remote state, workspaces)
Container:  Docker (local dev + Lambda container image)
CI/CD:      GitHub Actions (test.yml + deploy.yml)
AI Router:  Gemini Flash → GPT-4o-mini → Claude Haiku (Phase 1–3)
            → AWS Bedrock Claude (Phase 4)
AI Extra:   FinBERT (HuggingFace), Fear & Greed API, LLM Pattern Recognition
Data:       yfinance (OHLCV US), Alpaca News API, Alpha Vantage, CNN F&G
Region:     us-east-1 (NYSE proximity)
Market:     US Stocks — AAPL, MSFT, NVDA, GOOGL, TSLA, SPY
Schedule:   09:00 EST, 09:30 EST, 16:15 EST — MON–FRI only

## Project Structure
```
alpha-forge/
├── lambdas/
│   ├── analyzer/           ← main Lambda (scheduler-triggered)
│   │   ├── handler.py      ← entry point
│   │   ├── fetcher.py      ← yfinance US + Alpaca News
│   │   ├── scorer.py       ← weighted scoring engine
│   │   ├── notifier.py     ← LINE Notify
│   │   ├── technical/      ← TA indicators (trend/momentum/volume/volatility)
│   │   └── ai/             ← AI layer (router/finbert/pattern/regime)
│   └── api/                ← read-only REST API Lambda
├── infrastructure/
│   ├── sam/template.yaml   ← Lambda + API + EventBridge + DynamoDB
│   └── terraform/          ← S3 + CloudFront + IAM + Budget + Monitoring
├── tests/                  ← pytest (coverage ≥ 80%)
├── .github/workflows/      ← CI/CD
├── docker-compose.yml      ← DynamoDB Local
└── Makefile                ← all commands
```

## Secrets — ALL stored in SSM Parameter Store
/alpha-forge/LINE_NOTIFY_TOKEN
/alpha-forge/ANTHROPIC_API_KEY
/alpha-forge/OPENAI_API_KEY
/alpha-forge/GEMINI_API_KEY
/alpha-forge/ALPACA_API_KEY
/alpha-forge/HF_API_KEY
/alpha-forge/DYNAMODB_TABLE
/alpha-forge/MONTHLY_AI_BUDGET

## Coding Standards (Non-negotiable)
1. ทุก function ต้องมี type hints
2. ทุก Lambda handler ต้องมี try/except + structured JSON logging
3. ห้าม hardcode secrets — ดึงจาก SSM เท่านั้น
4. ทุก AI call ต้องผ่าน ai/ai_router.py (ยกเว้น FinBERT ซึ่งเรียกตรง)
5. บันทึกผลวิเคราะห์กลับ Obsidian 02-Analysis/ เสมอ
6. ทุก error ต้อง log เป็น JSON format สำหรับ CloudWatch

## Signal Scoring v2.0
```
score = EMA_align(0.15) + Supertrend(0.10) + RSI(0.10) + MACD(0.10)
      + VWAP(0.07) + ATR(0.03)
      + FinBERT(0.20) + FearGreed(0.05) + LLM_Pattern(0.15)
      × RegimeMultiplier (Bull=1.2, Bear=0.8, Sideways=1.0)
      + RS_bonus (+0.05 if Relative Strength vs SPY > 1.0)

>= 0.75 → STRONG → LINE alert ทันที
>= 0.55 → BUY/SELL → บันทึก + รอ confirm
>= 0.35 → WATCH → บันทึก dashboard
<  0.35 → NEUTRAL → ข้าม
```

## Phase 1 Status (Current)
AI layer (FinBERT / LLM Pattern / Fear&Greed) = placeholder (returns 0.5 = neutral)
จะ implement ใน Phase 2 (Day 41–80)

## Common Commands
make dev              → docker-compose up (local DynamoDB + admin UI)
make test             → pytest tests/ -v
make deploy-dev       → SAM deploy to dev (test must pass first)
make deploy-prod      → SAM deploy to production
make tf-plan-dev      → terraform plan (dev workspace)
make tf-apply-prod    → terraform apply (prod workspace)
make logs             → tail CloudWatch logs (prod)
make setup-secrets    → upload all secrets to SSM
make invoke-local     → SAM local invoke (no AWS needed)
make backtest         → run vectorbt backtest

## When Adding Features
1. เขียน test ก่อน (TDD)
2. ทดสอบ make invoke-local
3. deploy-dev → verify CloudWatch → deploy-prod
4. อัปเดต scoring weights ใน Obsidian ถ้าเปลี่ยน logic

## When Debugging
1. CloudWatch Logs → /aws/lambda/alpha-forge-*
2. DynamoDB Console → ดู record ที่บันทึก
3. SSM Parameter Store → ตรวจ secrets
4. docker-compose local → reproduce ปัญหา

## Watchlist
AAPL, MSFT, NVDA, GOOGL, TSLA, SPY
(Phase 4: expand 50+ via SQS)

## Cost Guardrails
AWS:     <$1/month (free tier heavy)
AI APIs: ~$0.17/month (via router)
Total:   < $5/month — Budget Alert ที่ $3
ถ้า budget alert trigger → ตรวจ Lambda loop / AI call frequency ก่อน
