"""ObsidianVaultへの記録
- 通知: wiki/log.md に追記（新しいエントリを先頭に。vaultのCLAUDE.md規約「追記専用、新しいエントリは常に先頭」に従う）
- 優良銘柄マスタ: wiki/japan-stock.md に日付セクションを追記（既存セクションは上書きしない。過去データを消さない）
vault側の書き込み失敗・想定外の入力形式のいずれでも、Discord通知・rescreenの本処理は継続させるため
公開関数は例外を一切送出せず警告を出すのみ(関数本体全体をtryで囲む)。
"""
import re
from datetime import datetime
from pathlib import Path

import yaml

LOG_NOTE = "wiki/log.md"
JAPAN_STOCK_NOTE = "wiki/japan-stock.md"


def _vault_path(cfg: dict) -> Path | None:
    ob = cfg.get("obsidian", {})
    if not ob.get("enabled"):
        return None
    path = Path(ob["vault_path"])
    if not path.exists():
        print(f"[警告] Obsidian Vaultが見つかりません: {path}（記録をスキップします）")
        return None
    return path


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """先頭の```---\\nYAML\\n---```フロントマターとそれ以降の本文を分離する。フロントマターが無ければ空dictを返す。"""
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    fm = yaml.safe_load(m.group(1)) or {}
    return fm, m.group(2)


def _join_frontmatter(fm: dict, body: str) -> str:
    if not fm:
        return body
    yaml_text = yaml.dump(fm, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{yaml_text}\n---\n{body}"


def record_notification(cfg: dict, code: str, name: str, result: dict) -> None:
    """Discord通知1件をwiki/log.mdの先頭に追記する。
    vault未設定・書き込み失敗はもちろん、result/cfgの形が想定と違う場合の例外も含めて
    ここで完結させ、呼び出し元(Discord送信本体)には一切伝播させない。
    """
    try:
        vault = _vault_path(cfg)
        if vault is None:
            return

        now = datetime.now()
        vs = result["volume_surge"]
        lp = result["low_price"]
        dev = lp["checks"].get("ma_deviation", {}).get("value")
        w52 = lp["checks"].get("week52_low", {}).get("value")
        detail = []
        if dev is not None:
            detail.append(f"25/75日線乖離{dev:+.1f}%")
        if w52 is not None:
            detail.append(f"52週安値+{w52:.1f}%")
        detail_str = "・".join(detail) if detail else "-"

        line = (f"- {now.strftime('%Y-%m-%d %H:%M')}: [[japan-stock]] {name}({code}) が"
                f"優良銘柄×安値圏×出来高急増でDiscord通知（"
                f"価格{result['price']:,.0f}円、出来高比{vs['ratio']}倍、{detail_str}）"
                f" #jp_stock_alert")

        note_path = vault / LOG_NOTE
        if note_path.exists():
            fm, body = _split_frontmatter(note_path.read_text(encoding="utf-8"))
        else:
            fm, body = {}, "\n# Log\n\n## ログ\n"
        if not fm:
            # フロントマターが無い(新規ファイル、または既存ファイルが規約に反して欠落)場合は
            # vaultのCLAUDE.md規約(type/status/created/tags必須)通りに補う
            fm = {"type": "log", "status": "active", "created": now.strftime("%Y-%m-%d"), "tags": ["log"]}

        fm["updated"] = now.strftime("%Y-%m-%d")

        heading_marker = "## ログ\n"
        idx = body.find(heading_marker)
        if idx == -1:
            body = body.rstrip() + "\n\n## ログ\n" + line + "\n"
        else:
            insert_at = idx + len(heading_marker)
            body = body[:insert_at] + line + "\n" + body[insert_at:]

        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(_join_frontmatter(fm, body), encoding="utf-8")
        print(f"[OK] ObsidianVault {LOG_NOTE} に通知記録を追記しました")
    except Exception as e:
        print(f"[警告] ObsidianVaultへの通知記録に失敗しました: {e}")


def record_quality_stocks(cfg: dict, passed_entries: list[dict]) -> None:
    """rescreen.pyで優良銘柄マスタに通過した銘柄を wiki/japan-stock.md に日付セクションとして追記する。
    既存セクションは変更しない（過去のスクリーニング記録を上書きしない）。
    vault未設定・書き込み失敗はもちろん、passed_entriesの形が想定と違う場合の例外も含めて
    ここで完結させ、呼び出し元(rescreenの本処理)には一切伝播させない。
    """
    try:
        vault = _vault_path(cfg)
        if vault is None or not passed_entries:
            return

        now = datetime.now()
        rows = []
        for e in sorted(passed_entries, key=lambda x: -x["score"]):
            m = e["metrics"]
            rows.append(
                f"| {e['code']} | {e['name']} | {e['score']} | "
                f"{_fmt_pct(m.get('roe_pct'))} | {_fmt_pct(m.get('equity_ratio_pct'))} | "
                f"{_fmt_growth(e['trend'])} | {_fmt_pct(m.get('payout_ratio_pct'))} |"
            )

        section = (
            f"\n## jp_stock_alert 優良銘柄マスタ — {now.strftime('%Y-%m-%d')}\n\n"
            f"`jp_stock_alert/rescreen.py` によるirbank.netスコアリングで優良銘柄マスタ"
            f"（100点満点、閾値{cfg['universe']['score_pass_threshold']}点）に通過した銘柄。\n\n"
            f"| コード | 銘柄 | スコア | ROE | 自己資本比率 | 増収増益 | 配当性向 |\n"
            f"|---|---|---|---|---|---|---|\n"
            + "\n".join(rows) + "\n\n"
            f"### 出典\n- `jp_stock_alert/rescreen.py`（irbank.net、{now.strftime('%Y-%m-%d')}時点）\n"
        )

        note_path = vault / JAPAN_STOCK_NOTE
        if note_path.exists():
            fm, body = _split_frontmatter(note_path.read_text(encoding="utf-8"))
        else:
            fm, body = {}, "\n# Japan Stock\n"
        if not fm:
            fm = {"type": "note", "status": "active", "created": now.strftime("%Y-%m-%d"),
                  "tags": ["japan-stock", "screening", "finance"]}

        fm["updated"] = now.strftime("%Y-%m-%d")
        body = body.rstrip() + "\n" + section

        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(_join_frontmatter(fm, body), encoding="utf-8")
        print(f"[OK] ObsidianVault {JAPAN_STOCK_NOTE} に優良銘柄マスタ({len(passed_entries)}件)を追記しました")
    except Exception as e:
        print(f"[警告] ObsidianVaultへの優良銘柄記録に失敗しました: {e}")


def _fmt_pct(v) -> str:
    return f"{v:.1f}%" if v is not None else "-"


def _fmt_growth(trend: dict) -> str:
    rg, og = trend.get("revenue_growth"), trend.get("op_income_growth")
    if rg is None or og is None:
        return "データ不足"
    if rg and og:
        return "増収増益"
    if rg:
        return "増収"
    if og:
        return "増益"
    return "減収減益"
