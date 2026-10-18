# Agent Development Contract — issue-63-activation-ruleset-management-successor

Repository: puchinya/ai-agent-workflow
Trusted repository identity for this contract: GitHub repository ID `1401910271`; repository owner User ID `3744776`.
Issue: 63
Parent contract: none
Predecessor ADC: Issue #63 comment #6244160653, SHA-256 `f1cab9b9edca34d4e80c486642059881b62abd5d95b993999a52494494bafac8`
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

The current approved pointer journal names comment `#6244160653` as the predecessor even though that immutable comment body says `Draft only`. This final successor records the pointer journal's actual current predecessor and does not edit or reinterpret the historical comment, pointer, owner decision, or Phase evidence.

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
- REQ-F01-013: #63 shall use a two-stage completion order: exact successor ADC and Phase receipts; verify the solo-owner effective Ruleset and all normal #64 gates; merge existing PR #64 with a unique standalone `Refs #63` association while Issue #63 remains OPEN; then complete Activation V2 from current main and close #63 only after a later V2 `created_at`, owned Ruleset, and effective policy are read back. The shared closer detector covers GitHub's case-insensitive close/closes/closed, fix/fixes/fixed, and resolve/resolves/resolved forms, an optional colon, and either `#N` or `OWNER/REPO#N`; repository-qualified references are normalized case-insensitively before Issue identity is compared. Before merge, inspect the PR body, all commit messages, planned merge message, GitHub `closingIssuesReferences`, and Issue cross-reference metadata with this same detector; any auto-close token/link or incomplete read blocks. PR #64's `PR_MERGE` approval and the Setup PR's decision are separate. Independent Review is produced by one dedicated fresh native host subagent that reads the exact full contract, checklist, diff, and tests; the host owns spawn/join/cancel and verifies actual spawn/session, reviewer, and implementation-binding identities. The child-authored raw result maps its own context ID to `context_id` and compact canonical provenance JSON to `provenance`; the parent compares those values to host metadata and the current binding and passes the unedited artifact to the existing audit. The host authenticates spawn provenance; runtime does not authenticate host metadata or spawn agent binaries, and a distinct context ID alone is not proof. Missing or unverifiable host provenance, a stale result, unavailable child, or same-head no-progress retry blocks readiness and starts no User Review. After Independent Review and all other required gates PASS, a PASS from `delivery readiness` automatically starts exactly one User Review session without another confirmation; starting a session is not approval.
- REQ-F01-014: Activation Admin commands default to isolated browser device auth using a private mode-0700 `GH_CONFIG_DIR`, `gh auth login --web`, and a runner-managed PTY when available; owner-local TTY is not required. PAT is explicit nonstandard fallback only. Strip ambient tokens from scoped children, preserve normal `gh`, verify owner/repository/admin identity and complete policy reads, fail closed on 403/device unavailability, and never treat authentication as approval.
- REQ-F01-015: Preserve V1/V2 meaning and add operator-reported V3 chat-confirmed evidence for direct same-conversation exact-scope user approval plus owner-authenticated GitHub action. V3 is not a signed chat attestation. The CLI cannot accept approval; a chat host without a verifiable direct user-role event blocks. Keep ADC, Ruleset, User Review, Setup PR merge, and PR #64 merge as distinct exact-scope operations, with append-only cross-version history, GitHub API I/O through `gh`, Git object transfer through Git, direct/list/direct readback, automatic phase rebaseline, and no self-approval. Before any new `approved` ADC publication, the shared approval-ready preflight rejects a draft/proposal title, draft-only header, nonfinal State/Status, malformed predecessor declaration, or a declared predecessor that differs from the current verified approved pointer. Issue #63 successor candidates must name that current pointer. The same preflight is required by owner-authorization preview, chat-confirmed commit, the ADC publisher, and direct CLI publication before the first write; it does not replace exact SHA approval. Structural parsing and historical-generation verification remain compatible with immutable older records that were published with draft-only text, and draft publication remains unchanged.

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
- ユーザー向けの「P-ASESを有効化して」は、Activation discovery、setup branch準備、canonical Ruleset plan、必要時の正確なチャット承認とisolated browser device Admin continuation、effective-policy readback、policy-bound setup PR、merge後のV2記録までを一つの再開可能な処理として進める。通常利用者にRuleset準備コマンドの手動連鎖を要求しない。
- `solo_owner`以外の既存V1動作は維持し、#63で認可されていないpolicy writeを追加しない。全modeで設定インベントリを報告し、mode上必須の未充足項目がある間は`ACTIVE`を返さない。

