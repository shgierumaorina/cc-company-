# tmux-dashboard node-pty移行 設計書

- 日付: 2026-08-23
- 対象: `tmux-dashboard/`（既存バックエンドの内部実装を置き換え）
- 背景: `tmux-dashboard`はWSL経由のtmux（`wsl -e tmux ...`）を前提に実装したが（[2026-08-23-tmux-dashboard-backend-design.md](2026-08-23-tmux-dashboard-backend-design.md)）、実際の運用環境にはWSLがインストールされておらず、監視対象のClaude Codeセッションも手動で個別に開いたWindowsネイティブのターミナルウィンドウで動いていることが判明した。tmuxに依存する設計そのものがこの環境では機能しないため、node-ptyでバックエンドがclaudeプロセス自体を起動・保有する方式に作り直す。

## スコープ

含む:
- `lib/tmux.js` → `lib/agentProcess.js`（node-pty経由でclaudeプロセスを起動・書き込み）への置き換え
- `lib/poller.js` → `lib/manager.js`（イベント駆動の出力蓄積＋定期的な状態再判定）への置き換え
- `agents.json`のフォーマット変更（`session`→`cwd`、`command`は`claude`固定）
- APIレスポンスの`session`フィールドを`cwd`にリネーム（フロントエンドの参照箇所も追従修正）
- サーバー起動時の全エージェント自動spawn

含まない:
- プロセスクラッシュ時の自動再起動・手動再起動ボタン（将来対応）
- `claude`以外の任意コマンド指定（`command`は固定）
- 認証・複数ユーザー対応

## 技術構成

- 追加npm依存: `node-pty`（ビルド不要、プリビルドバイナリで動作することを実機確認済み）
- 既存の`express`, `ws`, `cors`はそのまま使用

## agentProcess.js（旧tmux.js相当）

```
spawnAgentProcess({ command, args, cwd, cols, rows }) → ptyProcess
  node-ptyの pty.spawn() をラップする薄い関数。テスト時に差し替え可能にするため、
  実際の呼び出し（pty.spawn）をこの関数1つに閉じ込める。

writeToProcess(ptyProcess, text) → void
  ptyProcess.write(text + '\r') を呼ぶ。
```

## manager.js（旧poller.jsの後継）

`poller.js`の`determineStatus`・`matchesWaitingInputPattern`は純粋関数なのでそのまま流用する。

責務:
1. 起動時: `agentsConfig`の各エージェントについて`spawnAgentProcess`を呼び、返ってきた`ptyProcess`を保持する。
2. `ptyProcess.onData`: 受信するたびに該当エージェントの出力バッファ（`rawOutput`、末尾`OUTPUT_LINES`行に切り詰め）に追記し、`lastChangedAt`を更新、`state`に反映する。
3. `ptyProcess.onExit`: 該当エージェントの状態を`not_running`とし、`state`に反映する。以降そのエージェントへの`send`は409を返す（既存の`not_running`チェックをそのまま利用）。
4. `spawnAgentProcess`が例外を投げた場合（`cwd`が存在しない、`claude`コマンドが見つからない等）: 該当エージェントを`unresponsive`にし、ログ出力。サーバー全体は落とさない。
5. `POLL_INTERVAL_MS`ごとのタイマーで全エージェントの`secondsSinceChange`を再計算し、`determineStatus`で状態を再判定する（`outputChanged`は直近tickでデータ受信があったかどうかのフラグとして扱う）。状態が変わったエージェントidをコールバックで返す（WebSocket配信用、既存の`startPolling`と同じインターフェースを維持）。

## agents.json（新フォーマット）

```json
[
  { "id": "agent1", "name": "リサーチ担当", "cwd": "C:\\path\\to\\project1" }
]
```

`command`は常に`claude`（固定、設定項目としては持たない）。

## API仕様の変更点

- エンドポイント（`GET /api/agents`, `GET /api/agents/:id/output`, `POST /api/agents/:id/send`, `POST /api/agents/broadcast`, `WebSocket /ws`）は変更なし。
- レスポンスの`session`フィールドを`cwd`にリネームする。影響箇所: `server.js`のレスポンス生成、`lib/state.js`の`formatAgentSummary`、`tmux-dashboard/public/index.html`（フロントエンドはこのフィールド名を直接参照していないため実質修正不要。念のため`README.md`のレスポンス例のみ更新する）。
- `status`の意味変更:
  - `not_running`: プロセス未起動 or 終了済み（旧: tmuxセッションが存在しない）
  - `unresponsive`: spawn失敗（旧: tmuxコマンド実行エラー）
  - 他の状態（`working`/`waiting_input`/`idle`/`stale`）は判定ロジックそのまま変更なし

## エラーハンドリング

- spawn失敗時: 該当エージェントを`unresponsive`にしてログ出力、他のエージェントのspawnは継続する。
- `POST /api/agents/:id/send`を`not_running`（プロセス終了済み）に対して呼んだ場合: 既存通り409を返す。

## テスト方針

- `determineStatus`/`matchesWaitingInputPattern`の既存ユニットテストはそのまま流用（変更不要）。
- `lib/agentProcess.js`は実際の`claude`ではなく、Windows標準の軽量コマンド（`cmd.exe /c echo ...`等）でspawn→データ受信→書き込みの単体テストを行う。
- `lib/manager.js`は`spawnAgentProcess`をモック注入してテストする（実プロセスを起動しない）。
- 実際の`claude`プロセスでの動作確認はBrowser toolによる手動統合確認で行う（既存の`README.md`テスト方針を踏襲）。
