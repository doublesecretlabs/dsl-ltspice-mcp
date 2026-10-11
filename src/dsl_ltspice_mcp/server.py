"""MCP server exposing LTspice simulation, waveform, schematic and docs tools."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import anyio
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import __version__, docs, logfile, ltspice, rawfile
from .schematic_svg import DEFAULT_OPTIONS, asc_to_svg

INSTRUCTIONS = """\
Drives a local LTspice install in batch mode (no GUI). Typical flow: write or edit a
netlist/schematic with write_design, run_simulation, then get_simulation_log for .meas
results and get_raw_info / read_waveforms for data. Always pass absolute paths.
For LTspice syntax questions, search the official help with search_reference_docs
instead of answering from memory."""

mcp = FastMCP("dsl-ltspice", instructions=INSTRUCTIONS)
mcp._mcp_server.version = __version__  # otherwise it reports the mcp library's version

Path_ = Annotated[str, Field(description="Absolute path to the file.")]


def _abs(path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else p.resolve()


# ------------------------------------------------------------
# Status
# ------------------------------------------------------------

@mcp.tool()
def ltspice_status() -> dict:
    """Show where LTspice, its symbol library and its help files were found."""
    try:
        exe = ltspice.find_ltspice()
        exe_info = {"path": str(exe), "version": ltspice.file_version(exe)}
    except ltspice.LTspiceNotFound as e:
        exe_info = {"error": str(e)}
    help_ = ltspice.help_dir()
    return {
        "server": f"dsl-ltspice-mcp {__version__}",
        "ltspice": exe_info,
        "symbol_dirs": [str(d) for d in ltspice.symbol_dirs()],
        "library_zip": str(z) if (z := ltspice.library_zip()) else None,
        "help_dir": str(help_) if help_ else None,
    }


# ------------------------------------------------------------
# Designs
# ------------------------------------------------------------

@mcp.tool()
def read_design(path: Path_) -> dict:
    """Read a schematic (.asc), netlist (.cir/.net/.sp), library (.lib/.sub) or symbol (.asy) as text.

    Handles the UTF-16 and Windows-1252 encodings LTspice sometimes uses."""
    text, encoding = ltspice.read_text(_abs(path))
    return {"path": str(_abs(path)), "encoding": encoding, "content": text}


@mcp.tool()
def write_design(
    path: Path_,
    content: Annotated[str, Field(description="Full new file contents.")],
) -> dict:
    """Create or replace a schematic, netlist or library file.

    An existing file keeps its original text encoding. New files are written as UTF-8."""
    p = _abs(path)
    encoding = ltspice.read_text(p)[1] if p.exists() else "utf-8"
    p.parent.mkdir(parents=True, exist_ok=True)
    ltspice.write_text(p, content, encoding)
    return {"path": str(p), "encoding": encoding, "bytes": p.stat().st_size}


@mcp.tool()
async def generate_netlist(asc_path: Path_) -> dict:
    """Generate the SPICE netlist for a schematic (writes name.net next to it) and return it."""
    net = await anyio.to_thread.run_sync(ltspice.make_netlist, _abs(asc_path))
    return {"netlist_path": str(net), "content": ltspice.read_text(net)[0]}


# ------------------------------------------------------------
# Simulation
# ------------------------------------------------------------

@mcp.tool()
async def run_simulation(
    design_path: Annotated[str, Field(description="Absolute path to an .asc schematic or a .cir/.net/.sp netlist.")],
    timeout_seconds: Annotated[float, Field(description="Kill LTspice if it runs longer than this.")] = 300,
) -> dict:
    """Run a simulation with LTspice in batch mode and wait for it to finish.

    Returns the output files, any errors or warnings from the log, and the .meas results.
    Waveforms go to name.raw (and name.op.raw for the operating point)."""
    design = _abs(design_path)
    result = await anyio.to_thread.run_sync(ltspice.simulate, design, timeout_seconds)
    out: dict = {
        "design_path": str(design),
        "exit_code": result.exit_code,
        "elapsed_s": round(result.elapsed_s, 3),
        "timed_out": result.timed_out,
        "output_files": [str(p) for p in result.outputs],
    }
    log = logfile.log_path_for(design)
    if log in result.outputs:
        parsed = logfile.read_log(log)
        out["log_path"] = str(log)
        out["problems"] = parsed["problems"]
        out["measurements"] = parsed["measurements"]
        out["step_values"] = parsed["step_values"]
        if parsed["fourier"]:
            out["fourier"] = parsed["fourier"]
        if result.exit_code != 0:
            out["log_tail"] = "\n".join(parsed["text"].splitlines()[-15:])
    else:
        out["problems"] = ["LTspice didn't write a new .log file; the design may have failed to load."]
    raw = rawfile.raw_path_for(design)
    if raw in result.outputs:
        out["raw_path"] = str(raw)
    return out


@mcp.tool()
def get_simulation_log(
    path: Annotated[str, Field(description="Absolute path to the .log file, or the design/.raw path (the .log next to it is used).")],
    include_text: Annotated[bool, Field(description="Include the full log text as well as the parsed results.")] = True,
) -> dict:
    """Read an LTspice .log: .meas results (including stepped tables), .step values,
    .four THD, and error or warning lines."""
    result = logfile.read_log(_abs(path))
    if not include_text:
        result.pop("text")
    return result


# ------------------------------------------------------------
# Waveforms
# ------------------------------------------------------------

@mcp.tool()
def get_raw_info(
    raw_path: Annotated[str, Field(description="Absolute path to a .raw file (or the design; name.raw is used).")],
) -> dict:
    """List the analysis type, signals, point count, steps and step parameters in a .raw file.
    Call this before read_waveforms to size the request."""
    return rawfile.info(rawfile.read_raw(_abs(raw_path)))


@mcp.tool()
def read_waveforms(
    raw_path: Annotated[str, Field(description="Absolute path to a .raw file (or the design; name.raw is used).")],
    signals: Annotated[list[str] | None, Field(description="Signal names such as 'V(out)' or 'I(L1)'. Default: all.")] = None,
    steps: Annotated[list[int] | None, Field(description="Step indices, numbered from 0. Default: all steps.")] = None,
    x_min: Annotated[float | None, Field(description="Only points with time/frequency >= x_min.")] = None,
    x_max: Annotated[float | None, Field(description="Only points with time/frequency <= x_max.")] = None,
    ac_format: Annotated[Literal["db_phase", "mag_phase", "cartesian"], Field(
        description="How complex (AC) values are returned.")] = "db_phase",
    max_points_per_step: Annotated[int | None, Field(
        description="Decimate evenly to at most this many points per step.")] = None,
    max_values: Annotated[int, Field(description="Refuse requests larger than this many numbers.")] = 10_000,
) -> dict:
    """Return waveform data from a .raw file, per step. For .op files, returns the operating-point values."""
    raw = rawfile.read_raw(_abs(raw_path))
    return rawfile.waveforms(raw, signals, steps, x_min, x_max, ac_format, max_points_per_step, max_values)


@mcp.tool()
def export_waveforms(
    raw_path: Annotated[str, Field(description="Absolute path to a .raw file (or the design; name.raw is used).")],
    output_path: Annotated[str, Field(description="Absolute path ending in .csv (wide table) or .db/.sqlite (SQLite, one row per value).")],
    signals: Annotated[list[str] | None, Field(description="Signal names. Default: all.")] = None,
    steps: Annotated[list[int] | None, Field(description="Step indices from 0. Default: all.")] = None,
    x_min: float | None = None,
    x_max: float | None = None,
    ac_format: Annotated[Literal["db_phase", "mag_phase", "cartesian"], Field(
        description="Complex value columns for CSV output (SQLite stores all forms).")] = "db_phase",
) -> dict:
    """Write waveforms to CSV or SQLite, for data too large to read directly or for SQL queries."""
    raw = rawfile.read_raw(_abs(raw_path))
    return rawfile.export(raw, _abs(output_path), signals, steps, x_min, x_max, ac_format)


# ------------------------------------------------------------
# Schematic export
# ------------------------------------------------------------

@mcp.tool()
def export_schematic_svg(
    asc_path: Path_,
    output_path: Annotated[str | None, Field(description="Where to write the SVG. Default: next to the .asc with an .svg extension.")] = None,
    stroke_color: str = "#000000",
    background: Annotated[str, Field(description="Background fill, e.g. '#ffffff', or 'none' for transparent.")] = "none",
    scale: float = 1.0,
    wire_width: float = 2,
    symbol_width: float = 1.5,
    font_family: str = "Arial, sans-serif",
    font_size: float = 18,
    show_values: bool = True,
    show_refdes: bool = True,
    show_net_names: bool = True,
    show_junctions: bool = True,
    junction_dot_shape: Literal["circle", "square"] = "circle",
    custom_symbols: Annotated[bool, Field(description="Prefer DSL custom symbol variants (e.g. res-mrcust) where available.")] = False,
    include_metadata: Annotated[bool, Field(description="Add component attributes as data-* attributes on each symbol.")] = False,
    return_svg: Annotated[bool, Field(description="Also return the SVG text in the result.")] = False,
) -> dict:
    """Render an LTspice schematic (.asc) to an SVG drawing, e.g. for a report."""
    asc = _abs(asc_path)
    out = _abs(output_path) if output_path else asc.with_suffix(".svg")
    options = {**DEFAULT_OPTIONS,
               "strokeColor": stroke_color, "background": background, "scale": scale,
               "wireWidth": wire_width, "symbolWidth": symbol_width, "fontFamily": font_family,
               "fontSize": font_size, "showValues": show_values, "showRefDes": show_refdes,
               "showNetNames": show_net_names, "showJunctions": show_junctions,
               "junctionDotShape": junction_dot_shape, "customSymbols": custom_symbols,
               "includeMetadata": include_metadata}
    r = asc_to_svg(asc, out, options)
    result = {"svg_path": str(out), "width": round(r.width, 1), "height": round(r.height, 1),
              "unknown_symbols": r.unknown_symbols,
              "note": "Unknown symbols are drawn as dashed placeholder boxes." if r.unknown_symbols else None}
    if return_svg:
        result["svg"] = r.svg
    return result


# ------------------------------------------------------------
# Reference docs
# ------------------------------------------------------------

@mcp.tool()
def search_reference_docs(
    query: Annotated[str, Field(description="Words to search for, e.g. '.meas rise time' or 'timestep too small'.")],
    limit: int = 8,
) -> list[dict]:
    """Search the official LTspice help pages installed with LTspice. Returns page names and snippets."""
    return docs.search(query, limit)


@mcp.tool()
def get_reference_doc(
    name: Annotated[str, Field(description="Page name from search_reference_docs or list_reference_docs.")],
) -> dict:
    """Return the full text of one LTspice help page."""
    return docs.get_doc(name)


@mcp.tool()
def list_reference_docs(
    filter: Annotated[str | None, Field(description="Only pages whose title or name contains this text.")] = None,
) -> list[dict]:
    """List the LTspice help pages (name and title)."""
    return docs.list_docs(filter)


def run() -> None:
    mcp.run()