**D3 — 管理対象Rulesetのexact state**

- 対象はrepository scopeで**名前`P-ASES Final Delivery (managed)`の一件のみ**。`target=branch`、`enforcement=active`、`conditions.ref_name={include:["~DEFAULT_BRANCH"],exclude:[]}`、`bypass_actors=[]`。
- ルールは3種: `pull_request`（approvals=0、stale-dismiss=false、code-owner=false、last-push-approval=false、review-thread-resolution=true、merge methods=[merge,squash,rebase]）、`required_status_checks`（profileの4件の`context`＋`integration_id=15368`完全一致、strict=true）、`non_fast_forward`（force push禁止）。GitHub APIのrequired fieldsを全て正確に付ける。
- この自動更新は**明示選択したsolo_ownerのみ**。`external_reviewer`は読み取り・診断のみ。別名Ruleset、組織Ruleset、legacy protectionは変更しない。同名で管理所有証跡がない、競合保護、複数候補はBLOCK。削除・強制上書き・ルール緩和は禁止。

**D4 — 人の承認を拘束した安全な自動適用**

- Activation setupはGitHub read-only discoveryの後、policy-bearing setup PRを作る前にsetup branchと`.agent/project.json`のcommitだけを準備する。既存canonical plannerはrepo/owner ID、default branchと現行policy、setup branchのcommit/profile bytes、Activation ADC generationとpredecessor、mode/check集合、既存Ruleset ownership、desired API payload、diff、現行保護証跡、open-PR影響を含むblocker-free plan SHA-256を生成し、同じActivation checkpointへ保存する。
- Ruleset書込が必要なときは、正確なblocker-free plan SHAに対する`RULESET_PLAN_APPLY`を別途チャットで承認する。V1 brokerは従来どおり検証可能な場合だけ保持し、標準経路は同一チャットのdirect user-role approvalをin-processで受けてV3 owner decisionと既存の二行`PASES-RULESET-APPROVE` / `PASES-REPOSITORY`コメントを各一度だけghで追記する。`approval_scope_sha256`は提示対象を固定するdigestで、チャット署名ではない。`owner-authorize-commit` CLIはfail-closedであり、hostがuser-role provenanceを供給できない場合は`CHAT_PROVENANCE_UNAVAILABLE`、書込0とする。
  ```text
  PASES-RULESET-APPROVE: <64桁plan SHA-256>
  PASES-REPOSITORY: puchinya/ai-agent-workflow
  ```
- V1 relay writes remain available only under their unchanged positively isolated boundary. V2 local records retain `owner_local_tty_v1` meaning and are not ChatGPT signatures. V3 `chat_confirmed_gh_v1` is operator-reported approval plus owner-authenticated GitHub action; neither path creates a host signature. The V3 decision and exact two-line #57 approval both read back before the existing Admin continuation accepts them.
- isolated browser device Admin continuationは同じcheckpointのexact planとowner approvalを再検証し、書込直前に前提を再取得する。一致時のみ**初回一度POST／所有証跡がある既存IDへ一度PUT／一致ならNOOP**。runner-managed PTYでURL/codeを表示し、owner-local TTYは要求しない。HTTP errorや失われたresponse後は管理対象のunique ID/bodyを再取得し、曖昧ならBLOCK。盲目的再試行、無断ロールバックは禁止。
- 適用後はruleset detail / effective branch rules / legacy protection / `main.protected`を**同じAdmin認証**で再読取し、#60互換の`EffectiveBranchPolicy.status=VERIFIED`以外はActivation発行不可。初回成功時に#57へ追記専用`PASES_RULESET_APPLIED_V1`（repo、ID、plan SHA、承認comment ID、適用後body digest）を投稿・再検証して管理所有証跡とする。以後のPUTはこのIDと前回digestに一致する場合のみ許可し、成功ごとに後継適用証跡を追加。証跡投稿失敗時は**一意ID＋元plan/承認＋現状が完全一致する場合だけ**冪等回復し、曖昧ならBLOCK。403を未設定扱いにせず、tokenをログに出さない。書込中・適用後の実効設定変更を検知したらBLOCK。過去のrecordは編集しない。

