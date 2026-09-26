# ── Environment ───────────────────────────────────────────────────────────────

-include .env
export

.PHONY: lint type-check test install frontend \
	precompute-db upload-update-prompt sam-build sam-data dev-agent ask memory \
	dev dev-api dev-frontend \
	synth deploy destroy clean

# ── Quality ───────────────────────────────────────────────────────────────────

lint:
	uv run ruff check --fix
	uv run ruff format

type-check:
	uv run ty check src app.py --verbose

test:
	uv run pytest --ignore=cdk.out

# ── Local development ─────────────────────────────────────────────────────────

install-backend:
	uv sync

install-frontend:
	cd src/finops_agent/frontend && npm install
	cd src/finops_agent/frontend && npm approve-scripts unrs-resolver || true

install: install-backend install-frontend

precompute-db:
	uv run python scripts/precompute_data.py

upload-update-prompt:
	uv run python scripts/upload_prompt.py

# ── SAM local testing ─────────────────────────────────────────────────────────

test-env:
	@test -n "$(LOCAL_API_PORT)" || { echo "LOCAL_API_PORT is not set in .env"; exit 1; }
	@test -n "$(AGENT_PORT)" || { echo "AGENT_PORT is not set in .env"; exit 1; }

sam-build:
	uv run sam build --use-buildkit

EVENT ?= tests/events/health.json
sam-data: sam-build
	uv run sam local invoke DataFunction --event $(EVENT) --env-vars .env

dev-api: test-env sam-build
	uv run sam local start-api --port $(LOCAL_API_PORT) --warm-containers EAGER --env-vars .env

dev-frontend: test-env
	cd src/finops_agent/frontend && API_BASE_URL=http://127.0.0.1:$(LOCAL_API_PORT) bun run dev

dev-agent:
	uv run python -m finops_agent.ai.runtime.agent

Q ?= Which are the most expensive on demand services in september 2025?
ask: test-env
	curl -N -sS -X POST http://127.0.0.1:$(AGENT_PORT)/invocations \
		-H "Content-Type: application/json" \
		-H "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: local-finops-agent-session-0001" \
		-d "{\"question\":\"$(Q)\",\"context\":{\"period\":\"2025-09\"}}"

memory:
	aws bedrock-agentcore list-events --region us-east-1 --memory-id FinopsAgentMemory-f4nK7H77t7 --actor-id demo --session-id "$(SESSION)" --include-payloads

# ── CDK ───────────────────────────────────────────────────────────────────────

synth:
	uv run cdk synth --all

deploy:
	uv run cdk deploy --all --require-approval never \
	--parameters FinopsAgentStack:GithubTokenSecretArn=$(GITHUB_TOKEN_SECRET_ARN) \
	--parameters FinopsAgentStack:BudgetAlertEmail=$(BUDGET_ALERT_EMAIL)

destroy:
	uv run cdk destroy --all --force

# ── Cleanup ───────────────────────────────────────────────────────────────────

clean:
	rm -rf cdk.out .aws-sam .cache src/.cache src/finops_agent/frontend/.next src/finops_agent/frontend/out
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
