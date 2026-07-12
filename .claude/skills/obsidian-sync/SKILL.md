---
name: obsidian-sync
description: ObsidianVault（C:\Users\shige\Documents\ObsidianVault）の変更をcommitしてGitHub（shgierumaorina/ObsidianVault, private）にpushする
---

# Obsidian Vault sync

Vault: `C:\Users\shige\Documents\ObsidianVault`
Remote: `https://github.com/shgierumaorina/ObsidianVault.git`（private, branch: `main`）

Obsidian内のGitプラグイン（obsidian-git）と同じリポジトリを操作する。二重管理にならないよう、以下の手順のみ行う。

## 手順

Bashツールで実行する（パスは `/c/Users/shige/Documents/ObsidianVault`）:

1. **状態確認**: `git status --porcelain` で変更の有無を見る。変更ゼロなら「変更なし、pushのみ確認」に進む。
2. **pull（rebase）**: 他端末やObsidian側のcommitと衝突しないよう、先に `git pull --rebase origin main`。
   コンフリクトが出たら自動解決せず、そのまま中断してユーザーに報告する。
3. **commit**: `git add -A` → `git commit -m "vault: sync YYYY-MM-DD HH:MM"`（日時は実行時刻）。
4. **push**: `git push origin main`。認証はGit Credential Manager（保存済み）が処理する。
5. **検証（必須）**: 以下が exit 0 で "DONE" を出力した場合のみ完了と報告する。

```bash
set -e
V="/c/Users/shige/Documents/ObsidianVault"
test -z "$(git -C "$V" status --porcelain)"
test "$(git -C "$V" rev-parse main)" = "$(git -C "$V" rev-parse origin/main)"
echo "DONE"
```

## 注意

- `.obsidian/workspace.json` は `.gitignore` 済み。gitignoreを変更しない。
- Vault内のノート内容を編集・削除しない。同期のみ。
- force push禁止。rebase/pushが失敗したら出力をそのまま報告して止まる。
