"use client";

import { useEffect, useRef, useCallback } from "react";

interface UseSSEOptions<T> {
  url: string;
  onMessage: (data: T) => void;
  onError?: (err: Event) => void;
  enabled?: boolean;
  reconnectDelay?: number;
}

export function useSSE<T = unknown>({
  url,
  onMessage,
  onError,
  enabled = true,
  reconnectDelay = 3000,
}: UseSSEOptions<T>) {
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!enabled || !mountedRef.current) return;

    esRef.current?.close();
    const es = new EventSource(url, { withCredentials: true });
    esRef.current = es;

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as T;
        onMessage(data);
      } catch {
        // ignore malformed frames
      }
    };

    es.onerror = (err) => {
      onError?.(err);
      es.close();
      if (mountedRef.current) {
        reconnectTimer.current = setTimeout(connect, reconnectDelay);
      }
    };
  }, [url, enabled, onMessage, onError, reconnectDelay]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      esRef.current?.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [connect]);
}

// ─── Typed SSE hooks per service ────────────────────────────────────────────

import { useStore } from "@/lib/stores/app.store";
import type { ExecutionEvent, RiskEvent, PortfolioSnapshot } from "@/types";

const SSE_BASE = process.env.NEXT_PUBLIC_SSE_BASE_URL || "http://localhost";

export function usePortfolioStream() {
  const setSnapshot = useStore((s) => s.setSnapshot);
  const addExecution = useStore((s) => s.addExecution);

  useSSE<{ type: string; data: unknown }>({
    url: `${SSE_BASE}:8009/api/v1/portfolio/stream`,
    onMessage: (event) => {
      if (event.type === "SNAPSHOT_UPDATE") {
        setSnapshot(event.data as PortfolioSnapshot);
      }
      if (event.type === "EXECUTION") {
        addExecution(event.data as ExecutionEvent);
      }
    },
  });
}

export function useRiskStream() {
  const addRiskEvent = useStore((s) => s.addRiskEvent);
  const setMetrics = useStore((s) => s.setMetrics);

  useSSE<{ type: string; data: unknown }>({
    url: `${SSE_BASE}:8007/api/v1/risk/stream`,
    onMessage: (event) => {
      if (event.type === "RISK_EVENT") {
        addRiskEvent(event.data as RiskEvent);
      }
      if (event.type === "METRICS_UPDATE") {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        setMetrics(event.data as any);
      }
    },
  });
}

export function useExecutionStream() {
  const addExecution = useStore((s) => s.addExecution);

  useSSE<ExecutionEvent>({
    url: `${SSE_BASE}:8008/api/v1/execution/stream`,
    onMessage: addExecution,
  });
}
