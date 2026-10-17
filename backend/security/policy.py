"""Centralized policy engine for Anything-to-MCP tool execution.

Evaluates every tool invocation against configured security rules:
- ALLOW: Operation may proceed to upstream API.
- DENY: Operation is strictly prohibited.
- REQUIRE_APPROVAL: Operation requires human approval before execution.
- DRY_RUN: Operation is simulated; no upstream HTTP request is dispatched.

Strict Precedence:
DENY > DRY_RUN > REQUIRE_APPROVAL > ALLOW.
"""

from enum import Enum
import os
from typing import Any, Optional
from pydantic import BaseModel, Field


class PolicyDecision(str, Enum):
    """Possible outcomes of security policy evaluation."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DRY_RUN = "DRY_RUN"


class PolicyEvaluationResult(BaseModel):
    """Detailed evaluation result returned before tool execution."""

    decision: PolicyDecision
    reason: str
    tool_name: str
    method: str
    path: str
    is_mutating: bool
    requires_approval: bool = False
    is_dry_run: bool = False
    is_denied: bool = False


class SecurityPolicy(BaseModel):
    """Configurable security policy model."""

    dry_run: bool = Field(default=False, description="Simulate mutating operations without sending HTTP requests")
    require_approval: bool = Field(default=False, description="Require human approval for mutating operations")
    mask_secrets: bool = Field(default=True, description="Enable layered secret masking across payloads and headers")
    denied_operations: list[str] = Field(default_factory=list, description="Explicitly forbidden tool names")
    denied_methods: list[str] = Field(default_factory=list, description="Explicitly forbidden HTTP methods (e.g. DELETE)")
    denied_paths: list[str] = Field(default_factory=list, description="Explicitly forbidden path patterns")
    operation_overrides: dict[str, PolicyDecision] = Field(
        default_factory=dict,
        description="Tool-specific policy overrides mapping tool_name to PolicyDecision",
    )

    @classmethod
    def from_env(cls) -> "SecurityPolicy":
        """Load policy configuration from environment variables."""
        dry_run = os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")
        require_approval = os.getenv("REQUIRE_APPROVAL", "false").lower() in ("true", "1", "yes")
        mask_secrets = os.getenv("MASK_SECRETS", "true").lower() in ("true", "1", "yes")

        denied_ops = [
            op.strip()
            for op in os.getenv("DENIED_OPERATIONS", "").split(",")
            if op.strip()
        ]
        denied_methods = [
            m.strip().upper()
            for m in os.getenv("DENIED_METHODS", "").split(",")
            if m.strip()
        ]

        return cls(
            dry_run=dry_run,
            require_approval=require_approval,
            mask_secrets=mask_secrets,
            denied_operations=denied_ops,
            denied_methods=denied_methods,
        )


class PolicyEngine:
    """Thread-safe policy evaluation engine."""

    def __init__(self, policy: Optional[SecurityPolicy] = None) -> None:
        self.policy = policy or SecurityPolicy.from_env()

    def update_policy(
        self,
        dry_run: Optional[bool] = None,
        require_approval: Optional[bool] = None,
        mask_secrets: Optional[bool] = None,
        denied_operations: Optional[list[str]] = None,
        denied_methods: Optional[list[str]] = None,
        operation_overrides: Optional[dict[str, PolicyDecision]] = None,
    ) -> SecurityPolicy:
        """Dynamically update runtime security policy."""
        if dry_run is not None:
            self.policy.dry_run = dry_run
        if require_approval is not None:
            self.policy.require_approval = require_approval
        if mask_secrets is not None:
            self.policy.mask_secrets = mask_secrets
        if denied_operations is not None:
            self.policy.denied_operations = denied_operations
        if denied_methods is not None:
            self.policy.denied_methods = [m.upper() for m in denied_methods]
        if operation_overrides is not None:
            self.policy.operation_overrides = operation_overrides
        return self.policy

    def evaluate(
        self,
        tool_name: str,
        method: str,
        path: str,
        arguments: Optional[dict[str, Any]] = None,
    ) -> PolicyEvaluationResult:
        """Evaluate security rules for a tool invocation immediately before execution.
        
        Enforces strict precedence:
        1. DENY rules cannot be bypassed.
        2. Explicit overrides (unless DENY).
        3. Dry-run mode intercepts mutating requests before dispatch.
        4. Require-approval pauses mutating requests for explicit confirmation.
        5. Default: Read-only operations ALLOW; mutating operations ALLOW unless configured otherwise.
        """
        norm_method = (method or "GET").upper()
        is_mutating = norm_method in ("POST", "PUT", "PATCH", "DELETE")

        # 1. Check DENY rules (Absolute Precedence)
        if tool_name in self.policy.denied_operations:
            return PolicyEvaluationResult(
                decision=PolicyDecision.DENY,
                reason=f"Tool '{tool_name}' is explicitly forbidden by security policy.",
                tool_name=tool_name,
                method=norm_method,
                path=path,
                is_mutating=is_mutating,
                is_denied=True,
            )

        if norm_method in [m.upper() for m in self.policy.denied_methods]:
            return PolicyEvaluationResult(
                decision=PolicyDecision.DENY,
                reason=f"HTTP method '{norm_method}' is explicitly blocked by security policy.",
                tool_name=tool_name,
                method=norm_method,
                path=path,
                is_mutating=is_mutating,
                is_denied=True,
            )

        for denied_p in self.policy.denied_paths:
            if denied_p and denied_p in path:
                return PolicyEvaluationResult(
                    decision=PolicyDecision.DENY,
                    reason=f"Path pattern '{denied_p}' is restricted by security policy.",
                    tool_name=tool_name,
                    method=norm_method,
                    path=path,
                    is_mutating=is_mutating,
                    is_denied=True,
                )

        # 2. Check operation-specific overrides
        if tool_name in self.policy.operation_overrides:
            override_decision = self.policy.operation_overrides[tool_name]
            # If override is DENY
            if override_decision == PolicyDecision.DENY:
                return PolicyEvaluationResult(
                    decision=PolicyDecision.DENY,
                    reason=f"Tool '{tool_name}' has an explicit DENY override.",
                    tool_name=tool_name,
                    method=norm_method,
                    path=path,
                    is_mutating=is_mutating,
                    is_denied=True,
                )
            # If dry-run is globally enabled, dry-run takes precedence over non-deny overrides for mutating ops
            if self.policy.dry_run and is_mutating:
                return PolicyEvaluationResult(
                    decision=PolicyDecision.DRY_RUN,
                    reason="Dry-run mode is enabled. Mutating operation intercepted before network dispatch.",
                    tool_name=tool_name,
                    method=norm_method,
                    path=path,
                    is_mutating=is_mutating,
                    is_dry_run=True,
                )
            return PolicyEvaluationResult(
                decision=override_decision,
                reason=f"Tool '{tool_name}' has an explicit {override_decision.value} override.",
                tool_name=tool_name,
                method=norm_method,
                path=path,
                is_mutating=is_mutating,
                requires_approval=(override_decision == PolicyDecision.REQUIRE_APPROVAL),
                is_dry_run=(override_decision == PolicyDecision.DRY_RUN),
            )

        # 3. Dry-Run Check (Takes precedence over approval)
        if self.policy.dry_run and is_mutating:
            return PolicyEvaluationResult(
                decision=PolicyDecision.DRY_RUN,
                reason="Dry-run mode is active. Mutating operations are simulated without sending upstream HTTP requests.",
                tool_name=tool_name,
                method=norm_method,
                path=path,
                is_mutating=is_mutating,
                is_dry_run=True,
            )

        # 4. Explicit Approval Check
        if self.policy.require_approval and is_mutating:
            return PolicyEvaluationResult(
                decision=PolicyDecision.REQUIRE_APPROVAL,
                reason=f"Explicit approval required for mutating operation '{norm_method} {path}'.",
                tool_name=tool_name,
                method=norm_method,
                path=path,
                is_mutating=is_mutating,
                requires_approval=True,
            )

        # 5. Default ALLOW
        return PolicyEvaluationResult(
            decision=PolicyDecision.ALLOW,
            reason="Operation permitted under active security policy.",
            tool_name=tool_name,
            method=norm_method,
            path=path,
            is_mutating=is_mutating,
        )


# Global default policy engine instance
global_policy_engine = PolicyEngine()
