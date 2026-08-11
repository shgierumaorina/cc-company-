import { NextRequest, NextResponse } from "next/server";
import { listEntryDatesInRange } from "@/lib/db";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export async function GET(request: NextRequest) {
  const from = request.nextUrl.searchParams.get("from");
  const to = request.nextUrl.searchParams.get("to");
  if (!from || !to || !DATE_RE.test(from) || !DATE_RE.test(to)) {
    return NextResponse.json(
      { error: "from and to query params must be YYYY-MM-DD" },
      { status: 400 }
    );
  }
  const dates = listEntryDatesInRange(from, to);
  return NextResponse.json({ dates });
}
