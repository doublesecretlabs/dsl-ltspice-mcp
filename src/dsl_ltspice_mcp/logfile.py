"""Parsing LTspice .log files: .meas results, .step values, .four THD, errors."""

from __future__ import annotations

import re
from pathlib import Path

from .ltspice import read_text

_MEAS = re.compile(
    r"^(?P<name>[A-Za-z_]\w*):\s+(?P<expr>.+?)=(?P<value>\S+)"
    r"(?:\s+(?P<at_kw>at|AT)\s+(?P<at>\S+))?"
    r"(?:\s+FROM\s+(?P<from>\S+)\s+TO\s+(?P<to>\S+))?\s*$"
)
_STEP = re.compile(r"^\s*\.step\s+(.*)$", re.IGNORECASE)
_FOURIER = re.compile(r"^Fourier components of (.+)$", re.IGNORECASE)
_THD = re.compile(r"^Total Harmonic Distortion:\s*([-+\d.eE]+)%")
_PROBLEM = re.compile(
    r"error|warning|cannot|can't|could not|unable|unknown|undefined|not defined|invalid|"
    r"syntax|fatal|abort|missing|singular matrix|time ?step too small|failed|not found",
    re.IGNORECASE,
)


def to_float(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def log_path_for(path: str | Path) -> Path:
    """Map a design, raw or log path to the matching .log file."""
    p = Path(path)
    name = p.name
    for suffix in (".op.raw", ".raw", ".log"):
        if name.lower().endswith(suffix):
            return p.with_name(name[: -len(suffix)] + ".log")
    return p.with_suffix(".log")


def parse_step_values(text: str) -> list[dict[str, str]]:
    steps = []
    for line in text.splitlines():
        m = _STEP.match(line)
        if m:
            steps.append(dict(re.findall(r"([\w.]+)=(\S+)", m.group(1))))
    return steps


def parse_log(text: str) -> dict:
    """Pull the useful parts out of LTspice log text."""
    lines = text.splitlines()
    measurements: list[dict] = []
    fourier: list[dict] = []
    problems: list[str] = []
    current_fourier = None
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        # Stepped .meas results come as a table:
        #   Measurement: vmax
        #     step  MAX(v(out))  FROM  TO
        #        1  1.02         0     0.001
        if line.startswith("Measurement:"):
            name = line.split(":", 1)[1].strip()
            columns = lines[i + 1].split("\t") if i + 1 < len(lines) else []
            columns = [c.strip() for c in columns if c.strip()]
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip():
                cells = [c.strip() for c in lines[i].split("\t") if c.strip()]
                rows.append([f if (f := to_float(c)) is not None else c for c in cells])
                i += 1
            measurements.append({"name": name, "stepped": True, "columns": columns, "rows": rows})
            continue

        m = _MEAS.match(line)
        if m:
            at_kw = m.group("at_kw")
            # "name: cond=val AT x" (WHEN) -> result is x;
            # "name: expr=val at x" (FIND ... AT/WHEN) -> result is val.
            result = m.group("at") if at_kw == "AT" else m.group("value")
            entry = {
                "name": m.group("name"),
                "stepped": False,
                "expression": m.group("expr"),
                "value": m.group("value"),
                "result": to_float(result) if to_float(result) is not None else result,
                "text": line,
            }
            if m.group("at"):
                entry["at"] = to_float(m.group("at"))
            if m.group("from"):
                entry["from"] = to_float(m.group("from"))
                entry["to"] = to_float(m.group("to"))
            measurements.append(entry)

        fm = _FOURIER.match(line)
        if fm:
            current_fourier = {"signal": fm.group(1).strip()}
            fourier.append(current_fourier)
        tm = _THD.match(line.strip())
        if tm and current_fourier is not None:
            current_fourier["thd_percent"] = to_float(tm.group(1))

        if _PROBLEM.search(line) and not line.startswith(("Files loaded", "Circuit:")):
            problem = line.strip()
            # LTspice often follows an error with the offending line and a ^^^ marker.
            if i + 2 < len(lines) and lines[i + 2].strip().startswith("^"):
                problem += "\n" + lines[i + 1] + "\n" + lines[i + 2]
                i += 2
            problems.append(problem)
        i += 1

    return {
        "measurements": measurements,
        "step_values": parse_step_values(text),
        "fourier": fourier,
        "problems": problems,
    }


def read_log(path: str | Path) -> dict:
    log = log_path_for(path)
    text, _ = read_text(log)
    result = parse_log(text)
    result["log_path"] = str(log)
    result["text"] = text
    return result
