# linux/arm64 is the image AgentCore runs. A local docker build uses the same pin.
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:latest AS uv
FROM --platform=linux/arm64 python:3.12-slim AS builder

COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1
ENV UV_NO_PROGRESS=1
ENV UV_LINK_MODE=copy

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-editable --no-dev --no-default-groups --group ai

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --no-dev --no-default-groups --group ai \
    && rm -rf /app/.venv/lib/python3.12/site-packages/finops_agent/data/precomputed

# AgentCore runs this image directly: it speaks its own container contract
# (POST /invocations, GET /ping on 8088), not the Lambda Runtime Interface.
# No `public.ecr.aws/lambda/python` base, no Lambda Web Adapter, no dice.
FROM --platform=linux/arm64 python:3.12-slim

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}"

WORKDIR /app
EXPOSE 8088

CMD ["python", "-m", "finops_agent.ai.runtime.agent"]