**D5 — 後継Activation V2**

- V1 payloadと承認履歴を一切変更せず、同じ#57へversioned setup/approval/record **V2をappend-only**。V2 setupとrecordはmerged profile bytes SHA、review mode、Check集合/App ID、exact setup branch generation、管理Ruleset ID、実効policy digest、setup PR/管理者を拘束する。既存setup proposalのRuleset ID/applied-record/policy digestが現行verified policyと異なる場合は旧proposalを不変のまま残し、新しいexact branch/plan/PR generationを作る。古いproposalを更新して現行証跡に見せかけない。
- V2の**有効時刻はGitHubが返すActivation recordの`created_at`**。setup PR mergeとrecord作成の中間に作成されたIssueは新V2を使用しない（旧V1が有効ならV1を使用）。V1の時刻は従来どおり。
- 現行`setup_consumer_activation`が同一ADC SHAで古いACTIVEを返す短絡は**V1→V2移行の場合に使わない**。fresh policy double-read後のみrecord追加。発行後のpolicy変更は過去のrecordを無効にせず、現在のpreflight/Final DeliveryだけBLOCK。

**D1 — GitHub API とGit repository transfer のtransport boundary**

- All GitHub API reads and writes for Issues, PRs, comments, reviews, checks, Actions, Rulesets, branch protection, merges, labels and closure use `gh` through `runtime/p_ases/github.py`. JSON bodies go to `gh api --input -` stdin. No connector/plugin, SDK, direct HTTP, curl or UI write is permitted.
- Source repository operations use Git (`git`) through the existing Git boundary. Fetch, push and remote-ref/object readback (`ls-remote`) are the only GitHub-hosted transport exception; they transfer Git objects/refs and do not replace `gh` for GitHub API state. Do not add another GitHub API writer or use Git transport for Issues, PR metadata, comments, checks, policy, Rulesets or merge state.

**D6 — Activation-owned provisioning with isolated browser device authentication**

- Preserve D1–D5 and the exact Ruleset plan approval/apply contract. `consumer-activation-setup` owns the resumable transaction. The two Admin continuation commands default to `isolated-gh-device`, which runs `gh auth login --hostname github.com --web --git-protocol https --insecure-storage` in a fresh mode-0700 `GH_CONFIG_DIR`. A runner-managed PTY may show the browser URL and device code; the owner completes browser authentication without opening an owner-local terminal. Remove ambient standard and enterprise token variables from the login and Admin API child environments. If the runner cannot show the challenge, block as `ADMIN_DEVICE_LOGIN_UNAVAILABLE`; do not fall back to normal `gh` auth.
- `pat` is a nonstandard explicit fallback requiring a trusted owner-local TTY and a short-lived repository-scoped token. It is not the standard authorization flow. Device and PAT authentication are distinct from every operation approval. Preserve the normal `gh` config and environment. Delete the private config best-effort but do not claim OAuth grant revocation; same-OS-user subprocesses are not a strong sandbox. Never expose credentials in argv, logs, JSON, files, or chat.
- Admin preflight/apply must verify authenticated owner ID, repository ID/name, admin and collaborator permissions, complete branch-protection/Ruleset/effective-policy reads, and the exact saved plan. A 403 or incomplete response is unavailable. Admin-plan is GitHub-read-only; Admin-apply reuses the existing exact approval, single writer, durable intent, and readback. The Setup PR is created only after policy is verified.
- The private admin `GitHub` client remains isolated to the selected child process. All GitHub API reads and writes use `gh` through `runtime/p_ases/github.py`; Git fetch/push/remote-ref operations use the existing Git boundary only for repository object transfer. No connector/plugin, SDK, direct HTTP, curl, or GitHub UI write is allowed. JSON request bodies go to `gh api --input -` stdin. Normal `gh` configuration and credentials are unchanged.

