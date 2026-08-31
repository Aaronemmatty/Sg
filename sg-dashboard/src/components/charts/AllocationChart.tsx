"use client";

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import type { Position } from "@/types";
import { formatPct } from "@/lib/utils/format";

const COLORS = [
  "#F59E0B", "#10B981", "#3B82F6", "#8B5CF6",
  "#EF4444", "#06B6D4", "#F97316", "#EC4899",
  "#84CC16", "#6366F1",
];

interface Props {
  positions: Position[];
}

export function AllocationChart({ positions }: Props) {
  if (positions.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-text-muted">
        No positions
      </div>
    );
  }

  const data = positions.map((p) => ({
    name: p.symbol,
    value: p.weight_pct,
    marketValue: p.market_value_inr,
  }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius="55%"
          outerRadius="80%"
          paddingAngle={2}
          dataKey="value"
        >
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} opacity={0.85} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            background: "#1A2235",
            border: "1px solid #1E2D45",
            borderRadius: "6px",
            fontSize: "11px",
            color: "#F1F5F9",
          }}
          formatter={(value: number, name: string) => [formatPct(value), name]}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}
