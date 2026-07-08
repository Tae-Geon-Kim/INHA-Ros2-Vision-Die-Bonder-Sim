export default function MetricCard({ label, value, icon: Icon, tone = "moss", caption }) {
  const tones = {
    moss: "border-moss bg-emerald-50 text-moss",
    signal: "border-signal bg-sky-50 text-signal",
    ember: "border-ember bg-red-50 text-ember",
    amber: "border-amber-500 bg-amber-50 text-amber-700",
  };

  return (
    <article className="rounded-lg border border-slate-200 bg-white p-5 shadow-panel">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-bold text-slate-500">{label}</span>
        {Icon ? (
          <span className={`grid h-10 w-10 place-items-center rounded-lg border ${tones[tone]}`}>
            <Icon size={18} />
          </span>
        ) : null}
      </div>
      <strong className="mt-4 block text-3xl font-black text-ink">{value}</strong>
      {caption ? <p className="mt-2 text-xs font-medium text-slate-500">{caption}</p> : null}
    </article>
  );
}
