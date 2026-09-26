"""CDK construct for the Data Lambda service (economics math + analytical store)."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import (
    Duration,
    RemovalPolicy,
    aws_lambda as _lambda,
    aws_logs as logs,
)
from constructs import Construct


class DataConstruct(Construct):
    """Provisions the serverless Data backend Lambda."""

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        environment: dict[str, str] = {
            "CC_DATA_DIR": "/var/task/finops_agent/data/precomputed",
        }

        log_group = logs.LogGroup(
            self,
            "Logs",
            log_group_name="/finops-agent/data",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        repo_root = Path(__file__).resolve().parents[3]

        self.function = _lambda.DockerImageFunction(
            self,
            "Function",
            code=_lambda.DockerImageCode.from_image_asset(
                str(repo_root),
                file="src/finops_agent/data/runtime/Dockerfile",
            ),
            architecture=_lambda.Architecture.ARM_64,
            memory_size=512,
            timeout=Duration.seconds(30),
            environment=environment,
            log_group=log_group,
        )
