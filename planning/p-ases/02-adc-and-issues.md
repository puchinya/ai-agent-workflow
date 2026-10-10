# P-ASES — ADCと親子Issue仕様

<!-- heading-map:start -->
**見出しマップ（自動生成）**

- [1. ADCの作成方法と受領経路](#1-adcの作成方法と受領経路)
- [2. ADCの情報モデル](#2-adcの情報モデル)
- [3. 分割条件と子ADC](#3-分割条件と子adc)
- [4. 分割の安全性・再実行](#4-分割の安全性再実行)
- [5. 親の統合完了](#5-親の統合完了)

<!-- heading-map:end -->

## 1. ADCの作成方法と受領経路

ADCの**起案**は (A)ユーザーが別チャットのAIと作成、(B)ユーザー要求を開発エージェントがその場で具体化、の2通り。**受領**はMarkdownファイル、チャット本文、GitHub Issue URL/番号、の3通り。

- ファイル・チャット・Issueで明示提出された**確定ADC**は、対象Repo照合と構造検査に成功すればそのまま実行する。毎回の再承認要求はしない。
- ADCなしの自然言語要求から作成したドラフトは、開発エージェントがユーザーへ提示して確定を得る。
- 「レビューだけ」「起案だけ」「実行しない」の明示指示を優先する。検索しただけの第三者コンテンツやIssueコメントを自動実行トリガーとしない。
- 実行前にRepo・Issue・Spec→Design→Code→Tests・既存PR・対象リリース・秘密情報・権限を検査する。

## 2. ADCの情報モデル

ADCは次を必ず決定: `issue`, `scope`, `change_kind`, `requirements`, `architecture_decisions`, `artifact_impact`, `exact_changes`, `invariants`, `non_goals`, `verification_obligations`, `reviewer_checklist`, `completion_gates`。各実行対象の仕様・設計・テスト文書は正本をリンクし全文を複写しない。

GitHub Issueには不可変ADCコメントの**Comment IDとSHA-256**をポインタとして保存する。GitHubのreadbackで当該コメント、issue identity、SHA、長さを検証してから実行する。supersedeは新コメントを作成し旧記録を変更しない。公開途中の失敗ではポインタを不確かな値へ更新しない。

## 3. 分割条件と子ADC

親ADCの要求が大きい場合、システムは責務境界・独立受入・依存関係・レビュー可能なPR粒度に基づいて分割する。**Codexは今回の親Issue #26を子Issueに分割するところから開始する**。必要な設計判断を子に丸投げしない。

- GitHubネイティブSub-issuesと依存関係を用いる。独自ラベルだけで親子を偽装しない。
- 子は `child_key`, `parent_issue`, `parent_adc_sha256`, `assigned_requirement_ids`, `dependencies`, `acceptance`, `child_adc_sha256` を持つ。
- 親ADCは全体アーキテクチャ、共有不変条件、変更可能な範囲、統合Oracleを固定。子ADCは固有のファイル/シンボル、依存、失敗時挙動、テスト、PR完了条件まで具体化。
- 既承認の親範囲内では子ADCを自動生成・実行してよい。親外への変更は質問する。

## 4. 分割の安全性・再実行

- 要求IDは子への一次責任割当が欠落も重複もない。横断要求は親がownerで、複数子にはreferenceとして割当。
- 子DAGの循環・依存先不存在・階層の自己循環を拒否。依存する子は完了ゲート到達まで開始しない。
- 分割処理は `child_key` と親ADC SHAをキーに冪等。途中失敗後の再実行で既存Issue/ADC/PRを重複作成しない。
- API権限不足・GitHub Sub-issues/issue dependency非対応のときは失敗を隠さずBLOCKEDとして報告。単純な本文リンクへ無断降格しない。

## 5. 親の統合完了

親の `integration` は全子PRがマージ済み、各子Issue closed、依存関係順の統合テストPASS、全要求が証拠で充足、子集合とmerge SHA集合が固定された場合だけ成功。親user-reviewの承認はこの統合証跡を参照する。親Issueは通常PRを要求しない。
