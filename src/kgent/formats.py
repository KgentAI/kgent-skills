"""Format bridge: markdown ↔ minimal Confluence storage XHTML (ADR 0016).

The single shared converter behind ``kgent formats`` and the confluence
adapter — deliberately the only implementation (skill prose must not grow a
second one). markdown is kgent's lingua franca; Confluence Cloud v2 has no
markdown representation, so:

- read  = storage XHTML → markdown (lossy: bridge-external structures degrade
  to declared placeholders, script/style content is stripped);
- write = markdown → minimal-subset storage XHTML (bridge-external constructs
  are REFUSED, never silently dropped; raw HTML is rejected outright).

Minimal subset (both directions): ``p``, ``h1–h6``, ``ul/ol/li``, ``pre/code``,
``table`` (``tr/th/td``), ``blockquote``, ``hr``, ``strong/b``, ``em/i``,
``code``, ``a``, ``br``. stdlib only (``html.parser`` + ``html.escape``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser

from kgent.errors import KgentError

__all__ = ["markdown_to_storage", "storage_to_markdown"]

_MACRO_PLACEHOLDER = '[kgent: unsupported confluence macro "{name}"]'
_MEDIA_PLACEHOLDER = "[confluence attachment omitted]"

# Raw HTML / image detection runs on the markdown source BEFORE tokenization —
# these are write-side refusals, not escapes (spec 2026-09-22 Tier table).
_RAW_HTML = re.compile(r"</?[a-zA-Z][^>]*>|<!--|<!")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")

_FENCE = "```"


# ---------------------------------------------------------------------------
# storage XHTML → markdown (read direction)
# ---------------------------------------------------------------------------


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str]
    children: list[_Node | str] = field(default_factory=list)


_VOID = frozenset({"br", "hr", "img"})
_SKIP_SUBTREE = frozenset({"script", "style"})


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self.stack: list[_Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_SUBTREE:
            self.stack.append(_Node("#skip", {}))
            return
        node = _Node(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_SUBTREE:
            return
        self.stack[-1].children.append(_Node(tag, {k: v or "" for k, v in attrs}))

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_SUBTREE:
            if len(self.stack) > 1 and self.stack[-1].tag == "#skip":
                self.stack.pop()
            return
        # Lenient on malformed input: unwind to the matching open tag if present.
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _inline(nodes: list[_Node | str]) -> str:
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, str):
            parts.append(re.sub(r"\s+", " ", node))
            continue
        tag = node.tag
        inner = _inline(node.children)
        if tag in ("strong", "b"):
            parts.append(f"**{inner.strip()}**" if inner.strip() else "")
        elif tag in ("em", "i"):
            parts.append(f"*{inner.strip()}*" if inner.strip() else "")
        elif tag == "code":
            parts.append(f"`{inner.strip()}`" if inner.strip() else "")
        elif tag == "a":
            parts.append(
                f"[{inner.strip()}]({node.attrs.get('href', '')})" if inner.strip() else ""
            )
        elif tag == "br":
            parts.append("\n")
        elif tag == "hr":
            parts.append("\n---\n")
        elif tag == "span":
            parts.append(inner)
        # other inline strangers degrade to their text content (declared lossy)
        else:
            parts.append(inner)
    return "".join(parts)


def _blocks(nodes: list[_Node | str]) -> list[str]:
    out: list[str] = []
    for node in nodes:
        if isinstance(node, str):
            text = re.sub(r"\s+", " ", node).strip()
            if text:
                out.append(text)
            continue
        tag = node.tag
        if tag in ("p",):
            text = _inline(node.children).strip()
            if text:
                out.append(text)
        elif re.fullmatch(r"h[1-6]", tag):
            level = int(tag[1])
            out.append("#" * level + " " + _inline(node.children).strip())
        elif tag in ("ul", "ol"):
            lines = _list_lines(node, tag, 0)
            if lines:
                out.append("\n".join(lines))
        elif tag == "pre":
            code = _raw_text(node).strip("\n")
            out.append(_FENCE + "\n" + code + "\n" + _FENCE)
        elif tag == "blockquote":
            inner = _blocks(node.children)
            out.extend("> " + line for line in inner)
        elif tag == "hr":
            out.append("---")
        elif tag == "table":
            lines = _table_lines(node)
            if lines:
                out.append("\n".join(lines))
        elif tag.startswith("ac:"):
            out.append(_macro_placeholder(node))
        elif tag in ("div", "span", "section", "body"):
            out.extend(_blocks(node.children))
        # anything else (Confluence internals, unknown tags): inner text survives,
        # structure does not — the lossy direction is declared in fidelity docs.
        else:
            out.extend(_blocks(node.children))
    return out


def _list_lines(node: _Node, kind: str, depth: int) -> list[str]:
    lines: list[str] = []
    index = 0
    marker = "-" if kind == "ul" else None
    for child in node.children:
        if isinstance(child, _Node) and child.tag in ("ul", "ol"):
            # Confluence emits bare nested lists without an intervening <li>;
            # descending keeps their content visible instead of dropping it.
            lines.extend(_list_lines(child, child.tag, depth))
            continue
        if not isinstance(child, _Node) or child.tag != "li":
            continue
        if kind == "ol":
            index += 1
            prefix = f"{index}. "
        else:
            prefix = f"{marker} "
        own: list[_Node | str] = []
        nested: list[str] = []
        for item in child.children:
            if isinstance(item, _Node) and item.tag in ("ul", "ol"):
                nested.extend(_list_lines(item, item.tag, depth + 1))
            else:
                own.append(item)
        text = _inline(own).strip()
        lines.append("  " * depth + prefix + text)
        lines.extend(nested)
    return lines


def _table_lines(node: _Node) -> list[str]:
    rows: list[list[str]] = []
    header: list[str] | None = None

    def collect(n: _Node) -> None:
        nonlocal header
        if n.tag == "tr":
            cells = [
                _inline(c.children).strip()
                for c in n.children
                if isinstance(c, _Node) and c.tag in ("th", "td")
            ]
            if cells:
                if all(
                    isinstance(c, _Node) and c.tag == "th"
                    for c in n.children
                    if isinstance(c, _Node)
                ):
                    header = cells
                else:
                    rows.append(cells)
            return
        for child in n.children:
            if isinstance(child, _Node):
                collect(child)

    collect(node)
    widths = [len(header or []), *(len(r) for r in rows)]
    width = max(widths) if widths else 1
    lines: list[str] = []
    if header is None and rows:
        header = rows.pop(0)
    header = header or [""] * width
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * width) + " |")
    for row in rows:
        row = row + [""] * (width - len(row))
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _macro_placeholder(node: _Node) -> str:
    if node.tag in ("ac:image", "ac:attachment", "ac:media", "ac:link"):
        return _MEDIA_PLACEHOLDER
    name = node.attrs.get("ac:name") or node.attrs.get("name") or node.tag
    return _MACRO_PLACEHOLDER.format(name=name)


def _raw_text(node: _Node) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag not in _SKIP_SUBTREE:
            parts.append(_raw_text(child))
    return "".join(parts)


def storage_to_markdown(xhtml: str) -> str:
    """Convert Confluence storage-format XHTML to markdown (ADR 0016, read)."""
    builder = _TreeBuilder()
    builder.feed(xhtml)
    builder.close()
    return "\n\n".join(_blocks(builder.root.children))


# ---------------------------------------------------------------------------
# markdown → storage XHTML (write direction)
# ---------------------------------------------------------------------------


def _esc(text: str) -> str:
    return escape(text, quote=False)


def _inline_to_xhtml(text: str) -> str:
    # code spans first: their content is literal, invisible to other tokens
    parts: list[str] = []
    pos = 0
    for match in re.finditer(r"`([^`]+)`", text):
        parts.append(_emit_inline(text[pos : match.start()]))
        parts.append("<code>" + _esc(match.group(1)) + "</code>")
        pos = match.end()
    parts.append(_emit_inline(text[pos:]))
    return "".join(parts)


def _emit_inline(text: str) -> str:
    out = _esc(text)
    out = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: f'<a href="{escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        out,
    )
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", out)
    return out


def markdown_to_storage(markdown: str) -> str:
    """Convert markdown to minimal-subset storage XHTML (ADR 0016, write).

    Raises :class:`KgentError` on bridge-external constructs (images, raw
    HTML, fenced code containing a fence) — refusal, never silent drop.
    """
    if _IMAGE.search(markdown):
        raise KgentError(
            "format bridge: markdown images are not supported by confluence (ADR 0016)"
        )
    if _RAW_HTML.search(markdown.replace("\n", " ")):
        raise KgentError("format bridge: raw HTML in markdown is not supported (ADR 0016)")

    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith(_FENCE):
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != _FENCE:
                if _FENCE in lines[i]:
                    raise KgentError("format bridge: nested code fence is not supported (ADR 0016)")
                code_lines.append(lines[i])
                i += 1
            if i >= len(lines):
                raise KgentError("format bridge: unterminated code fence")
            i += 1  # closing fence
            blocks.append("<pre><code>" + _esc("\n".join(code_lines)) + "</code></pre>")
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            blocks.append(f"<h{level}>" + _inline_to_xhtml(heading.group(2)) + f"</h{level}>")
            i += 1
            continue

        if stripped == "---":
            blocks.append("<hr/>")
            i += 1
            continue

        if stripped.startswith(">"):
            quote: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            inner = _paragraph_blocks(quote)
            blocks.append("<blockquote>" + "".join(inner) + "</blockquote>")
            continue

        if stripped.startswith("|"):
            table_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            blocks.append(_table_to_xhtml(table_lines))
            continue

        ul = stripped.startswith(("- ", "* ", "+ "))
        ol = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
        if ul or ol:
            items: list[str] = []
            tag = "ul"
            while i < len(lines):
                cur = lines[i].strip()
                m_ol = re.match(r"^(\d+)[.)]\s+(.*)$", cur)
                if cur.startswith(("- ", "* ", "+ ")):
                    if tag == "ol":
                        break
                    items.append(cur[2:].strip())
                    i += 1
                elif m_ol:
                    if tag == "ul":
                        tag = "ol"
                    items.append(m_ol.group(2))
                    i += 1
                else:
                    break
            # (raw-HTML-in-list needs no re-check here: the function-entry
            # _RAW_HTML scan already refuses any such markdown.)
            blocks.append(
                f"<{tag}>"
                + "".join("<li>" + _inline_to_xhtml(it) + "</li>" for it in items)
                + f"</{tag}>"
            )
            continue

        para: list[str] = []
        while i < len(lines) and lines[i].strip() and not _starts_block(lines[i].strip()):
            para.append(lines[i].strip())
            i += 1
        blocks.append("<p>" + _inline_to_xhtml(" ".join(para)) + "</p>")

    return "".join(blocks)


def _starts_block(stripped: str) -> bool:
    return (
        stripped.startswith(("```", ">", "|", "- ", "* ", "+ ", "---"))
        or bool(re.match(r"^#{1,6}\s+", stripped))
        or bool(re.match(r"^\d+[.)]\s+", stripped))
    )


def _paragraph_blocks(lines: list[str]) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for line in lines:
        if line:
            current.append(line)
        elif current:
            chunks.append(" ".join(current))
            current = []
    if current:
        chunks.append(" ".join(current))
    return ["<p>" + _inline_to_xhtml(c) + "</p>" for c in chunks]


def _table_to_xhtml(table_lines: list[str]) -> str:
    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip("|").split("|")]

    header: list[str] | None = None
    rows: list[list[str]] = []
    for idx, line in enumerate(table_lines):
        parsed = cells(line)
        if all(re.fullmatch(r":?-{3,}:?", c) for c in parsed if c):
            continue  # separator row
        if header is None and idx <= 1:
            header = parsed
        else:
            rows.append(parsed)
    header = header or []
    parts = ["<table><tbody>"]
    if header:
        parts.append(
            "<tr>" + "".join("<th>" + _inline_to_xhtml(c) + "</th>" for c in header) + "</tr>"
        )
    for row in rows:
        parts.append(
            "<tr>" + "".join("<td>" + _inline_to_xhtml(c) + "</td>" for c in row) + "</tr>"
        )
    parts.append("</tbody></table>")
    return "".join(parts)
