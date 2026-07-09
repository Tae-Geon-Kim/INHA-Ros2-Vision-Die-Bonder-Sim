const KST_TIME_ZONE = "Asia/Seoul";
const HAS_TIMEZONE = /(?:Z|[+-]\d{2}:?\d{2})$/i;

export function parseKstDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;

  if (typeof value === "string") {
    const trimmed = value.trim();
    const normalized =
      trimmed.includes("T") && !HAS_TIMEZONE.test(trimmed)
        ? `${trimmed}+09:00`
        : trimmed;
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function timestampOf(value) {
  return parseKstDate(value)?.getTime() || 0;
}

export function formatDate(value) {
  const date = parseKstDate(value);
  if (!date) return value || "-";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: KST_TIME_ZONE,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatPreciseDate(value) {
  const date = parseKstDate(value);
  if (!date) return value || "-";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: KST_TIME_ZONE,
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export function formatNumber(value, digits = 3) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return number.toFixed(digits);
}

export function formatDuration(startValue, endValue) {
  if (!startValue || !endValue) return "-";
  const start = timestampOf(startValue);
  const end = timestampOf(endValue);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return "-";

  const totalSeconds = Math.round((end - start) / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

export function formatTimeLabel(value) {
  const date = parseKstDate(value);
  if (!date) return "unknown";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: KST_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatHourBucket(value) {
  const date = parseKstDate(value);
  if (!date) return "unknown";
  const parts = new Intl.DateTimeFormat("ko-KR", {
    timeZone: KST_TIME_ZONE,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const partMap = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${partMap.month}/${partMap.day} ${partMap.hour}:00`;
}
