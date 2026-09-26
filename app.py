#!/usr/bin/env python3
"""CDK application entry point."""

from __future__ import annotations

import aws_cdk as cdk

from finops_agent.component import FinopsAgentStack, FinopsAgentStatefulStack
from finops_agent.config import SynthSettings

settings = SynthSettings()
app = cdk.App()
env = cdk.Environment(account=settings.account, region=settings.region)

stateful = FinopsAgentStatefulStack(app, "FinopsAgentStatefulStack", env=env)
stateless = FinopsAgentStack(
    app,
    "FinopsAgentStack",
    stateful=stateful,
    prompt_arn=settings.prompt_arn,
    local_api_port=settings.local_api_port,
    env=env,
)
stateless.add_stack_dependency(stateful)

app.synth()
