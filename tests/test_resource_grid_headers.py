"""Resource headers must live outside their vertically scrolling grid body."""

from html.parser import HTMLParser
from pathlib import Path


def test_resource_headers_have_a_separate_fixed_row():
    class ElementAncestors(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.parents = {}

        def handle_starttag(self, tag, attrs):
            if tag != "div":
                return
            identity = dict(attrs).get("id")
            if identity:
                assert identity not in self.parents
                self.parents[identity] = tuple(self.stack)
            self.stack.append(identity)

        def handle_endtag(self, tag):
            if tag == "div":
                self.stack.pop()

    parser = ElementAncestors()
    source = Path("app/presentation/assets/components/gantt/index.html").read_text(encoding="utf-8")
    parser.feed(source.split("<script>", 1)[0])
    for header in ("resource-left-header", "resource-right-header"):
        assert "resource-grid-header" in parser.parents[header]
        assert "resource-grid-main" not in parser.parents[header]
    for body in ("resource-left-body", "resource-right-body"):
        assert "resource-grid-main" in parser.parents[body]
        assert "resource-grid-header" not in parser.parents[body]
