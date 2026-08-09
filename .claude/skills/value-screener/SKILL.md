---
name: value-screener
description: TDnetの決算短信を取得しclaude -pでセンチメントをスコアリング、バリュー指標(PER/PBR)と組み合わせてExcel出力する。出来高急増銘柄・Discord通知済み底値圏/急騰銘柄と連携して「今日の候補銘柄の決算センチメント」も確認できる。手動実行専用（stock-screener.pyの無人デイトレフローとは独立）
---

# バリュー株センチメントスクリーナー

`scripts/value-screener.py`（手動実行専用）を操作する。TDnetの決算短信PDFを取得し、
`claude -p`（Pro/Maxプラン認証、API課金なし）でセンチメントをスコアリング、
PER/PBRと組み合わせてExcelに出力する。

## 引数による分岐

`/value-screener` の引数に応じて以下を実行する。

### 銘柄コードを直接指定する場合

`/value-screener 7203,6758` のようにカンマ区切りのコードが渡されたら:

```bash
cd "C:/Users/shige/Desktop/ClaudeCode/cc-company" && python scripts/value-screener.py --codes <コード> --export-excel value_screen_$(date +%Y%m%d).xlsx
```

### 引数なし、または「出来高急増」「volsurge」等の指定があった場合

本日の出来高急増銘柄を取得してから実行する（2ステップ）。

1. 出来高急増データを取得:
   ```bash
   cd "C:/Users/shige/Desktop/ClaudeCode/cc-company" && python scripts/daily-picks.py --mode volsurge --no-notify
   ```
   - 場中データが無い場合（例: 開場前・休日）は `[volsurge] 当日データなし ... 休場とみなし通知スキップ` と表示されて終了する。
   - この場合、そのままユーザーに「本日分のデータがまだ無い」旨を報告する。**前営業日データで代用するかは必ずユーザーに確認してから** `--force` を付けて再実行すること（無断で代用しない）。
2. 出力（標準出力の `N. コード 銘柄名 score=X` の行、または `.company/japan-stock/daily/YYYY-MM-DD-picks.md` の出来高急増セクション）からコードを抽出する
3. 抽出したコードを `--codes` にカンマ区切りで渡して実行:
   ```bash
   cd "C:/Users/shige/Desktop/ClaudeCode/cc-company" && python scripts/value-screener.py --codes <抽出したコード一覧> --export-excel volsurge_value_screen_$(date +%Y%m%d).xlsx
   ```

### 「底値圏」「急騰」「notified」「discord通知」等の指定があった場合

`daily-picks.py` が実際にDiscordへ通知した銘柄（底値圏=bottom/higherlowモード、急騰=gap/closestrongモード）を
再スコア評価してから、value-screenerで決算センチメントも確認する（3ステップ）。

1. 通知済み銘柄の技術・バリュエーション再スコア評価を取得:
   ```bash
   cd "C:/Users/shige/Desktop/ClaudeCode/cc-company" && python scripts/notified-stock-score.py --days 5 --top-n 5 --min-occur 2
   ```
   - `.company/japan-stock/picks-log.tsv` に該当データが無い場合はそのまま「対象銘柄が見つかりません」と報告する
   - ユーザーが期間・件数を指定した場合は `--days`（遡る営業日数）・`--top-n`（各モード上位何位まで対象か）・`--min-occur`（最低出現回数）を調整する
   - 出力の「底値圏候補」「急騰候補」それぞれのブロックからコードを抽出する（`[コード] 銘柄名 score=X ...` の行）。この時点でRSI・BB・25日線乖離・出来高倍率による技術スコアと根拠（反発初動/過熱警戒など）がすでに得られている
2. 抽出したコードをまとめて `--codes` に渡して実行:
   ```bash
   cd "C:/Users/shige/Desktop/ClaudeCode/cc-company" && python scripts/value-screener.py --codes <抽出したコード一覧> --export-excel notified_value_screen_$(date +%Y%m%d).xlsx
   ```
3. Excelのセンチメント・バリュー判定と、手順1で得た技術スコア・根拠（特に「⚠️過熱警戒」「⚠️既に底値圏を脱している」等のリスクフラグ）を突き合わせて総合評価する。結果をObsidian（`wiki/japan-stock.md`。無ければ新規作成し `wiki/index.md` の Domains にリンク追記）にまとめたいとユーザーが望む場合は `mcp__obsidian-vault__write_note` で追記する

## Excel出力後のおすすめ表示

`--export-excel` を伴う実行が完了したら、出力先Excelを読み込み、結果報告の最後に「おすすめ」を提示する。

1. Excelを読み込む（例: `python -c "import openpyxl; ..."`）。列は
   `コード, 会社名, PER, PBR, 株価, バリュー型, 決算開示日, 直近センチメント, 直近スコア, センチメント件数, トレンド判定, ...` の順。
2. 「バリュー型」列が `True`（PER/PBRが `--per-max`/`--pbr-max` 以下）かつ「直近センチメント」が `positive` の銘柄を最優先候補として提示する。
3. 該当が無い場合は、直近センチメントが `positive` な銘柄の中からPER/PBRが相対的に低いものを参考情報として提示し、「バリュー基準は満たしていない（割安ではない）」旨を明記する。
4. 「トレンド判定」が「データ不足」の銘柄は、初回実行による参考値であることを必ず注記する。
5. センチメントが `negative` の銘柄は見送り候補として触れてよいが、推奨はしない。
6. 末尾に「これはPER/PBRと決算短信の文言トーンを組み合わせた機械的スコアリングであり、投資判断はご自身の判断で行ってください」旨を一言添える。

## 主なオプション（value-screener.py）

| オプション | デフォルト | 説明 |
|---|---|---|
| `--codes` | 必須 | 証券コード（カンマ区切り、コードのみ・会社名不可） |
| `--history-limit` | 4 | 蓄積する履歴の最大件数 |
| `--lookback-days` | 45 | TDnetを何日遡って探すか |
| `--export-excel` | なし | 指定した場合のみExcel出力 |
| `--per-max` | 15.0 | バリュー型判定のPER上限 |
| `--pbr-max` | 1.0 | バリュー型判定のPBR上限 |

## 重要な前提・注意

- **手動実行のみ**。無人実行（タスクスケジューラ等）には組み込まない。`claude -p`呼び出しに数十秒〜数分かかるため
- **TDnetは直近31日程度しか開示を遡れない**。過去分は取得できず、実行のたびに`value_screener_data/{コード}.json`へ1件ずつ自前で蓄積する方式。決算発表シーズン外は「見つかりませんでした」になるのが正常
- **トレンド判定は初回「データ不足」になる**。同じ銘柄で決算のたびに実行を重ねることで2〜4回目以降にトレンドが出る
- **大型株・金融持株会社は決算短信に本文が無く外部説明会資料への参照のみのことがある**。その場合は先頭の数値サマリーにフォールックしてスコアリングする旨の警告が出る（バグではない、既知の仕様）
- 対象コードは4桁の証券コードのみ対応（会社名検索は未実装、ユーザーの判断で見送り済み）

## 動作確認済みの検証コマンド

```bash
python -m py_compile scripts/value-screener.py scripts/notified-stock-score.py
```
exit 0 であること。実データでの動作確認は2026-08-04（TDnet日別一覧・PDF抽出・claude -pスコアリング・Excel出力）、
2026-08-09（notified-stock-score.pyによるpicks-log.tsv抽出・yfinance再スコア評価）にそれぞれ実施済み。
