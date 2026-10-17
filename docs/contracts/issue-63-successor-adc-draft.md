# Agent Development Contract — issue-63-activation-ruleset-management-successor-draft

Draft only — not approved for execution or publication.

Repository: puchinya/ai-agent-workflow
Trusted repository identity for this proposed contract: GitHub repository ID `1401910271`; repository owner User ID `3744776`.
Issue: 63
Parent contract: none
Predecessor ADC: Issue #63 comment #6228771805, SHA-256 `ad13d005126693bb4e1cbe1e7eaa815e43f0a1ef3b88ef9f1670450a42bc9622` (immutable; this draft is a proposed successor).
Assigned requirements: REQ-F01-008, REQ-F01-009, REQ-F01-010, REQ-F01-011, REQ-F01-012, REQ-F01-013, REQ-F01-014, REQ-F01-015
Dependencies: Consumer Activation #57; predecessor F01 Issue #42; open #60/PR #62 is a downstream integration target, not a prerequisite.
Target release: unspecified

<!-- contents:start -->
**Contents**
- [1 Issue](#1-issue)
- [2 Scope](#2-scope)
- [3 Change Kind](#3-change-kind)
- [4 Requirements](#4-requirements)
- [5 Architecture Decisions](#5-architecture-decisions)
- [6 Artifact Impact](#6-artifact-impact)
- [7 Exact Changes](#7-exact-changes)
  - [7.1 Activation-owned current-base transition](#71-activation-owned-current-base-transition)
- [8 Invariants](#8-invariants)
- [9 Non-goals](#9-non-goals)
- [10 Verification Obligations](#10-verification-obligations)
- [11 Reviewer Checklist](#11-reviewer-checklist)
- [12 Completion Gates](#12-completion-gates)
<!-- contents:end -->

<!-- heading-map:start -->
**Stable heading map**
<!-- heading-map:end -->


<a id="issue"></a>
## 1 Issue

[P-ASES][F01][P0] Activation時のRuleset自動整備と既存Issue非破壊の再Activation. This contract authorizes implementation for this Issue alone, not administrator privileges or a Ruleset plan approval.

<a id="scope"></a>
## 2 Scope

Consumer Activation must establish effective repository Ruleset protection using exact, human-approved plans before recording V2 Activation. Preserve existing Issue authorization and append-only history, while applying current runtime fixes and live GitHub policy checks to old Issues. #63 is implemented before #60/PR #62 is merged.

<a id="change-kind"></a>
## 3 Change Kind

Behavioral bug fix and approved workflow enhancement. No implicit change to legacy V1 contracts or automatic authority for GitHub settings edits.

<a id="requirements"></a>
## 4 Requirements

All requirements from the immutable predecessor ADC remain binding. This successor adds the following requirement without changing the prior Activation history, Gate Selection, or Ruleset approval requirements.

- REQ-F01-008: V2 Activation shall verify the effective protected default-branch policy, trusted Required Checks/App IDs, review mode, and readable admin credentials before issuing the new record.
- REQ-F01-009: An explicitly approved canonical plan shall be required for any automated repository Ruleset create/update; writes shall be confined to the verified owned Ruleset and shall be idempotent/fail-closed.
- REQ-F01-010: V1 Activation history and existing Issue Gate Selections, ADCs, PRs and evidence shall remain unchanged; current runtime bug fixes and live Final Delivery checks shall apply to those Issues without re-authorization.
- REQ-F01-011: V2 Activation shall be append-only, have a record.created_at effective time, and must not retroactively authorize Issues created before its issuance.
- REQ-F01-012: Existing Issues shall validate only the authenticated history prefix ending at their selected Activation; issuing a successor and choosing new Issues shall validate the full history.
- REQ-F01-013: #63 shall bootstrap its Ruleset automation before merge, not require #60 completion, and preserve the existing independent review, Required Checks, User Review and merge gates.
- REQ-F01-014: Only the two explicit Activation admin commands shall accept a short-lived owner-created repository-scoped fine-grained PAT with Administration read/write through `getpass` on the owner’s interactive local TTY, with a separate session per command. The token shall reach only that command’s `gh api` child process, never global authentication state, unrelated processes, logs, arguments, files, JSON, or chat. The stable authenticated user ID must equal the target repository owner ID, with owner login, repository ID, `permissions.admin=true`, and collaborator permission `admin` verified. Non-TTY/cancelled/identity-mismatched/admin-insufficient/unreadable states shall block with zero Ruleset writes. Admin-plan shall save only a blocker-free canonical plan; admin-apply shall reuse the existing exact Issue #57 plan-approval and durable-intent path. The owner shall revoke the PAT in GitHub after use.
- REQ-F01-015: Keep delegated V1 owner records unchanged. If a ChatGPT broker boundary is positively verified, its V1 route may be used; otherwise require the owner's independent trusted local host, native local GitHub authentication, and interactive TTY. Codex Cloud, Cloud PTY, inherited/shared token variables, CLI flags, JSON consent, and manual GitHub UI edits are not owner-local approval. `delivery owner-authorize-plan` creates a canonical read-only plan; `delivery owner-authorize-commit` re-reads the fixed reviewed source, repository/Issue/PR subject and current HEAD, verifies the authenticated owner ID, displays the plan, requires the exact plan SHA typed on that TTY, performs one write, then direct/list/direct readback. Fail closed with `AUTH_TRANSPORT_UNAVAILABLE` on missing TTY/local auth, wrong owner, 403, stale subject, or ambiguous write; resume is read-only and never retries a POST. Owner-local records use `PASES_OWNER_DECISION_V2` / `PASES_USER_REVIEW_DECISION_V2` with `evidence_channel=owner_local_tty_v1`; these are GitHub actor evidence, not ChatGPT signatures. ADC_SUPERSEDE binds the exact successor ADC bytes SHA; RULESET_PLAN_APPLY binds the exact blocker-free plan SHA and appends the existing exact #57 two-line approval for the existing Admin apply path; USER_REVIEW binds exact session, Readiness, ADC, HEAD, prior feedback digest and plan digest; Setup PR and #64 PR_MERGE decisions bind separate exact HEADs. V1/V2 histories are checked together for cross-version replay. Phase bootstrap follows approved ADC publication automatically and uses only Intent/Applied technical records, never a PHASE_REBASE decision. PR merge remains gated by all required checks, independent review, User Review, Final Delivery, and Activation state.

<a id="architecture-decisions"></a>
## 5 Architecture Decisions

**D1 — 履歴の非遡及とruntime修正を分離する**

- 既存IssueのGate Selectionが参照するActivation comment ID/SHA、ADC、本文、phase、PR、過去の証跡を不変とする。V1有効時刻は既存の`merged_at`。V2の新review要求を旧ADCに遡及しない。
- 最新の**バグ修正済みruntime**と**現在の**CI/Ruleset/reviewは既存Issueでも評価する。保護が不足すればBLOCKし、古いIssueを新Activationへ付け替えない。
- 既存Issueの認可履歴は、参照先までの**厳密なprefix検証**を共有関数で行う。後続Activationの破損は旧Issueに波及させない。prefix自身の異常はBLOCK。新Issue選択・新Activation発行は全履歴を検証する。

**D2 — #63を先行し#62と共通基盤を一本化する**

- 順序: **#63の実装PR → #63ブランチで初回Ruleset整備 → #63レビュー/マージ → V2後継Activation → PR #62をmainへ追従 → #60完了**。#63は#60マージ待ちにしない。
- #63で`branch_policy.py::{EffectiveBranchPolicy,assess_branch_policy}`、`profile.py`のSchema 2任意`final_delivery.review_mode`、`github.py`の保護APIを先行導入。公開インターフェースはPR #62の現行実装に互換。後の#62で重複コードを除去し、機能実装自体は#60へ残す。
- このrepositoryの#63 PRは`.agent/project.json`に**明示`final_delivery.review_mode=solo_owner`**を追加し、既存Required Checks 4件とtrusted App ID 15368を維持。既定`external_reviewer`の互換性と他consumer repoの設定は変更しない。#57 V1のmerged profile証跡は変更しない。
- ユーザー向けの「P-ASESを有効化して」は、Activation discovery、setup branch準備、canonical Ruleset plan、必要時の正確なオーナー承認とowner-local Admin continuation、effective-policy readback、policy-bound setup PR、merge後のV2記録までを一つの再開可能な処理として進める。通常利用者にRuleset準備コマンドの手動連鎖を要求しない。
- `solo_owner`以外の既存V1動作は維持し、#63で認可されていないpolicy writeを追加しない。全modeで設定インベントリを報告し、mode上必須の未充足項目がある間は`ACTIVE`を返さない。

**D3 — 管理対象Rulesetのexact state**

- 対象はrepository scopeで**名前`P-ASES Final Delivery (managed)`の一件のみ**。`target=branch`、`enforcement=active`、`conditions.ref_name={include:["~DEFAULT_BRANCH"],exclude:[]}`、`bypass_actors=[]`。
- ルールは3種: `pull_request`（approvals=0、stale-dismiss=false、code-owner=false、last-push-approval=false、review-thread-resolution=true、merge methods=[merge,squash,rebase]）、`required_status_checks`（profileの4件の`context`＋`integration_id=15368`完全一致、strict=true）、`non_fast_forward`（force push禁止）。GitHub APIのrequired fieldsを全て正確に付ける。
- この自動更新は**明示選択したsolo_ownerのみ**。`external_reviewer`は読み取り・診断のみ。別名Ruleset、組織Ruleset、legacy protectionは変更しない。同名で管理所有証跡がない、競合保護、複数候補はBLOCK。削除・強制上書き・ルール緩和は禁止。

**D4 — 人の承認を拘束した安全な自動適用**

- Activation setupはGitHub read-only discoveryの後、policy-bearing setup PRを作る前にsetup branchと`.agent/project.json`のcommitだけを準備する。既存canonical plannerはrepo/owner ID、default branchと現行policy、setup branchのcommit/profile bytes、Activation ADC generationとpredecessor、mode/check集合、既存Ruleset ownership、desired API payload、diff、現行保護証跡、open-PR影響を含むblocker-free plan SHA-256を生成し、同じActivation checkpointへ保存する。
- Ruleset書込が必要なときは、正確なblocker-free plan SHAに対する`RULESET_PLAN_APPLY`を別途承認する。専用broker経路がcredential/tool分離まで実証済みならV1 relayを使用できる。実証できない場合はownerの独立したtrusted local TTYとそのホストのlocal GitHub authを必須fallbackとする。`delivery owner-authorize-plan`でplanをreadbackし、`delivery owner-authorize-commit`で本人が表示済みplan SHAをTTY入力する。V2 OwnerDecisionと既存の二行`PASES-RULESET-APPROVE` / `PASES-REPOSITORY`コメントをGitHubへ各一度だけ追記し、stable owner ID、対象Issue/repository、canonical bytes、direct/list/directを検証した後、既存 Admin applyへcomment IDを渡す。Cloud PTY、共有token変数、UI手編集は使わない。
  ```text
  PASES-RULESET-APPROVE: <64桁plan SHA-256>
  PASES-REPOSITORY: puchinya/ai-agent-workflow
  ```
  V1 relay writes remain available only when the broker credential and route are positively isolated from the implementation runtime. The mandatory fallback is owner-local TTY plus the owner's local GitHub authentication. V2 local records retain `owner_local_tty_v1` evidence channel and are not ChatGPT signatures. The Ruleset decision and existing exact two-line #57 approval both read back before the existing Admin continuation accepts them.
- trusted local TTY Admin continuationは同じcheckpointのexact planとowner approvalを再検証し、書込直前に前提を再取得する。一致時のみ**初回一度POST／所有証跡がある既存IDへ一度PUT／一致ならNOOP**。HTTP errorや失われたresponse後は管理対象のunique ID/bodyを再取得し、曖昧ならBLOCK。盲目的再試行、無断ロールバックは禁止。
- 適用後はruleset detail / effective branch rules / legacy protection / `main.protected`を**同じAdmin認証**で再読取し、#60互換の`EffectiveBranchPolicy.status=VERIFIED`以外はActivation発行不可。初回成功時に#57へ追記専用`PASES_RULESET_APPLIED_V1`（repo、ID、plan SHA、承認comment ID、適用後body digest）を投稿・再検証して管理所有証跡とする。以後のPUTはこのIDと前回digestに一致する場合のみ許可し、成功ごとに後継適用証跡を追加。証跡投稿失敗時は**一意ID＋元plan/承認＋現状が完全一致する場合だけ**冪等回復し、曖昧ならBLOCK。403を未設定扱いにせず、tokenをログに出さない。書込中・適用後の実効設定変更を検知したらBLOCK。過去のrecordは編集しない。

**D5 — 後継Activation V2**

- V1 payloadと承認履歴を一切変更せず、同じ#57へversioned setup/approval/record **V2をappend-only**。V2 setupとrecordはmerged profile bytes SHA、review mode、Check集合/App ID、exact setup branch generation、管理Ruleset ID、実効policy digest、setup PR/管理者を拘束する。既存setup proposalのRuleset ID/applied-record/policy digestが現行verified policyと異なる場合は旧proposalを不変のまま残し、新しいexact branch/plan/PR generationを作る。古いproposalを更新して現行証跡に見せかけない。
- V2の**有効時刻はGitHubが返すActivation recordの`created_at`**。setup PR mergeとrecord作成の中間に作成されたIssueは新V2を使用しない（旧V1が有効ならV1を使用）。V1の時刻は従来どおり。
- 現行`setup_consumer_activation`が同一ADC SHAで古いACTIVEを返す短絡は**V1→V2移行の場合に使わない**。fresh policy double-read後のみrecord追加。発行後のpolicy変更は過去のrecordを無効にせず、現在のpreflight/Final DeliveryだけBLOCK。

**D6 — Activation-owned provisioning with a temporary administrator credential**

- Preserve D1–D5 and the predecessor ADC’s exact-plan approval/apply rules. `delivery consumer-activation-setup` is the user-facing orchestration and resumes the transaction from its persisted stage. The two commands `delivery consumer-activation-admin-plan` and `delivery consumer-activation-admin-apply` remain internal trusted owner-operated continuations for the provisioning stage; ordinary preflight, Ruleset plan/apply, and all other commands never prompt or escalate.
- The human owner creates a short-lived fine-grained PAT limited to repository `puchinya/ai-agent-workflow`, with Administration read/write and only the minimum additional read/write permissions the existing Issue #57 approval and applied-record path requires. The owner enters it using `getpass` on an interactive local TTY. Non-TTY/sandbox execution returns `ADMIN_AUTH_INTERACTIVE_REQUIRED` before requesting the token or making requests. Do not use browser automation, `gh auth login --web`, token arguments, token files, global `GH_TOKEN`, or persistent credential stores. The owner revokes the PAT in GitHub after the separate plan and apply sessions; process exit alone does not revoke it.
- For normal Activation, the Cloud/runtime flow prepares and persists the reviewable exact plan and checkpoint; the owner runs the Admin continuation in a separate trusted local environment with an interactive local TTY. Codex Cloud and Work Browser cannot provide that local TTY and do not receive or enter the PAT. If the owner has no such local environment, Activation remains resumably blocked at provisioning and other independent implementation/review preparation may continue. The #63 pre-merge bootstrap uses this same Activation transaction and canonical plan/apply/readback path.
- Add `runtime/p_ases/admin_auth.py` for the TTY-only owner session and account/repository/admin preflight. Add a private, repr-hidden credential override to `GitHub`; `GitHub.request` copies the child environment, sets the override as `GH_TOKEN`, removes competing token variables, and supplies it only to its own `gh api` subprocess. Never mutate `os.environ` or unrelated child environments. Clear the override in `finally` across success, error, and interruption; Python-memory erasure is not guaranteed.
- Add only these CLI commands and arguments:
  ```sh
  python -m p_ases delivery consumer-activation-admin-plan --repo puchinya/ai-agent-workflow --root . --output /tmp/pases-issue63-plan.json
  python -m p_ases delivery consumer-activation-admin-apply --repo puchinya/ai-agent-workflow --root . --plan /tmp/pases-issue63-plan.json --approval-comment-id COMMENT_ID
  ```
  Each command obtains a separate TTY credential session. The plan command is read-only with respect to GitHub and saves a canonical plan only when `status=PLANNED` and `blockers=[]`. Apply rechecks stable user ID equality with owner ID, owner login, repository/owner IDs, `permissions.admin=true`, collaborator permission `admin`, main legacy protection, Ruleset inventory, effective branch rules, exact plan freshness, Activation checkpoint subject, and exact human approval on configured Activation Issue #57 before reusing `apply_ruleset_plan`. A 403 or partial read remains unavailable and blocks. It returns the Activation transaction to policy readback; the setup PR is created only after policy is verified and its marker binds the Ruleset ID, applied-record ID, and effective-policy digest.
- No credential is approval. Owner-local V2 approval requires the owner's local TTY confirmation and separately authenticated local GitHub identity; the Admin credential remains a separate session. Reuse existing durable intent, one-write/no-op semantics, readback, V1 history, PR #64, #57 V1, and #60/PR #62 unchanged. Admin authentication and Ruleset approval do not approve PR merge.

**D7 — Owner-local authorization fallback and V2 history**

- Before an optional V1 relay operation, positively verify the broker credential and write route are unavailable to the implementation agent and subprocesses. Otherwise use the owner-local TTY plan/commit commands. The owner must see the exact operation, repository, Issue/PR and subject SHA/HEAD, then type the plan SHA on the local terminal. A generic continuation, shared credential, browser session or caller-supplied JSON is not consent. Owner-local records are `owner_local_tty_v1` GitHub actor evidence, not signed chat events. If the owner-local TTY, local GitHub auth or pinned identity is unavailable, return `AUTH_TRANSPORT_UNAVAILABLE` without a write.
- `owner_consent.py` verifies immutable V1 delegated records and V2 owner-local records across one append-only history. V2 adds a canonical `plan_sha256` and `evidence_channel=owner_local_tty_v1`; the stable actor ID must be 3744776 and repository ID 1401910271. Reject cross-version operation/subject duplicates, wrong source URLs, edits, deletions, stale subjects, invalid predecessor chains and replay. V1 bytes and semantics remain unchanged.
- ADC_SUPERSEDE, RULESET_PLAN_APPLY, USER_REVIEW, and each PR_MERGE target are separate one-time operations. The owner-local dispatcher emits V2 ordinary decisions or a distinct V2 User Review record. Phase rebaseline remains an automatic #63 execution step after approved ADC publication and has only Intent/Applied technical records. Ruleset apply requires both the exact-plan V2 decision and the exact existing two-line #57 plan approval, then delegates to the canonical one-writer/durable-intent/Admin TTY path. Setup PR merge and PR #64 merge require separate exact-HEAD decisions. The owner-authorize-commit command revalidates the applicable gates after the exact local TTY confirmation, writes a create-only durable merge-attempt record before one GitHub merge request with the exact HEAD precondition, and never retries that request. For Issue #57, require the canonical Activation V2 setup payload, current Ruleset policy, matching ADC generation, all trusted Required Checks, an independent approval on the exact HEAD, and resolved review threads; the Setup PR binds Issue #57 without closing it. For PR #64, require a fresh PASS Final Delivery for the same repository, Issue, PR and HEAD. A lost response or later invocation only reads the PR and attempt record. A merged PR readback must show the exact HEAD, repository, merge commit, and owner actor.
- Preserve `PASES_USER_REVIEW_DECISION_V1` as delegated evidence. `PASES_USER_REVIEW_DECISION_V2` adds `feedback_sha256` and `plan_sha256`, uses `owner_local_tty_v1`, and binds repository/Issue/PR, owner ID, immutable session, Readiness, ADC, current HEAD and the prior complete feedback digest. Direct/list/direct verification checks actual comment URLs, stable actor and predecessor chain. The evaluator receives typed evidence and compares the V2 prior-feedback digest against the current full snapshot excluding the selected carrier; Final Delivery recomputes both. Formal self-approval and use of an ordinary owner-decision record remain invalid.
- The exact integration seam is `evaluate_user_review(session, readiness, current_pr_head_sha40, snapshot, *, review_mode, pr_author_user_id, repository_owner_user_id, authenticated_verifier_user_id, allowed_human_user_ids, relay_approval, all_feedback_surfaces_read, ...)`. For this #63-specific successor ADC, the trusted target identity is pinned above: `repository_owner_user_id=3744776` and repository ID `1401910271`. These values become execution authority only if this ADC is separately approved and published. The read-only caller ID comes from `GET /user` through a dedicated read-only client; it may differ from the owner, has no approval authority, and must never be obtained implicitly through the privileged relay credential. Its read route must be separately scoped from broker writes and positively verified; otherwise the User Review path fails closed. The fresh `GET /repos/{owner}/{repo}` response must match the pinned repository ID, exact `full_name`, `owner.type=User`, and `owner.id=repository_owner_user_id`; a rename, transfer, or identity drift blocks and requires a separately approved successor rather than dynamic rebinding. The current PR response supplies `pr_author_user_id`, which must equal the pinned owner ID. The carrier `owner_id` and actual GitHub comment actor must also equal that pinned ID. Missing or mismatched identity fails closed. `allowed_human_user_ids` comes from approved repository review policy. A formal approval by the PR author is rejected even if allowlisted. The evaluator requires the exact subject across the validated `UserReviewSession`, full `FeedbackSnapshot`, Readiness, current PR HEAD, and typed relay approval. The carrier remains dedicated `user-review-relay` evidence and is never converted into a formal PR review, host-attested chat event, or generic Issue-comment approval. The selected approval's type, comment ID, canonical body SHA-256, owner ID, creation time, session SHA-256, predecessor ID, and evidence channel are persisted in `PASES_USER_REVIEW_RESULT_V2`, bound to the full snapshot SHA-256 and exact subject. Final Delivery repeats full carrier-history and feedback readback, then requires the same selected evidence and result. Existing V1 result records remain immutable and cannot prove this relay path.
- For `RULESET_PLAN_APPLY`, the owner-local commit writes a V2 decision for the exact blocker-free canonical plan and the existing two-line `PASES-RULESET-APPROVE` / `PASES-REPOSITORY` comment to Issue #57. Both records must identify the stable owner and pass direct/list/direct readback. The returned #57 comment ID is passed to the existing owner-local Admin plan/apply continuation; no second Ruleset writer or blind retry is allowed.
- After exact `ADC_SUPERSEDE` approval and publication, the regular authenticated executor automatically replaces only #63's `phase:ready` label with `phase:requirements`, preserving `kind:single` and all other labels. Its Intent/Applied comments record execution and do not grant approval. The rebaseline does not change the Issue body, old Phase Decisions, Gate Selection, ADC history, or existing PR.
- Preserve PRBinding V1 byte-for-byte. A new version may advance only the same repository, Issue #63, PR #64, branch, base SHA, and commit ancestry; validate the append-only ADC journal, old V1 readback, and new ExecutionBinding before the append. Reject gaps, duplicate/non-contiguous versions, stale or backward ADC identity, ancestry mismatch, and any cross-PR/branch/base drift. `pr ensure`, Review Readiness, and Final Delivery validate the latest generation while retaining legacy single-generation compatibility.

<a id="artifact-impact"></a>
## 6 Artifact Impact

Canonical: update `docs/specs/workflow-spec.md` (REQ-F01-008/009/011/013/014/015), `docs/design/workflow-design.md` (DES-F01-011/013/014/015), `docs/testing/pases-lifecycle-tests.md` (TST/ORA-F01-013/014/015), `docs/testing/runtime-tests.md` (TST/ORA-RT-018/019), `docs/testing/traceability.md`, and `workflow/skills/delivery-control/SKILL.md`. Keep this unapproved review copy at `docs/contracts/issue-63-successor-adc-draft.md` until ADC publication. Update `runtime/p_ases/{owner_authorization,owner_consent,user_review_relay,user_review,cli,github,consumer_activation}.py` for the exact Activation-owned base transition while keeping the original ExecutionBinding and PRBinding bytes unchanged. Add the linked base-transition regression cases. Regenerate the three distribution targets with the repository build tool after implementation. The #57 records, #60 ADC, and PR #62 remain unchanged.

<a id="exact-changes"></a>
## 7 Exact Changes

1. Continue the already authorized #63 implementation while revising this local successor-ADC draft and linked specification/design/oracle/traceability. Commit and push the complete implementation to the existing PR #64. This does not publish or approve the ADC, change Issue phase, authorize any owner decision, or permit Ruleset writes. Keep #57 and #60 read-only.
2. Before declaring implementation ready, validate that every referenced test source, document link, anchor, and commit exists and matches the successor ADC. Missing test files may make draft validation fail before this check; no fake paths or permanent skips are allowed.
3. `runtime/p_ases/{branch_policy,profile,github}.py`の#62互換基盤、`runtime/p_ases/ruleset_management.py`（plan/approval/唯一の対象へのPOST/PUT/NOOP）、`runtime/p_ases/consumer_activation.py`（V2/冪等発行）、`runtime/p_ases/{gate_policy,phase_evidence}.py`（prefix検証）を実装。`phase_rebaseline.py` verifies the approved ADC predecessor/successor pointer chain, writes a canonical Intent before the single permitted #63 label PUT, double-reads Issue/ADC, writes Applied evidence, and recovers without repeating the PUT.
4. `runtime/p_ases/cli.py`へ`delivery consumer-activation-preflight`、`delivery consumer-activation-ruleset-plan --output <path>`、`delivery consumer-activation-ruleset-apply --plan <path> --approval-comment-id <id>`、owner-local admin continuation、V2 setup/verifyを統合する。通常ユーザーは`consumer-activation-setup`だけで再開可能なActivation処理を開始する。関連Skill更新、`dist/{openai,claude,antigravity}`を生成。
5. **後続ADC正式化→Phase更新**: 最新草案の全文・SHAをownerへreadbackし、当該SHAに対する別個のexact `ADC_SUPERSEDE`承認を取得してappend-onlyで正式発行する。pointerとforward generationをreadbackした後、認証済みP-ASES executorが#63のIntent/一度限りのlabel PUT/Appliedを実行し、IssueとADCを再readbackする。`PHASE_REBASE` decisionは要求せず、必須のIntent/Applied技術記録を残す。
6. **Activation V2 ACTIVE**: successor ADCとPhase証跡成立後、blocker-free canonical Ruleset planに別のexact `RULESET_PLAN_APPLY`承認が必要なら取得する。既存のone-writer/durable-intent/apply/readback経路とowner-local Admin TTYを使う。Activation Setup PRを別途review/mergeした後、V2 recordのID・`created_at`・Ruleset/policyをreadbackして`ACTIVE`を確定する。Setup PR mergeだけではActivation完了ではない。PR #64はこの時点では未mergeのまま保持する。
7. **PR #64とIssue #63**: `ACTIVE`後にPR #64のActivation由来base advance証跡、最新HEAD/CI、independent review、User Review、Final Deliveryを再評価し、別のexact-HEAD `PR_MERGE`承認後に既存PR #64をmergeする。`Closes #63`とmerge SHAをreadbackし、自動closeされなければ別途正規closeしてIssue stateを再readbackする。PR #62/#60は変更しない。
8. Keep the two admin commands and TTY session boundary exactly as in D6. `consumer-activation-setup` owns orchestration and directs a resumable continuation to those commands only when the persisted stage requires it. Reuse the current canonical Ruleset plan, Issue #57 approval verification, durable intent, one-write apply, and effective-policy readback paths; do not add aliases or a second apply implementation.
9. Implement V1/V2 ordinary owner-decision history verification, the owner-local create-only plan/TTY/commit/read-only resume transport, the separate V1/V2 User Review verifier and evaluator integration, all distinct operation scopes, #63 approved-ADC-backed automatic phase rebaseline, and forward-only PRBinding successor generation exactly as in REQ-F01-015 and D7. Keep USER_REVIEW records out of `owner_consent.py`. The owner-local transport writes only after local TTY confirmation and authenticated owner verification; broker records remain optional and require a positively verified capability boundary.

<a id="activation-owned-current-base-transition"></a>
### 7.1 Activation-owned current-base transition

The immutable `ExecutionBinding` and original V1 `PRBinding` retain frozen base A. Accept base B only when the current default branch is exactly the Activation V2 setup PR merge commit; A is its first parent; the setup PR and setup commit are bound by the V2 record; both diffs change only `.agent/project.json`; the Activation record, setup PR, target PR, repository and Issue identities match; and profile bytes on B and the exact target PR HEAD match the recorded Activation profile digest. The target PR must preserve its original code patch while integrating B. Store the proof as create-only typed evidence, append a V2 PRBinding generation referencing it, and revalidate it in `pr ensure`, Readiness, and Final Delivery. Any other main advancement, profile mismatch, identity mismatch, missing proof, or unrelated commit blocks.

<a id="invariants"></a>
Before implementation is reported ready, `tests/test_user_review_relay.py` MUST exercise the same-session evaluator integration and persisted `PASES_USER_REVIEW_RESULT_V2` evidence, including a read-only verifier ID distinct from the owner, wrong carrier actor, wrong PR author/owner, executor self-approval rejection, actual wrong-Issue/wrong-repository comment URLs, and direct/list/direct disagreement, as well as pre-session/equal timestamps, genesis/orphan/skipped predecessors, replay, incomplete pagination, edits, deletion, changed feedback, and unresolved threads. Runtime and tests may be completed under the explicit implementation authorization in the Activation addendum; `ADC_SUPERSEDE` publication requires its exact approval and verified relay, while phase rebaseline executes automatically afterward through the authenticated P-ASES workflow executor.

The selected-evidence object for V1 retains exactly `evidence_type, evidence_channel, comment_id, body_sha256, owner_id, created_at, review_session_sha256, predecessor_comment_id`. V2 adds `feedback_sha256` and `plan_sha256`, and carries `evidence_type=PASES_USER_REVIEW_DECISION_V2` with `evidence_channel=owner_local_tty_v1`. The result binds this typed object to the full `snapshot_sha256` and exact User Review subject.
## 8 Invariants

- The V1 #57 Activation ADC, pointer, approval, record, original `merged_at`, and each prior Issue's ADC/Gate Selection/PR/evidence remain immutable.
- Existing Issues are never auto-migrated to V2. The current live Final Delivery policy continues to fail closed on unavailable or mismatched protection.
- Ruleset mutation requires an exact plan plus a separately confirmed `RULESET_PLAN_APPLY` decision and owner-local V2 or verified-relay Issue #57 approval comment; this ADC approval does not grant that permission.
- Only the uniquely owned P-ASES repository Ruleset may be created or changed. No silent changes to unrelated Rulesets, legacy branch protection, bypass actors, or repository authorization.
- Keep approved #60 behavior confined to #60; use one shared policy API and preserve the original Issue #60 closing association.
- Never ask the agent to receive or display the PAT. Never pass it through CLI args, files, JSON, logs, chat, `os.environ`, default `gh` auth, or unrelated child processes.
- GitHub-side PAT revocation is the owner’s explicit post-use action; local cleanup must not be reported as revocation.

<a id="non-goals"></a>
## 9 Non-goals

- [ ] 既存#57 V1および#60/PR #62の本文/ADC/Gate Selection/証跡を変更・再承認しない
- [ ] #63の修正で#60のレビュー/mergeを代行しない。#49/#61/#41/#46の改修を混在させない
- [ ] Ruleset writeは本人のexact-plan承認後のみ。ownerの無関係Settings、legacyや組織Rulesetを変更しない
- [ ] V1/V2の認可、実効時刻、履歴prefix、新Issue full-historyを別々に検証
- [ ] 認証・race・重複・失敗時の停止と安全なresumeをテストする
- [ ] spec→design→tests→traceability・3 distributionが同期する
- [ ] コミット・push・PR作成（`Closes #63`）・self/独立review・CI・別subjectのUser Review/PR_MERGE承認・正規owner-local merge実行・Issue closure readbackを報告する

<a id="verification-obligations"></a>
## 10 Verification Obligations

- 旧V1/旧IssueのADC・Gate Selection・phase/PR不変。後続V2だけ破損→旧Issue PASS/新Issue BLOCK、元V1改変→旧Issue BLOCK。
- V2の記録前後でIssue作成日時を比較し、PR merge日時でV2を誤選択しない。
- 空→1 POST、同一→NOOP、承認済みowned ID変更→1 PUT。それ以外・同名collision・承認なし・403・race・partial write→BLOCK/二重作成なし。
- wrong branch、Check name/App ID、approve count、force push、bypass、inactive enforcement、legacy conflict→VERIFIED不可。
- 非TTY/getpass cancellation/空入力/identity mismatch/admin不足/403/不完全readback/blocked plan/未承認apply/driftではRuleset POST/PUTが0回。正常時もIssue #57のexact-plan承認後に既存の1回write経路だけを通る。
- self-authored `solo_owner` User Review verifies exact repo/Issue/PR/HEAD/Readiness/ADC/session and full prior feedback, then uses V1 only through a verified isolated relay or V2 through the owner-local TTY. The V2 carrier binds prior feedback and plan digests and is read back direct/list/direct before it reaches the normal evaluator. Formal self-approval, ordinary `PASES_OWNER_DECISION_V1`, generic continuation, stale subject, replay, incomplete feedback and unresolved threads never approve. Eligible external reviewers continue through the native formal review path. User Review does not authorize independent review or PR merge.
- token markerはargv/log/file/JSON/chat/os.environ/unrelated child/default authに現れず、例外・中断後の通常GitHub requestにも残らない。POST/PUT中断後の再開はread-only recoveryで二重writeしない。
- admin-planとadmin-applyは別々にTTY認証し、owner操作後のGitHub UIでのPAT revokeを記録する。Codex環境がTTYを提供しない場合はlive activationをBLOCKEDとする。
- Activation Setup PRは#64より先にmergeするが、それだけでは#64をmergeできない。V2 `ACTIVE`後に#64のexact HEAD gatesをすべて再評価する。base A→Bは検証済みのSetup PR遷移だけを許可し、通常のbase drift、未知のmain commit、profile相違を拒否する。旧PRBinding bytesは不変。
- commands: `python -m compileall runtime tools tests`, `python -m unittest discover -s tests -p 'test_*.py'`, `python -m p_ases docs validate --root .`, `python tools/build_dist.py --check`, `python tools/validate_dist.py`。既存3系統traceability/16 Skills acceptance/Ubuntu・Windows・macOSの4 Required Checksも実行してexact HEAD/App IDを検証。live管理API実測ができなければBLOCKED。

<a id="reviewer-checklist"></a>
## 11 Reviewer Checklist

- [ ] Activation, rather than the end user, orchestrates all profile-required and in-scope GitHub provisioning.
- [ ] An empty Ruleset produces a resumable plan/approval state instead of an unexplained prerequisite failure.
- [ ] Setup PR profile bytes and exact commit are bound to the canonical policy plan before privileged apply.
- [ ] Exact owner approval and local Admin credentials remain separate; Codex has neither credential nor relay write route.
- [ ] Ruleset management uses the existing single plan/apply/readback writer and never duplicates POST/PUT on recovery.
- [ ] Existing #57 V1, #60/PR #62, predecessor #63 ADC, Gate Selections, and historical evidence remain untouched.
- [ ] V2 and User Review/Final Delivery remain exact-subject, full-readback, and fail closed.
- [ ] Successor ADC/Phase receipts complete before Activation; Activation V2 is fully `ACTIVE` before PR #64 merge.
- [ ] Activation Setup PR merge and PR #64 merge use separate exact-HEAD review/merge decisions.
- [ ] The one-time A→B current-base evidence proves the exact Activation merge, profile-only diff, matching profile bytes, and unchanged PR code patch; old V1 Binding bytes are unchanged.
- [ ] Required tests, traceability, generated distributions, and four exact-HEAD CI checks pass.
- [ ] PR #64 remains open until its separate current-HEAD review, User Review, merge authorization, and closure readbacks pass.

## 12 Completion Gates
<a id="completion-gates"></a>

- Implementation, local tests, documentation, distributions, and PR preparation are authorized to proceed while the successor ADC remains an unapproved draft. Keep the published predecessor, #57 V1, #60/PR #62, Issue phase, and all GitHub policy/evidence read-only.
- Before implementation is marked ready, verify all referenced tests, links, anchors and commits, then read back the complete successor draft bytes and SHA. A changed draft SHA requires a fresh exact ADC_SUPERSEDE decision; an earlier SHA approval cannot transfer. Phase bootstrap remains automatic only after approved ADC publication. This contract does not authorize ADC publication, Ruleset writes, Activation, or PR merge.
- First finish implementation on existing PR #64 and record the final successor ADC bytes/SHA. Obtain an exact-SHA `ADC_SUPERSEDE` approval, publish/read back the successor, automatically rebaseline #63 with Intent/Applied evidence, and establish its Phase receipts before Activation.
- Complete Activation V2 to `ACTIVE` before merging PR #64. Any necessary Ruleset change requires its own exact plan approval and the trusted owner-local Admin TTY continuation; the Setup PR has its own merge gate.
- After `ACTIVE`, revalidate PR #64's current base proof, exact HEAD, four Required Checks, Independent Review, User Review, Final Delivery, and separate `PR_MERGE` approval. Merge #64 and read back its merge SHA and Issue #63 close state. If any external gate is unavailable, report `IMPLEMENTATION_READY / ACTIVATION_DELIVERY_BLOCKED` and do not claim completion.
- Report changed files, contract checklist/acceptance outcomes, exact test commands/results, CI and unverified environments, A/B/C/D review findings, deviations/blockers, missing operation-specific approvals/Admin boundary evidence, and the existing PR URL. Separate implementation readiness from Activation delivery readiness.

This document is an Implementation Contract. Do not redesign the architecture during implementation. If a requirement conflicts with repository reality or requires a material design change, do not silently choose an alternative. Report the exact conflict and continue only with independent valid work.
