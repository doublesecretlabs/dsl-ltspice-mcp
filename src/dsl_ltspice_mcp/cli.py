"""Command line: no arguments runs the MCP server on stdio; subcommands are for scripts."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="dsl-ltspice-mcp",
        description="LTspice MCP server by Double Secret Labs. Run with no arguments to start the "
                    "MCP server (stdio), or use a subcommand.")
    parser.add_argument("--version", action="version", version=f"dsl-ltspice-mcp {__version__}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("serve", help="Run the MCP server on stdio (the default).")

    p = sub.add_parser("sim", help="Run a simulation and print the results as JSON.")
    p.add_argument("design")
    p.add_argument("--timeout", type=float, default=300)

    p = sub.add_parser("svg", help="Convert an .asc schematic to SVG.")
    p.add_argument("asc")
    p.add_argument("-o", "--output", help="Output path (default: next to the .asc).")
    p.add_argument("--background", default="none")
    p.add_argument("--custom-symbols", action="store_true")

    p = sub.add_parser("status", help="Show where LTspice and its library were found.")

    args = parser.parse_args(argv)

    if args.command in (None, "serve"):
        from .server import run
        run()
    elif args.command == "status":
        from .server import ltspice_status
        print(json.dumps(ltspice_status(), indent=2))
    elif args.command == "sim":
        import anyio
        from .server import run_simulation
        print(json.dumps(anyio.run(run_simulation, args.design, args.timeout), indent=2))
    elif args.command == "svg":
        from pathlib import Path
        from .schematic_svg import asc_to_svg
        out = args.output or str(Path(args.asc).with_suffix(".svg"))
        r = asc_to_svg(args.asc, out, {"background": args.background, "customSymbols": args.custom_symbols})
        print(f"Wrote {out} ({r.width:.0f} x {r.height:.0f})")
        if r.unknown_symbols:
            print("Unknown symbols (drawn as placeholders): " + ", ".join(r.unknown_symbols), file=sys.stderr)
