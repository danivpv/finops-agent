# Agent guide

## Where code goes

Before writing, name the subsystem and the kind of code.

1. Subsystem: one folder under `src/<package>/`. This repo: `ai`, `data`, `frontend`.
2. Kind: runtime (the process), service (domain logic with no HTTP), infrastructure (a CDK construct), or app wiring (`component.py`, `app.py`).
3. File: prefer the names below. Do not invent a filename when one of these already has that job and do not place all code in one file.
4. A type used by two subsystems lives in the package root (`constants.py`, `exceptions.py`, `schemas.py`). A type used by one subsystem lives in that subsystem.

## Layout

```
app.py                          CDK entry. Instantiates stacks only.
src/<package>/
  component.py                  Composes constructs into stateful and stateless stacks.
  constants.py                  Fixed values shared by more than one subsystem. Not environment variables.
  config.py                     Parent settings for values synth and a runtime both read. Synth-only class in this file. Required fields have no default.
  exceptions.py                 Base exception. Subsystems subclass it.
  schemas.py                    Models shared by more than one subsystem.
  <subsystem>/
    constants.py                Fixed values for this subsystem only.
    infrastructure.py           CDK construct for this subsystem. Not a stack.
    services/                   Domain logic and data access. No FastAPI, Mangum, or Lambda.
    runtime/
      handler.py                Process entry. Declares the app and registers handlers.
      routes.py                 HTTP routes only.
      schemas.py                Request and response models for this process only.
      exceptions.py             Subsystem errors. Subclass the parent exception.
      exception_handlers.py     Map those errors into the HTTP body, if the mapping is not trivial.
      config.py                 This process only. Inherits the package parent. Does not inherit the synth class.
      Dockerfile                Image for this process only.
```

`component.py` is the deployment layout. A subsystem folder owns its construct, its runtime, and its services.

## File purposes

- `handler.py`: process entry. Register exception handlers on the app here. Do not put route bodies here.
- `routes.py`: one function per HTTP path. Call services. Do not parse raw Lambda events here.
- `schemas.py`: Pydantic models. Shared models at package root. Process-only models in `runtime/schemas.py`.
- `exceptions.py`: classes with `status_code`, `error_id`, `message`. Subclass the package base. Do not build errors with ad-hoc dicts.
- `exception_handlers.py`: translate those classes into the response body when the translation is reused. Registration stays in `handler.py`.
- `config.py`: pydantic-settings. The package file holds the parent and the synth class. The runtime file holds that process only.
- `constants.py`: literals that do not change per deploy. Not environment variables.
- `infrastructure.py`: one CDK construct. Hand-written IAM. No `grant_*` helpers that open wildcards.
- `services/`: functions another process could call without starting HTTP.
- Paths: `pathlib.Path`. Do not use the `os` module for filesystem paths.

## Lambda

A Lambda that serves HTTP uses FastAPI and Mangum in `handler.py`. `Mangum(app, lifespan="off")`. Do not create an event loop before Mangum. A buffered API Gateway invocation does not need one.

A non-HTTP door (AgentCore Gateway tool args) is not an API Gateway event. Discriminate with a Pydantic model, then call the same function the HTTP route calls. Allow extra fields on inbound AWS events. Mangum handles HTTP. Do not hand-parse either event.

The image uses `public.ecr.aws/lambda/python`. CMD is the handler module path. Install only that subsystem's uv group.

## API

Browser traffic enters through API Gateway. The browser never holds AWS keys. Authorization is IAM. The server-side proxy signs `https` calls. `http://` is local SAM and stays unsigned.

Routes take Pydantic models. Both doors that need the same work call one function. Do not add a second implementation.

The hosted frontend build spec is `amplify.yml` at the repo root. One copy. The app root in that file matches the monorepo root the platform is given. Do not also store the spec on the construct. The file is the one the platform runs.

## Environment

One `.env` at the repo root. `make` exports it. `.env.sample` lists the variables and is the template for `.env`. Prefer that file. Before changing how a client finds an API, look for a gitignored env file in the subsystem that already overrides it. Do not add a second env file to steer a local run.

A constant is the same in every environment. It lives in `constants.py`: the package root when two subsystems use it, otherwise the subsystem. It is not an environment variable.

An environment variable differs per machine or deploy. pydantic-settings is the only reader. Declare each name once.

- Synth and a runtime both read it: the parent class in package `config.py`. The runtime class inherits that parent.
- Synth alone reads it: the synth class in that same file. Only the CDK entry loads it. A runtime class does not inherit the synth class.
- One process alone reads it: that subsystem's `runtime/config.py`.

A required variable has no default. An empty value is missing, and pydantic fails. Do not invent a fallback to make import or synth succeed. Do not invent a second name for the same value. The process binds `AGENT_PORT` and does not branch on the number. Locally that number is the env value, because this machine cannot bind 8080. The hosted runtime is injected 8080, because that platform dials 8080 only.

Account and region stay in the AWS profile. The CDK CLI and the AWS SDK read them. They are not product environment variables.

Read configuration from the settings object. Do not branch on `os.environ` in routes, handlers, or constructs. Do not construct the settings object at import time. The process loads it at startup. Tests pass an instance.

A script that creates a cloud resource may leave that resource's identifier empty. Synth and the runtime require it.

## States

Keep two environments: development and production. Do not add a third mode inside the process.

A missing cloud resource is not a local fallback. Do not add a boolean flag, an `if unset, use the copy in git` branch, or a second implementation for the laptop. If a new state looks necessary, stop and scope it: the behavior, the alternatives, and which one you recommend. Wait for the developer before writing it.

