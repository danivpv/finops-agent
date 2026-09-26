# Maintainer notes

Context for the next pass: frontend integration, refactor, local testing, and deployment. `README.md` is the public page. This file is the contract.

## Product

Show a signed savings figure, the covered spend under it, and unused commitment. Let a customer slice that figure by their own dimensions and follow one slice to the usage lines behind it. Show the customer share, the risk reserve, and the operator profit, with the reserve framed as the cost of the guarantee.

The assistant answers a question about the current screen. It may run at most two typed queries. It receives aggregated rows and the display SQL, never raw lines.

## What is deployed

Two CDK stacks, composed in `src/finops_agent/component.py`. `app.py` only instantiates them.

| Stack | Owns |
|---|---|
| `FinopsAgentStatefulStack` | AgentCore Memory (`Duration.days(7)`) |
| `FinopsAgentStatelessStack` | Data Lambda, API Gateway, AgentCore Gateway, AgentCore Runtime, Amplify SSR |

API Gateway authorization is IAM. The Gateway authorizer is IAM. The runtime inbound auth is IAM. The Amplify SSR role is granted `runtime.grant_invoke_runtime(...)` (`bedrock-agentcore:InvokeAgentRuntime` on the runtime and its endpoints) and `execute-api:Invoke` on the Data API. The runtime role is granted `gateway.grant_invoke(...)` plus explicit statements for the Nova 2 Lite cross-region profile, short-term memory event actions (`ListEvents`, `GetEvent`, `CreateEvent`), and reading this one prompt (`bedrock:GetPrompt` and `bedrock:ListPrompts`). No wildcard grants on customer resources.

The browser never holds AWS keys. `src/finops_agent/frontend/app/api/backend/[...path]/route.ts` is the only door. `http://` targets (local SAM, local agent) are fetched unsigned. `https://` data calls are signed with Signature V4 for `execute-api`. `/ask` and `/assistant` invoke the runtime when `AGENT_RUNTIME_ARN` is set, and the local agent process when it is not.

There is one query function, `run_query` in `data/runtime/routes.py`. `POST /investigate` and the Gateway tool `run_finops_query` both call it. The tool schema is `src/finops_agent/ai/run_finops_query.json`. The visible Gateway name is `finops-data___run_finops_query`. Target names cannot contain underscores.

The Data image contains the precomputed dice. The agent image does not, and it does not import the store. With `GATEWAY_URL` unset, the agent POSTs to `DATA_API_BASE_URL` + `/investigate`.

Do not bring back a shared header secret, `x-demo-auth`, OpenRouter, a Function URL, or a second copy of the query.

## Local integration

| Process | Port | Make target |
|---|---|---|
| Next.js | 3000 | `make dev-frontend` |
| SAM local API | `LOCAL_API_PORT` in `.env` | `make dev-api` |
| Agent process | `AGENT_PORT` in `.env` | `make dev-agent` |

`make dev-frontend` sets `API_BASE_URL` to `http://127.0.0.1:$LOCAL_API_PORT`. The browser default is `NEXT_PUBLIC_API_URL=/api/backend`, so the page hits the Next proxy, and the proxy hits SAM. Run `dev-api` and `dev-frontend` together. Do not add another port, and do not add `frontend/.env.local`.

```bash
make dev-api
make dev-frontend
# http://localhost:3000

make dev-agent
make ask Q="What are the top services by on-demand spend?"
```

Contract checks against SAM, with no frontend:

```bash
make sam-data
make sam-data EVENT=tests/events/slice.json
curl "http://127.0.0.1:${LOCAL_API_PORT}/health"
curl -X POST "http://127.0.0.1:${LOCAL_API_PORT}/slice" -H "Content-Type: application/json" -d "{\"group_by\":\"service\",\"metric\":\"on_demand_cost\",\"top_n\":5}"
curl "http://127.0.0.1:${LOCAL_API_PORT}/economics"
```

`make test` is the suite. Infra changes are proven with `tests/test_cdk_stack.py`, not by deploying.

