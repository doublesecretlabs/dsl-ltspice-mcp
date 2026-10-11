"""Locating LTspice and running it in batch mode."""

from __future__ import annotations

import codecs
import ctypes
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

ENV_EXE = "DSL_LTSPICE_EXE"
ENV_SYMBOL_PATH = "DSL_LTSPICE_SYMBOL_PATH"

# File types LTspice can simulate directly.
SIM_SUFFIXES = {".asc", ".cir", ".net", ".sp", ".spi", ".txt"}


class LTspiceNotFound(RuntimeError):
    pass


# ------------------------------------------------------------
# Text files (LTspice writes UTF-8, UTF-16 or Windows-1252)
# ------------------------------------------------------------

def read_text(path: str | Path) -> tuple[str, str]:
    """Read an LTspice text file, returning (text, encoding).

    The encoding name can be passed back to write_text() to save the file
    the same way it was read.
    """
    data = Path(path).read_bytes()
    if data.startswith(codecs.BOM_UTF8):
        return data[3:].decode("utf-8"), "utf-8-sig"
    if data.startswith(codecs.BOM_UTF16_LE):
        return data[2:].decode("utf-16-le"), "utf-16"
    if len(data) >= 2 and data[0] != 0 and data[1] == 0:
        return data.decode("utf-16-le"), "utf-16-le"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252"), "cp1252"


def write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    # newline="" keeps whatever line endings the caller supplied.
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(text)


# ------------------------------------------------------------
# Locating LTspice
# ------------------------------------------------------------

def _candidate_exes() -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    pf86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    return [
        local / "Programs" / "ADI" / "LTspice" / "LTspice.exe",
        pf / "ADI" / "LTspice" / "LTspice.exe",
        pf / "LTC" / "LTspiceXVII" / "XVIIx64.exe",
        pf86 / "LTC" / "LTspiceIV" / "scad3.exe",
    ]


def find_ltspice() -> Path:
    override = os.environ.get(ENV_EXE)
    if override:
        p = Path(override)
        if p.is_file():
            return p
        raise LTspiceNotFound(f"{ENV_EXE} is set to {override!r}, but that file doesn't exist.")
    for p in _candidate_exes():
        if p.is_file():
            return p
    raise LTspiceNotFound(
        "LTspice was not found. Install it from analog.com, or set the "
        f"{ENV_EXE} environment variable to the full path of LTspice.exe."
    )


def file_version(path: Path) -> str | None:
    """Return the Windows file version of an executable, e.g. '26.0.2.1'."""
    try:
        ver = ctypes.windll.version  # type: ignore[attr-defined]
        size = ver.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
            return None
        ptr = ctypes.c_void_p()
        length = ctypes.c_uint()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
            return None
        # VS_FIXEDFILEINFO: dwFileVersionMS / dwFileVersionLS at offsets 8 and 12.
        ms = ctypes.c_uint32.from_address(ptr.value + 8).value
        ls = ctypes.c_uint32.from_address(ptr.value + 12).value
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except (AttributeError, OSError):
        return None


def user_lib_dir() -> Path:
    """Where LTspice 17+ unpacks its component library."""
    return Path(os.environ.get("LOCALAPPDATA", "")) / "LTspice" / "lib"


def symbol_dirs() -> list[Path]:
    """Directories searched for .asy symbol files, in priority order."""
    dirs: list[Path] = []
    extra = os.environ.get(ENV_SYMBOL_PATH)
    if extra:
        dirs += [Path(p) for p in extra.split(os.pathsep) if p]
    docs = Path(os.environ.get("USERPROFILE", "")) / "Documents" / "LTspice" / "lib" / "sym"
    dirs += [docs, user_lib_dir() / "sym"]
    return [d for d in dirs if d.is_dir()]


def library_zip() -> Path | None:
    """lib.zip next to LTspice.exe (fallback if the library isn't unpacked)."""
    candidates = [user_lib_dir().parent / "lib.zip"]
    try:
        candidates.insert(0, find_ltspice().parent / "lib.zip")
    except LTspiceNotFound:
        pass
    return next((p for p in candidates if p.is_file()), None)


def help_dir() -> Path | None:
    try:
        d = find_ltspice().parent / "LTspiceHelp"
    except LTspiceNotFound:
        return None
    return d if d.is_dir() else None


# ------------------------------------------------------------
# Running LTspice
# ------------------------------------------------------------

@dataclass
class RunResult:
    exit_code: int | None
    elapsed_s: float
    timed_out: bool
    command: list[str]
    outputs: list[Path] = field(default_factory=list)


def _run(args: list[str], cwd: Path, timeout: float) -> tuple[int | None, float, bool]:
    exe = str(find_ltspice())
    start = time.monotonic()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # stdin/stdout must not be inherited: in server mode they carry the MCP protocol.
    proc = subprocess.Popen(
        [exe, *args], cwd=cwd, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
    )
    try:
        code = proc.wait(timeout=timeout)
        return code, time.monotonic() - start, False
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return None, time.monotonic() - start, True


def output_files(design: Path, since: float = 0.0) -> list[Path]:
    """Files LTspice wrote for a design: name.log, name.raw, name.op.raw, ..."""
    found = []
    for p in design.parent.glob(design.stem + ".*"):
        if p == design or p.suffix.lower() in SIM_SUFFIXES - {".net"}:
            continue
        if p.stat().st_mtime >= since:
            found.append(p)
    return sorted(found)


def simulate(design: str | Path, timeout: float = 300.0) -> RunResult:
    """Run a schematic or netlist with `LTspice -b` and wait for it to finish."""
    design = Path(design).resolve()
    if not design.is_file():
        raise FileNotFoundError(design)
    started = time.time() - 1  # mtime granularity
    args = ["-b", str(design)]
    code, elapsed, timed_out = _run(args, design.parent, timeout)
    return RunResult(code, elapsed, timed_out, args, output_files(design, started))


def make_netlist(asc: str | Path, timeout: float = 60.0) -> Path:
    """Generate name.net from a schematic with `LTspice -netlist`."""
    asc = Path(asc).resolve()
    if asc.suffix.lower() != ".asc":
        raise ValueError("Netlists can only be generated from .asc schematics.")
    if not asc.is_file():
        raise FileNotFoundError(asc)
    net = asc.with_suffix(".net")
    before = net.stat().st_mtime if net.exists() else None
    code, _, timed_out = _run(["-netlist", str(asc)], asc.parent, timeout)
    if timed_out:
        raise TimeoutError(f"LTspice didn't finish generating the netlist within {timeout} s.")
    if not net.exists() or (before is not None and net.stat().st_mtime == before):
        raise RuntimeError(f"LTspice exited with code {code} but didn't write {net}.")
    return net
