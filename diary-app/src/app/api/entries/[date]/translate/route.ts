import { NextRequest, NextResponse } from "next/server";
import { getEntry, saveTranslation } from "@/lib/db";
import { translateToEnglish } from "@/lib/anthropic";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

type Params = { params: Promise<{ date: string }> };

export async function POST(_request: NextRequest, { params }: Params) {
  const { date } = await params;
  if (!DATE_RE.test(date)) {
    return NextResponse.json({ error: "invalid date" }, { status: 400 });
  }

  const entry = getEntry(date);
  if (!entry) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  try {
    const contentEn = await translateToEnglish(entry.content_ja);
    const updated = saveTranslation(date, contentEn);
    return NextResponse.json(updated);
  } catch (err) {
    const message = err instanceof Error ? err.message : "translation failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
