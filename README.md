# dsl-ltspice-mcp

An MCP server that lets Claude (or any MCP client) drive LTspice: run simulations, read
`.meas` results and waveforms, render schematics to SVG, and look things up in the official
LTspice help. By **Double Secret Labs**.

It runs LTspice in batch mode (`LTspice.exe -b`), so it works on any Windows PC with LTspice
installed, including Windows on ARM. It doesn't attach to an open LTspice window.

*Not affiliated with or endorsed by Analog Devices. LTspice is a trademark of Analog Devices, Inc.*

## Install

You need LTspice (free from analog.com) and Claude Code or Claude Desktop.

1. Download the exe for your PC and put it somewhere permanent, e.g.
   `C:\Tools\dsl-ltspice-mcp\`:
   - `dsl-ltspice-mcp-x64.exe` for normal Intel/AMD PCs
   - `dsl-ltspice-mcp-arm64.exe` for Windows on ARM (Snapdragon etc.)
2. Windows may warn that the file is unrecognized, because it isn't code-signed. Choose
   **More info** then **Run anyway**, or right-click the file, open **Properties** and tick **Unblock**.
3. Check it can find LTspice:
   ```powershell
   C:\Tools\dsl-ltspice-mcp\dsl-ltspice-mcp-x64.exe status
   ```
4. Register it with Claude Code (available in every project):
   ```powershell
   claude mcp add --scope user --transport stdio dsl-ltspice -- "C:\Tools\dsl-ltspice-mcp\dsl-ltspice-mcp-x64.exe"
   ```
   For Claude Desktop, add this to `claude_desktop_config.json` instead:
   ```json
   "mcpServers": {
     "dsl-ltspice": { "command": "C:\\Tools\\dsl-ltspice-mcp\\dsl-ltspice-mcp-x64.exe" }
   }
   ```
5. Restart Claude. The tools appear as `dsl-ltspice` (in Claude Code: `mcp__dsl-ltspice__*`).

If LTspice is installed somewhere unusual, set the environment variable `DSL_LTSPICE_EXE` to
the full path of `LTspice.exe`.

## Tools

| Tool | What it does |
|---|---|
| `ltspice_status` | Where LTspice, its symbol library and help files were found |
| `read_design`, `write_design` | Read or write `.asc`, `.cir`/`.net`, `.lib`, `.asy` files (keeps LTspice's text encoding) |
| `generate_netlist` | Netlist from a schematic (`LTspice -netlist`) |
| `run_simulation` | Run a schematic or netlist and return errors, `.step` values, `.meas` and `.four` THD results |
| `get_simulation_log` | Parse a `.log` file |
| `get_raw_info` | Analysis type, signals, points and steps in a `.raw` file |
| `read_waveforms` | Waveform data per step; AC as dB/phase, mag/phase or re/im; can decimate |
| `export_waveforms` | Write waveforms to CSV or SQLite |
| `export_schematic_svg` | Render a schematic to SVG |
| `search_reference_docs`, `get_reference_doc`, `list_reference_docs` | Search and read the LTspice help installed with LTspice |

## Example prompts

- "Write a netlist for a 2nd-order Sallen-Key low-pass at 10 kHz, simulate it, and give me the -3 dB point."
- "Run `C:\designs\amp.asc`, read V(out) from the AC analysis, and report bandwidth and phase margin."
- "Add `.step param Rload list 10 100 1k` and compare the output ripple for each step."
- "Export the schematic to SVG with a white background for my report."
- "My sim fails with 'timestep too small'. Check the LTspice docs and fix it."

## Command line and Python use

The exe also has a few commands for scripts:

```powershell
dsl-ltspice-mcp-x64.exe status
dsl-ltspice-mcp-x64.exe sim C:\designs\filter.cir      # prints results as JSON
dsl-ltspice-mcp-x64.exe svg C:\designs\filter.asc -o filter.svg --background "#ffffff"
```

From Python (with the package installed), the same functions are available directly:

```python
from dsl_ltspice_mcp import simulate, read_raw, read_log, asc_to_svg

simulate("C:/designs/filter.asc")
raw = read_raw("C:/designs/filter.raw")
freq, vout = raw.axis(), raw.signal("V(out)")   # numpy arrays (complex for AC)
meas = read_log("C:/designs/filter.log")["measurements"]
asc_to_svg("C:/designs/filter.asc", "filter.svg")
```

## Schematic symbols

The SVG export draws symbols from a small hand-tuned set (from the DSL schematic-export
tool), then from the schematic's own folder, then from your LTspice library
(`%LOCALAPPDATA%\LTspice\lib\sym`, or `lib.zip`). Add more symbol folders with the
`DSL_LTSPICE_SYMBOL_PATH` environment variable (separate folders with `;`). Anything not
found is drawn as a dashed box.

## Building from source

Requires [uv](https://docs.astral.sh/uv/). On the machine type you want an exe for:

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

This produces `dist\dsl-ltspice-mcp-x64.exe` or `dist\dsl-ltspice-mcp-arm64.exe`.
To run from source instead: `uv run python -m dsl_ltspice_mcp`.

## License

MIT. See [LICENSE](LICENSE).
