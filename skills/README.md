# Claude skills

## research-report

A Claude Code skill that makes research reports consistent: one plot style, full-width figures
(6.5 in, PNG, 300 dpi), numbered captions, LaTeX math and a fixed report layout. Reports are
Markdown written for [Typora](https://typora.io) and exported to PDF. It pairs with the
dsl-ltspice MCP server (which supplies the waveform data), but works with any data.

What's in `research-report/`:

| File | Purpose |
|---|---|
| `SKILL.md` | The rules Claude follows when writing a report |
| `report_style.py` | Shared matplotlib style plus `plot_signals()` and `save_fig()` |
| `report_template.md` | Report skeleton Claude starts from |
| `sample/` | Worked example: circuit, figure script, generated figure, finished `report.md` |

### Install

You need [uv](https://docs.astral.sh/uv/) (it fetches matplotlib and numpy on demand) and
Claude Code.

Copy the folder into your Claude skills directory. For all projects:

```powershell
Copy-Item -Recurse skills\research-report "$env:USERPROFILE\.claude\skills\research-report"
```

Or for one project only, copy it to `<project>\.claude\skills\research-report`.
Restart Claude Code (or start a new session) and the skill is available as `research-report`.

In Typora, enable math: **Preferences > Markdown > Syntax Support > Inline Math**.

### Use

Ask Claude for a report, naming the skill if you like:

> Simulate `C:\designs\filter.asc`, then write a research report on its AC response using the
> research-report skill. Save it to `C:\reports\filter\report.md`.

Claude copies the template, makes figures into `figures\` with the shared style, and writes the
report. Open `report.md` in Typora and use **File > Export > PDF**.

To change the look for every future report (colors, fonts, size), edit `report_style.py` in the
installed skill folder.

### Try the sample

From the repo root (this runs the bundled circuit through LTspice and redraws the figure):

```powershell
uv run --no-project --with mcp --with numpy --with matplotlib python skills/research-report/sample/make_figures.py
```

Then open `skills/research-report/sample/report.md` in Typora.

`report_style.py` can also be used on its own:

```python
import sys; sys.path.insert(0, r"C:\path\to\research-report")
from report_style import plot_signals, save_fig
fig, ax = plot_signals(t, {"V(out)": vout}, xlabel="Time", xunit="s", ylabel="Voltage", yunit="V")
save_fig(fig, "figures/01-step-response.png")
```
