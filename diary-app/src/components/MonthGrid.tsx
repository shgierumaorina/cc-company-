import { toDateKey } from "@/lib/date";

const WEEKDAYS_JA = ["日", "月", "火", "水", "木", "金", "土"];

interface MonthGridProps {
  year: number;
  month: number; // 1-12
  markedDates: Set<string>;
  selectedDate: string;
  todayKey: string;
  onSelectDate: (date: string) => void;
  onMonthChange: (delta: number) => void;
}

export default function MonthGrid({
  year,
  month,
  markedDates,
  selectedDate,
  todayKey,
  onSelectDate,
  onMonthChange,
}: MonthGridProps) {
  const firstDay = new Date(year, month - 1, 1).getDay();
  const daysInMonth = new Date(year, month, 0).getDate();

  const cells: (number | null)[] = [
    ...Array(firstDay).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  while (cells.length % 7 !== 0) cells.push(null);

  return (
    <div className="month-grid">
      <div className="month-grid-header">
        <button
          type="button"
          className="month-nav"
          onClick={() => onMonthChange(-1)}
          aria-label="前の月"
        >
          ‹
        </button>
        <h2 className="month-grid-title">
          {year}年 {month}月
        </h2>
        <button
          type="button"
          className="month-nav"
          onClick={() => onMonthChange(1)}
          aria-label="次の月"
        >
          ›
        </button>
      </div>

      <div className="month-grid-cells month-grid-weekdays">
        {WEEKDAYS_JA.map((w) => (
          <div key={w} className="month-weekday">
            {w}
          </div>
        ))}
      </div>

      <div className="month-grid-cells">
        {cells.map((day, idx) => {
          if (day === null) {
            return (
              <div key={`blank-${idx}`} className="month-cell month-cell--empty" />
            );
          }
          const dateKey = toDateKey(year, month, day);
          const hasEntry = markedDates.has(dateKey);
          const isSelected = dateKey === selectedDate;
          const isToday = dateKey === todayKey;
          return (
            <button
              type="button"
              key={dateKey}
              className={[
                "month-cell",
                isSelected && "month-cell--selected",
                isToday && "month-cell--today",
              ]
                .filter(Boolean)
                .join(" ")}
              onClick={() => onSelectDate(dateKey)}
            >
              <span className="month-daynum">{day}</span>
              {hasEntry && <span className="month-flame">🔥</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}
