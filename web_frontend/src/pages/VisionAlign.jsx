import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, Hash, Search } from "lucide-react";

import { AlignmentConvergenceChart } from "../components/charts/ChartCard.jsx";
import MetricCard from "../components/cards/MetricCard.jsx";
import PageHeader, { ServerStatus } from "../components/layout/PageHeader.jsx";
import StatusBadge from "../components/logs/StatusBadge.jsx";
import { robotLogApi } from "../api/api.js";
import { formatNumber, formatPreciseDate } from "../utils/format.js";

const STEP_OPTIONS = ["PICK", "PLACE"];

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
  const [work, setWork] = useState([]);
  const [workError, setWorkError] = useState(null);
  const loadInFlight = useRef(false);
  const workLoadInFlight = useRef(false);

  const loadVisionAlign = useCallback(async ({ background = false } = {}) => {
    if (loadInFlight.current) return;
    loadInFlight.current = true;
    if (!background) {
      setLoading(true);
      setError(null);
    }
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
      setError(null);
    } catch (requestError) {
      setError(requestError.message || "비전 정렬 로그를 불러오지 못했습니다.");
    } finally {
      loadInFlight.current = false;
      if (!background) setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    loadVisionAlign();
    const timer = window.setInterval(
      () => loadVisionAlign({ background: true }),
      3000,
    );
    return () => window.clearInterval(timer);
  }, [loadVisionAlign]);

  const loadWorkHistories = useCallback(async () => {
    if (workLoadInFlight.current) return;
    workLoadInFlight.current = true;
    try {
      const response = await robotLogApi.listWorkHistories({
        limit: 200,
        offset: 0,
      });
      setWork(response?.data?.items || []);
      setWorkError(null);
    } catch (requestError) {
      setWorkError(
        requestError.message || "작업 이력을 불러오지 못했습니다.",
      );
    } finally {
      workLoadInFlight.current = false;
    }
  }, []);

  useEffect(() => {
    loadWorkHistories();
    const timer = window.setInterval(loadWorkHistories, 1000);
    return () => window.clearInterval(timer);
  }, [loadWorkHistories]);

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
        actions={<ServerStatus />}
      />

      {error || workError ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
          {error || workError}
        </div>
      ) : null}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Total" value={metrics.total} icon={Activity} caption="matching rows" />
        <MetricCard label="Pick" value={metrics.pick} icon={Activity} tone="signal" caption="pick offsets" />
        <MetricCard label="Place" value={metrics.place} icon={Activity} tone="signal" caption="place offsets" />
        <MetricCard label="Max Abs" value={formatNumber(metrics.maxError, 3)} icon={Activity} tone="ember" caption="x/y/theta" />
      </section>

      <AlignmentConvergenceChart work={work} />

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
            onClick={() => loadVisionAlign()}
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
