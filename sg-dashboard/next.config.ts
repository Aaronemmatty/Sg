import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [];
  },
  env: {
    AUTH_SERVICE_URL: process.env.AUTH_SERVICE_URL || "http://localhost:8001",
    MARKET_DATA_SERVICE_URL: process.env.MARKET_DATA_SERVICE_URL || "http://localhost:8002",
    BROKER_SERVICE_URL: process.env.BROKER_SERVICE_URL || "http://localhost:8003",
    STRATEGY_SERVICE_URL: process.env.STRATEGY_SERVICE_URL || "http://localhost:8004",
    REGIME_SERVICE_URL: process.env.REGIME_SERVICE_URL || "http://localhost:8005",
    ORCHESTRATOR_SERVICE_URL: process.env.ORCHESTRATOR_SERVICE_URL || "http://localhost:8006",
    RISK_ENGINE_URL: process.env.RISK_ENGINE_URL || "http://localhost:8007",
    EXECUTION_ENGINE_URL: process.env.EXECUTION_ENGINE_URL || "http://localhost:8008",
    PORTFOLIO_SERVICE_URL: process.env.PORTFOLIO_SERVICE_URL || "http://localhost:8009",
    BACKTESTING_SERVICE_URL: process.env.BACKTESTING_SERVICE_URL || "http://localhost:8010",
    ML_PLATFORM_URL: process.env.ML_PLATFORM_URL || "http://localhost:8011",
    AI_ANALYST_URL: process.env.AI_ANALYST_URL || "http://localhost:8012",
  },
};

export default nextConfig;
