import { NextRequest, NextResponse } from "next/server";
import { computeStreak } from "@/lib/db";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function serverTodayKey(): string {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = (now.getMonth() + 1).toString().padStart(2, "0");
  const dd = now.getDate().toString().padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export async function GET(request: NextRequest) {
  const todayParam = request.nextUrl.searchParams.get("today");
  const today =
    todayParam && DATE_RE.test(todayParam) ? todayParam : serverTodayKey();
  const streak = computeStreak(today);
  return NextResponse.json({ streak });
}
