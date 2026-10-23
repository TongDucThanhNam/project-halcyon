"""Opt-in client-facing origins for an owned-domain, unmodified CE experiment.

This changes advertised URLs only, not DNS, certificates, listeners or gameplay.
Absent environment settings preserve the existing emulator response contract.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
import re
from urllib.parse import urlsplit, urlunsplit


RPC_FIELDS = frozenset(("startSessionUrl", "platformUrl"))
NOTIFY_FIELDS = frozenset(("notifyUrl", "notifyFallbackUrl"))


def _origin(value: str, schemes: tuple[str, ...]) -> str:
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("client endpoint must be a nonempty URL without whitespace")
    parts = urlsplit(value)
    if (parts.scheme not in schemes or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.path not in ("", "/") or parts.query or parts.fragment
            or "?" in value or "#" in value or parts.netloc.endswith(":")):
        raise ValueError("client endpoint must be an allowed origin, without credentials/path/query/fragment")
    host = parts.hostname
    if len(host) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                              for label in host.split(".")):
        raise ValueError("client endpoint requires an ASCII DNS hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("client endpoint requires a DNS hostname, not a numeric address")
    port = parts.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("client endpoint port must be in 1..65535")
    default_port = 80 if parts.scheme == "ws" else 443
    authority = host if port in (None, default_port) else f"{host}:{port}"
    return f"{parts.scheme}://{authority}"


@dataclass(frozen=True)
class ClientEndpoints:
    rpc_origin: str
    notify_origin: str

    @property
    def bootstrap_authority(self) -> str:
        parts = urlsplit(self.rpc_origin)
        return f"{parts.hostname}:{parts.port or 443}"

    def rewrite(self, value):
        """Rewrite only named transport fields; retain paths, tokens and shapes."""
        if isinstance(value, list):
            return [self.rewrite(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key in RPC_FIELDS | NOTIFY_FIELDS and item:
                if not isinstance(item, str) or any(c.isspace() or ord(c) < 32 for c in item):
                    raise ValueError("invalid client transport URL in scripted response")
                old = urlsplit(item)
                allowed = ("http", "https") if key in RPC_FIELDS else ("ws", "wss")
                if old.scheme not in allowed or not old.hostname or old.username is not None:
                    raise ValueError("invalid client transport URL in scripted response")
                origin = urlsplit(self.rpc_origin if key in RPC_FIELDS else self.notify_origin)
                result[key] = urlunsplit((origin.scheme, origin.netloc, old.path, old.query, old.fragment))
            else:
                result[key] = self.rewrite(item)
        return result


def from_environment(environ=None) -> ClientEndpoints | None:
    env = os.environ if environ is None else environ
    rpc = env.get("HALCYON_PLATFORM_ORIGIN")
    notify = env.get("HALCYON_NOTIFY_ORIGIN")
    if rpc is None:
        if notify is not None:
            raise ValueError("HALCYON_NOTIFY_ORIGIN requires HALCYON_PLATFORM_ORIGIN")
        return None
    rpc = _origin(rpc, ("https",))
    # Keep the measured cleartext WebSocket transport inside the private VPN.
    # wss is explicit opt-in, not a claim that the CE client supports it.
    notify = _origin(notify if notify is not None else f"ws://{urlsplit(rpc).hostname}", ("ws", "wss"))
    return ClientEndpoints(rpc, notify)
