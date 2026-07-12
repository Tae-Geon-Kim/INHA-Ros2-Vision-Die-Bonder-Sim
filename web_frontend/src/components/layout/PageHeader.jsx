import { useEffect, useState } from "react";
import { CirclePause, LoaderCircle } from "lucide-react";

import { systemApi } from "../../api/api.js";


export function ServerStatus({ className = "" }) {
  const [serverOnline, setServerOnline] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let requestInFlight = false;
    let activeController = null;

    const checkServer = async () => {
      if (requestInFlight) return;
      requestInFlight = true;
      activeController = new AbortController();
      const timeout = window.setTimeout(() => activeController.abort(), 1500);
      try {
        const response = await systemApi.getHealth(activeController.signal);
        if (!cancelled) setServerOnline(response?.status === "ok");
      } catch {
        if (!cancelled) setServerOnline(false);
      } finally {
        window.clearTimeout(timeout);
        requestInFlight = false;
      }
    };

    checkServer();
    const timer = window.setInterval(checkServer, 2000);
    return () => {
      cancelled = true;
      activeController?.abort();
      window.clearInterval(timer);
    };
  }, []);

  return (
    <div
      aria-live="polite"
      className={`inline-flex h-9 w-[220px] items-center justify-center gap-2 rounded-md border text-sm font-black ${
        serverOnline
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border-slate-300 bg-slate-100 text-slate-600"
      } ${className}`}
      role="status"
    >
      {serverOnline ? (
        <LoaderCircle aria-hidden="true" className="animate-spin" size={18} />
      ) : (
        <CirclePause aria-hidden="true" size={18} />
      )}
      {serverOnline ? "Server Processing" : "Server Stoped"}
    </div>
  );
}


export default function PageHeader({ eyebrow, title, description, actions }) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="text-xs font-black uppercase tracking-[0.22em] text-signal">{eyebrow}</p>
        <h1 className="mt-2 text-3xl font-black text-ink">{title}</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">{description}</p>
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </header>
  );
}
