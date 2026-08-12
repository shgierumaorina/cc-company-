import { NextRequest, NextResponse } from "next/server";
import { getEntry, saveTranslation } from "@/lib/db";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

type Params = { params: Promise<{ date: string }> };

export async function PUT(request: NextRequest, { params }: Params) {
  const { date } = await params;
  if (!DATE_RE.test(date)) {
    return NextResponse.json({ error: "invalid date" }, { status: 400 });
  }

  const entry = await getEntry(date);
  if (!entry) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "invalid JSON body" }, { status: 400 });
  }

  const contentEn =
    typeof (body as { content_en?: unknown })?.content_en === "string"
      ? (body as { content_en: string }).content_en
      : "";
  if (!contentEn.trim()) {
    return NextResponse.json(
      { error: "content_en is required" },
      { status: 400 }
    );
  }

  const updated = await saveTranslation(date, contentEn);
  return NextResponse.json(updated);
}
