// Service URL registry — server-side only (BFF pattern)
export const SERVICES = {
  auth: process.env.AUTH_SERVICE_URL || "http://localhost:8001",
  marketData: process.env.MARKET_DATA_SERVICE_URL || "http://localhost:8002",
  broker: process.env.BROKER_SERVICE_URL || "http://localhost:8003",
  strategy: process.env.STRATEGY_SERVICE_URL || "http://localhost:8004",
  regime: process.env.REGIME_SERVICE_URL || "http://localhost:8005",
  orchestrator: process.env.ORCHESTRATOR_SERVICE_URL || "http://localhost:8006",
  risk: process.env.RISK_ENGINE_URL || "http://localhost:8007",
  execution: process.env.EXECUTION_ENGINE_URL || "http://localhost:8008",
  portfolio: process.env.PORTFOLIO_SERVICE_URL || "http://localhost:8009",
  backtesting: process.env.BACKTESTING_SERVICE_URL || "http://localhost:8010",
  ml: process.env.ML_PLATFORM_URL || "http://localhost:8011",
  analyst: process.env.AI_ANALYST_URL || "http://localhost:8012",
} as const;

export type ServiceKey = keyof typeof SERVICES;

// ─── Server-side fetch with Bearer token ────────────────────────────────────

export async function serverFetch<T>(
  url: string,
  token: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...options.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(res.status, body || res.statusText);
  }

  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ─── Client-side fetch (hits Next.js /api/proxy/*) ──────────────────────────

export async function clientFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`/api/proxy/${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail || res.statusText);
  }

  return res.json() as Promise<T>;
}
