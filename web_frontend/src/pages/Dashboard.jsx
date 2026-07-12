import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ClipboardList,
  Database,
  Play,
  RefreshCw,
  Square,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import MetricCard from "../components/cards/MetricCard.jsx";
import ChartCard from "../components/charts/ChartCard.jsx";
import StackSetupDialog, {
  DEFAULT_STACK_COUNT,
} from "../components/controls/StackSetupDialog.jsx";
import PageHeader from "../components/layout/PageHeader.jsx";
import StatusBadge from "../components/logs/StatusBadge.jsx";
import { useAuthStore } from "../state/authStore.js";
import { useRobotLogStore } from "../state/store.js";
import {
  formatDate,
  formatNumber,
  formatTimeLabel,
  timestampOf,
} from "../utils/format.js";
import { robotControlApi, robotLogApi } from "../api/api.js";

const PIE_COLORS = ["#267a4d", "#376d86", "#a46213", "#a83b3b", "#6b7280"];
const OPEN_WORK_STATUSES = new Set(["START", "RUNNING"]);
const ALIGNMENT_AXES = [
  { key: "x", label: "X" },
  { key: "y", label: "Y" },
  { key: "theta", label: "Theta" },
];

function workHistoryLabel(item) {
  const timestamp = String(item.start_time || "-").replace("T", "_").slice(0, 19);
  return `${item.die_serial_number}_${item.stack_count ?? 4}HBM_${timestamp}`;
}

function symmetricDomain(rows, keys, minimum) {
  const maximum = rows.reduce(
    (current, row) => Math.max(
      current,
      ...keys.map((key) => Math.abs(Number(row[key]) || 0)),
    ),
    0,
  );
  const padded = Math.max(maximum * 1.15, minimum);
  return [-padded, padded];
}

