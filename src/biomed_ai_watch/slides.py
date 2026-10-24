"""16:9 slide images, two charts side by side, drawn from chart specs and real datasets.

A spec names a dataset and its columns (see skills/chart-picker/SKILL.md); values always come from the
dataset rows, never from the spec. Sized to stay legible when an email client scales them to ~600px.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

# A varied palette, deliberately not the website's orange: easy on the eye and distinct side by side.
PALETTE = ["#2a9d8f", "#e76f51", "#3d5a80", "#e9c46a", "#8e6bbf", "#7fb069", "#4ea8de", "#f4a261"]
HEATMAP = "YlGnBu"  # pale yellow = thin evidence, deep blue = well studied
INK, GREY = "#1d2327", "#7a848b"
TYPES = ["bar", "barh", "lollipop", "line", "grouped_bar", "stacked_barh", "heatmap", "scatter", "funnel"]


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 13, "axes.titlesize": 15,
                         "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.labelsize": 12,
                         "xtick.labelsize": 11, "ytick.labelsize": 11, "axes.edgecolor": "#c9ced2",
                         "axes.spines.top": False, "axes.spines.right": False, "text.color": INK})
    return plt


def fmt(v, kind: str = "int") -> str:
    if v is None:
        return ""
    if kind == "pct":
        return f"{v:.0f}%" if abs(v) >= 1 or v == 0 else f"{v:.1f}%"
    if kind == "usd_m":
        return f"${v / 1e6:.1f}M"
    return f"{v:,.0f}" if abs(v) >= 10 or float(v).is_integer() else f"{v:.1f}"


def _short(s, n=22) -> str:
    return textwrap.shorten(str(s), n, placeholder="…")


def _nice(col: str) -> str:
    return col.replace("_pct", " (%)").replace("_usd", " ($)").replace("_", " ").capitalize()


def _rows(spec: dict, data: dict) -> list[dict]:
    rows = list(data["rows"])
    y = spec["y"][0] if spec.get("y") else None
    if y and spec.get("sort") in ("desc", "asc"):
        rows.sort(key=lambda r: r.get(y) or 0, reverse=spec["sort"] == "desc")
    if spec.get("top"):
        rows = rows[: spec["top"]]
    return rows


def _scale(spec: dict, v):
    return v / 1e6 if spec.get("value_format") == "usd_m" else v


def chart(spec: dict, data: dict, k: int):
    """A panel for slide(): draws `spec` from `data`, with palette colours offset by k."""
    c = lambda i: PALETTE[(k + i) % len(PALETTE)]
    vf = spec.get("value_format", "int")

    def draw(fig, ax):
        t, rows = spec["type"], _rows(spec, data)
        x, ys = spec.get("x"), spec.get("y") or []
        ax.set_title(textwrap.fill(spec.get("title", ""), 36), fontsize=14)

        if t in ("bar", "barh", "lollipop", "funnel"):
            y = ys[0]
            if t != "funnel":  # an empty bar says nothing
                rows = [r for r in rows if r.get(y)]
            if t == "funnel":
                rows = sorted(rows, key=lambda r: -(r.get(y) or 0))
            cats = [_short(r[x]) for r in rows]
            vals = [_scale(spec, r.get(y) or 0) for r in rows]
            if t == "bar":
                cats = [textwrap.fill(str(r[x]), 12, max_lines=2, placeholder="…") for r in rows]
                bars = ax.bar(cats, vals, color=[c(i) for i in range(len(vals))])
                for b, r in zip(bars, rows):
                    ax.text(b.get_x() + b.get_width() / 2, b.get_height(), fmt(r.get(y), vf), ha="center",
                            va="bottom", fontsize=10)
                if len(cats) > 5:
                    ax.tick_params(axis="x", rotation=30)
                ax.set_ylabel(spec.get("y_label", ""))
            else:
                first = rows[0].get(y) if t == "funnel" and rows else None
                cats, vals, rows = cats[::-1], vals[::-1], rows[::-1]
                if t == "lollipop":
                    ax.hlines(cats, 0, vals, color=c(0), linewidth=2.5)
                    ax.scatter(vals, cats, color=c(1), s=90, zorder=3)
                else:
                    ax.barh(cats, vals, color=[c(i) for i in range(len(vals))][::-1])
                top = max(vals) if vals else 1
                for i, (v, r) in enumerate(zip(vals, rows)):
                    label = fmt(r.get(y), vf)
                    if first and r.get(y) != first:
                        label += f" ({100 * (r.get(y) or 0) / first:.0f}%)"
                    ax.text(v + (top or 1) * 0.02, i, label, va="center", fontsize=11)
                ax.set_xlim(0, (top or 1) * 1.4)
                ax.set_xticks([])
                ax.spines["bottom"].set_visible(False)

        elif t in ("line", "grouped_bar"):
            xs = [str(r[x]) for r in rows]
            if t == "line":
                y2 = spec.get("y2")
                if y2:  # bars for the count, line for the share on its own axis
                    ax.bar(xs, [r.get(ys[0]) or 0 for r in rows], color=c(0))
                    a2 = ax.twinx()
                    a2.plot(xs, [r.get(y2) or 0 for r in rows], color=c(1), marker="o", linewidth=2.5)
                    a2.set_ylim(bottom=0)
                    a2.spines["right"].set_visible(True)
                    a2.set_ylabel(_nice(y2), color=c(1))
                else:
                    for i, y in enumerate(ys):
                        ax.plot(xs, [r.get(y) for r in rows], marker="o", linewidth=2.5, color=c(i),
                                label=_nice(y))
            else:
                w = 0.8 / max(len(ys), 1)
                for i, y in enumerate(ys):
                    ax.bar([j + i * w for j in range(len(xs))], [r.get(y) or 0 for r in rows], width=w,
                           color=c(i), label=_nice(y))
                ax.set_xticks([j + 0.4 - w / 2 for j in range(len(xs))], xs)
            if len(ys) > 1:
                ax.legend(frameon=False, fontsize=10)
            if len(xs) > 6:
                ax.tick_params(axis="x", rotation=35)
            ax.set_ylabel(spec.get("y_label", ""))
            ax.set_xlabel(spec.get("x_label", ""))

        elif t == "stacked_barh":
            cats = [_short(r[x]) for r in rows][::-1]
            left = [0.0] * len(cats)
            for i, y in enumerate(ys):
                vals = [r.get(y) or 0 for r in rows][::-1]
                ax.barh(cats, vals, left=left, color=c(i), label=_nice(y))
                left = [a + b for a, b in zip(left, vals)]
            ax.legend(frameon=False, fontsize=10, loc="lower right")
            ax.set_xlabel(spec.get("x_label", ""))

        elif t == "heatmap":
            row_key, val = spec["label"], ys[0]
            row_names = list(dict.fromkeys(r[row_key] for r in data["rows"]))
            col_names = list(dict.fromkeys(r[x] for r in data["rows"]))
            cell = {(r[row_key], r[x]): r.get(val) or 0 for r in data["rows"]}
            grid = [[cell.get((rn, cn), 0) for cn in col_names] for rn in row_names]
            vmax = max((v for row in grid for v in row), default=1) or 1
            if vf == "pct":  # cap so one crowded column doesn't wash out the thin ones, which are the point
                vmax = min(vmax, 25)
            ax.imshow(grid, cmap=HEATMAP, aspect="auto", vmin=0, vmax=vmax)
            ax.xaxis.tick_top()
            ax.set_xticks(range(len(col_names)), [textwrap.fill(str(n), 11) for n in col_names], fontsize=10)
            ax.set_yticks(range(len(row_names)), [_short(n) for n in row_names], fontsize=11)
            ax.tick_params(length=0)
            for s in ax.spines.values():
                s.set_visible(False)
            for i, row in enumerate(grid):
                for j, v in enumerate(row):
                    ax.text(j, i, fmt(v, vf), ha="center", va="center", fontsize=10,
                            color="white" if v > vmax * 0.6 else INK)
            ax.set_xlabel("Pale cells = little evidence: candidate gaps", fontsize=10, color=GREY)

        elif t == "scatter":
            y, label, size = ys[0], spec.get("label"), spec.get("size")
            xs, yv = [r.get(x) or 0 for r in rows], [r.get(y) or 0 for r in rows]
            big = (max((r.get(size) or 0 for r in rows), default=1) or 1) if size else 1
            sizes = [80 + 900 * (r.get(size) or 0) / big for r in rows] if size else 140
            ax.scatter(xs, yv, s=sizes, c=[c(i) for i in range(len(rows))], alpha=.85, edgecolor="white")
            if label:
                # Alternate label sides by height so neighbouring points don't stack their labels.
                order = sorted(range(len(rows)), key=lambda i: yv[i])
                for n, i in enumerate(order):
                    ax.annotate(_short(rows[i][label], 18), (xs[i], yv[i]), xytext=(9, 9 if n % 2 else -15),
                                textcoords="offset points", fontsize=10)
            ax.set_xlabel(spec.get("x_label") or x)
            ax.set_ylabel(spec.get("y_label") or y)
    return draw


def slide(path: Path, title: str, panels: list, widths: tuple = (1, 1), source: str = "") -> str:
    """panels: callables (fig, ax) -> None, drawn left to right. Returns the file name."""
    plt = _plt()
    fig = plt.figure(figsize=(11, 6.2), dpi=145)
    fig.patch.set_facecolor("white")
    fig.text(0.03, 0.95, title, fontsize=19, fontweight="bold", color=INK, va="top")
    fig.add_artist(plt.Line2D([0.03, 0.12], [0.885, 0.885], color=PALETTE[0], linewidth=4))
    grid = fig.add_gridspec(1, len(panels), width_ratios=widths[: len(panels)], left=0.07, right=0.97,
                            top=0.72, bottom=0.15, wspace=0.6)
    for k, draw in enumerate(panels):
        draw(fig, fig.add_subplot(grid[0, k]))
    if source:
        fig.text(0.03, 0.025, source[:200], fontsize=9, color=GREY)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)
    return path.name
