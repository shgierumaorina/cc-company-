import { createClient, type Client } from "@libsql/client";
import fs from "fs";
import path from "path";

declare global {
  var __diaryDb: Client | undefined;
  var __diaryDbReady: Promise<void> | undefined;
}

async function getDb(): Promise<Client> {
  if (globalThis.__diaryDb) {
    await globalThis.__diaryDbReady;
    return globalThis.__diaryDb;
  }

  let url = process.env.TURSO_DATABASE_URL;
  const authToken = process.env.TURSO_AUTH_TOKEN;

  if (!url) {
    const dataDir = path.join(process.cwd(), "data");
    if (!fs.existsSync(/* turbopackIgnore: true */ dataDir)) {
      fs.mkdirSync(dataDir, { recursive: true });
    }
    url = `file:${path.join(dataDir, "diary.db")}`;
  }

  const client = createClient(
    authToken ? { url, authToken } : { url }
  );

  globalThis.__diaryDb = client;
  globalThis.__diaryDbReady = client.execute(`
    CREATE TABLE IF NOT EXISTS diary_entries (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      date TEXT NOT NULL UNIQUE,
      content_ja TEXT NOT NULL,
      content_en TEXT,
      updated_at TEXT NOT NULL
    );
  `).then(() => undefined);

  await globalThis.__diaryDbReady;
  return client;
}

export interface DiaryEntry {
  id: number;
  date: string;
  content_ja: string;
  content_en: string | null;
  updated_at: string;
}

function toEntry(row: Record<string, unknown>): DiaryEntry {
  return {
    id: Number(row.id),
    date: String(row.date),
    content_ja: String(row.content_ja),
    content_en: row.content_en === null ? null : String(row.content_en),
    updated_at: String(row.updated_at),
  };
}

export async function getEntry(date: string): Promise<DiaryEntry | undefined> {
  const db = await getDb();
  const result = await db.execute({
    sql: "SELECT * FROM diary_entries WHERE date = ?",
    args: [date],
  });
  const row = result.rows[0];
  return row ? toEntry(row as unknown as Record<string, unknown>) : undefined;
}

export async function upsertEntry(
  date: string,
  contentJa: string
): Promise<DiaryEntry> {
  const db = await getDb();
  const now = new Date().toISOString();
  await db.execute({
    sql: `INSERT INTO diary_entries (date, content_ja, updated_at)
          VALUES (?, ?, ?)
          ON CONFLICT(date) DO UPDATE SET content_ja = excluded.content_ja, updated_at = excluded.updated_at`,
    args: [date, contentJa, now],
  });
  return (await getEntry(date))!;
}

export async function saveTranslation(
  date: string,
  contentEn: string
): Promise<DiaryEntry | undefined> {
  const db = await getDb();
  const now = new Date().toISOString();
  await db.execute({
    sql: "UPDATE diary_entries SET content_en = ?, updated_at = ? WHERE date = ?",
    args: [contentEn, now, date],
  });
  return getEntry(date);
}

export async function listEntryDatesInRange(
  from: string,
  to: string
): Promise<string[]> {
  const db = await getDb();
  const result = await db.execute({
    sql: "SELECT date FROM diary_entries WHERE date BETWEEN ? AND ? ORDER BY date",
    args: [from, to],
  });
  return result.rows.map((r) => String(r.date));
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

export async function computeStreak(todayKey: string): Promise<number> {
  const db = await getDb();
  const result = await db.execute("SELECT date FROM diary_entries");
  const dateSet = new Set(result.rows.map((r) => String(r.date)));
  if (dateSet.size === 0) return 0;

  let cursor = dateSet.has(todayKey) ? todayKey : shiftDateKey(todayKey, -1);
  let streak = 0;
  while (dateSet.has(cursor)) {
    streak += 1;
    cursor = shiftDateKey(cursor, -1);
  }
  return streak;
}
