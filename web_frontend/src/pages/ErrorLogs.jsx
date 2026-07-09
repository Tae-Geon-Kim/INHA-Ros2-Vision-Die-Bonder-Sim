import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Hash, RefreshCw } from "lucide-react";

import MetricCard from "../components/cards/MetricCard.jsx";
import PageHeader from "../components/layout/PageHeader.jsx";
import StatusBadge from "../components/logs/StatusBadge.jsx";
import { robotLogApi } from "../api/api.js";
import { formatPreciseDate } from "../utils/format.js";

const LEVEL_OPTIONS = ["INFO", "WARN", "ERROR", "FATAL"];

export default function ErrorLogs() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState({ error_level: "", history_id: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const loadErrorLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await robotLogApi.listErrorLogs({
        limit: 100,
        offset: 0,
        error_level: filters.error_level,
        history_id: filters.history_id,
      });
      setItems(response?.data?.items || []);
      setTotal(response?.data?.total || 0);
    } catch (requestError) {
      setError(requestError.message || "에러 로그를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    loadErrorLogs();
  }, [loadErrorLogs]);

  const metrics = useMemo(() => ({
    total,
    warn: items.filter((item) => item.error_level === "WARN").length,
    error: items.filter((item) => item.error_level === "ERROR").length,
    fatal: items.filter((item) => item.error_level === "FATAL").length,
  }), [items, total]);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Robot Logs"
        title="Error Logs"
        description="로봇 제어 중 발생한 경고, 에러, 치명 로그를 확인합니다."
        actions={
          <button
            className="inline-flex h-10 items-center gap-2 rounded-md bg-moss px-4 text-sm font-bold text-white disabled:opacity-60"
            onClick={loadErrorLogs}
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
        <MetricCard label="Total" value={metrics.total} icon={AlertTriangle} caption="matching rows" />
        <MetricCard label="Warn" value={metrics.warn} icon={AlertTriangle} tone="amber" caption="warnings" />
        <MetricCard label="Error" value={metrics.error} icon={AlertTriangle} tone="ember" caption="errors" />
        <MetricCard label="Fatal" value={metrics.fatal} icon={AlertTriangle} tone="ember" caption="critical" />
      </section>

      <section className="rounded-lg border border-slate-200 bg-white shadow-panel">
        <div className="grid gap-3 border-b border-slate-200 px-5 py-4 md:grid-cols-[160px_minmax(160px,1fr)_auto]">
          <select
            className="h-10 rounded-md border border-slate-200 bg-white px-3 text-sm font-semibold text-ink outline-none"
            value={filters.error_level}
            onChange={(event) => setFilters((current) => ({ ...current, error_level: event.target.value }))}
          >
            <option value="">All levels</option>
            {LEVEL_OPTIONS.map((level) => (
              <option key={level} value={level}>{level}</option>
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
          <button
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-slate-200 px-4 text-sm font-bold text-ink disabled:opacity-60"
            onClick={loadErrorLogs}
            type="button"
            disabled={loading}
          >
            Apply
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Log ID</th>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Level</th>
                <th className="px-4 py-3">Code</th>
                <th className="px-4 py-3">History</th>
                <th className="px-4 py-3">Detail</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr className="border-t border-slate-100" key={item.log_id}>
                  <td className="px-4 py-3 font-bold">{item.log_id}</td>
                  <td className="px-4 py-3">{formatPreciseDate(item.error_time)}</td>
                  <td className="px-4 py-3"><StatusBadge value={item.error_level} /></td>
                  <td className="px-4 py-3 font-mono text-xs">{item.error_code || "-"}</td>
                  <td className="px-4 py-3">{item.history_id || "-"}</td>
                  <td className="px-4 py-3 text-slate-600">{item.detail || "-"}</td>
                </tr>
              ))}
              {!items.length ? (
                <tr>
                  <td className="px-4 py-10 text-center text-sm font-semibold text-slate-500" colSpan={6}>
                    No error log rows
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
