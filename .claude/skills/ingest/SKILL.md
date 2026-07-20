---
name: ingest
description: ObsidianVaultの.raw/フォルダに手動で放り込んだ記事を読み込み、要約してwiki/層（wiki/index.md・wiki/hot.md・ドメイン別サブインデックス）に取り込む。/ingest [ファイル名] で実行。
---

# /ingest — .raw/ フォルダの取り込み

`ObsidianVault/.raw/` に置かれた個別記事ファイルを読み込み、要約・相互リンク生成のうえ [[wiki]] が構築した `wiki/` 層に反映する。

## 前提

- `ObsidianVault/wiki/index.md` が存在すること。存在しなければ先に [[wiki]]（`/wiki`）を実行するようユーザーに案内し、ここでは何もしない。
- 対象ファイルは `ObsidianVault/.raw/<ファイル名>`。存在しない場合は「不明」として報告し、処理を中断する（存在しないファイルを作らない）。

## research-wiki との違い

これは [[research-wiki]] とは別の取り込みパイプライン。混同しない。

| | research-wiki（取り込み） | ingest |
|---|---|---|
| ソース | `.company/research/raw/YYYY-MM-DD-raw.md`（自動収集・日付ファイル） | `ObsidianVault/.raw/<任意ファイル名>`（ユーザーが手動で放り込む個別記事） |
| 出力先 | `ObsidianVault/Research/*.md` + `_index.md` | `ObsidianVault/wiki/*.md` + `wiki/index.md`/`wiki/hot.md` |

両者のソース・出力先を混ぜて書き込まない。

## 手順

1. `ObsidianVault/.raw/<ファイル名>` を読む。
2. 内容を要約し、該当ドメインを判定する（例: technology, science）。
3. `wiki/<domain>.md` が無ければ新規作成し、あれば末尾に新しいセクションとして追記する（既存セクションは上書きしない）。セクションには要約と出典（元ファイル名、取り込み日）を記載する。
4. 内容と関連する既存の `wiki/*.md` 内の話題があれば `[[ページ名#セクション]]` 形式で相互リンクする。
5. `wiki/index.md`（マスターカタログ）に、当該ドメインページへのリンクが無ければ追加する。
6. `wiki/hot.md`（ホットキャッシュ）に今回取り込んだトピックを追記する。直近5件を超えたら古いものから削除して短く保つ。
7. `.raw/index.md` に取り込み記録（ファイル名・取り込み日・反映先セクションへのリンク）を追記する。
8. 取り込んだ結果（作成/更新したファイルと反映先セクション）をユーザーに報告する。

## 注意

- `.raw/<ファイル名>` の原文は編集・削除・上書きしない（読み取り専用の一次情報として扱う。[[project_fx_alert_task_hang]] 等と同じくraw保護の原則に従う）。
- 1回の `/ingest` は指定された1ファイルのみを対象とする。フォルダ内の複数ファイルを一括処理しない。
- 存在しないドメイン名・架空の出典を作らない。判定に迷う場合はドメイン名をユーザーに確認する。
- Vaultへのcommit/pushはこのスキルでは行わない。反映後は必要に応じて `obsidian-sync` を別途実行する。
