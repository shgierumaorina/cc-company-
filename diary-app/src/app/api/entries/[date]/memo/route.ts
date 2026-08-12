import { NextRequest, NextResponse } from "next/server";
import { getEntry, saveMemo } from "@/lib/db";
import { CATEGORIES, type Category } from "@/lib/categories";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

type Params = { params: Promise<{ date: string }> };

function isCategory(value: unknown): value is Category {
  return typeof value === "string" && (CATEGORIES as readonly string[]).includes(value);
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

  const entry = await getEntry(date, category);
  if (!entry) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  const memo =
    typeof (body as { memo?: unknown })?.memo === "string"
      ? (body as { memo: string }).memo
      : "";

  const updated = await saveMemo(date, category, memo);
  return NextResponse.json(updated);
}
