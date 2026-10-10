# P-ASES — Verificationと証跡仕様

<!-- heading-map:start -->
**見出しマップ（自動生成）**

- [1. Verificationの目的](#1-verificationの目的)
- [2. Verification PlanとOracle](#2-verification-planとoracle)
- [3. Verificationの証跡モデル](#3-verificationの証跡モデル)
- [4. Required Checksの信頼条件](#4-required-checksの信頼条件)
- [5. 実行・保存と失効](#5-実行保存と失効)
- [6. 成果物ごとのAcceptance](#6-成果物ごとのacceptance)
- [7. 判定](#7-判定)
- [8. セキュリティと誤認防止](#8-セキュリティと誤認防止)

<!-- heading-map:end -->

## 1. Verificationの目的

Verificationは単なるコマンド終了コードの記録ではなく、**確定した要求を、妥当なOracle・テスト・実行証拠で満たしたことの確認**。実装結果から期待値を逆算してはならない。

## 2. Verification PlanとOracle

テスト仕様・製品仕様を入力としてVerification Planを確定する。各規範REQ-IDに適格なOracle-ID、Test-ID、環境・対象、実行コマンド、Acceptance条件、リスクレベル、Evidenceを割り当てる。重要な不具合修正は修正前RED→修正後GREENを実証し、単に「例外なし」は十分なテストとしない。

## 3. Verificationの証跡モデル

証跡の必須同一性: `{repository, issue, pr, adc_comment_id, adc_sha256, plan_sha256, exact_pr_head_sha40, command/test_identity, environment, runner_source, outcome, evidence_digest}`。個々のテスト成否・skipped・failed・flakyを区別する。CI provenance、テスト数、入力・実行時刻・対象プラットフォームを可能な限り保持し、秘密値と全文ログは公開しない。

## 4. Required Checksの信頼条件

- 指定されたGitHub Checkの**job name、GitHub App ID、PR現HEAD、`status=completed`、`conclusion=success`**が一致した場合だけPASS。
- `skipped`, `neutral`, cancelled, timed_out, stale, provenance未知はPASSではない。レガシー同名Commit Statusで代替しない。
- `required_checks=[]`はFAIL-CLOSED。GitHubチェックの不在を成功としない。fork/外部ジョブは明示的に信用ポリシーへ追加しない限り不可。
- 現行 `runtime/agent_workflow/delivery.py::_check_passed` がskipped/neutralを通すのはP0修正対象。

## 5. 実行・保存と失効

- `PR` はVerification開始前にopen/non-draftとして存在し、ローカルHEAD=PR HEADかつclean worktreeが必要。実行前後のHEADが違えば失敗。
- 結果コメントは発行→Comment ID readback→payload SHA確認→最新状態再検査→pointer更新→readback。失敗をPASSに見せない。
- PR HEAD、ADC SHA、Verification Plan、重要なSpec/Oracle、Required Check setが変わった場合は影響するEvidence・自己/独立レビュー・User Reviewを失効。再検証を実施。
- 実行再試行は成功だけを残して失敗履歴を消す設計にしない。flakyはCONCERNS/BLOCKEDに分類して追跡。

## 6. 成果物ごとのAcceptance

| 作業 | 必須の確認 |
|---|---|
| 新規仕様/変更 | 対象REQ-IDの完備・受入基準・トレーサビリティ |
| 設計変更 | 仕様維持、依存・所有権・故障時動作の整合 |
| バグ修正 | 再現条件、修正前失敗、修正後PASS、回帰 |
| 文書整理 | 規範内容不変・リンク/見出し/IDの整合 |
| テスト改善 | テストが実際に欠陥を検出できるOracle検証 |
| 機能/GUI | 自動・手動の適格な実機/E2E証拠、未検証環境明示 |

## 7. 判定

`PASS`, `CONCERNS`, `FAIL`, `BLOCKED` の4状態。未実行・空計画・重要skip・証拠不足はPASSでない。Review Readinessは必須Verification/Acceptance/自己監査/独立レビュー/Required Checksがすべて適格なPASSのときのみPASS。

## 8. セキュリティと誤認防止

GitHubチェックはTrusted App IDを定義し、同名チェック/トークンによる偽装を認めない。独立レビューのfresh-contextは宣誓だけで実行元を証明できないため、確かめられない出所を推測しない。CIの成功と実機プラットフォーム確認を混同しない。
