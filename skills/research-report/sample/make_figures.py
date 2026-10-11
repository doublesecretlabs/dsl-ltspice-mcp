"""Simulates rc_lowpass.cir and draws the report figure with the shared style.

Run from the repo root:
  uv run --no-project --with mcp --with numpy --with matplotlib python skills/research-report/sample/make_figures.py
"""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent))                    # report_style.py
sys.path.insert(0, str(here.parents[2] / "src"))        # dsl_ltspice_mcp (from source)

from dsl_ltspice_mcp import simulate, read_raw
from report_style import plot_signals, save_fig

result = simulate(str(here / "rc_lowpass.cir"))
print(result)
raw = read_raw(str(here / "rc_lowpass.raw"))
t = raw.axis()
fig, ax = plot_signals(t, {"V(out)": raw.signal("V(out)"), "V(in)": raw.signal("V(in)")},
                       xlabel="Time", xunit="s", ylabel="Voltage", yunit="V")
ax.set_xlim(0, 1e-3)   # zoom on the rise (tau = RC = 100 us)
print(save_fig(fig, str(here / "figures" / "01-step-response.png")))
