import { useEffect } from "react";
import { Layers3, Minus, Plus, X } from "lucide-react";

export const MIN_STACK_COUNT = 4;
export const MAX_STACK_COUNT = 16;
export const DEFAULT_STACK_COUNT = 4;

function StackPreview({ count }) {
  return (
    <div className="relative flex min-h-64 items-end justify-center overflow-hidden rounded-2xl border border-emerald-900/10 bg-gradient-to-b from-slate-50 via-emerald-50/50 to-emerald-100/80 px-6 pb-8 pt-6">
      <div className="absolute left-6 top-5">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-moss/70">
          Stack preview
        </p>
        <p className="mt-1 text-sm font-semibold text-slate-600">
          {count} chips selected
        </p>
      </div>

      <div className="relative h-48 w-64" aria-hidden="true">
        <div className="absolute bottom-0 left-1/2 h-4 w-52 -translate-x-1/2 rounded-[50%] bg-emerald-950/15 blur-md" />
        <div className="absolute bottom-2 left-1/2 h-5 w-52 -translate-x-1/2 rounded-md border border-slate-500/30 bg-gradient-to-b from-slate-300 to-slate-500 shadow-lg">
          <div className="mx-auto mt-1 h-1 w-32 rounded-full bg-white/40" />
        </div>

        {Array.from({ length: count }, (_, index) => {
          const isTopChip = index === count - 1;
          const horizontalOffset = index % 2 === 0 ? -2 : 2;

          return (
            <div
              className="absolute left-1/2 h-3.5 w-36 rounded-[4px] border border-emerald-950/35 bg-gradient-to-r from-emerald-700 via-emerald-400 to-emerald-700 shadow-[0_4px_7px_rgba(15,61,42,0.22)] transition-all duration-300 ease-out"
              key={index}
              style={{
                bottom: `${24 + index * 9}px`,
                transform: `translateX(calc(-50% + ${horizontalOffset}px))`,
                zIndex: index + 1,
              }}
            >
              <div className="mx-auto mt-0.5 h-1 w-24 rounded-full bg-emerald-100/50" />
              {isTopChip ? (
                <div className="absolute -right-2 -top-2 h-4 w-4 animate-pulse rounded-full border-2 border-white bg-amber-400 shadow" />
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="absolute bottom-4 right-5 flex items-center gap-2 rounded-full bg-white/85 px-3 py-1.5 text-xs font-bold text-emerald-900 shadow-sm backdrop-blur">
        <Layers3 size={14} />
        {count} layers
      </div>
    </div>
  );
}

export default function StackSetupDialog({
  error,
  loading,
  onChange,
  onClose,
  onStart,
  open,
  stackCount,
}) {
  useEffect(() => {
    if (!open) return undefined;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const closeOnEscape = (event) => {
      if (event.key === "Escape" && !loading) onClose();
    };

    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [loading, onClose, open]);

  if (!open) return null;

  const sliderProgress =
    ((stackCount - MIN_STACK_COUNT) / (MAX_STACK_COUNT - MIN_STACK_COUNT)) * 100;

  const updateCount = (nextCount) => {
    onChange(Math.min(MAX_STACK_COUNT, Math.max(MIN_STACK_COUNT, nextCount)));
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !loading) onClose();
      }}
      role="presentation"
    >
      <section
        aria-describedby="stack-dialog-description"
        aria-labelledby="stack-dialog-title"
        aria-modal="true"
        className="max-h-[calc(100vh-2rem)] w-full max-w-4xl overflow-y-auto rounded-3xl border border-white/60 bg-white shadow-2xl"
        role="dialog"
      >
        <div className="flex items-start justify-between border-b border-slate-100 px-6 py-5 sm:px-8">
          <div>
            <p className="text-xs font-black uppercase tracking-[0.24em] text-moss">
              Vision stack setup
            </p>
            <h2 className="mt-2 text-2xl font-black text-ink" id="stack-dialog-title">
              적층할 칩 개수를 선택하세요
            </h2>
            <p
              className="mt-1 text-sm text-slate-500"
              id="stack-dialog-description"
            >
              4개부터 16개까지 선택할 수 있으며 기본값은 4개입니다.
            </p>
          </div>
          <button
            aria-label="칩 적층 설정 닫기"
            className="rounded-full p-2 text-slate-500 transition hover:bg-slate-100 hover:text-ink disabled:opacity-50"
            disabled={loading}
            onClick={onClose}
            type="button"
          >
            <X size={20} />
          </button>
        </div>

        <div className="grid gap-7 p-6 sm:p-8 lg:grid-cols-[minmax(0,1fr)_minmax(310px,0.8fr)]">
          <StackPreview count={stackCount} />

          <div className="flex flex-col justify-between gap-6">
            <div>
              <div className="flex items-end justify-between">
                <div>
                  <p className="text-sm font-bold text-slate-500">Stack count</p>
                  <p
                    aria-live="polite"
                    className="mt-1 text-5xl font-black tabular-nums text-ink"
                  >
                    {stackCount}
                    <span className="ml-2 text-base font-bold text-slate-400">chips</span>
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    aria-label="칩 개수 줄이기"
                    className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200 text-slate-600 transition hover:border-moss hover:text-moss disabled:cursor-not-allowed disabled:opacity-35"
                    disabled={loading || stackCount <= MIN_STACK_COUNT}
                    onClick={() => updateCount(stackCount - 1)}
                    type="button"
                  >
                    <Minus size={17} />
                  </button>
                  <button
                    aria-label="칩 개수 늘리기"
                    className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200 text-slate-600 transition hover:border-moss hover:text-moss disabled:cursor-not-allowed disabled:opacity-35"
                    disabled={loading || stackCount >= MAX_STACK_COUNT}
                    onClick={() => updateCount(stackCount + 1)}
                    type="button"
                  >
                    <Plus size={17} />
                  </button>
                </div>
              </div>

              <input
                aria-label="적층할 칩 개수"
                aria-valuetext={`${stackCount}개`}
                autoFocus
                className="stack-range mt-8 h-2 w-full cursor-pointer appearance-none rounded-full bg-slate-200 disabled:cursor-not-allowed"
                disabled={loading}
                max={MAX_STACK_COUNT}
                min={MIN_STACK_COUNT}
                onChange={(event) => updateCount(Number(event.target.value))}
                style={{
                  background: `linear-gradient(to right, #267a4d 0%, #267a4d ${sliderProgress}%, #e2e8f0 ${sliderProgress}%, #e2e8f0 100%)`,
                }}
                type="range"
                value={stackCount}
              />

              <div className="mt-3 flex justify-between text-xs font-bold text-slate-400">
                <span>{MIN_STACK_COUNT}</span>
                <span>10</span>
                <span>{MAX_STACK_COUNT}</span>
              </div>
            </div>

            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs leading-5 text-emerald-900">
              Start를 누르면 선택한 <strong>{stackCount}개</strong>를 기준으로
              Gazebo, joint bridge, 비전 적층 데모가 모두 자동 실행됩니다.
              로컬 환경에 따라 최초 준비에는 수십 초가 걸릴 수 있습니다.
            </div>

            {error ? (
              <div
                aria-live="assertive"
                className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-xs font-semibold leading-5 text-red-700"
                role="alert"
              >
                {error}
              </div>
            ) : null}

            <div className="flex gap-3">
              <button
                className="h-11 flex-1 rounded-xl border border-slate-200 px-4 text-sm font-bold text-slate-600 transition hover:bg-slate-50 disabled:opacity-50"
                disabled={loading}
                onClick={onClose}
                type="button"
              >
                Cancel
              </button>
              <button
                className="inline-flex h-11 flex-[1.4] items-center justify-center gap-2 rounded-xl bg-ink px-5 text-sm font-black text-white shadow-lg shadow-slate-900/15 transition hover:-translate-y-0.5 hover:bg-moss disabled:translate-y-0 disabled:cursor-wait disabled:opacity-60"
                disabled={loading}
                onClick={onStart}
                type="button"
              >
                <Layers3 size={17} />
                {loading ? "환경 시작 중..." : "Start"}
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
