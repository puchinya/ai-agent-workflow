# P-ASES — ワークフロー仕様

<!-- heading-map:start -->
**見出しマップ（自動生成）**

- [1. 対象と原則](#1-対象と原則)
- [2. 全体の工程と依存](#2-全体の工程と依存)
- [3. 単独・子Issueの状態](#3-単独子issueの状態)
- [4. 親Issueの状態](#4-親issueの状態)
- [5. Phaseと待機の不変条件](#5-phaseと待機の不変条件)
- [6. 自動実行・例外](#6-自動実行例外)

<!-- heading-map:end -->

## 1. 対象と原則

- 正式名は **Puchinya Agentic Software Engineering System（P-ASES）**。ADCはAgent Development Contractであり、製品仕様・設計・テスト仕様とは異なるIssue単位の開発指示。
- ユーザーの要求を、起案→受領→具体化→開発作業→Verification→独立レビュー→最終ユーザーレビュー→マージ・完了までつなぐ。
- 対象は新規仕様・仕様変更・設計変更・文書整理・バグ修正・テスト改善・品質改善・基盤改修。不要な成果物を作成しない。

## 2. 全体の工程と依存

~~~text
要求・Issue → ADC（確定／公開） → 必要なら子Issueと子ADC
 → 製品仕様の確定（必要時）
 → 設計の確定（必要時）
 → テスト仕様・Oracle・Verification Planの確定（必要時）
 → 成果物の作成 → Commit/Push/PR作成
 → PR exact-HEAD Verification・Acceptance・自己監査・独立レビュー・Required Checks
 → Review Readiness → User Review（PRコメント／チャット）
 → 明示的ユーザー承認 → 明示的merge権限・GitHubゲート → merge → Issue closed
~~~

仕様変更を伴う場合、**仕様内容の確定は設計内容の確定に先行**する。これは意味上の依存順序であって全編集操作の時系列を固定するものではない。設計中に仕様変更が判明したら仕様の判断へ差し戻す。

## 3. 単独・子Issueの状態

`requirements → [specification] → [design] → ready → execution → verification → user-review → closed`。

- `requirements`: ADCの具体化・確定。確定ADCの提出は原則として実行指示。
- `specification`: 必要な製品仕様を確定。`design`: 確定した仕様から設計を確定。不要時は根拠付きで省略。
- `ready`: 必要な技術判断とVerificationのオラクルが定義済み。
- `execution`: ADCが指定した変更作業・commit・push・PR作成。
- `verification`: PR HEADに束縛したVerification、Acceptance、ADC自己監査、独立レビュー、必須CIを確認。
- `user-review`: 最終ユーザーのフィードバック・承認。修正時はexecutionへ戻り再検証。
- `closed`: 実際のGitHub Issue closed。`phase:closed`ラベルは禁止。

## 4. 親Issueの状態

`requirements → ready → execution → integration → user-review → closed`。親は全体要求・子集合・DAG・統合Acceptanceを所有し、通常PRを持たない。子PRのmergeとIssue closeが完了するまで親integrationをPASSとしない。親のUser Reviewは親Issueコメントまたはチャット。

## 5. Phaseと待機の不変条件

- Open Issueは `phase:requirements|specification|design|ready|execution|verification|user-review|integration` のいずれか1件だけ付与。
- 待機は `attention:waiting-user|blocked|waiting-dependency` を別に付与して工程を失わない。
- 実行中のHEAD/ADC/Plan変更は該当証跡と承認を失効。PRが作られただけではUser Reviewへ進めない。
- `Review Readiness` と `Final Delivery` は別。前者で最終レビュー開始可能、後者はユーザー承認とGitHubルールを別途要求。

## 6. 自動実行・例外

- 明示提示された確定ADCに重大な未決定・矛盾・権限不足がなければ追加確認なく作業開始。草案作成だけ、レビューだけの明示指示では実行しない。
- 重大な矛盾は質問し、影響外の独立作業のみ継続。GitHub権限昇格、破壊的Git操作、merge/releaseは追加許可が必要。
- 親ADC承認範囲内で子Issue・子ADCを自動生成できるが、親範囲外の判断を委譲しない。
