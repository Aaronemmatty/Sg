"use client";

import { useEffect, useRef } from "react";
import type { Candle } from "@/types";

interface Props {
  candles: Candle[];
  height?: number;
}

export function CandlestickChart({ candles, height = 300 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<unknown>(null);

  useEffect(() => {
    if (!containerRef.current || candles.length === 0) return;

    let chart: unknown;
    let series: unknown;

    async function init() {
      const { createChart, ColorType, CrosshairMode } = await import("lightweight-charts");

      if (!containerRef.current) return;

      chart = createChart(containerRef.current, {
        height,
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: "#94A3B8",
        },
        grid: {
          vertLines: { color: "#1E2D45" },
          horzLines: { color: "#1E2D45" },
        },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: {
          borderColor: "#1E2D45",
          textColor: "#94A3B8",
        },
        timeScale: {
          borderColor: "#1E2D45",
          timeVisible: true,
          secondsVisible: false,
        },
      });

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      series = (chart as any).addCandlestickSeries({
        upColor: "#10B981",
        downColor: "#EF4444",
        borderUpColor: "#10B981",
        borderDownColor: "#EF4444",
        wickUpColor: "#10B981",
        wickDownColor: "#EF4444",
      });

      const data = candles.map((c) => ({
        time: (new Date(c.timestamp).getTime() / 1000) as unknown as string,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }));

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (series as any).setData(data);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (chart as any).timeScale().fitContent();
      chartRef.current = chart;
    }

    init();

    return () => {
      if (chartRef.current) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (chartRef.current as any).remove();
        chartRef.current = null;
      }
    };
  }, [candles, height]);

  // Handle resize
  useEffect(() => {
    if (!containerRef.current || !chartRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (chartRef.current as any)?.applyOptions({ width: entry.contentRect.width });
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  return <div ref={containerRef} className="w-full" style={{ height }} />;
}
