export const CATEGORIES = ["free", "work", "study"] as const;
export type Category = (typeof CATEGORIES)[number];

export const CATEGORY_LABELS: Record<Category, string> = {
  free: "フリー",
  work: "仕事",
  study: "自己学習",
};
