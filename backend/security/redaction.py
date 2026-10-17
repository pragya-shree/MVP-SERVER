"""Multi-layer secret redaction module for Anything-to-MCP.

Provides layered masking of sensitive credentials, API keys, tokens,
and authentication headers across HTTP requests, responses, logs,
and LLM tool outputs.
"""

import copy
import json
import logging
import os
import re
from typing import Any, Optional, Tuple, Union

DEFAULT_REDACTION_PLACEHOLDER = "[REDACTED_SECRET]"

# Sensitive HTTP header names (checked case-insensitively)
DEFAULT_SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "apikey",
    "x-auth-token",
    "auth-token",
    "cookie",
    "set-cookie",
    "x-csrf-token",
    "x-access-token",
}

# Sensitive JSON keys / field names (checked case-insensitively)
DEFAULT_SENSITIVE_FIELDS = {
    "access_token",
    "refresh_token",
    "id_token",
    "api_key",
    "apikey",
    "client_secret",
    "password",
    "secret",
    "token",
    "auth_token",
    "authorization",
    "private_key",
    "session_token",
    "sessionid",
    "bearer_token",
}

# Regex patterns for common secrets in plain text or structured strings
TOKEN_PATTERNS = [
    # Bearer tokens (e.g., Bearer eyJhbGciOi..., Bearer secret-token-12345)
    (re.compile(r"(?i)\b(bearer\s+)([a-zA-Z0-9_\-\.]{8,})"), r"\1" + DEFAULT_REDACTION_PLACEHOLDER),
    # Basic auth (e.g., Basic dXNlcjpwYXNz)
    (re.compile(r"(?i)\b(basic\s+)([a-zA-Z0-9+/=]{6,})"), r"\1" + DEFAULT_REDACTION_PLACEHOLDER),
    # OpenAI / Stripe / standard secret keys (sk-..., sk_live_..., sk_test_..., sk-proj-...)
    (re.compile(r"\b(sk[-_][a-zA-Z0-9_\-]{14,})\b"), DEFAULT_REDACTION_PLACEHOLDER),
    # GitHub personal access tokens (ghp_..., gho_..., ghu_...)
    (re.compile(r"\b(gh[pous]_[a-zA-Z0-9]{20,})\b"), DEFAULT_REDACTION_PLACEHOLDER),
    # Query param credentials (e.g. api_key=xyz, token=xyz, password=xyz)
    (re.compile(r"(?i)([?&](?:api[_-]?key|access[_-]?token|secret|password)=)([^&]+)"), r"\1" + DEFAULT_REDACTION_PLACEHOLDER),
    # Generic password assignments in text: password="xyz" or password='xyz'
    (re.compile(r"""(?i)(["']?(?:password|client_secret|private_key)["']?\s*[:=]\s*["'])([^"']{3,})(["'])"""), r"\1" + DEFAULT_REDACTION_PLACEHOLDER + r"\3"),
    # Cookie header contents: sessionid=xyz; auth_token=xyz
    (re.compile(r"(?i)\b((?:sessionid|token|jwt|auth|cookie|key)=)([^;,\s]+)"), r"\1" + DEFAULT_REDACTION_PLACEHOLDER),
]