**D7 — Chat-confirmed V3 operation decisions and forward-only history**

- Keep V1 delegated-relay and V2 owner-local-TTY semantics and history unchanged. Add `PASES_OWNER_DECISION_V3` and `PASES_USER_REVIEW_DECISION_V3` with `evidence_channel=chat_confirmed_gh_v1`. V3 records operator-reported direct same-conversation user approval followed by a GitHub-authenticated owner action. It is not a signed chat-host event or an independent relay. `approval_scope_sha256` binds the shown content only and is not an attestation.
- Approval is collected in the same chat by showing repository, Issue, operation, exact ADC/Ruleset plan SHA or PR number+HEAD, and relevant diff/gates, then asking the user directly. For `ADC_SUPERSEDE`, provide the canonical `.md` file and render its complete contents as Markdown before asking; do not put the document inside a fenced source-code block or an HTML disclosure/container. A file link, excerpt, or SHA alone is insufficient. If the selection UI cannot contain the document, render the complete Markdown in the immediately preceding message in this same conversation, link the canonical `.md` file, and make the approval prompt explicitly refer to that rendered document. The prompt also identifies the exact ADC SHA, current approved predecessor pointer, plan SHA, approval-scope SHA, and resulting operation. If any ADC byte changes, recalculate the SHA, provide and render the complete new Markdown again, and request a fresh approval. Accept only an explicit user-role approval event bound to that displayed scope. A vague “continue”, assistant-authored content, CLI flag, arbitrary JSON/file, or approval from another chat without a trusted transfer is not approval. If the live host cannot provide the user-role event, return `CHAT_PROVENANCE_UNAVAILABLE` and do not write. No owner-local TTY, SHA retyping, or manual GitHub UI post is required. The CLI `owner-authorize-commit` blocks because it cannot prove chat provenance; only an in-process chat integration can pass an ephemeral typed grant.
- Every V3 grant binds the canonical repository/Issue/operation/subject, plan digest, `approval_scope_sha256`, optional PR/HEAD, owner ID, and predecessor. The authenticated GitHub actor must be the configured owner ID `3744776`, and repository ID `1401910271` plus comment API/Issue/HTML URLs are independently verified. Cross-version history remains append-only and rejects duplicates, replays, missing pages, edits/deletions, wrong actor, changed subject, and direct/list/direct disagreement. The GitHub read-only verifier principal is separate from trusted owner identity and may differ.
- `ADC_SUPERSEDE`, `RULESET_PLAN_APPLY`, `USER_REVIEW`, Setup PR `PR_MERGE`, and PR #64 `PR_MERGE` are separate scopes. ADC approval binds exact successor bytes and the current approved predecessor pointer, then invokes the existing publisher and automatic #63 Phase Intent/Applied path. Ruleset approval binds exact blocker-free plan and is paired with the existing owner-authenticated two-line #57 comment before the sole Ruleset writer. User Review V3 binds the exact session, Readiness, ADC, PR HEAD, prior full feedback digest, plan and scope; it enters the existing evaluator and Final Delivery rereads the chain/snapshot. Formal self-approval remains invalid. Each merge plan binds exact current HEAD and gates; a lost response is read-only recovery with no second merge request.
- Required #63 lifecycle is `implementation → approved successor ADC → automatic Phase receipts → pre-merge Ruleset verification and normal PR #64 gates → separate exact-HEAD PR_MERGE → PR #64 merge with Refs #63 → verify Issue #63 OPEN → Activation V2 Setup PR review/merge → V2 ACTIVE/effective-policy readback later than PR merge → one-shot Issue #63 close`. Activation `ACTIVE` is post-merge work and is not a prerequisite for #64 merge. Use the existing exact current-base proof only where that ordering actually applies; it does not authorize #64 after the fact. Preserve ExecutionBinding, original PRBinding V1, #57 V1, old ADC, and #60/PR #62.

