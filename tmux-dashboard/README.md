# tmux-dashboard

tmuxで並行実行している複数のClaude Codeセッションを監視・操作するAPI/WebSocketサーバー。

## セットアップ

```bash
cd tmux-dashboard
npm install
cp agents.example.json agents.json
# agents.json を実際のtmuxセッションに合わせて編集
npm start
```

デフォルトで `http://localhost:3000` で起動します。ポート等は `config.json` で変更できます。

tmuxコマンドはWSL経由（`wsl -e tmux ...`）で実行します。Windows上でこのサーバーを実行し、監視対象のtmuxセッションはWSL内で動作している前提です。

## agents.json

```json
[
  { "id": "agent1", "name": "リサーチ担当", "session": "cc-agent1" }
]
```

## config.json

| キー | 既定値 | 説明 |
|---|---|---|
| PORT | 3000 | HTTP/WebSocketのポート |
| POLL_INTERVAL_MS | 2500 | tmux poll間隔（ミリ秒） |
| IDLE_THRESHOLD_SEC | 60 | この秒数以上出力変化がなければ`idle` |
| STALE_THRESHOLD_SEC | 300 | この秒数以上出力変化がなければ`stale` |
| OUTPUT_LINES | 200 | capture-paneで取得する行数 |

## 状態(status)一覧

- `working`: 出力が変化中
- `waiting_input`: 出力末尾が確認プロンプトらしき文字列
- `idle`: 一定時間出力変化なし
- `stale`: 長時間出力変化なし（応答なし疑い）
- `not_running`: tmuxセッション未起動
- `unresponsive`: tmuxコマンド実行エラー

## API

### GET /api/agents

全エージェントの一覧・状態・直近出力・経過時間を返す。

```json
{
  "agents": [
    {
      "id": "agent1",
      "name": "リサーチ担当",
      "session": "cc-agent1",
      "status": "working",
      "lastOutputPreview": "...(直近5行)...",
      "lastChangedAt": "2026-08-23T19:15:00.000Z",
      "elapsedSec": 12
    }
  ]
}
```

### GET /api/agents/:id/output

指定エージェントの直近出力全文を返す。未登録idは404。

```json
{ "id": "agent1", "session": "cc-agent1", "output": "...(capture-pane全文)..." }
```

### POST /api/agents/:id/send

リクエストボディ: `{ "text": "指示文" }`

```json
{ "ok": true, "id": "agent1", "sentAt": "2026-08-23T19:15:03.000Z" }
```

エラー: text欠落→400、未登録id→404、`not_running`状態→409。

### POST /api/agents/broadcast

リクエストボディ: `{ "text": "指示文" }`

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

- 接続時: `{ "type": "snapshot", "agents": [...] }`（全件）
- 以降: `{ "type": "update", "agents": [...] }`（状態変化のあったエージェントのみ、`POLL_INTERVAL_MS`ごと）

## フロントエンド

`public/index.html` にバニラJSのダッシュボードがあります。追加のnpm依存はありません。

```bash
npm run serve
```

既定で `http://localhost:8080` で配信されます。`public/index.html` 内の `API_BASE` 定数（既定 `http://localhost:3000`）を編集すればバックエンドの接続先を変更できます。

## テスト

```bash
npm test
```
