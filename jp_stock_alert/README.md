# jp_stock_alert

優良銘柄（財務健全性・収益性スクリーニング）が安値圏にあり、かつ出来高が急増したタイミングでDiscordに通知するツール。

## 構成

```
jp_stock_alert/
├── config.yaml            # 閾値・パラメータ設定（すべての判定基準はここで調整する）
├── .env.example            # J-Quants/Discord設定のテンプレート
├── universe/
│   ├── master_candidates.json   # irbankスコアリング結果（全評価銘柄、passed=trueが優良銘柄）
│   └── watchlist.json           # 実際に監視する銘柄（ユーザーがCLIで管理）
├── irbank_client.py        # irbank.netスクレイピング（ROE・自己資本比率・増収増益・時価総額）
├── universe_manager.py     # スコアリング・master/watchlistのI/O
├── manage_universe.py      # CLI: add / remove / list
├── rescreen.py              # 優良銘柄マスタの再選定バッチ（デフォルト母集団=日経225）
├── jquants_client.py        # J-Quants APIクライアント（未検証、下記参照）
├── signal_detector.py       # 安値圏×出来高急増の判定（単体実行可）
├── notifier.py                # Discord Webhook通知 + 当日重複防止
├── check_signals.py          # 1回分のチェック実行（タスクスケジューラから呼ぶ）
└── watch.py                   # 常駐ループ版
```

## セットアップ

1. 依存パッケージ: リポジトリ直下の `requirements.txt` に `pyyaml` を追加済み。`pip install -r requirements.txt` を実行する。
2. Discord Webhook URL: `envutil.get_secret` はリポジトリ直下（`jp_stock_alert/`の一つ上）の `.env` しか読まない。既に `DISCORD_WEBHOOK_URL` が設定済みならそのまま再利用される。別のWebhookを使いたい場合も **`jp_stock_alert/.env` ではなくリポジトリ直下の `.env`** に追記すること（`jp_stock_alert/.env.example` は追記する値のサンプル）。
3. J-Quants（任意）: リポジトリ直下の `.env` に `JQUANTS_EMAIL` / `JQUANTS_PASSWORD` を設定すると日足取得の第一候補として使う。未設定なら自動的にyfinanceのみを使う。

## 使い方

```bash
# 1. 優良銘柄マスタを作成（日経225全銘柄をirbank.netでスコアリング、数分〜十数分かかる）
python rescreen.py
# 特定銘柄のみ: python rescreen.py --codes 7203,6758

# 2. 監視対象を選ぶ
python manage_universe.py add 7203
python manage_universe.py list
python manage_universe.py remove 7203

# 3. シグナルチェック（1回分）
python check_signals.py

# 4. 常駐ループ（タスクスケジューラを使わない場合）
python watch.py

# 各モジュール単体テスト
python irbank_client.py 7203
python signal_detector.py 7203
```

## 実行スケジュール

リポジトリ直下に `jp_stock_alert_task.xml`（タスク定義）と `run_jp_stock_alert.bat`（起動用バッチ）を用意した。
**このツールはタスクの自動登録（schtasksの実行）は行っていない。** 登録する場合は以下をユーザー自身が実行すること。

```powershell
schtasks /create /xml "C:\Users\shige\Desktop\ClaudeCode\cc-company\jp_stock_alert_task.xml" /tn "JpStockAlert"
```

登録すると平日9:00〜15:00の間20分間隔で `check_signals.py` が起動する。昼休み(11:30-12:30)や取引時間外は
`check_signals.py` 内部の市場時間判定でスキップされるため、タスク側は厳密な時間指定をしていない
（既存の `nikkei_task.xml` と同じ設計）。

## 優良銘柄マスタのスコアリング基準（config.yaml）

100点満点、`score_pass_threshold`（デフォルト60点）以上でマスタ入り。

| 項目 | 満点 | 満点条件 | 部分点条件 |
|---|---|---|---|
| ROE | 25 | 10%以上 | 8%以上で15点 |
| 自己資本比率 | 20 | 40%以上 | 30%以上で10点 |
| 増収増益 | 25 | 直近確定期の売上高・営業利益がともに前期比増 | 片方のみで12点 |
| 時価総額 | 15 | 300億円以上 | - |
| 配当性向 | 15 | 50%以下 | 70%以下で7点 |

irbankから取得できなかった項目は加点せず `data_incomplete: true` を立てる（値を捏造しない）。

## データソースに関する注意

- **irbank.net**: 実ページ（`/{code}`, `/{code}/pl`）のHTML構造を確認した上でスクレイピングしている。
  アクセス頻度は `config.yaml` の `request_interval_sec`（デフォルト2秒間隔）とローカルキャッシュ
  （`cache_ttl_hours`、デフォルト24時間、`.cache/irbank/` に保存）で抑制している。
- **配当性向**: irbankには直接のラベルがないため、`配当性向(%) = 配当利回り(%) × PER(倍)`
  （= 100×DPS/EPS という恒等式）から算出している。捏造ではなく数学的導出。
- **J-Quants**: 公開されているAPI仕様（`/token/auth_user` → `/token/auth_refresh` → `/prices/daily_quotes`）
  に基づいて実装したが、**実際の認証情報での動作確認はしていない**（本環境にJ-Quantsアカウントがないため）。
  無料プランは日足EODのみでザラ場中のリアルタイム出来高は取得できないため、当日の出来高は
  J-Quants設定の有無にかかわらず常にyfinanceで補っている。取得手順は `.env.example` 参照。
- **株価・出来高（日次）**: J-Quants未設定時、または取得失敗時はyfinanceにフォールバックする。

## 出来高急増の按分ロジックについて

寄り付き直後は経過時間が短く分母が小さいため、単純な按分では小さな出来高でも「急増」と誤検知しやすい。
`config.yaml` の `volume_surge.min_elapsed_minutes`（デフォルト30分）未満は判定自体を保留する。
