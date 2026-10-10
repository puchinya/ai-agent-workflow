# P-ASES — Codex実行引き継ぎ文書

<!-- heading-map:start -->
**見出しマップ（自動生成）**

- [1. 文書の読み順と責務](#1-文書の読み順と責務)
- [2. 文書の正本と重複排除](#2-文書の正本と重複排除)
- [3. Codexへの入口](#3-codexへの入口)

<!-- heading-map:end -->

> **対象**: [親Issue #26](https://github.com/puchinya/ai-agent-workflow/issues/26)。これらは計画ブランチの開発正本候補であり、現行mainに適用済みの仕様ではない。
> **対象HEAD（調査時）**: `1689d74aa356dba784fb8695aa000f2df09dcd96`。実行時に再取得する。

## 1. 文書の読み順と責務

| 順 | ファイル | 一義的な責務 |
|---|---|---|
| 1 | [01-workflow.md](01-workflow.md) | フェーズと全体の状態遷移 |
| 2 | [02-adc-and-issues.md](02-adc-and-issues.md) | ADC受付、承認、親子Issue・子ADC |
| 3 | [03-documentation.md](03-documentation.md) | 製品仕様・設計・テスト仕様の正本と順序 |
| 4 | [04-verification.md](04-verification.md) | Verification計画、証跡、CI信頼条件 |
| 5 | [05-user-review.md](05-user-review.md) | 最終ユーザー確認・修正・承認 |
| 6 | [06-architecture.md](06-architecture.md) | 16 Skill、CLI、ランタイム境界、名称 |
| 7 | [07-acceptance.md](07-acceptance.md) | 横断的な受入ケースと検証コマンド |
| 8 | [08-migration-contract.md](08-migration-contract.md) | Codexへの決定済み移行Implementation Contract |

## 2. 文書の正本と重複排除

- 01〜05はシステムの**必要な動作・制約**、06は**採用済みアーキテクチャ・公開名称**、07は**検証条件**、08は**今回のIssueで実施する変更義務**を所有する。
- 実装時、恒久規則を `docs/specs/`、技術設計を `docs/design/`、テスト仕様を `docs/testing/`、Skill/標準を `workflow/` に振り分ける。移行指示を永続仕様の正本として複製しない。
- 規範の変更は正本と依存先の整合を更新する。変更により重要な設計判断が変わる場合だけIssueで質問する。

## 3. Codexへの入口

1. [Issue #26](https://github.com/puchinya/ai-agent-workflow/issues/26)と[移行Contract](08-migration-contract.md)を読む。
2. `main`の最新仕様・実装・テスト・Issue/PRを調査する。
3. 最初に子Issue分割案・要求割当・依存DAGを確定し、GitHubネイティブSub-issuesと固有の子ADCを生成する。
4. 子ごとに仕様→設計→テスト仕様→作業→PR→Verification→User Reviewを完遂する。mergeはユーザーの別許可まで行わない。
