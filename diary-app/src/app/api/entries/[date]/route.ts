import { NextRequest, NextResponse } from "next/server";
import { getEntriesForDate, upsertEntry } from "@/lib/db";
import { CATEGORIES, type Category } from "@/lib/categories";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

type Params = { params: Promise<{ date: string }> };

function isCategory(value: unknown): value is Category {
  return typeof value === "string" && (CATEGORIES as readonly string[]).includes(value);
}

export async function GET(_request: NextRequest, { params }: Params) {
  const { date } = await params;
  if (!DATE_RE.test(date)) {
    return NextResponse.json({ error: "invalid date" }, { status: 400 });
  }
  const entries = await getEntriesForDate(date);
  return NextResponse.json({ entries });
}

export async function PUT(request: NextRequest, { params }: Params) {
  const { date } = await params;
  if (!DATE_RE.test(date)) {
    return NextResponse.json({ error: "invalid date" }, { status: 400 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  const category = (body as { category?: unknown })?.category;
  if (!isCategory(category)) {
    return NextResponse.json({ error: "invalid category" }, { status: 400 });
  }

  const contentJa =
    typeof (body as { content_ja?: unknown })?.content_ja === "string"
      ? (body as { content_ja: string }).content_ja
      : "";
  if (!contentJa.trim()) {
    return NextResponse.json(
      { error: "content_ja is required" },
      { status: 400 }
    );
  }

  const entry = await upsertEntry(date, category, contentJa);
  return NextResponse.json(entry);
}
