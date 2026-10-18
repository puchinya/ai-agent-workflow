# Implementation Contract — Issue #63 / PR #64 最終実行順序（後続ADC承認方針）

作成日: 2026-10-17
Repository: `puchinya/ai-agent-workflow`
Issue: [#63](https://github.com/puchinya/ai-agent-workflow/issues/63)
既存実装PR: [#64](https://github.com/puchinya/ai-agent-workflow/pull/64)
確認時HEAD: `2910d49602ce512ef123fb58d722ec755bb76c2c`（実行時に再取得する）

<!-- contents:start -->
**Contents**
- [1 Repository Baseline](#1-repository-baseline)
- [2 Architecture Decisions](#2-architecture-decisions)
  - [2.1 Issue #63 の二段階完了順序](#21-issue-63-の二段階完了順序)
- [3 Exact Change Set](#3-exact-change-set)
- [4 Implementation Sequence — 必ずこの順](#4-implementation-sequence-必ずこの順)
- [5 Required Runtime Semantics](#5-required-runtime-semantics)
- [6 Non-goals / Forbidden Changes](#6-non-goals-forbidden-changes)
- [7 Concrete Tests](#7-concrete-tests)
- [8 Verification](#8-verification)
- [9 Reviewer Checklist（実装開始前に公開）](#9-reviewer-checklist実装開始前に公開)
- [10 Completion Report](#10-completion-report)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
<!-- heading-map:end -->


## 1 Repository Baseline

- Ownerの最新指示はPRコメント #6243550895。通常のPR associationは従来どおり独立行`Closes #N`で、自動close後にIssueをreadbackする。後工程が残る今回のIssue #63 / PR #64だけは`Refs #63`とし、順序は**実装完了 → 後続ADC正式化 → Phase receipts → #64通常ゲート/merge（Issue OPEN）→ Activation V2 Setup PR/`ACTIVE` → Issue #63 close**。以前の「Activation `ACTIVE`を#64 merge前に要求する」記述を置き換える。
- Ownerは後続ADCを承認する意向を明示した。ただし承認対象は最終順序を反映して確定した**正確なADCバイト列とSHA-256**でなければならない。新SHAが未提示・未照合の間、現行草案の曖昧な承認を `ADC_SUPERSEDE` の実行証跡に変換してはならない。後続ADCの正式化はActivationより先に完了させる。
- #64はOPEN、Issue #63はOPEN / `phase:requirements`。確認時点の現HEAD・CI・test数は実行ごとにghでreadbackし、古いCIやPRコメントの報告値を現在の証拠として再利用しない。コード検証は実運用Activationが成功したことを意味しない。
- 現行pointer journal上のapproved predecessor: ADC comment `#6244160653`, SHA `f1cab9b9edca34d4e80c486642059881b62abd5d95b993999a52494494bafac8`; pointer record comment `#6244160966`。その不変本文は `Draft only` と `successor-draft` を名乗るがjournal stateはapproved。この矛盾を編集・遡及解釈しない。新しいcanonical candidateは `docs/contracts/issue-63-successor-adc-final.md`; `issue-63-successor-adc-draft.md` は履歴用に保持する。新規approved publishはfinal-content/current-predecessor preflightを通し、exact bytesを別途承認する。
- #57のV1 Activationは残存。#57にはまだRuleset plan承認、`PASES_RULESET_APPLIED_V1`、`PASES_CONSUMER_ACTIVATION_V2` の実証済み記録がない。
- 根拠: `docs/specs/workflow-spec.md` REQ-F01-008/009/011/013/014/015、`docs/design/workflow-design.md` DES-F01-011/013/014/015、`runtime/p_ases/consumer_activation.py::{setup_consumer_activation,verify_and_record_activation}`、`runtime/p_ases/adc.py::{publish_adc,verify_adc}`、`runtime/p_ases/phase_rebaseline.py::rebaseline_issue_phase`、`runtime/p_ases/work.py::ensure_pull_request`。

## 2 Architecture Decisions

1. **後続ADCをActivationより先に正式化する。** #63既存IssueとPR #64のみを維持する。最初の後続ADCでは既存V1 Intent/Appliedを当時のbaseline→successor ADCに結び付いた物理的`phase:ready`→`phase:requirements`更新の履歴として保持する。実在する旧V1 payloadは`executor_user_id`を含まず、GitHub carrier authorを保持してApplied authorとの一致を検証する。さらに後続の承認済みADC世代には、V2 Intent/Appliedを一世代ずつappend-onlyで追記する。Issueがすでに`phase:requirements`なら`adopt_existing_requirements`として同一の完全なlabel集合を記録し、label PUTは0回。各V2は直前ADC pointerと直前Applied ID/payload digestに連結し、世代skip・旧世代未完了・driftはBLOCKする。Phase記録は実行証跡であり、`PHASE_REBASE`承認・owner decisionは作らない。新ADC世代の作業は、その世代に結び付くPhase証跡を仕様→設計→ready順に確立する。旧世代のADC/pointer/receipt/Gate Selectionを上書きしない。実装根拠となる詳細なV2 wire contractはPRコメント[#6244287641](https://github.com/puchinya/ai-agent-workflow/pull/64#issuecomment-6244287641)を参照する。
2. **ActivationはStage 2で完全に終える。** **Rulesetを設定しただけ・Setup PRを開いただけ・`SETUP_PENDING`を返しただけは未完了。** `PASES_CONSUMER_ACTIVATION_V2`のappend-only record（Issue #57）を発行し、comment ID・内容・`created_at`・管理Ruleset ID／owned apply記録・有効policy digestをreadbackして`ACTIVE`を確定する。
3. **Setup PRのマージはActivation内部。** Activation V2が要求する別のSetup PRは、PR #64が通常ゲートでマージされIssue #63がOPENと確認された後、別途審査・正確なHEADに対するmerge承認を経てマージする。Setup PRの承認をPR #64の`PR_MERGE`承認へ流用しない。Setup PRマージ自体がActivationの完了を意味しない（post-merge verify / recordが必要）。
4. **Activation自身がGitHub必須設定を整備。** `consumer-activation-setup`がrepository/profile検査、exact Ruleset plan、別承認、isolated browser device Admin continuation、単一Rulesetへの一度限りのPOST/PUTまたはNOOP、policy double-read、Setup PRの作成・再開、post-merge recordを駆動する。Admin device flowはrunner-managed PTYでURL/codeを表示し、owner-local terminalを必須にしない。変更対象は既定済みの単一 `P-ASES Final Delivery (managed)` Rulesetのみ。Required Checks 4件/App ID 15368、PR必須、review-thread解決、force push禁止、bypass無しを保つ。
5. **承認と実装権限は分離。** Ownerの本チャットでの「後続ADCは承認する」は意向として受領する。実際の `ADC_SUPERSEDE`依頼では、最終canonical ADC `.md`ファイルを提示し、その全文をコードフェンスやHTML disclosure/containerで囲まずMarkdownとして同一会話で表示する。対象Issue、operation、exact SHA、approved predecessor pointer、plan/scope SHAと結果のPhase更新も示してから、その全文に結び付く明示承認を求める。UIに全文を含められない場合は直前の同一会話メッセージにMarkdown全文とcanonical file linkを表示し、選択式の依頼からその全文を明示参照する。リンク・抜粋・SHAだけで承認を求めない。ADC bytesが変われば新しいMarkdownを再表示し、新SHAへの承認を要する。`RULESET_PLAN_APPLY`、Setup PR merge、`USER_REVIEW`、PR #64 `PR_MERGE`は**別操作**であり、この承認から自動的に許可されない。Phase更新は後続ADCの承認・公開後に自動実行し、Owner decisionとは扱わない。決定記録をCodexがオーナーに成り代わって作成してはならない。owner-decision relayのcredential/tool boundaryを実証できなければ承認記録のwriteはBLOCKED。Phase Intent/Appliedとlabel更新は、ADC公開後の通常認証済みP-ASES executor操作として行う。
6. **Activationのmain進行とPRBindingの互換性。** Issue #63ではPR #64を先にマージするため、Activation Setup PRによる後の`main`進行はPR #64のmerge前提ではない。ほかの対応workflowでこのcurrent-base証跡を使う場合も、旧`ExecutionBinding`/`PRBinding`/frozen baseは書き換えず、正規Setup PR由来と独立検証できる前進（旧baseの子孫、Setup PR merge commitの正確な同定、変更ファイルは`.agent/project.json`のみ、期待profileと一致、GitHubに別PR介入なし）だけを追記専用evidenceとして許可する。一般的base driftや不明なmain変更はBLOCKする。旧実装の固定SHA比較を無条件に削除してはならない。
7. **#64の通常ゲートはActivationと独立。** 後続ADCとPhase receiptsの後、Activation `ACTIVE`前にPR #64の4 Required Checks/current HEAD、Self-Audit、Independent Review、User Review、Final Delivery、effective Ruleset policy、別`PR_MERGE`承認をすべて再評価する。成功後もIssue #63がOPENであることを確認し、Activation/Issue closeは後続工程とする。必要な承認またはGitHub管理認証がない間、コード実装/テストは継続できるが、merge/close完了を偽装しない。
8. **GitHub APIとrepository transferを分ける。** Issue/PR/comment/review/check/Actions/Ruleset/policy/merge/label/close等のGitHub API read/writeは`runtime/p_ases/github.py`経由の`gh`のみ。JSON bodyは`gh api --input -`のstdinへ渡し、connector/plugin/SDK/direct HTTP/curl/UI writeを使わない。repositoryのfetch/push/remote-ref・object readbackは既存Git境界の`git`で行う唯一のGitHub-hosted transport例外。Git操作でIssue/PR等のAPI状態を読み書きしない。実環境に必要な認証済み`gh`がなければGitHub API操作未実施と報告し、別連携に切り替えない。
9. **チャット承認はexact scopeごと。** 同一会話でユーザー本人の直接user-role応答を受け、repo/Issue/operation/ADCまたはplan SHA/PR+HEAD/scopeを提示して明示承認を得る。`ADC_SUPERSEDE`では最終canonical `.md`ファイルを提示し、その全文をコードフェンスやHTML disclosure/containerで囲まずMarkdownとして承認依頼の直前に表示する。選択UIの容量上全文を入れられない場合も同じ会話の直前メッセージにMarkdown全文とfile linkを表示し、承認選択はその表示とSHAを明示参照する。リンク・抜粋だけで依頼しない。ADC変更時は新しいMarkdownを再表示し、新SHAで再承認する。V3 `chat_confirmed_gh_v1`はoperator-reportedチャット承認とGitHub owner actorを記録し、チャット署名や独立relayを主張しない。承認TTY・SHA再入力・GitHub UI投稿は不要。hostの直接user-role provenanceが得られなければ`CHAT_PROVENANCE_UNAVAILABLE`で書込0。CLI `owner-authorize-commit`はfail-closed、in-process integrationだけがtyped grantを受け取る。

<a id="issue-63-two-stage-completion-order"></a>
### 2.1 Issue #63 の二段階完了順序

- #64 merge前には、通常のFinal Deliveryゲート、solo-owner effective Ruleset、exact HEAD、CI、Independent Review、User Review、別個のPR_MERGE承認を要求する。Activation V2 `ACTIVE`はこのmergeの前提にしない。
- #64本文は`Closes #63`ではなく一意のstandalone `Refs #63`を使い、共通検出器はGitHubの大文字小文字を区別しないclose/closes/closed、fix/fixes/fixed、resolve/resolves/resolvedと任意のコロン、`#N`および`OWNER/REPO#N`を検出する。repo-qualified参照はowner/repoをcase-insensitiveに正規化してIssue identityを比較する。merge前にbody、全commit message、planned merge message、GitHub `closingIssuesReferences`、Issue cross-reference metadataを完全にreadbackし、merge後も実merge commitに同じ検出器を適用する。auto-close token/linkまたは不完全readbackはmerge前にBLOCK。merge直後にIssue #63がOPENであることを確認する。
- Rulesetが必要なら、cleanなPR #64確定HEADと`.agent/project.json`のsolo_owner/Required Checksから`activation_binding`なしでcanonical Ruleset planを作成し、別のRULESET_PLAN_APPLY承認、既存の単一writer/apply/readbackを#64 merge前に使う。既存owned policyはNOOP。Activation V2やSetup PRを前倒ししない。
- #64 merge後にclean default worktree/current mainからActivation V2 Setup PRをreview/mergeし、`ACTIVE` record、`created_at`、Ruleset/effective policyを再検証する。`created_at`は#64 mergeより後であること。最後にdurable close intentを使ってIssueを一度だけ閉じ、direct/list/directでreadbackする。失敗時はIssueをOPENのままにし、ambiguous PATCHを再送しない。
- `Setup PR merge = Activation ACTIVE`、Ruleset適用だけでActivation ACTIVE、旧ADC草案のSHA/承認を新しいバイトへ流用、一般的base driftの許可は禁止。

## 3 Exact Change Set

- `docs/contracts/issue-63-successor-adc-final.md` をcanonical approval candidateとして最終化し、第7節手順、第11節チェックリスト、第12節Completion Gates、独立レビューhandoffを同期する。新規approved publishのshared preflightはdraft-only title/header/statusとpredecessor mismatchをfirst write前に拒否する。`parse_adc` / historical generation verificationとdraft publicationは互換のまま。変更後のfinal bytesをSHA-256で固定し、GitHub PR HEAD上のraw contentと同じであることを確認する。**最終SHAへの新しい承認証跡を得るまでは発行しない。**
- `docs/specs/workflow-spec.md` REQ-F01-008/009/011/013、`docs/design/workflow-design.md` DES-F01-011/013、および `docs/testing/{pases-lifecycle-tests,runtime-tests,traceability}.md`、`workflow/skills/delivery-control/SKILL.md` に全順序とSetup PR/PR #64の区別を反映する。
- `runtime/p_ases/{work,checkpoint,cli}.py`で「Activation内部Setup PRによる検証済みmain進行」への前述の限定対応を実装する。`runtime/p_ases/consumer_activation.py`はSetup PRマージ後のV2発行まで確実にresumeし、`ACTIVE`でのみActivation完了扱いとする。既存`ruleset_management.py`のcanonical one-writer / durable intentを変更・複製しない。
- `tests/{test_pr_ensure,test_consumer_activation,test_p_ases_cli,test_final_delivery,test_ruleset_management}.py`等に具体的な回帰を追加。通常のIssueでは`Closes #N`による自動closeを維持し、後工程付きのPR #64だけ`Refs #63`へ変更する。新規の実装PRは作らない（Activation Setup PRのみ別管理）。
- `python tools/build_dist.py`のみで`dist/{openai,claude,antigravity}`を生成し、手編集しない。

## 4 Implementation Sequence — 必ずこの順

1. **実装**: PR #64に現在の契約修正、必要な互換機能、Oracle/テストを実装、コミット・push。CI/セルフレビューを通す。すでにPASSした部分を原因なく作り直さない。
2. **後続ADC正式化**: `issue-63-successor-adc-final.md`を現在のapproved pointer predecessorに一致させてfinalizeし、canonical `.md`ファイルを提示して全Markdownを同一会話で表示する。コードフェンスやHTML disclosure/containerで囲まない。本文全体・実SHA・predecessor pointer・plan/scope SHAをownerへreadbackした後に、後続ADCの正確なSHAに対する`ADC_SUPERSEDE`承認（このチャットでの以前の承認意向を未提示SHAへ流用しない）を取得し、`publish_adc(...state="approved",supersede=True,explicitly_approved=True,expected_current=...)`の正規経路→`verify_adc` / forward generation→自動Phase Intent/一回限りのlabel PUT/Applied→Phase receiptsをreadback。選択UIに全文を格納できなければ、依頼直前の同一会話メッセージにMarkdown全文とfile linkを表示し、選択式依頼がその表示とcanonical fileを明示参照する。SHAが変わる場合は新しいMarkdown全文表示・承認を繰り返す。**この工程を完全に終えてからActivationへ進む。**
3. **PR #64通常ゲート/merge**: 後続ADC/Phase receipts、current HEADの4 Required Checks、Independent Review、User Review、Final Delivery、effective solo-owner Ruleset、exact-HEAD `PR_MERGE`を確認する。Rulesetが必要ならcleanな確定HEAD/profileから`activation_binding`なしのcanonical planを使い、別のplan承認・scoped Admin applyを経る。PR本文は唯一のstandalone `Refs #63`。全commit message、planned merge message、GitHub `closingIssuesReferences`とIssue cross-reference metadataを完全readbackし、auto-close関係や不完全readbackがあればmerge前にBLOCK。通常ゲートを緩和せずPR #64を一度だけmergeし、直後にIssue #63がOPENであることを確認して`MERGED_AWAITING_ISSUE_COMPLETION`を記録する。
4. **Post-merge Activation V2完了**: PR #64 merge後にclean default worktree/current mainからIssue #57の現在record、Ruleset inventory/legacy protection等を管理者権限でreadbackし、`consumer-activation-setup` checkpointを再開する。必要なRuleset変更には別plan SHAと`RULESET_PLAN_APPLY`チャット承認が必要。V3 recordとexisting two-line #57 approvalをghで検証後、isolated browser device Admin applyを行う。Ruleset VERIFIED後に別Activation Setup PRを作成し、そのPRの別merge承認・mergeを経て、`consumer-activation-verify`でV2 recordを発行し`ACTIVE`をreadbackする。Activation `created_at`がPR #64 mergeより後であることを確認する。

   **Worktree境界:** 新ADC世代の`work bind`とIssue #63 Phase receipts、PR #64 normal gates/mergeはPR #64の実装worktreeで行う。Activation setupはPR #64 merge後の別の専用Activation worktreeでのみ実行し、そのworktreeはcleanかつrepository default branch上で、local HEAD = `git ls-remote origin refs/heads/<default>` = `gh api repos/<owner>/<repo>/branches/<default> --jq .commit.sha`でなければならない。実行前に`git worktree list`、`git status --porcelain --untracked-files=all`、`git symbolic-ref --short HEAD`、`git rev-parse HEAD^{commit}`、`git ls-remote`、`gh api`を照合する。API readは`gh`のみ、Git object/refの検査は`git`を使う。PR #64 worktreeをreset/rebaseしてActivationへ流用しない。適合worktreeがなければGit worktree境界で別checkoutを用意し、既定refの進行が必要な場合も専用Activation worktree内の検証済みfast-forwardのみ行ってpreflightをやり直す。CLIは`python -m p_ases delivery consumer-activation-setup --repo OWNER/REPO --root ACTIVATION_WORKTREE`のようにrootを明示する。
5. **Issue #63クローズ**: clean current-main worktreeでActivation V2 `ACTIVE`、V2 `created_at`が#64 mergeより後、現行owned Ruleset/effective policyをreadbackする。`delivery finalize 63 64`のdurable intentを使ってIssue #63を一度だけ閉じ、direct/list/directでCLOSEDを確認する。失敗/曖昧なPATCHはIssueをOPENのままとし、二度目のPATCHや再openをしない。

## 5 Required Runtime Semantics

- **No-op/retry**: V2 recordが既に存在し内容一致なら新規発行しない。Rulesetが完全一致ならNOOP。通信不達後はread-only recovery→一致すれば継続、不明ならBLOCK。二重Ruleset write・二重ADC publish・二重Activation recordを禁止。
- **Stale subject**: ADC/plan/profile/branch/Setup PR/HEAD/Readinessに差異があれば以前のapprovalを失効扱いし、新対象をreadbackする。#63の古いADCを削除しない。
- **Partial failure**: 403/chat provenance unavailable/device login unavailable/credential不足/承認未成立では機密情報を要求せず、該当段階を`BLOCKED`または`PENDING_APPROVAL`にする。独立コード作業は継続。PR #64のmerge/closeはしない。
- **Ownership**: PATはCodex Cloud、PR、logs、files、CI、argv、`os.environ`へ露出させない。PATは明示的なnonstandard fallbackで、owner-local TTYが必要。標準`isolated-gh-device`はprivate mode-0700 `GH_CONFIG_DIR`、ambient token除去、normal `gh`不変、cleanupを使う。runner-managed PTYでbrowser URL/codeを表示できなければ`ADMIN_DEVICE_LOGIN_UNAVAILABLE`で停止。OAuth grantはcleanupで失効しない。同じOS userのsubprocessは強いsandboxではない。
- **Historic**: #57 V1、#63旧ADC・Phase Decision・Gate Selection、#60/PR #62、旧PRBindingは不変。V2の有効時刻はrecord commentの`created_at`。

## 6 Non-goals / Forbidden Changes

- 管理外Ruleset・組織Ruleset・legacy protection・bypass・他リポジトリ設定の無断変更。
- チャット承認の署名・ホスト認証・GitHub actor由来を偽装すること。
- Self-authored PRへの正式GitHub self-APPROVEを実施すること。専用`PASES_USER_REVIEW_DECISION_V1` carrierのみ。
- ゲートのテストskip、閾値緩和、データ書換えでgreen化すること。
- Issue #63とは別の実装Issue/PRを新設すること。

## 7 Concrete Tests

1. **順序**: ADC未正式化→Phase receipts/PR #64 merge拒否; #64の通常ゲート完了→`Refs #63`でmerge→Issue OPEN; V2 record/Setup PR未完了→Issue close禁止; verified `ACTIVE` after merge→one-shot close。Setup PRのmergeだけではActivation ACTIVEにならない。
2. **ADC**: old approved pointer→exact successor approved→new Phase receipts。欠損/未承認/異SHA/重複/actor不一致で拒否。旧ADCとGate Selection不変。
3. **Base A→B**: Activation Setup PRが`.agent/project.json`だけをコミットしてmerge、旧Aから子孫Bへ進み、期待プロファイル一致→PR #64 readback/新世代Binding/Readiness継続。旧Bindingのbytes変化なし。
4. **Base drift拒否**: 通常PRのmergeや不明コミット/force push、profile相違、direct GitHub readback相違→失敗を特定してBLOCK。単に「no panic」では不可。
5. **Ruleset/Activation**: Empty→approved create1、owned same→NOOP、owned change→approved update1。403、legacy conflict、broker境界不明、失われたPOST/PUT応答、中断後再開で二重書込なし。V2 record ID + `created_at`厳密一致。
6. **review/merge**: solo_owner carrierのexact session/readiness/HEAD一致、後続コメントやthread未解決で拒否。Setup PR承認を#64に流用不可。必要CIのApp ID差異で拒否。
7. **Activation worktree**: PR #64 feature worktreeからsetupを呼ぶとGitHub write 0で拒否し、feature HEAD、ExecutionBinding、PRBinding、Issue #63 historyが不変。clean default worktreeの完全一致HEADからsetupへ進む。dirty、detached、remote/GitHub default HEADより古いcheckoutはwrite 0で拒否。

## 8 Verification

```sh
python -m compileall runtime tools tests
python -m unittest discover -s tests -p 'test_*.py'
python -m p_ases docs validate --root .
python -m p_ases docs format --check --root .
python tools/validate_pases_traceability.py specification
python tools/validate_pases_traceability.py design
python tools/validate_pases_traceability.py test-oracle
python tools/build_dist.py
python tools/build_dist.py --check
python tools/validate_dist.py
python tools/validate_parent_acceptance.py 16-skills-package
git diff --check
```

GitHub Actionsが同じHEADでUbuntu 3.10/3.14、Windows 3.14、macOS 3.14（App ID 15368）の4つすべてPASSすること。ローカル成功を実GitHub Ruleset成功と混同しない。

## 9 Reviewer Checklist（実装開始前に公開）

- [ ] 通常PRは`Closes #N`で自動closeされる。後工程付きPR #64は`Refs #63`で通常merge後もIssue OPENを保つ。
- [ ] 完了順序が `実装 → 後続ADC正式化 → Phase receipts → #64通常ゲート/merge → Issue OPEN確認 → Activation V2 ACTIVE → #63 one-shot close`。
- [ ] 後続ADC最終バイト/SHAのapprovalが本人に読戻され、公開後に正確なpointer/Phase receiptsを検証。
- [ ] Activation Setup PRの正規mergeと#64のmerge許可が完全に別。
- [ ] V2 record ID/created_at/owned Ruleset ID・policy digestまでverifyしてACTIVE。
- [ ] Setup PR由来base advanceの例外は検証済み限定で、元Bindingと旧履歴を不変維持。
- [ ] チャットV3はoperator-reportedと明記し、chat署名を主張しない。Admin credentialはisolated child内のみ。
- [ ] `isolated-gh-device`はAdmin標準、private mode-0700 config/ambient token除去/normal gh不変/cleanupを満たす。Cloud runner PTY live flowが未実施なら未検証とする。
- [ ] 5種のowner decisionを相互流用せず、署名・Actorの偽装なし。
- [ ] GitHub API I/Oはghのみ、repository fetch/push/ref transferは既存Git境界のgitのみ。chat approvalは同一会話のdirect user-role eventから exact scopeごとに取得。
- [ ] 4 CI / unit / docs / traceability / dist / 16 Skillsを最新HEADで検証。
- [ ] PR #64の通常ゲート（current HEAD CI / independent review / User Review / Final Delivery / effective Ruleset / exact PR_MERGE）はActivation前に完了し、Activationは#64 merge後に行う。
- [ ] PR #64のmerged SHAとIssue #63 OPENを直後にreadbackし、後続ActivationのSetup PR/V2 recordおよびIssue #63 CLOSEDを最終readback。

実装担当は各項目を自ら確認し、未達の箇所をCompletion Reportに未達と記載する。

## 10 Completion Report

必須: 変更ファイル、全Checklistの結果、実行したテストと正確な結果、未検証OS、CI run URL、最終ADC digest・正式comment/pointer、V1 Intent/Appliedの歴史的証跡、各V2 generationのIntent/Applied IDと前Applied ID/payload digest、今回のlabel PUT回数（0）、Setup PR URL/merged SHA、Ruleset plan・適用record、V2 Activation record comment ID・有効時刻、PR #64 URL/merged SHA、Issue #63 close readback、承認別証跡、契約逸脱、実運用blocker、レビュー分類 **A（契約違反）/B（契約曖昧）/C（新要件）/D（任意改善）**。

**実装だけ完了してActivationが権限・承認により止まった場合は `IMPLEMENTATION_READY / ACTIVATION_DELIVERY_BLOCKED` と報告する。全段階の証跡がそろうまで `COMPLETED` としない。**

> This document is an Implementation Contract. Do not redesign the architecture during implementation. If a requirement conflicts with repository reality or requires a material design change, do not silently choose an alternative. Report the exact conflict and continue only with independent valid work.
