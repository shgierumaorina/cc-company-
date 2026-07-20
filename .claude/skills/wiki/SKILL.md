---
name: wiki
description: ObsidianVaultにWikiの骨格（wiki/index.md・wiki/hot.md・ドメイン別サブインデックス・.raw/index.md）を一発構築する。Vaultで最初に一度だけ実行するセットアップ専用コマンド。
---

# /wiki — Vault骨格構築

Vault（`C:\Users\shige\Documents\ObsidianVault`）に以下の骨格を構築する、**初回セットアップ専用**のコマンド。内容の編纂（raw取り込み・質問応答・整理）は行わない。それは [[research-wiki]] の役割。

## 構築する構造

```
ObsidianVault/
├─ wiki/
│  ├─ index.md      … マスターカタログ（全ページの目次）
│  ├─ hot.md         … ホットキャッシュ（直近扱ったトピックの短いリスト）
│  └─ <domain>.md    … ドメイン別サブインデックス（トピックが増えるたびに追加。初回は作らない）
└─ .raw/
   └─ index.md       … 原文保管の索引（`.company/research/raw/*.md` への参照リンクのみ。内容はコピーしない）
```

## 手順

1. `wiki/index.md` が既に存在するか確認する。存在する場合は「既にセットアップ済み」として何もせず報告する（冪等・上書きしない）。
2. 存在しない場合、以下を新規作成する。
   - `wiki/index.md` — 見出しと空の目次のみ（ページが増えるごとに追記していく前提のテンプレート）。
   - `wiki/hot.md` — 見出しと「直近の更新」セクションのみ（空）。
   - `.raw/index.md` — 見出しと「参照元一覧」セクションのみ（空。`.company/research/raw/` のファイルへの相対パス参照を追記していく前提）。
3. ドメイン別サブインデックス（`wiki/technology.md` など）はこの初回構築では作らない。実際にトピックが編纂される際に必要になったドメインだけ都度作成する（空のプレースホルダを乱造しない）。
4. 作成したファイル一覧をユーザーに報告する。

## 注意

- `.raw/index.md` は索引のみで、raw本文のコピーは置かない（raw の一元管理は `.company/research/raw/` のまま。[[feedback_read_minimal]] とも整合）。
- Vaultへのcommit/pushはこのスキルでは行わない。作成後は必要に応じて [[obsidian-sync]] を別途実行する。
- 既存の `ObsidianVault/Research/*.md`（research-wiki が編纂するページ群）とは別の階層。統合や移行はユーザーの明示的な指示があるまで行わない。
