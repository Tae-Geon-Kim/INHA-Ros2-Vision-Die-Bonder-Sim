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
