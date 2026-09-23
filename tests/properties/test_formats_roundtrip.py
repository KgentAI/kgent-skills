"""Property: format-bridge round-trip on the minimal subset (spec A4, ADR 0016).

Generated markdown documents built only from bridge-subset structures must
survive markdown → storage XHTML → markdown unchanged. The generator emits
the CANONICAL form directly (stripped blocks; leading list/heading markers
excluded from free text — those constructs ARE lists/headings in markdown).
"""

import re
import string

from hypothesis import given
from hypothesis import strategies as st

from kgent.formats import markdown_to_storage, storage_to_markdown

_text = st.text(
    alphabet=string.ascii_letters + string.digits + " ,.;:!?()äöü中文",
    min_size=1,
    max_size=40,
).filter(
    lambda s: (
        s.strip()
        and "`" not in s
        and "|" not in s
        and "\n" not in s
        and not re.match(r"^\d+[.)]\s", s.strip())
    )
)


@st.composite
def _docs(draw):
    blocks = []
    if draw(st.booleans()):
        blocks.append("# " + draw(_text).strip())
    blocks.append(draw(_text).strip())
    if draw(st.booleans()):
        items = draw(st.lists(_text, min_size=1, max_size=4))
        blocks.append("\n".join("- " + i.strip() for i in items))
    if draw(st.booleans()):
        items = draw(st.lists(_text, min_size=1, max_size=4))
        blocks.append("\n".join(f"{n}. {i.strip()}" for n, i in enumerate(items, 1)))
    if draw(st.booleans()):
        blocks.append("> " + draw(_text).strip())
    if draw(st.booleans()):
        code = draw(
            st.text(
                alphabet=string.ascii_letters + string.digits + " <>=_", min_size=0, max_size=30
            )
        )
        blocks.append("```\n" + code.strip("\n") + "\n```")
    return "\n\n".join(blocks)


class TestFormatBridgeRoundTrip:
    @given(source=_docs())
    def test_subset_documents_roundtrip(self, source: str):
        back = storage_to_markdown(markdown_to_storage(source))
        assert back == source
