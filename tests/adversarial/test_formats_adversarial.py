"""Adversarial corpus for the format bridge (spec 2026-09-22, A4).

Malicious / malformed storage XHTML and markdown must never crash the
converter, never smuggle scripts through to markdown, and never let raw
HTML through the write direction.
"""

import pytest

from kgent.errors import KgentError
from kgent.formats import markdown_to_storage, storage_to_markdown


class TestReadDirectionHostile:
    def test_script_in_paragraph_stripped(self):
        md = storage_to_markdown("<p>a</p><p><script>alert(document.cookie)</script>b</p>")
        assert "alert" not in md
        assert "a" in md and "b" in md

    def test_event_handler_attributes_dropped_with_tag(self):
        md = storage_to_markdown('<p><span onmouseover="steal()">text</span></p>')
        assert "steal" not in md
        assert "text" in md

    def test_deeply_nested_lists_do_not_crash(self):
        xhtml = "<ul>" * 200 + "<li>x</li>" + "</ul>" * 200
        md = storage_to_markdown(xhtml)
        assert "x" in md

    def test_mismatched_tags_do_not_crash(self):
        md = storage_to_markdown("<ul><li>a</p></li><li>b</ul></li>")
        assert "a" in md and "b" in md

    def test_unclosed_macro_placeholder_survives(self):
        md = storage_to_markdown('<ac:structured-macro ac:name="toc"><p>never closed')
        assert "unsupported confluence macro" in md

    def test_injection_via_macro_name_is_quoted_not_executed(self):
        # the name lands in a markdown line — it must not gain markdown power
        md = storage_to_markdown("<ac:structured-macro ac:name='x\" onclick=\"y'>")
        assert md.count("[kgent:") == 1

    def test_null_bytes_and_control_chars(self):
        md = storage_to_markdown("<p>a\x00b\x0cc</p>")
        assert "a" in md and "c" in md

    def test_empty_and_whitespace_only(self):
        assert storage_to_markdown("") == ""
        assert storage_to_markdown("   \n  ") == ""


class TestWriteDirectionHostile:
    def test_script_tag_markdown_rejected(self):
        with pytest.raises(KgentError, match="[Hh][Tt][Mm][Ll]"):
            markdown_to_storage("hello <script>alert(1)</script>")

    def test_image_smuggled_in_list_rejected(self):
        with pytest.raises(KgentError, match="image"):
            markdown_to_storage("- item\n- ![x](y.png)")

    def test_html_comment_rejected(self):
        with pytest.raises(KgentError, match="[Hh][Tt][Mm][Ll]"):
            markdown_to_storage("before <!-- comment --> after")

    def test_autolink_angle_brackets_rejected(self):
        with pytest.raises(KgentError, match="[Hh][Tt][Mm][Ll]"):
            markdown_to_storage("see <https://example.com>")

    def test_escaped_html_entities_pass_through_escaped(self):
        # literal text mentioning tags via entities is inert on both sides
        xhtml = markdown_to_storage("use &lt;b&gt; carefully")
        assert "&amp;lt;" in xhtml

    def test_crlf_normalised(self):
        xhtml = markdown_to_storage("# T\r\n\r\nbody\r\n")
        assert "<h1>T</h1>" in xhtml and "<p>body</p>" in xhtml


class TestRealConfluenceBody:
    """Live-captured regression (2026-09-25, KKB space): an unterminated quoted
    attribute value (truncated/malformed markup) makes html.parser give up on
    the start tag and emit it as DATA — raw markup must never leak into read
    output regardless of how malformed the source is."""

    # verbatim open tag of the KKB "DACI: Decision documentation" page as it
    # flowed through the live pipeline: data-parameters opens with a single
    # quote that is never terminated, so the stdlib parser treats the whole
    # tag as text.
    LEAKING_DIV = (
        '<div data-local-id="92593a07-15f6-31be-87cb-46ffb5976234" data-type="bodied-extension" '
        'data-extension-key="details" data-extension-type="com.atlassian.confluence.macro.core" '
        'data-parameters=\'{"macroParams":{"_parentId":{"value":"327863"}},'
        '"macroMetadata":{"schemaVersion":{"value":"1"},"title":"Page Properties"}}">'
        "<table><thead><tr><th><p><strong>Status</strong></p></th>"
        "<td><p>Not started</p></td></tr></thead></table></div>"
    )

    def test_unterminated_attr_start_tag_never_leaks_as_text(self):
        md = storage_to_markdown(self.LEAKING_DIV)
        assert "<div" not in md
        assert "data-parameters" not in md
        assert "macro.core" not in md
        assert "| **Status** | Not started |" in md  # inner table still converts

    def test_mid_text_angle_bracket_text_survives(self):
        # non-tag-like stray `<` in prose must NOT be eaten by the leak guard
        md = storage_to_markdown("<p>a &lt; b and x &lt;y</p>")
        assert "a < b and x <y" in md
