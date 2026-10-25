"""Shared validator for bytes returned by a host's own native delegation API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..evidence_store import VerificationSubject
from ..review_assurance import IndependentReviewV2, attest_native_review


@dataclass(frozen=True)
class AdapterCapabilities:
    surface: str
    native_request_return_capture: bool
    trusted_host_event_verification: bool
    host_ids_optional: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "host_ids_optional": self.host_ids_optional,
            "native_request_return_capture": self.native_request_return_capture,
            "surface": self.surface,
            "trusted_host_event_verification": self.trusted_host_event_verification,
        }


class NativeReviewAdapter:
    surface = "unsupported"

    @classmethod
    def capabilities(cls) -> AdapterCapabilities:
        # This package validates captured bytes but is not itself connected to a
        # host's native delegate API. Do not advertise a live capability.
        return AdapterCapabilities(cls.surface, native_request_return_capture=False,
                                   trusted_host_event_verification=False)

    @classmethod
    def attest(cls, *, subject: VerificationSubject, execution_identity_context_id: str,
               profile_sha256: str, request: bytes, terminal_return: bytes,
               child_output: bytes, host_spawn_id: str | None = None,
               host_child_id: str | None = None,
               host_join_id: str | None = None) -> IndependentReviewV2:
        """Validate exact native tool bytes supplied by the host integration.

        Adapters never spawn an agent executable and never infer host event IDs.
        A returned record is INDEPENDENT_ATTESTED; it is not host-authenticated.
        """
        return attest_native_review(
            subject=subject,
            execution_identity_context_id=execution_identity_context_id,
            profile_sha256=profile_sha256,
            request=request,
            terminal_return=terminal_return,
            child_output=child_output,
            host_spawn_id=host_spawn_id,
            host_child_id=host_child_id,
            host_join_id=host_join_id,
        )