<a id="artifact-impact"></a>
## 6 Artifact Impact

Canonical: update spec/design/oracle/traceability, this final successor candidate, execution-order contract, Skills, runtime and tests for `gh`-only GitHub API I/O and Git-based repository object transfer, V3 chat-confirmed exact scopes, operator-reported assurance, no owner approval TTY, isolated admin browser auth, approval-ready ADC publication preflight, and forward-only compatibility. The candidate becomes authoritative only after its exact bytes are owner-approved and immutably published through the existing pointer journal. Regenerate dist only with `python tools/build_dist.py`.

<a id="exact-changes"></a>
## 7 Exact Changes

1. Finish the authorized #63 implementation on the existing PR #64 and prepare this final successor candidate plus its linked specification/design/oracle/traceability. Commit and push the reviewable result to PR #64. This does not publish the ADC, change Issue phase, authorize Ruleset writes, User Review, or merge. Keep #57 and #60 read-only.
2. Before declaring implementation ready, validate that every referenced test source, document link, anchor, and commit exists and matches this final successor. No fake paths or permanent skips are allowed.
3. `runtime/p_ases/{branch_policy,profile,github}.py`の#62互換基盤、`runtime/p_ases/ruleset_management.py`（plan/approval/唯一の対象へのPOST/PUT/NOOP）、`runtime/p_ases/consumer_activation.py`（V2/冪等発行）、`runtime/p_ases/{gate_policy,phase_evidence}.py`（prefix検証）を実装。`phase_rebaseline.py` verifies the approved ADC predecessor/successor pointer chain, writes a canonical Intent before the single permitted #63 label PUT, double-reads Issue/ADC, writes Applied evidence, and recovers without repeating the PUT.
4. `runtime/p_ases/cli.py`へ`delivery consumer-activation-preflight`、`delivery consumer-activation-ruleset-plan --output <path>`、`delivery consumer-activation-ruleset-apply --plan <path> --approval-comment-id <id>`、isolated browser device Admin continuation、V2 setup/verifyを統合する。通常ユーザーは`consumer-activation-setup`だけで再開可能なActivation処理を開始する。関連Skill更新、`dist/{openai,claude,antigravity}`を生成。
5. **後続ADC正式化→Phase更新**: `docs/contracts/issue-63-successor-adc-final.md` のcanonical bytesを提示し、全文をMarkdownとして同一会話の承認依頼直前に表示する。SHA/current approved predecessor/plan/scopeとともにownerへreadbackしてから、当該SHAに対する新たなexact `ADC_SUPERSEDE`承認を取得し、approved preflight後にappend-onlyで正式発行する。承認依頼ではコードフェンスではなくMarkdownとして表示し、canonical `.md`へのリンクも付ける。selection UIに全文を格納できない場合は、直前の同一会話メッセージにMarkdown全文を表示し、承認依頼からその表示を明示参照する。候補の1 byteでも変われば新しいMarkdownを再表示して新しい承認を求める。公開後はpointerとforward generationをreadbackし、認証済みP-ASES executorが#63のIntent/一度限りのlabel PUT/Appliedを実行してIssueとADCを再readbackする。`PHASE_REBASE` decisionは要求せず、必須のIntent/Applied技術記録を残す。
6. **PR #64 pre-merge gates**: #63に必要なsolo-owner Rulesetがなければ、PR #64のcleanな確定HEADと`.agent/project.json`のsolo_owner/Required Checksを使い、`activation_binding`なしでcanonical planを作成する。Activation Setup branch/PRやV2 `ACTIVE`を前倒しせず、別のexact `RULESET_PLAN_APPLY`承認後に既存one-writer/durable-intent/apply/readback経路で適用する。既存owned policyはNOOP。current HEAD CI、Independent Review、User Review、Final Delivery、effective policyを再評価し、PR #64専用のexact-HEAD `PR_MERGE`承認を取得する。PR本文は唯一のstandalone `Refs #63`とし、全commit message、planned merge request message、GitHub `closingIssuesReferences`、Issue cross-reference metadataにclosing関係がないことを読み戻す。疑義・不完全readbackはmerge前にBLOCK。merge後直ちにIssue #63がOPENであることを確認する。
7. **Post-merge Activation V2とIssue #63 close**: #64 merge後のclean default worktree at latest mainからActivationを開始する。Activation Setup PRのreviewとexact-HEAD merge decisionは#64と別。V2 record ID/`created_at`/Ruleset ID/effective policyを再読込し、`created_at`が#64 merge時刻より後であることを確認する。`delivery finalize 63 64`はこれらの証跡とcurrent policyが成立した場合だけ、durable close intentを一度だけ作成してIssue PATCHしdirect/list/direct readbackする。V2未成立、policy drift/403、事前に閉じていたIssue、または曖昧なPATCHはBLOCKし、再PATCHやIssue再openをしない。PR #62/#60は変更しない。
8. Keep the two Admin commands and isolated browser-auth child boundary exactly as in D6. The device URL/code may be shown through a runner-managed PTY; do not require an owner-local TTY for approval or browser authentication.
9. Preserve V1/V2 ordinary owner-decision history, add V3 exact-scope chat-confirmed owner/User Review carriers, expose only an in-process chat-grant integration, and keep the CLI approval route fail-closed. Implement automatic Phase rebaseline and forward-only PRBinding successors; keep USER_REVIEW out of `owner_consent.py` and never claim cryptographic chat attestation.
10. Add one shared approved-publication preflight in `runtime/p_ases/adc.py` and call it from owner-plan preview, chat-confirmed commit, `publish_adc`, and direct CLI publication. Reject draft/proposal titles, draft-only headers, nonfinal statuses, malformed predecessor metadata, and Issue #63 candidates whose declared predecessor comment/SHA is not the current approved pointer before any publication write. Keep `parse_adc`, historical-generation verification, and `state=draft` publication compatible; never auto-edit candidate bytes after approval. Add focused regression tests and update ADC authoring/registry/work-execution/delivery Skills, Specs, Design, Oracle, traceability, and generated distributions.

