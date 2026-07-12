---
name: work
description: GitHub Issueを読み込み、実装・テスト・修正を繰り返す
argument-hint: "[issue-number]"
disable-model-invocation: true
allowed-tools: Bash(gh *), Bash(git *), Bash(python *), Bash(pytest *), Bash(mypy *), Read, Write, Edit, Glob, Grep
---

GitHub Issue $ARGUMENTS を処理してください。

1. `gh issue view $ARGUMENTS`で内容を取得する。
2. 関連ファイルと`CLAUDE.md`を読む。
3. 実装計画を短く作る。
4. 必要な変更とテストを実装する。
5. `python verify_code_quality.py`を実行する。
6. 失敗した場合は原因を分析し、最大5回まで修正を繰り返す。5回失敗したら停止し、最後のエラー出力をそのまま報告する。
7. 成功後に変更内容と検証結果を報告する。
8. 明示的な許可がある場合のみ、Issueを閉じてコミットする。
