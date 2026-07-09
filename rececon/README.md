# レセコンMVP

`docs/レセコン詳細設計書.md` に基づくコア業務フローのMVP実装（Python標準ライブラリのみ、外部依存なし）。

## 実装範囲

| モジュール | 内容 | 詳細設計書対応 |
|---|---|---|
| `rececon/db.py` | SQLiteスキーマ（患者/保険/診療/算定/会計/レセプト/監査） | 3章 |
| `rececon/patient.py` | 患者登録（重複・類似検知）、保険資格（有効期間管理） | 4.1 |
| `rececon/encounter.py` | 診療イベント、診療行為（source_refによる冪等取込） | 4.2 |
| `rececon/calculator.py` | 算定エンジンIF＋スタブ（10円未満四捨五入の負担金計算） | 5.1 |
| `rececon/billing.py` | 算定実行（履歴保持）、会計・収納 | 4.3 |
| `rececon/receipt.py` | 月次レセプト生成（チェック→生成→billed遷移）、UKE簡易出力 | 4.4 |
| `rececon/audit.py` | 監査ログ | 8.1 |

## 本実装のスタブ・簡略化箇所（本番開発で差替え）

- **共通算定モジュール**：`SimpleCalculator`（単純積算）で代替。製品版API公開後に `Calculator` IF実装を追加（詳細設計書 T-01）
- **UKE形式**：簡易プレースホルダ形式（RE/HO/SI/GOのカンマ区切り）。電子レセプト作成手引き準拠版はレコードビルダー差替えで対応
- **テナント分離・認証・外部連携（オン資格等）**：本MVPは単一テナント・ローカル実行。詳細設計書2章・5章に基づき別途実装
- **公費・入院・返戻再請求**：未実装（次イテレーション）

## 実行方法

```bash
cd rececon

# デモシナリオ（受付→診療→算定→会計→レセプト生成）
python -m rececon.demo

# テスト
python -m unittest discover tests -v
```
