import { type NextRequest, NextResponse } from "next/server";
import { getAccessToken } from "@/lib/auth/session";
import { SERVICES } from "@/lib/api/client";

// Route prefix → service mapping
const ROUTE_MAP: Array<{ prefix: string; service: string }> = [
  { prefix: "portfolio/", service: SERVICES.portfolio },
  { prefix: "portfolio", service: SERVICES.portfolio },
  { prefix: "risk/", service: SERVICES.risk },
  { prefix: "risk", service: SERVICES.risk },
  { prefix: "strategies/", service: SERVICES.strategy },
  { prefix: "strategies", service: SERVICES.strategy },
  { prefix: "regime/", service: SERVICES.regime },
  { prefix: "regime", service: SERVICES.regime },
  { prefix: "ml/", service: SERVICES.ml },
  { prefix: "ml", service: SERVICES.ml },
  { prefix: "backtesting/", service: SERVICES.backtesting },
  { prefix: "backtesting", service: SERVICES.backtesting },
  { prefix: "market/", service: SERVICES.marketData },
  { prefix: "market", service: SERVICES.marketData },
  { prefix: "broker/", service: SERVICES.broker },
  { prefix: "broker", service: SERVICES.broker },
  { prefix: "execution/", service: SERVICES.execution },
  { prefix: "execution", service: SERVICES.execution },
  { prefix: "analyst/", service: SERVICES.analyst },
  { prefix: "analyst", service: SERVICES.analyst },
];

// Map proxy path segments to backend API paths
const BACKEND_PATH_MAP: Record<string, string> = {
  "portfolio/snapshot": "/api/v1/portfolio/snapshot",
  "portfolio/positions": "/api/v1/portfolio/positions",
  "portfolio/exposure": "/api/v1/portfolio/exposure",
  "portfolio/trades": "/api/v1/ledger/trades",
  "risk/metrics": "/api/v1/risk/metrics",
  "risk/events": "/api/v1/risk/events",
  "regime/current": "/api/v1/regime/current",
  "ml/registry/champions": "/api/v1/registry/champions",
  "ml/registry/models": "/api/v1/registry/models",
  "ml/training/jobs": "/api/v1/training/jobs",
  "ml/training/active": "/api/v1/training/active",
  "ml/monitoring/drift": "/api/v1/monitoring/drift",
  "ml/monitoring/accuracy": "/api/v1/monitoring/accuracy",
  "backtesting/runs": "/api/v1/backtest/runs",
  "market/symbols": "/api/v1/symbols",
  "analyst/reports": "/api/v1/reports",
};

function resolveBackend(path: string): { baseUrl: string; backendPath: string } | null {
  // Check exact map first
  if (BACKEND_PATH_MAP[path]) {
    const match = ROUTE_MAP.find((r) => path.startsWith(r.prefix));
    if (match) return { baseUrl: match.service, backendPath: BACKEND_PATH_MAP[path] };
  }

  // Pattern-based resolution
  const match = ROUTE_MAP.find((r) => path.startsWith(r.prefix));
  if (!match) return null;

  // Derive backend path
  let backendPath = path;

  // portfolio/*
  if (path.startsWith("portfolio/performance/")) {
    backendPath = `/api/v1/performance/${path.replace("portfolio/performance/", "")}`;
  } else if (path.startsWith("portfolio/")) {
    backendPath = `/api/v1/${path.replace("portfolio/", "")}`;
  }
  // risk/*
  else if (path.startsWith("risk/")) {
    backendPath = `/api/v1/risk/${path.replace("risk/", "")}`;
  }
  // strategies/*
  else if (path.startsWith("strategies")) {
    backendPath = `/api/v1/strategies${path.replace("strategies", "")}`;
  }
  // regime/*
  else if (path.startsWith("regime/")) {
    backendPath = `/api/v1/regime/${path.replace("regime/", "")}`;
  }
  // ml/*
  else if (path.startsWith("ml/")) {
    const mlPath = path.replace("ml/", "");
    if (mlPath.startsWith("registry/")) backendPath = `/api/v1/${mlPath}`;
    else if (mlPath.startsWith("training/")) backendPath = `/api/v1/${mlPath}`;
    else if (mlPath.startsWith("monitoring/")) backendPath = `/api/v1/${mlPath}`;
    else if (mlPath.startsWith("predict/")) backendPath = `/api/v1/${mlPath}`;
    else if (mlPath.startsWith("features/")) backendPath = `/api/v1/${mlPath}`;
    else backendPath = `/api/v1/${mlPath}`;
  }
  // backtesting/*
  else if (path.startsWith("backtesting/")) {
    const btPath = path.replace("backtesting/", "");
    backendPath = `/api/v1/backtest/${btPath}`;
  }
  // market/*
  else if (path.startsWith("market/candles/")) {
    const symbol = path.replace("market/candles/", "").split("?")[0];
    const qs = path.includes("?") ? `?${path.split("?")[1]}` : "";
    backendPath = `/api/v1/symbols/${symbol}/candles${qs}`;
  }
  else if (path.startsWith("market/")) {
    backendPath = `/api/v1/${path.replace("market/", "")}`;
  }
  // analyst/*
  else if (path.startsWith("analyst/")) {
    backendPath = `/api/v1/${path.replace("analyst/", "")}`;
  }
  // broker/* execution/*
  else {
    backendPath = `/api/v1/${path}`;
  }

  return { baseUrl: match.service, backendPath };
}

async function handler(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const token = await getAccessToken();
  if (!token) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  const { path: pathSegments } = await params;
  const proxyPath = pathSegments.join("/");
  const queryString = req.nextUrl.search;

  const resolved = resolveBackend(proxyPath);
  if (!resolved) {
    return NextResponse.json({ detail: "Unknown service route" }, { status: 404 });
  }

  const targetUrl = `${resolved.baseUrl}${resolved.backendPath}${queryString}`;

  try {
    const body = req.method !== "GET" && req.method !== "HEAD"
      ? await req.text()
      : undefined;

    const upstream = await fetch(targetUrl, {
      method: req.method,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body,
    });

    const data = await upstream.json().catch(() => null);
    return NextResponse.json(data, { status: upstream.status });
  } catch (err) {
    console.error(`Proxy error for ${targetUrl}:`, err);
    return NextResponse.json(
      { detail: "Service unavailable" },
      { status: 503 }
    );
  }
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
