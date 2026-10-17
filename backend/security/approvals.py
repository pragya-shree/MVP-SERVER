"""Cryptographically bound, stateful approval management for sensitive MCP tool operations.

Enforces:
- Unique approval request IDs
- Argument binding & SHA-256 fingerprint validation
- Time-to-live (TTL) expiration
- Single-use consumption (anti-replay defense)
- Human-in-the-loop verification (model-supplied flags alone are rejected)
"""

from datetime import datetime, timezone
import hashlib
import json
import secrets
import threading
import time
from typing import Any, Optional
from pydantic import BaseModel, Field

from backend.security.redaction import global_redactor


class ApprovalStatus(str):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXECUTED = "EXECUTED"


def compute_argument_hash(arguments: Optional[dict[str, Any]]) -> str:
    """Compute a deterministic SHA-256 fingerprint for operation arguments."""
    if not arguments:
        return hashlib.sha256(b"{}").hexdigest()
    try:
        canonical_json = json.dumps(arguments, sort_keys=True, default=str)
    except Exception:
        canonical_json = str(arguments)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class ApprovalRequest(BaseModel):
    """Approval request bound to a specific tool, operation, and arguments."""

    approval_id: str
    tool_name: str
    method: str
    path: str
    argument_hash: str
    safe_arguments: dict[str, Any]
    status: str = ApprovalStatus.PENDING
    created_at: float = Field(default_factory=time.time)
    expires_at: float
    reason: str = "Mutating operation requires explicit authorization"
    approved_at: Optional[float] = None
    executed_at: Optional[float] = None

    @property
    def is_expired(self) -> bool:
        """Check if approval has passed its expiration timestamp."""
        return time.time() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to public dictionary suitable for API and UI rendering."""
        created_dt = datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat()
        expires_dt = datetime.fromtimestamp(self.expires_at, tz=timezone.utc).isoformat()
        
        current_status = self.status
        if current_status == ApprovalStatus.PENDING and self.is_expired:
            current_status = ApprovalStatus.EXPIRED

        return {
            "approval_id": self.approval_id,
            "tool_name": self.tool_name,
            "method": self.method,
            "path": self.path,
            "status": current_status,
            "safe_arguments": self.safe_arguments,
            "reason": self.reason,
            "created_at": created_dt,
            "expires_at": expires_dt,
            "ttl_remaining_seconds": max(0, int(self.expires_at - time.time())),
        }


class ApprovalStore:
    """Thread-safe in-memory approval manager."""

    def __init__(self, default_ttl_seconds: int = 300) -> None:
        self.default_ttl = default_ttl_seconds
        self._lock = threading.Lock()
        self._requests: dict[str, ApprovalRequest] = {}
        # Keep non-sensitive internal mapping of raw arguments for verified execution
        self._bound_args: dict[str, dict[str, Any]] = {}

    def create_request(
        self,
        tool_name: str,
        method: str,
        path: str,
        arguments: Optional[dict[str, Any]] = None,
        reason: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> ApprovalRequest:
        """Create and register a new pending approval bound to exact arguments."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        now = time.time()
        approval_id = f"appr_{secrets.token_urlsafe(16)}"

        args_dict = dict(arguments or {})
        arg_hash = compute_argument_hash(args_dict)

        # Redact secrets from safe_arguments before storing for display
        sanitized_args, _ = global_redactor.redact_json(args_dict)

        req = ApprovalRequest(
            approval_id=approval_id,
            tool_name=tool_name,
            method=method.upper(),
            path=path,
            argument_hash=arg_hash,
            safe_arguments=sanitized_args,
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=now + ttl,
            reason=reason or f"Sensitive {method.upper()} operation requires human approval",
        )

        with self._lock:
            self._requests[approval_id] = req
            self._bound_args[approval_id] = args_dict

        return req

    def get_request(self, approval_id: str) -> Optional[ApprovalRequest]:
        """Retrieve an approval request by ID, updating status if expired."""
        with self._lock:
            req = self._requests.get(approval_id)
            if not req:
                return None
            if req.status == ApprovalStatus.PENDING and req.is_expired:
                req.status = ApprovalStatus.EXPIRED
            return req

    def list_requests(self, include_resolved: bool = True) -> list[ApprovalRequest]:
        """List stored approval requests sorted by most recent."""
        with self._lock:
            items = []
            for req in self._requests.values():
                if req.status == ApprovalStatus.PENDING and req.is_expired:
                    req.status = ApprovalStatus.EXPIRED
                if include_resolved or req.status == ApprovalStatus.PENDING:
                    items.append(req)
            return sorted(items, key=lambda r: r.created_at, reverse=True)

    def approve(self, approval_id: str) -> tuple[bool, str]:
        """Mark a pending approval as APPROVED by a human user."""
        with self._lock:
            req = self._requests.get(approval_id)
            if not req:
                return False, f"Approval request '{approval_id}' not found."

            if req.is_expired:
                req.status = ApprovalStatus.EXPIRED
                return False, f"Approval request '{approval_id}' has expired."

            if req.status == ApprovalStatus.REJECTED:
                return False, f"Approval request '{approval_id}' was already rejected."

            if req.status == ApprovalStatus.EXECUTED:
                return False, f"Approval request '{approval_id}' was already executed."

            if req.status == ApprovalStatus.APPROVED:
                return True, "Approval already granted."

            req.status = ApprovalStatus.APPROVED
            req.approved_at = time.time()
            return True, f"Approval granted for {req.tool_name}."

    def reject(self, approval_id: str, reason: Optional[str] = None) -> tuple[bool, str]:
        """Mark a pending approval as REJECTED."""
        with self._lock:
            req = self._requests.get(approval_id)
            if not req:
                return False, f"Approval request '{approval_id}' not found."

            if req.status == ApprovalStatus.EXECUTED:
                return False, "Cannot reject an already executed approval."

            req.status = ApprovalStatus.REJECTED
            if reason:
                req.reason = f"Rejected: {reason}"
            return True, f"Approval request '{approval_id}' has been rejected."

    def consume_and_verify(
        self,
        approval_id: str,
        tool_name: str,
        arguments: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, str, Optional[dict[str, Any]]]:
        """Single-use verification to execute an approved operation.
        
        Validates:
        1. Approval exists
        2. Status is APPROVED (not PENDING, REJECTED, EXPIRED, or already EXECUTED)
        3. Expiration has not passed
        4. Tool name matches
        5. Argument hash matches exact bound payload
        
        If valid, marks status as EXECUTED to prevent replay attacks and returns bound arguments.
        """
        with self._lock:
            req = self._requests.get(approval_id)
            if not req:
                return False, f"Invalid approval ID: '{approval_id}' not found.", None

            if req.is_expired:
                req.status = ApprovalStatus.EXPIRED
                return False, f"Approval request '{approval_id}' has expired.", None

            if req.status == ApprovalStatus.REJECTED:
                return False, f"Approval request '{approval_id}' was rejected and cannot be executed.", None

            if req.status == ApprovalStatus.EXECUTED:
                return False, f"Approval request '{approval_id}' has already been consumed (replay prevention).", None

            if req.status != ApprovalStatus.APPROVED:
                return False, f"Approval request '{approval_id}' is still in status '{req.status}'.", None

            # Verify bound tool name
            if req.tool_name != tool_name:
                return False, f"Approval '{approval_id}' is bound to tool '{req.tool_name}', not '{tool_name}'.", None

            # Verify argument binding
            incoming_hash = compute_argument_hash(arguments)
            if req.argument_hash != incoming_hash:
                return (
                    False,
                    f"Arguments do not match the parameters authorized for approval '{approval_id}'. Tampering prevented.",
                    None,
                )

            # Mark as EXECUTED to prevent replay
            req.status = ApprovalStatus.EXECUTED
            req.executed_at = time.time()
            bound_args = self._bound_args.get(approval_id, arguments or {})
            return True, "Approval successfully consumed.", bound_args

    def clear(self) -> None:
        """Reset store (useful for test isolation)."""
        with self._lock:
            self._requests.clear()
            self._bound_args.clear()


# Global singleton approval store
global_approval_store = ApprovalStore()
