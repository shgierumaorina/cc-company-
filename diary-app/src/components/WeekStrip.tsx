const WEEKDAYS_JA = ["日", "月", "火", "水", "木", "金", "土"];

interface WeekStripProps {
  weekDates: string[];
  markedDates: Set<string>;
  selectedDate: string;
  todayKey: string;
  onSelectDate: (date: string) => void;
}

export default function WeekStrip({
  weekDates,
  markedDates,
  selectedDate,
  todayKey,
  onSelectDate,
}: WeekStripProps) {
  return (
    <div className="week-strip">
      {weekDates.map((dateKey, i) => {
        const day = Number(dateKey.split("-")[2]);
        const hasEntry = markedDates.has(dateKey);
        const isSelected = dateKey === selectedDate;
        const isToday = dateKey === todayKey;
        return (
          <button
            type="button"
            key={dateKey}
            className={[
              "week-day",
              isSelected && "week-day--selected",
              isToday && "week-day--today",
            ]
              .filter(Boolean)
              .join(" ")}
            onClick={() => onSelectDate(dateKey)}
          >
            <span className="week-day-label">{WEEKDAYS_JA[i]}</span>
            <span className="week-day-num">{day}</span>
            <span className="week-day-flame">{hasEntry ? "🔥" : ""}</span>
          </button>
        );
      })}
    </div>
  );
}
