import { useCallback, useEffect, useMemo, useState } from "react";
import { ClipboardList, RefreshCw, Search } from "lucide-react";

import MetricCard from "../components/cards/MetricCard.jsx";
import PageHeader from "../components/layout/PageHeader.jsx";
import StatusBadge from "../components/logs/StatusBadge.jsx";
import { robotLogApi } from "../api/api.js";
import { formatDate, formatDuration } from "../utils/format.js";

const STATUS_OPTIONS = ["START", "RUNNING", "DONE", "FAIL", "STOP"];

export default function WorkHistory() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState({ status: "", die_serial_number: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const loadWorkHistory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await robotLogApi.listWorkHistories({
        limit: 100,
        offset: 0,
        status: filters.status,
        die_serial_number: filters.die_serial_number.trim(),
      });
      setItems(response?.data?.items || []);
      setTotal(response?.data?.total || 0);
    } catch (requestError) {
      setError(requestError.message || "작업 이력을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    loadWorkHistory();
  }, [loadWorkHistory]);

  const metrics = useMemo(() => {
    const openStatuses = new Set(["START", "RUNNING"]);
    return {
      total,
      open: items.filter((item) => openStatuses.has(item.status)).length,
      done: items.filter((item) => item.status === "DONE").length,
      fail: items.filter((item) => item.status === "FAIL").length,
    };
  }, [items, total]);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Robot Logs"
        title="Work History"
        description="다이 본딩 작업 시작, 진행, 종료 상태를 최신순으로 추적합니다."
        actions={
          <button
            className="inline-flex h-10 items-center gap-2 rounded-md bg-moss px-4 text-sm font-bold text-white disabled:opacity-60"
            onClick={loadWorkHistory}
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
        <MetricCard label="Total" value={metrics.total} icon={ClipboardList} caption="matching rows" />
        <MetricCard label="Open" value={metrics.open} icon={ClipboardList} tone="signal" caption="START/RUNNING" />
        <MetricCard label="Done" value={metrics.done} icon={ClipboardList} tone="signal" caption="completed" />
        <MetricCard label="Fail" value={metrics.fail} icon={ClipboardList} tone="ember" caption="failed" />
      </section>

      <section className="rounded-lg border border-slate-200 bg-white shadow-panel">
        <div className="grid gap-3 border-b border-slate-200 px-5 py-4 md:grid-cols-[160px_minmax(220px,1fr)_auto]">
          <select
            className="h-10 rounded-md border border-slate-200 bg-white px-3 text-sm font-semibold text-ink outline-none"
            value={filters.status}
            onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}
          >
            <option value="">All status</option>
            {STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>{status}</option>
            ))}
          </select>
          <label className="flex h-10 items-center gap-2 rounded-md border border-slate-200 px-3 text-sm text-slate-500">
            <Search size={16} />
            <input
              className="min-w-0 flex-1 outline-none"
              placeholder="Die serial"
              value={filters.die_serial_number}
              onChange={(event) => setFilters((current) => ({ ...current, die_serial_number: event.target.value }))}
            />
          </label>
          <button
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-slate-200 px-4 text-sm font-bold text-ink disabled:opacity-60"
            onClick={loadWorkHistory}
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
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3">Die Serial</th>
                <th className="px-4 py-3">DRAM Dies</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Start</th>
                <th className="px-4 py-3">End</th>
                <th className="px-4 py-3">Duration</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr className="border-t border-slate-100" key={item.history_id}>
                  <td className="px-4 py-3 font-bold">{item.history_id}</td>
                  <td className="px-4 py-3">{item.die_serial_number}</td>
                  <td className="px-4 py-3 tabular-nums">{item.stack_count}</td>
                  <td className="px-4 py-3"><StatusBadge value={item.status} /></td>
                  <td className="px-4 py-3">{formatDate(item.start_time)}</td>
                  <td className="px-4 py-3">{formatDate(item.end_time)}</td>
                  <td className="px-4 py-3">{formatDuration(item.start_time, item.end_time)}</td>
                </tr>
              ))}
              {!items.length ? (
                <tr>
                  <td className="px-4 py-10 text-center text-sm font-semibold text-slate-500" colSpan={7}>
                    No work history rows
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
