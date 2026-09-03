"""``defaults.workspace_domain`` discovery + surgical config write (S75, N20).

The workspace domain is required to render ``kgent://`` URIs as native
platform URLs (``skills.urls.native_url``). When it is missing from
``~/.kgent/config.yaml`` it can be discovered from a ``lark-cli drive +search``
probe: every hit carries a server-rendered ``result_meta.url`` whose host is
the tenant domain (e.g. ``https://<tenant>.jp.larksuite.com/wiki/<token>``).

Deliberately NOT used as discovery sources (2026-09-02 findings):

- ``drive metas batch_query`` — returns ``970005`` unless the caller already
  has metadata permission on every token, so it fails exactly when discovery
  is needed;
- ``drive +inspect`` — echoes a generic ``www.larksuite.com`` placeholder,
  not the tenant domain.

The config write is surgical: only the ``defaults.workspace_domain`` key is
added/replaced. The rest of the file (including user edits such as
``enabled: true``) is preserved byte-for-byte — unlike ``kgent setup``, which
regenerates the whole file.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable, NamedTuple
from urllib.parse import urlsplit

from kgent.adapters.cli_adapter import run_cli
from kgent.config import _yaml
from kgent.errors import ConfigError

__all__ = [
    "ProbeResult",
    "discover_and_set",
    "extract_domain",
    "probe_workspace_domain",
    "set_workspace_domain",
    "validate_domain",
]

#: Full-text queries tried in order until one returns a hit. Any tenant with
#: at least one document matches one of these; probes are best-effort reads.
_PROBE_QUERIES: tuple[str, ...] = ("文档", "doc")

#: Generic marketing hosts returned by tools like ``drive +inspect`` — never
#: a tenant domain, so never a valid discovery result.
_PLACEHOLDER_HOSTS = frozenset({"www.larksuite.com", "www.feishu.cn"})

#: Hostname shape: dot-separated alphanumeric labels; no scheme, path, or ``_``.
_HOST_RE = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$"
)


class ProbeResult(NamedTuple):
    """Outcome of one discovery probe: a domain, or why none was found."""

    domain: str | None
    detail: str


def extract_domain(payload: Any) -> str | None:
    """Return the first usable tenant host from a ``drive +search`` JSON body.

    Placeholder hosts are skipped so a generic hit never masks a real tenant
    domain further down the result list. ``None`` when nothing usable remains.
    """
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return None
    for hit in results:
        meta = hit.get("result_meta") if isinstance(hit, dict) else None
        url = meta.get("url") if isinstance(meta, dict) else None
        if not isinstance(url, str) or not url:
            continue
        host = urlsplit(url).hostname
        if host and host not in _PLACEHOLDER_HOSTS and _HOST_RE.match(host):
            return host
    return None


def validate_domain(host: str) -> str:
    """Return ``host`` if it is a plausible tenant domain; raise otherwise."""
    candidate = str(host).strip()
    if candidate in _PLACEHOLDER_HOSTS:
        raise ConfigError(f"workspace_domain: {candidate!r} is a generic placeholder, not a tenant domain")
    if not _HOST_RE.match(candidate):
        raise ConfigError(
            f"workspace_domain: {candidate!r} is not a bare hostname "
            "(expected e.g. 'acme.jp.larksuite.com' — no scheme, no path)"
        )
    return candidate


def probe_workspace_domain(
    resolve: Callable[[str], str | None] = shutil.which,
) -> ProbeResult:
    """Discover the tenant domain via a read-only ``lark-cli drive +search``.

    The executable is resolved with :func:`shutil.which` first and spawned by
    full path: bare names fail on Windows, where npm-style shims are
    ``.cmd`` files that ``CreateProcess`` cannot launch by name.
    """
    exe = resolve("lark-cli")
    if exe is None:
        return ProbeResult(None, "lark-cli not found on PATH")
    for query in _PROBE_QUERIES:
        try:
            proc = run_cli(
                [exe, "drive", "+search", "--query", query, "--as", "user", "--json"],
                timeout=15.0,
            )
        except Exception as exc:  # spawn/timeout — probe must never crash setup flows
            return ProbeResult(None, f"lark-cli probe failed: {exc}")
        if proc.returncode != 0 or not (proc.stdout or "").strip():
            continue
        try:
            payload = json.loads(proc.stdout)
        except ValueError:
            continue
        domain = extract_domain(payload)
        if domain is not None:
            return ProbeResult(domain, "")
    return ProbeResult(None, "probe returned no usable document hits")


def discover_and_set(
    config_path: Path,
    probe: Callable[[], ProbeResult] = probe_workspace_domain,
) -> tuple[str | None, str]:
    """Probe for the tenant domain, validate it, then write it into config.

    Raises :class:`ConfigError` (without touching the file) when the probe
    yields nothing usable, pointing at the explicit ``--domain`` fallback.
    """
    result = probe()
    if result.domain is None:
        raise ConfigError(
            f"workspace_domain discovery failed ({result.detail or 'no domain found'}); "
            "set it explicitly: kgent config set-workspace-domain --domain <host>"
        )
    try:
        domain = validate_domain(result.domain)
    except ConfigError as exc:
        raise ConfigError(
            f"workspace_domain discovery returned an unusable domain ({exc}); "
            "set it explicitly: kgent config set-workspace-domain --domain <host>"
        ) from exc
    return set_workspace_domain(config_path, domain)


def set_workspace_domain(config_path: Path, domain: str) -> tuple[str | None, str]:
    """Set ``defaults.workspace_domain`` in the config, changing nothing else.

    Returns ``(previous, new)``. The file must parse cleanly first — an
    unparseable config is never rewritten. Everything outside the one key
    (comments, ordering, ``enabled`` flags, other defaults) is preserved.
    """
    domain = validate_domain(domain)
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(
            f"config file not found: {path} — run 'kgent setup' first, then retry"
        )
    text = path.read_text(encoding="utf-8")

    raw = _yaml.parse(text)  # ConfigError → caller sees it, file stays untouched
    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")
    defaults = raw.get("defaults")
    previous = defaults.get("workspace_domain") if isinstance(defaults, dict) else None

    updated = _inject_key(text, domain)
    fd = os.open(path, os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(updated)
    os.chmod(path, 0o600)
    return (None if previous is None else str(previous)), domain


# ---------------------------------------------------------------------------
# text-level key injection (surgical: comments and formatting survive)
# ---------------------------------------------------------------------------


def _inject_key(text: str, domain: str) -> str:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("defaults:"):
            continue
        if line[0].isspace():
            continue  # nested 'defaults:' under some other section
        inline = stripped[len("defaults:") :].strip()
        if inline == "{}":
            lines[idx] = "defaults:"
            lines.insert(idx + 1, f"  workspace_domain: {domain}")
            return _join(lines)
        block_end = idx + 1
        while block_end < len(lines) and lines[block_end][:1].isspace():
            key = lines[block_end].strip().split(":", 1)[0]
            if key == "workspace_domain":
                indent = lines[block_end][: len(lines[block_end]) - len(lines[block_end].lstrip())]
                lines[block_end] = f"{indent}workspace_domain: {domain}"
                return _join(lines)
            block_end += 1
        lines.insert(idx + 1, f"  workspace_domain: {domain}")
        return _join(lines)
    if lines and lines[-1].strip() == "":
        lines.pop()
    lines.append("defaults:")
    lines.append(f"  workspace_domain: {domain}")
    return _join(lines)


def _join(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"
