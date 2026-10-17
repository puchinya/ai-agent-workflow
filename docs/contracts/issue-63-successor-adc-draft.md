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
- REQ-F01-015: For delegated GitHub relay operations, the owner must receive a ChatGPT readback of the exact operation, repository, Issue/PR, and subject SHA/HEAD, then directly confirm that operation in chat. A generic request to continue, Issue comment, model-generated text, CLI flag, or caller-supplied JSON is not an operation-specific decision. An isolated ChatGPT relay broker owns the GitHub write credential and connector route; the Codex implementation runtime and its subprocesses have neither that credential nor a write-capable route. The stable GitHub actor ID alone cannot distinguish the broker from the executor, so failure to verify this permission/tool boundary blocks the write. Broker actions are delegated GitHub evidence, not signed or host-attested chat events. The four ordinary relay operations (`PHASE_REBASE`, `ADC_SUPERSEDE`, `RULESET_PLAN_APPLY`, `PR_MERGE`) use canonical `PASES_OWNER_DECISION_V1` records with exact subject and predecessor comment ID, appended and read back only after direct operation-specific confirmation. `USER_REVIEW` remains separate: retain the host-attested direct-chat route and eligible external reviewer's native formal PR-review path; for a self-authored PR in `solo_owner` mode, use a separate canonical `PASES_USER_REVIEW_DECISION_V1` record. This record binds repository, Issue, PR, stable owner ID, immutable session ID, Readiness digest, exact PR HEAD, approved ADC digest, and predecessor comment ID, and may be used once only for that session after exact readback and direct confirmation. It is neither a formal PR approval nor a `PASES_OWNER_DECISION_V1` record or host attestation. No relay evidence itself proves chat authorship. For #63, one bootstrap-only exception is permitted because ordinary phase advancement does not support `ready` to `requirements` and new-generation receipts require that transition. After the exception is included in and separately confirmed against the exact successor ADC SHA, only the isolated relay may double-read the open Issue, complete label set, predecessor ADC bytes and pointer journal, append/read back the `PHASE_REBASE` decision, replace the single phase label, and perform complete post-write readbacks. This is not a general phase transition route. `ADC_SUPERSEDE` is separately confirmed for that same exact SHA and published append-only by the isolated relay with pointer-journal readback. Once implemented, `phase_rebaseline.py` verifies the already completed bootstrap and returns a no-op; it blocks if bootstrap evidence or the changed phase label is missing and never issues a second label write. The #57 Ruleset comment remains an exact-plan exception; PR merge remains separately authorized after all gates. Existing PRBinding V1 remains immutable and successor generations remain forward-only for the same execution identity.

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
- 書込が必要なとき、本人はChatGPTからrepository、Activation Issue、operation、plan SHAをreadbackされ、`RULESET_PLAN_APPLY`を別途直接確認する。分離済みGitHub relayがdecisionを追記・readbackし、broker境界とstable owner ID・exact subjectを検証できた後に限り、#57へ次の完全一致コメントをAPIで追記する（Codex実装エージェントによる投稿は禁止）。これはこの後継ADCで定義するrelay限定例外であり、未承認または別SHAでは実行しない。
  ```text
  PASES-RULESET-APPROVE: <64桁plan SHA-256>
  PASES-REPOSITORY: puchinya/ai-agent-workflow
  ```
  既存apply CLIは中継者が記録したcomment ID・actor stable User ID・未編集本文・Issue/repo・exact plan・direct/list/direct readbackを検証する。ChatGPT relayがGitHub上で行った記録はdelegated GitHub evidenceであり、host署名済みchat eventとは扱わない。User Reviewのraw chat decision入力は既存host-attested境界を維持する。self-authored `solo_owner` PRにはformal self-approvalを使わず、別schemaの`PASES_USER_REVIEW_DECISION_V1`を専用runtime verifierで検証する。このcanonical Issue commentはrepo/Issue/PR、stable owner ID、immutable session ID、Readiness SHA、ADC SHA、exact HEAD、predecessor comment IDを束縛し、同一sessionに一度だけ有効。direct/list/direct readback、重複・編集・削除・別session replay拒否を必須とする。eligible external reviewerはnative formal PR reviewを使える。専用recordは`PASES_OWNER_DECISION_V1`、formal GitHub review、host署名済みchat eventのいずれでもない。
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
- No credential is approval. The owner separately confirms the exact plan SHA through `RULESET_PLAN_APPLY`; only the ChatGPT GitHub relay appends the existing exact approval comment on #57 under this successor ADC's scoped exception. Existing durable intent, one-write/no-op semantics, readback, V1/V2 history, PR #64, #57 V1, and #60/PR #62 remain unchanged. Admin authentication and Ruleset approval do not approve PR merge.

