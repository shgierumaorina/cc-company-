"use client";

import { useEffect, useState } from "react";
import type { DiaryEntry } from "@/lib/db";
import { CATEGORIES, CATEGORY_LABELS, type Category } from "@/lib/categories";

interface DiaryPanelProps {
  selectedDate: string;
  entries: Record<Category, DiaryEntry | null>;
  loading: boolean;
  saving: boolean;
  translating: boolean;
  savingTranslation: boolean;
  savingMemo: boolean;
  error: string | null;
  onSave: (category: Category, contentJa: string) => void;
  onTranslate: (category: Category) => void;
  onSaveTranslation: (category: Category, contentEn: string) => void;
  onSaveMemo: (category: Category, memo: string) => void;
}

const GEMINI_URL = "https://gemini.google.com/app";

function formatDateHeading(dateKey: string): string {
  const [y, m, d] = dateKey.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  const weekday = ["日", "月", "火", "水", "木", "金", "土"][date.getDay()];
  return `${y}年${m}月${d}日（${weekday}）`;
}

function draftsFrom(entries: Record<Category, DiaryEntry | null>): Record<Category, string> {
  return {
    free: entries.free?.content_ja ?? "",
    work: entries.work?.content_ja ?? "",
    study: entries.study?.content_ja ?? "",
  };
}

function translationDraftsFrom(
  entries: Record<Category, DiaryEntry | null>
): Record<Category, string> {
  return {
    free: entries.free?.content_en ?? "",
    work: entries.work?.content_en ?? "",
    study: entries.study?.content_en ?? "",
  };
}

function memoDraftsFrom(entries: Record<Category, DiaryEntry | null>): Record<Category, string> {
  return {
    free: entries.free?.memo ?? "",
    work: entries.work?.memo ?? "",
    study: entries.study?.memo ?? "",
  };
}

export default function DiaryPanel({
  selectedDate,
  entries,
  loading,
  saving,
  translating,
  savingTranslation,
  savingMemo,
  error,
  onSave,
  onTranslate,
  onSaveTranslation,
  onSaveMemo,
}: DiaryPanelProps) {
  const [activeTab, setActiveTab] = useState<Category>("free");

  const syncKey = `${selectedDate}:${CATEGORIES.map((c) => entries[c]?.updated_at ?? "").join(",")}`;
  const [lastSyncKey, setLastSyncKey] = useState(syncKey);
  const [drafts, setDrafts] = useState<Record<Category, string>>(() => draftsFrom(entries));
  const [translationDrafts, setTranslationDrafts] = useState<Record<Category, string>>(
    () => translationDraftsFrom(entries)
  );
  const [memoDrafts, setMemoDrafts] = useState<Record<Category, string>>(
    () => memoDraftsFrom(entries)
  );
  const [speaking, setSpeaking] = useState(false);
  const [copied, setCopied] = useState(false);

  if (syncKey !== lastSyncKey) {
    setLastSyncKey(syncKey);
    setDrafts(draftsFrom(entries));
    setTranslationDrafts(translationDraftsFrom(entries));
    setMemoDrafts(memoDraftsFrom(entries));
  }

  useEffect(() => {
    return () => {
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    };
  }, [syncKey, activeTab]);

  const entry = entries[activeTab];
  const draft = drafts[activeTab];
  const translationDraft = translationDrafts[activeTab];
  const memoDraft = memoDrafts[activeTab];
  const isDirty = draft !== (entry?.content_ja ?? "");
  const translationIsDirty = translationDraft !== (entry?.content_en ?? "");
  const memoIsDirty = memoDraft !== (entry?.memo ?? "");
  const hasTranslation = Boolean(entry?.content_en) || translationDraft.trim().length > 0;

  const handleCopyTranslation = () => {
    if (typeof window === "undefined" || !navigator.clipboard) return;
    navigator.clipboard
      .writeText(translationDraft)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => {});
  };

  const handleOpenGemini = () => {
    window.open(GEMINI_URL, "_blank", "noopener,noreferrer");
  };

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

  const handleSelectTab = (category: Category) => {
    if (category === activeTab) return;
    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
    }
    setCopied(false);
    setActiveTab(category);
  };

  return (
    <div className="diary-panel">
      <h2 className="diary-heading">{formatDateHeading(selectedDate)}</h2>

      <div className="diary-tabs" role="tablist">
        {CATEGORIES.map((category) => (
          <button
            key={category}
            type="button"
            role="tab"
            aria-selected={activeTab === category}
            className={`diary-tab${activeTab === category ? " diary-tab--active" : ""}`}
            onClick={() => handleSelectTab(category)}
          >
            {CATEGORY_LABELS[category]}
          </button>
        ))}
      </div>

      <textarea
        className="diary-textarea"
        value={draft}
        placeholder="今日のことを書く……"
        onChange={(e) => setDrafts((prev) => ({ ...prev, [activeTab]: e.target.value }))}
        disabled={loading}
        rows={9}
      />

      <button
        type="button"
        className="btn btn--pill"
        disabled={saving || !draft.trim() || !isDirty}
        onClick={() => onSave(activeTab, draft)}
      >
        {saving ? "保存中…" : `${CATEGORY_LABELS[activeTab]}の日記を書く`}
      </button>

      <div className="diary-actions">
        <button
          type="button"
          className="btn btn--outline"
          disabled={!entry || translating || isDirty}
          onClick={() => onTranslate(activeTab)}
          title={isDirty ? "先に保存してください" : undefined}
        >
          {translating ? "翻訳中…" : "英語に変換"}
        </button>
      </div>

      {error && <p className="diary-error">{error}</p>}

      {hasTranslation && (
        <div className="diary-translation">
          <div className="diary-translation-header">
            <h3 className="diary-translation-label">English</h3>
            <button
              type="button"
              className="btn btn--outline btn--small"
              onClick={handleOpenGemini}
            >
              Gemini起動
            </button>
          </div>
          <textarea
            className="diary-translation-textarea"
            value={translationDraft}
            onChange={(e) =>
              setTranslationDrafts((prev) => ({ ...prev, [activeTab]: e.target.value }))
            }
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
              onClick={() => onSaveTranslation(activeTab, translationDraft)}
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
            <button
              type="button"
              className="btn btn--outline btn--small"
              disabled={!translationDraft.trim()}
              onClick={handleCopyTranslation}
            >
              {copied ? "コピーしました" : "コピー"}
            </button>
          </div>

          <div className="diary-memo">
            <h3 className="diary-translation-label">メモ</h3>
            <textarea
              className="diary-translation-textarea"
              value={memoDraft}
              placeholder="メモを書く……"
              onChange={(e) =>
                setMemoDrafts((prev) => ({ ...prev, [activeTab]: e.target.value }))
              }
              rows={5}
            />
            <div className="diary-translation-actions">
              <button
                type="button"
                className="btn btn--outline btn--small"
                disabled={savingMemo || !memoIsDirty}
                onClick={() => onSaveMemo(activeTab, memoDraft)}
              >
                {savingMemo ? "登録中…" : "登録"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
