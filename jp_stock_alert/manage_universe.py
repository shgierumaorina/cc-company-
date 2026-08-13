"""監視リスト(watchlist.json)管理CLI
使い方:
  python manage_universe.py add 7203
  python manage_universe.py remove 7203
  python manage_universe.py list
"""
import sys
import io
import argparse
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import universe_manager as um


def cmd_add(code: str) -> None:
    watchlist = um.load_watchlist()
    master = um.load_master()
    master_entry = next((m for m in master if m["code"] == code), None)
    if master_entry is None:
        print(f"[警告] {code} は優良銘柄マスタに未登録です（rescreen.py未実行、または基準未達）。監視リストには追加しますが、シグナル検知の3条件目（マスタ登録）を満たさないため通知対象にはなりません。")
        name = ""
    else:
        name = master_entry.get("name", "")

    watchlist, added = um.add_to_watchlist(watchlist, code, name)
    if not added:
        print(f"[SKIP] {code} は既に監視リストにあります")
        return
    um.save_watchlist(watchlist)
    print(f"[OK] {code} {name} を監視リストに追加しました")


def cmd_remove(code: str) -> None:
    watchlist = um.load_watchlist()
    watchlist, removed = um.remove_from_watchlist(watchlist, code)
    if not removed:
        print(f"[SKIP] {code} は監視リストにありません")
        return
    um.save_watchlist(watchlist)
    print(f"[OK] {code} を監視リストから削除しました")


def cmd_list() -> None:
    watchlist = um.load_watchlist()
    master = {m["code"]: m for m in um.load_master()}
    if not watchlist:
        print("監視リストは空です")
        return
    print(f"監視リスト（{len(watchlist)}銘柄）")
    for w in watchlist:
        m = master.get(w["code"])
        if m is None:
            status = "マスタ未登録"
        else:
            status = f"score={m['score']} passed={m['passed']}"
        print(f"  {w['code']} {w.get('name', '')} [{status}]")


def main():
    parser = argparse.ArgumentParser(description="監視リスト管理CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="監視リストに銘柄コードを追加")
    p_add.add_argument("code", help="4桁の銘柄コード 例: 7203")

    p_remove = sub.add_parser("remove", help="監視リストから銘柄コードを削除")
    p_remove.add_argument("code", help="4桁の銘柄コード")

    sub.add_parser("list", help="監視リストを表示")

    args = parser.parse_args()
    if args.command == "add":
        cmd_add(args.code)
    elif args.command == "remove":
        cmd_remove(args.code)
    elif args.command == "list":
        cmd_list()


if __name__ == "__main__":
    main()
