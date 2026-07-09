import { useState } from "react";
import { Lock, LogIn, User } from "lucide-react";

import { useAuthStore } from "../state/authStore.js";

export default function Login() {
  const { login, loading, error, clearError } = useAuthStore();
  const [form, setForm] = useState({ id: "", password: "" });

  const updateField = (event) => {
    clearError();
    setForm((current) => ({
      ...current,
      [event.target.name]: event.target.value,
    }));
  };

  const submit = async (event) => {
    event.preventDefault();
    await login(form);
  };

  return (
    <main className="grid min-h-screen place-items-center bg-field px-4 py-10">
      <section className="w-full max-w-[420px] rounded-lg border border-slate-200 bg-white p-8 shadow-panel">
        <div className="mb-8">
          <span className="grid h-12 w-12 place-items-center rounded-lg bg-emerald-100 text-sm font-black text-emerald-900">
            RV
          </span>
          <p className="mt-6 text-xs font-black uppercase tracking-[0.22em] text-signal">
            INHA ROS2 Vision
          </p>
          <h1 className="mt-2 text-2xl font-black text-ink">Robot Log Console</h1>
        </div>

        <form className="grid gap-4" onSubmit={submit}>
          <label className="grid gap-2 text-sm font-bold text-slate-600">
            ID
            <span className="flex items-center gap-2 rounded-md border border-slate-200 px-3">
              <User size={17} className="text-slate-400" />
              <input
                className="h-11 min-w-0 flex-1 outline-none"
                name="id"
                value={form.id}
                onChange={updateField}
                autoComplete="username"
                required
              />
            </span>
          </label>

          <label className="grid gap-2 text-sm font-bold text-slate-600">
            Password
            <span className="flex items-center gap-2 rounded-md border border-slate-200 px-3">
              <Lock size={17} className="text-slate-400" />
              <input
                className="h-11 min-w-0 flex-1 outline-none"
                name="password"
                type="password"
                value={form.password}
                onChange={updateField}
                autoComplete="current-password"
                required
              />
            </span>
          </label>

          {error ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700">
              {error}
            </div>
          ) : null}

          <button
            className="mt-2 inline-flex h-11 items-center justify-center gap-2 rounded-md bg-ink px-4 text-sm font-black text-white disabled:opacity-60"
            type="submit"
            disabled={loading}
          >
            <LogIn size={17} />
            {loading ? "Signing in" : "Login"}
          </button>
        </form>
      </section>
    </main>
  );
}