<a id="activation-owned-current-base-transition"></a>
### 7.1 Activation-owned current-base transition

The immutable `ExecutionBinding` and original V1 `PRBinding` retain frozen base A. Accept base B only when the current default branch is exactly the Activation V2 setup PR merge commit; A is its first parent; the setup PR and setup commit are bound by the V2 record; both diffs change only `.agent/project.json`; the Activation record, setup PR, target PR, repository and Issue identities match; and profile bytes on B and the exact target PR HEAD match the recorded Activation profile digest. The target PR must preserve its original code patch while integrating B. Store the proof as create-only typed evidence, append a V2 PRBinding generation referencing it, and revalidate it in `pr ensure`, Readiness, and Final Delivery. Any other main advancement, profile mismatch, identity mismatch, missing proof, or unrelated commit blocks.

<a id="invariants"></a>
Before implementation is reported ready, `tests/test_user_review_relay.py` MUST exercise the same-session evaluator integration and persisted `PASES_USER_REVIEW_RESULT_V2` evidence, including a read-only verifier ID distinct from the owner, wrong carrier actor, wrong PR author/owner, executor self-approval rejection, actual wrong-Issue/wrong-repository comment URLs, and direct/list/direct disagreement, as well as pre-session/equal timestamps, genesis/orphan/skipped predecessors, replay, incomplete pagination, edits, deletion, changed feedback, and unresolved threads. `ADC_SUPERSEDE` publication requires a separate exact approval for these final bytes and the verified current predecessor; after publication, phase rebaseline executes automatically through the authenticated P-ASES workflow executor.

The selected-evidence object for V1 retains exactly `evidence_type, evidence_channel, comment_id, body_sha256, owner_id, created_at, review_session_sha256, predecessor_comment_id`. V2 adds `feedback_sha256` and `plan_sha256`, and carries `evidence_type=PASES_USER_REVIEW_DECISION_V2` with `evidence_channel=owner_local_tty_v1`. V3 retains those subject fields and adds `approval_scope_sha256` with `evidence_type=PASES_USER_REVIEW_DECISION_V3` and `evidence_channel=chat_confirmed_gh_v1`; this reports operator-confirmed chat approval and GitHub owner action without claiming a host signature. The result binds the typed object to the full `snapshot_sha256` and exact User Review subject.
## 8 Invariants

