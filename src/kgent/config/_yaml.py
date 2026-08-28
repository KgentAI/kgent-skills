"""Minimal YAML-subset loader for kgent config files (§2.1, §2.3).

Supports exactly what the config schema needs — indent-based mappings, block
and inline lists, scalars (str/int/bool/None), comments, and quoted strings.
Full YAML constructs (anchors, aliases, merge keys, tags, flow mappings) are
rejected with :class:`~kgent.errors.ConfigError`.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from kgent.errors import ConfigError

__all__ = ["parse"]


class _Line(NamedTuple):
    indent: int
    text: str
    number: int


def parse(text: str) -> Any:
    """Parse a YAML-subset document into plain Python objects."""
    lines = _tokenize(text)
    if not lines:
        return {}
    parser = _Parser(lines)
    result = parser.parse_node(0)
    if result is None:
        return {}
    if parser.index < len(parser.lines):
        line = parser.lines[parser.index]
        raise ConfigError(f"unexpected content at line {line.number}")
    return result


def _tokenize(text: str) -> list[_Line]:
    lines: list[_Line] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip(" ")
        if stripped.startswith("\t"):
            raise ConfigError(f"tab indentation is not allowed (line {number})")
        indent = len(line) - len(stripped)
        lines.append(_Line(indent, stripped, number))
    return lines


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "\\" and in_double and i + 1 < n:
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:i]
        i += 1
    return line


def _find_unquoted_colon(s: str) -> int:
    in_single = False
    in_double = False
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and in_double and i + 1 < n:
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ":" and not in_single and not in_double:
            return i
        i += 1
    return -1


def _split_unquoted(s: str, sep: str) -> list[str]:
    parts: list[str] = []
    in_single = False
    in_double = False
    current: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and in_double and i + 1 < n:
            current.append(s[i : i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
        elif ch == sep and not in_single and not in_double:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    parts.append("".join(current))
    return parts


def _split_key_value(text: str, number: int) -> tuple[str, str | None]:
    idx = _find_unquoted_colon(text)
    if idx == -1:
        raise ConfigError(f"expected 'key: value' at line {number}")
    key = text[:idx].strip()
    value = text[idx + 1 :].strip()
    if key == "<<":
        raise ConfigError(f"merge keys are not supported (line {number})")
    if key.startswith(("&", "*", "!")):
        raise ConfigError(f"anchors, aliases and tags are not supported (line {number})")
    if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
        key = key[1:-1]
    if value == "":
        return key, None
    return key, value


def _parse_inline(s: str, number: int) -> Any:
    s = s.strip()
    if s == "":
        return None
    if s.startswith("{"):
        raise ConfigError(f"flow mappings are not supported (line {number})")
    if s.startswith("["):
        return _parse_inline_list(s, number)
    if s.startswith(("&", "*", "!")):
        raise ConfigError(f"anchors, aliases and tags are not supported (line {number})")
    if s == "<<":
        raise ConfigError(f"merge keys are not supported (line {number})")
    return _parse_scalar(s)


def _parse_inline_list(s: str, number: int) -> list[Any]:
    if not s.endswith("]"):
        raise ConfigError(f"malformed inline list (line {number})")
    inner = s[1:-1].strip()
    if inner == "":
        return []
    result: list[Any] = []
    for part in _split_unquoted(inner, ","):
        part = part.strip()
        if part == "":
            raise ConfigError(f"malformed inline list (line {number})")
        result.append(_parse_inline(part, number))
    return result


def _parse_scalar(s: str) -> Any:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    lowered = s.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("null", "~"):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


class _Parser:
    def __init__(self, lines: list[_Line]) -> None:
        self.lines = lines
        self.index = 0

    def parse_node(self, indent: int) -> Any:
        if self.index >= len(self.lines):
            return None
        line = self.lines[self.index]
        if line.indent < indent:
            return None
        if line.indent > indent:
            raise ConfigError(f"unexpected indentation at line {line.number}")
        if line.text.startswith("- "):
            return self._parse_list(indent)
        return self._parse_mapping(indent)

    def _parse_mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while self.index < len(self.lines):
            line = self.lines[self.index]
            if line.indent < indent:
                break
            if line.indent > indent:
                raise ConfigError(f"unexpected indentation at line {line.number}")
            if line.text.startswith("- "):
                break
            key, inline = _split_key_value(line.text, line.number)
            self.index += 1
            if inline is None:
                if self.index < len(self.lines) and self.lines[self.index].indent > indent:
                    result[key] = self.parse_node(self.lines[self.index].indent)
                else:
                    result[key] = None
            else:
                result[key] = _parse_inline(inline, line.number)
        return result

    def _parse_list(self, indent: int) -> list[Any]:
        result: list[Any] = []
        while self.index < len(self.lines):
            line = self.lines[self.index]
            if line.indent < indent:
                break
            if line.indent > indent:
                raise ConfigError(f"unexpected indentation at line {line.number}")
            if not line.text.startswith("- "):
                break
            rest = line.text[2:].strip()
            self.index += 1
            if rest == "":
                if self.index < len(self.lines) and self.lines[self.index].indent > indent:
                    result.append(self.parse_node(self.lines[self.index].indent))
                else:
                    result.append(None)
            else:
                result.append(self._parse_list_item(rest, indent, line.number))
        return result

    def _parse_list_item(self, rest: str, indent: int, number: int) -> Any:
        if _find_unquoted_colon(rest) == -1:
            return _parse_inline(rest, number)
        key, inline = _split_key_value(rest, number)
        item: dict[str, Any] = {}
        if inline is None:
            if self.index < len(self.lines) and self.lines[self.index].indent > indent:
                item[key] = self.parse_node(self.lines[self.index].indent)
            else:
                item[key] = None
        else:
            item[key] = _parse_inline(inline, number)
        # Remaining keys of this list-item mapping are aligned under the dash.
        item.update(self._parse_mapping(indent + 2))
        return item
