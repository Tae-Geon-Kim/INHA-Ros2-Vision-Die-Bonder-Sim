import { useEffect, useMemo, useRef, useState } from "react";
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

import { robotLogApi } from "../../api/api.js";
import { formatNumber, formatTimeLabel, timestampOf } from "../../utils/format.js";

const OPEN_WORK_STATUSES = new Set(["START", "RUNNING"]);
const ALIGNMENT_AXES = [
  { key: "x", label: "X" },
  { key: "y", label: "Y" },
  { key: "theta", label: "Theta" },
];

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

export default function ChartCard({ title, description, actions, children }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-panel">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-black text-ink">{title}</h2>
          {description ? <p className="mt-1 text-sm text-slate-500">{description}</p> : null}
        </div>
        {actions ? <div className="min-w-0">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function AlignmentConvergenceChart({ work = [] }) {
  const [selectedHistoryId, setSelectedHistoryId] = useState(null);
  const [alignmentRows, setAlignmentRows] = useState([]);
  const [alignmentError, setAlignmentError] = useState(null);
  const [visibleAxes, setVisibleAxes] = useState({
    x: true,
    y: true,
    theta: true,
  });
  const latestHistoryIdRef = useRef(null);

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

  const chartData = useMemo(
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
    () => symmetricDomain(chartData, ["dx", "dy"], 0.001),
    [chartData],
  );
  const thetaDomain = useMemo(
    () => symmetricDomain(chartData, ["dtheta"], 0.001),
    [chartData],
  );
  const placeCompletionMarkers = useMemo(
    () => (selectedWork?.place_completion_times || [])
      .map((completedAt, index) => ({
        chipIndex: index + 1,
        timestamp: timestampOf(completedAt),
      }))
      .filter((marker) => marker.timestamp > 0),
    [selectedWork],
  );
  const timeDomain = useMemo(() => {
    if (!chartData.length) return [0, 1];
    const timestamps = [
      ...chartData.map((row) => row.timestamp),
      ...placeCompletionMarkers.map((marker) => marker.timestamp),
    ];
    const first = Math.min(...timestamps);
    const last = Math.max(...timestamps);
    const padding = Math.max((last - first) * 0.03, 500);
    return [first - padding, last + padding];
  }, [chartData, placeCompletionMarkers]);

  const selectedAxisCount = Object.values(visibleAxes).filter(Boolean).length;
  const showXyAxis = visibleAxes.x || visibleAxes.y;
  const toggleAxis = (axis) => {
    setVisibleAxes((current) => {
      const enabledCount = Object.values(current).filter(Boolean).length;
      if (current[axis] && enabledCount === 1) return current;
      return { ...current, [axis]: !current[axis] };
    });
  };
  const selectHistory = (historyId) => {
    setSelectedHistoryId(historyId);
    setAlignmentRows([]);
    setAlignmentError(null);
  };

  return (
    <ChartCard
      title="Alignment Error Convergence"
      description="선택한 작업의 비전 측정 x/y/theta 오차 기록입니다."
      actions={(
        <div className="flex max-w-full flex-col items-stretch gap-2 sm:items-end">
          <select
            aria-label="정렬 오차 작업 이력"
            className="h-9 w-full max-w-sm rounded-md border border-slate-200 bg-white px-3 text-xs font-semibold text-ink outline-none focus:border-moss sm:w-80"
            onChange={(event) => selectHistory(Number(event.target.value))}
            value={selectedHistoryId || ""}
          >
            {!work.length ? <option value="">작업 이력 없음</option> : null}
            {work.map((item) => (
              <option key={item.history_id} value={item.history_id}>
                {item.die_serial_number}
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
                  checked={visibleAxes[axis.key]}
                  className="h-4 w-4 accent-moss"
                  disabled={visibleAxes[axis.key] && selectedAxisCount === 1}
                  onChange={() => toggleAxis(axis.key)}
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
      {!chartData.length ? (
        <div className="grid h-80 place-items-center text-sm font-semibold text-slate-500">
          선택한 작업의 정렬 오차 기록이 없습니다.
        </div>
      ) : (
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="timestamp"
                domain={timeDomain}
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
              {visibleAxes.theta ? (
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
              {placeCompletionMarkers.map((marker) => (
                <ReferenceLine
                  key={marker.chipIndex}
                  label={{
                    value: `Die ${marker.chipIndex} Place`,
                    position: "insideTopRight",
                    fill: "#a83b3b",
                    fontSize: 11,
                  }}
                  stroke="#a83b3b"
                  strokeDasharray="4 4"
                  strokeWidth={2}
                  x={marker.timestamp}
                  yAxisId={showXyAxis ? "xy" : "theta"}
                />
              ))}
              {visibleAxes.x ? (
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
              {visibleAxes.y ? (
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
              {visibleAxes.theta ? (
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
  );
}
