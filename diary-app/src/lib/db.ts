import Database from "better-sqlite3";
import fs from "fs";
import path from "path";

declare global {
  var __diaryDb: Database.Database | undefined;
}

function getDb(): Database.Database {
  if (globalThis.__diaryDb) {
    return globalThis.__diaryDb;
  }

  const dataDir = process.env.DIARY_DB_DIR ?? path.join(process.cwd(), "data");
  if (!fs.existsSync(/* turbopackIgnore: true */ dataDir)) {
    fs.mkdirSync(dataDir, { recursive: true });
  }

  const instance = new Database(path.join(dataDir, "diary.db"));
  instance.pragma("journal_mode = WAL");
  instance.exec(`
    CREATE TABLE IF NOT EXISTS diary_entries (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      date TEXT NOT NULL UNIQUE,
      content_ja TEXT NOT NULL,
      content_en TEXT,
      updated_at TEXT NOT NULL
    );
  `);

  globalThis.__diaryDb = instance;
  return instance;
}

export interface DiaryEntry {
  id: number;
  date: string;
  content_ja: string;
  content_en: string | null;
  updated_at: string;
}

export function getEntry(date: string): DiaryEntry | undefined {
  return getDb()
    .prepare("SELECT * FROM diary_entries WHERE date = ?")
    .get(date) as DiaryEntry | undefined;
}

export function upsertEntry(date: string, contentJa: string): DiaryEntry {
  const now = new Date().toISOString();
  getDb()
    .prepare(
      `INSERT INTO diary_entries (date, content_ja, updated_at)
       VALUES (@date, @content_ja, @updated_at)
       ON CONFLICT(date) DO UPDATE SET content_ja = @content_ja, updated_at = @updated_at`
    )
    .run({ date, content_ja: contentJa, updated_at: now });
  return getEntry(date)!;
}

export function saveTranslation(
  date: string,
  contentEn: string
): DiaryEntry | undefined {
  const now = new Date().toISOString();
  getDb()
    .prepare(
      "UPDATE diary_entries SET content_en = ?, updated_at = ? WHERE date = ?"
    )
    .run(contentEn, now, date);
  return getEntry(date);
}

export function listEntryDatesInRange(from: string, to: string): string[] {
  const rows = getDb()
    .prepare(
      "SELECT date FROM diary_entries WHERE date BETWEEN ? AND ? ORDER BY date"
    )
    .all(from, to) as { date: string }[];
  return rows.map((r) => r.date);
}

function shiftDateKey(dateKey: string, deltaDays: number): string {
  const [y, m, d] = dateKey.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  date.setDate(date.getDate() + deltaDays);
  const yyyy = date.getFullYear();
  const mm = (date.getMonth() + 1).toString().padStart(2, "0");
  const dd = date.getDate().toString().padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export function computeStreak(todayKey: string): number {
  const rows = getDb()
    .prepare("SELECT date FROM diary_entries")
    .all() as { date: string }[];
  const dateSet = new Set(rows.map((r) => r.date));
  if (dateSet.size === 0) return 0;

  let cursor = dateSet.has(todayKey) ? todayKey : shiftDateKey(todayKey, -1);
  let streak = 0;
  while (dateSet.has(cursor)) {
    streak += 1;
    cursor = shiftDateKey(cursor, -1);
  }
  return streak;
}
