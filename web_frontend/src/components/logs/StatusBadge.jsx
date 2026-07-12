const toneMap = {
  START: "bg-emerald-100 text-emerald-700",
  RUNNING: "bg-emerald-100 text-emerald-700",
  DONE: "bg-sky-100 text-sky-700",
  WARN: "bg-amber-100 text-amber-700",
  INFO: "bg-slate-100 text-slate-600",
  ERROR: "bg-red-100 text-red-700",
  FATAL: "bg-red-100 text-red-700",
  FAIL: "bg-red-100 text-red-700",
  STOP: "bg-red-100 text-red-700",
  PICK: "bg-emerald-100 text-emerald-700",
  PLACE: "bg-sky-100 text-sky-700",
};

export default function StatusBadge({ value }) {
  const tone = toneMap[value] || "bg-slate-100 text-slate-600";
  return (
    <span className={`inline-flex min-w-16 justify-center rounded-full px-2.5 py-1 text-xs font-black ${tone}`}>
      {value || "-"}
    </span>
  );
}
