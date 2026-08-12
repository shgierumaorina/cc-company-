"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import WeekStrip from "@/components/WeekStrip";
import MonthGrid from "@/components/MonthGrid";
import StreakBadge from "@/components/StreakBadge";
import DiaryPanel from "@/components/DiaryPanel";
import type { DiaryEntry } from "@/lib/db";
import type { Category } from "@/lib/categories";
import { daysInMonth, getWeekDates, monthKey, pad2, toDateKey } from "@/lib/date";

type ViewMode = "week" | "month";

const EMPTY_ENTRIES: Record<Category, DiaryEntry | null> = {
  free: null,
  work: null,
  study: null,
};

export default function Home() {
  const todayKey = useMemo(() => {
    const now = new Date();
    return toDateKey(now.getFullYear(), now.getMonth() + 1, now.getDate());
  }, []);
  const weekDates = useMemo(() => getWeekDates(todayKey), [todayKey]);

  const [year, setYear] = useState(() => Number(todayKey.split("-")[0]));
  const [month, setMonth] = useState(() => Number(todayKey.split("-")[1]));
  const [viewMode, setViewMode] = useState<ViewMode>("week");
  const [selectedDate, setSelectedDate] = useState(todayKey);

  const [markedDates, setMarkedDates] = useState<Set<string>>(new Set());
  const [entries, setEntries] = useState<Record<Category, DiaryEntry | null>>(EMPTY_ENTRIES);
  const [streak, setStreak] = useState(0);

  const [loadingEntry, setLoadingEntry] = useState(true);
  const [saving, setSaving] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [savingTranslation, setSavingTranslation] = useState(false);
  const [savingMemo, setSavingMemo] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStreak = useCallback(() => {
    fetch(`/api/streak?today=${todayKey}`)
      .then((res) => res.json())
      .then((data: { streak: number }) => setStreak(data.streak))
      .catch(() => {});
  }, [todayKey]);

  useEffect(() => {
    fetchStreak();
  }, [fetchStreak]);

  useEffect(() => {
    let cancelled = false;
    const range =
      viewMode === "week"
        ? { from: weekDates[0], to: weekDates[6] }
        : {
            from: `${year}-${pad2(month)}-01`,
            to: `${year}-${pad2(month)}-${pad2(daysInMonth(year, month))}`,
          };
    fetch(`/api/entries?from=${range.from}&to=${range.to}`)
      .then((res) => res.json())
      .then((data: { dates: string[] }) => {
        if (!cancelled) setMarkedDates(new Set(data.dates));
      })
      .catch(() => {
        if (!cancelled) setError("カレンダーの読み込みに失敗しました");
      });
    return () => {
      cancelled = true;
    };
  }, [viewMode, year, month, weekDates]);

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/entries/${selectedDate}`)
      .then(async (res) => {
        if (!res.ok) throw new Error("読み込みに失敗しました");
        return (await res.json()) as { entries: DiaryEntry[] };
      })
      .then((data) => {
        if (cancelled) return;
        const byCategory: Record<Category, DiaryEntry | null> = { ...EMPTY_ENTRIES };
        for (const item of data.entries) {
          byCategory[item.category] = item;
        }
        setEntries(byCategory);
      })
      .catch(() => {
        if (!cancelled) setError("日記の読み込みに失敗しました");
      })
      .finally(() => {
        if (!cancelled) setLoadingEntry(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDate]);

  const handleSelectDate = (date: string) => {
    if (date !== selectedDate) {
      setSelectedDate(date);
      setLoadingEntry(true);
      setError(null);
    }
  };

  const handleMonthChange = (delta: number) => {
    let newMonth = month + delta;
    let newYear = year;
    if (newMonth > 12) {
      newMonth = 1;
      newYear += 1;
    } else if (newMonth < 1) {
      newMonth = 12;
      newYear -= 1;
    }
    setYear(newYear);
    setMonth(newMonth);
  };

  const handleToggleView = () => {
    setViewMode((prev) => (prev === "week" ? "month" : "week"));
  };

  const handleSave = useCallback(
    async (category: Category, contentJa: string) => {
      setSaving(true);
      setError(null);
      try {
        const res = await fetch(`/api/entries/${selectedDate}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category, content_ja: contentJa }),
        });
        if (!res.ok) throw new Error("保存に失敗しました");
        const data = (await res.json()) as DiaryEntry;
        setEntries((prev) => ({ ...prev, [category]: data }));
        setMarkedDates((prev) => new Set(prev).add(selectedDate));
        fetchStreak();
      } catch {
        setError("保存に失敗しました");
      } finally {
        setSaving(false);
      }
    },
    [selectedDate, fetchStreak]
  );

  const handleTranslate = useCallback(
    async (category: Category) => {
      setTranslating(true);
      setError(null);
      try {
        const res = await fetch(`/api/entries/${selectedDate}/translate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data?.error ?? "翻訳に失敗しました");
        setEntries((prev) => ({ ...prev, [category]: data as DiaryEntry }));
      } catch (err) {
        setError(err instanceof Error ? err.message : "翻訳に失敗しました");
      } finally {
        setTranslating(false);
      }
    },
    [selectedDate]
  );

  const handleSaveTranslation = useCallback(
    async (category: Category, contentEn: string) => {
      setSavingTranslation(true);
      setError(null);
      try {
        const res = await fetch(`/api/entries/${selectedDate}/translation`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category, content_en: contentEn }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data?.error ?? "翻訳の保存に失敗しました");
        setEntries((prev) => ({ ...prev, [category]: data as DiaryEntry }));
      } catch (err) {
        setError(err instanceof Error ? err.message : "翻訳の保存に失敗しました");
      } finally {
        setSavingTranslation(false);
      }
    },
    [selectedDate]
  );

  const handleSaveMemo = useCallback(
    async (category: Category, memo: string) => {
      setSavingMemo(true);
      setError(null);
      try {
        const res = await fetch(`/api/entries/${selectedDate}/memo`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category, memo }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data?.error ?? "メモの保存に失敗しました");
        setEntries((prev) => ({ ...prev, [category]: data as DiaryEntry }));
      } catch (err) {
        setError(err instanceof Error ? err.message : "メモの保存に失敗しました");
      } finally {
        setSavingMemo(false);
      }
    },
    [selectedDate]
  );

  return (
    <main className="app-shell">
      <header className="app-header">
        <h1 className="app-title">日記</h1>
        <StreakBadge streak={streak} />
      </header>
      <div className="app-layout">
        <div className="calendar-panel">
          <div className="calendar-panel-toolbar">
            <span className="calendar-panel-caption">
              {viewMode === "week" ? "今週" : `${monthKey(year, month)}`}
            </span>
            <button
              type="button"
              className="view-toggle"
              onClick={handleToggleView}
              aria-label={
                viewMode === "week" ? "月表示に切り替え" : "週表示に切り替え"
              }
              title={viewMode === "week" ? "月表示に切り替え" : "週表示に戻る"}
            >
              {viewMode === "week" ? "📅" : "📆"}
            </button>
          </div>
          {viewMode === "week" ? (
            <WeekStrip
              weekDates={weekDates}
              markedDates={markedDates}
              selectedDate={selectedDate}
              todayKey={todayKey}
              onSelectDate={handleSelectDate}
            />
          ) : (
            <MonthGrid
              year={year}
              month={month}
              markedDates={markedDates}
              selectedDate={selectedDate}
              todayKey={todayKey}
              onSelectDate={handleSelectDate}
              onMonthChange={handleMonthChange}
            />
          )}
        </div>
        <DiaryPanel
          selectedDate={selectedDate}
          entries={entries}
          loading={loadingEntry}
          saving={saving}
          translating={translating}
          savingTranslation={savingTranslation}
          savingMemo={savingMemo}
          error={error}
          onSave={handleSave}
          onTranslate={handleTranslate}
          onSaveTranslation={handleSaveTranslation}
          onSaveMemo={handleSaveMemo}
        />
      </div>
    </main>
  );
}
