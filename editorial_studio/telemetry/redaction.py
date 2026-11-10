"""Sanitize at the persistence boundary, including provider error strings."""

import re
from typing import Any

from pydantic import SecretStr

SENSITIVE = re.compile(r"api.?key|authorization|password|secret|access.?token|cookie", re.I)


class Redactor:
    def __init__(self, secrets: list[str] = ()):
        self.secrets = sorted((s for s in secrets if len(s) >= 4), key=len, reverse=True)

    def text(self, value: str) -> str:
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED]", value)
        value = re.sub(r"(?i)Bearer\s+[^\s,\"']+", "Bearer [REDACTED]", value)
        return value

    def clean(self, value: Any) -> Any:
        # Dictionaries here are serialized provider payloads, never domain contracts.
        if isinstance(value, SecretStr):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {
                k: "[REDACTED]" if SENSITIVE.search(k) else self.clean(v)
                for k, v in value.items()
                if k not in {"encrypted_content", "chain_of_thought"}
            }
        if isinstance(value, (list, tuple)):
            return [self.clean(v) for v in value]
        return self.text(value) if isinstance(value, str) else value

    def provisional(self, value: str) -> str:
        # Hold incomplete secret prefixes across stream chunk boundaries.
        for secret in self.secrets:
            for length in range(min(len(secret) - 1, len(value)), 0, -1):
                if value.endswith(secret[:length]):
                    return self.text(value[:-length]) + "[REDACTED_PENDING]"
        return self.text(value)
