# tmux エージェント監視バックエンドサーバー 設計書

- 日付: 2026-08-23
- 対象: `cc-company/tmux-dashboard/`（新規Node.jsプロジェクト）
- 目的: tmuxで並行実行している複数のClaude Codeセッションの状態を監視・操作するAPI/WebSocketサーバー。フロントエンド（Claude Designで別途作成）から叩かれる想定。

## スコープ

含む:
- agents.json に登録したエージェント（名前とtmuxセッション名のペア）の状態監視
- REST API（一覧取得・出力取得・送信・一斉送信）
- WebSocket による状態差分のpush配信

含まない:
- フロントエンドUI（別途Claude Designで作成）
- 認証・認可（ローカル利用専用、無人運用は想定しない）
- tmuxセッション自体の起動・停止

## 実行環境

- Windows上で `node server.js` を実行。
- tmuxコマンドはWSL経由で呼び出す: `child_process.execFile('wsl', ['-e', 'tmux', ...])`。
  `execFile` + 配列引数を用い、シェル経由の文字列結合（`exec`）は使わない（シェルインジェクション対策）。

## プロジェクト構成

```
tmux-dashboard/
├── server.js          # エントリポイント（node server.js で起動、既定ポート3000）
├── package.json
├── agents.json         # [{id, name, session}] ユーザーが手動編集
├── config.json          # PORT, POLL_INTERVAL_MS, IDLE_THRESHOLD_SEC, STALE_THRESHOLD_SEC, OUTPUT_LINES
├── lib/
│   ├── tmux.js         # wsl tmux 呼び出しラッパー
│   ├── poller.js       # 定期ポーリング・状態判定ループ
│   └── state.js        # メモリ上の状態ストア
├── README.md           # API仕様書（エンドポイント一覧・レスポンス例）
└── .gitignore           # node_modules
```

依存パッケージ: `express`, `ws`, `cors` のみ。

## 内部動作

単一の poller ループが `POLL_INTERVAL_MS`（既定2500ms）ごとに全登録エージェントに対して実行し、結果をメモリ上の state ストアに保持する。REST/WebSocketはこのキャッシュを読むだけで、リクエストの都度tmuxは叩かない。

### 状態判定ロジック（優先順位順）

1. `tmux list-sessions -F '#S'` にセッション名が無い → `not_running`（未起動）
2. `tmux capture-pane` 実行がエラー（コマンド失敗、WSL異常等） → `unresponsive`
3. 前回ポーリング時との出力差分あり → `working`（作業中）
4. 出力末尾が入力待ちパターンにマッチ（`/[❯>]\s*$/`, `/\(y\/n\)/i`, `/Do you want/i`, `/continue\?/i` など） → `waiting_input`
5. 出力変化なしが `IDLE_THRESHOLD_SEC`（既定60秒）以上 → `idle`
6. 出力変化なしが `STALE_THRESHOLD_SEC`（既定300秒）以上 → `stale`

判定は上から順に評価し、最初にマッチした状態を採用する。

## API設計

### GET /api/agents
全エージェントの一覧・現在状態・直近出力・経過時間を返す。

```json
{
  "agents": [
    {
      "id": "agent1",
      "name": "リサーチ担当",
      "session": "cc-agent1",
      "status": "working",
      "lastOutputPreview": "...(直近数行の抜粋)...",
      "lastChangedAt": "2026-08-23T19:15:00+09:00",
      "elapsedSec": 12
    }
  ]
}
```
`status`: `working | waiting_input | idle | stale | not_running | unresponsive`

### GET /api/agents/:id/output
指定エージェントの直近出力全文を返す。未登録idは404。

```json
{ "id": "agent1", "session": "cc-agent1", "output": "...(capture-pane全文)..." }
```

### POST /api/agents/:id/send
リクエスト: `{ "text": "指示文" }`
`tmux send-keys -t <session> "<text>" Enter` を実行。

```json
{ "ok": true, "id": "agent1", "sentAt": "2026-08-23T19:15:03+09:00" }
```
未登録id→404、`not_running`状態→409。

### POST /api/agents/broadcast
リクエスト: `{ "text": "指示文" }`
全エージェントに一斉送信。

```json
{
  "ok": true,
  "results": [
    { "id": "agent1", "ok": true },
    { "id": "agent2", "ok": false, "error": "session not found" }
  ]
}
```

### WebSocket /ws
- 接続時: 全件スナップショットを1回送信 `{ "type": "snapshot", "agents": [...] }`
- 以降: `POLL_INTERVAL_MS`ごとに状態変化のあったエージェントのみ差分push `{ "type": "update", "agents": [...] }`

## エラーハンドリング

- WSL/tmuxコマンド失敗 → 該当エージェントを`unresponsive`にし、サーバーログに出力。サーバー全体は落とさない。
- 未登録id → 404 JSON（`{"error": "agent not found"}`）
- 不正なリクエストボディ（text欠落等） → 400 JSON

## CORS・認証

- `cors`パッケージで全オリジン許可。ローカル利用専用・認証なし。

## テスト方針

- `node -e` またはユニットテストで状態判定ロジック（`lib/poller.js`の純粋関数部分）を検証する。
- 実機tmux/WSLが無い環境でも判定ロジック単体はテスト可能な形に分離する。
- サーバー起動確認は `node server.js` 実行 → `curl http://localhost:3000/api/agents` で疎通確認する。
