# P-ASES — 命名・Skill・ランタイム設計

<!-- heading-map:start -->
**見出しマップ（自動生成）**

- [1. 正式識別子と廃止対象](#1-正式識別子と廃止対象)
- [2. 16 Skillの正規集合](#2-16-skillの正規集合)
- [3. CLIとモジュール境界](#3-cliとモジュール境界)
- [4. 配布と標準](#4-配布と標準)
- [5. ワークスペースと権限境界](#5-ワークスペースと権限境界)

<!-- heading-map:end -->

## 1. 正式識別子と廃止対象

| 対象 | 唯一の正規形 |
|---|---|
| システム | Puchinya Agentic Software Engineering System（P-ASES） |
| 契約 | Agent Development Contract（ADC） |
| Python distribution | `p-ases` |
| Python package / CLI | `p_ases` / `python -m p_ases` |
| Plugin表示名 / slug | `P-ASES` / `p-ases` |
| GitHub repository | `puchinya/ai-agent-workflow`（変更しない） |

旧 `agent_workflow` module、旧公開Skill 10件、旧フラットCLI、旧証跡マーカの新API互換レイヤは作らない。GitHubの歴史的コメントや過去のマージ履歴は変更しない。

## 2. 16 Skillの正規集合

`request-intake`, `adc-authoring`, `adc-registry`, `issue-decomposition`, `product-specification`, `technical-design`, `test-specification`, `work-execution`, `verification-evidence`, `acceptance-validation`, `contract-audit`, `independent-review`, `user-review`, `integration-validation`, `delivery-control`, `work-checkpoint`。

| Skill群 | 主な境界 |
|---|---|
| request-intake / adc-authoring / adc-registry | 受付と権限判定 / 作成 / GitHub上の不変契約管理 |
| issue-decomposition / integration-validation | 子Issue+DAG / 親統合・全要求の受入 |
| product-specification / technical-design / test-specification | 規範仕様 / 技術判断 / 独立Oracle |
| work-execution / work-checkpoint | 変更作業+PR / 同一workspaceの再開 |
| verification-evidence / acceptance-validation | 実行証拠の収集と検証 / 成果物受入 |
| contract-audit / independent-review / user-review | 自己監査 / 独立AI監査 / ユーザー最終判断 |
| delivery-control | Review Readiness / Final Delivery / merge後finalize |

## 3. CLIとモジュール境界

唯一のCLI形式は `python -m p_ases <namespace> <verb> [args]`。namespaceは `project`, `context`, `adc`, `issue`, `docs`, `work`, `pr`, `verification`, `acceptance`, `audit`, `user-review`, `delivery`。

公開必須操作: `adc validate|publish|verify|restore`、`issue split|advance|integration-check`、`docs validate|format`、`work base|branch|bind|recover`、`pr ensure`、`verification plan|collect|validate|final|published`、`acceptance prepare|validate|publish|verify`、`audit self|independent`、`user-review start|sync|record|status`、`delivery readiness|final|finalize|parent`。

- `runtime/p_ases/adc.py`は不変契約・ポインタ、`intake.py`は入力権限、`phases.py`は状態遷移、`issue_graph.py`は親子DAG。
- `documents.py`/`document_format.py`は文書整合と採番、`verification_plan.py`/`oracle_trace.py`/`verification.py`/`evidence_store.py`は検証、`acceptance.py`は成果物受入。
- `audits.py`は自己/独立監査、`user_review.py`は**最後のユーザー**、`delivery.py`はreadiness/final/finalize。GitHub APIは`github.py`、Git subprocessは`git.py`だけ。

## 4. 配布と標準

正本は `workflow/skills/<id>/SKILL.md`, `workflow/standards/`, `workflow/templates/`, `runtime/p_ases/`。`tools/build_dist.py`は3ホストOpenAI/Codex・Claude Code・Antigravityへ決定的生成し、`tools/validate_dist.py`で同じ16件を検査。`dist/**`を手作業で編集しない。

## 5. ワークスペースと権限境界

Python 3.10+、標準ライブラリ一回限りCLIを維持。exact-base SHAを凍結しworktree分離はホストが所有。既存継続workspaceではHEAD/baseを誤って再解決しない。Secretsをログ・Issue・PRへ出さない。通常のpush/PRには確定ADCの実行許可を引き継ぐが、force push、破壊的Git、merge/release、権限昇格には別権限が必要。