**D7 — Delegated owner decision relay**

- Before each relay operation, ChatGPT reads back the exact operation, repository, Issue/PR, and ADC/plan SHA or PR HEAD and waits for the owner's direct, operation-specific chat confirmation. A generic continuation does not authorize a write. A separately permissioned ChatGPT relay broker must own the GitHub write credential and connector route; the Codex implementation agent, runtime, and subprocesses must have neither that credential nor a write-capable route. The stable GitHub actor ID alone cannot distinguish a broker write from an implementation-executor write. The deployment must positively verify broker/credential scoping before any relay write; the contract or chat confirmation is not that proof. If the separate permission/tool boundary is absent, unavailable, or inconclusive, block all relay writes. Broker GitHub records are delegated evidence; never call them host attestations or cryptographically signed chat events. Cloud implementation does not require a Chat host signature, browser OAuth, or interactive TTY for this relay path.
- The independent `owner_consent.py` verifier parses canonical append-only `PASES_OWNER_DECISION_V1` fields: `schema, repository, issue_number, operation, subject_sha256, pr_number, pr_head_sha40, owner_id, evidence_channel, predecessor_comment_id`; unused PR fields are null and `evidence_channel` is exactly `delegated_github_relay`. The GitHub relay appends the record and reads it back. Runtime verifies canonical bytes, stable owner ID, unchanged direct/list/direct readback, monotonic comment IDs, one-time operation/subject use, and the current subject. A GitHub record verifies the relay actor and delegated action; it does not prove chat authorship. The implementation executor cannot write a decision under the owner's name.
- The five decisions `PHASE_REBASE`, `ADC_SUPERSEDE`, `RULESET_PLAN_APPLY`, `USER_REVIEW`, and `PR_MERGE` are separate and one-time. The four ordinary GitHub relay operations have `PASES_OWNER_DECISION_V1` records. User Review retains its host-attested direct-chat path and eligible native external-reviewer path; for a self-authored PR in `solo_owner` mode, it uses a dedicated `PASES_USER_REVIEW_DECISION_V1` record, never a formal self-approval or `PASES_OWNER_DECISION_V1`. The dedicated record is appended to Issue #63 by the isolated broker only after exact repo/Issue/PR/HEAD/Readiness/ADC/session readback and a separate direct `USER_REVIEW` confirmation. It binds stable owner ID, immutable session ID, Readiness digest, ADC digest, and current HEAD, is read back directly/list/directly, and is accepted once for that session by the User Review evaluator. It is delegated GitHub evidence, not a host-attested chat event or formal PR review. The first two decisions bind the exact successor ADC SHA. Ruleset approval binds a blocker-free exact plan SHA. User Review and merge bind the current PR HEAD; merge additionally requires all independent CI/review/Final Delivery gates. No decision implies another.
- `PASES_USER_REVIEW_DECISION_V1` has exactly `schema, repository, issue_number, pr_number, decision, owner_id, review_session_id, readiness_sha256, adc_sha256, pr_head_sha40, evidence_channel, predecessor_comment_id`; `decision=APPROVED`, and `evidence_channel=delegated_github_relay`. `review_session_id` equals `PASES_USER_REVIEW_SESSION_V1.session_sha256`. The GitHub comment actor ID must equal `owner_id`; its creation time must be strictly later than the validated session's immutable `started_at`, and `updated_at` must equal `created_at`. The verifier requires canonical bytes, complete pagination, and direct/list/direct equality for every dedicated carrier in the `(repository, issue, PR, owner_id)` chain. Each carrier's actual GitHub `url`, `issue_url`, and `html_url` must identify the configured host, exact repository, Issue, and comment ID, and match across direct/list/direct reads; body-declared identity is insufficient. Chain genesis uses a null predecessor; every successor points to the immediately preceding valid carrier comment with strictly increasing IDs. It rejects wrong source URLs, orphaned, missing, skipped, edited, deleted, duplicate, replayed, or wrong-session records and returns one typed `UserReviewRelayApproval` for the exact current session.
- The exact integration seam is `evaluate_user_review(session, readiness, current_pr_head_sha40, snapshot, *, review_mode, pr_author_user_id, repository_owner_user_id, authenticated_verifier_user_id, allowed_human_user_ids, relay_approval, all_feedback_surfaces_read, ...)`. For this #63-specific successor ADC, the trusted target identity is pinned above: `repository_owner_user_id=3744776` and repository ID `1401910271`. These values become execution authority only if this ADC is separately approved and published. The read-only caller ID comes from `GET /user` through a dedicated read-only client; it may differ from the owner, has no approval authority, and must never be obtained implicitly through the privileged relay credential. Its read route must be separately scoped from broker writes and positively verified; otherwise the User Review path fails closed. The fresh `GET /repos/{owner}/{repo}` response must match the pinned repository ID, exact `full_name`, `owner.type=User`, and `owner.id=repository_owner_user_id`; a rename, transfer, or identity drift blocks and requires a separately approved successor rather than dynamic rebinding. The current PR response supplies `pr_author_user_id`, which must equal the pinned owner ID. The carrier `owner_id` and actual GitHub comment actor must also equal that pinned ID. Missing or mismatched identity fails closed. `allowed_human_user_ids` comes from approved repository review policy. A formal approval by the PR author is rejected even if allowlisted. The evaluator requires the exact subject across the validated `UserReviewSession`, full `FeedbackSnapshot`, Readiness, current PR HEAD, and typed relay approval. The carrier remains dedicated `user-review-relay` evidence and is never converted into a formal PR review, host-attested chat event, or generic Issue-comment approval. The selected approval's type, comment ID, canonical body SHA-256, owner ID, creation time, session SHA-256, predecessor ID, and evidence channel are persisted in `PASES_USER_REVIEW_RESULT_V2`, bound to the full snapshot SHA-256 and exact subject. Final Delivery repeats full carrier-history and feedback readback, then requires the same selected evidence and result. Existing V1 result records remain immutable and cannot prove this relay path.
- For `RULESET_PLAN_APPLY`, after a separate exact-plan chat confirmation and only under this approved successor ADC, the delegated relay may append the existing two-line `PASES-RULESET-APPROVE` / `PASES-REPOSITORY` comment to #57. The comment must read back with the configured stable owner User ID expected by existing Ruleset verification; an unknown actor blocks. This is a relay-only, exact-plan-scoped exception to the predecessor's agent-posting prohibition; existing apply, durable intent, one-write and readback logic remains unchanged.
- `PHASE_REBASE` permits the relay to replace only #63's labels from `phase:ready` to `phase:requirements` for the exact approved successor ADC, preserving `kind:single` and all other labels. It does not authorize `ADC_SUPERSEDE`; that publication requires its own exact-SHA decision. Neither operation changes the Issue body, old Phase Decisions, Gate Selection, ADC, or existing PR.
- Preserve PRBinding V1 byte-for-byte. A new version may advance only the same repository, Issue #63, PR #64, branch, base SHA, and commit ancestry; validate the append-only ADC journal, old V1 readback, and new ExecutionBinding before the append. Reject gaps, duplicate/non-contiguous versions, stale or backward ADC identity, ancestry mismatch, and any cross-PR/branch/base drift. `pr ensure`, Review Readiness, and Final Delivery validate the latest generation while retaining legacy single-generation compatibility.

