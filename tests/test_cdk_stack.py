"""Infrastructure assertions for the two FinOps Agent stacks.

Follows the AWS CDK best-practices blog: test synthesized CloudFormation
rather than hoping deployments behave. Runs fully offline (fixed fake env,
no STS/account lookup) and fast enough for `make test`.
"""

import json
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk import assertions

from finops_agent.component import FinopsAgentStack, FinopsAgentStatefulStack

_ENV = cdk.Environment(account="111122223333", region="us-east-1")
_PROMPT_ARN = "arn:aws:bedrock:us-east-1:111122223333:prompt/ABCDEFGHIJ"


def _templates() -> tuple[assertions.Template, assertions.Template]:
    app = cdk.App()
    stateful = FinopsAgentStatefulStack(app, "TestStatefulStack", env=_ENV)
    stack = FinopsAgentStack(
        app,
        "TestStack",
        env=_ENV,
        stateful=stateful,
        prompt_arn=_PROMPT_ARN,
        local_api_port=3001,
    )
    return (
        assertions.Template.from_stack(stateful),
        assertions.Template.from_stack(stack),
    )


def test_data_bucket_is_retained_not_auto_deleted() -> None:
    stateful, _ = _templates()
    buckets = stateful.find_resources("AWS::S3::Bucket")
    assert len(buckets) == 1
    bucket = next(iter(buckets.values()))
    assert bucket["DeletionPolicy"] == "Retain"
    assert bucket["UpdateReplacePolicy"] == "Retain"
    # No auto-delete-objects custom resource Lambda for this bucket.
    assert not stateful.find_resources("Custom::S3AutoDeleteObjects")


def test_memory_has_no_long_term_strategies_and_short_expiry() -> None:
    stateful, _ = _templates()
    memories = stateful.find_resources("AWS::BedrockAgentCore::Memory")
    assert len(memories) == 1
    props = next(iter(memories.values()))["Properties"]
    assert "MemoryStrategies" not in props
    # AWS's real `CreateMemory` minimum is 3 days (the CDK L2 `Memory`
    # construct's 7-day client-side guard is wrong); see docs/PRD.md §AI.2.
    assert props["EventExpiryDuration"] == 3


def test_one_data_lambda_no_ai_lambda() -> None:
    _, stack = _templates()
    functions = stack.find_resources("AWS::Lambda::Function")
    assert len(functions) == 1
    props = next(iter(functions.values()))["Properties"]
    assert props["PackageType"] == "Image"
    assert props["MemorySize"] == 512
    assert props["Timeout"] == 30
    env = props["Environment"]["Variables"]
    assert env["CC_DATA_DIR"] == "/var/task/finops_agent/data/precomputed"
    assert "CC_DATA_BUCKET" not in env
    assert "CC_AUTH_SECRET_ARN" not in env


def test_no_lambda_function_urls() -> None:
    """The old AI Function URL (`AuthType: NONE`) is gone entirely."""
    _, stack = _templates()
    assert not stack.find_resources("AWS::Lambda::Url")


def test_api_gateway_has_no_ask_or_assistant_routes() -> None:
    _, stack = _templates()
    resources = stack.find_resources("AWS::ApiGateway::Resource")
    path_parts = {props["Properties"]["PathPart"] for props in resources.values()}
    assert "assistant" not in path_parts
    assert "ask" not in path_parts


def test_exactly_one_agentcore_runtime_with_iam_auth() -> None:
    _, stack = _templates()
    runtimes = stack.find_resources("AWS::BedrockAgentCore::Runtime")
    assert len(runtimes) == 1
    props = next(iter(runtimes.values()))["Properties"]
    # No `AuthorizerConfiguration` -> defaults to IAM. Never AuthType: NONE.
    assert "AuthorizerConfiguration" not in props
    # 8-hour idle session (API max 28800s). Runtime lifecycle TTL, not Memory
    # eventExpiryDuration (that API is days, minimum 3).
    lifecycle = props["LifecycleConfiguration"]
    assert lifecycle["IdleRuntimeSessionTimeout"] == 8 * 60 * 60
    assert lifecycle["MaxLifetime"] == 8 * 60 * 60


def test_runtime_has_no_custom_log_group() -> None:
    """AgentCore writes logs and traces itself. The Data Lambda keeps its own group."""
    _, stack = _templates()
    names = {
        props["Properties"].get("LogGroupName")
        for props in stack.find_resources("AWS::Logs::LogGroup").values()
    }
    assert names == {"/finops-agent/data"}
    runtimes = stack.find_resources("AWS::BedrockAgentCore::Runtime")
    runtime_props = next(iter(runtimes.values()))["Properties"]
    assert "LoggingConfig" not in runtime_props


