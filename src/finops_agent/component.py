"""CDK stacks: stateful data plane, and the stateless API + AgentCore Runtime + Amplify app."""

from __future__ import annotations

from typing import Any

from aws_cdk import (
    CfnOutput,
    CfnParameter,
    RemovalPolicy,
    Stack,
    aws_apigateway as apigw,
    aws_budgets as budgets,
    aws_iam as iam,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct

from .ai.constants import BASE_MODEL_ID, MODEL_ID, MODEL_SOURCE_REGIONS
from .ai.infrastructure import AiConstruct, AiMemoryConstruct
from .constants import FRONTEND_BRANCH, FRONTEND_REPOSITORY
from .data.infrastructure import DataConstruct
from .frontend.infrastructure import FrontendConstruct


class FinopsAgentStatefulStack(Stack):
    """S3 data bucket and AgentCore Memory.

    These outlive redeploys of the stateless stack. Passed in as a construct.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Unused on the hot path today. Real data lands here later, so RETAIN.
        self.data_bucket = s3.Bucket(
            self,
            "DataBucket",
            removal_policy=RemovalPolicy.RETAIN,
            enforce_ssl=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        self.memory = AiMemoryConstruct(self, "AiMemory")


class FinopsAgentStack(Stack):
    """Data Lambda, API Gateway, AgentCore Gateway and Runtime, and Amplify."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stateful: FinopsAgentStatefulStack,
        prompt_arn: str,
        local_api_port: int,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        github_token_secret_arn = CfnParameter(
            self,
            "GithubTokenSecretArn",
            type="String",
            no_echo=True,
            description="Secrets Manager ARN holding the GitHub access token used by Amplify.",
        )

        self.data = DataConstruct(self, "Data")

        self.ai = AiConstruct(
            self,
            "Ai",
            memory_arn=stateful.memory.memory_arn,
            memory_id=stateful.memory.memory_id,
            data_function=self.data.function,  # ty: ignore[invalid-argument-type]
            prompt_arn=prompt_arn,
            local_api_port=local_api_port,
        )

        # Data routes only. /ask and /assistant are invoked on the Runtime
        # by the Next proxy, not by API Gateway.
        self.api = apigw.RestApi(
            self,
            "ApiGateway",
            rest_api_name="FinopsAgentApi",
            description="Serverless API routing to the Data Lambda.",
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["*"],
            ),
            deploy_options=apigw.StageOptions(stage_name="prod"),
        )

        data_integration = apigw.LambdaIntegration(
            self.data.function  # ty: ignore[invalid-argument-type]
        )
        iam_auth = apigw.AuthorizationType.IAM
        self.api.root.add_method("ANY", data_integration, authorization_type=iam_auth)
        self.api.root.add_proxy(
            default_integration=data_integration,
            any_method=True,
            default_method_options=apigw.MethodOptions(authorization_type=iam_auth),
        )

        github_token = secretsmanager.Secret.from_secret_complete_arn(
            self, "GithubToken", github_token_secret_arn.value_as_string
        )
        self.frontend = FrontendConstruct(
            self,
            "Frontend",
            repository=FRONTEND_REPOSITORY,
            branch_name=FRONTEND_BRANCH,
            github_token=github_token,
            api_base_url=self.api.url,
            agent_runtime_arn=self.ai.agent_runtime_arn,
        )
        self.frontend.ssr_role.add_to_policy(
            iam.PolicyStatement(
                actions=["execute-api:Invoke"],
                resources=[self.api.arn_for_execute_api()],
            )
        )

        self._spend_caps(stateful)

        CfnOutput(self, "ApiGatewayUrl", value=self.api.url)
        CfnOutput(self, "AgentRuntimeArn", value=self.ai.agent_runtime_arn)
        CfnOutput(self, "GatewayUrl", value=self.ai.gateway.gateway_url or "")
        CfnOutput(self, "DataBucketName", value=stateful.data_bucket.bucket_name)
        CfnOutput(self, "AmplifyDefaultDomain", value=self.frontend.default_domain)

    def _spend_caps(self, stateful: FinopsAgentStatefulStack) -> None:
        """Monthly caps. Either one denies Nova 2 Lite invoke on the runtime role.

        The project cap follows the CloudFormation stack-name tag. That tag has
        to be an active cost allocation tag or the cap stays at zero. Nova
        tokens are a separate filter: they are not tagged with the stack.
        """
        email = CfnParameter(
            self,
            "BudgetAlertEmail",
            type="String",
            allowed_pattern=r".+@.+\..+",
            description="Inbox for the project and Nova budget alerts.",
        ).value_as_string
        nova_resources = [
            self.format_arn(
                service="bedrock",
                resource="inference-profile",
                resource_name=MODEL_ID,
            ),
            *[
                f"arn:{self.partition}:bedrock:{region}::foundation-model/{BASE_MODEL_ID}"
                for region in MODEL_SOURCE_REGIONS
            ],
        ]
        project_policy = self._nova_deny("ProjectNovaDeny", nova_resources)
        token_policy = self._nova_deny("TokenNovaDeny", nova_resources)
        action_role = iam.Role(
            self,
            "BudgetsActionRole",
            assumed_by=iam.ServicePrincipal(  # ty: ignore[invalid-argument-type]
                "budgets.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {
                        "aws:SourceArn": self.format_arn(
                            service="budgets",
                            region="",
                            resource="budget",
                            resource_name="*",
                        )
                    },
                },
            ),
        )
        action_role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:AttachRolePolicy", "iam:DetachRolePolicy"],
                resources=[self.ai.execution_role.role_arn],
                conditions={
                    "ArnEquals": {
                        "iam:PolicyARN": [
                            project_policy.managed_policy_arn,
                            token_policy.managed_policy_arn,
                        ]
                    }
                },
            )
        )
        action_role.add_to_policy(
            iam.PolicyStatement(
                actions=["iam:GetRole", "iam:ListAttachedRolePolicies"],
                resources=[self.ai.execution_role.role_arn],
            )
        )
        self._budget_with_deny(
            construct_id="ProjectBudget",
            budget_name="finops-agent-project",
            amount=17,
            cost_filters={
                "TagKeyValue": [
                    f"aws:cloudformation:stack-name${self.stack_name}",
                    f"aws:cloudformation:stack-name${stateful.stack_name}",
                ]
            },
            policy=project_policy,
            action_role=action_role,
            email=email,
        )
        usage_prefix = {"us-east-1": "USE1", "us-east-2": "USE2", "us-west-2": "USW2"}
        self._budget_with_deny(
            construct_id="NovaBudget",
            budget_name="finops-agent-nova",
            amount=14,
            cost_filters={
                "UsageType": [
                    f"{usage_prefix[region]}-Nova2.0Lite-{kind}"
                    for region in MODEL_SOURCE_REGIONS
                    for kind in ("input-tokens", "output-tokens")
                ]
            },
            policy=token_policy,
            action_role=action_role,
            email=email,
        )

    def _nova_deny(self, construct_id: str, resources: list[str]) -> iam.ManagedPolicy:
        return iam.ManagedPolicy(
            self,
            construct_id,
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.DENY,
                    actions=[
                        "bedrock:InvokeModel",
                        "bedrock:InvokeModelWithResponseStream",
                    ],
                    resources=resources,
                )
            ],
        )

    def _budget_with_deny(
        self,
        *,
        construct_id: str,
        budget_name: str,
        amount: int,
        cost_filters: dict[str, list[str]],
        policy: iam.ManagedPolicy,
        action_role: iam.Role,
        email: str,
    ) -> None:
        budget = budgets.CfnBudget(
            self,
            construct_id,
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=budget_name,
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=amount, unit="USD"),
                cost_filters=cost_filters,
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        comparison_operator="GREATER_THAN",
                        notification_type="ACTUAL",
                        threshold=100,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            address=email,
                            subscription_type="EMAIL",
                        )
                    ],
                )
            ],
        )
        action = budgets.CfnBudgetsAction(
            self,
            f"{construct_id}Action",
            budget_name=budget_name,
            notification_type="ACTUAL",
            action_type="APPLY_IAM_POLICY",
            approval_model="AUTOMATIC",
            action_threshold=budgets.CfnBudgetsAction.ActionThresholdProperty(
                type="PERCENTAGE",
                value=100,
            ),
            execution_role_arn=action_role.role_arn,
            definition=budgets.CfnBudgetsAction.DefinitionProperty(
                iam_action_definition=budgets.CfnBudgetsAction.IamActionDefinitionProperty(
                    policy_arn=policy.managed_policy_arn,
                    roles=[self.ai.execution_role.role_name],
                )
            ),
            subscribers=[
                budgets.CfnBudgetsAction.SubscriberProperty(address=email, type="EMAIL")
            ],
        )
        action.node.add_dependency(budget)