<a id="artifact-impact"></a>
## 6 Artifact Impact

Canonical: update `docs/specs/workflow-spec.md` (REQ-F01-014/015), `docs/design/workflow-design.md` (DES-F01-014/015), `docs/testing/pases-lifecycle-tests.md` (TST/ORA-F01-014/015), `docs/testing/runtime-tests.md` (TST/ORA-RT-018/019), and `docs/testing/traceability.md`. Keep this unapproved review copy at `docs/contracts/issue-63-successor-adc-draft.md` until ADC publication. Update `runtime/p_ases/github.py`, add `runtime/p_ases/admin_auth.py`, `runtime/p_ases/owner_consent.py`, and `runtime/p_ases/user_review_relay.py`, update `runtime/p_ases/cli.py`, `runtime/p_ases/phase_rebaseline.py`, and `workflow/skills/{delivery-control,user-review}/SKILL.md`. Add `tests/test_admin_auth.py`, `tests/test_owner_consent.py`, `tests/test_phase_rebaseline.py`, and `tests/test_user_review_relay.py`; extend `tests/test_github_checks.py`, `tests/test_p_ases_cli.py`, and `tests/test_ruleset_management.py`. Before Ready, all test paths linked by traceability must exist as actual source files in a commit; they may be failing test-driven scaffolds until implementation. Regenerate the three distribution targets with the repository build tool after implementation. The existing `.agent/project.json`, #57 records, #60 ADC, and PR #62 remain unchanged.

<a id="exact-changes"></a>
## 7 Exact Changes

