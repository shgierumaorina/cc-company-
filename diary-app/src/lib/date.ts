export function pad2(n: number): string {
  return n.toString().padStart(2, "0");
}

export function toDateKey(year: number, month: number, day: number): string {
  return `${year}-${pad2(month)}-${pad2(day)}`;
}

export function monthKey(year: number, month: number): string {
  return `${year}-${pad2(month)}`;
}

export function daysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

export function getWeekDates(referenceDateKey: string): string[] {
  const [y, m, d] = referenceDateKey.split("-").map(Number);
  const ref = new Date(y, m - 1, d);
  const start = new Date(ref);
  start.setDate(ref.getDate() - ref.getDay());
  return Array.from({ length: 7 }, (_, i) => {
    const dt = new Date(start);
    dt.setDate(start.getDate() + i);
    return toDateKey(dt.getFullYear(), dt.getMonth() + 1, dt.getDate());
  });
}
