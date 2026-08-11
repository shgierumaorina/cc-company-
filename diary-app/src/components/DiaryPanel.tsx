"use client";

import { useEffect, useState } from "react";
import type { DiaryEntry } from "@/lib/db";

interface DiaryPanelProps {
  selectedDate: string;
  entry: DiaryEntry | null;
  loading: boolean;
  saving: boolean;
  translating: boolean;
  savingTranslation: boolean;
  error: string | null;
  onSave: (contentJa: string) => void;
  onTranslate: () => void;
  onSaveTranslation: (contentEn: string) => void;
}

function formatDateHeading(dateKey: string): string {
  const [y, m, d] = dateKey.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const weekday = ["日", "月", "火", "水", "木", "金", "土"][date.getDay()];
  return `${y}年${m}月${d}日（${weekday}）`;
}

export default function DiaryPanel({
  selectedDate,
  entry,
  loading,
  saving,
  translating,
  savingTranslation,
  error,
  onSave,
  onTranslate,
  onSaveTranslation,
}: DiaryPanelProps) {
  const syncKey = `${selectedDate}:${entry?.updated_at ?? ""}`;
  const [lastSyncKey, setLastSyncKey] = useState(syncKey);
  const [draft, setDraft] = useState(entry?.content_ja ?? "");
  const [translationDraft, setTranslationDraft] = useState(
    entry?.content_en ?? ""
  );
  const [speaking, setSpeaking] = useState(false);

  if (syncKey !== lastSyncKey) {
    setLastSyncKey(syncKey);
    setDraft(entry?.content_ja ?? "");
    setTranslationDraft(entry?.content_en ?? "");
  }

  useEffect(() => {
    return () => {
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    };
  }, [syncKey]);

  const isDirty = draft !== (entry?.content_ja ?? "");
  const translationIsDirty = translationDraft !== (entry?.content_en ?? "");
  const hasTranslation = Boolean(entry?.content_en) || translationDraft.trim().length > 0;

  const handleToggleSpeak = () => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      return;
    }
    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
      return;
    }
    const utterance = new SpeechSynthesisUtterance(translationDraft);
    utterance.lang = "en-US";
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
    setSpeaking(true);
  };

  return (
    <div className="diary-panel">
      <h2 className="diary-heading">{formatDateHeading(selectedDate)}</h2>

      <textarea
        className="diary-textarea"
        value={draft}
        placeholder="今日のことを書く……"
        onChange={(e) => setDraft(e.target.value)}
        disabled={loading}
        rows={9}
      />

      <button
        type="button"
        className="btn btn--pill"
        disabled={saving || !draft.trim() || !isDirty}
        onClick={() => onSave(draft)}
      >
        {saving ? "保存中…" : "自由に日記を書く"}
      </button>

      <div className="diary-actions">
        <button
          type="button"
          className="btn btn--outline"
          disabled={!entry || translating || isDirty}
          onClick={onTranslate}
          title={isDirty ? "先に保存してください" : undefined}
        >
          {translating ? "翻訳中…" : "英語に変換"}
        </button>
      </div>

      {error && <p className="diary-error">{error}</p>}

      {hasTranslation && (
        <div className="diary-translation">
          <h3 className="diary-translation-label">English</h3>
          <textarea
            className="diary-translation-textarea"
            value={translationDraft}
            onChange={(e) => setTranslationDraft(e.target.value)}
            rows={6}
          />
          <div className="diary-translation-actions">
            <button
              type="button"
              className="btn btn--outline btn--small"
              disabled={
                savingTranslation ||
                !translationDraft.trim() ||
                !translationIsDirty
              }
              onClick={() => onSaveTranslation(translationDraft)}
            >
              {savingTranslation ? "保存中…" : "保存"}
            </button>
            <button
              type="button"
              className="btn btn--flame btn--small"
              disabled={!translationDraft.trim()}
              onClick={handleToggleSpeak}
            >
              {speaking ? "⏹ 停止" : "🔊 音読"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
