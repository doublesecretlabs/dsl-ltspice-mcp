"""Reading LTspice binary .raw waveform files."""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .logfile import log_path_for, parse_step_values
from .ltspice import read_text


@dataclass
class Variable:
    index: int
    name: str
    kind: str


@dataclass
class RawFile:
    path: Path
    title: str
    date: str
    plotname: str
    flags: set[str]
    variables: list[Variable]
    data: np.ndarray            # shape (points, variables); complex for AC
    step_slices: list[slice]

    @property
    def is_complex(self) -> bool:
        return "complex" in self.flags

    @property
    def x(self) -> Variable:
        return self.variables[0]

    @property
    def n_points(self) -> int:
        return self.data.shape[0]

    @property
    def n_steps(self) -> int:
        return len(self.step_slices)

    def find(self, name: str) -> Variable:
        for v in self.variables:
            if v.name == name:
                return v
        for v in self.variables:
            if v.name.lower() == name.lower():
                return v
        # Allow "out" for "V(out)".
        for v in self.variables:
            if v.name.lower() == f"v({name.lower()})":
                return v
        raise KeyError(f"Signal {name!r} isn't in {self.path.name}. "
                       f"Available: {', '.join(v.name for v in self.variables)}")

    def axis(self, step: int | None = None) -> np.ndarray:
        x = self.data[:, 0].real
        return x if step is None else x[self.step_slices[step]]

    def signal(self, name: str, step: int | None = None) -> np.ndarray:
        col = self.data[:, self.find(name).index]
        if not self.is_complex:
            col = col.real
        return col if step is None else col[self.step_slices[step]]

    def step_values(self) -> list[dict[str, str]]:
        """Parameter values for each step, read from the matching .log file."""
        log = log_path_for(self.path)
        if not log.exists():
            return []
        steps = parse_step_values(read_text(log)[0])
        return steps if len(steps) == self.n_steps else []


def raw_path_for(path: str | Path) -> Path:
    p = Path(path)
    return p if p.suffix.lower() == ".raw" else p.with_suffix(".raw")


def read_raw(path: str | Path) -> RawFile:
    path = raw_path_for(path)
    blob = path.read_bytes()
    enc = "utf-16-le" if len(blob) > 1 and blob[1] == 0 else "latin-1"

    def encoded(s: str) -> bytes:
        return s.encode(enc)

    marker_pos, binary = -1, True
    for marker, is_binary in (("Binary:", True), ("Values:", False)):
        marker_pos = blob.find(encoded(marker))
        if marker_pos >= 0:
            binary = is_binary
            break
    if marker_pos < 0:
        raise ValueError(f"{path} doesn't look like an LTspice .raw file.")
    newline = blob.find(encoded("\n"), marker_pos)
    start = newline + len(encoded("\n"))
    header = blob[:marker_pos].decode(enc)

    fields: dict[str, str] = {}
    variables: list[Variable] = []
    in_vars = False
    for line in header.splitlines():
        if in_vars and line[:1] in ("\t", " "):
            parts = line.split()
            if len(parts) >= 3:
                variables.append(Variable(int(parts[0]), parts[1], parts[2]))
            continue
        in_vars = False
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
            if key.strip() == "Variables":
                in_vars = True

    flags = set(fields.get("Flags", "").lower().split())
    n_vars = int(fields["No. Variables"])
    n_pts = int(fields["No. Points"])
    if not binary:
        raise ValueError("ASCII .raw files aren't supported. Re-run LTspice without the -ascii option.")

    data = _decode_binary(blob[start:], flags, n_vars, n_pts)
    if not np.iscomplexobj(data) and fields.get("Plotname", "").lower().startswith("transient"):
        # LTspice flags some time points by negating them.
        data[:, 0] = np.abs(data[:, 0])

    raw = RawFile(path, fields.get("Title", ""), fields.get("Date", ""),
                  fields.get("Plotname", ""), flags, variables, data, [])
    raw.step_slices = _find_steps(raw.axis())
    return raw


def _decode_binary(buf: bytes, flags: set[str], n_vars: int, n_pts: int) -> np.ndarray:
    if "complex" in flags:
        layouts = [("complex", 16 * n_vars)]
    elif "double" in flags:
        layouts = [("double", 8 * n_vars)]
    else:
        # Normally the x axis is a double and everything else float32.
        layouts = [("mixed", 8 + 4 * (n_vars - 1)), ("float", 4 * n_vars), ("double", 8 * n_vars)]
    for kind, point_size in layouts:
        if point_size * n_pts == len(buf):
            break
    else:
        kind, point_size = layouts[0]
        n_pts = len(buf) // point_size  # truncated file (sim still running?)
        buf = buf[: n_pts * point_size]

    fast = "fastaccess" in flags
    if kind == "complex":
        flat = np.frombuffer(buf, "<c16")
        return (flat.reshape(n_vars, n_pts).T if fast else flat.reshape(n_pts, n_vars)).copy()
    if kind == "double":
        flat = np.frombuffer(buf, "<f8")
        return (flat.reshape(n_vars, n_pts).T if fast else flat.reshape(n_pts, n_vars)).copy()
    if kind == "float":
        flat = np.frombuffer(buf, "<f4").astype(np.float64)
        return flat.reshape(n_vars, n_pts).T.copy() if fast else flat.reshape(n_pts, n_vars)
    out = np.empty((n_pts, n_vars), np.float64)
    if fast:
        out[:, 0] = np.frombuffer(buf, "<f8", n_pts)
        out[:, 1:] = np.frombuffer(buf, "<f4", offset=8 * n_pts).reshape(n_vars - 1, n_pts).T
    else:
        rec = np.frombuffer(buf, np.dtype([("x", "<f8"), ("y", "<f4", (n_vars - 1,))]))
        out[:, 0] = rec["x"]
        out[:, 1:] = rec["y"]
    return out


