import { NextRequest, NextResponse } from "next/server";
import { getNotesForDate, setNote } from "@/lib/db";
import { NOTE_FIELDS, type NoteField } from "@/lib/habits";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const MAX_LENGTH = 500;

type Params = { params: Promise<{ date: string }> };

function isNoteField(value: unknown): value is NoteField {
  return typeof value === "string" && (NOTE_FIELDS as readonly string[]).includes(value);
}

export async function GET(_request: NextRequest, { params }: Params) {
  const { date } = await params;
  if (!DATE_RE.test(date)) {
    return NextResponse.json({ error: "invalid date" }, { status: 400 });
  }
  return NextResponse.json(await getNotesForDate(date));
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

  const field = (body as { field?: unknown })?.field;
  if (!isNoteField(field)) {
    return NextResponse.json({ error: "invalid field" }, { status: 400 });
  }

  const value = (body as { value?: unknown })?.value;
  if (typeof value !== "string" || value.length > MAX_LENGTH) {
    return NextResponse.json({ error: "invalid value" }, { status: 400 });
  }

  return NextResponse.json(await setNote(date, field, value.trim()));
}
