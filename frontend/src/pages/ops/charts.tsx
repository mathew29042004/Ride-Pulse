import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { RIDE_TYPE_COLORS } from "@/components/map";
import { inr, inrCompact } from "@/lib/format";
import type { Breakdown, SeriesPoint } from "@/lib/types";

const axis = { fill: "var(--color-muted)", fontSize: 11 };
const tooltipStyle = {
  background: "var(--color-surface)",
  border: "1px solid var(--color-line)",
  borderRadius: 12,
  fontSize: 12,
  color: "var(--color-fg)",
};

function label(bucket: string, unit: string) {
  const d = new Date(bucket);
  return unit === "hour"
    ? d.toLocaleTimeString("en-IN", { hour: "numeric" })
    : d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function TripsChart({ series, unit }: { series: SeriesPoint[]; unit: string }) {
  const data = series.map((p) => ({ ...p, label: label(p.bucket, unit) }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}>
        <defs>
          <linearGradient id="req" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#0ea5e9" stopOpacity={0.25} />
            <stop offset="100%" stopColor="#0ea5e9" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="done" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#10b981" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke="var(--color-line)" />
        <XAxis dataKey="label" tick={axis} axisLine={false} tickLine={false} minTickGap={16} />
        <YAxis tick={axis} axisLine={false} tickLine={false} allowDecimals={false} />
        <Tooltip contentStyle={tooltipStyle} />
        <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
        <Area type="monotone" dataKey="requested" name="Requested" stroke="#0ea5e9" fill="url(#req)" strokeWidth={2} />
        <Area type="monotone" dataKey="completed" name="Completed" stroke="#10b981" fill="url(#done)" strokeWidth={2} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function GmvChart({ series, unit }: { series: SeriesPoint[]; unit: string }) {
  const data = series.map((p) => ({ label: label(p.bucket, unit), gmv: Number(p.gmv), surge: p.avg_surge }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 10, right: 10, left: 4, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--color-line)" />
        <XAxis dataKey="label" tick={axis} axisLine={false} tickLine={false} minTickGap={16} />
        <YAxis tick={axis} axisLine={false} tickLine={false} tickFormatter={(v) => inrCompact(v)} width={64} />
        <Tooltip contentStyle={tooltipStyle} formatter={(v) => [inr(Number(v)), "GMV"]} cursor={{ fill: "var(--color-surface-3)" }} />
        <Bar dataKey="gmv" fill="#10b981" radius={[6, 6, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function RideTypeDonut({ data }: { data: Breakdown["ride_types"] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie data={data} dataKey="trips" nameKey="name" innerRadius="58%" outerRadius="88%" paddingAngle={2} stroke="none">
          {data.map((d) => (
            <Cell key={d.code} fill={d.code === "SEDAN" ? "#475569" : (RIDE_TYPE_COLORS[d.code] ?? "#94a3b8")} />
          ))}
        </Pie>
        <Tooltip contentStyle={tooltipStyle} />
        <Legend iconType="circle" layout="vertical" align="right" verticalAlign="middle" wrapperStyle={{ fontSize: 12 }} />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function HourlyChart({ data }: { data: Breakdown["hourly"] }) {
  const max = Math.max(...data.map((d) => d.requests), 1);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 10, right: 0, left: -24, bottom: 0 }}>
        <XAxis dataKey="hour" tick={axis} axisLine={false} tickLine={false} tickFormatter={(h) => (h % 3 === 0 ? `${h}h` : "")} />
        <YAxis tick={axis} axisLine={false} tickLine={false} allowDecimals={false} />
        <Tooltip contentStyle={tooltipStyle} labelFormatter={(h) => `${h}:00 – ${h}:59`} cursor={{ fill: "var(--color-surface-3)" }} />
        <Bar dataKey="requests" name="Requests" radius={[4, 4, 0, 0]}>
          {data.map((d) => (
            <Cell key={d.hour} fill={d.requests / max > 0.75 ? "#f59e0b" : "#0ea5e9"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
