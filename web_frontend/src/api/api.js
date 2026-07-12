const DEFAULT_API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export function getStoredApiBase() {
  return DEFAULT_API_BASE;
}

function buildUrl(path, apiBase, params = {}) {
  const url = new URL(path, apiBase);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  });
  return url;
}

export async function request(path, options = {}) {
  const apiBase = options.apiBase || getStoredApiBase();
  const response = await fetch(buildUrl(path, apiBase, options.params), {
    method: options.method || "GET",
    credentials: "include",
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(payload?.detail || payload?.message || response.statusText);
  }

  return payload;
}

function unwrapItems(response) {
  return response?.data?.items || [];
}

export const robotLogApi = {
  async getDashboardData(apiBase) {
    const [work, errors, align] = await Promise.all([
      request("/robot-logs/work-history", {
        apiBase,
        params: { limit: 200, offset: 0 },
      }),
      request("/robot-logs/errors", {
        apiBase,
        params: { limit: 200, offset: 0 },
      }),
      request("/robot-logs/vision-align", {
        apiBase,
        params: { limit: 200, offset: 0 },
      }),
    ]);

    return {
      work: unwrapItems(work),
      errors: unwrapItems(errors),
      align: unwrapItems(align),
    };
  },

  listWorkHistories(params, apiBase) {
    return request("/robot-logs/work-history", { apiBase, params });
  },

  listErrorLogs(params, apiBase) {
    return request("/robot-logs/errors", { apiBase, params });
  },

  listVisionAlignLogs(params, apiBase) {
    return request("/robot-logs/vision-align", { apiBase, params });
  },
};

export const robotControlApi = {
  startDemo(stackCount = 4) {
    return request("/robot-control/demo/start", {
      method: "POST",
      body: { stack_count: stackCount },
    });
  },

  stopDemo() {
    return request("/robot-control/demo/stop", { method: "POST" });
  },

  getDemoStatus() {
    return request("/robot-control/demo/status");
  },
};

export const systemApi = {
  getHealth(signal) {
    return request("/health", { signal });
  },
};

export const authApi = {
  login(data, apiBase) {
    return request("/users/login", { method: "POST", body: data, apiBase });
  },

  logout(apiBase) {
    return request("/users/logout", { method: "POST", apiBase });
  },
};
