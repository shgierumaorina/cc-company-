export const HABITS = ["workout", "english", "self_improve"] as const;
export type Habit = (typeof HABITS)[number];

export const HABIT_LABELS: Record<Habit, string> = {
  workout: "筋トレ",
  english: "英語",
  self_improve: "自己改善",
};

export const NOTE_FIELDS = ["weight", "other"] as const;
export type NoteField = (typeof NOTE_FIELDS)[number];

export const NOTE_LABELS: Record<NoteField, string> = {
  weight: "体重",
  other: "その他",
};
