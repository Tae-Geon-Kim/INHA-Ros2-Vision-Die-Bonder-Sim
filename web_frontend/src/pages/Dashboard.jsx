import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ClipboardList,
  Database,
  Play,
  RefreshCw
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
import { formatDate, formatNumber } from "../utils/format.js";
import { robotControlApi } from "../api/api.js";

const PIE_COLORS = ["#267a4d", "#376d86", "#a46213", "#a83b3b", "#6b7280"];

export default function Dashboard() {
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoMessage, setDemoMessage] = useState(null);
  const [stackDialogOpen, setStackDialogOpen] = useState(false);
  const [stackCount, setStackCount] = useState(DEFAULT_STACK_COUNT);
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
    const refreshTimer = window.setInterval(refreshDashboard, 3000);
    return () => window.clearInterval(refreshTimer);
  }, [refreshDashboard]);

  useEffect(() => {
    if (unauthorized) {
      requireLogin(error || "로그인이 필요합니다.");
    }
  }, [error, requireLogin, unauthorized]);

  const metrics = getMetrics();
  const charts = getCharts();
  const recentWork = useMemo(() => work.slice(0, 8), [work]);
  const latestErrors = useMemo(() => errors.slice(0, 8), [errors]);

  const startGazeboDemo = async () => {
    setDemoLoading(true);
    setDemoMessage(null);
    try {
      const response = await robotControlApi.startDemo(stackCount);
      setDemoMessage(response?.message || `${stackCount}-chip stack demo started.`);
      setStackDialogOpen(false);
      await refreshDashboard();
    } catch (requestError) {
      setDemoMessage(requestError.message || "Vision stack demo start failed.");
    } finally {
      setDemoLoading(false);
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
              onClick={() => setStackDialogOpen(true)}
              type="button"
              disabled={demoLoading}
            >
              <Play size={16} />
              Start
            </button>
            <button
              className="inline-flex h-10 items-center gap-2 rounded-md bg-moss px-4 text-sm font-bold text-white disabled:opacity-60"
              onClick={refreshDashboard}
              type="button"
              disabled={loading}
            >
              <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
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
        loading={demoLoading}
        onChange={setStackCount}
        onClose={() => setStackDialogOpen(false)}
        onStart={startGazeboDemo}
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

      <ChartCard title="Alignment Error Convergence" description="Gazebo 작업 중 기록된 x/y/theta 오차가 0 기준선으로 수렴하는 흐름입니다.">
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={charts.alignmentConvergence}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="time" tick={{ fontSize: 12 }} minTickGap={18} />
              <YAxis
                domain={charts.alignmentDomain}
                tickFormatter={(value) => formatNumber(value, 2)}
                width={64}
              />
              <Tooltip
                formatter={(value, name) => [formatNumber(value, 4), name]}
                labelFormatter={(label) => `time ${label}`}
              />
              <Legend />
              <ReferenceLine y={0} stroke="#202822" strokeDasharray="5 5" />
              <Line type="monotone" dataKey="dx" name="x error" stroke="#267a4d" strokeWidth={3} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="dy" name="y error" stroke="#376d86" strokeWidth={3} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="dtheta" name="theta error" stroke="#a46213" strokeWidth={3} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
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
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3">ID</th>
                  <th className="px-4 py-3">Die Serial</th>
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
