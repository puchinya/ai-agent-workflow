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
  - [2.1 禁止する旧順序](#21-禁止する旧順序)
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

- Owner最終決定: **実装完了 → 後続ADC正式化 → Activation V2 `ACTIVE` → 実装PR #64マージ → Issue #63クローズ**。この順序は旧PRコメントの矛盾する順序指定に優先する。
- Ownerは後続ADCを承認する意向を明示した。ただし承認対象は最終順序を反映して確定した**正確なADCバイト列とSHA-256**でなければならない。新SHAが未提示・未照合の間、現行草案の曖昧な承認を `ADC_SUPERSEDE` の実行証跡に変換してはならない。後続ADCの正式化はActivationより先に完了させる。
- #64はOPEN、Issue #63はOPEN / `phase:ready`。PR #64の現HEADに対してCI #168は4 matrix成功、PR報告は421 unit tests成功。これは実運用Activationが成功したことを意味しない。
- #63の現行approved ADC: Issueコメント `#6228771805`、SHA `ad13d005126693bb4e1cbe1e7eaa815e43f0a1ef3b88ef9f1670450a42bc9622`。後続草案: `docs/contracts/issue-63-successor-adc-draft.md`（PR #64内、**未正式化**）。PR本文の以前の草案SHA `5e112701903777f0786d6d8bbbe354b292300145262dbcada3563a4448f3a7a4`は修正後には失効する。
- #57のV1 Activationは残存。#57にはまだRuleset plan承認、`PASES_RULESET_APPLIED_V1`、`PASES_CONSUMER_ACTIVATION_V2` の実証済み記録がない。
- 根拠: `docs/specs/workflow-spec.md` REQ-F01-008/009/011/013/014/015、`docs/design/workflow-design.md` DES-F01-011/013/014/015、`runtime/p_ases/consumer_activation.py::{setup_consumer_activation,verify_and_record_activation}`、`runtime/p_ases/adc.py::{publish_adc,verify_adc}`、`runtime/p_ases/phase_rebaseline.py::rebaseline_issue_phase`、`runtime/p_ases/work.py::ensure_pull_request`。

## 2 Architecture Decisions

1. **後続ADCをActivationより先に正式化する。** #63既存IssueとPR #64のみを維持する。後続ADCをappend-only `ADC_SUPERSEDE`で正式発行し、approved pointerとforward generationを確認した後、通常の認証済みP-ASES executorが#63を`phase:ready`から`phase:requirements`へ一度だけ自動更新する。Intent/Appliedコメントは実行証跡であり、`PHASE_REBASE`承認・owner decisionは作らない。正式化後は同一ADC世代のPhase証跡を仕様→設計→ready順に確立する。旧世代のADC/pointer/receipt/Gate Selectionを上書きしない。
2. **ActivationはStage 2で完全に終える。** **Rulesetを設定しただけ・Setup PRを開いただけ・`SETUP_PENDING`を返しただけは未完了。** `PASES_CONSUMER_ACTIVATION_V2`のappend-only record（Issue #57）を発行し、comment ID・内容・`created_at`・管理Ruleset ID／owned apply記録・有効policy digestをreadbackして`ACTIVE`を確定する。
3. **Setup PRのマージはActivation内部。** Activation V2が要求する別のSetup PRは、PR #64より前に別途審査・正確なHEADに対するmerge承認を経てマージする。Setup PRの承認をPR #64の`PR_MERGE`承認へ流用しない。Setup PRマージ自体がActivationの完了を意味しない（post-merge verify / recordが必要）。
4. **Activation自身がGitHub必須設定を整備。** `consumer-activation-setup`がrepository/profile検査、exact Ruleset plan、別承認、isolated browser device Admin continuation、単一Rulesetへの一度限りのPOST/PUTまたはNOOP、policy double-read、Setup PRの作成・再開、post-merge recordを駆動する。Admin device flowはrunner-managed PTYでURL/codeを表示し、owner-local terminalを必須にしない。変更対象は既定済みの単一 `P-ASES Final Delivery (managed)` Rulesetのみ。Required Checks 4件/App ID 15368、PR必須、review-thread解決、force push禁止、bypass無しを保つ。
5. **承認と実装権限は分離。** Ownerの本チャットでの「後続ADCは承認する」は意向として受領する。実際の `ADC_SUPERSEDE`には修正後の正確なADCバイト列/SHA、対象Issue、predecessor pointerのreadbackと、当該SHAに結び付く認証済み本人承認が必要。`RULESET_PLAN_APPLY`、Setup PR merge、`USER_REVIEW`、PR #64 `PR_MERGE`は**別操作**であり、この承認から自動的に許可されない。Phase更新は後続ADCの承認・公開後に自動実行し、Owner decisionとは扱わない。決定記録をCodexがオーナーに成り代わって作成してはならない。owner-decision relayのcredential/tool boundaryを実証できなければ承認記録のwriteはBLOCKED。Phase Intent/Appliedとlabel更新は、ADC公開後の通常認証済みP-ASES executor操作として行う。
6. **Activationのmain進行とPRBindingの互換性。** Activation Setup PRマージが先に`main`を前進させ、`runtime/p_ases/work.py::ensure_pull_request`の凍結base SHAとの厳密一致が破れる。旧`ExecutionBinding`/`PRBinding`/frozen baseは書き換えない。正規Setup PR由来と独立検証できる前進（旧baseの子孫、Setup PR merge commitの正確な同定、変更ファイルは`.agent/project.json`のみ、内容がPR #64の期待profileと一致、GitHubに別PR介入なし）だけを追記専用current-base evidenceとして許可し、`pr ensure`・Readiness・Final Deliveryへ同一判定を適用する。一般的base driftや不明なmain変更はBLOCKする。旧実装の固定SHA比較を無条件に削除してはならない。
7. **Activation前のADC・後のPR reviewは各々別Gate。** `ACTIVATION_ACTIVE`を検証してからPR #64の4 Required Checks/current HEAD、Self-Audit、Independent Review、User Review、Final Delivery、別`PR_MERGE`承認を再評価する。必要な承認またはGitHub管理認証がない間、コード実装/テストは継続できるが、Activation/merge完了を偽装しない。
8. **GitHub APIとrepository transferを分ける。** Issue/PR/comment/review/check/Actions/Ruleset/policy/merge/label/close等のGitHub API read/writeは`runtime/p_ases/github.py`経由の`gh`のみ。JSON bodyは`gh api --input -`のstdinへ渡し、connector/plugin/SDK/direct HTTP/curl/UI writeを使わない。repositoryのfetch/push/remote-ref・object readbackは既存Git境界の`git`で行う唯一のGitHub-hosted transport例外。Git操作でIssue/PR等のAPI状態を読み書きしない。実環境に必要な認証済み`gh`がなければGitHub API操作未実施と報告し、別連携に切り替えない。
9. **チャット承認はexact scopeごと。** 同一会話でユーザー本人の直接user-role応答を受け、repo/Issue/operation/ADCまたはplan SHA/PR+HEAD/scopeを提示して明示承認を得る。V3 `chat_confirmed_gh_v1`はoperator-reportedチャット承認とGitHub owner actorを記録し、チャット署名や独立relayを主張しない。承認TTY・SHA再入力・GitHub UI投稿は不要。hostの直接user-role provenanceが得られなければ`CHAT_PROVENANCE_UNAVAILABLE`で書込0。CLI `owner-authorize-commit`はfail-closed、in-process integrationだけがtyped grantを受け取る。

<a id="禁止する旧順序"></a>
### 2.1 禁止する旧順序

- `#64マージ → V2 Activation`、`#64マージ後に後続ADC公開`、`Ruleset適用だけ → #64マージ → V2は後日`、`Setup PR merge = Activation ACTIVE`、`後続ADC草案を未修正で承認済み扱い`。

## 3 Exact Change Set

- `docs/contracts/issue-63-successor-adc-draft.md` 第7節手順6、第11節チェックリスト、第12節Completion Gates、および本文中の「#63 merge後にV2」という古い約束をすべて上記順序に修正。変更後のADCをcanonical bytesでSHA-256再計算、GitHub PR HEAD上のraw contentとして確認する。**最終SHAへの承認証跡を得るまでは発行しない。**
- `docs/specs/workflow-spec.md` REQ-F01-008/009/011/013、`docs/design/workflow-design.md` DES-F01-011/013、および `docs/testing/{pases-lifecycle-tests,runtime-tests,traceability}.md`、`workflow/skills/delivery-control/SKILL.md` に全順序とSetup PR/PR #64の区別を反映する。
- `runtime/p_ases/{work,checkpoint,cli}.py`で「Activation内部Setup PRによる検証済みmain進行」への前述の限定対応を実装する。`runtime/p_ases/consumer_activation.py`はSetup PRマージ後のV2発行まで確実にresumeし、`ACTIVE`でのみActivation完了扱いとする。既存`ruleset_management.py`のcanonical one-writer / durable intentを変更・複製しない。
- `tests/{test_pr_ensure,test_consumer_activation,test_p_ases_cli,test_final_delivery,test_ruleset_management}.py`等に具体的な回帰を追加。既存PR #64 `Closes #63`を維持し、新規の実装PRは作らない（Activation Setup PRのみ別管理）。
- `python tools/build_dist.py`のみで`dist/{openai,claude,antigravity}`を生成し、手編集しない。

## 4 Implementation Sequence — 必ずこの順

1. **実装**: PR #64に現在の契約修正、必要な互換機能、Oracle/テストを実装、コミット・push。CI/セルフレビューを通す。すでにPASSした部分を原因なく作り直さない。
2. **後続ADC正式化**: 草案を最終順序と一致させ、実SHAをownerへreadbackし、後続ADCの正確なSHAに対する`ADC_SUPERSEDE`承認（このチャットでの以前の承認意向を未提示SHAへ流用しない）→`publish_adc(...state="approved",supersede=True,explicitly_approved=True,expected_current=...)`の正規経路→`verify_adc` / forward generation→自動Phase Intent/一回限りのlabel PUT/Applied→Phase receiptsをreadback。**この工程を完全に終えてからActivationへ進む。**
3. **Activation V2 完了**: issue #57の現在record、Ruleset inventory/legacy protection等を管理者権限でreadbackし、`consumer-activation-setup` checkpointを再開する。必要なRuleset変更には別plan SHAと`RULESET_PLAN_APPLY`チャット承認が必要。V3 recordとexisting two-line #57 approvalをghで検証後、isolated browser device Admin applyを行う。Ruleset VERIFIED後に別Activation Setup PRを作成し、そのPRの別merge承認・mergeを経て、`consumer-activation-verify`でV2 recordを発行し`ACTIVE`をreadbackする。**Setup PRはActivation工程内でmergeしてよいが、#64はまだmergeしない。**
4. **PR #64マージ**: Activation V2 `ACTIVE`のlive readback、新base互換証跡、HEAD/current CI、Independent Review、User Review、Final Delivery、#64専用exact HEAD `PR_MERGE`承認を再確認し、`gh`経由で一度だけmerge。SHA/readback必須。
5. **Issue #63クローズ**: PR #64 `Closes #63`を確認。自動closeの状態を読み取り、必要なら独立の正規Issue close操作で閉じ、再readbackする。

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

1. **順序**: ADC未正式化→Activation開始拒否; V2 record未発行→#64 merge禁止; `ACTIVE`/レビュー/承認完了→#64 merge→close。Setup PRのmergeだけでは#64 merge不可。
2. **ADC**: old approved pointer→exact successor approved→new Phase receipts。欠損/未承認/異SHA/重複/actor不一致で拒否。旧ADCとGate Selection不変。
3. **Base A→B**: Activation Setup PRが`.agent/project.json`だけをコミットしてmerge、旧Aから子孫Bへ進み、期待プロファイル一致→PR #64 readback/新世代Binding/Readiness継続。旧Bindingのbytes変化なし。
4. **Base drift拒否**: 通常PRのmergeや不明コミット/force push、profile相違、direct GitHub readback相違→失敗を特定してBLOCK。単に「no panic」では不可。
5. **Ruleset/Activation**: Empty→approved create1、owned same→NOOP、owned change→approved update1。403、legacy conflict、broker境界不明、失われたPOST/PUT応答、中断後再開で二重書込なし。V2 record ID + `created_at`厳密一致。
6. **review/merge**: solo_owner carrierのexact session/readiness/HEAD一致、後続コメントやthread未解決で拒否。Setup PR承認を#64に流用不可。必要CIのApp ID差異で拒否。

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

- [ ] 完了順序が `実装 → 後続ADC正式化 → Activation V2 ACTIVE → #64 merge → #63 close`。
- [ ] 後続ADC最終バイト/SHAのapprovalが本人に読戻され、公開後に正確なpointer/Phase receiptsを検証。
- [ ] Activation Setup PRの正規mergeと#64のmerge許可が完全に別。
- [ ] V2 record ID/created_at/owned Ruleset ID・policy digestまでverifyしてACTIVE。
- [ ] Setup PR由来base advanceの例外は検証済み限定で、元Bindingと旧履歴を不変維持。
- [ ] チャットV3はoperator-reportedと明記し、chat署名を主張しない。Admin credentialはisolated child内のみ。
- [ ] `isolated-gh-device`はAdmin標準、private mode-0700 config/ambient token除去/normal gh不変/cleanupを満たす。Cloud runner PTY live flowが未実施なら未検証とする。
- [ ] 5種のowner decisionを相互流用せず、署名・Actorの偽装なし。
- [ ] GitHub API I/Oはghのみ、repository fetch/push/ref transferは既存Git境界のgitのみ。chat approvalは同一会話のdirect user-role eventから exact scopeごとに取得。
- [ ] 4 CI / unit / docs / traceability / dist / 16 Skillsを最新HEADで検証。
- [ ] PR #64の現HEAD independent review / User Review / Final Delivery / PR_MERGEはActivation後に再実施。
- [ ] PR #64のmerged SHA、Issue #63 CLOSED、およびActivationのSetup PR/V2 record URLをreadback。

実装担当は各項目を自ら確認し、未達の箇所をCompletion Reportに未達と記載する。

## 10 Completion Report

必須: 変更ファイル、全Checklistの結果、実行したテストと正確な結果、未検証OS、CI run URL、最終ADC digest・正式comment/pointer、`PASES_PHASE_REBASE_INTENT_V1` / `PASES_PHASE_REBASE_APPLIED_V1`実行記録、Setup PR URL/merged SHA、Ruleset plan・適用record、V2 Activation record comment ID・有効時刻、PR #64 URL/merged SHA、Issue #63 close readback、承認別証跡、契約逸脱、実運用blocker、レビュー分類 **A（契約違反）/B（契約曖昧）/C（新要件）/D（任意改善）**。

**実装だけ完了してActivationが権限・承認により止まった場合は `IMPLEMENTATION_READY / ACTIVATION_DELIVERY_BLOCKED` と報告する。全段階の証跡がそろうまで `COMPLETED` としない。**

> This document is an Implementation Contract. Do not redesign the architecture during implementation. If a requirement conflicts with repository reality or requires a material design change, do not silently choose an alternative. Report the exact conflict and continue only with independent valid work.
