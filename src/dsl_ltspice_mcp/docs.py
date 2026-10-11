"""Searching the LTspice help pages installed with LTspice (LTspiceHelp/*.htm)."""

from __future__ import annotations

import re
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

from .ltspice import help_dir


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "table", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("td", "th"):
            self.parts.append("\t")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        t = "".join(self.parts).replace("\xa0", " ")
        t = re.sub(r"[ \t]+\n", "\n", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()


@lru_cache(maxsize=1)
def _index() -> dict[str, dict]:
    d = help_dir()
    if d is None:
        return {}
    docs = {}
    for p in sorted(d.iterdir()):
        if p.suffix.lower() not in (".htm", ".html"):
            continue
        parser = _TextExtractor()
        try:
            parser.feed(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        text = parser.text()
        title = parser.title.strip() or (text.splitlines()[0] if text else p.stem)
        docs[p.stem.lower()] = {"name": p.stem, "title": title, "text": text}
    return docs


def list_docs(filter: str | None = None) -> list[dict]:
    f = (filter or "").lower()
    return [{"name": d["name"], "title": d["title"]} for d in _index().values()
            if not f or f in d["title"].lower() or f in d["name"].lower()]


def search(query: str, limit: int = 8) -> list[dict]:
    terms = [t for t in re.findall(r"[\w.]+", query.lower()) if len(t) > 1]
    if not terms:
        return []
    results = []
    for d in _index().values():
        body = d["text"].lower()
        title = d["title"].lower()
        score = sum(body.count(t) + 20 * title.count(t) for t in terms)
        if all(t in body or t in title for t in terms):
            score *= 2
        if score:
            pos = min((body.find(t) for t in terms if t in body), default=0)
            snippet = d["text"][max(0, pos - 120): pos + 240].replace("\n", " ")
            results.append({"name": d["name"], "title": d["title"], "score": score, "snippet": snippet})
    results.sort(key=lambda r: -r["score"])
    return results[:limit]


def get_doc(name: str) -> dict:
    idx = _index()
    if not idx:
        raise FileNotFoundError("The LTspice help files (LTspiceHelp folder) weren't found next to LTspice.exe.")
    key = Path(name).stem.lower()
    doc = idx.get(key) or next((d for d in idx.values() if d["title"].lower() == name.lower()), None)
    if doc is None:
        raise KeyError(f"No help page named {name!r}. Use search_reference_docs or list_reference_docs.")
    return doc
