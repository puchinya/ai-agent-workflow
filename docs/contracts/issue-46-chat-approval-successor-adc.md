# Agent Development Contract — Issue #46 Chat Approval

Repository: puchinya/ai-agent-workflow  
Issue: #46  
PR: #67  
Candidate state: Forward successor ADC draft. It is not approved, published, bound, or effective.  
Approved predecessor ADC: Issue comment #6399289386; SHA-256 `8465cfa151186b3a59a015f9f0c6f674f9e7bedce587747b72e080197e480ab3`.  
Inspected PR HEAD: `44e74ec04fa423acbd4cd904d48530ae4cd04f12`; refresh before execution.  
Current unapproved Requirements Rebaseline plan: SHA-256 `8ba115422d82f6883af10ee4d4bbed580ea3598f472e12c5e01131762f150c48`; do not apply or reuse.  
Owner direction received 2026-10-26: all Issue #46 lifecycle approvals must be available through this chat; the Owner must not be asked to post an approval comment to Issue #46; cryptographic verification of chat origin is not required.

> This successor changes the approval interaction for Issue #46 / PR #67 only. Preserve every prior approved ADC, Issue comment, pointer, Binding, Phase receipt, reset record, and PR commit. Do not edit or delete historical records.

## Issue

The approved predecessor requires the Owner to post a separate exact approval comment to Issue #46 before the requirements rebaseline. The Owner has directed that approvals be handled in chat and that the Owner not be asked to post approval comments. Existing `requirements-rebaseline` implementation and plan therefore use an obsolete approval route and must be replaced before any phase label change. Technical decision and phase evidence comments remain permitted.

The earlier PR #64 operating contract already described direct same-session chat approval as the preferred interaction, but its later Issue #46 implementation contract required an Owner-authored Issue comment. This successor resolves that conflict for the Issue #46 lifecycle without changing the meaning of earlier evidence.

## Scope

This contract applies to approval decisions and P-ASES records for Issue #46 / PR #67. Every explicit human approval in this lifecycle—including ADC supersession, the Requirements Rebaseline, an unavailable-review exception, User Review, and PR merge—must be requested and answered in the active chat session. The exact current subject and consequences must be displayed before each request.

The Owner is never asked to post an approval comment to Issue #46. After a direct chat approval, the authorized workflow may write the existing typed technical decision/evidence record to Issue #46 using the established `gh` transport and readback protocol. ADC pointers, Phase receipts, reset Intent/Applied records, exception records, and User Review decision carriers keep their existing record locations and schemas unless a separate approved change requires otherwise. Existing comments remain append-only and are never edited or deleted.

## Change kind

Forward-only change to the approval interaction. This successor supersedes the predecessor's requirement for an Owner-authored Issue #46 approval comment. It does not change the established technical evidence locations, approved Independent Review occurrence/outcome requirements, or permit skipping any gate.

## Requirements

- REQ-F06-006 through REQ-F06-014: Preserve the Independent Review occurrence, outcome/findings, unavailable-provenance exception eligibility, exact-subject Readiness, User Review, and Final Delivery requirements from the approved predecessors.
- REQ-F06-015 (forward revision): The Owner's chat approval of this exact successor ADC also authorizes one Requirements Rebaseline from the current `phase:user-review` to `phase:requirements`, once the approved bootstrap implementation has generated a current read-only plan and verified every ADC precondition. The plan binds the exact current ADC pointer, Binding, PR/base/HEAD, complete labels, and completed predecessor Legacy Reset V1 receipt. No second Owner or chat approval of that plan is required. If any precondition fails or the exact subject changes, perform no write and report the blocker; this authorization cannot be reused or expanded to another phase, Issue, or plan.
- REQ-F06-016: All explicit human approvals for Issue #46 / PR #67 lifecycle operations are requested through a direct selection UI in the same active chat session. Each request names the repository, Issue/PR, operation, current HEAD or plan/ADC SHA, and exact authorized consequences. The choices are `承認する` and `承認しない`. Only the user's direct response to that active request counts. Prior, generic, assistant-authored, quoted, or unrelated text is not approval.
- REQ-F06-017: No Owner-authored approval comment is required or requested on Issue #46. After a direct affirmative chat selection, the workflow may append the existing typed technical decision record to Issue #46 through the established writer and verify it by direct/list/direct readback. The record describes the chat answer as operator-reported; the GitHub comment author is the recorder and must not be described as the person who typed the chat answer.
- REQ-F06-018: Chat origin is operator-reported evidence from the active conversation. Cryptographic host signatures, device signatures, or independent proof of the ChatGPT UI transport are not required. Do not claim such cryptographic proof. The record binds the exact operation and subject SHA so a changed subject requires a new chat request.
- REQ-F06-019: Existing Issue #46 records remain append-only and immutable. New typed technical evidence continues to use its already specified Issue #46 carrier and complete direct/list/direct readback. The Owner does not need to post a separate approval comment. Do not move records to the PR conversation ledger as part of this successor.

