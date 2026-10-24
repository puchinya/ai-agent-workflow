## PRE-ADMISSION Stage 1レビュー: BLOCKED

これは独立childによる信頼境界のレビュー結果です。正式なIndependent Review V2 PASSではありません。ファイル変更、GitHub操作、commit/pushはしていません。

**B-1 [P1] Adoption/Gate appendに同時実行制御がありません。**
[runtime/p_ases/legacy_adoption.py:821] は既存コメントを読み取ってからPOSTしますが、その間を排他する仕組みがありません。2つのapplyが同時に「未作成」と確認すると、同じAdoptionを2件作れます。後続の`_read_adoption_state`は重複として拒否しますが、Issue履歴には重複が残り、通常経路で回復できません。Gate appendにも同じ競合があります。

再現テスト案: 同じplanとapprovalで2つのapplyを並行実行し、コメント作成前の読み取りをbarrierで同期する。履歴にAdoption/Gateが各1件だけ残り、一方が成功、他方が安全にNOOP/BLOCKとなることを確認する。現実装では重複レコードが残り得ます。

**B-2 [P1] 記録の削除・marker除去後に、履歴を再作成できます。**
[legacy_adoption.py:750]はmarker付きコメントだけを履歴として読みます。Gateが削除されるか本文からmarkerを除かれると、既存Adoptionを未完了として返します。その後のapplyは同じ承認で新しいGateを追記できます。AdoptionとGateの両方が削除・marker除去されれば、空履歴として再作成できます。これは改変・欠落履歴をBLOCKし、append-only履歴を保つ要件を満たしません。

再現テスト案: applyを完了し、Gate本文のmarkerを削るかGateコメントを削除してから同じapplyを再実行する。再POSTせずBLOCKする必要があります。ところが、Gate POSTの応答喪失後に実際には未作成だった場合の復旧と、成功後に削除された場合の検知を、現在のIssueコメント履歴だけでは区別できません。v5契約の両要件をどう両立するか、設計上の決定が必要です。

どちらも確認される前にAdoption/Gate適用やStage 1の完了を宣言しないでください。B-1には書き込みを一意化する方式、B-2には欠落時の復旧と改変検知の扱いについて、契約との正確な衝突を報告します。
