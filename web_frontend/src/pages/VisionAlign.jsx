import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Hash, RefreshCw, Search } from "lucide-react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import ChartCard from "../components/charts/ChartCard.jsx";
import MetricCard from "../components/cards/MetricCard.jsx";
import PageHeader from "../components/layout/PageHeader.jsx";
import StatusBadge from "../components/logs/StatusBadge.jsx";
import { robotLogApi } from "../api/api.js";
import { formatNumber, formatPreciseDate, formatTimeLabel, timestampOf } from "../utils/format.js";

const STEP_OPTIONS = ["PICK", "PLACE"];

function buildRows(items) {
  return [...items]
    .sort((a, b) => timestampOf(a.created_at) - timestampOf(b.created_at))
    .map((item) => ({
      time: formatTimeLabel(item.created_at),
      dx: Number(item.offset_x || 0),
      dy: Number(item.offset_y || 0),
      dtheta: Number(item.offset_theta || 0),
    }));
}

function symmetricDomain(rows) {
  const maxAbs = rows.reduce((currentMax, row) => (
    Math.max(currentMax, Math.abs(row.dx), Math.abs(row.dy), Math.abs(row.dtheta))
  ), 0);
  const padded = Math.max(maxAbs * 1.15, 1);
  return [-padded, padded];
}

export default function VisionAlign() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState({
    process_step: "",
    camera_type: "",
    history_id: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const loadVisionAlign = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await robotLogApi.listVisionAlignLogs({
        limit: 100,
        offset: 0,
        process_step: filters.process_step,
        camera_type: filters.camera_type.trim(),
        history_id: filters.history_id,
      });
      setItems(response?.data?.items || []);
      setTotal(response?.data?.total || 0);
    } catch (requestError) {
      setError(requestError.message || "비전 정렬 로그를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    loadVisionAlign();
  }, [loadVisionAlign]);

  const chartRows = useMemo(() => buildRows(items), [items]);
  const chartDomain = useMemo(() => symmetricDomain(chartRows), [chartRows]);
  const metrics = useMemo(() => {
    const maxError = items.reduce((currentMax, item) => Math.max(
      currentMax,
      Math.abs(Number(item.offset_x || 0)),
      Math.abs(Number(item.offset_y || 0)),
      Math.abs(Number(item.offset_theta || 0)),
    ), 0);
    return {
      total,
      pick: items.filter((item) => item.process_step === "PICK").length,
      place: items.filter((item) => item.process_step === "PLACE").length,
      maxError,
    };
  }, [items, total]);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Vision Logs"
        title="Vision Align"
        description="Pick/Place 공정의 카메라 보정 offset과 0 기준 수렴 상태를 확인합니다."
        actions={
          <button
            className="inline-flex h-10 items-center gap-2 rounded-md bg-moss px-4 text-sm font-bold text-white disabled:opacity-60"
            onClick={loadVisionAlign}
            type="button"
            disabled={loading}
          >
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        }
      />

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
          {error}
        </div>
      ) : null}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Total" value={metrics.total} icon={Activity} caption="matching rows" />
        <MetricCard label="Pick" value={metrics.pick} icon={Activity} tone="signal" caption="pick offsets" />
        <MetricCard label="Place" value={metrics.place} icon={Activity} tone="signal" caption="place offsets" />
        <MetricCard label="Max Abs" value={formatNumber(metrics.maxError, 3)} icon={Activity} tone="ember" caption="x/y/theta" />
      </section>

      <ChartCard title="Alignment Error Convergence" description="x/y/theta offset이 0 기준선으로 가까워지는 흐름입니다.">
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartRows}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="time" tick={{ fontSize: 12 }} minTickGap={18} />
              <YAxis domain={chartDomain} tickFormatter={(value) => formatNumber(value, 2)} width={64} />
              <Tooltip formatter={(value, name) => [formatNumber(value, 4), name]} />
              <Legend />
              <ReferenceLine y={0} stroke="#202822" strokeDasharray="5 5" />
              <Line type="monotone" dataKey="dx" name="x error" stroke="#267a4d" strokeWidth={3} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="dy" name="y error" stroke="#376d86" strokeWidth={3} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="dtheta" name="theta error" stroke="#a46213" strokeWidth={3} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>

      <section className="rounded-lg border border-slate-200 bg-white shadow-panel">
        <div className="grid gap-3 border-b border-slate-200 px-5 py-4 lg:grid-cols-[150px_150px_minmax(170px,1fr)_auto]">
          <select
            className="h-10 rounded-md border border-slate-200 bg-white px-3 text-sm font-semibold text-ink outline-none"
            value={filters.process_step}
            onChange={(event) => setFilters((current) => ({ ...current, process_step: event.target.value }))}
          >
            <option value="">All steps</option>
            {STEP_OPTIONS.map((step) => (
              <option key={step} value={step}>{step}</option>
            ))}
          </select>
          <label className="flex h-10 items-center gap-2 rounded-md border border-slate-200 px-3 text-sm text-slate-500">
            <Hash size={16} />
            <input
              className="min-w-0 flex-1 outline-none"
              inputMode="numeric"
              placeholder="History ID"
              value={filters.history_id}
              onChange={(event) => setFilters((current) => ({ ...current, history_id: event.target.value }))}
            />
          </label>
          <label className="flex h-10 items-center gap-2 rounded-md border border-slate-200 px-3 text-sm text-slate-500">
            <Search size={16} />
            <input
              className="min-w-0 flex-1 outline-none"
              placeholder="Camera type"
              value={filters.camera_type}
              onChange={(event) => setFilters((current) => ({ ...current, camera_type: event.target.value }))}
            />
          </label>
          <button
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-slate-200 px-4 text-sm font-bold text-ink disabled:opacity-60"
            onClick={loadVisionAlign}
            type="button"
            disabled={loading}
          >
            Apply
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Align ID</th>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Step</th>
                <th className="px-4 py-3">Camera</th>
                <th className="px-4 py-3">History</th>
                <th className="px-4 py-3">Offset X</th>
                <th className="px-4 py-3">Offset Y</th>
                <th className="px-4 py-3">Theta</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr className="border-t border-slate-100" key={item.align_id}>
                  <td className="px-4 py-3 font-bold">{item.align_id}</td>
                  <td className="px-4 py-3">{formatPreciseDate(item.created_at)}</td>
                  <td className="px-4 py-3"><StatusBadge value={item.process_step} /></td>
                  <td className="px-4 py-3 font-mono text-xs">{item.camera_type}</td>
                  <td className="px-4 py-3">{item.history_id}</td>
                  <td className="px-4 py-3 font-mono text-xs">{formatNumber(item.offset_x, 4)}</td>
                  <td className="px-4 py-3 font-mono text-xs">{formatNumber(item.offset_y, 4)}</td>
                  <td className="px-4 py-3 font-mono text-xs">{formatNumber(item.offset_theta, 4)}</td>
                </tr>
              ))}
              {!items.length ? (
                <tr>
                  <td className="px-4 py-10 text-center text-sm font-semibold text-slate-500" colSpan={8}>
                    No vision align rows
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
