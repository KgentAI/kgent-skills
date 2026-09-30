"""Format bridge tests (spec 2026-09-22, ADR 0016, A4).

markdown ↔ minimal storage XHTML: the shared converter behind `kgent formats`
and the confluence adapter. Subset round-trips close; bridge-external
structures degrade loudly (placeholder on read, refusal on write).
"""

import io
import re

import pytest

from kgent.cli import main as cli_main
from kgent.errors import KgentError
from kgent.formats import markdown_to_storage, storage_to_markdown


class TestReadDirection:
    def test_paragraph(self):
        assert storage_to_markdown("<p>hello world</p>") == "hello world"

    def test_heading_levels(self):
        assert storage_to_markdown("<h1>Title</h1>") == "# Title"
        assert storage_to_markdown("<h3>Sub</h3>") == "### Sub"

    def test_unordered_list(self):
        md = storage_to_markdown("<ul><li>one</li><li>two</li></ul>")
        assert md == "- one\n- two"

    def test_ordered_list(self):
        md = storage_to_markdown("<ol><li>first</li><li>second</li></ol>")
        assert md == "1. first\n2. second"

    def test_code_block(self):
        md = storage_to_markdown("<pre><code>x = 1 &lt; 2</code></pre>")
        assert md.startswith("```\n")
        assert md.endswith("\n```")
        assert "x = 1 < 2" in md

    def test_blockquote(self):
        assert storage_to_markdown("<blockquote><p>quoted</p></blockquote>") == "> quoted"

    def test_table_becomes_gfm(self):
        md = storage_to_markdown(
            "<table><tbody><tr><th>a</th><th>b</th></tr>"
            "<tr><td>1</td><td>2</td></tr></tbody></table>"
        )
        assert "| a | b |" in md
        assert "| 1 | 2 |" in md
        assert re.search(r"\|[-| ]+\|", md)  # separator row

    def test_inline_styling(self):
        assert storage_to_markdown("<p><strong>bold</strong> and <em>it</em></p>") == (
            "**bold** and *it*"
        )

    def test_inline_code_and_link(self):
        md = storage_to_markdown('<p>see <code>x</code> and <a href="https://e/x">docs</a></p>')
        assert "see `x` and [docs](https://e/x)" == md

    def test_entities_unescaped(self):
        assert storage_to_markdown("<p>a &amp; b &lt; c</p>") == "a & b < c"

    def test_macro_becomes_placeholder_not_silence(self):
        md = storage_to_markdown(
            '<p>before</p><ac:structured-macro ac:name="info"><ac:rich-text-body>'
            "<p>inner</p></ac:rich-text-body></ac:structured-macro>"
        )
        assert "before" in md
        assert 'unsupported confluence macro "info"' in md

    def test_media_becomes_placeholder(self):
        md = storage_to_markdown(
            '<p>x</p><ac:image><ri:attachment ri:filename="f.png" /></ac:image>'
        )
        assert "[confluence attachment omitted" in md

    def test_script_content_stripped(self):
        md = storage_to_markdown("<p>safe</p><script>alert(1)</script>")
        assert "alert" not in md
        assert "safe" in md

    def test_style_tag_content_stripped(self):
        md = storage_to_markdown("<style>body{}</style><p>ok</p>")
        assert "body{}" not in md


class TestWriteDirection:
    def test_paragraph_escaped(self):
        xhtml = markdown_to_storage("a < b & c")
        assert xhtml == "<p>a &lt; b &amp; c</p>"

    def test_heading(self):
        assert markdown_to_storage("## Head") == "<h2>Head</h2>"

    def test_list(self):
        xhtml = markdown_to_storage("- one\n- two")
        assert xhtml == "<ul><li>one</li><li>two</li></ul>"

    def test_code_block(self):
        xhtml = markdown_to_storage("```\nx < 1\n```")
        assert xhtml == "<pre><code>x &lt; 1</code></pre>"

    def test_blockquote(self):
        assert markdown_to_storage("> quoted") == "<blockquote><p>quoted</p></blockquote>"

    def test_table(self):
        xhtml = markdown_to_storage("| a | b |\n| --- | --- |\n| 1 | 2 |")
        assert "<table>" in xhtml and "<td>1</td>" in xhtml and "<th>a</th>" in xhtml

    def test_inline_styling_and_link(self):
        xhtml = markdown_to_storage("**b** *i* `c` [t](https://e/x)")
        assert "<strong>b</strong>" in xhtml
        assert "<em>i</em>" in xhtml
        assert "<code>c</code>" in xhtml
        assert '<a href="https://e/x">t</a>' in xhtml

    def test_image_rejected(self):
        with pytest.raises(KgentError, match="image"):
            markdown_to_storage("![alt](pic.png)")

    def test_raw_html_rejected(self):
        with pytest.raises(KgentError, match="[Hh][Tt][Mm][Ll]"):
            markdown_to_storage('<div onclick="x">raw</div>')

    def test_multiline_document(self):
        xhtml = markdown_to_storage("# T\n\nintro\n\n- a\n- b")
        assert "<h1>T</h1>" in xhtml
        assert "<p>intro</p>" in xhtml
        assert "<ul>" in xhtml


