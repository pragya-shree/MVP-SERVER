"""Safe execution audit history and logging for Anything-to-MCP security guardrails.

Maintains an in-memory bounded execution log with status badges:
- ALLOWED
- MUTATING
- BLOCKED
- DRY-RUN
- PENDING APPROVAL
- APPROVED
- EXECUTED
- FAILED
- SECRETS REDACTED

Never stores raw credentials, authorization headers, or unsanitized payloads.
"""

from collections import deque
from datetime import datetime, timezone
import threading
import time
from typing import Any, Optional
from pydantic import BaseModel, Field

from backend.security.redaction import global_redactor


class AuditEntry(BaseModel):
    """Sanitized record of a tool invocation or security decision."""

    id: str
    timestamp: str
    tool_name: str
    method: str
    sanitized_path: str
    policy_decision: str
    execution_status: str
    is_mutating: bool
    secrets_redacted: bool = False
    redaction_count: int = 0
    safe_arguments: Optional[dict[str, Any]] = None
    reason: Optional[str] = None
    status_code: Optional[int] = None
    approval_id: Optional[str] = None


class AuditLogger:
    """Thread-safe bounded audit history manager."""

    def __init__(self, max_entries: int = 100) -> None:
        self.max_entries = max_entries
        self._lock = threading.Lock()
        self._entries: deque[AuditEntry] = deque(maxlen=max_entries)
        self._counter = 0

    def record(
        self,
        tool_name: str,
        method: str,
        path: str,
        policy_decision: str,
        execution_status: str,
        is_mutating: bool,
        arguments: Optional[dict[str, Any]] = None,
        reason: Optional[str] = None,
        status_code: Optional[int] = None,
        secrets_redacted: bool = False,
        redaction_count: int = 0,
        approval_id: Optional[str] = None,
    ) -> AuditEntry:
        """Record an audited execution event after sanitizing all arguments."""
        with self._lock:
            self._counter += 1
            event_id = f"aud_{self._counter:06d}"
            now_iso = datetime.now(timezone.utc).isoformat()

            # Sanitize path to prevent accidental credentials in query strings
            sanitized_path, path_redacted = global_redactor.redact_text(path)
            # Sanitize arguments
            sanitized_args = None
            args_redacted = False
            args_count = 0
            if arguments:
                sanitized_args, args_count = global_redactor.redact_json(arguments)
                args_redacted = args_count > 0

            has_redaction = secrets_redacted or path_redacted > 0 or args_redacted
            total_redactions = redaction_count + path_redacted + args_count

            entry = AuditEntry(
                id=event_id,
                timestamp=now_iso,
                tool_name=tool_name,
                method=method.upper(),
                sanitized_path=sanitized_path,
                policy_decision=policy_decision,
                execution_status=execution_status,
                is_mutating=is_mutating,
                secrets_redacted=has_redaction,
                redaction_count=total_redactions,
                safe_arguments=sanitized_args,
                reason=global_redactor.sanitize_error(reason) if reason else None,
                status_code=status_code,
                approval_id=approval_id,
            )

            self._entries.appendleft(entry)
            return entry

    def get_entries(self, limit: int = 50) -> list[AuditEntry]:
        """Return the most recent audit records."""
        with self._lock:
            return list(self._entries)[:limit]

    def clear(self) -> None:
        """Clear audit history (for test isolation)."""
        with self._lock:
            self._entries.clear()
            self._counter = 0


# Global audit logger instance
global_audit_logger = AuditLogger()