class SecretRedactor:
    """Configurable multi-layer secret redaction engine."""

    def __init__(
        self,
        enabled: Optional[bool] = None,
        placeholder: str = DEFAULT_REDACTION_PLACEHOLDER,
        extra_sensitive_headers: Optional[set[str]] = None,
        extra_sensitive_fields: Optional[set[str]] = None,
    ) -> None:
        if enabled is None:
            # Environment variable takes priority; default is True
            env_val = os.getenv("MASK_SECRETS", "true").lower()
            self.enabled = env_val in ("true", "1", "yes")
        else:
            self.enabled = enabled

        self.placeholder = placeholder
        self.sensitive_headers = {h.lower() for h in DEFAULT_SENSITIVE_HEADERS}
        if extra_sensitive_headers:
            self.sensitive_headers.update(h.lower() for h in extra_sensitive_headers)

        self.sensitive_fields = {f.lower() for f in DEFAULT_SENSITIVE_FIELDS}
        if extra_sensitive_fields:
            self.sensitive_fields.update(f.lower() for f in extra_sensitive_fields)

    def redact_headers(self, headers: dict[str, Any]) -> Tuple[dict[str, Any], int]:
        """Redact known sensitive headers case-insensitively.
        
        Returns (sanitized_headers, count_of_redactions).
        """
        if not self.enabled or not headers:
            return copy.deepcopy(headers), 0

        sanitized: dict[str, Any] = {}
        redactions = 0

        for key, value in headers.items():
            lower_key = str(key).lower()
            if lower_key in self.sensitive_headers:
                sanitized[key] = self.placeholder
                redactions += 1
            else:
                # Value may still contain tokens like "Bearer xyz"
                val_str = str(value)
                cleaned_val, pattern_redactions = self.redact_text(val_str)
                sanitized[key] = cleaned_val
                redactions += pattern_redactions

        return sanitized, redactions

    def redact_json(self, data: Any) -> Tuple[Any, int]:
        """Recursively redact sensitive fields in dicts and lists while preserving structure.
        
        Returns (sanitized_data, count_of_redactions).
        """
        if not self.enabled or data is None:
            return copy.deepcopy(data), 0

        redactions = 0

        def _traverse(node: Any) -> Any:
            nonlocal redactions
            if isinstance(node, dict):
                cleaned_dict = {}
                for k, v in node.items():
                    k_lower = str(k).lower()
                    if k_lower in self.sensitive_fields:
                        cleaned_dict[k] = self.placeholder
                        redactions += 1
                    else:
                        cleaned_dict[k] = _traverse(v)
                return cleaned_dict
            elif isinstance(node, list):
                return [_traverse(item) for item in node]
            elif isinstance(node, str):
                cleaned_str, pattern_count = self.redact_text(node)
                redactions += pattern_count
                return cleaned_str
            else:
                return node

        sanitized = _traverse(data)
        return sanitized, redactions

    def redact_text(self, text: str) -> Tuple[str, int]:
        """Apply regex patterns to detect and mask credentials embedded in plain text.
        
        Returns (sanitized_text, count_of_redactions).
        """
        if not self.enabled or not text or not isinstance(text, str):
            return text, 0

        current = text
        redactions = 0

        for pattern, replacement in TOKEN_PATTERNS:
            new_text, count = pattern.subn(replacement, current)
            if count > 0:
                redactions += count
                current = new_text

        return current, redactions

    def redact_payload(self, payload: Any) -> Tuple[Any, bool, int]:
        """Generic redactor supporting dicts, lists, strings, and JSON text.
        
        Returns (sanitized_payload, was_redacted, total_redaction_count).
        """
        if not self.enabled:
            return payload, False, 0

        if isinstance(payload, (dict, list)):
            sanitized, count = self.redact_json(payload)
            return sanitized, count > 0, count

        if isinstance(payload, str):
            # Try to see if string is JSON
            stripped = payload.strip()
            if (stripped.startswith("{") and stripped.endswith("}")) or (
                stripped.startswith("[") and stripped.endswith("]")
            ):
                try:
                    parsed = json.loads(payload)
                    sanitized_obj, count = self.redact_json(parsed)
                    return json.dumps(sanitized_obj, indent=2), count > 0, count
                except Exception:
                    pass

            sanitized_txt, count = self.redact_text(payload)
            return sanitized_txt, count > 0, count

        return payload, False, 0

    def sanitize_error(self, err: Union[Exception, str]) -> str:
        """Sanitize an exception or error message before returning to user or LLM."""
        msg = str(err)
        cleaned, _ = self.redact_text(msg)
        return cleaned

    def log_safe(self, logger: logging.Logger, level: int, message: str, *args: Any) -> None:
        """Format and log a message ensuring all credentials are redacted beforehand."""
        if not self.enabled:
            logger.log(level, message, *args)
            return

        formatted = message % args if args else message
        cleaned, _ = self.redact_text(formatted)
        logger.log(level, cleaned)


# Global singleton instance with standard settings
global_redactor = SecretRedactor()
