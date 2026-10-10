# P-ASES移行 Implementation Contract — 親Issue #26

<!-- heading-map:start -->
**見出しマップ（自動生成）**

- [1. Repository Baseline](#1-repository-baseline)
- [2. Architecture Decisions](#2-architecture-decisions)
- [3. Exact Change Set](#3-exact-change-set)
- [4. Implementation Sequence](#4-implementation-sequence)
- [5. Required Runtime Semantics](#5-required-runtime-semantics)
- [6. Non-goals / Forbidden Changes](#6-non-goals-forbidden-changes)
- [7. Concrete Tests](#7-concrete-tests)
- [8. Verification](#8-verification)
- [9. Reviewer Checklist](#9-reviewer-checklist)
- [10. Completion Report](#10-completion-report)

<!-- heading-map:end -->

Repository: https://github.com/puchinya/ai-agent-workflow
Owning Issue: https://github.com/puchinya/ai-agent-workflow/issues/26
Baseline: main `1689d74aa356dba784fb8695aa000f2df09dcd96`（実行時更新確認）
Target release: 指定なし。推測しない。
Status: **実行引き継ぎ**。Codexはまず子Issue/子ADCを作成する。ユーザーの指定と重大な矛盾がなければ再承認確認は不要。

> This document is an Implementation Contract. Do not redesign the architecture during implementation. If a requirement conflicts with repository reality or requires a material design change, do not silently choose an alternative. Report the exact conflict and continue only with independent valid work.

## 1. Repository Baseline

- 現行: `runtime/agent_workflow/` Python 3.10+ stdlib-only CLI、10 Skills、3ホスト配布、旧Phase。主な正本は `docs/specs/{workflow-spec,runtime-spec,distribution-spec}.md` と対応する `docs/design/`。テストは `tests/test_runtime.py`。
- 契約処理 `contracts.py::{validate_contract_structure,publish_contract,verify_contract,parse_pointer}`、文書処理 `documents.py::{REQUIRED_HEADINGS,validate_markdown_file,resolve_document_impact}`、実行 `execution.py::prepare_implementation`、証拠 `verification.py::verify_final`、判定 `delivery.py::_check_passed,delivery_check`、レビュー `review.py` を確認。
- 現行 `_check_passed` は `skipped`/`neutral` を許容するため優先修正。`tools/build_dist.py::EXPECTED_SKILLS` と `tools/validate_dist.py::SKILLS` は旧集合。
- 今回のIssueは親で、Codexが実施可能な子単位のADCを分割し、子ごとにPRを作る。ベース更新/既存Issue・PRの重複は実行時に確認。

## 2. Architecture Decisions

- 正規製品名/CLI/Python package/16 Skillは [06-architecture](06-architecture.md) に固定し、旧API互換は不要。現行GitHub repository名は変えない。
- 起案2方式・受領file/chat/Issue・実行許可の境界・親子DAGは [02-adc-and-issues](02-adc-and-issues.md) に固定。
- 正規の工程、親子Issue phase、Review ReadinessとFinal Deliveryは [01-workflow](01-workflow.md) に固定。仕様確定→設計確定は必須の意味的依存。
- 正本分離は [03-documentation](03-documentation.md)。Verification Oracle、証拠同一性とRequired Checkは [04-verification](04-verification.md)。User Reviewは [05-user-review](05-user-review.md)。
- 却下: 独立AIレビューをUser Reviewと呼ぶこと、スキップをsuccess扱いすること、Chat承認でGitHub Approvalを偽造すること、親を子PRで自動closeすること、single巨大小PR、旧API互換レイヤ。

## 3. Exact Change Set

- **入口/契約/Issue**: `runtime/p_ases/{__init__,__main__,cli,intake,adc,phases,issue_graph,execution}.py`。公開APIは06のnamespace CLIに統一。ADC comment ID+SHA、子DAG、phase・base凍結を実装。
- **仕様・文書**: `runtime/p_ases/{documents,document_format}.py`、`workflow/standards/{adc,product-specification,technical-design,test-specification,documentation-sync}.md`、`workflow/templates/{adc,product-spec,technical-design,test-spec}-template.md`、`docs/specs/**, docs/design/**, docs/testing/**`。
- **Verification/Review**: `runtime/p_ases/{verification_plan,oracle_trace,evidence_store,verification,acceptance,audits,user_review,delivery}.py`。GitHub境界 `github.py`、Git境界 `git.py`、process `process.py`。Review ReadinessとFinal Deliveryを分離。
- **配布**: 旧10Skill→06の16Skillへ全面置換。`tools/{build_dist,validate_dist}.py`, `adapters/**`, `README.md`, `AGENTS.md`, `CLAUDE.md`, `pyproject.toml`, `.agent/project.json`, `.github/workflows/{ci,release}.yml`、旧 `runtime/agent_workflow/` の削除、新16Skillと全参照整合。生成 `dist/**` はbuilderのみ。
- **テスト**: `tests/test_runtime.py`の旧前提を置換し、`tests/test_{adc_intake,issue_phases,verification_security,user_review}.py` を追加。07の各ケースを必ず検証。

## 4. Implementation Sequence

1. `main`、Issues/PRs、現行specs→design→code→tests→statusを調査。親Issue #26とこの文書の判断を確認し、子Issue分割計画を決定。
2. GitHubネイティブSub-issuesと依存DAGを作成し、子ごとの決定完結ADCを生成・readback。各子は担当REQ-ID、変更ファイル/シンボル、テスト、禁止事項、PR要件を持つ。
3. 最初の子で命名・`p_ases`のCLI・Core ADC/Phase/Intakeを確立し、次の子が依存できるようPR/ユーザーレビューのゲートまで進める。
4. 次の子で仕様/設計/テスト仕様の新標準とMarkdown formatterを確立する。恒久的な規範は `docs/specs`/`docs/design`/`docs/testing`に移し、計画文書をそのまま永続正本と二重化しない。
5. Verification子でOracle→Test→EvidenceとTrusted App ID・CI成功判定を修正。失効・flaky・環境別Acceptanceも対象にする。
6. 実行/PR/Readiness子でexact-head証拠・監査・CIを統合。PR作成後のVerificationとreadiness合否を機械判定する。
7. User Review子でPRコメント/チャット・actor/HEAD・指摘差戻し・承認失効・merge権限分離を実装。親統合子で子merged/closedと親User Reviewを実装。
8. 配布/CLI/docs/テストを整合し、各子PRごとにユーザー最終レビューへ渡す。Mergeは権限が別に与えられるまで保留し、親の統合完了は全子merge後のみ。

## 5. Required Runtime Semantics

- 確定ADCの明示提示は原則即実行（質問が必要な場合は対象を限定して質問）。草案作成依頼は実行しない。
- GitHubコメントはIDでreadbackしpayloadとSHAが一致してからポインタを変更。失敗を勝手にリトライして重複Issue/ADC/PRを作らない。
- 同一worktree/base SHA凍結、clean PR exact HEAD検証、失効した証拠の再利用禁止。素材修正後は依存証拠/自己・独立レビュー/必要なUser Reviewを再実行。
- 文書整形は元のMarkdown H2以下の番号・見出しマップを直接更新し、二度目は無差分。無関係ソース/コメントは変更しない。
- Required Check: 完了かつsuccess、指定GitHub App ID、現行HEAD。skip/neutral、同名status、過去HEAD、発行元不明はPASSとしない。
- User Reviewは本人による明示判断だけで成立。Chatでの証拠出所を検証できなければBLOCKED。Chat承認≠GitHub Approval。merge権限がなければmergeしない。
- 親DAGの循環/重複/欠落/子merge未完は統合失敗。子範囲外判断は親要求へ戻す。

## 6. Non-goals / Forbidden Changes

- GitHubリポジトリ名変更、実装用常駐サーバー、クラウドサービス新設、消費者リポジトリへ勝手に編集、secret公開。
- 現行公開コマンドや過去証跡の互換shim・旧Skill alias、GitHub履歴コメント改変、生成 `dist/**` の手修正。
- 全作業への無条件の文書作成、テスト手順を製品仕様書へ混入、親Issueを子PRのCloses句でclose、最終ユーザーレビューの省略。

## 7. Concrete Tests

- [07-acceptance](07-acceptance.md)のA01〜A04、D01〜D06、V01〜V08、U01〜U07をsetup/action/expectedでテストし、GitHub境界をFakeGitHubで検証。
- コマンド検証だけでなく、既存commit SHA/親ADC SHA/plan SHA/PR HEAD/actorの不一致を操作してfail-closedを確認。
- 文書はformatterを2回実行し差分なし、分割は途中失敗再実行で重複子0、User ReviewはChatとPRコメントで等価な修正ループ。

## 8. Verification

~~~bash
python -m compileall runtime tools tests
python -m unittest discover -s tests -p 'test_*.py'
python tools/build_dist.py
python tools/build_dist.py --check
python tools/validate_dist.py
git diff --check
~~~

- 新CLI Help、文書標準、16Skill・manifest、古い公開名の非存在、現行mainに対する意図外差分がないこともチェック。
- Ubuntu 3.10/3.14・Windows 3.14・macOS 3.14のCI実行結果と未検証環境を正確に区別。
- GitHub readback、CI Required Check、Review Readiness、ユーザー最終レビューは別々に判定し、偽の成功を表示しない。

## 9. Reviewer Checklist

The implementer must self-review every item in this checklist.

<!-- AGENT_REVIEWER_CHECKLIST_V1 -->
- [ ] 親子IssueはネイティブSub-issuesで管理され、各子のADC/REQ/DAG/PRが明示される。
- [ ] P-ASES/ADC/p_ases/16Skill/CLI・manifestが唯一の命名で一致する。
- [ ] 仕様確定→設計確定、製品仕様とテスト仕様の正本分離が維持される。
- [ ] ADCの2起案×3入力、確定ADCの自動実行と例外境界が適合する。
- [ ] Required Checkは成功・Trusted App ID・現行HEADのみで合格する。
- [ ] Oracle→Test→Evidence・実行元・失効・文書Acceptanceが検証される。
- [ ] PR生成→Verification→独立監査→最終User Reviewの順序が正しい。
- [ ] User ReviewのPR/Chat二経路、User承認とGitHub Approvalの分離、失効が機能する。
- [ ] 親のIntegration/最終User Reviewなしにclosed扱いしない。
- [ ] 変更・テスト・未検証・BLOCKED・PR URLを偽りなく報告する。
<!-- /AGENT_REVIEWER_CHECKLIST_V1 -->

## 10. Completion Report

- 変更ファイル、担当子Issue、決定と逸脱、テストコマンドと結果、未検証OS、残課題。
- コミットSHAとpush結果、open/non-draft子PR URL、およびPR本文のown-line `Closes #<child-number>`。
- 子PRのReview Readiness、ユーザー待ち、独立レビューのfresh-context・CI状態、統合ゲートを別々に報告。
- Issue/PR連携やPR作成が認証/権限で詰まった場合は**BLOCKED**とし、発生箇所・API/コマンドの正確なエラーを報告。
- 親IssueのDONEは全子のmerge/closed、統合PASS、親User Review明示承認後だけ。
