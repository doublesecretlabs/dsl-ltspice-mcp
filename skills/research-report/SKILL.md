---
name: research-report
description: Use when writing a research report or any document with figures/plots/equations (Typora markdown exported to PDF), including plotting LTspice or measurement data. Enforces one consistent plot style, figure size, and report layout.
---

# Research report (Typora markdown -> PDF)

## Rules
1. **Never write ad hoc plotting code.** Use `report_style.py` in this skill folder
   (`plot_signals`, `save_fig`). Run scripts with
   `uv run --with matplotlib --with numpy python script.py`.
2. **Figures:** full text width, 6.5 in, PNG at 300 dpi, white background, saved to
   `figures/NN-short-name.png` next to the report. Reference with a relative path.
   Do not change the style per figure; if the style needs to change, edit `report_style.py`.
   Zoom or limit axes on the returned `ax` (e.g. `ax.set_xlim(...)`) before `save_fig`.
3. **Captions:** add a bold hand-numbered line under each image:
   `**Figure N:** Description (units, conditions).` Number in order of appearance.
4. **Math:** `$...$` inline, `$$...$$` display, standard LaTeX only. Units upright with a
   thin space: `1.59\,\text{kHz}`. Typora needs Preferences > Markdown > Inline Math enabled.
5. **Layout:** start from `report_template.md` (copy it; keep the headings).
6. **Reproducibility:** keep the plotting script (e.g. `figures/make_figures.py`) and name the
   source simulation file and signals in the Method section.
7. **Data source:** for LTspice, use the dsl-ltspice MCP (`run_simulation`, `read_waveforms`,
   `export_waveforms`) or its Python API (`simulate`, `read_raw`), then pass arrays to
   `plot_signals`. Do not screenshot LTspice. See `sample/make_figures.py`.
8. After saving a figure, open it (Read tool) and check for overlapping labels or clipped
   text before referring to it in the report.
9. Tell the user to export with Typora: File > Export > PDF.
