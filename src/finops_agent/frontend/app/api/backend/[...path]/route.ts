import { NextRequest } from "next/server";
import { Readable } from "node:stream";
import { BedrockAgentCoreClient, InvokeAgentRuntimeCommand } from "@aws-sdk/client-bedrock-agentcore";
import { defaultProvider } from "@aws-sdk/credential-provider-node";
import { SignatureV4 } from "@aws-sdk/signature-v4";
import { Sha256 } from "@aws-crypto/sha256-js";
import { HttpRequest } from "@smithy/protocol-http";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Context = { params: Promise<{ path: string[] }> };

// The browser never holds AWS credentials. This server signs with the Amplify
// SSR compute role: AgentCore for /ask and /assistant, IAM on API Gateway for
// every other path. http:// targets (local SAM) are not signed.
const AGENT_ROUTES = new Set(["ask", "assistant"]);

let agentCoreClient: BedrockAgentCoreClient | undefined;

function getAgentCoreClient(): BedrockAgentCoreClient {
  agentCoreClient ??= new BedrockAgentCoreClient({});
  return agentCoreClient;
}

// Local process is `python -m finops_agent.ai.runtime.agent` (POST /invocations).
// AGENT_PORT comes from the repo-root .env. When AGENT_RUNTIME_ARN is unset,
// the proxy talks to that local server instead of SigV4.
const LOCAL_RUNTIME_URL = process.env.AGENT_RUNTIME_URL
  ?? (process.env.AGENT_PORT ? `http://127.0.0.1:${process.env.AGENT_PORT}` : undefined);

async function invokeLocalAgent(body: Record<string, unknown>, sessionId: string | undefined): Promise<Response> {
  if (!LOCAL_RUNTIME_URL) {
    return Response.json({ error: "AGENT_PORT is not set." }, { status: 503 });
  }
  const headers = new Headers({ "content-type": "application/json", accept: "text/event-stream" });
  if (sessionId) headers.set("X-Amzn-Bedrock-AgentCore-Runtime-Session-Id", sessionId);
  let upstream: Response;
  try {
    upstream = await fetch(`${LOCAL_RUNTIME_URL.replace(/\/$/, "")}/invocations`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return Response.json({ error: "Local agent is not running." }, { status: 502 });
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
  });
}

async function invokeAgent(request: NextRequest): Promise<Response> {
  const agentRuntimeArn = process.env.AGENT_RUNTIME_ARN;

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const sessionId = typeof body.session_id === "string" ? body.session_id : undefined;
  if (!agentRuntimeArn) return invokeLocalAgent(body, sessionId);

  let response;
  try {
    response = await getAgentCoreClient().send(
      new InvokeAgentRuntimeCommand({
        agentRuntimeArn,
        runtimeSessionId: sessionId,
        contentType: "application/json",
        accept: "text/event-stream",
        payload: new TextEncoder().encode(JSON.stringify(body)),
      }),
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return Response.json({ error: `AgentCore invoke failed: ${message}` }, { status: 502 });
  }

  const nodeStream = response.response;
  if (!nodeStream) {
    return Response.json({ error: "Empty AgentCore response." }, { status: 502 });
  }

  const webStream = Readable.toWeb(nodeStream as Readable) as ReadableStream<Uint8Array>;
  return new Response(webStream, {
    status: response.statusCode ?? 200,
    headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
  });
}

async function proxy(request: NextRequest, { params }: Context) {
  const { path } = await params;

  if (path.length > 0 && AGENT_ROUTES.has(path[0])) {
    return invokeAgent(request);
  }

  const apiBaseUrl = process.env.API_BASE_URL;
  if (!apiBaseUrl) {
    return Response.json({ error: "Backend proxy is not configured." }, { status: 503 });
  }

  const target = new URL(path.join("/"), `${apiBaseUrl.replace(/\/$/, "")}/`);
  target.search = request.nextUrl.search;
  const requestBody = request.method === "GET" || request.method === "HEAD"
    ? undefined
    : await request.arrayBuffer();
  const upstream = target.protocol === "http:"
    ? await fetch(target, {
      method: request.method,
      headers: proxyHeaders(request),
      body: requestBody,
      cache: "no-store",
    })
    : await signedApiFetch(target, request.method, requestBody, request);

  const responseHeaders = new Headers();
  for (const name of ["content-type", "cache-control"]) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

function proxyHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  headers.set("accept", request.headers.get("accept") ?? "application/json");
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  return headers;
}

async function signedApiFetch(
  target: URL,
  method: string,
  body: ArrayBuffer | undefined,
  request: NextRequest,
): Promise<Response> {
  const region = process.env.AWS_REGION ?? process.env.AWS_DEFAULT_REGION ?? "us-east-1";
  const payload = body ? new Uint8Array(body) : undefined;
  const signer = new SignatureV4({
    credentials: defaultProvider(),
    region,
    service: "execute-api",
    sha256: Sha256,
  });
  const headers: Record<string, string> = {
    host: target.host,
    accept: request.headers.get("accept") ?? "application/json",
  };
  const contentType = request.headers.get("content-type");
  if (contentType) headers["content-type"] = contentType;
  const signed = await signer.sign(
    new HttpRequest({
      method,
      protocol: target.protocol,
      hostname: target.hostname,
      path: target.pathname,
      query: Object.fromEntries(target.searchParams),
      headers,
      body: payload,
    }),
  );
  return fetch(target, {
    method,
    headers: signed.headers,
    body: payload,
    cache: "no-store",
  });
}

export const GET = proxy;
export const POST = proxy;