Source that must exist in AWS (a prompt, a precomputed dataset) stays in the repo and is uploaded by a script. A make target runs that script before deploy. The process reads the cloud resource only.

Deploy-time values are constructor arguments or the platform environment (CDK env, Amplify branch env). They are not a second file in the repo.

`.env.sample` lists every variable. `make` uses the exported variable. Do not put a port number in `constants.py` or the Makefile.

## Dependencies and images

One uv dependency group per subsystem. The frontend stays on its own package manager. The image installs that group only: `--frozen --no-dev --no-default-groups --group <name>`.

Docker is two stages, matching `<subsystem>/runtime/Dockerfile` and the [uv Lambda guide](https://docs.astral.sh/uv/guides/integration/aws-lambda/).

1. Install locked dependencies with the project excluded, so the dependency layer stays cached.
2. Copy source and install the project.
3. The final stage does not contain the uv binary.

AgentCore Runtime images use `python:slim`, copy the virtualenv, and do not use the Lambda base image or the Lambda Web Adapter. Do not copy data files into an image that does not read them.

## Makefile

Targets use a prefix for the tool and a verb for the action.

| Prefix | Meaning |
|---|---|
| `sam-` | Local SAM. `sam-build`, `sam-<function>` invokes that function. |
| `dev-` | A local process. `dev-<subsystem>`. |
| (none) | Repo verbs: `test`, `lint`, `type-check`, `synth`, `deploy`. |

Do not put ports, model ids, or secrets in the Makefile. `deploy` only when asked. Infra changes are proven with template tests, not by deploying.

## AWS CDK

Follow the [CDK application best practices](https://aws.amazon.com/blogs/devops/best-practices-for-developing-cloud-applications-with-aws-cdk/) and the [recommended Python project structure](https://aws.amazon.com/blogs/developer/recommended-aws-cdk-project-structure-for-python-applications/).

- Constructs are logical units. Stacks are deployment units. `component.py` composes constructs. `app.py` only creates stacks.
- Stateful resources that must survive a redeploy live in the stateful stack. Compute and images live in the stateless stack.
- Differences between environments are constructor arguments, not a second copy of the stack.
- Do not rename construct ids without a reason. A new id replaces the resource.
- IAM statements name the actions and the resources. No wildcard grants.
- Test the synthesized template in `tests/`. Do not deploy to discover a template mistake.
- Do not commit secrets. A secret in AWS is referenced by ARN or created by the construct.

## Integration traps

These are the mistakes that cost a deploy cycle. Do not relearn them.

- `FRONTEND_REPOSITORY` is the git remote Amplify builds. It is `https://github.com/danivpv/finops-agent.git`. A push to a different repo does not start a build.
- `AGENT_RUNTIME_ARN` does not exist until the runtime resource is created. CloudFormation writes it onto the Amplify branch. The Next server only sees branch variables that `amplify.yml` echoes into `.env.production` (`API_BASE_URL`, `NEXT_PUBLIC_API_URL`, `AGENT_RUNTIME_ARN`). A missing echo makes `/ask` and `/assistant` look for a local agent.
- `bedrock-agentcore:InvokeAgentRuntime` on the SSR role names the runtime ARN and `{runtime}/runtime-endpoint/DEFAULT`. The runtime ARN alone is denied.
- Image architecture is `linux/arm64` on every `FROM` in the runtime Dockerfiles. Do not also set a platform on the CDK asset.
- A named log group uses `RemovalPolicy.DESTROY`. A retained group with the same name blocks the next create.
- Git Bash rewrites CLI arguments that start with `/`. Prefix those commands with `MSYS_NO_PATHCONV=1`.
- The drawer keeps every turn for the tab. AgentCore Memory is the server copy, actor `demo`, session id from `sessionStorage` (`finops-agent-session-id`). List events with `bedrock-agentcore list-events`.

## What a person sees

A screen, a command, a message, and a document are for the person who uses them. Verifiable behavior is not enough. Step back and ask what they are trying to do, what they already know, and what they would rather not read.

Match the interface that is already there. Read the page, the stylesheet, and the nearest component before adding a control. Use the same type, color, shape, and density. The words on a control are the action. A person should be able to check the result against the screen they are looking at.

Follow the conventions and patterns already in the repo. Look at the docs and at nearby code. If the pattern is not written down, ask. Do not invent a second way because the first one was not in the prompt.

## Review behavior

Use the AWS MCP tools (`aws___search_documentation`, then `aws___read_documentation` or `aws___retrieve_skill`) before guessing a service limit, an API shape, or a price. Be open and communicate alternatives proactively and concisely.Then implement the smallest design that is still complete. KISS and DRY cut extra machinery. They do not cut the real integration.

Stop in the same turn when a service limit blocks the request. Say the limit and the closest legal value. Do not spend a long silent loop and then ship a workaround as if it were the request.

If the platform already emits the logs, traces, or session view, do not add a log group or a hand-written logs policy. Name the console page the user will open before naming the product that delivers the data. A quota is not a budget.

Type-checker ignores are one line and one rule, on the false positive only.

Never `deploy`. Prove infra with template tests.

A bug you notice outside the task gets a short scope before a fix: symptom, cause, options. Do not fold it into the current change unlabeled.

## Review bar

Prefer the library that already does the job. Pydantic validates. FastAPI routes. Mangum adapts Lambda HTTP events. The AWS SDK and `mcp-proxy-for-aws` sign AWS calls. Do not reimplement those.

One function for one behavior. Delete code that nothing calls.

A change is ready for review when a reader can open one subsystem folder and see the route, the model, the error, and the construct without hunting.
