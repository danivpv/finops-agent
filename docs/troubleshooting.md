# Troubleshooting

Incidents from building the Phase 1 FinOps agent. The product contract and the decisions that stuck are in `PRD.md`.

## Nova 2 Lite on-demand `ValidationException`

Calling `InvokeModelWithResponseStream` with `amazon.nova-2-lite-v1:0` raised `ValidationException: on-demand throughput isn't supported`. Switching the model id to `us.amazon.nova-2-lite-v1:0` then failed with `AccessDeniedException` when the request was served from another region.

Nova 2 Lite serves on-demand traffic through the cross-region inference profile. Bedrock authorizes both the account-scoped `inference-profile/us.amazon.nova-2-lite-v1:0` ARN and the regional `foundation-model/amazon.nova-2-lite-v1:0` ARN in whichever of `us-east-1`, `us-east-2`, or `us-west-2` handles the call.

`MODEL_ID` in `ai/constants.py` is the profile id. `ai/infrastructure.py` and the budget Deny statements in `component.py` name the profile ARN and the three foundation-model ARNs.

## `InvokeAgentRuntime` denied on the runtime ARN alone

The Next.js SSR proxy received `AccessDeniedException` on `InvokeAgentRuntimeCommand` when the SSR role was allowed to call only `agent_runtime_arn`.

AgentCore dispatches through the default endpoint, so IAM also needs `{runtime_arn}/runtime-endpoint/DEFAULT`. `runtime.grant_invoke_runtime` grants the runtime ARN and `{runtime_arn}/*`. `component.py` uses that grant. `tests/test_cdk_stack.py` asserts both resources.

## Gateway target names reject underscores

A Gateway Lambda target whose name contained an underscore failed to create. Tool calls that used the bare tool name also missed.

Target names are hyphenated. The gateway exposes the tool as `{target}___{tool}`. The target is `finops-data`. The visible tool name is `finops-data___run_finops_query`. `LambdaContextView.tool_name` strips the prefix before dispatch.

## Memory retention: 3 days rejected by the L2 construct

`agentcore.Memory` refuses `expiration_duration` under 7 days. The `CreateMemory` API accepts 3. An earlier pass used L1 `CfnMemory` at 3 days to get past the construct guard.

The current stack uses the L2 construct at 7 days (`MEMORY_EXPIRY_DAYS = 7`). The 3-day API minimum is real, and it is not what this deploy uses.

## Streaming responses

The assistant still streams. `invoke` in `ai/runtime/agent.py` returns a `StreamingResponse` of `text/event-stream` with `event:` lines (`status`, `sql`, `text`, `meta`). The drawer parser in `frontend/lib/api.ts` reads those frames. Nothing in the CDK alignment removed that path.
