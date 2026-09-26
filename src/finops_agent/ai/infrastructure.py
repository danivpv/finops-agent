"""CDK constructs for the AgentCore short-term Memory and Runtime.

Split across the two stacks: `AiMemoryConstruct` is stateful (the Memory
resource must outlive redeploys of the runtime that reads/writes it);
`AiConstruct` is stateless (the Runtime, its ECR image asset, and its
execution role are rebuilt freely).
"""

from __future__ import annotations

from aws_cdk import (
    Duration,
    Stack,
    aws_bedrockagentcore as agentcore,
    aws_iam as iam,
    aws_lambda as _lambda,
)
from constructs import Construct

from ..constants import GATEWAY_TARGET_NAME, REPO_ROOT
from .constants import (
    BASE_MODEL_ID,
    MEMORY_EXPIRY_DAYS,
    MODEL_ID,
    MODEL_SOURCE_REGIONS,
    RUNTIME_IDLE_SESSION_TIMEOUT_SECONDS,
    RUNTIME_MAX_LIFETIME_SECONDS,
)


class AiMemoryConstruct(Construct):
    """Provisions AgentCore short-term Memory. No long-term strategies.

    Uses the L1 `CfnMemory` directly rather than the L2 `Memory` construct:
    the L2 enforces a client-side 7-365 day range for `expiration_duration`,
    but the real `CreateMemory` API accepts 3-365 — the L2's guard is simply
    wrong. `MEMORY_EXPIRY_DAYS` uses the true minimum. See `docs/PRD.md` §AI.2.
    """

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        self.memory = agentcore.CfnMemory(
            self,
            "Memory",
            name="FinopsAgentMemory",
            event_expiry_duration=MEMORY_EXPIRY_DAYS,
            # memory_strategies omitted: no long-term extraction. It calls a
            # model to extract long-term memories and is out of scope here.
        )
        self.memory_arn = self.memory.attr_memory_arn
        self.memory_id = self.memory.attr_memory_id


class AiConstruct(Construct):
    """Provisions the AgentCore Runtime and the Gateway in front of the Data Lambda."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        memory_arn: str,
        memory_id: str,
        data_function: _lambda.IFunction,
        prompt_arn: str,
        local_api_port: int,
    ) -> None:
        super().__init__(scope, construct_id)

        repo_root = REPO_ROOT
        stack = Stack.of(self)

        # Hand-built least-privilege execution role. No `grant_*` wildcards.
        # `Runtime` itself attaches its baseline policy (the service log group
        # `/aws/bedrock-agentcore/runtimes/*`, X-Ray, ECR pull, workload
        # identity). Observability traces and session views come from that.
        # This role only adds model invoke, this memory, this prompt, and the
        # query gateway.
        self.execution_role = iam.Role(
            self,
            "ExecutionRole",
            assumed_by=iam.ServicePrincipal(  # ty: ignore[invalid-argument-type]
                "bedrock-agentcore.amazonaws.com"
            ),
        )
        execution_role = self.execution_role

        # 1. Invoke exactly this model. Nova 2 Lite is cross-region-inference-
        # only: direct on-demand invocation of the bare foundation-model id
        # fails with ValidationException even when it's enabled on the
        # account (confirmed against a live account). The inference-profile
        # ARN is account-scoped; the underlying foundation-model ARNs it
        # routes to are not. See docs/PRD.md §AI.1.
        inference_profile_arn = stack.format_arn(
            service="bedrock",
            resource="inference-profile",
            resource_name=MODEL_ID,
        )
        foundation_model_arns = [
            f"arn:{stack.partition}:bedrock:{region}::foundation-model/{BASE_MODEL_ID}"
            for region in MODEL_SOURCE_REGIONS
        ]
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=[inference_profile_arn, *foundation_model_arns],
            )
        )

        # 2. Read/write only this memory's short-term conversational events —
        # not the LTM-record APIs `Memory.grant_read`/`grant_write` cover.
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:ListEvents",
                    "bedrock-agentcore:GetEvent",
                    "bedrock-agentcore:CreateEvent",
                ],
                resources=[memory_arn],
            )
        )

        # IAM inbound auth. The L2 default authorizer is Cognito, which this
        # stack does not use. The Lambda target is the same Data function API
        # Gateway already invokes.
        self.gateway = agentcore.Gateway(
            self,
            "Gateway",
            gateway_name="FinopsAgentGateway",
            description="Typed FinOps query tool backed by the Data Lambda",
            authorizer_configuration=agentcore.GatewayAuthorizer.using_aws_iam(),
        )
        self.gateway.add_lambda_target(
            "DataQuery",
            gateway_target_name=GATEWAY_TARGET_NAME,
            description="Store.investigate over the precomputed cost dice",
            lambda_function=data_function,
            tool_schema=agentcore.ToolSchema.from_local_asset(
                str(REPO_ROOT / "src" / "finops_agent" / "ai" / "run_finops_query.json")
            ),
        )
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeGateway"],
                resources=[self.gateway.gateway_arn],
            )
        )
        # ListPrompts picks the highest published version. GetPrompt reads it.
        # The runtime never requests the DRAFT.
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:GetPrompt", "bedrock:ListPrompts"],
                # A published version is its own ARN: prompt/ID:2, not prompt/ID.
                resources=[prompt_arn, f"{prompt_arn}:*"],
            )
        )

        self.runtime = agentcore.Runtime(
            self,
            "Runtime",
            agent_runtime_artifact=agentcore.AgentRuntimeArtifact.from_asset(
                str(repo_root),
                file="src/finops_agent/ai/runtime/Dockerfile",
            ),
            execution_role=execution_role,  # ty: ignore[invalid-argument-type]
            environment_variables={
                "MEMORY_ID": memory_id,
                "GATEWAY_URL": self.gateway.gateway_url or "",
                "PROMPT_ARN": prompt_arn,
                # The platform dials 8080. The local process uses its own port.
                "AGENT_PORT": "8080",
                "LOCAL_API_PORT": str(local_api_port),
            },
            lifecycle_configuration=agentcore.LifecycleConfiguration(
                idle_runtime_session_timeout=Duration.seconds(
                    RUNTIME_IDLE_SESSION_TIMEOUT_SECONDS
                ),
                max_lifetime=Duration.seconds(RUNTIME_MAX_LIFETIME_SECONDS),
            ),
            # No custom log group. Runtime stdout and traces go to the
            # service group `/aws/bedrock-agentcore/runtimes/<id>-<endpoint>`.
            # authorizer_configuration omitted: defaults to IAM (SigV4).
            # Never AuthType.NONE, never Cognito/JWT for this thread.
        )
        self.agent_runtime_arn = self.runtime.agent_runtime_arn