1. Continue the already authorized #63 implementation while revising this local successor-ADC draft and linked specification/design/oracle/traceability. Commit and push the complete implementation to the existing PR #64. This does not publish or approve the ADC, change Issue phase, authorize any owner decision, or permit Ruleset writes. Keep #57 and #60 read-only.
2. Before declaring implementation ready, validate that every referenced test source, document link, anchor, and commit exists and matches the successor ADC. Missing test files may make draft validation fail before this check; no fake paths or permanent skips are allowed.
3. `runtime/p_ases/{branch_policy,profile,github}.py`の#62互換基盤、`runtime/p_ases/ruleset_management.py`（plan/approval/唯一の対象へのPOST/PUT/NOOP）、`runtime/p_ases/consumer_activation.py`（V2/冪等発行）、`runtime/p_ases/{gate_policy,phase_evidence}.py`（prefix検証）を実装。`phase_rebaseline.py`はbootstrap decisionと完了済みlabel setを検証するread-only/no-op routeであり、broker bootstrapのlabel writeを再実行しない。
4. `runtime/p_ases/cli.py`へ`delivery consumer-activation-preflight`、`delivery consumer-activation-ruleset-plan --output <path>`、`delivery consumer-activation-ruleset-apply --plan <path> --approval-comment-id <id>`、owner-local admin continuation、V2 setup/verifyを統合する。通常ユーザーは`consumer-activation-setup`だけで再開可能なActivation処理を開始する。関連Skill更新、`dist/{openai,claude,antigravity}`を生成。
5. **初回ブートストラップ（別途承認が必要なdelivery gate）**: successor ADC/phase evidence成立後、Activation checkpointのblocker-free plan SHAについて別のexact `RULESET_PLAN_APPLY` direct chat confirmationを得る。実行境界を独立に検証できる場合のみChatGPT GitHub relayが#57へ既存exact approval commentを追記する。所有者は信頼済みlocal TTY Admin continuationから同一checkpointのapply/readbackを実行する。これは実装・CI・review preparationを待たせない。#63のUser Review/独立レビュー/Final Delivery/PR mergeは**省略しない**。各operationには別のexact subject decisionが必要であり、権限・承認が欠ける場合はDeliveryをBLOCKEDとし、強行mergeしない。
6. #63 merge後は、mainで後継V2 Activation setup PR→検証・記録を実施。Rulesetが一致していればNOOP。PR #62は同じPRのままmainへ追従、重複共有基盤差分を解消、#60独自のレビュー/最終判定を再実行する。
7. Keep the two admin commands and TTY session boundary exactly as in D6. `consumer-activation-setup` owns orchestration and directs a resumable continuation to those commands only when the persisted stage requires it. Reuse the current canonical Ruleset plan, Issue #57 approval verification, durable intent, one-write apply, and effective-policy readback paths; do not add aliases or a second apply implementation.
8. Implement the owner-decision verifier for the four ordinary delegated GitHub relay operations, the separate `PASES_USER_REVIEW_DECISION_V1` verifier and evaluator integration for self-authored `solo_owner` PRs, five distinct one-time decision types, #63 phase rebaseline, and forward-only PRBinding successor generation exactly as in REQ-F01-015 and D7. Keep `USER_REVIEW` records out of `owner_consent.py`. The relay-only #57 plan-approval comment and User Review evidence record are enabled only by this approved successor ADC; the implementation executor has no relay write credential/route and cannot submit either in the owner's name.

<a id="invariants"></a>
Before implementation is reported ready, `tests/test_user_review_relay.py` MUST exercise the same-session evaluator integration and persisted `PASES_USER_REVIEW_RESULT_V2` evidence, including a read-only verifier ID distinct from the owner, wrong carrier actor, wrong PR author/owner, executor self-approval rejection, actual wrong-Issue/wrong-repository comment URLs, and direct/list/direct disagreement, as well as pre-session/equal timestamps, genesis/orphan/skipped predecessors, replay, incomplete pagination, edits, deletion, changed feedback, and unresolved threads. Runtime and tests may be completed under the explicit implementation authorization in the Activation addendum; relay writes, phase rebaseline, and ADC publication still require their separate approvals and verified execution boundary.

The selected-evidence object has exactly `evidence_type, evidence_channel, comment_id, body_sha256, owner_id, created_at, review_session_sha256, predecessor_comment_id`, where `evidence_type=PASES_USER_REVIEW_DECISION_V1` and `evidence_channel=delegated_github_relay`. The result stores `selected_approval_event=user-review-relay:<comment_id>` and that object; the V2 result wrapper binds its digest to `snapshot_sha256` and the exact User Review subject.
## 8 Invariants

