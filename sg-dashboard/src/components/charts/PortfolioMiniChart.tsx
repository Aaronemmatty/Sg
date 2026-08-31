"use client";

import { useEffect, useState } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { clientFetch } from "@/lib/api/client";
import { formatInrCompact, formatDateShort } from "@/lib/utils/format";
import type { EquityPoint } from "@/types";

export function PortfolioMiniChart() {
  const [data, setData] = useState<EquityPoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    clientFetch<EquityPoint[]>("portfolio/equity-curve?window=30d")
      .then(setData)
      .catch(() => setData([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="h-full bg-surface-2/50 rounded animate-pulse" />;
  }

  if (data.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-text-muted">
        No equity data available
      </div>
    );
  }

  const firstVal = data[0]?.equity_inr ?? 0;
  const lastVal = data[data.length - 1]?.equity_inr ?? 0;
  const isPositive = lastVal >= firstVal;
  const color = isPositive ? "#10B981" : "#EF4444";

  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.2} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis
          dataKey="timestamp"
          tickFormatter={formatDateShort}
          tick={{ fill: "#475569", fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          interval="preserveStartEnd"
        />
        <YAxis
          tickFormatter={formatInrCompact}
          tick={{ fill: "#475569", fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          width={55}
          domain={["auto", "auto"]}
        />
        <Tooltip
          contentStyle={{
            background: "#1A2235",
            border: "1px solid #1E2D45",
            borderRadius: "6px",
            fontSize: "11px",
            color: "#F1F5F9",
          }}
          labelFormatter={formatDateShort}
          formatter={(value: number) => [formatInrCompact(value), "Equity"]}
        />
        <ReferenceLine y={firstVal} stroke="#1E2D45" strokeDasharray="3 3" />
        <Area
          type="monotone"
          dataKey="equity_inr"
          stroke={color}
          strokeWidth={1.5}
          fill="url(#equityGradient)"
          dot={false}
          activeDot={{ r: 3, fill: color }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