## Approval interaction

Before every approval request, display the full ADC or plan content needed for the decision in ordinary rendered Markdown, followed by the exact SHA and the operation scope. The ADC approval request must explicitly state that it includes one Requirements Rebaseline under REQ-F06-015. The generated plan is read-only evidence for checking those approved limits; do not ask for another approval of it.

Use a selection UI with exactly these choices:

- `承認する`
- `承認しない`

On `承認しない`, cancellation, no response, or an answer that is not the active request's exact affirmative choice, perform zero protected writes. On `承認する`, continue only for the named SHA and operation, record the answer as operator-reported chat evidence using the operation's existing typed Issue #46 evidence carrier, and recheck the live subject before the operation. The Owner is not asked to post any comment. For the one-time Requirements Rebaseline already authorized by REQ-F06-015, a changed plan, ADC, HEAD, labels, Binding, PR base, or repository state blocks execution; it does not trigger another approval request or permit applying stale evidence.

## Architecture decisions

1. Keep all GitHub reads and writes behind `runtime/p_ases/github.py`, which invokes `gh`. Git transport continues to use `git`.
2. Reuse the existing typed Issue #46 evidence carriers and their single writer. Do not create another GitHub writer or move records to PR #67 comments.
3. Approval UI response and GitHub recording identity are separate facts. Store the selected answer, active question item ID when available, exact scope digest, subject SHA, and recording actor metadata. The record states `operator_reported_chat`; it is not a cryptographic chat signature.
4. Preserve the current single writer for any Ruleset operation. Chat approval authorizes only the exact named plan; it does not grant administrator credentials or broaden the plan.
5. Preserve normal Independent Review, Verification, Acceptance, Self-Audit, Required CI, User Review, Final Delivery, and separate PR_MERGE gates. A chat approval does not make an unperformed review pass.
6. The current plan SHA `8ba115422d82f6883af10ee4d4bbed580ea3598f472e12c5e01131762f150c48` was generated under the superseded manual-comment route. It is invalid and must not be applied. Generate a fresh read-only plan after bootstrap implementation, then apply it without another approval only if it satisfies REQ-F06-015 and all exact-subject checks.

## Artifact impact

After this successor is approved in chat, store its exact bytes and operator-reported chat decision through the existing Issue #46 ADC/evidence carriers, append the new Binding generation, and then implement the following. These declarations are consumed by `phase_evidence._artifact_impacts`:

- Specification: `docs/specs/workflow-spec.md`
- Design: `docs/design/workflow-design.md`
- Testing: `docs/testing/pases-lifecycle-tests.md`, `docs/testing/runtime-tests.md`, `docs/testing/traceability.md`

## Exact changes

- Update the ADC reader/publisher for Issue #46 so the active successor ADC and pointer continue to use the existing Issue #46 ADC carriers through `gh`; preserve the existing approved Issue comment #6399289386 as the immutable predecessor.
- Update `runtime/p_ases/requirements_rebaseline.py` and `runtime/p_ases/cli.py` so plan approval comes from the direct active chat selection and existing typed approval, Intent, and Applied records are written to/read from their current Issue #46 carriers. Remove the requirement that the Owner manually post an approval comment. Do not add a generic `--approved` bypass.
- Update Issue #46 Phase evidence, unavailable-review exception, User Review, and final-delivery readers/writers to retain their existing record locations and make each human approval a separate chat request bound to its exact subject.
- Preserve all V1/V2 schemas and historical Issue #46 records. Introduce new forward schemas for chat-recorded decisions; each schema clearly distinguishes the chat answer from the GitHub recording actor.
- Update the canonical specs/design/oracles, Issue #46 execution Skills, status docs, traceability, CLI tests, lifecycle tests, and distributions with `tools/build_dist.py`. Confirm exact affected paths before editing.
- Do not change Issue #63 / PR #64, Activation, fixed Bootstrap Issues #26–#32, or other Issues as part of this bounded successor.

