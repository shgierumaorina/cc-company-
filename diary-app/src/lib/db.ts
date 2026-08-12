import { createClient, type Client } from "@libsql/client";
import fs from "fs";
import path from "path";
import type { Category } from "./categories";

declare global {
  var __diaryDb: Client | undefined;
  var __diaryDbReady: Promise<void> | undefined;
}

async function ensureMemoColumn(client: Client): Promise<void> {
  const info = await client.execute(`PRAGMA table_info(diary_entries)`);
  const hasMemo = info.rows.some((r) => String(r.name) === "memo");
  if (hasMemo) return;
  await client.execute(`ALTER TABLE diary_entries ADD COLUMN memo TEXT`);
}

async function migrateLegacyTable(client: Client): Promise<void> {
  const info = await client.execute(`PRAGMA table_info(diary_entries)`);
  if (info.rows.length === 0) return; // table doesn't exist yet
  const hasCategory = info.rows.some((r) => String(r.name) === "category");
  if (hasCategory) return;

  await client.execute(`ALTER TABLE diary_entries RENAME TO diary_entries_legacy`);
  await client.execute(`
    CREATE TABLE diary_entries (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      date TEXT NOT NULL,
      category TEXT NOT NULL,
      content_ja TEXT NOT NULL,
      content_en TEXT,
      updated_at TEXT NOT NULL,
      UNIQUE(date, category)
    );
  `);
  await client.execute(`
    INSERT INTO diary_entries (date, category, content_ja, content_en, updated_at)
    SELECT date, 'free', content_ja, content_en, updated_at FROM diary_entries_legacy
  `);
  await client.execute(`DROP TABLE diary_entries_legacy`);
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
  globalThis.__diaryDbReady = (async () => {
    await client.execute(`
      CREATE TABLE IF NOT EXISTS diary_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        category TEXT NOT NULL,
        content_ja TEXT NOT NULL,
        content_en TEXT,
        memo TEXT,
        updated_at TEXT NOT NULL,
        UNIQUE(date, category)
      );
    `);
    await migrateLegacyTable(client);
    await ensureMemoColumn(client);
  })();

  await globalThis.__diaryDbReady;
  return client;
}

export interface DiaryEntry {
  id: number;
  date: string;
  category: Category;
  content_ja: string;
  content_en: string | null;
  memo: string | null;
  updated_at: string;
}

function toEntry(row: Record<string, unknown>): DiaryEntry {
  return {
    id: Number(row.id),
    date: String(row.date),
    category: String(row.category) as Category,
    content_ja: String(row.content_ja),
    content_en: row.content_en === null ? null : String(row.content_en),
    memo: row.memo === null || row.memo === undefined ? null : String(row.memo),
    updated_at: String(row.updated_at),
  };
}

export async function getEntry(
  date: string,
  category: Category
): Promise<DiaryEntry | undefined> {
  const db = await getDb();
  const result = await db.execute({
    sql: "SELECT * FROM diary_entries WHERE date = ? AND category = ?",
    args: [date, category],
  });
  const row = result.rows[0];
  return row ? toEntry(row as unknown as Record<string, unknown>) : undefined;
}

export async function getEntriesForDate(date: string): Promise<DiaryEntry[]> {
  const db = await getDb();
  const result = await db.execute({
    sql: "SELECT * FROM diary_entries WHERE date = ?",
    args: [date],
  });
  return result.rows.map((r) => toEntry(r as unknown as Record<string, unknown>));
}

export async function upsertEntry(
  date: string,
  category: Category,
  contentJa: string
): Promise<DiaryEntry> {
  const db = await getDb();
  const now = new Date().toISOString();
  await db.execute({
    sql: `INSERT INTO diary_entries (date, category, content_ja, updated_at)
          VALUES (?, ?, ?, ?)
          ON CONFLICT(date, category) DO UPDATE SET content_ja = excluded.content_ja, updated_at = excluded.updated_at`,
    args: [date, category, contentJa, now],
  });
  return (await getEntry(date, category))!;
}

export async function saveTranslation(
  date: string,
  category: Category,
  contentEn: string
): Promise<DiaryEntry | undefined> {
  const db = await getDb();
  const now = new Date().toISOString();
  await db.execute({
    sql: "UPDATE diary_entries SET content_en = ?, updated_at = ? WHERE date = ? AND category = ?",
    args: [contentEn, now, date, category],
  });
  return getEntry(date, category);
}

export async function saveMemo(
  date: string,
  category: Category,
  memo: string
): Promise<DiaryEntry | undefined> {
  const db = await getDb();
  const now = new Date().toISOString();
  await db.execute({
    sql: "UPDATE diary_entries SET memo = ?, updated_at = ? WHERE date = ? AND category = ?",
    args: [memo, now, date, category],
  });
  return getEntry(date, category);
}

export async function listEntryDatesInRange(
  from: string,
  to: string
): Promise<string[]> {
  const db = await getDb();
  const result = await db.execute({
    sql: "SELECT DISTINCT date FROM diary_entries WHERE date BETWEEN ? AND ? ORDER BY date",
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
  const result = await db.execute("SELECT DISTINCT date FROM diary_entries");
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