def _find_steps(x: np.ndarray) -> list[slice]:
    """Each .step run restarts the x axis at its first value."""
    if len(x) == 0:
        return [slice(0, 0)]
    starts = [0] + [int(i) for i in np.flatnonzero(x[1:] == x[0]) + 1]
    # A sweep that genuinely revisits x[0] would be split wrongly; require
    # the axis to go backwards just before each restart.
    starts = [s for s in starts if s == 0 or x[s - 1] != x[0]]
    ends = starts[1:] + [len(x)]
    return [slice(a, b) for a, b in zip(starts, ends)]


# ------------------------------------------------------------
# Summaries and extraction
# ------------------------------------------------------------

def analysis_type(raw: RawFile) -> str:
    p = raw.plotname.lower()
    for key, name in (("transient", "tran"), ("ac", "ac"), ("dc", "dc"), ("operating", "op"),
                      ("noise", "noise"), ("transfer", "tf"), ("fft", "fft")):
        if p.startswith(key):
            return name
    return p


def operating_point(raw: RawFile) -> list[dict]:
    """Values from a .op raw file (no x axis: every variable is a result)."""
    log = log_path_for(raw.path)
    steps = parse_step_values(read_text(log)[0]) if log.exists() else []
    points = []
    for i in range(raw.n_points):
        p: dict = {"step": i}
        if len(steps) == raw.n_points:
            p["params"] = steps[i]
        p["values"] = {v.name: float(raw.data[i, v.index].real) for v in raw.variables}
        points.append(p)
    return points


def info(raw: RawFile) -> dict:
    if analysis_type(raw) == "op":
        return {"raw_path": str(raw.path), "analysis": "op", "plotname": raw.plotname,
                "points_total": raw.n_points,
                "signals": [{"name": v.name, "type": v.kind} for v in raw.variables],
                "note": "Operating point: use read_waveforms to get the values."}
    x = raw.axis()
    lengths = [s.stop - s.start for s in raw.step_slices]
    return {
        "raw_path": str(raw.path),
        "analysis": analysis_type(raw),
        "plotname": raw.plotname,
        "flags": sorted(raw.flags),
        "points_total": raw.n_points,
        "steps": raw.n_steps,
        "points_per_step": lengths if len(set(lengths)) > 1 else lengths[0],
        "step_values": raw.step_values(),
        "x_axis": {"name": raw.x.name, "min": float(x.min()) if len(x) else None,
                   "max": float(x.max()) if len(x) else None},
        "signals": [{"name": v.name, "type": v.kind} for v in raw.variables[1:]],
    }


def _format_complex(values: np.ndarray, ac_format: str) -> dict[str, list[float]]:
    if ac_format == "cartesian":
        return {"re": values.real.tolist(), "im": values.imag.tolist()}
    mag = np.abs(values)
    phase = np.degrees(np.angle(values))
    if ac_format == "mag_phase":
        return {"mag": mag.tolist(), "phase_deg": phase.tolist()}
    with np.errstate(divide="ignore"):
        db = 20 * np.log10(mag)
    return {"db": db.tolist(), "phase_deg": phase.tolist()}


def _select(raw: RawFile, signals, steps, x_min, x_max):
    names = [v.name for v in raw.variables[1:]] if not signals else [raw.find(s).name for s in signals]
    step_ids = list(range(raw.n_steps)) if steps is None else list(steps)
    for s in step_ids:
        if not 0 <= s < raw.n_steps:
            raise IndexError(f"Step {s} is out of range (the file has {raw.n_steps} steps, numbered from 0).")
    masks = {}
    for s in step_ids:
        x = raw.axis(s)
        m = np.ones(len(x), bool)
        if x_min is not None:
            m &= x >= x_min
        if x_max is not None:
            m &= x <= x_max
        masks[s] = m
    return names, step_ids, masks