class TestRoundTrip:
    def test_minimal_subset_roundtrip(self):
        md_source = "# Title\n\nA paragraph with **bold**, *italic*, `code` and a [link](https://e/x).\n\n- one\n- two\n\n1. first\n2. second\n\n> quoted\n\n```\ncode < line\n```\n\n| a | b |\n| --- | --- |\n| 1 | 2 |"
        back = storage_to_markdown(markdown_to_storage(md_source))
        assert back == md_source.strip()


class TestReadBranches:
    def test_self_closing_hr_block(self):
        assert storage_to_markdown("<p>a</p><hr/><p>b</p>") == "a\n\n---\n\nb"

    def test_inline_br_and_span(self):
        assert storage_to_markdown("<p>a<br/>b <span>sp</span></p>") == "a\nb sp"

    def test_unknown_inline_tag_degrades_to_text(self):
        assert storage_to_markdown("<p><u>underlined</u></p>") == "underlined"

    def test_loose_top_level_text_survives(self):
        assert storage_to_markdown("loose text") == "loose text"

    def test_div_wrapper_passthrough(self):
        assert storage_to_markdown("<div><p>x</p></div>") == "x"

    def test_list_with_stray_text_skips_it(self):
        assert storage_to_markdown("<ul>junk<li>a</li></ul>") == "- a"

    def test_script_inside_li_skipped(self):
        assert storage_to_markdown("<ul><li><script>x</script>a</li></ul>") == "- a"

    def test_nested_list_inside_li(self):
        md = storage_to_markdown("<ul><li>a<ul><li>b</li></ul></li></ul>")
        assert md == "- a\n  - b"

    def test_table_without_header_row_promotes_first_row(self):
        md = storage_to_markdown(
            "<table><tbody><tr><td>1</td></tr><tr><td>2</td></tr></tbody></table>"
        )
        assert md.splitlines()[0] == "| 1 |"
        assert md.splitlines()[2] == "| 2 |"


class TestWriteBranches:
    def test_hr_write(self):
        assert markdown_to_storage("---") == "<hr/>"

    def test_unterminated_fence_rejected(self):
        with pytest.raises(KgentError, match="unterminated"):
            markdown_to_storage("```\ncode without close")

    def test_nested_fence_rejected(self):
        with pytest.raises(KgentError, match="nested code fence"):
            markdown_to_storage("```\ninner ``` tick\n```")

    def test_raw_html_inside_list_rejected(self):
        with pytest.raises(KgentError, match="[Hh][Tt][Mm][Ll]"):
            markdown_to_storage("- <b>bold item</b>")

    def test_table_without_separator_row(self):
        xhtml = markdown_to_storage("| a |\n| 1 |")
        assert "<th>a</th>" in xhtml and "<td>1</td>" in xhtml

    def test_blockquote_with_blank_line_inside(self):
        xhtml = markdown_to_storage("> a\n>\n> b")
        assert xhtml == "<blockquote><p>a</p><p>b</p></blockquote>"

    def test_self_closing_style_tag_skipped(self):
        md = storage_to_markdown("<p>a<style/></p>")
        assert md == "a"

    def test_inline_hr_inside_paragraph(self):
        assert storage_to_markdown("<p>a<hr/>b</p>") == "a\n---\nb"

    def test_unknown_block_tag_degrades_to_inner_blocks(self):
        assert storage_to_markdown("<custom-wrap><p>deep</p></custom-wrap>") == "deep"

    def test_ordered_list_reverting_to_unordered_splits_blocks(self):
        xhtml = markdown_to_storage("1. a\n- b")
        assert "<ol><li>a</li></ol>" in xhtml
        assert "<ul><li>b</li></ul>" in xhtml


class TestCli:
    def test_formats_to_markdown_stdin_stdout(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.stdin", io.StringIO("<p>hi &amp; bye</p>"))
        assert cli_main(["formats", "to-markdown"]) == 0
        assert capsys.readouterr().out.strip() == "hi & bye"

    def test_formats_to_storage_stdin_stdout(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.stdin", io.StringIO("# H"))
        assert cli_main(["formats", "to-storage-xhtml"]) == 0
        assert capsys.readouterr().out.strip() == "<h1>H</h1>"

    def test_formats_write_refusal_is_cli_failure(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("![x](y.png)"))
        assert cli_main(["formats", "to-storage-xhtml"]) == 1

    def test_formats_unknown_action_rejected(self):
        assert cli_main(["formats", "to-rtf"]) == 1

    def test_formats_stdin_decodes_utf8(self, monkeypatch, capsys):
        # Windows pipes default to the legacy codepage (cp1252); the bridge
        # contract is UTF-8 in/out regardless of console locale (live finding
        # 2026-09-25: emoji arrived mojibake'd through a cp1252 stdin).
        import io as _io

        monkeypatch.setattr(
            "sys.stdin",
            _io.TextIOWrapper(_io.BytesIO("<h2>📘 背景</h2>".encode()), encoding="cp1252"),
        )
        assert cli_main(["formats", "to-markdown"]) == 0
        assert capsys.readouterr().out.strip() == "## 📘 背景"