def test_runtime_role_is_least_privilege_no_grant_wildcards() -> None:
    """The Runtime's own custom statements are model, memory, prompt read, and gateway invoke."""
    _, stack = _templates()
    policies = stack.find_resources("AWS::IAM::Policy")
    ai_policy = next(
        props
        for name, props in policies.items()
        if name.startswith("AiExecutionRoleDefaultPolicy")
    )
    custom_statements = ai_policy["Properties"]["PolicyDocument"]["Statement"]

    model_stmt = next(
        s for s in custom_statements if "bedrock:InvokeModel" in _actions(s)
    )
    assert all("bedrock:" in action for action in _actions(model_stmt))
    resources = model_stmt["Resource"]
    assert any("nova-2-lite" in str(r) for r in resources)

    memory_stmt = next(
        s for s in custom_statements if "bedrock-agentcore:CreateEvent" in _actions(s)
    )
    assert set(_actions(memory_stmt)) == {
        "bedrock-agentcore:ListEvents",
        "bedrock-agentcore:GetEvent",
        "bedrock-agentcore:CreateEvent",
    }

    gateway_stmt = next(
        s for s in custom_statements if "bedrock-agentcore:InvokeGateway" in _actions(s)
    )
    assert _actions(gateway_stmt) == ["bedrock-agentcore:InvokeGateway"]
    assert gateway_stmt["Resource"] != "*"

    prompt_stmt = next(
        s for s in custom_statements if "bedrock:GetPrompt" in _actions(s)
    )
    assert set(_actions(prompt_stmt)) == {"bedrock:GetPrompt", "bedrock:ListPrompts"}
    resources = prompt_stmt["Resource"]
    assert set(resources if isinstance(resources, list) else [resources]) == {
        _PROMPT_ARN,
        f"{_PROMPT_ARN}:*",
    }

    assert not any(
        "logs:" in action
        for statement in custom_statements
        for action in _actions(statement)
        if "Sid" not in statement
    )


def _actions(statement: dict) -> list[str]:
    actions = statement["Action"]
    return actions if isinstance(actions, list) else [actions]


def test_runtime_env_points_at_the_gateway_not_the_dice() -> None:
    _, stack = _templates()
    runtimes = stack.find_resources("AWS::BedrockAgentCore::Runtime")
    env = next(iter(runtimes.values()))["Properties"]["EnvironmentVariables"]
    assert "MEMORY_ID" in env
    assert "GATEWAY_URL" in env
    assert env["PROMPT_ARN"] == _PROMPT_ARN
    assert env["AGENT_PORT"] == "8080"
    assert env["LOCAL_API_PORT"] == "3001"
    assert "CC_DATA_DIR" not in env


def test_required_settings_have_no_defaults(monkeypatch) -> None:
    """Missing or empty required values fail in pydantic. No code fallback."""
    from pydantic import ValidationError

    from finops_agent.config import Settings, SynthSettings

    monkeypatch.delenv("PROMPT_ARN", raising=False)
    monkeypatch.delenv("AGENT_PORT", raising=False)
    filled = {
        "region": "us-east-1",
        "prompt_arn": _PROMPT_ARN,
        "agent_port": 8088,
        "local_api_port": 3001,
        "account": "111122223333",
        "github_token_secret_arn": "arn:aws:secretsmanager:us-east-1:111122223333:secret:g",
    }
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, **{k: v for k, v in filled.items() if k != "prompt_arn"}
        )
    with pytest.raises(ValidationError):
        SynthSettings(_env_file=None, **filled | {"prompt_arn": ""})
    assert Settings.model_fields["agent_port"].is_required()
    assert "container_agent_port" not in SynthSettings.model_fields


