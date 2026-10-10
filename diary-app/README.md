# diary-app

日記・習慣チェックアプリ（Next.js）。本番は Render（`render.yaml`）にデプロイ。

## ローカルPCで動かす（Windows）

前提: [Node.js](https://nodejs.org/) 20.9 以上

1. `diary-app\start-local.bat` をダブルクリック
   - 初回のみ `npm ci` で依存をインストール → ビルド → `http://localhost:3000` を起動しブラウザを開く
   - ブラウザが先に開いて表示されない場合は数秒後に再読み込み
2. 停止はコマンドプロンプトで `Ctrl+C`

手動で動かす場合:

```bat
cd diary-app
npm ci
npm run dev
```

## 環境変数（任意）

`.env.example` を `.env.local` にコピーして設定する（`.env*` はコミット対象外）。

| 変数 | 未設定時の動作 |
|---|---|
| `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` | `data/diary.db`（ローカルSQLite）に保存。Render本番のデータとは別になる |
| `DEEPL_API_KEY` | 英訳ボタンがエラーになる（他の機能は動く） |
| `DIARY_PASSWORD` | Basic認証なしで開ける |

本番と同じデータを使いたい場合は `TURSO_DATABASE_URL` と `TURSO_AUTH_TOKEN` を設定する。
