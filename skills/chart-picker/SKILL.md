---
name: chart-picker
description: Choose which charts to draw from a set of tabular datasets, and pair them into compact two-chart slides with one-line takeaways. Use when deciding how to visualise data for BioMed AI Watch issues (or any data-to-slides task) - given dataset names, columns and rows, it returns chart specs that a renderer draws from the real data.
---

# Chart picker

You are choosing charts for a compact, slide-style newsletter on AI in medicine. Readers skim. Each
slide holds two charts side by side and two one-line takeaways. The goal of every slide is to help a
reader see **where medical AI research is crowded and where it is thin**: novel research gaps.

You never type numbers into a chart. You name a dataset and its columns; the renderer reads the values.
Takeaways may quote numbers only if they appear in the dataset rows you were shown.

## 1. Read each dataset's shape first

| Shape of the data | Best chart | Avoid |
|---|---|---|
| One category column + one count/amount, few categories (<= 6) | `bar` | pie charts |
| One category column + one value, many categories or long labels | `barh` (sorted desc, top <= 10) | vertical bars with rotated labels |
| Categories where only rank matters, many near-ties | `lollipop` | 3-D anything |
| Time (years, months) + one value | `line` (or `bar` for counts per period) | unsorted time axes |
| Time + a count and a percentage of a different scale | `line` with `y2` (dual axis: bars for count, line for share) | two unrelated series on one axis |
| Time or categories + 2-4 comparable series | `grouped_bar` | more than 4 series |
| Parts of a whole across categories | `stacked_barh` | stacking unrelated measures |
| Two categorical dimensions + a value (long format) | `heatmap` | heatmaps with fewer than 3x3 cells |
| Two numeric measures per item (e.g. volume vs maturity) | `scatter` with `label` (and `size`) | scatter with fewer than 4 points |
| Ordered stages that narrow (all -> validated -> trialled) | `funnel` | funnels for unordered categories |

## 2. Prefer charts that expose gaps

Rank candidate charts by how much they reveal about under-studied areas, then by how new the
information is to a reader:
1. Gap structure: heatmaps of subarea x evidence stage, evidence funnels, volume-vs-maturity scatters
   (high volume, low validation = hype; low volume, high need = opportunity).
2. Change over time: is the field growing, and is evidence keeping pace?
3. Where money and attention go this week: grant dollars by funder or institution, sources scanned.
4. Anything from the web-sourced series, if it shows a quantity the PubMed data cannot.

Do not draw the same dataset twice. Do not draw a chart whose data has fewer than 3 rows.

## 3. Pair charts into slides

- Two charts per slide that answer one question together (e.g. "how big" + "how mature").
  A heatmap is wide: give it `"wide": true`, and pair it with one narrow chart or put it alone.
- Slide titles state the question or the finding in at most 8 words.
- Order slides from overview to gaps.

## 4. Write the takeaways

One takeaway per chart, at most 18 words, interpreting rather than describing: say what the reader
should conclude ("RCTs make up 1% of AI work on EHRs; deployment claims outpace trials"), not what the
chart shows ("This chart shows RCTs").

## 5. Labels and style

- Titles at most 45 characters; axis labels short, with units ("AI papers", "$ millions", "% of papers").
- Use `value_format`: `int`, `pct` or `usd_m` so values print readably.
- Sort categorical bars by value (`"sort": "desc"`) unless the categories have a natural order.
- Colour is handled by the renderer (a varied palette), so don't specify colours.