def test_one_iam_gateway_targets_the_data_lambda() -> None:
    """Browser API Gateway and the agent Gateway share the one Data function."""
    _, stack = _templates()
    assert not stack.find_resources("AWS::Cognito::UserPool")

    gateways = stack.find_resources("AWS::BedrockAgentCore::Gateway")
    assert len(gateways) == 1
    gateway = next(iter(gateways.values()))["Properties"]
    assert gateway["AuthorizerType"] == "AWS_IAM"
    assert gateway["Name"] == "FinopsAgentGateway"

    targets = stack.find_resources("AWS::BedrockAgentCore::GatewayTarget")
    assert len(targets) == 1
    target = next(iter(targets.values()))["Properties"]
    assert target["Name"] == "finops-data"
    lambda_arn = target["TargetConfiguration"]["Mcp"]["Lambda"]["LambdaArn"]
    functions = stack.find_resources("AWS::Lambda::Function")
    assert len(functions) == 1
    function_id = next(iter(functions))
    assert lambda_arn == {"Fn::GetAtt": [function_id, "Arn"]}
    schema = target["TargetConfiguration"]["Mcp"]["Lambda"]["ToolSchema"]
    assert schema["S3"]["Uri"].startswith("s3://")
    tool = json.loads(
        (
            Path(__file__).parents[1]
            / "src"
            / "finops_agent"
            / "ai"
            / "run_finops_query.json"
        ).read_text(encoding="utf-8")
    )[0]
    assert tool["name"] == "run_finops_query"
    assert tool["inputSchema"]["required"] == ["group_by", "metric", "period"]


def test_ssr_role_invokes_the_runtime_and_the_data_api() -> None:
    _, stack = _templates()
    policies = stack.find_resources("AWS::IAM::Policy")
    ssr_policy = next(
        props
        for name, props in policies.items()
        if name.startswith("FrontendSsrComputeRoleDefaultPolicy")
    )
    statements = ssr_policy["Properties"]["PolicyDocument"]["Statement"]
    actions = {action for statement in statements for action in _actions(statement)}
    assert actions == {
        "bedrock-agentcore:InvokeAgentRuntime",
        "execute-api:Invoke",
    }
    invoke = next(
        statement
        for statement in statements
        if "bedrock-agentcore:InvokeAgentRuntime" in _actions(statement)
    )
    resources = invoke["Resource"]
    assert any(
        "runtime-endpoint/DEFAULT" in json.dumps(resource) for resource in resources
    )


def test_budgets_deny_nova_for_the_project_and_for_tokens() -> None:
    _, stack = _templates()
    budgets = stack.find_resources("AWS::Budgets::Budget")
    by_name = {
        props["Properties"]["Budget"]["BudgetName"]: props["Properties"]["Budget"]
        for props in budgets.values()
    }
    assert set(by_name) == {"finops-agent-project", "finops-agent-nova"}
    assert by_name["finops-agent-project"]["BudgetLimit"] == {
        "Amount": 17,
        "Unit": "USD",
    }
    assert by_name["finops-agent-nova"]["BudgetLimit"] == {"Amount": 14, "Unit": "USD"}
    tags = by_name["finops-agent-project"]["CostFilters"]["TagKeyValue"]
    assert "aws:cloudformation:stack-name$TestStack" in tags
    assert "aws:cloudformation:stack-name$TestStatefulStack" in tags
    assert set(by_name["finops-agent-nova"]["CostFilters"]["UsageType"]) == {
        "USE1-Nova2.0Lite-input-tokens",
        "USE1-Nova2.0Lite-output-tokens",
        "USE2-Nova2.0Lite-input-tokens",
        "USE2-Nova2.0Lite-output-tokens",
        "USW2-Nova2.0Lite-input-tokens",
        "USW2-Nova2.0Lite-output-tokens",
    }

    actions = stack.find_resources("AWS::Budgets::BudgetsAction")
    assert len(actions) == 2
    for props in actions.values():
        action = props["Properties"]
        assert action["ActionType"] == "APPLY_IAM_POLICY"
        assert action["ApprovalModel"] == "AUTOMATIC"
        assert action["NotificationType"] == "ACTUAL"
        assert action["ActionThreshold"] == {"Type": "PERCENTAGE", "Value": 100}
        definition = action["Definition"]["IamActionDefinition"]
        assert definition["Roles"]

    denies = [
        statement
        for props in stack.find_resources("AWS::IAM::ManagedPolicy").values()
        for statement in props["Properties"]["PolicyDocument"]["Statement"]
        if statement["Effect"] == "Deny"
    ]
    assert len(denies) == 2
    for statement in denies:
        assert set(_actions(statement)) == {
            "bedrock:InvokeModel",
            "bedrock:InvokeModelWithResponseStream",
        }
        rendered = json.dumps(statement["Resource"])
        assert "us.amazon.nova-2-lite-v1:0" in rendered
        for region in ("us-east-1", "us-east-2", "us-west-2"):
            assert (
                f"bedrock:{region}::foundation-model/amazon.nova-2-lite-v1:0"
                in rendered
            )
