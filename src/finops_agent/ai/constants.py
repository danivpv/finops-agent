"""Fixed policy for the AgentCore Runtime and its Strands agent.

No aws_cdk imports here: the runtime image does not install the infra group.
Deployment-varying values (`MEMORY_ID`, `GATEWAY_URL`) are read by
`runtime/config.py`. `PROMPT_ARN`, the region, and the local port are on the
package settings, which this process inherits. The hosted runtime listens
on 8080, the port the platform dials.
"""

from __future__ import annotations

# Cross-region inference profile. Direct on-demand invocation of the bare
# foundation-model id (`amazon.nova-2-lite-v1:0`) fails with
# `ValidationException: on-demand throughput isn't supported` even when the
# model is enabled on the account. Nova 2 Lite is CRIS-only. See docs/PRD.md.
MODEL_ID = "us.amazon.nova-2-lite-v1:0"
BASE_MODEL_ID = "amazon.nova-2-lite-v1:0"
MODEL_SOURCE_REGIONS = ("us-east-1", "us-east-2", "us-west-2")

# The model plans at most this many typed queries per question.
MAX_QUERY_STEPS = 2

# Single demo actor. No Cognito, no per-user identity.
ACTOR_ID = "demo"

# CreateMemory minimum is 3 days. CDK L2 Memory rejects anything under 7.
# See docs/PRD.md §AI.2. This is event retention, not a chat-session timeout.
MEMORY_EXPIRY_DAYS = 3

# Each turn reads and writes at most this many events for the current
# actor+session. No cross-session recall and no long-term strategies.
MAX_MEMORY_EVENTS = 10

# Runtime lifecycle, in seconds. API max for idle session timeout is 28800 (8h).
RUNTIME_IDLE_SESSION_TIMEOUT_SECONDS = 8 * 60 * 60
RUNTIME_MAX_LIFETIME_SECONDS = 8 * 60 * 60

# One Bedrock Prompt Management prompt. The runtime reads the highest
# published version. The DRAFT is the working copy the upload script updates.
PROMPT_NAME = "finops-agent-system"
PROMPT_VARIANT_NAME = "system"

# Customer-facing answer when the prompt cannot be loaded. No model call.
PROMPT_UNAVAILABLE_MESSAGE = (
    "The assistant is not available right now. "
    "The Bedrock agent could not load its prompt."
)
