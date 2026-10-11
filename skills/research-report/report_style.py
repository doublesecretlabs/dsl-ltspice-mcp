"""Shared figure style for research reports (Typora -> PDF, 6.5 in text width).

Usage (run with: uv run --with matplotlib --with numpy python script.py):

    import sys; sys.path.insert(0, r"<this folder>")
    from report_style import plot_signals, save_fig
    fig, ax = plot_signals(t, {"V(out)": vout, "V(in)": vin},
                           xlabel="Time", xunit="s", ylabel="Voltage", yunit="V")
    save_fig(fig, "figures/01-step-response.png")
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import EngFormatter

WIDTH_IN = 6.5          # full text width
HEIGHT_IN = 3.6         # default aspect ~ 1.8:1
DPI = 300

# Colorblind-safe (Okabe-Ito), black first for the primary trace.
COLORS = ["#000000", "#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]

plt.rcParams.update({
    "figure.figsize": (WIDTH_IN, HEIGHT_IN),
    "figure.dpi": 100,
    "savefig.dpi": DPI,
    "savefig.facecolor": "white",
    "savefig.bbox": "tight",
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size": 9,
    "axes.labelsize": 9,
    "axes.titlesize": 10,
    "legend.fontsize": 8,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "axes.prop_cycle": matplotlib.cycler(color=COLORS),
    "axes.grid": True,
    "grid.color": "#CCCCCC",
    "grid.linewidth": 0.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "lines.linewidth": 1.2,
    "legend.frameon": False,
})


def plot_signals(x, signals, xlabel="", xunit="", ylabel="", yunit="",
                 xlog=False, ylog=False, title=None, height=HEIGHT_IN):
    """Plot {name: y_array} against x. Axis ticks use SI prefixes (k, m, u...)."""
    fig, ax = plt.subplots(figsize=(WIDTH_IN, height))
    for name, y in signals.items():
        ax.plot(x, y, label=name)
    ax.xaxis.set_major_formatter(EngFormatter(unit=xunit))
    ax.yaxis.set_major_formatter(EngFormatter(unit=yunit))
    if xlog:
        ax.set_xscale("log")
    if ylog:
        ax.set_yscale("log")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)
    if len(signals) > 1:
        ax.legend()
    return fig, ax


def save_fig(fig, path):
    """Save as PNG at 300 dpi (safe for Typora PDF export)."""
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path
