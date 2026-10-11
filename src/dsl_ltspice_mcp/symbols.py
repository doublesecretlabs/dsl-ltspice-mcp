"""LTspice symbol (.asy) parsing and lookup.

Ported from asy-to-json.js in schematic-export. Symbols are looked up in:
  1. the bundled, hand-tuned symbols.json (the -mrcust variants first, if asked for)
  2. the schematic's own folder (LTspice also looks there)
  3. the user's LTspice library (unpacked lib/sym folder, then lib.zip)
"""

from __future__ import annotations

import json
import os
import zipfile
from functools import lru_cache
from importlib import resources
from pathlib import Path

from .ltspice import library_zip, read_text, symbol_dirs


def _int(s: str) -> int:
    return int(s)


def parse_asy(text: str) -> dict:
    """Convert .asy text to the shape/pin structure used by symbols.json."""
    symbol: dict = {"shapes": [], "pins": []}
    last_pin = None
    for line in (l.strip() for l in text.splitlines()):
        if not line:
            continue
        parts = line.split()
        kw = parts[0]
        try:
            if kw == "LINE" and len(parts) >= 6:
                symbol["shapes"].append({"type": "line", "x1": _int(parts[2]), "y1": _int(parts[3]),
                                         "x2": _int(parts[4]), "y2": _int(parts[5])})
            elif kw == "RECTANGLE" and len(parts) >= 6:
                symbol["shapes"].append({"type": "rect", "x1": _int(parts[2]), "y1": _int(parts[3]),
                                         "x2": _int(parts[4]), "y2": _int(parts[5])})
            elif kw == "CIRCLE" and len(parts) >= 6:
                x1, y1, x2, y2 = map(_int, parts[2:6])
                symbol["shapes"].append({"type": "circle", "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2,
                                         "r": abs(x2 - x1) / 2})
            elif kw == "ARC" and len(parts) >= 10:
                x1, y1, x2, y2, xs, ys, xe, ye = map(_int, parts[2:10])
                symbol["shapes"].append({"type": "arcPoints", "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                                         "xStart": xs, "yStart": ys, "xEnd": xe, "yEnd": ye})
            elif kw == "TEXT" and len(parts) >= 6:
                symbol["shapes"].append({"type": "text", "x": _int(parts[1]), "y": _int(parts[2]),
                                         "align": parts[3], "size": _int(parts[4]),
                                         "text": line.split(None, 5)[5]})
            elif kw == "PIN" and len(parts) >= 3:
                last_pin = {"x": _int(parts[1]), "y": _int(parts[2])}
                symbol["pins"].append(last_pin)
            elif kw == "PINATTR" and len(parts) >= 3 and last_pin is not None:
                if parts[1] == "PinName":
                    last_pin["name"] = parts[2]
                elif parts[1] == "SpiceOrder":
                    last_pin["spiceOrder"] = _int(parts[2])
            elif kw == "WINDOW" and len(parts) >= 5:
                key = {"0": "name", "3": "value"}.get(parts[1])
                if key:
                    symbol[f"{key}Offset"] = {"x": _int(parts[2]), "y": _int(parts[3])}
                    symbol[f"{key}Align"] = parts[4]
            elif kw == "SYMATTR" and len(parts) >= 3:
                symbol.setdefault("attributes", {})[parts[1]] = line.split(None, 2)[2]
        except ValueError:
            continue  # malformed line; skip it like LTspice would
    return symbol


@lru_cache(maxsize=1)
def bundled() -> tuple[dict, dict]:
    data = json.loads(resources.files("dsl_ltspice_mcp").joinpath("data/symbols.json").read_text("utf-8"))
    return data["symbols"], data.get("aliases", {})


class SymbolLibrary:
    def __init__(self, extra_dirs: list[Path] | None = None):
        self.extra_dirs = [Path(d) for d in (extra_dirs or [])]
        self._cache: dict[str, dict | None] = {}
        self.sources: dict[str, str] = {}  # symbol ref -> where it was found

    # Index of every .asy in the LTspice library, by lowercase relative path and basename.
    @staticmethod
    @lru_cache(maxsize=1)
    def _library_index() -> tuple[dict[str, str], dict[str, str], str | None]:
        by_rel: dict[str, str] = {}
        by_base: dict[str, str] = {}
        for d in reversed(symbol_dirs()):  # earlier dirs win
            for root, _, files in os.walk(d):
                for f in files:
                    if f.lower().endswith(".asy"):
                        full = os.path.join(root, f)
                        rel = os.path.relpath(full, d)[:-4].replace("\\", "/").lower()
                        by_rel[rel] = full
                        by_base[f[:-4].lower()] = full
        zpath = None
        if not by_rel:
            z = library_zip()
            if z:
                zpath = str(z)
                with zipfile.ZipFile(z) as zf:
                    for n in zf.namelist():
                        if n.lower().startswith("lib/sym/") and n.lower().endswith(".asy"):
                            rel = n[len("lib/sym/"):-4].lower()
                            by_rel[rel] = "zip:" + n
                            by_base[rel.rsplit("/", 1)[-1]] = "zip:" + n
        return by_rel, by_base, zpath

    def _load_file(self, ref: str) -> dict:
        if ref.startswith("zip:"):
            _, _, zpath = self._library_index()
            with zipfile.ZipFile(zpath) as zf:
                raw = zf.read(ref[4:])
            tmp_text = _decode(raw)
            return parse_asy(tmp_text)
        return parse_asy(read_text(ref)[0])

    def lookup(self, ref: str, custom: bool = False) -> dict | None:
        """Find a symbol by the name used in a SYMBOL line, e.g. 'Opamps\\LT1001'."""
        key = f"{ref}|{custom}"
        if key in self._cache:
            return self._cache[key]
        ref_norm = ref.replace("\\", "/")
        name = ref_norm.rsplit("/", 1)[-1]
        symbols, aliases = bundled()

        result, source = None, None
        if custom and symbols.get(name.lower() + "-mrcust"):
            result, source = symbols[name.lower() + "-mrcust"], "bundled (custom)"
        if result is None:
            result = symbols.get(name) or symbols.get(name.lower())
            if result is None and name in aliases:
                result = symbols.get(aliases[name])
            if result is not None:
                source = "bundled"
        if result is None:
            for d in self.extra_dirs:
                for cand in (d / (ref_norm + ".asy"), d / (name + ".asy")):
                    if cand.is_file():
                        result, source = parse_asy(read_text(cand)[0]), str(cand)
                        break
                if result is not None:
                    break
        if result is None:
            by_rel, by_base, _ = self._library_index()
            hit = by_rel.get(ref_norm.lower()) or by_base.get(name.lower())
            if hit:
                result, source = self._load_file(hit), hit
        self._cache[key] = result
        if source:
            self.sources[ref] = source
        return result


def _decode(raw: bytes) -> str:
    if raw[:2] == b"\xff\xfe":
        return raw[2:].decode("utf-16-le")
    if len(raw) > 1 and raw[1] == 0:
        return raw.decode("utf-16-le")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")
