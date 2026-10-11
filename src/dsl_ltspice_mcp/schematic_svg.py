"""LTspice .asc schematic to SVG.

Ported from app.js in schematic-export (parseASC / renderSchematic and helpers).
Changes from the JS version:
  - symbols missing from symbols.json are loaded from the user's LTspice library
  - the drawing bounds use the real symbol shapes when they're known
  - TEXT lines inside symbols (e.g. op-amp +/- labels) are drawn
  - multi-line TEXT annotations (LTspice stores "\\n") become separate lines
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .ltspice import read_text
from .symbols import SymbolLibrary


def _pint(s: str | None, default=None):
    """JavaScript parseInt(): leading integer, else default."""
    if s is None:
        return default
    m = re.match(r"\s*([-+]?\d+)", s)
    return int(m.group(1)) if m else default


def _n(v) -> str:
    """Format a number for SVG output (integers without a trailing .0)."""
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        s = f"{v:.3f}".rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s
    return str(v)


def escape_xml(s: str | None) -> str:
    if not s:
        return ""
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&apos;"))


# ============================================================
# PARSER
# ============================================================

def parse_asc(content: str) -> dict:
    schematic = {"wires": [], "symbols": [], "flags": [], "texts": [], "iopin": [],
                 "width": 0, "height": 0}
    current = None
    for line in content.split("\n"):
        line = line.strip()
        parts = line.split()
        if line.startswith("SHEET"):
            if len(parts) >= 4:
                schematic["width"] = _pint(parts[2]) or 880
                schematic["height"] = _pint(parts[3]) or 680
        elif line.startswith("WIRE"):
            if len(parts) >= 5:
                x1, y1, x2, y2 = (_pint(p, 0) for p in parts[1:5])
                schematic["wires"].append({"x1": x1, "y1": y1, "x2": x2, "y2": y2})
        elif line.startswith("FLAG"):
            if len(parts) >= 4:
                schematic["flags"].append({"x": _pint(parts[1], 0), "y": _pint(parts[2], 0),
                                           "name": " ".join(parts[3:])})
        elif line.startswith("IOPIN"):
            if len(parts) >= 4:
                schematic["iopin"].append({"x": _pint(parts[1], 0), "y": _pint(parts[2], 0), "dir": parts[3]})
        elif line.startswith("SYMBOL"):
            if current:
                schematic["symbols"].append(current)
            if len(parts) >= 5:
                ref = parts[1]
                current = {"ref": ref, "name": re.split(r"[\\/]", ref)[-1],
                           "x": _pint(parts[2], 0), "y": _pint(parts[3], 0),
                           "rotation": parts[4] or "R0", "attributes": {}, "windows": {}}
            else:
                current = None
        elif line.startswith("WINDOW"):
            # WINDOW <attr_num> <x> <y> <alignment> <size>; 0=InstName, 3=Value
            if current and len(parts) >= 5:
                current["windows"][_pint(parts[1])] = {
                    "x": _pint(parts[2], 0), "y": _pint(parts[3], 0), "align": parts[4],
                    "size": _pint(parts[5], 2) if len(parts) > 5 else 2}
        elif line.startswith("SYMATTR"):
            if current and len(parts) >= 3:
                current["attributes"][parts[1]] = " ".join(parts[2:])
        elif line.startswith("TEXT"):
            m = re.match(r"TEXT\s+(-?\d+)\s+(-?\d+)\s+(\w+)\s+(\d+)\s*(.*)", line)
            if m:
                schematic["texts"].append({"x": int(m.group(1)), "y": int(m.group(2)),
                                           "align": m.group(3), "size": int(m.group(4)),
                                           "text": re.sub(r"^[;!]?\s*", "", m.group(5), count=1)})
    if current:
        schematic["symbols"].append(current)
    return schematic


# ============================================================
# JUNCTION DETECTION
# ============================================================

def point_on_segment(px, py, x1, y1, x2, y2) -> bool:
    if px < min(x1, x2) or px > max(x1, x2) or py < min(y1, y2) or py > max(y1, y2):
        return False
    cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
    return abs(cross) < 1


def find_junctions(wires: list[dict]) -> list[tuple[int, int]]:
    """Points where 3+ wire segments meet, including T-junctions."""
    count: dict[tuple[int, int], int] = {}
    for w in wires:
        for p in ((w["x1"], w["y1"]), (w["x2"], w["y2"])):
            count[p] = count.get(p, 0) + 1
    for w in wires:
        for o in wires:
            if o is w:
                continue
            for p in ((o["x1"], o["y1"]), (o["x2"], o["y2"])):
                if point_on_segment(*p, w["x1"], w["y1"], w["x2"], w["y2"]):
                    if p != (w["x1"], w["y1"]) and p != (w["x2"], w["y2"]):
                        count[p] = count.get(p, 0) + 2
    return [p for p, c in count.items() if c >= 3]


# ============================================================
# COORDINATE TRANSFORMS
# ============================================================

def transform_point(x, y, rotation: str) -> tuple:
    """LTspice R0/R90/R180/R270 and mirrored M0/M90/M180/M270."""
    mirror = rotation.startswith("M")
    angle = _pint(rotation[1:], 0) or 0
    tx, ty = x, y
    if angle == 90:
        tx, ty = -y, x
    elif angle == 180:
        tx, ty = -x, -y
    elif angle == 270:
        tx, ty = y, -x
    if mirror:
        tx = -tx
    return tx, ty


def transform_shape(shape: dict, rotation: str) -> dict:
    s = dict(shape)
    t = shape["type"]
    if t == "line":
        s["x1"], s["y1"] = transform_point(shape["x1"], shape["y1"], rotation)
        s["x2"], s["y2"] = transform_point(shape["x2"], shape["y2"], rotation)
    elif t == "rect":
        p1 = transform_point(shape["x1"], shape["y1"], rotation)
        p2 = transform_point(shape["x2"], shape["y2"], rotation)
        s["x1"], s["y1"] = min(p1[0], p2[0]), min(p1[1], p2[1])
        s["x2"], s["y2"] = max(p1[0], p2[0]), max(p1[1], p2[1])
    elif t == "circle":
        s["cx"], s["cy"] = transform_point(shape["cx"], shape["cy"], rotation)
    elif t == "arc":
        s["cx"], s["cy"] = transform_point(shape["cx"], shape["cy"], rotation)
        angle = _pint(rotation[1:], 0) or 0
        s["start"] = shape["start"] - angle
        s["end"] = shape["end"] - angle
        if rotation.startswith("M"):
            s["start"], s["end"] = 180 - s["end"], 180 - s["start"]
    elif t == "polygon":
        s["points"] = [dict(zip("xy", transform_point(p["x"], p["y"], rotation))) for p in shape["points"]]
    elif t == "arcPoints":
        b1 = transform_point(shape["x1"], shape["y1"], rotation)
        b2 = transform_point(shape["x2"], shape["y2"], rotation)
        s["x1"], s["y1"] = min(b1[0], b2[0]), min(b1[1], b2[1])
        s["x2"], s["y2"] = max(b1[0], b2[0]), max(b1[1], b2[1])
        s["xStart"], s["yStart"] = transform_point(shape["xStart"], shape["yStart"], rotation)
        s["xEnd"], s["yEnd"] = transform_point(shape["xEnd"], shape["yEnd"], rotation)
        # Mirror reverses arc winding direction: flip sweep flag
        if rotation.startswith("M"):
            s["sweep"] = 1
    elif t == "text":
        s["x"], s["y"] = transform_point(shape["x"], shape["y"], rotation)
    return s


def shape_points(shape: dict):
    """Rough extent of a (transformed) shape, for computing drawing bounds."""
    t = shape["type"]
    if t in ("line", "rect", "arcPoints"):
        return [(shape["x1"], shape["y1"]), (shape["x2"], shape["y2"])]
    if t in ("circle", "arc"):
        r = shape.get("r") or shape.get("rx") or 10
        return [(shape["cx"] - r, shape["cy"] - r), (shape["cx"] + r, shape["cy"] + r)]
    if t == "polygon":
        return [(p["x"], p["y"]) for p in shape["points"]]
    if t == "text":
        return [(shape["x"], shape["y"])]
    return []


# ============================================================
# RENDERER
# ============================================================

DEFAULT_OPTIONS = {
    "strokeColor": "#000000",
    "wireWidth": 2,
    "symbolWidth": 1.5,
    "background": "none",
    "scale": 1,
    "showValues": True,
    "showNetNames": True,
    "showRefDes": True,
    "showJunctions": True,
    "junctionDotSize": 5,
    "junctionDotShape": "circle",
    "customSymbols": False,
    "debugMode": False,
    "includeMetadata": False,
    "fontFamily": "Arial, sans-serif",
    "fontSize": 18,
    "fontWeight": "400",
}


@dataclass
class RenderResult:
    svg: str
    width: float
    height: float
    unknown_symbols: list[str] = field(default_factory=list)
    symbol_sources: dict[str, str] = field(default_factory=dict)


def render_schematic(schematic: dict, options: dict | None = None,
                     library: SymbolLibrary | None = None) -> RenderResult:
    o = {**DEFAULT_OPTIONS, **(options or {})}
    library = library or SymbolLibrary()
    stroke, font_size, font_family, font_weight = o["strokeColor"], o["fontSize"], o["fontFamily"], o["fontWeight"]

    # Resolve symbols first so their real shapes can feed the bounds.
    resolved = []
    for sym in schematic["symbols"]:
        sym_def = library.lookup(sym.get("ref", sym["name"]), custom=o["customSymbols"])
        resolved.append((sym, sym_def))

    xs: list[float] = []
    ys: list[float] = []

    def extend(*pts):
        for x, y in pts:
            xs.append(x)
            ys.append(y)

    for w in schematic["wires"]:
        extend((w["x1"], w["y1"]), (w["x2"], w["y2"]))
    for sym, sym_def in resolved:
        if sym_def and sym_def.get("shapes"):
            for shape in sym_def["shapes"]:
                for px, py in shape_points(transform_shape(shape, sym["rotation"])):
                    extend((sym["x"] + px, sym["y"] + py))
        else:
            extend((sym["x"] - 50, sym["y"] - 50), (sym["x"] + 50, sym["y"] + 100))
    for f in schematic["flags"]:
        extend((f["x"] - 20, f["y"]), (f["x"] + 60, f["y"] + 40))
    for t in schematic["texts"]:
        lines = t["text"].split("\\n")
        longest = max(len(l) for l in lines)
        w = longest * font_size * 0.55
        extend((t["x"] - (w if t["align"] == "Right" else w / 2 if t["align"] == "Center" else 0), t["y"] - font_size),
               (t["x"] + w, t["y"] + font_size * 1.25 * len(lines)))

    if not xs:
        xs, ys = [0, 100], [0, 100]
    padding = 40
    min_x, min_y = min(xs) - padding, min(ys) - padding
    max_x, max_y = max(xs) + padding, max(ys) + padding
    width = (max_x - min_x) * o["scale"]
    height = (max_y - min_y) * o["scale"]

    out = [f'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" '
           f'width="{_n(width)}" height="{_n(height)}" viewBox="{_n(min_x)} {_n(min_y)} '
           f'{_n(max_x - min_x)} {_n(max_y - min_y)}">\n']
    if o["background"] != "none":
        out.append(f'  <rect x="{_n(min_x)}" y="{_n(min_y)}" width="{_n(max_x - min_x)}" '
                   f'height="{_n(max_y - min_y)}" fill="{o["background"]}"/>\n')

    font = f"font-family: {font_family}; font-weight: {font_weight}; fill: {stroke};"
    out.append(
        "  <defs>\n    <style>\n"
        f"      .wire {{ stroke: {stroke}; stroke-width: {_n(o['wireWidth'])}; stroke-linecap: round; fill: none; }}\n"
        f"      .symbol {{ stroke: {stroke}; stroke-width: {_n(o['symbolWidth'])}; fill: none; }}\n"
        f"      .symbol-filled {{ stroke: {stroke}; stroke-width: {_n(o['symbolWidth'])}; fill: {stroke}; }}\n"
        f"      .text {{ {font} font-size: {_n(font_size + 2)}px; }}\n"
        f"      .value {{ {font} font-size: {_n(font_size)}px; }}\n"
        f"      .refdes {{ {font} font-size: {_n(font_size)}px; }}\n"
        f"      .netname {{ {font} font-size: {_n(font_size - 2)}px; }}\n"
        f"      .symtext {{ {font} font-size: {_n(font_size * 0.8)}px; }}\n"
        f"      .junction {{ fill: {stroke}; }}\n"
        "    </style>\n  </defs>\n")

    out.append('  <g class="wires">\n')
    for w in schematic["wires"]:
        out.append(f'    <line class="wire" x1="{w["x1"]}" y1="{w["y1"]}" x2="{w["x2"]}" y2="{w["y2"]}"/>\n')
    out.append("  </g>\n")

    if o["debugMode"]:
        out.append('  <g class="debug-wire-endpoints">\n')
        pts = dict.fromkeys(p for w in schematic["wires"] for p in ((w["x1"], w["y1"]), (w["x2"], w["y2"])))
        for x, y in pts:
            out.append(f'    <circle cx="{x}" cy="{y}" r="3" fill="lime" stroke="green" stroke-width="1" opacity="0.8"/>\n')
        out.append("  </g>\n")

    if o["showJunctions"]:
        junctions = find_junctions(schematic["wires"])
        if junctions:
            out.append('  <g class="junctions">\n')
            r = o["junctionDotSize"] or 5
            for x, y in junctions:
                if o["junctionDotShape"] == "square":
                    out.append(f'    <rect class="junction" x="{_n(x - r)}" y="{_n(y - r)}" width="{_n(r * 2)}" height="{_n(r * 2)}"/>\n')
                else:
                    out.append(f'    <circle class="junction" cx="{x}" cy="{y}" r="{_n(r)}"/>\n')
            out.append("  </g>\n")

    out.append('  <g class="symbols">\n')
    unknown: list[str] = []
    for sym, sym_def in resolved:
        if sym_def:
            out.append(render_symbol(sym, sym_def, o))
        else:
            if sym["name"] not in unknown:
                unknown.append(sym["name"])
            out.append(render_placeholder(sym, o))
    out.append("  </g>\n")

    out.append('  <g class="flags">\n')
    for f in schematic["flags"]:
        if f["name"] == "0":
            out.append(render_ground_symbol(f["x"], f["y"]))
        elif o["showNetNames"]:
            out.append(f'    <text class="netname" x="{f["x"] + 4}" y="{f["y"] - 4}">{escape_xml(f["name"])}</text>\n')
    out.append("  </g>\n")

    out.append('  <g class="annotations">\n')
    for t in schematic["texts"]:
        anchor = {"Center": "middle", "Right": "end"}.get(t["align"], "start")
        lines = t["text"].split("\\n")
        if len(lines) == 1:
            out.append(f'    <text class="text" x="{t["x"]}" y="{t["y"]}" text-anchor="{anchor}">{escape_xml(t["text"])}</text>\n')
        else:
            spans = "".join(f'<tspan x="{t["x"]}" dy="{0 if i == 0 else "1.25em"}">{escape_xml(l)}</tspan>'
                            for i, l in enumerate(lines))
            out.append(f'    <text class="text" x="{t["x"]}" y="{t["y"]}" text-anchor="{anchor}">{spans}</text>\n')
    out.append("  </g>\n")
    out.append("</svg>")

    return RenderResult("".join(out), width, height, unknown, dict(library.sources))


def _metadata(sym: dict, o: dict) -> str:
    if not o.get("includeMetadata"):
        return ""
    attrs = f' data-symbol="{escape_xml(sym["name"])}"'
    for k, v in sym["attributes"].items():
        attrs += f' data-{re.sub(r"[^a-z0-9]", "-", k.lower())}="{escape_xml(v)}"'
    return attrs


def _text_anchor(align: str | None, original_x=None, transformed_x=None) -> str:
    # LTspice alignments: Left, Right, Center, Top, Bottom, VLeft, VRight, VCenter, VTop, VBottom
    base = re.sub(r"^V", "", align) if align else "Left"
    anchor = "end" if base == "Right" else "middle" if base in ("Center", "Top", "Bottom") else "start"
    if original_x is not None and transformed_x is not None:
        flipped = (original_x > 0 and transformed_x < 0) or (original_x < 0 and transformed_x > 0)
        if flipped:
            anchor = {"start": "end", "end": "start"}.get(anchor, anchor)
    return anchor


def _baseline(align: str | None) -> str:
    base = re.sub(r"^V", "", align) if align else "Left"
    return "hanging" if base == "Top" else "auto"


def render_symbol(sym: dict, sym_def: dict, o: dict) -> str:
    out = [f'    <g transform="translate({sym["x"]}, {sym["y"]})"{_metadata(sym, o)}>\n']
    rot = sym["rotation"]

    if o["debugMode"]:
        out.append('      <line class="debug-origin" x1="-6" y1="0" x2="6" y2="0" stroke="red" stroke-width="1"/>\n')
        out.append('      <line class="debug-origin" x1="0" y1="-6" x2="0" y2="6" stroke="red" stroke-width="1"/>\n')
        for pin in sym_def.get("pins", []):
            x, y = transform_point(pin["x"], pin["y"], rot)
            out.append(f'      <circle class="debug-pin" cx="{_n(x)}" cy="{_n(y)}" r="4" fill="blue" opacity="0.7"/>\n')

    for shape in sym_def.get("shapes", []):
        out.append(render_shape(transform_shape(shape, rot)))

    for attr, win, cls, default_offset, show in (
        ("Value", 3, "value", {"x": 30, "y": 44}, o["showValues"]),
        ("InstName", 0, "refdes", {"x": -30, "y": 44}, o["showRefDes"]),
    ):
        text = sym["attributes"].get(attr)
        if not show or not text:
            continue
        key = "value" if win == 3 else "name"
        window = sym["windows"].get(win)
        if window:
            if window["align"] == "Invisible":
                continue
            x, y = transform_point(window["x"], window["y"], rot)
            anchor = _text_anchor(window["align"], window["x"], x)
            baseline = _baseline(window["align"])
        else:
            offset = sym_def.get(f"{key}Offset") or default_offset
            align = sym_def.get(f"{key}Align", "Left")
            if align == "Invisible":
                continue
            x, y = transform_point(offset["x"], offset["y"], rot)
            anchor = _text_anchor(align, offset["x"], x)
            baseline = _baseline(align) if f"{key}Align" in sym_def else "auto"
        bl = f' dominant-baseline="{baseline}"' if baseline != "auto" else ""
        out.append(f'      <text class="{cls}" x="{_n(x)}" y="{_n(y)}" text-anchor="{anchor}"{bl}>{escape_xml(text)}</text>\n')

    out.append("    </g>\n")
    return "".join(out)


def render_shape(shape: dict) -> str:
    t = shape["type"]
    if t == "line":
        return f'      <line class="symbol" x1="{_n(shape["x1"])}" y1="{_n(shape["y1"])}" x2="{_n(shape["x2"])}" y2="{_n(shape["y2"])}"/>\n'
    if t == "rect":
        return (f'      <rect class="symbol" x="{_n(shape["x1"])}" y="{_n(shape["y1"])}" '
                f'width="{_n(shape["x2"] - shape["x1"])}" height="{_n(shape["y2"] - shape["y1"])}"/>\n')
    if t == "circle":
        return f'      <circle class="symbol" cx="{_n(shape["cx"])}" cy="{_n(shape["cy"])}" r="{_n(shape["r"])}"/>\n'
    if t == "arc":
        rx = shape.get("rx") or shape.get("r") or 10
        ry = shape.get("ry") or shape.get("r") or 10
        sr, er = math.radians(shape["start"]), math.radians(shape["end"])
        x1, y1 = shape["cx"] + rx * math.cos(sr), shape["cy"] + ry * math.sin(sr)
        x2, y2 = shape["cx"] + rx * math.cos(er), shape["cy"] + ry * math.sin(er)
        diff = shape["end"] - shape["start"]
        if diff > 180:
            diff -= 360
        if diff < -180:
            diff += 360
        large = 1 if abs(diff) > 180 else 0
        sweep = 1 if diff > 0 else 0
        return f'      <path class="symbol" d="M {_n(x1)} {_n(y1)} A {_n(rx)} {_n(ry)} 0 {large} {sweep} {_n(x2)} {_n(y2)}"/>\n'
    if t == "arcPoints":
        # ARC from .asy: bounding box (x1,y1)-(x2,y2), drawn from (xStart,yStart) to (xEnd,yEnd)
        rx = (shape["x2"] - shape["x1"]) / 2
        ry = (shape["y2"] - shape["y1"]) / 2
        cx = (shape["x1"] + shape["x2"]) / 2
        cy = (shape["y1"] + shape["y2"]) / 2
        a0 = math.atan2(shape["yStart"] - cy, shape["xStart"] - cx)
        a1 = math.atan2(shape["yEnd"] - cy, shape["xEnd"] - cx)
        diff = a0 - a1
        if diff < 0:
            diff += 2 * math.pi
        large = 1 if diff > math.pi else 0
        sweep = shape.get("sweep") or 0
        return (f'      <path class="symbol" d="M {_n(shape["xStart"])} {_n(shape["yStart"])} A {_n(rx)} {_n(ry)} '
                f'0 {large} {sweep} {_n(shape["xEnd"])} {_n(shape["yEnd"])}"/>\n')
    if t == "polygon":
        pts = " ".join(f'{_n(p["x"])},{_n(p["y"])}' for p in shape["points"])
        cls = "symbol-filled" if shape.get("filled") else "symbol"
        return f'      <polygon class="{cls}" points="{pts}"/>\n'
    if t == "text":
        anchor = _text_anchor(shape.get("align"))
        return (f'      <text class="symtext" x="{_n(shape["x"])}" y="{_n(shape["y"])}" text-anchor="{anchor}" '
                f'dominant-baseline="middle">{escape_xml(shape["text"])}</text>\n')
    return ""


def render_placeholder(sym: dict, o: dict) -> str:
    size = 40
    out = [f'    <g transform="translate({sym["x"]}, {sym["y"]})"{_metadata(sym, o)}>\n',
           f'      <rect class="symbol" x="{_n(-size / 2)}" y="0" width="{size}" height="{_n(size * 1.5)}" stroke-dasharray="4"/>\n',
           f'      <text class="value" x="0" y="{_n(size * 0.75)}" text-anchor="middle" font-size="8">{escape_xml(sym["name"])}</text>\n']
    if o["showValues"] and sym["attributes"].get("Value"):
        out.append(f'      <text class="value" x="{_n(size / 2 + 5)}" y="{_n(size * 0.75)}">{escape_xml(sym["attributes"]["Value"])}</text>\n')
    if o["showRefDes"] and sym["attributes"].get("InstName"):
        out.append(f'      <text class="refdes" x="{_n(-size / 2 - 5)}" y="{_n(size * 0.75)}" text-anchor="end">{escape_xml(sym["attributes"]["InstName"])}</text>\n')
    out.append("    </g>\n")
    return "".join(out)


def render_ground_symbol(x, y) -> str:
    return (f'    <g transform="translate({x}, {y})">\n'
            '      <line class="symbol" x1="0" y1="0" x2="0" y2="18"/>\n'
            '      <line class="symbol" x1="-18" y1="18" x2="18" y2="18"/>\n'
            '      <line class="symbol" x1="-11" y1="25" x2="11" y2="25"/>\n'
            '      <line class="symbol" x1="-5" y1="32" x2="5" y2="32"/>\n'
            '    </g>\n')


# ============================================================
# FILE-LEVEL HELPERS
# ============================================================

def asc_to_svg(asc_path: str | Path, output_path: str | Path | None = None,
               options: dict | None = None) -> RenderResult:
    """Convert an .asc file; writes the SVG if output_path is given."""
    asc_path = Path(asc_path)
    text, _ = read_text(asc_path)
    library = SymbolLibrary(extra_dirs=[asc_path.parent])
    result = render_schematic(parse_asc(text), options, library)
    if output_path:
        Path(output_path).write_text(result.svg, encoding="utf-8")
    return result
