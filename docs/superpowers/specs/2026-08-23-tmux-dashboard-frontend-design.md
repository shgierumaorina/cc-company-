# tmuxエージェント監視フロントエンド 設計書

- 日付: 2026-08-23
- 対象: `tmux-dashboard/public/index.html`, `tmux-dashboard/serve.js`（既存の`tmux-dashboard`バックエンドに追加する新規サブシステム）
- 目的: `tmux-dashboard`バックエンド（[docs/superpowers/specs/2026-08-23-tmux-dashboard-backend-design.md](2026-08-23-tmux-dashboard-backend-design.md)、`http://localhost:3000`）と通信し、複数のtmuxエージェントの状態監視・指示送信を行うWebダッシュボード。

## スコープ

含む:
- カード形式のエージェント一覧表示（状態バッジ・出力プレビュー・経過時間）
- 出力全文モーダル表示
- 個別指示送信・全体一斉送信
- WebSocketによるリアルタイム更新・切断検知・自動再接続
- ダッシュボードの配信用簡易静的サーバー

含まない:
- ビルドツール・フレームワーク（React等）導入
- 認証
- バックエンド側の変更

## 技術構成

- バニラJS + HTML + CSS の単一ファイル `tmux-dashboard/public/index.html`（外部CDN依存なし）
- 配信用に `tmux-dashboard/serve.js`（Node標準`http`+`fs`モジュールのみ、追加npm依存なし）を追加し、`package.json`に`"serve": "node serve.js"`スクリプトを追加。既定ポート8080。
- バックエンド（3000番、既存のCORS全許可設定）とは別ポートで動作する。

## 配色・スタイル

既存の`cost_dashboard.html`のダークテーマを踏襲する:
- 背景 `#0f0f1a`、カード背景 `#1e1e2e`、ボーダー `#2d2d44`、本文文字 `#e2e8f0`、見出しアクセント `#a78bfa`
- 状態バッジは意味色を使う: `working`=緑`#4ade80`, `waiting_input`=黄`#facc15`, `idle`=グレー`#94a3b8`, `stale`=オレンジ`#fb923c`, `not_running`=濃グレー`#475569`, `unresponsive`=赤`#f87171`

## 画面構成

### ヘッダー
- タイトル「tmux エージェント監視ダッシュボード」
- WebSocket接続状態インジケーター（●接続中=緑 / ●切断・再接続中=赤）

### 一斉送信バー
- テキスト入力 + 「全員に送信」ボタン。送信中はボタン無効化、完了後は各エージェントの結果件数（成功/失敗）をトースト表示。

### エージェントカードグリッド
`display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));`

各カードに表示する要素:
- エージェント名 + status バッジ
- 直近出力プレビュー（`lastOutputPreview`、`<pre>`で等幅表示）。クリックで`<dialog>`モーダルを開き、`GET /api/agents/:id/output`を都度fetchして全文表示。
- 経過時間表示（`elapsedSec`を起点にクライアント側で1秒ごとにインクリメントし「3秒前」「2分前」のように整形。WS更新を受信するたびに`elapsedSec`をリセット）
- 指示入力欄（`<input>`）+ 送信ボタン。Enterキーでも送信。送信中はボタン無効化、成功/失敗をカード上に一時表示（3秒で消える）。

## データフロー

1. 初期表示: `GET /api/agents` を1回fetchし、返ってきた`agents`配列でカードを描画する。
2. リアルタイム更新: `new WebSocket('ws://<API_HOST>/ws')` に接続。
   - `{"type":"snapshot","agents":[...]}` 受信 → 全カードを置き換え
   - `{"type":"update","agents":[...]}` 受信 → 該当idのカードのみDOM更新
3. 切断検知: WebSocketの`onclose`/`onerror`でヘッダーの接続状態を「切断・再接続中」に変更し、2秒間隔で再接続を試行する。再接続成功（`onopen`）で「接続中」に戻す。
4. 送信: `POST /api/agents/:id/send`（個別）/ `POST /api/agents/broadcast`（一斉）をfetchで呼ぶ。

## API Base URL設定

`index.html`内のJS先頭に定数 `const API_BASE = 'http://localhost:3000';` を置き、WebSocket URLは `API_BASE`のプロトコル/ホストから`ws://`に変換して生成する。将来ホストを変える場合はこの1行を編集すればよい。

## エラーハンドリング

- 初期fetch失敗時: カードグリッドの位置に「バックエンドに接続できません（`API_BASE`を確認してください）」を表示。
- 個別送信・一斉送信のfetch失敗時: カード上またはトーストにエラーメッセージを表示し、コンソールに詳細をログ出力。
- WebSocket接続失敗・切断: ヘッダーインジケーターで表示し、自動再接続を継続する（無限リトライ、上限なし。ローカル利用のみのため）。

## テスト方針

- ユニットテスト対象となるロジック（経過時間のフォーマット関数など）は`<script>`内から抽出しない（単一HTMLファイル方針のため）。関数を`window`にぶら下げず、目視・実機確認で検証する。
- Chrome（Browser pane）でバックエンドを起動した状態で実際にページを開き、以下を確認する:
  - カード一覧表示、状態バッジの色分け
  - 出力モーダルの開閉
  - 個別送信・一斉送信の実行（バックエンドのモックagentsに対して）
  - WebSocket自動更新（バックエンドを一時停止して切断表示→再起動で復帰表示）
