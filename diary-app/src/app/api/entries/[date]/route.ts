import { NextRequest, NextResponse } from "next/server";
import { getEntry, upsertEntry } from "@/lib/db";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

type Params = { params: Promise<{ date: string }> };

export async function GET(_request: NextRequest, { params }: Params) {
  const { date } = await params;
  if (!DATE_RE.test(date)) {
    return NextResponse.json({ error: "invalid date" }, { status: 400 });
  }
  const entry = await getEntry(date);
  if (!entry) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return NextResponse.json(entry);
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

  const entry = await upsertEntry(date, contentJa);
  return NextResponse.json(entry);
}