- The V1 #57 Activation ADC, pointer, approval, record, original `merged_at`, and each prior Issue's ADC/Gate Selection/PR/evidence remain immutable.
- Existing Issues are never auto-migrated to V2. The current live Final Delivery policy continues to fail closed on unavailable or mismatched protection.
- Ruleset mutation requires an exact plan plus a separately confirmed `RULESET_PLAN_APPLY` decision and relay-recorded Issue #57 approval comment; this ADC approval does not grant that permission.
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
- [ ] コミット・push・PR作成（`Closes #63`）・self/独立review・CI・別subjectのUser Review/PR_MERGE承認・ブローカー実行のmerge・Issue closure readbackを報告する

<a id="verification-obligations"></a>
## 10 Verification Obligations

- 旧V1/旧IssueのADC・Gate Selection・phase/PR不変。後続V2だけ破損→旧Issue PASS/新Issue BLOCK、元V1改変→旧Issue BLOCK。
- V2の記録前後でIssue作成日時を比較し、PR merge日時でV2を誤選択しない。
- 空→1 POST、同一→NOOP、承認済みowned ID変更→1 PUT。それ以外・同名collision・承認なし・403・race・partial write→BLOCK/二重作成なし。
- wrong branch、Check name/App ID、approve count、force push、bypass、inactive enforcement、legacy conflict→VERIFIED不可。
- 非TTY/getpass cancellation/空入力/identity mismatch/admin不足/403/不完全readback/blocked plan/未承認apply/driftではRuleset POST/PUTが0回。正常時もIssue #57のexact-plan承認後に既存の1回write経路だけを通る。
- self-authored `solo_owner` Cloud User Reviewはexact repo/Issue/PR/HEAD/Readiness/ADC/session readback→別の直接`USER_REVIEW`確認→isolated brokerによる一度の`PASES_USER_REVIEW_DECISION_V1` Issue comment→direct/list/direct readback→通常feedback evaluatorの順。formal self-approval、`PASES_OWNER_DECISION_V1`の流用、未確認、generic continuation、stale subject、別session replay、不完全feedbackでは承認を拒否する。eligible external reviewerのformal reviewは従来通りactor ID/type・state・commit・session時刻を評価する。User Review結果は独立reviewやPR_MERGEを許可しない。
- token markerはargv/log/file/JSON/chat/os.environ/unrelated child/default authに現れず、例外・中断後の通常GitHub requestにも残らない。POST/PUT中断後の再開はread-only recoveryで二重writeしない。
- admin-planとadmin-applyは別々にTTY認証し、owner操作後のGitHub UIでのPAT revokeを記録する。Codex環境がTTYを提供しない場合はlive activationをBLOCKEDとする。
- PR #63をmerge前のbranch runtimeで整備できるがUser Review/CIは省略できない。#62をrebaseしても#60の`Closes #60`とADCは不変。
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
- [ ] The first #63 bootstrap can precede PR #64 merge; normal Activation after merge recognizes the same policy as NOOP.
- [ ] Required tests, traceability, generated distributions, and four exact-HEAD CI checks pass.
- [ ] PR #64 remains open until its separate current-HEAD review, User Review, merge authorization, and closure readbacks pass.

## 12 Completion Gates
<a id="completion-gates"></a>

- Implementation, local tests, documentation, distributions, and PR preparation are authorized to proceed while the successor ADC remains an unapproved draft. Keep the published predecessor, #57 V1, #60/PR #62, Issue phase, and all GitHub policy/evidence read-only.
- Before the implementation is marked ready, verify every referenced test source, link, anchor, and commit. Read back the full successor draft bytes and SHA. Any future `PHASE_REBASE` and `ADC_SUPERSEDE` still require separate direct operation-specific approval for that same exact SHA and the verified isolated relay; this implementation contract does not grant either approval or publish the draft.
- The #63 pre-merge Ruleset bootstrap still requires a separate exact blocker-free `RULESET_PLAN_APPLY` decision, relay-bound approval evidence, and owner-local Admin TTY apply/readback. If any external gate is unavailable, report Activation/Delivery as blocked and continue no unauthorized GitHub write.
- Pass the requested local checks and exact-head CI, complete self-review, independent review, User Review and verified Final Delivery, then commit and push to existing PR #64 while preserving its standalone `Closes #63` reference. Do not merge.
- Report changed files, contract checklist/acceptance outcomes, exact test commands/results, CI and unverified environments, A/B/C/D review findings, deviations/blockers, missing operation-specific approvals/Admin boundary evidence, and the existing PR URL. Separate implementation readiness from Activation delivery readiness.

This document is an Implementation Contract. Do not redesign the architecture during implementation. If a requirement conflicts with repository reality or requires a material design change, do not silently choose an alternative. Report the exact conflict and continue only with independent valid work.