- The V1 #57 Activation ADC, pointer, approval, record, original `merged_at`, and each prior Issue's ADC/Gate Selection/PR/evidence remain immutable.
- Existing Issues are never auto-migrated to V2. The current live Final Delivery policy continues to fail closed on unavailable or mismatched protection.
- Ruleset mutation requires an exact plan plus a separately confirmed V3 `RULESET_PLAN_APPLY` decision and the owner-authenticated exact two-line Issue #57 approval comment; this ADC approval does not grant that permission.
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
- [ ] コミット・push・PR作成（`Refs #63`）・self/独立review・CI・別subjectのUser Review/PR_MERGE承認・gh経由のmerge実行・IssueがOPENであること・後続Activation V2・one-shot Issue close/readbackを報告する

<a id="verification-obligations"></a>
## 10 Verification Obligations

- 旧V1/旧IssueのADC・Gate Selection・phase/PR不変。後続V2だけ破損→旧Issue PASS/新Issue BLOCK、元V1改変→旧Issue BLOCK。
- V2の記録前後でIssue作成日時を比較し、PR merge日時でV2を誤選択しない。
- 空→1 POST、同一→NOOP、承認済みowned ID変更→1 PUT。それ以外・同名collision・承認なし・403・race・partial write→BLOCK/二重作成なし。
- wrong branch、Check name/App ID、approve count、force push、bypass、inactive enforcement、legacy conflict→VERIFIED不可。
- 非TTY/getpass cancellation/空入力/identity mismatch/admin不足/403/不完全readback/blocked plan/未承認apply/driftではRuleset POST/PUTが0回。正常時もIssue #57のexact-plan承認後に既存の1回write経路だけを通る。
- self-authored `solo_owner` User Review verifies exact repo/Issue/PR/HEAD/Readiness/ADC/session and full prior feedback. Preserve V1/V2; V3 adds operator-reported chat confirmation and exact approval scope, never a chat signature. Distinct read-only verifier identity, authenticated owner identity, comment URLs, and complete direct/list/direct history are separately checked. Formal self-approval, vague continuation, stale subject, replay, incomplete feedback and unresolved threads never approve.
- token markerはargv/log/file/JSON/chat/os.environ/unrelated child/default authに現れず、例外・中断後のnormal gh requestにも残らない。`isolated-gh-device`は正規モードとして exact login argv、runner-managed PTYの可用性、mode-0700 private config、ambient token除去、親`gh`不変、cleanupをテストする。未提供Cloud device flowは未検証と報告し、PATは明示的owner-local fallback。
- admin-planとadmin-applyは別々の一時管理認証を使い、同じApprovalを流用しない。owner TTYは承認/認証の必須条件ではなく、PAT fallbackを選んだ場合だけ必要。
- 通常のPRはstandalone `Closes #N`とGitHub自動closeを維持する。後工程が残る#63だけはPR #64にstandalone `Refs #63`を使い、通常merge後にIssue OPENを確認してからActivation V2を実施する。Setup PRは#64より後に別途review/mergeし、V2 `ACTIVE`後に#63を一度だけcloseする。Activation-owned base A→Bはそれを必要とする別workflowでのみ検証済みSetup PR遷移に限って許可し、通常base drift、未知のmain commit、profile相違を拒否する。旧PRBinding bytesは不変。
- commands: `python -m compileall runtime tools tests`, `python -m unittest discover -s tests -p 'test_*.py'`, `python -m p_ases docs validate --root .`, `python tools/build_dist.py --check`, `python tools/validate_dist.py`。既存3系統traceability/16 Skills acceptance/Ubuntu・Windows・macOSの4 Required Checksも実行してexact HEAD/App IDを検証。live管理API実測ができなければBLOCKED。

<a id="reviewer-checklist"></a>
## 11 Reviewer Checklist

