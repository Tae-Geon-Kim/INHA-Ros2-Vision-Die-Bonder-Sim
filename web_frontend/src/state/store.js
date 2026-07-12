import { create } from "zustand";

import { getStoredApiBase, robotLogApi } from "../api/api.js";
import { formatHourBucket } from "../utils/format.js";

let dashboardRefreshPromise = null;

function groupBy(items, keySelector) {
  return items.reduce((acc, item) => {
    const key = keySelector(item);
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
}

function toChartRows(grouped, nameKey = "name", valueKey = "value") {
  return Object.entries(grouped).map(([name, value]) => ({
    [nameKey]: name,
    [valueKey]: value,
  }));
}

function buildTimeline(work, errors, align) {
  const grouped = {};

  work.forEach((item) => {
    const key = formatHourBucket(item.start_time);
    grouped[key] = grouped[key] || { time: key, work: 0, errors: 0, align: 0 };
    grouped[key].work += 1;
  });

  errors.forEach((item) => {
    const key = formatHourBucket(item.error_time);
    grouped[key] = grouped[key] || { time: key, work: 0, errors: 0, align: 0 };
    grouped[key].errors += 1;
  });

  align.forEach((item) => {
    const key = formatHourBucket(item.created_at);
    grouped[key] = grouped[key] || { time: key, work: 0, errors: 0, align: 0 };
    grouped[key].align += 1;
  });

  return Object.values(grouped).sort((a, b) => a.time.localeCompare(b.time));
}

export const useRobotLogStore = create((set, get) => ({
  apiBase: getStoredApiBase(),
  work: [],
  errors: [],
  align: [],
  loading: false,
  error: null,
  unauthorized: false,
  lastUpdated: null,

  async refreshDashboard({ background = false } = {}) {
    if (dashboardRefreshPromise) return dashboardRefreshPromise;

    if (!background) {
      set({ loading: true, error: null, unauthorized: false });
    }

    dashboardRefreshPromise = (async () => {
      try {
        const apiBase = get().apiBase;
        const { work, errors, align } = await robotLogApi.getDashboardData(apiBase);
        set({
          work,
          errors,
          align,
          error: null,
          unauthorized: false,
          lastUpdated: new Date().toISOString(),
        });
      } catch (error) {
        const unauthorized =
          error.message.includes("인증") ||
          error.message.includes("token") ||
          error.message.includes("Token") ||
          error.message.includes("401");
        set({ error: error.message, unauthorized });
      } finally {
        dashboardRefreshPromise = null;
        if (!background) set({ loading: false });
      }
    })();

    return dashboardRefreshPromise;
  },

  getMetrics() {
    const { work, errors, align } = get();
    const openStatuses = new Set(["START", "RUNNING"]);
    return {
      workTotal: work.length,
      openWork: work.filter((item) => openStatuses.has(item.status)).length,
      errorTotal: errors.length,
      fatalErrors: errors.filter((item) => item.error_level === "FATAL").length,
      alignTotal: align.length,
    };
  },

  getCharts() {
    const { work, errors, align } = get();
    return {
      timeline: buildTimeline(work, errors, align),
      errorFrequency: toChartRows(groupBy(errors, (item) => item.error_level || "UNKNOWN")),
      statusDistribution: toChartRows(groupBy(work, (item) => item.status || "UNKNOWN")),
      cameraDistribution: toChartRows(groupBy(align, (item) => item.camera_type || "UNKNOWN")),
    };
  },
}));