def waveforms(raw: RawFile, signals: list[str] | None = None, steps: list[int] | None = None,
              x_min: float | None = None, x_max: float | None = None,
              ac_format: str = "db_phase", max_points_per_step: int | None = None,
              max_values: int = 10_000) -> dict:
    if analysis_type(raw) == "op":
        points = operating_point(raw)
        if signals:
            wanted = {raw.find(s).name for s in signals}
            for p in points:
                p["values"] = {k: v for k, v in p["values"].items() if k in wanted}
        return {"analysis": "op", "points": points}
    names, step_ids, masks = _select(raw, signals, steps, x_min, x_max)
    if max_points_per_step:
        for s, m in masks.items():
            idx = np.flatnonzero(m)
            if len(idx) > max_points_per_step:
                keep = idx[np.linspace(0, len(idx) - 1, max_points_per_step).round().astype(int)]
                m[:] = False
                m[keep] = True
    per_value = 2 if raw.is_complex else 1
    total = sum(int(m.sum()) * (1 + per_value * len(names)) for m in masks.values())
    if total > max_values:
        raise ValueError(
            f"That selection is {total} values, over the limit of {max_values}. Narrow it with "
            "x_min/x_max, steps or fewer signals, set max_points_per_step to decimate, raise "
            "max_values, or use export_waveforms instead.")

    out_steps = []
    step_vals = raw.step_values()
    for s in step_ids:
        m = masks[s]
        entry: dict = {"step": s}
        if step_vals:
            entry["params"] = step_vals[s]
        entry["x"] = raw.axis(s)[m].tolist()
        entry["signals"] = {}
        for n in names:
            y = raw.signal(n, s)[m]
            entry["signals"][n] = _format_complex(y, ac_format) if raw.is_complex else y.tolist()
        out_steps.append(entry)
    return {"analysis": analysis_type(raw), "x_name": raw.x.name,
            "format": ac_format if raw.is_complex else "real", "steps": out_steps}


def export(raw: RawFile, output: str | Path, signals: list[str] | None = None,
           steps: list[int] | None = None, x_min: float | None = None,
           x_max: float | None = None, ac_format: str = "db_phase") -> dict:
    """Write waveforms to .csv (wide) or .db/.sqlite (long format, one row per value)."""
    output = Path(output)
    names, step_ids, masks = _select(raw, signals, steps, x_min, x_max)
    step_vals = raw.step_values()
    suffix = output.suffix.lower()
    rows = 0

    def columns_for(n: str) -> list[str]:
        if not raw.is_complex:
            return [n]
        keys = {"cartesian": ("re", "im"), "mag_phase": ("mag", "phase_deg")}.get(ac_format, ("db", "phase_deg"))
        return [f"{n} {k}" for k in keys]

    if suffix == ".csv":
        with open(output, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            header = ["step", raw.x.name] + [c for n in names for c in columns_for(n)]
            w.writerow(header)
            for s in step_ids:
                m = masks[s]
                cols = [raw.axis(s)[m]]
                for n in names:
                    y = raw.signal(n, s)[m]
                    if raw.is_complex:
                        cols += list(_format_complex(y, ac_format).values())
                    else:
                        cols.append(y)
                for r in zip(*cols):
                    w.writerow([s, *r])
                    rows += 1
    elif suffix in (".db", ".sqlite", ".sqlite3"):
        if output.exists():
            output.unlink()
        con = sqlite3.connect(output)
        con.executescript("""
            CREATE TABLE info (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE steps (step INTEGER, param TEXT, value TEXT);
            CREATE TABLE waveforms (step INTEGER, point INTEGER, x REAL, signal TEXT,
                                    value REAL, re REAL, im REAL, db REAL, phase_deg REAL);
        """)
        con.executemany("INSERT INTO info VALUES (?, ?)", [
            ("raw_path", str(raw.path)), ("analysis", analysis_type(raw)),
            ("x_name", raw.x.name), ("plotname", raw.plotname)])
        for s in step_ids:
            for k, v in (step_vals[s] if step_vals else {}).items():
                con.execute("INSERT INTO steps VALUES (?, ?, ?)", (s, k, v))
            m = masks[s]
            x = raw.axis(s)[m]
            pts = np.flatnonzero(m)
            for n in names:
                y = raw.signal(n, s)[m]
                if raw.is_complex:
                    with np.errstate(divide="ignore"):
                        db = 20 * np.log10(np.abs(y))
                    ph = np.degrees(np.angle(y))
                    data = zip([s] * len(y), pts.tolist(), x.tolist(), [n] * len(y),
                               np.abs(y).tolist(), y.real.tolist(), y.imag.tolist(), db.tolist(), ph.tolist())
                else:
                    data = ((s, int(p), float(xx), n, float(v), None, None, None, None)
                            for p, xx, v in zip(pts, x, y))
                cur = con.executemany("INSERT INTO waveforms VALUES (?,?,?,?,?,?,?,?,?)", data)
                rows += cur.rowcount
        con.execute("CREATE INDEX idx_signal_step ON waveforms (signal, step)")
        con.commit()
        con.close()
    else:
        raise ValueError("The output file must end in .csv, .db or .sqlite.")
    return {"output_path": str(output.resolve()), "rows": rows, "signals": names, "steps": step_ids,
            "note": None if suffix == ".csv" else
            "Table waveforms(step, point, x, signal, value, re, im, db, phase_deg). For AC data "
            "value is the magnitude; for real data re/im/db/phase_deg are NULL. Step parameters "
            "are in table steps(step, param, value)."}