- [ ] Activation, rather than the end user, orchestrates all profile-required and in-scope GitHub provisioning.
- [ ] An empty Ruleset produces a resumable plan/approval state instead of an unexplained prerequisite failure.
- [ ] Setup PR profile bytes and exact commit are bound to the canonical policy plan before privileged apply.
- [ ] Exact chat V3 owner decision and Admin authentication remain separate; the owner TTY is not required for chat approval.
- [ ] Browser device auth is the Admin default in an isolated child; PAT is explicit fallback; normal gh remains unchanged and OAuth cleanup is not called revocation.
- [ ] Ruleset management uses the existing single plan/apply/readback writer and never duplicates POST/PUT on recovery.
- [ ] Existing #57 V1, #60/PR #62, predecessor #63 ADC, Gate Selections, and historical evidence remain untouched.
- [ ] New approved ADC publication rejects draft-only content and stale predecessor pointers before writing, while historical approved-draft bytes remain readable and immutable.
- [ ] V2 and User Review/Final Delivery remain exact-subject, full-readback, and fail closed.
- [ ] Ordinary PRs retain standalone `Closes #N` and GitHub auto-close. Only the deferred Issue #63 / PR #64 path uses standalone `Refs #63`.
- [ ] Successor ADC/Phase receipts and effective solo-owner Ruleset policy are ready before PR #64 merge; Activation V2 `ACTIVE` is completed after merge.
- [ ] Activation Setup PR merge and PR #64 merge use separate exact-HEAD review/merge decisions.
- [ ] The one-time A→B current-base evidence proves the exact Activation merge, profile-only diff, matching profile bytes, and unchanged PR code patch; old V1 Binding bytes are unchanged.
- [ ] Required tests, traceability, generated distributions, and four exact-HEAD CI checks pass.
- [ ] PR #64 remains unmerged until its separate current-HEAD review, User Review, Final Delivery and merge authorization pass; after merge, verify Issue #63 remains OPEN until V2 Activation completion permits the one-shot Issue close.

## 12 Completion Gates
<a id="completion-gates"></a>

- The exact final successor candidate becomes canonical only after a separate exact-SHA `ADC_SUPERSEDE` decision, successful approval-ready preflight, immutable pointer publication, and readback. Its authority does not include Ruleset writes, User Review, or PR merge; those retain their distinct gates. Keep the published predecessor, #57 V1, #60/PR #62, and historical evidence read-only.
- Before requesting ADC approval, verify all referenced test sources, links, anchors, documents, and commits against the final candidate; render and read back its complete bytes and SHA with the current approved predecessor. A changed byte invalidates any earlier presentation and requires new exact-SHA approval. Do not rewrite the final bytes after approval; pointer publication must match them exactly.
- First finish implementation on existing PR #64 and record the exact final successor bytes/SHA. Obtain a fresh exact-SHA `ADC_SUPERSEDE` approval, publish/read back that exact candidate, automatically rebaseline #63 with Intent/Applied evidence, and establish its Phase receipts.
- Ordinary PRs continue to use `Closes #N`; only this deferred completion path uses `Refs #63`. Before #64 merge, verify current solo-owner effective policy; any Ruleset write requires its own exact plan approval and isolated Admin authentication. Then revalidate the current HEAD, four Required Checks, Independent Review, User Review, Final Delivery, no-auto-close metadata, and separate `PR_MERGE` approval. Merge with `Refs #63` and verify Issue #63 remains OPEN.
- After the #64 merge, complete Activation V2 and its separately approved Setup PR merge from a clean current-main worktree. Verify the V2 record and policy, require its `created_at` after the PR merge, then run the durable one-shot Issue close path. If any external gate is unavailable, report the exact blocked stage and do not claim completion.
- Report changed files, contract checklist/acceptance outcomes, exact test commands/results, CI and unverified environments, A/B/C/D review findings, deviations/blockers, missing operation-specific approvals/Admin boundary evidence, and the existing PR URL. Separate implementation readiness from Activation delivery readiness.

This document is an Implementation Contract. Do not redesign the architecture during implementation. If a requirement conflicts with repository reality or requires a material design change, do not silently choose an alternative. Report the exact conflict and continue only with independent valid work.
