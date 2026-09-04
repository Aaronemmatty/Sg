"use client";

import { useEffect, useState } from "react";
import { clientFetch, ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils/cn";
import {
  ExternalLink,
  KeyRound,
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Loader2,
  Lock,
  ArrowRight,
} from "lucide-react";
import toast from "react-hot-toast";
import type { User } from "@/types";

interface BrokerStatus {
  broker: string;
  mode: string;
  connected: boolean;
  circuit_breaker?: Record<string, any> | null;
  rate_limiter?: Record<string, any> | null;
}

interface LoginUrlResponse {
  login_url: string;
  api_key: string;
}

interface SessionResponse {
  ok: boolean;
  message: string;
}

export function KiteAuthContent({ user }: { user: User }) {
  const [status, setStatus] = useState<BrokerStatus | null>(null);
  const [loginUrl, setLoginUrl] = useState<string>("");
  const [apiKey, setApiKey] = useState<string>("");
  const [requestToken, setRequestToken] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(true);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [lastMessage, setLastMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  async function loadData() {
    setLoading(true);
    try {
      const [statusData, loginData] = await Promise.all([
        clientFetch<BrokerStatus>("broker/status"),
        clientFetch<LoginUrlResponse>("broker/kite/login-url"),
      ]);
      setStatus(statusData);
      setLoginUrl(loginData.login_url);
      setApiKey(loginData.api_key);
    } catch (err: any) {
      const msg = err instanceof ApiError ? err.message : "Failed to connect to broker service";
      setLastMessage({ type: "error", text: msg });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  async function handleSubmitToken(e: React.FormEvent) {
    e.preventDefault();
    const token = requestToken.trim();
    if (!token) {
      toast.error("Please enter a request_token");
      return;
    }

    setSubmitting(true);
    setLastMessage(null);

    try {
      const res = await clientFetch<SessionResponse>("broker/kite/session", {
        method: "POST",
        body: JSON.stringify({ request_token: token }),
      });

      // Clear the transient input immediately upon success
      setRequestToken("");
      setLastMessage({
        type: "success",
        text: res.message || "Kite session activated successfully! The broker is now live and connected.",
      });
      toast.success("Kite session activated!");

      // Refresh broker status
      await loadData();
    } catch (err: any) {
      const errorMsg = err instanceof ApiError ? err.message : err.message || "Failed to activate Kite session";
      setLastMessage({ type: "error", text: errorMsg });
      toast.error(errorMsg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-fade-in">
      {/* Header Banner */}
      <div className="flex items-center justify-between p-5 bg-surface-2 border border-border rounded-xl">
        <div className="flex items-center gap-3.5">
          <div className="w-10 h-10 rounded-lg bg-accent/10 border border-accent/20 flex items-center justify-center">
            <KeyRound className="w-5 h-5 text-accent" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-text-primary">Zerodha Kite Authentication</h1>
            <p className="text-xs text-text-muted">
              Operator authentication gateway for daily Zerodha Connect session generation.
            </p>
          </div>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="btn-secondary flex items-center gap-2 text-xs px-3 py-2"
          id="btn-refresh-status"
        >
          <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
          Refresh Status
        </button>
      </div>

      {/* Connection Status Card */}
      <div className="card p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wider">
            Current Broker Connection Status
          </h2>
          {status && (
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "w-2.5 h-2.5 rounded-full",
                  status.connected ? "bg-bull animate-pulse" : "bg-bear"
                )}
              />
              <span
                id="broker-connection-badge"
                className={cn(
                  "text-xs font-semibold px-2.5 py-1 rounded-full border",
                  status.connected
                    ? "bg-bull/10 text-bull border-bull/30"
                    : "bg-bear/10 text-bear border-bear/30"
                )}
              >
                {status.connected ? "Connected" : "Disconnected / Auth Required"}
              </span>
            </div>
          )}
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="w-6 h-6 animate-spin text-accent" />
          </div>
        ) : status ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-2 border-t border-border">
            <div className="p-3 bg-surface-2 rounded-lg border border-border">
              <div className="text-2xs text-text-muted uppercase">Broker Name</div>
              <div className="text-sm font-semibold text-text-primary mt-0.5 capitalize">
                {status.broker}
              </div>
            </div>
            <div className="p-3 bg-surface-2 rounded-lg border border-border">
              <div className="text-2xs text-text-muted uppercase">Broker Mode</div>
              <div className="text-sm font-semibold text-text-primary mt-0.5 uppercase font-mono">
                {status.mode}
              </div>
            </div>
            <div className="p-3 bg-surface-2 rounded-lg border border-border">
              <div className="text-2xs text-text-muted uppercase">Circuit Breaker</div>
              <div className="text-sm font-semibold text-bull mt-0.5 capitalize">
                {status.circuit_breaker?.state || "Closed (Healthy)"}
              </div>
            </div>
            <div className="p-3 bg-surface-2 rounded-lg border border-border">
              <div className="text-2xs text-text-muted uppercase">Rate Limiter</div>
              <div className="text-sm font-semibold text-text-primary mt-0.5">
                {status.rate_limiter?.calls_in_window ?? 0} / {status.rate_limiter?.max_calls ?? 10} rps
              </div>
            </div>
          </div>
        ) : (
          <div className="text-xs text-text-muted py-3">Could not load broker status.</div>
        )}
      </div>

      {/* Step 1: Open Login URL */}
      <div className="card p-6 space-y-4">
        <div className="flex items-start gap-4">
          <div className="w-8 h-8 rounded-full bg-accent/10 border border-accent/30 text-accent font-bold text-sm flex items-center justify-center shrink-0">
            1
          </div>
          <div className="space-y-1">
            <h3 className="text-sm font-semibold text-text-primary">
              Log into Zerodha Kite via OAuth
            </h3>
            <p className="text-xs text-text-muted">
              Click the button below to launch the official Zerodha login page in a new browser tab.
              Authenticate with your Zerodha credentials and 2FA.
            </p>
          </div>
        </div>

        <div className="pl-12">
          {loginUrl ? (
            <a
              id="btn-kite-login"
              href={loginUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-primary inline-flex items-center gap-2 text-xs font-semibold px-4 py-2.5 rounded-lg shadow-sm hover:shadow transition-all"
            >
              <span>Login to Zerodha Kite</span>
              <ExternalLink className="w-4 h-4" />
            </a>
          ) : (
            <div className="text-xs text-bear">Login URL not available. Verify API credentials in broker_service.</div>
          )}
          {apiKey && (
            <div className="text-2xs text-text-muted mt-2 font-mono">
              Registered API Key: <span className="text-text-secondary">{apiKey}</span>
            </div>
          )}
        </div>
      </div>

      {/* Step 2: Paste request_token and Submit */}
      <div className="card p-6 space-y-4">
        <div className="flex items-start gap-4">
          <div className="w-8 h-8 rounded-full bg-accent/10 border border-accent/30 text-accent font-bold text-sm flex items-center justify-center shrink-0">
            2
          </div>
          <div className="space-y-1">
            <h3 className="text-sm font-semibold text-text-primary">
              Paste Redirect Request Token
            </h3>
            <p className="text-xs text-text-muted">
              After successful login, Zerodha redirects your browser to your configured redirect URL.
              Copy the <code className="px-1.5 py-0.5 bg-surface-2 text-accent rounded font-mono">request_token</code> query parameter from your browser's address bar and paste it below.
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmitToken} className="pl-12 space-y-4">
          <div>
            <label htmlFor="input-request-token" className="block text-2xs font-medium text-text-secondary uppercase mb-1.5">
              Request Token
            </label>
            <div className="relative">
              <input
                id="input-request-token"
                type="text"
                autoComplete="off"
                spellCheck={false}
                value={requestToken}
                onChange={(e) => setRequestToken(e.target.value)}
                placeholder="e.g. 7kF9xY1zW4..."
                className="w-full bg-surface-2 border border-border rounded-lg px-4 py-2.5 text-sm font-mono text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent transition-all"
                disabled={submitting}
              />
              <Lock className="w-4 h-4 text-text-muted absolute right-3 top-3 pointer-events-none" />
            </div>
            <p className="text-2xs text-text-muted mt-1">
              Transient submission only. The token is never written to localStorage or cookies.
            </p>
          </div>

          <button
            id="btn-submit-kite-session"
            type="submit"
            disabled={submitting || !requestToken.trim()}
            className="btn-primary flex items-center gap-2 text-xs font-semibold px-5 py-2.5 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            {submitting ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Exchanging Token with Zerodha...</span>
              </>
            ) : (
              <>
                <span>Activate Kite Session</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </>
            )}
          </button>
        </form>
      </div>

      {/* Response Feedback Alerts */}
      {lastMessage && (
        <div
          id="kite-auth-feedback"
          className={cn(
            "p-4 rounded-xl border flex items-start gap-3 transition-all",
            lastMessage.type === "success"
              ? "bg-bull/10 border-bull/30 text-bull"
              : "bg-bear/10 border-bear/30 text-bear"
          )}
        >
          {lastMessage.type === "success" ? (
            <CheckCircle2 className="w-5 h-5 shrink-0 mt-0.5" />
          ) : (
            <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
          )}
          <div className="space-y-1">
            <div className="text-xs font-bold uppercase tracking-wider">
              {lastMessage.type === "success" ? "Session Activation Success" : "Authentication Error"}
            </div>
            <div className="text-xs font-mono">{lastMessage.text}</div>
          </div>
        </div>
      )}

      {/* Security Info Footnote */}
      <div className="p-4 bg-surface-2/40 border border-border/70 rounded-lg flex items-center gap-3 text-xs text-text-muted">
        <ShieldCheck className="w-4 h-4 text-accent shrink-0" />
        <span>
          Access token is secured in Redis with a 26-hour TTL and refreshed automatically across platform workers via internal Pub/Sub.
        </span>
      </div>
    </div>
  );
}
