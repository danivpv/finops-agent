#!/usr/bin/env python3
"""CDK application entry point."""

from __future__ import annotations

import aws_cdk as cdk

from finops_agent.component import FinopsAgentStatefulStack, FinopsAgentStatelessStack
from finops_agent.config import SynthSettings

settings = SynthSettings()
app = cdk.App()
env = cdk.Environment(account=settings.account, region=settings.region)

stateful = FinopsAgentStatefulStack(app, "FinopsAgentStatefulStack", env=env)
stateless = FinopsAgentStatelessStack(
    app,
    "FinopsAgentStatelessStack",
    stateful=stateful,
    prompt_arn=settings.prompt_arn,
    local_api_port=settings.local_api_port,
    github_token_secret_arn=settings.github_token_secret_arn,
    budget_alert_email=settings.budget_alert_email,
    env=env,
)
stateless.add_stack_dependency(stateful)

app.synth()
