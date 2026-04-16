.PHONY: dev dev-down test deploy-dev deploy-prod \
        tf-init tf-plan-dev tf-plan-prod tf-apply-dev tf-apply-prod \
        logs invoke-local setup-secrets backtest create-table

# ───── LOCAL DEV ─────
dev:
	docker-compose up -d
	@echo ""
	@echo "✅ DynamoDB Local  → http://localhost:8000"
	@echo "✅ DynamoDB Admin  → http://localhost:8001"

dev-down:
	docker-compose down

create-table:
	@echo "Creating DynamoDB table locally..."
	aws dynamodb create-table \
		--table-name alpha-signals-dev \
		--attribute-definitions \
			AttributeName=symbol,AttributeType=S \
			AttributeName=timestamp,AttributeType=S \
		--key-schema \
			AttributeName=symbol,KeyType=HASH \
			AttributeName=timestamp,KeyType=RANGE \
		--billing-mode PAY_PER_REQUEST \
		--endpoint-url http://localhost:8000 \
		--region us-east-1
	@echo "✅ Table created"

# ───── TESTING ─────
test:
	cd lambdas/analyzer && pip install -r requirements.txt -q
	cd lambdas/analyzer && pip install pytest -q
	PYTHONPATH=lambdas/analyzer pytest tests/ -v --tb=short

test-watch:
	PYTHONPATH=lambdas/analyzer pytest tests/ -v --tb=short -f

# ───── DEPLOY ─────
deploy-dev: test
	@echo "Deploying to dev..."
	cd infrastructure/sam && sam build
	cd infrastructure/sam && sam deploy \
		--stack-name alpha-forge-dev \
		--parameter-overrides Environment=dev \
		--capabilities CAPABILITY_IAM \
		--region us-east-1 \
		--no-confirm-changeset

deploy-prod: test
	@echo "Deploying to PROD — are you sure? (Ctrl+C to cancel)"
	@sleep 3
	cd infrastructure/sam && sam build
	cd infrastructure/sam && sam deploy \
		--stack-name alpha-forge-prod \
		--parameter-overrides Environment=prod \
		--capabilities CAPABILITY_IAM \
		--region us-east-1 \
		--no-confirm-changeset

# ───── TERRAFORM ─────
tf-init:
	cd infrastructure/terraform && terraform init

tf-plan-dev:
	cd infrastructure/terraform && \
		terraform workspace select dev 2>/dev/null || terraform workspace new dev && \
		terraform plan -var-file=workspaces/dev.tfvars

tf-plan-prod:
	cd infrastructure/terraform && \
		terraform workspace select prod 2>/dev/null || terraform workspace new prod && \
		terraform plan -var-file=workspaces/prod.tfvars

tf-apply-dev:
	cd infrastructure/terraform && \
		terraform workspace select dev && \
		terraform apply -var-file=workspaces/dev.tfvars -auto-approve

tf-apply-prod:
	cd infrastructure/terraform && \
		terraform workspace select prod && \
		terraform apply -var-file=workspaces/prod.tfvars

# ───── LOCAL INVOKE ─────
invoke-local:
	cd infrastructure/sam && sam build -q
	cd infrastructure/sam && sam local invoke AnalyzerFunction \
		--event events/test_event.json \
		--env-vars ../../.env.json 2>&1

# ───── LOGS ─────
logs:
	aws logs tail /aws/lambda/alpha-forge-analyzer-prod --follow --region us-east-1

logs-dev:
	aws logs tail /aws/lambda/alpha-forge-analyzer-dev --follow --region us-east-1

# ───── SECRETS SETUP ─────
setup-secrets:
	@echo "Uploading secrets to SSM Parameter Store..."
	@[ -n "$(LINE_TOKEN)" ] && aws ssm put-parameter --name "/alpha-forge/LINE_NOTIFY_TOKEN" --type "SecureString" --value "$(LINE_TOKEN)" --overwrite || echo "Skip LINE_TOKEN"
	@[ -n "$(GEMINI_KEY)" ] && aws ssm put-parameter --name "/alpha-forge/GEMINI_API_KEY" --type "SecureString" --value "$(GEMINI_KEY)" --overwrite || echo "Skip GEMINI_KEY"
	@[ -n "$(OPENAI_KEY)" ] && aws ssm put-parameter --name "/alpha-forge/OPENAI_API_KEY" --type "SecureString" --value "$(OPENAI_KEY)" --overwrite || echo "Skip OPENAI_KEY"
	@[ -n "$(ANTHROPIC_KEY)" ] && aws ssm put-parameter --name "/alpha-forge/ANTHROPIC_API_KEY" --type "SecureString" --value "$(ANTHROPIC_KEY)" --overwrite || echo "Skip ANTHROPIC_KEY"
	@echo "✅ Secrets uploaded"

# ───── BACKTEST ─────
backtest:
	PYTHONPATH=lambdas/analyzer python lambdas/analyzer/backtester.py

# ───── HELP ─────
help:
	@echo ""
	@echo "AlphaForge — Available Commands"
	@echo "─────────────────────────────────────────"
	@echo "make dev           → Start DynamoDB Local + Admin UI"
	@echo "make test          → Run pytest"
	@echo "make invoke-local  → SAM local invoke (no AWS needed)"
	@echo "make deploy-dev    → Deploy to AWS dev"
	@echo "make deploy-prod   → Deploy to AWS prod"
	@echo "make tf-plan-dev   → Terraform plan (dev)"
	@echo "make tf-apply-prod → Terraform apply (prod)"
	@echo "make logs          → Tail CloudWatch logs (prod)"
	@echo "make setup-secrets → Upload secrets to SSM"
	@echo ""
