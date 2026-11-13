# english-app（英語リスニング・ラボ クラウド版）

ポッドキャストを「区間を聞く → 要旨チェック → 答え合わせ（聞き取れない原因のタグ付け）→ AIと会話 → 復習」で毎日10分学習するWebアプリ。スマホからいつでも使える。日記アプリ（diary-app）とは別のアプリ。

## 仕組み

| 役割 | 場所 | 料金 |
|---|---|---|
| 画面・API（`app/server.py`） | Render の無料Webサービス | 無料 |
| データ（学習記録・文字起こし・会話） | Turso（日記と同じDB。表は `en_kv` のみで日記の表には触れない） | 無料枠 |
| 文字起こし（Whisper）・要旨問題作成 | GitHub Actions `.github/workflows/english-prepare.yml` | 公開リポジトリは無料 |
| 要旨問題・翻訳・会話 | Gemini API 無料枠 | 無料 |
| 音声 | 保存しない。番組の配信元URLから直接再生 | — |
| 発話の文字化・読み上げ | ブラウザ（Chrome / Edge / Safari） | 無料 |

- 画面で「準備する」を押すと順番待ちになり、30分以内にGitHub Actionsが文字起こしを始める（38分の回で15分前後が目安）。
- 毎朝JST 3:07に、新着確認と各番組の未準備の最新回1本の準備を自動で行う。
- 追加ライブラリなし（Render側は標準ライブラリのみ）。Actionsだけ `requirements-actions.txt`（faster-whisper）を入れる。

## 初回セットアップ（ユーザーが行う）

### 1. Render にWebサービスを作る

Render ダッシュボード → New → Web Service → このリポジトリを選び、次のように設定する。

- Root Directory: `english-app`
- Runtime: Python 3
- Build Command: `echo "no build"`
- Start Command: `python -m app.server`
- Instance Type: Free
- Health Check Path: `/api/health`

環境変数（Environment）:

| 名前 | 値 |
|---|---|
| `TURSO_DATABASE_URL` | 日記アプリと同じ値 |
| `TURSO_AUTH_TOKEN` | 日記アプリと同じ値 |
| `GEMINI_API_KEY` | Google AI Studio で発行したキー |
| `APP_PASSWORD` | このアプリを開くときのパスワード（自分で決める） |
| `GITHUB_DISPATCH_TOKEN`（任意） | GitHubのFine-grainedトークン（対象リポジトリ cc-company-、権限 Actions: Read and write）。設定すると「準備する」を押した直後に文字起こしが始まる。未設定なら30分ごとの定期実行で拾う |

### 2. GitHub Actions の Secrets を入れる

GitHub → このリポジトリ → Settings → Secrets and variables → Actions → New repository secret

- `TURSO_DATABASE_URL`、`TURSO_AUTH_TOKEN`、`GEMINI_API_KEY`（Renderと同じ値）

### 3. 使い始める

1. Render のURL（`https://〜.onrender.com`）をスマホのChromeで開き、パスワードを入れる（ユーザー名は何でもよい）
2. 「番組と音源」で Apple Podcasts の番組URLを登録し、エピソードの「準備する」を押す
3. Chromeのメニュー →「ホーム画面に追加」でアプリのように使える

## 注意

- Render無料プランは15分使わないと停止し、次に開くとき30秒〜1分ほど待つ。これを防ぐため `.github/workflows/english-keepalive.yml` が JST 6:00〜24:00 の間10分ごとに `/api/health` を叩く（リポジトリ変数 `ENGLISH_APP_URL` にRenderのURLを登録しておく）。夜間は無料枠（月750時間）節約のため止めている。
- Gemini無料枠では、送った内容（文字起こし・会話）がGoogleのサービス改善に使われることがある。
- このリポジトリは公開設定。Actionsのログにはエピソード名が出る（文字起こし本文は出さない）。
- PC版（Windowsで動く版）は `C:\Users\shige\AI開発\listening-lab` にあり、こちらとはデータを共有しない。

## 手元での動作確認

```bash
cd english-app
python -m app.server        # TURSO_DATABASE_URL 未設定なら data/ に保存
```