## Frontend contract

`src/finops_agent/frontend/lib/api.ts` is the client. Keep one client.

| Screen | Calls |
|---|---|
| `/` | `GET /economics`, `GET /narration` |
| `/explore` | `GET /vocab`, `POST /slice`, `POST /delta`, `POST /drill` |
| `/split` | `GET /economics`, `POST /econ/economics` |
| Assistant drawer | `POST /assistant` (SSE: `status`, `sql`, `text`, `meta`) |
| Ask panel | `POST /ask` (SSE) |

`/ask` and `/assistant` are agent routes. Everything else is the Data Lambda. `GET /health` is the readiness check. `savingsReady` (`GET /impact-status`) and `warmSavings` (`POST /warm`) are exported from `lib/api.ts`. Confirm a screen still calls them before deleting either.

Data routes the Lambda also serves: `POST /investigate` (the agent's query). The UI does not call it directly.

## Environment

One `.env` at the repo root. Python runtimes and CDK synth load it through pydantic-settings. `make` exports it. Do not add another env file. Do not branch on `os.environ` in Python. Paths use `pathlib.Path`.

| Variable | Local | Deployed |
|---|---|---|
| `GITHUB_TOKEN_SECRET_ARN` | Loaded by `SynthSettings` at `cdk synth` / `make deploy` | Amplify source access |
| `BUDGET_ALERT_EMAIL` | Loaded by `SynthSettings` at `cdk synth` / `make deploy` | AWS Budgets subscriber |
| `PROMPT_ARN` | Written by `make upload-update-prompt`. Required for the local agent | Runtime env, set by CDK from the same value |
| `API_BASE_URL` | Set by `make dev-frontend` to the SAM URL | Amplify branch env, the API Gateway URL |
| `NEXT_PUBLIC_API_URL` | Default `/api/backend` | Same, set on the Amplify branch |
| `AGENT_RUNTIME_ARN` | Unset. Proxy uses the local agent | Amplify branch env |
| `GATEWAY_URL` | Unset. Agent uses `DATA_API_BASE_URL` | Runtime env, set by CDK |
| `MEMORY_ID` | Unset. Memory calls are skipped | Runtime env, set by CDK |
| `CC_DATA_DIR` | Default `src/finops_agent/data/precomputed` | Image and CDK set `/var/task/finops_agent/data/precomputed` |
| `LOCAL_API_PORT` | Required in `.env`. No code default | Injected into the runtime from that same value |
| `AGENT_PORT` | Required in `.env`. The local process binds it | Injected into the runtime as the same value |

AWS credentials stay in the ambient profile. They are not `.env` keys.

The OpenRouter secret and any `x-demo-auth` header secret are unused. Keep the GitHub token secret. Delete the others in the console if they are still billed. There is no data bucket. The precomputed tables are files in the Data Lambda image.

## Architectural decision log

Each entry records the alternatives considered, the decision made, and the rationale in the shipped codebase.

### AI.1 Model invocation and cross-region inference profile (Amazon Nova 2 Lite)

| | |
|---|---|
| Alternatives considered | Invoke the bare foundation-model ID `amazon.nova-2-lite-v1:0` directly; route requests through an external LLM proxy (`OpenRouter` or `MLflow AI Gateway`) |
| Decision | **Invoke Amazon Nova 2 Lite through the US cross-region inference profile (`us.amazon.nova-2-lite-v1:0`) with IAM scoped to the profile ARN and the three regional foundation-model ARNs (`us-east-1`, `us-east-2`, `us-west-2`)** |
| Rationale | Nova 2 Lite does not support direct on-demand `InvokeModel` calls against the bare foundation-model ID and fails with `ValidationException: on-demand throughput isn't supported`. Calling the cross-region inference profile succeeds, but Bedrock evaluates IAM against both the account-scoped `inference-profile` ARN in the calling region and the regional `foundation-model/amazon.nova-2-lite-v1:0` ARN in whichever US source region serves the request. Scoping both in `ai/infrastructure.py` keeps the runtime keyless and avoids operating a separate proxy server. |

### AI.2 AgentCore short-term Memory via L2 `Memory` construct and scoped event IAM

| | |
|---|---|
| Alternatives considered | Enable long-term memory extraction strategies; use `memory.grant_read_short_term_memory()` unconditionally; store chat turns in DynamoDB |
| Decision | **Provision `agentcore.Memory` with `expiration_duration=Duration.days(7)`, omit `memory_strategies`, and scope the runtime role to `ListEvents`, `GetEvent`, and `CreateEvent` only** |
| Rationale | Using the L2 `Memory` construct with its 7-day minimum (`MEMORY_EXPIRY_DAYS = 7`) and omitting `memory_strategies` gives the assistant per-session continuity without invoking background models for long-term memory extraction. Even `Memory.grant_read_short_term_memory` adds `bedrock-agentcore:ListActors` and `bedrock-agentcore:ListSessions` on top of `GetEvent` and `ListEvents`, whereas a single-session turn only needs to read and append its own session events. Writing the three event actions explicitly keeps the runtime from enumerating other sessions or actors. |

### AI.3 One Query, Two Doors (Data Lambda behind API Gateway and AgentCore Gateway)

| | |
|---|---|
| Alternatives considered | Embed DuckDB and `precomputed/` inside both the Data Lambda and the AgentCore Runtime image; let the model generate SQL over the dataset |
| Decision | **Expose a single typed `run_query(query: InvestigateQuery)` function in `data/runtime/routes.py` invoked by both `POST /investigate` on API Gateway and the `run_finops_query` MCP target on AgentCore Gateway** |
| Rationale | Duplicating the analytical store across two container images risks drift between what the dashboard charts render and what the assistant answers, while inflating the agent image with precomputed data. Letting the model write raw SQL introduces syntax and hallucination failures. A single `run_query` implementation behind both doors guarantees that every figure in the UI and every number cited by the assistant comes from the same parameterized DuckDB aggregation, and the agent never sees raw usage rows. |

### AI.4 Server-side tool budget (`_QueryBudget`) vs prompt-only instructions

| | |
|---|---|
| Alternatives considered | Rely solely on the system prompt instruction ("Call the tool at most twice"); rely on framework max-iteration defaults |
| Decision | **Enforce a hard per-question cap of two tool invocations in `_QueryBudget` (`MAX_QUERY_STEPS = 2`) inside `ai/runtime/agent.py` before calling the Gateway** |
| Rationale | A system prompt is a hint to the model, not an execution boundary. If a model enters a retry or exploration loop, prompt instructions do not stop outbound Lambda invocations or token accumulation. Checking `budget.reserve()` inside the tool closure rejects a third call deterministically with `QueryBudgetError` (`AGT-2429`) before any network hop occurs. |

### AI.5 Keyless browser and SigV4 IAM proxy at every hop

| | |
|---|---|
| Alternatives considered | Authenticate requests with a shared custom header secret (`x-demo-auth`) in Secrets Manager; expose an unauthenticated Lambda Function URL (`AuthType: NONE`); configure a Cognito User Pool for a single-user portfolio demo |
| Decision | **Route all browser traffic through the Next.js App Router proxy (`app/api/backend/[...path]/route.ts`) running under an Amplify SSR compute role (`computeRoleArn`) granted `runtime.grant_invoke_runtime(ssr_role)` and `execute-api:Invoke`** |
| Rationale | Shared header secrets drift between stacks and still leave a public endpoint open to replay if leaked. Cognito adds a login wall to a public portfolio work sample. By binding an explicit `SsrComputeRole` to the Amplify `WEB_COMPUTE` branch, the browser holds zero credentials, every AWS hop (`API Gateway`, `AgentCore Runtime`, `AgentCore Gateway`) enforces `AWS_IAM`, and local `http://` development against SAM and the local agent stays frictionless. |

### AI.6 Bedrock Prompt Management with versioned reads and fail-closed startup

| | |
|---|---|
| Alternatives considered | Hardcode `SYSTEM_PROMPT` in `agent.py`; bundle `system_prompt.txt` inside the Docker image with an `if unset, read local file` fallback; read the `DRAFT` prompt version at runtime |
| Decision | **Publish immutable prompt versions via `scripts/upload_prompt.py`, resolve the highest numbered version via `ListPrompts` and `GetPrompt` in `ai/services/prompt.py`, ignore `DRAFT`, and fail closed (`AGT-2504`) without invoking the model if the prompt cannot be loaded** |
| Rationale | Baking prompts into container images couples prompt edits to image rebuilds, while reading `DRAFT` exposes the live agent to unreviewed edits in the console. A local file fallback masks IAM or configuration regressions in production by silently running a stale prompt. Failing closed with a typed error (`PromptUnavailableError`) surfaces broken prompt wiring immediately without spending model tokens. |

### AI.7 Two-tier AWS Budgets with automatic IAM Deny actions

| | |
|---|---|
| Alternatives considered | Email-only budget notifications; a single stack-tagged budget |
| Decision | **Provision two monthly `CfnBudget` + `CfnBudgetsAction` pairs in `component.py`: `finops-agent-project` ($17 cap on `aws:cloudformation:stack-name`) and `finops-agent-nova` ($14 cap on regional `Nova2.0Lite` input/output token usage types), each automatically attaching a managed `Deny` policy on `bedrock:InvokeModel` and `InvokeModelWithResponseStream` to the runtime role at 100% actual spend** |
| Rationale | Email alerts do not stop an unattended loop while you are away from the keyboard. Furthermore, Bedrock foundation-model token usage is not tagged with `aws:cloudformation:stack-name`, so a tag-only budget stays blind to model spend. Filtering the second budget directly on the six `USE1`/`USE2`/`USW2` `Nova2.0Lite` token usage types and wiring an automatic IAM `Deny` action cuts off model invocations the moment either threshold is reached. |

### AI.8 Two-stack CDK boundary and synth-time configuration (`SynthSettings`)

| | |
|---|---|
| Alternatives considered | Single CDK stack for all resources; deploy-time `CfnParameter`s or hardcoded physical resource names on compute and log groups |
| Decision | **Split `FinopsAgentStatefulStack` (`AiMemoryConstruct` only) from `FinopsAgentStatelessStack` (compute, gateways, Amplify, budgets), inject all deploy-time settings at synthesis time via `SynthSettings`, use generated physical names for compute/gateways/memory/logs, and verify invariants offline in `tests/test_cdk_stack.py`** |
| Rationale | Separating memory keeps the conversation store intact across stateless compute rebuilds. The precomputed tables live in the Data Lambda image, so there is no data bucket. Passing `github_token_secret_arn` and `budget_alert_email` from `SynthSettings` into `FinopsAgentStatelessStack` follows the CDK synthesis-time configuration pattern without committing personal ARNs to git, while generated resource names prevent replacement collisions during CloudFormation updates. |

Resolved incidents are in `troubleshooting.md`. The roadmap for later phases is `../../plan.md`.

## Deploy

`AWS_REGION`, `AWS_ACCOUNT_ID`, `PROMPT_ARN`, `AGENT_PORT`, `LOCAL_API_PORT`, `GITHUB_TOKEN_SECRET_ARN`, and `BUDGET_ALERT_EMAIL` have no code default. An empty value fails when settings load. `MEMORY_ID` and `GATEWAY_URL` stay unset locally. `make upload-update-prompt` before the first `make deploy`, so `PROMPT_ARN` is set for synth. After the runtime has that ARN, publishing another prompt version does not need a redeploy. `make deploy` synthesizes with `SynthSettings` from `.env` and deploys both stacks. The stateless stack owns two monthly budgets. `finops-agent-project` is $17, filtered to the CloudFormation stack-name tag on both stacks. `finops-agent-nova` is $14, filtered to Nova 2 Lite input and output tokens in Virginia, Ohio, and Oregon. Either one, at 100% actual, attaches a deny of `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` to the runtime role. `make destroy` deletes the budgets with the stack. The stack-name cost allocation tag is on in this account. It can take a day before the $17 budget sees cost. Nova tokens are not on that tag, which is why they have their own filter. Enable Amazon Nova 2 Lite in Bedrock first. The model id in code is the cross-region profile `us.amazon.nova-2-lite-v1:0`. The bare foundation-model id does not accept on-demand `InvokeModel`.

Memory retention is 7 days via the L2 `agentcore.Memory` construct (`Duration.days(7)`). The runtime idle timeout is 8 hours, the API maximum.

Stack outputs: `ApiGatewayUrl`, `AgentRuntimeArn`, `GatewayUrl`, `AmplifyDefaultDomain`. Amplify builds from `src/finops_agent/frontend` (`AMPLIFY_MONOREPO_APP_ROOT`). Put `AmplifyDefaultDomain` in the README placeholder after the first successful deploy.

Deploy only when asked.

## Observability

Checked in `us-east-1`. Transaction Search destination is `CloudWatchLogs` and the status is `ACTIVE`. The Default indexing rule `DesiredSamplingPercentage` is 1. Do not raise it.

The page to open is GenAI Observability, Bedrock AgentCore, Sessions. The session id is the browser `sessionStorage` key `finops-agent-session-id`, sent as `runtimeSessionId`.

Deployed runtime logs and traces go to `/aws/bedrock-agentcore/runtimes/<agent-id>-<endpoint>`. The group appears on first invoke. This runtime's group is `/aws/bedrock-agentcore/runtimes/FinopsAgentStatelessStackAiRuntime100F3236-uGdfwTFOvd-DEFAULT`.

`make dev-agent` is a laptop process. It does not write that log group, and it does not appear on the Sessions page.

Hosted AgentCore runtimes are already instrumented. Do not add a log group, a logs IAM policy, or `AGENT_OBSERVABILITY_ENABLED`. That Sessions page does not need an Omni Domain or Space. None was created.

## Prompt management

The source file is `scripts/system_prompt.txt`. `make upload-update-prompt` runs `scripts/upload_prompt.py`. The first run creates the Bedrock prompt, publishes version 1, and writes the base prompt ARN to `PROMPT_ARN` in `.env`. Later runs update that prompt and publish the next version. The base ARN stays the same, and only that `.env` line is rewritten.

The runtime reads `PROMPT_ARN` from package settings. It calls `ListPrompts` for that prompt, selects the highest numbered version, and calls `GetPrompt` for that version. It does not read the DRAFT. Screen context and the question stay in `agent.py`.

If the prompt cannot be loaded, the runtime logs the AWS error and emits `meta.error` with a fixed sentence (`AGT-2504`). The drawer already shows that as status. The model is not called. There is no fallback to text in git.

Storing and reading the prompt has no separate charge. Nova tokens are charged when the model runs. Do not run prompt optimization, and do not use the console Test button. Do not deploy to test this. `make test` covers the failure path without calling Bedrock.

## Frontend thread

Do this:

- Run `dev-api` and `dev-frontend` and exercise `/`, `/explore`, `/split`, the assistant drawer, and the ask panel.
- Treat a failure as a broken proxy, a wrong `API_BASE_URL`, or a contract mismatch in `lib/api.ts`. Fix it in the frontend subsystem unless the Lambda route itself is wrong.
- Keep both doors (the page and the agent) on the Next proxy.
- Refactor inside `src/finops_agent/frontend`. Do not add a second API client.

Do not do this:

- Change `data/services/domain.py` math.
- Move the query into the browser, the agent image, or a second Lambda.
- Put AWS keys, a shared header, or a secret in client code.
- Add `.env.local`, a new port, or a boolean env flag.
- Deploy to discover a template mistake. Synth and `tests/test_cdk_stack.py` come first.