export default function Dashboard() {
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoStopping, setDemoStopping] = useState(false);
  const [demoMessage, setDemoMessage] = useState(null);
  const [demoError, setDemoError] = useState(null);
  const [demoStatus, setDemoStatus] = useState(null);
  const [stackDialogOpen, setStackDialogOpen] = useState(false);
  const [stackCount, setStackCount] = useState(DEFAULT_STACK_COUNT);
  const [selectedHistoryId, setSelectedHistoryId] = useState(null);
  const [alignmentRows, setAlignmentRows] = useState([]);
  const [alignmentError, setAlignmentError] = useState(null);
  const [visibleAlignmentAxes, setVisibleAlignmentAxes] = useState({
    x: true,
    y: true,
    theta: true,
  });
  const latestHistoryIdRef = useRef(null);
  const {
    refreshDashboard,
    getMetrics,
    getCharts,
    work,
    errors,
    loading,
    error,
    unauthorized,
    lastUpdated,
  } = useRobotLogStore();
  const { requireLogin } = useAuthStore();

  useEffect(() => {
    refreshDashboard();
    const refreshTimer = window.setInterval(
      () => refreshDashboard({ background: true }),
      1000,
    );
    return () => window.clearInterval(refreshTimer);
  }, [refreshDashboard]);

  useEffect(() => {
    let cancelled = false;

    const refreshDemoStatus = async () => {
      try {
        const response = await robotControlApi.getDemoStatus();
        if (!cancelled) setDemoStatus(response?.data || null);
      } catch {
        // The log dashboard can still be used while the simulator is offline.
      }
    };

    refreshDemoStatus();
    const statusTimer = window.setInterval(refreshDemoStatus, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(statusTimer);
    };
  }, []);

  useEffect(() => {
    if (unauthorized) {
      requireLogin(error || "로그인이 필요합니다.");
    }
  }, [error, requireLogin, unauthorized]);

  const selectedWork = useMemo(
    () => work.find(
      (item) => Number(item.history_id) === selectedHistoryId,
    ) || null,
    [selectedHistoryId, work],
  );
  const selectedWorkStatus = selectedWork?.status || null;

  useEffect(() => {
    const latestWork = work[0];
    if (!latestWork) return;

    const latestHistoryId = Number(latestWork.history_id);
    if (latestHistoryIdRef.current === latestHistoryId) return;

    latestHistoryIdRef.current = latestHistoryId;
    setSelectedHistoryId(latestHistoryId);
    setAlignmentRows([]);
    setAlignmentError(null);
  }, [work]);

  useEffect(() => {
    if (!selectedHistoryId) {
      setAlignmentRows([]);
      return undefined;
    }

    let cancelled = false;
    let requestInFlight = false;
    const loadAlignmentHistory = async () => {
      if (requestInFlight) return;
      requestInFlight = true;
      try {
        const response = await robotLogApi.listVisionAlignLogs({
          history_id: selectedHistoryId,
          limit: 2000,
          offset: 0,
        });
        if (cancelled) return;
        setAlignmentRows(response?.data?.items || []);
        setAlignmentError(null);
      } catch (requestError) {
        if (cancelled) return;
        setAlignmentError(
          requestError.message || "정렬 오차 기록을 불러오지 못했습니다.",
        );
      } finally {
        requestInFlight = false;
      }
    };

    loadAlignmentHistory();
    const shouldPoll = !selectedWorkStatus
      || OPEN_WORK_STATUSES.has(selectedWorkStatus);
    const alignmentTimer = shouldPoll
      ? window.setInterval(loadAlignmentHistory, 1000)
      : null;
    return () => {
      cancelled = true;
      if (alignmentTimer) window.clearInterval(alignmentTimer);
    };
  }, [selectedHistoryId, selectedWorkStatus]);

  const metrics = getMetrics();
  const charts = getCharts();
  const recentWork = useMemo(() => work.slice(0, 8), [work]);
  const latestErrors = useMemo(() => errors.slice(0, 8), [errors]);
  const alignmentChartData = useMemo(
    () => [...alignmentRows]
      .sort((left, right) => {
        const timeDifference = timestampOf(left.created_at)
          - timestampOf(right.created_at);
        if (timeDifference !== 0) return timeDifference;
        return (left.align_id || 0) - (right.align_id || 0);
      })
      .map((item) => ({
        timestamp: timestampOf(item.created_at),
        dx: Number(item.offset_x || 0),
        dy: Number(item.offset_y || 0),
        dtheta: Number(item.offset_theta || 0),
        camera_type: item.camera_type,
        process_step: item.process_step,
      })),
    [alignmentRows],
  );
  const xyDomain = useMemo(
    () => symmetricDomain(alignmentChartData, ["dx", "dy"], 0.001),
    [alignmentChartData],
  );
  const thetaDomain = useMemo(
    () => symmetricDomain(alignmentChartData, ["dtheta"], 0.001),
    [alignmentChartData],
  );
  const alignmentTimeDomain = useMemo(() => {
    if (!alignmentChartData.length) return [0, 1];
    const first = alignmentChartData[0].timestamp;
    const last = alignmentChartData[alignmentChartData.length - 1].timestamp;
    return first === last ? [first - 1000, last + 1000] : [first, last];
  }, [alignmentChartData]);
  const selectedAxisCount = Object.values(visibleAlignmentAxes)
    .filter(Boolean).length;
  const showXyAxis = visibleAlignmentAxes.x || visibleAlignmentAxes.y;
  const dataStreamActive = Boolean(
    lastUpdated
      && !error
      && Date.now() - timestampOf(lastUpdated) < 2500,
  );

  const toggleAlignmentAxis = (axis) => {
    setVisibleAlignmentAxes((current) => {
      const enabledCount = Object.values(current).filter(Boolean).length;
      if (current[axis] && enabledCount === 1) return current;
      return { ...current, [axis]: !current[axis] };
    });
  };

  const selectAlignmentHistory = (historyId) => {
    setSelectedHistoryId(historyId);
    setAlignmentRows([]);
    setAlignmentError(null);
  };

  const simulatorRunning = Boolean(
    demoStatus?.running
      || demoStatus?.infrastructure_running
      || Object.values(demoStatus?.processes || {}).some(
        (process) => process?.running,
      ),
  );

  const startVisionStackDemo = async () => {
    setDemoLoading(true);
    setDemoMessage(null);
    setDemoError(null);
    try {
      const response = await robotControlApi.startDemo(stackCount);
      setDemoStatus(response?.data || null);
      const historyId = Number(response?.data?.history_id);
      if (Number.isInteger(historyId) && historyId > 0
          && historyId !== selectedHistoryId) {
        latestHistoryIdRef.current = historyId;
        selectAlignmentHistory(historyId);
      }
      setDemoMessage(
        response?.message || `${stackCount}개 칩 적층 시스템을 시작했습니다.`,
      );
      setStackDialogOpen(false);
      await refreshDashboard();
    } catch (requestError) {
      setDemoError(
        requestError.message || "비전 적층 시스템을 시작하지 못했습니다.",
      );
    } finally {
      setDemoLoading(false);
    }
  };

  const stopVisionStackDemo = async () => {
    setDemoStopping(true);
    setDemoMessage(null);
    setDemoError(null);
    try {
      const response = await robotControlApi.stopDemo();
      setDemoStatus(response?.data || null);
      setDemoMessage(response?.message || "비전 적층 시스템을 중지했습니다.");
    } catch (requestError) {
      setDemoMessage(
        requestError.message || "비전 적층 시스템을 중지하지 못했습니다.",
      );
    } finally {
      setDemoStopping(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="INHA ROS2 Vision"
        title="Robot Log Monitoring"
        description="작업 이력, 로봇 에러, 비전 정렬 로그를 한 화면에서 확인하는 React 기반 대시보드입니다."
        actions={
          <div className="flex flex-wrap gap-2">
            <button
              className="inline-flex h-10 items-center gap-2 rounded-md bg-ink px-4 text-sm font-bold text-white disabled:opacity-60"
              onClick={() => {
                setDemoError(null);
                setStackDialogOpen(true);
              }}
              type="button"
              disabled={demoLoading || demoStopping}
            >
              <Play size={16} />
              Start
            </button>
            <button
              className="inline-flex h-10 items-center gap-2 rounded-md border border-red-200 bg-white px-4 text-sm font-bold text-red-700 disabled:cursor-not-allowed disabled:opacity-40"
              onClick={stopVisionStackDemo}
              type="button"
              disabled={!simulatorRunning || demoLoading || demoStopping}
            >
              <Square size={14} fill="currentColor" />
              {demoStopping ? "Stopping..." : "Stop"}
            </button>
            <button
              className="inline-flex h-10 items-center gap-2 rounded-md bg-moss px-4 text-sm font-bold text-white disabled:opacity-60"
              onClick={() => refreshDashboard()}
              type="button"
              disabled={loading}
              aria-label={dataStreamActive ? "데이터 수신 중" : "데이터 수신 대기"}
              title={dataStreamActive ? "데이터 수신 중" : "데이터 수신 대기"}
            >
              <RefreshCw
                size={16}
                className={loading || dataStreamActive ? "animate-spin" : ""}
              />
              Refresh
            </button>
          </div>
        }
      />

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
          {error}
        </div>
      ) : null}

      {demoMessage ? (
        <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-700 shadow-panel">
          {demoMessage}
        </div>
      ) : null}

      <StackSetupDialog
        error={demoError}
        loading={demoLoading}
        onChange={setStackCount}
        onClose={() => {
          setDemoError(null);
          setStackDialogOpen(false);
        }}
        onStart={startVisionStackDemo}
        open={stackDialogOpen}
        stackCount={stackCount}
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <MetricCard label="Work Items" value={metrics.workTotal} icon={ClipboardList} caption="latest 200 rows" />
        <MetricCard label="Open Work" value={metrics.openWork} icon={Activity} tone="signal" caption="START or RUNNING" />
        <MetricCard label="Error Logs" value={metrics.errorTotal} icon={AlertTriangle} tone="ember" caption="all levels" />
        <MetricCard label="Fatal Errors" value={metrics.fatalErrors} icon={AlertTriangle} tone="amber" caption="requires action" />
        <MetricCard label="Align Logs" value={metrics.alignTotal} icon={Database} tone="signal" caption="vision offsets" />
      </section>

      <ChartCard
        title="Alignment Error Convergence"
        description="선택한 작업의 비전 측정 x/y/theta 오차 기록입니다."
        actions={(
          <div className="flex max-w-full flex-col items-stretch gap-2 sm:items-end">
            <select
              aria-label="정렬 오차 작업 이력"
              className="h-9 w-full max-w-sm rounded-md border border-slate-200 bg-white px-3 text-xs font-semibold text-ink outline-none focus:border-moss sm:w-80"
              onChange={(event) => selectAlignmentHistory(Number(event.target.value))}
              value={selectedHistoryId || ""}
            >
              {!work.length ? <option value="">작업 이력 없음</option> : null}
              {work.map((item) => (
                <option key={item.history_id} value={item.history_id}>
                  {workHistoryLabel(item)}
                </option>
              ))}
            </select>
            <div
              aria-label="표시할 정렬 오차"
              className="flex items-center justify-end gap-3"
              role="group"
            >
              {ALIGNMENT_AXES.map((axis) => (
                <label
                  className="inline-flex cursor-pointer items-center gap-1.5 text-xs font-bold text-slate-600"
                  key={axis.key}
                >
                  <input
                    checked={visibleAlignmentAxes[axis.key]}
                    className="h-4 w-4 accent-moss"
                    disabled={
                      visibleAlignmentAxes[axis.key]
                      && selectedAxisCount === 1
                    }
                    onChange={() => toggleAlignmentAxis(axis.key)}
                    type="checkbox"
                  />
                  {axis.label}
                </label>
              ))}
            </div>
          </div>
        )}
      >
        {alignmentError ? (
          <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700">
            {alignmentError}
          </div>
        ) : null}
        {!alignmentChartData.length ? (
          <div className="grid h-80 place-items-center text-sm font-semibold text-slate-500">
            선택한 작업의 정렬 오차 기록이 없습니다.
          </div>
        ) : (
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={alignmentChartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="timestamp"
                  domain={alignmentTimeDomain}
                  minTickGap={18}
                  scale="time"
                  tick={{ fontSize: 12 }}
                  tickFormatter={(value) => formatTimeLabel(Number(value))}
                  type="number"
                />
                {showXyAxis ? (
                  <YAxis
                    domain={xyDomain}
                    label={{ value: "X/Y (mm)", angle: -90, position: "insideLeft" }}
                    tickFormatter={(value) => formatNumber(value, 4)}
                    width={72}
                    yAxisId="xy"
                  />
                ) : null}
                {visibleAlignmentAxes.theta ? (
                  <YAxis
                    domain={thetaDomain}
                    label={{ value: "Theta (deg)", angle: 90, position: "insideRight" }}
                    orientation="right"
                    tickFormatter={(value) => formatNumber(value, 3)}
                    width={72}
                    yAxisId="theta"
                  />
                ) : null}
                <Tooltip
                  formatter={(value, name) => [
                    `${formatNumber(value, name === "Theta" ? 4 : 6)} ${
                      name === "Theta" ? "deg" : "mm"
                    }`,
                    name,
                  ]}
                  labelFormatter={(value) => formatTimeLabel(Number(value))}
                />
                <Legend />
                <ReferenceLine
                  stroke="#202822"
                  strokeDasharray="5 5"
                  y={0}
                  yAxisId={showXyAxis ? "xy" : "theta"}
                />
                {visibleAlignmentAxes.x ? (
                  <Line
                    dataKey="dx"
                    dot={false}
                    isAnimationActive={false}
                    name="X"
                    stroke="#267a4d"
                    strokeWidth={3}
                    type="monotone"
                    yAxisId="xy"
                  />
                ) : null}
                {visibleAlignmentAxes.y ? (
                  <Line
                    dataKey="dy"
                    dot={false}
                    isAnimationActive={false}
                    name="Y"
                    stroke="#376d86"
                    strokeWidth={3}
                    type="monotone"
                    yAxisId="xy"
                  />
                ) : null}
                {visibleAlignmentAxes.theta ? (
                  <Line
                    dataKey="dtheta"
                    dot={false}
                    isAnimationActive={false}
                    name="Theta"
                    stroke="#a46213"
                    strokeWidth={3}
                    type="monotone"
                    yAxisId="theta"
                  />
                ) : null}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </ChartCard>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.55fr)]">
        <ChartCard title="Hourly Log Trend" description="작업 시작, 에러, 비전 정렬 로그를 시간대별로 집계합니다.">
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={charts.timeline}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="time" tick={{ fontSize: 12 }} />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="work" stroke="#267a4d" strokeWidth={3} dot={false} />
                <Line type="monotone" dataKey="errors" stroke="#a83b3b" strokeWidth={3} dot={false} />
                <Line type="monotone" dataKey="align" stroke="#376d86" strokeWidth={3} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <ChartCard title="Work Status" description="작업 상태 분포">
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={charts.statusDistribution}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={62}
                  outerRadius={104}
                  paddingAngle={4}
                >
                  {charts.statusDistribution.map((entry, index) => (
                    <Cell key={entry.name} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <ChartCard title="Error Frequency" description="에러 레벨별 발생 빈도">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={charts.errorFrequency}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="value" fill="#a83b3b" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <ChartCard title="Camera Distribution" description="카메라 타입별 비전 정렬 로그 수">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={charts.cameraDistribution}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="value" fill="#376d86" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white shadow-panel">
          <div className="border-b border-slate-200 px-5 py-4">
            <h2 className="font-black text-ink">Recent Work</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3">ID</th>
                  <th className="px-4 py-3">Die Serial</th>
                  <th className="px-4 py-3">DRAM Dies</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Start</th>
                  <th className="px-4 py-3">End</th>
                </tr>
              </thead>
              <tbody>
                {recentWork.map((item) => (
                  <tr className="border-t border-slate-100" key={item.history_id}>
                    <td className="px-4 py-3 font-bold">{item.history_id}</td>
                    <td className="px-4 py-3">{item.die_serial_number}</td>
                    <td className="px-4 py-3 tabular-nums">{item.stack_count}</td>
                    <td className="px-4 py-3"><StatusBadge value={item.status} /></td>
                    <td className="px-4 py-3">{formatDate(item.start_time)}</td>
                    <td className="px-4 py-3">{formatDate(item.end_time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white shadow-panel">
          <div className="border-b border-slate-200 px-5 py-4">
            <h2 className="font-black text-ink">Latest Errors</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3">Level</th>
                  <th className="px-4 py-3">Code</th>
                  <th className="px-4 py-3">Detail</th>
                </tr>
              </thead>
              <tbody>
                {latestErrors.map((item) => (
                  <tr className="border-t border-slate-100" key={item.log_id}>
                    <td className="px-4 py-3">{formatDate(item.error_time)}</td>
                    <td className="px-4 py-3"><StatusBadge value={item.error_level} /></td>
                    <td className="px-4 py-3 font-mono text-xs">{item.error_code || "-"}</td>
                    <td className="px-4 py-3 text-slate-600">{item.detail || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <p className="text-xs text-slate-500">
        Last updated: {lastUpdated ? formatDate(lastUpdated) : "-"}
      </p>
    </div>
  );
}
