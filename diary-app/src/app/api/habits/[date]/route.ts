import { NextRequest, NextResponse } from "next/server";
import { getHabitsForDate, setHabit } from "@/lib/db";
import { HABITS, type Habit } from "@/lib/habits";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

type Params = { params: Promise<{ date: string }> };

function isHabit(value: unknown): value is Habit {
  return typeof value === "string" && (HABITS as readonly string[]).includes(value);
}

export async function GET(_request: NextRequest, { params }: Params) {
  const { date } = await params;
  if (!DATE_RE.test(date)) {
    return NextResponse.json({ error: "invalid date" }, { status: 400 });
  }
  return NextResponse.json(await getHabitsForDate(date));
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

  const habit = (body as { habit?: unknown })?.habit;
  if (!isHabit(habit)) {
    return NextResponse.json({ error: "invalid habit" }, { status: 400 });
  }

  const done = (body as { done?: unknown })?.done;
  if (typeof done !== "boolean") {
    return NextResponse.json({ error: "invalid done" }, { status: 400 });
  }

  return NextResponse.json(await setHabit(date, habit, done));
}
