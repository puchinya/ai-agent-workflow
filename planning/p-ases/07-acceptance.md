# P-ASES — 受入基準・検証マトリクス

<!-- heading-map:start -->
**見出しマップ（自動生成）**

- [1. ADC受付・作成](#1-adc受付作成)
- [2. 親子Issueと文書](#2-親子issueと文書)
- [3. Verification・安全性](#3-verification安全性)
- [4. User Review・Delivery](#4-user-reviewdelivery)
- [5. 最低限の実行コマンド](#5-最低限の実行コマンド)
- [6. レビューと完了](#6-レビューと完了)

<!-- heading-map:end -->

## 1. ADC受付・作成

| ID | Setup/Action | 期待結果 |
|---|---|---|
| A01 | 同一の確定ADCをfile/chat/Issueで提出 | 3経路で同じ対象と義務を実行し確認質問0件 |
| A02 | ADCなしの直接要求を入力 | 具体化した草案を作成し、未確定のまま実行しない |
| A03 | Review-onlyまたはdraft-onlyと指示 | 実行・push・PRを行わない |
| A04 | ADCが現行repoの不変条件に矛盾 | 独立作業以外を停止して具体的質問を出す |

## 2. 親子Issueと文書

| ID | Setup/Action | 期待結果 |
|---|---|---|
| D01 | 大きな親ADCを3子へ分割 | ネイティブSub-issues、決定済み子ADC、要求配賦漏れ/重複0 |
| D02 | 2子生成後にAPI障害、再実行 | 既存子を再利用し重複作成しない |
| D03 | DAGに依存循環を混入 | 公開前に拒否、親phaseを破壊しない |
| D04 | 仕様変更を伴う設計承認要求 | 仕様確定前のdesign確定を拒否 |
| D05 | 文書だけを採番して再実行 | 2度目差分0、リンク/fragment全保持 |
| D06 | docs-onlyのADCを検証 | オラクルと文書受入証拠が必要、無条件QA N/Aは禁止 |

## 3. Verification・安全性

| ID | Setup/Action | 期待結果 |
|---|---|---|
| V01 | 現HEADにconclusion=skipped/neutralのRequired Check | いずれもFAIL/BLOCKED |
| V02 | Check名が一致しApp IDが違う | PASSを拒否 |
| V03 | 古いHEADに成功Checkが存在 | 現HEADではPASSしない |
| V04 | Planが空、またはrequired targetがskip | Review Readinessを拒否 |
| V05 | Oracle未定義REQが存在 | Acceptance FAIL/CONCERNS、引渡し不可 |
| V06 | テスト結果が修正コードに合わせて変更 | 仕様/Oracleとの不一致を検出 |
| V07 | バグ修正のRED→GREENを検証 | 旧版で失敗、新版で成功する対象テストを確認 |
| V08 | PR HEADまたはADC SHAを変更 | dependent Evidence、独立レビュー、User Reviewをstale |

## 4. User Review・Delivery

| ID | Setup/Action | 期待結果 |
|---|---|---|
| U01 | Readiness未達でPRが存在 | user-reviewへ遷移しない |
| U02 | GitHub PRコメントで修正要求 | 同一PR修正→再Verification→再独立レビュー→再User Review |
| U03 | 直接チャットで修正要求 | PRコメントへの転記なしに同じ修正ループ |
| U04 | チャット承認、GitHub Required Approvalなし | GitHub条件を充足したと偽装しない |
| U05 | AI/bot・過去HEADの承認 | 明示ユーザー承認と扱わない |
| U06 | Merge許可なしでユーザーが承認 | 自動mergeしない |
| U07 | 親の全子未マージ・統合未検証 | 親user-review/closedを拒否 |

## 5. 最低限の実行コマンド

~~~bash
python -m compileall runtime tools tests
python -m unittest discover -s tests -p 'test_*.py'
python tools/build_dist.py
python tools/build_dist.py --check
python tools/validate_dist.py
git diff --check
~~~

現行CIはUbuntu Python 3.10/3.14、Windows Python 3.14、macOS Python 3.14を持つ。新CLIと配布に更新後もこれらを維持。実行していないプラットフォームをPASSと報告しない。

## 6. レビューと完了

子PRそれぞれで全ADCセクション・Reviewer Checklistを証拠付き自己監査、別コンテキスト独立レビュー、Evidence/CIのreadbackを実施。PR本文は `Closes #child-issue` を含む。親Issueは子PRでcloseしない。ユーザー最終承認・merge・親integrationは段階を別に報告。
