---
name: value-screener
description: TDnetの決算短信を取得しclaude -pでセンチメントをスコアリング、バリュー指標(PER/PBR)と組み合わせてExcel出力する。出来高急増銘柄と連携して「今日の急増銘柄の決算センチメント」も確認できる。手動実行専用（stock-screener.pyの無人デイトレフローとは独立）
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
python -m py_compile scripts/value-screener.py
```
exit 0 であること。実データでの動作確認は2026-08-04に実施済み（TDnet日別一覧・PDF抽出・claude -pスコアリング・Excel出力すべて実機テスト済み）。
