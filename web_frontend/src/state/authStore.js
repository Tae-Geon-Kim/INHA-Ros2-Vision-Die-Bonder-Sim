import { create } from "zustand";

import { authApi } from "../api/api.js";

const AUTH_STORAGE_KEY = "robotLogConsoleAuthenticated";

export const useAuthStore = create((set, get) => ({
  isAuthenticated: sessionStorage.getItem(AUTH_STORAGE_KEY) === "true",
  loading: false,
  error: null,

  async login(credentials) {
    set({ loading: true, error: null });
    try {
      await authApi.login(credentials);
      sessionStorage.setItem(AUTH_STORAGE_KEY, "true");
      set({ isAuthenticated: true, loading: false });
      return true;
    } catch (error) {
      set({
        error: error.message || "로그인에 실패했습니다.",
        loading: false,
      });
      return false;
    }
  },

  async logout() {
    try {
      await authApi.logout();
    } finally {
      sessionStorage.removeItem(AUTH_STORAGE_KEY);
      set({ isAuthenticated: false });
      get().clearError();
    }
  },

  requireLogin(message = "다시 로그인해주세요.") {
    sessionStorage.removeItem(AUTH_STORAGE_KEY);
    set({ isAuthenticated: false, error: message });
  },

  clearError() {
    set({ error: null });
  },
}));
