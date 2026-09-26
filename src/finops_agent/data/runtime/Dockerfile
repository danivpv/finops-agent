# linux/arm64 matches the Lambda function architecture. A local docker build uses the same pin.
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
    uv sync --frozen --no-install-project --no-editable --no-dev --no-default-groups --group data

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --no-dev --no-default-groups --group data

FROM --platform=linux/arm64 public.ecr.aws/lambda/python:3.12

COPY --from=builder /app/.venv/lib/python3.12/site-packages/ ${LAMBDA_TASK_ROOT}/
COPY src/finops_agent/data/precomputed ${LAMBDA_TASK_ROOT}/finops_agent/data/precomputed

ENV CC_DATA_DIR=${LAMBDA_TASK_ROOT}/finops_agent/data/precomputed

CMD ["finops_agent.data.runtime.handler.handler"]
