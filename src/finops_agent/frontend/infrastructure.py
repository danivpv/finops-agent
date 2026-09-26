"""CDK construct for the Amplify-hosted Next.js frontend."""

from __future__ import annotations

from aws_cdk import (
    aws_amplify as amplify,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class FrontendConstruct(Construct):
    """Provisions the Next.js frontend on AWS Amplify Hosting (WEB_COMPUTE)."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        repository: str,
        branch_name: str,
        github_token: secretsmanager.ISecret,
        api_base_url: str,
        agent_runtime_arn: str,
    ) -> None:
        super().__init__(scope, construct_id)

        role = iam.Role(
            self,
            "AmplifyRole",
            assumed_by=iam.ServicePrincipal(  # ty: ignore[invalid-argument-type]
                "amplify.amazonaws.com"
            ),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AdministratorAccess-Amplify"
                )
            ],
        )

        # SSR compute role: distinct from the build/deploy role above. This is
        # the identity Amplify Hosting's WEB_COMPUTE SSR runtime assumes for
        # each request, wired via `computeRoleArn` below. The browser never
        # holds AWS credentials; this role is how the Next.js proxy calls
        # AgentCore with IAM SigV4 for `/ask` and `/assistant`, and
        # API Gateway with IAM SigV4 for the Data routes.
        self.ssr_role = iam.Role(
            self,
            "SsrComputeRole",
            assumed_by=iam.ServicePrincipal(  # ty: ignore[invalid-argument-type]
                "amplify.amazonaws.com"
            ),
        )
        self.ssr_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                # Invoke is authorized on the default endpoint, not the runtime ARN alone.
                resources=[
                    agent_runtime_arn,
                    f"{agent_runtime_arn}/runtime-endpoint/DEFAULT",
                ],
            )
        )

        # Build settings are the repo-root amplify.yml.
        self.app = amplify.CfnApp(
            self,
            "App",
            name="finops-agent",
            repository=repository,
            access_token=github_token.secret_value.unsafe_unwrap(),
            platform="WEB_COMPUTE",
            iam_service_role=role.role_arn,
            environment_variables=[
                amplify.CfnApp.EnvironmentVariableProperty(
                    name="AMPLIFY_MONOREPO_APP_ROOT", value="src/finops_agent/frontend"
                )
            ],
        )

        self.branch = amplify.CfnBranch(
            self,
            "ProductionBranch",
            app_id=self.app.attr_app_id,
            branch_name=branch_name,
            stage="PRODUCTION",
            enable_auto_build=True,
            framework="Next.js - SSR",
            compute_role_arn=self.ssr_role.role_arn,
            environment_variables=[
                amplify.CfnBranch.EnvironmentVariableProperty(
                    name="NEXT_PUBLIC_API_URL", value="/api/backend"
                ),
                amplify.CfnBranch.EnvironmentVariableProperty(
                    name="API_BASE_URL",
                    value=api_base_url,
                ),
                amplify.CfnBranch.EnvironmentVariableProperty(
                    name="AGENT_RUNTIME_ARN",
                    value=agent_runtime_arn,
                ),
            ],
        )

        self.default_domain = self.app.attr_default_domain
