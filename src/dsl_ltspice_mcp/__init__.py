"""DSL LTspice MCP: drive LTspice from Claude (or your own Python scripts).

Library use, without MCP:

    from dsl_ltspice_mcp import simulate, read_raw, read_log, asc_to_svg
    simulate("C:/designs/filter.asc")
    raw = read_raw("C:/designs/filter.raw")
    vout = raw.signal("V(out)")
"""

__version__ = "0.1.0"

from .logfile import parse_log, read_log  # noqa: E402
from .ltspice import find_ltspice, make_netlist, simulate  # noqa: E402
from .rawfile import RawFile, read_raw  # noqa: E402
from .schematic_svg import asc_to_svg, parse_asc, render_schematic  # noqa: E402


def main() -> None:
    from .cli import main as cli_main
    cli_main()


__all__ = ["RawFile", "asc_to_svg", "find_ltspice", "main", "make_netlist", "parse_asc",
           "parse_log", "read_log", "read_raw", "render_schematic", "simulate"]
