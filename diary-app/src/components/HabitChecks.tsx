"use client";

import type { HabitState, NoteState } from "@/lib/db";
import {
  HABITS,
  HABIT_LABELS,
  NOTE_FIELDS,
  NOTE_LABELS,
  type Habit,
  type NoteField,
} from "@/lib/habits";

interface HabitChecksProps {
  checks: HabitState;
  notes: NoteState;
  disabled: boolean;
  onToggle: (habit: Habit, done: boolean) => void;
  onChangeNote: (field: NoteField, value: string) => void;
  onSaveNote: (field: NoteField) => void;
}

export default function HabitChecks({
  checks,
  notes,
  disabled,
  onToggle,
  onChangeNote,
  onSaveNote,
}: HabitChecksProps) {
  return (
    <div className="habit-panel">
      {HABITS.map((habit) => (
        <label key={habit} className="habit-check">
          <input
            type="checkbox"
            checked={checks[habit]}
            disabled={disabled}
            onChange={(e) => onToggle(habit, e.target.checked)}
          />
          <span>{HABIT_LABELS[habit]}</span>
        </label>
      ))}
      {NOTE_FIELDS.map((field) => (
        <label key={field} className={`habit-note habit-note-${field}`}>
          <span>{NOTE_LABELS[field]}</span>
          <input
            type="text"
            inputMode={field === "weight" ? "decimal" : "text"}
            maxLength={field === "weight" ? 10 : 100}
            value={notes[field]}
            disabled={disabled}
            onChange={(e) => onChangeNote(field, e.target.value)}
            onBlur={() => onSaveNote(field)}
            onKeyDown={(e) => {
              // 日本語変換の確定Enterでは抜けない（Safariは keyCode 229 で判定）
              const composing = e.nativeEvent.isComposing || e.keyCode === 229;
              if (e.key === "Enter" && !composing) e.currentTarget.blur();
            }}
          />
          {field === "weight" && <span className="habit-note-unit">kg</span>}
        </label>
      ))}
    </div>
  );
}