## Invariants

- No workflow asks the Owner to author or post an approval comment on Issue #46. Technical evidence records may still be appended through the established writers.
- A user must see the exact target before an approval UI request. The answer is valid only for that active request and SHA.
- Chat evidence is operator-reported. Do not call it cryptographic, host-signed, or independently attested.
- No automated approval, assistant-generated affirmative answer, stale SHA reuse, broad "continue" inference, or cancellation-as-approval.
- Existing ADC, Binding, Phase, Adoption, Gate, and Legacy Reset records remain byte-for-byte unchanged.
- The Requirements Rebaseline phase label changes at most once, and only after every REQ-F06-015 precondition passes under this ADC's explicit authorization. No second plan approval is requested.
- No approval skips actual Independent Review, Required CI, Readiness, User Review, Final Delivery, or separate PR merge authorization.

## Non-goals

- This successor does not move technical evidence away from its established Issue #46 carriers or alter prior evidence.
- It does not make chat approval cryptographic, host-signed, or independently attested.
- It authorizes only the single `phase:user-review` to `phase:requirements` Requirements Rebaseline defined in REQ-F06-015; it does not authorize any other phase change.
- It does not waive Independent Review, Required CI, Readiness, User Review, Final Delivery, PR_MERGE, or Issue closure requirements.

## Verification obligations

After implementation, run:

```text
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

Verify that no approval flow asks the Owner to post a comment, that chat answers are bound to the active exact-scope request, that all new technical records use their established carriers with complete readback, and that exact-HEAD CI passes. Do not report any unrun host/OS surface as verified.

## Reviewer checklist

- [ ] The current manual Owner Issue-comment requirement is superseded only forward.
- [ ] Every separately gated Issue #46 approval uses the chat UI with exact current scope; the ADC approval itself authorizes only the one Requirements Rebaseline defined in REQ-F06-015.
- [ ] The rebaseline plan is read-only evidence and has no second approval gate; all exact ADC preconditions still fail closed.
- [ ] No workflow asks the Owner to author or post an approval comment on Issue #46.
- [ ] Existing technical Issue #46 records identify the chat answer as operator-reported and the GitHub author as recorder.
- [ ] Existing Issue #46 comments and all prior receipts remain unchanged.
- [ ] No review occurrence, outcome, or downstream gate is skipped or fabricated.
- [ ] Old plan SHA `8ba115422d82f6883af10ee4d4bbed580ea3598f472e12c5e01131762f150c48` is rejected; a new plan is bound to final code/HEAD.
- [ ] Tests, docs, traceability, distributions, 16-Skill acceptance, and exact-HEAD CI pass.

## Completion gates

1. Obtain exact chat selection approval for this successor ADC, explicitly presenting that it includes one rebaseline under REQ-F06-015. Store its bytes and operator-reported decision using the existing Issue #46 ADC/evidence carriers, and append its Binding generation. Do not ask the Owner to post a comment.
2. Implement the chat approval path and required docs/tests/distributions while retaining existing technical record locations; commit and push to PR #67.
3. Generate a fresh read-only plan for the current approved successor and exact HEAD; verify its ADC, Binding, PR/base/HEAD, labels, predecessor receipt, and all other REQ-F06-015 preconditions.
4. If every check passes, apply the one phase change already authorized by this ADC approval; append/read back the Intent and Applied records through their current Issue #46 carriers, with one Phase label PUT maximum. If any check fails, make no protected write and report the exact blocker; do not request another approval.
5. Publish forward Specification/Design/Ready receipts through their current Issue #46 carriers, then implement the predecessor's Independent Review occurrence and outcome, report-bound exception, Readiness/Final Delivery, and review fixes.
6. Perform a fresh separate-context Independent Review on resulting HEAD; resolve findings. User Review and PR_MERGE each require separate exact chat approvals. The Owner does not post an approval comment.

This successor is not itself approved until the Owner selects `承認する` in the active chat request for its exact SHA. That approval includes only the one Requirements Rebaseline in REQ-F06-015. It does not authorize User Review approval, PR merge, or Issue closure.
