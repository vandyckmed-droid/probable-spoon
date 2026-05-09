"""Mobile-first HTML + CSV renderer for the ranked output.

Progressive disclosure via native <details>:
  - collapsed row: rank, ticker, company, sector, composite (+pill colour)
  - expanded row: per-factor z-score, contribution to composite, narrative
  - methodology drawer at bottom: formulas, residualisation, data source, cache

No JavaScript — works in iOS Quick Look, Safari, and desktop browsers alike.
"""
import re
from pathlib import Path

import pandas as pd

import snapshots


_CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
:root {
  --bg: #000000;
  --bg-elev: #0e0e10;
  --bg-card: #131316;
  --line: #232326;
  --text: #ececec;
  --text-strong: #ffffff;
  --text-muted: #8a8a8f;
  --text-faint: #5a5a5e;
  --accent-up: #34d399;
  --accent-up-soft: rgba(52, 211, 153, 0.18);
  --accent-down: #f87171;
  --accent-down-soft: rgba(248, 113, 113, 0.18);
  --tabular: ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Consolas,
             'Roboto Mono', monospace;
}
body {
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Inter',
               'Segoe UI', sans-serif;
  font-size: 15px; line-height: 1.4;
  color: var(--text); background: var(--bg);
  padding: 16px 14px 40px;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
.page-title {
  font-size: 11px; font-weight: 700;
  letter-spacing: 0.18em;
  color: var(--text-muted);
  text-transform: uppercase;
  text-align: center;
  margin: 4px 0 18px;
  user-select: none;
}
.header {
  font-size: 12px; line-height: 1.5;
  color: var(--text-muted); margin-bottom: 14px;
  user-select: none; -webkit-user-select: none;
  text-align: center;
}
.header b { color: var(--text); font-weight: 600; }
.header select {
  font-family: var(--tabular); font-size: 12px;
  padding: 3px 10px; margin-left: 4px;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: var(--bg-elev); color: var(--text);
}

/* Sticky sort bar */
.sticky-top {
  position: sticky; top: 0; z-index: 10;
  margin: 0 -14px 12px;
  background: rgba(0,0,0,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--line);
}
.toolbar {
  display: flex; gap: 4px; flex-wrap: wrap;
  padding: 8px 14px 8px;
  align-items: center;
  user-select: none; -webkit-user-select: none;
}
.toolbar-label {
  font-size: 10px; font-weight: 600;
  color: var(--text-faint);
  text-transform: uppercase; letter-spacing: 0.12em;
  margin-right: 6px;
}

/* Segmented controls — minimal, low-contrast inactive, glow on active */
.sort-radio { position: absolute; opacity: 0; pointer-events: none; }
.sort-btn {
  font: inherit; font-size: 12px; font-weight: 500;
  background: transparent; color: var(--text-muted);
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 4px 10px;
  cursor: pointer; user-select: none; -webkit-user-select: none;
  transition: color 0.12s ease, background 0.12s ease, box-shadow 0.12s ease;
}
.sort-btn:hover { color: var(--text); }

#sort-composite:checked ~ .sticky-top label[for="sort-composite"],
#sort-cash:checked      ~ .sticky-top label[for="sort-cash"],
#sort-sector:checked    ~ .sticky-top label[for="sort-sector"],
#sort-ticker:checked    ~ .sticky-top label[for="sort-ticker"],
#sort-mktcap:checked    ~ .sticky-top label[for="sort-mktcap"],
#sort-momentum:checked  ~ .sticky-top label[for="sort-momentum"],
#sort-quality:checked   ~ .sticky-top label[for="sort-quality"],
#sort-value:checked     ~ .sticky-top label[for="sort-value"] {
  background: rgba(255,255,255,0.08);
  color: var(--text-strong);
  border-color: rgba(255,255,255,0.12);
  box-shadow: 0 0 18px rgba(255,255,255,0.06);
}

/* CSS-only sort */
#sort-composite:checked ~ .section .list .row { order: var(--r-c, 0); }
#sort-cash:checked      ~ .section .list .row { order: var(--r-cash, 0); }
#sort-sector:checked    ~ .section .list .row { order: var(--r-sec, 0); }
#sort-ticker:checked    ~ .section .list .row { order: var(--r-tick, 0); }
#sort-mktcap:checked    ~ .section .list .row { order: var(--r-mkt, 0); }
#sort-momentum:checked  ~ .section .list .row { order: var(--r-mom, 0); }
#sort-quality:checked   ~ .section .list .row { order: var(--r-qual, 0); }
#sort-value:checked     ~ .section .list .row { order: var(--r-val, 0); }

/* Show-top-N toggle */
#show-25:checked ~ .section .list .row { display: none; }
#show-50:checked ~ .section .list .row { display: none; }
#show-25:checked ~ .section .list .row.in-25 { display: block; }
#show-50:checked ~ .section .list .row.in-50 { display: block; }
.sub-25, .sub-50, .sub-100 { display: none; }
#show-25:checked  ~ .section .sub-25 { display: inline; }
#show-50:checked  ~ .section .sub-50 { display: inline; }
#show-100:checked ~ .section .sub-100 { display: inline; }
#show-25:checked  ~ .section label[for="show-25"],
#show-50:checked  ~ .section label[for="show-50"],
#show-100:checked ~ .section label[for="show-100"] {
  background: rgba(255,255,255,0.08);
  color: var(--text-strong);
  border-color: rgba(255,255,255,0.12);
  box-shadow: 0 0 18px rgba(255,255,255,0.06);
}

/* Weighting toggle: hide all three cash variants by default, reveal active */
.cm-eq, .cm-ivp, .cm-hrp,
.wl-eq, .wl-ivp, .wl-hrp { display: none; }
#wt-equal:checked ~ .section .cm-eq,
#wt-equal:checked ~ .section .wl-eq { display: block; }
#wt-ivp:checked   ~ .section .cm-ivp,
#wt-ivp:checked   ~ .section .wl-ivp { display: block; }
#wt-hrp:checked   ~ .section .cm-hrp,
#wt-hrp:checked   ~ .section .wl-hrp { display: block; }
#wt-equal:checked ~ .section label[for="wt-equal"],
#wt-ivp:checked   ~ .section label[for="wt-ivp"],
#wt-hrp:checked   ~ .section label[for="wt-hrp"] {
  background: rgba(255,255,255,0.08);
  color: var(--text-strong);
  border-color: rgba(255,255,255,0.12);
  box-shadow: 0 0 18px rgba(255,255,255,0.06);
}

.list { display: flex; flex-direction: column; gap: 8px; }

/* Top-level section cards */
details.section {
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 14px;
  margin-bottom: 12px;
  overflow: hidden;
}
details.section > summary {
  list-style: none; cursor: pointer;
  padding: 14px 16px;
  display: flex; align-items: center; justify-content: space-between;
  user-select: none; -webkit-user-select: none;
}
details.section > summary::-webkit-details-marker { display: none; }
details.section > summary::marker { display: none; }
details.section > summary::after {
  content: ''; display: inline-block;
  border: solid var(--text-faint); border-width: 0 2px 2px 0;
  padding: 4px;
  transform: rotate(45deg);
  margin-left: 12px; flex: 0 0 auto;
  transition: transform 0.15s;
}
details.section[open] > summary::after { transform: rotate(-135deg); }
.section-head { display: flex; flex-direction: column; flex: 1 1 auto; min-width: 0; }
.section-title {
  font-size: 16px; font-weight: 600;
  color: var(--text-strong);
  letter-spacing: -0.01em;
}
.section-subtitle {
  font-size: 12px; color: var(--text-muted);
  margin-top: 3px;
}
.section-body { padding: 0 14px 16px; }

/* Inline weighting / show toggles inside a section body */
.weighting-toggle {
  display: inline-flex; gap: 2px;
  align-items: center;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 3px;
  margin: 6px 0 10px;
  user-select: none; -webkit-user-select: none;
}
.weighting-toggle .toolbar-label {
  margin: 0 8px 0 6px;
  color: var(--text-faint);
}
.weighting-toggle .sort-btn {
  border-radius: 6px;
  padding: 4px 12px;
  border-color: transparent;
}

/* Column-labels row inside section body */
.section-body .list-header {
  padding: 6px 4px 10px;
  display: grid;
  grid-template-columns: 24px 1fr 56px 70px;
  column-gap: 10px;
  font-size: 10px; font-weight: 600;
  color: var(--text-faint);
  text-transform: uppercase; letter-spacing: 0.12em;
  user-select: none; -webkit-user-select: none;
}
.section-body .list-header .col-rank { text-align: center; grid-column: 1; }
.section-body .list-header .col-name { grid-column: 2; }
.section-body .list-header .col-comp { text-align: right; grid-column: 4; }

/* Backtest table */
.bt-table { display: flex; flex-direction: column; font-size: 13px; }
.bt-row {
  display: grid;
  grid-template-columns: 1.2fr repeat(3, 1fr);
  column-gap: 8px;
  padding: 8px 4px;
  align-items: baseline;
  border-bottom: 1px solid var(--line);
}
.bt-row:last-child { border-bottom: none; }
.bt-row.bt-head {
  color: var(--text-faint); font-size: 10px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.12em;
}
.bt-label { color: var(--text); font-weight: 500; }
.bt-cell {
  font-family: var(--tabular);
  font-variant-numeric: tabular-nums; text-align: right;
  color: var(--text);
}
.bt-cell.ret { font-weight: 600; color: var(--text-strong); }
.bt-cell.dd { color: var(--accent-down); }
.bt-caveat {
  font-size: 12px; line-height: 1.55;
  color: var(--text-muted); margin: 14px 0 0;
}

/* Methodology */
.methodology-body h3 {
  font-size: 12px; font-weight: 600;
  margin: 16px 0 6px; color: var(--text-strong);
  text-transform: uppercase; letter-spacing: 0.08em;
}
.methodology-body h3:first-child { margin-top: 4px; }
.methodology-body p {
  font-size: 13px; line-height: 1.6;
  color: var(--text-muted); margin: 0 0 10px;
}

/* Stock row card */
details.row {
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
details.row[open] {
  border-color: rgba(52, 211, 153, 0.35);
  box-shadow: 0 0 30px rgba(52, 211, 153, 0.10);
}
details.row > summary {
  list-style: none; cursor: pointer;
  padding: 12px 14px;
  display: grid;
  grid-template-columns: 24px 1fr 56px 70px;
  grid-template-rows: auto auto;
  column-gap: 10px;
  row-gap: 3px;
  align-items: center;
}
details.row > summary::-webkit-details-marker { display: none; }
details.row > summary::marker { display: none; }

.rank {
  grid-row: 1 / span 2; grid-column: 1;
  font-family: var(--tabular);
  font-size: 12px; color: var(--text-faint);
  font-variant-numeric: tabular-nums; text-align: center;
}

.ticker {
  grid-row: 1; grid-column: 2;
  font-weight: 600; font-size: 16px;
  letter-spacing: -0.01em;
  color: var(--text-strong);
}

/* Composite pill — outlined bezel with soft glow */
.pill {
  grid-row: 1; grid-column: 4;
  justify-self: end;
  font-family: var(--tabular);
  font-variant-numeric: tabular-nums;
  font-weight: 600; font-size: 13px;
  padding: 3px 10px;
  border-radius: 999px;
  background: transparent;
  border: 1px solid;
  white-space: nowrap;
  letter-spacing: -0.01em;
}
.pill.up-strong {
  color: var(--accent-up); border-color: var(--accent-up);
  box-shadow: 0 0 14px rgba(52,211,153,0.30);
  background: rgba(52,211,153,0.05);
}
.pill.up-light {
  color: var(--accent-up); border-color: rgba(52,211,153,0.55);
  background: rgba(52,211,153,0.04);
}
.pill.down-strong {
  color: var(--accent-down); border-color: var(--accent-down);
  box-shadow: 0 0 14px rgba(248,113,113,0.28);
  background: rgba(248,113,113,0.05);
}
.pill.down-light {
  color: var(--accent-down); border-color: rgba(248,113,113,0.55);
  background: rgba(248,113,113,0.04);
}
.pill.flat {
  color: var(--text-muted); border-color: var(--line);
}

.cash-mini {
  grid-row: 2; grid-column: 4;
  justify-self: end; text-align: right;
  font-family: var(--tabular);
  font-size: 11px; color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  letter-spacing: 0;
}

/* Mini sparkline next to each row */
.mini-spark-cell {
  grid-row: 1 / span 2; grid-column: 3;
  align-self: center; justify-self: center;
  display: flex; flex-direction: column; align-items: center;
  gap: 1px;
}
svg.mini-spark {
  display: block;
  width: 56px; height: 22px;
  opacity: 0.9;
}
.mini-pct {
  font-family: var(--tabular);
  font-size: 10px; font-weight: 600;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}
.mini-pct.up   { color: var(--accent-up); }
.mini-pct.down { color: var(--accent-down); }

.meta {
  grid-row: 2; grid-column: 2;
  font-size: 12px; color: var(--text-muted);
  display: flex; align-items: baseline; gap: 5px;
  min-width: 0;
}
.meta .name {
  flex: 0 1 auto; min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--text);
}
.meta .dot { flex: 0 0 auto; opacity: 0.45; }
.meta .sector { flex: 0 0 auto; white-space: nowrap; }
.meta .tags { flex: 0 0 auto; display: inline-flex; gap: 3px; margin-left: 3px; }
.meta .tag {
  font-size: 9px; font-weight: 600;
  letter-spacing: 0.08em;
  padding: 1px 5px; border-radius: 3px;
  background: rgba(255,255,255,0.06);
  color: var(--text-muted);
  border: 1px solid var(--line);
  text-transform: uppercase;
}

.full-name {
  font-size: 12px; color: var(--text-muted);
  margin-top: 4px;
  letter-spacing: -0.01em;
}

.expanded { padding: 6px 14px 16px; }
.expanded .divider {
  border-top: 1px solid var(--line);
  margin: 0 0 14px;
}

/* Drawer residual-return chart + 21d pullback indicator */
.resid-block {
  margin: 6px 0 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px 8px;
  background: rgba(255,255,255,0.015);
}
.resid-head {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 8px;
}
.resid-title { display: flex; align-items: baseline; gap: 6px; }
.resid-label {
  font-size: 10px; font-weight: 600;
  color: var(--text-faint);
  text-transform: uppercase; letter-spacing: 0.12em;
}
.resid-axis {
  font-size: 10px; color: var(--text-faint);
}
.resid-readout {
  display: flex; align-items: baseline; gap: 6px;
  font-family: var(--tabular);
  font-variant-numeric: tabular-nums;
}
.resid-value {
  font-size: 16px; font-weight: 700;
  letter-spacing: -0.01em;
}
.resid-sigma { font-size: 11px; }
.resid-value.up,  .resid-sigma.up   { color: var(--accent-up); }
.resid-value.down, .resid-sigma.down { color: var(--accent-down); }

.resid-chart-wrap {
  position: relative;
  height: 110px;
  color: var(--text-faint);
}
svg.resid-chart {
  display: block;
  width: 100%; height: 100%;
}
.resid-axis-tl, .resid-axis-tr,
.resid-axis-bl, .resid-axis-br,
.resid-axis-zero {
  position: absolute;
  font-family: var(--tabular);
  font-size: 10px;
  color: var(--text-faint);
  pointer-events: none;
  font-variant-numeric: tabular-nums;
}
.resid-axis-tl { top: 2px; left: 2px; }
.resid-axis-tr { top: 2px; right: 2px; }
.resid-axis-bl { bottom: 2px; left: 2px; }
.resid-axis-br { bottom: 2px; right: 2px; }
.resid-axis-zero {
  top: calc(50% - 7px);
  left: 2px;
  opacity: 0.5;
}
.resid-desc {
  margin: 6px 0 0;
  font-size: 11px; color: var(--text-faint);
}
/* Smoothing tag — low in the visual hierarchy on purpose. */
.resid-ema {
  font-family: var(--tabular);
  font-variant-numeric: tabular-nums;
  font-size: 10px;
  letter-spacing: 0;
  opacity: 0.65;
  margin-left: 2px;
}

/* 21D Pullback indicator */
.pullback-block {
  margin: 0 0 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  background: rgba(255,255,255,0.015);
}
.pullback-head {
  display: flex; justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 10px;
}
.pullback-title { display: flex; align-items: baseline; gap: 6px; }
.pullback-label {
  font-size: 10px; font-weight: 600;
  color: var(--text-faint);
  text-transform: uppercase; letter-spacing: 0.12em;
}
.pullback-axis { font-size: 10px; color: var(--text-faint); }
.pullback-readout {
  display: flex; flex-direction: column; align-items: flex-end;
  gap: 1px;
  font-family: var(--tabular);
  font-variant-numeric: tabular-nums;
}
.pullback-z {
  font-size: 14px; font-weight: 700;
  letter-spacing: -0.01em;
}
.pullback-z.up   { color: var(--accent-up); }
.pullback-z.down { color: var(--accent-down); }
.pullback-status {
  font-size: 11px; font-weight: 600;
}
.pullback-status.up      { color: var(--accent-up); }
.pullback-status.down    { color: var(--accent-down); }
.pullback-status.neutral { color: var(--text-muted); }

.pullback-bar {
  position: relative;
  height: 10px; border-radius: 6px;
  background: linear-gradient(
    to right,
    #c0392b 0%,
    #e89a3a 30%,
    #d4c84a 50%,
    #6fb86b 70%,
    #2e9e60 100%
  );
  margin-bottom: 6px;
}
.pullback-marker {
  position: absolute;
  top: -3px;
  width: 14px; height: 14px;
  border-radius: 50%;
  background: var(--bg);
  border: 2px solid var(--text);
  transform: translateX(-50%);
  box-shadow: 0 1px 4px rgba(0,0,0,0.5);
}
.pullback-legend {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  font-size: 9px; line-height: 1.3;
  text-align: center;
  color: var(--text-faint);
  text-transform: uppercase; letter-spacing: 0.06em;
}
.pullback-leg-l { text-align: left;  color: var(--accent-down); }
.pullback-leg-c { text-align: center; }
.pullback-leg-r { text-align: right; color: var(--accent-up); }
.pullback-legend b { font-weight: 700; letter-spacing: 0.08em; }

/* Factor block in drawer */
.factors {
  display: grid;
  grid-template-columns: 1fr auto auto;
  column-gap: 22px; row-gap: 9px;
  font-size: 13px;
  margin-top: 4px;
}
.factors .label { color: var(--text); }
.factors .z, .factors .contrib {
  font-family: var(--tabular);
  font-variant-numeric: tabular-nums; text-align: right;
}
.factors .z { color: var(--text-muted); }
.factors .contrib { color: var(--text); font-weight: 500; }
.factors .contrib .w {
  color: var(--text-faint); font-weight: 400; margin-left: 6px;
}
/* Z-score colour buckets — same thresholds as the composite pill so the
   factor σ readouts and the pill stay in sync visually. */
.factors .z.up-strong   { color: var(--accent-up); }
.factors .z.up-light    { color: var(--accent-up); opacity: 0.78; }
.factors .z.down-strong { color: var(--accent-down); }
.factors .z.down-light  { color: var(--accent-down); opacity: 0.78; }
.factors .z.flat        { color: var(--text-muted); }
.factors .total .label,
.factors .total .contrib {
  font-weight: 700;
  font-size: 17px;
  color: var(--text-strong);
  letter-spacing: -0.01em;
}
.factors .total .contrib.up-strong   { color: var(--accent-up); }
.factors .total .contrib.up-light    { color: var(--accent-up); opacity: 0.85; }
.factors .total .contrib.down-strong { color: var(--accent-down); }
.factors .total .contrib.down-light  { color: var(--accent-down); opacity: 0.85; }
.factors .total .label,
.factors .total .z,
.factors .total .contrib {
  border-top: 1px solid var(--line);
  padding-top: 10px; margin-top: 4px;
}
.factors .muted { color: var(--text-faint); font-weight: 400; }

.explain {
  font-size: 13px; line-height: 1.65;
  color: var(--text-muted);
  margin-top: 18px;
  letter-spacing: 0.005em;
}
.cash-line {
  font-family: var(--tabular);
  font-size: 12px; color: var(--text-muted);
  margin-top: 14px;
  font-variant-numeric: tabular-nums;
}
.cash-line b { font-weight: 600; color: var(--text-strong); }

/* Diagnostic Expectations row (NOT in composite — visually separated). */
/* Universe card — descriptive stats + filter status */
.uni-h {
  font-size: 11px; font-weight: 600;
  color: var(--text-faint);
  text-transform: uppercase; letter-spacing: 0.08em;
  margin: 14px 0 6px;
}
.uni-h:first-child { margin-top: 0; }
.uni-table {
  display: grid;
  grid-template-columns: 1fr auto 56px;
  column-gap: 12px; row-gap: 4px;
  font-size: 13px;
}
.uni-row {
  display: contents;
}
.uni-label { color: var(--text-strong); }
.uni-count {
  font-family: var(--tabular);
  font-variant-numeric: tabular-nums;
  text-align: right;
  color: var(--text-strong);
}
.uni-pct {
  font-family: var(--tabular);
  font-variant-numeric: tabular-nums;
  text-align: right;
  color: var(--text-muted);
}
.uni-stats {
  font-size: 12px;
  color: var(--text-muted);
  margin: 4px 0 8px;
}
.uni-stats b { color: var(--text-strong); font-weight: 600; }
.uni-empty { color: var(--text-faint); font-style: italic; }
.uni-filters {
  display: grid;
  grid-template-columns: 1fr auto auto;
  column-gap: 12px; row-gap: 6px;
  font-size: 12px;
}
.uni-filter-row { display: contents; }
.uni-filter-state {
  font-family: var(--tabular);
  font-size: 11px; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase;
  padding: 1px 7px; border-radius: 4px;
  border: 1px solid var(--line);
}
.uni-filter-state.on  { color: var(--accent-up); border-color: var(--accent-up); }
.uni-filter-state.off { color: var(--text-faint); }
.uni-filter-cli {
  font-family: var(--tabular);
  font-size: 11px; color: var(--text-faint);
}
.uni-collapse {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px dashed var(--line);
}
.uni-collapse > summary {
  cursor: pointer; list-style: none;
  font-size: 11px; font-weight: 600;
  color: var(--text-faint);
  text-transform: uppercase; letter-spacing: 0.08em;
}
.uni-collapse > summary::-webkit-details-marker { display: none; }
.uni-collapse > summary::before {
  content: '\\203A'; color: var(--text-faint);
  margin-right: 6px; display: inline-block;
  transition: transform 0.15s;
}
.uni-collapse[open] > summary::before { transform: rotate(90deg); }
.uni-industries { margin-top: 10px; font-size: 12px; }

/* Drill-down pair lists used by the Unclassified / Hygiene drawers. */
.uni-collapse-note {
  font-size: 11px; color: var(--text-faint);
  font-style: italic;
  margin: 8px 0 10px;
  line-height: 1.5;
}
.uni-pair-list {
  display: flex; flex-direction: column;
  gap: 4px;
  font-size: 12px;
  margin-top: 6px;
}
.uni-pair-row {
  display: grid;
  grid-template-columns: 80px 1fr;
  column-gap: 12px;
  padding: 2px 0;
  border-bottom: 1px solid var(--line);
  font-family: var(--tabular);
}
.uni-pair-row:last-child { border-bottom: none; }
.uni-pair-ticker {
  color: var(--text-strong);
  font-weight: 600;
}
.uni-pair-name {
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.uni-hyg-group {
  margin: 12px 0;
  padding-top: 10px;
  border-top: 1px dashed var(--line);
}
.uni-hyg-group:first-of-type {
  border-top: none;
  margin-top: 6px;
  padding-top: 0;
}
.uni-hyg-label {
  font-size: 11px; font-weight: 700;
  letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--text-strong);
  margin-bottom: 6px;
}
.uni-hyg-count {
  font-weight: 500;
  color: var(--text-faint);
  letter-spacing: 0;
}

.exp-row {
  display: flex; align-items: center; gap: 10px;
  margin-top: 14px; padding-top: 12px;
  border-top: 1px dashed var(--line);
  font-size: 12px;
}
.exp-label { color: var(--text-muted); font-weight: 500; }
.exp-value {
  font-family: var(--tabular);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.exp-value.up   { color: var(--accent-up); }
.exp-value.down { color: var(--accent-down); }
.exp-tag {
  margin-left: auto;
  font-size: 10px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--text-faint);
  padding: 2px 7px; border: 1px solid var(--line);
  border-radius: 4px;
}

/* Snapshot archive — small status drawer at the bottom of the page */
.snap-archive {
  margin-top: 18px;
  padding: 8px 12px;
  border-top: 1px dashed var(--line);
  font-size: 11px;
  color: var(--text-faint);
}
.snap-archive > summary {
  cursor: pointer; list-style: none;
  font-weight: 500;
  letter-spacing: 0.02em;
  user-select: none; -webkit-user-select: none;
}
.snap-archive > summary::-webkit-details-marker { display: none; }
.snap-archive > summary::before {
  content: '\\203A'; color: var(--text-faint);
  margin-right: 6px; display: inline-block;
  transition: transform 0.15s;
}
.snap-archive[open] > summary::before { transform: rotate(90deg); }
.snap-note {
  font-size: 11px; color: var(--text-faint);
  margin: 8px 0 6px; font-style: italic;
}
.snap-empty {
  font-size: 11px; color: var(--text-faint);
  margin: 8px 0; font-style: italic;
}
.snap-empty code, .snap-archive code {
  font-family: var(--tabular);
  background: var(--bg-elev);
  padding: 1px 4px; border-radius: 3px;
}
.snap-list {
  display: flex; flex-direction: column;
  gap: 2px;
  font-family: var(--tabular);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  margin-top: 6px;
}
.snap-row {
  display: grid;
  grid-template-columns: auto auto 1fr;
  column-gap: 12px;
  padding: 2px 0;
}
.snap-ts { color: var(--text-muted); }
.snap-ver {
  color: var(--text-faint);
  text-transform: lowercase;
}
.snap-meta { color: var(--text-faint); text-align: right; }
"""


# Suffix must be preceded by whitespace or a comma so we never chew the inside
# of a word — "Equinor ASA" must NOT match the S.A. pattern, etc. Holdings /
# Group are intentionally NOT in this list because they're often substantive.
_SUFFIX_PATTERNS = [
    r"[\s,]+Incorporated$",
    r"[\s,]+Inc\.?$",
    r"[\s,]+Corporation$",
    r"[\s,]+Corp\.?$",
    r"[\s,]+Company$",
    r"[\s,]+Co\.?$",
    r"[\s,]+Limited$",
    r"[\s,]+Ltd\.?$",
    r"[\s,]+plc$",
    r"[\s,]+PLC$",
    r"[\s,]+N\.?V\.?$",
    r"[\s,]+S\.?A\.?$",
    r"[\s,]+S\.?E\.?$",
    r"[\s,]+A\.?G\.?$",
    r"[\s,]+ASA$",
    r"[\s,]+AB$",
    r"[\s,]+GmbH$",
]
_SUFFIX_RE = [re.compile(p, re.IGNORECASE) for p in _SUFFIX_PATTERNS]


def _short_name(name: str) -> str:
    """Strip common corporate suffixes so collapsed rows scan cleanly."""
    if not name:
        return name
    out = name
    # Apply repeatedly to peel compound suffixes ("Company Limited", "Holdings Inc").
    for _ in range(4):
        before = out
        for rx in _SUFFIX_RE:
            out = rx.sub("", out)
        if out == before:
            break
    out = out.rstrip(",.- ").strip()
    return out or name


_JS = """<script>
(function () {
  var cashSelect = document.getElementById('cashSelect');
  if (!cashSelect) return;
  var SCALE = { eq: __SCALE_EQ__, ivp: __SCALE_IVP__, hrp: __SCALE_HRP__ };
  var rows = document.querySelectorAll('details.row');
  function updateOne(r, baseCash) {
    var weights = {
      eq:  parseFloat(r.dataset.eq) || 0,
      ivp: parseFloat(r.dataset.ivp) || 0,
      hrp: parseFloat(r.dataset.hrp) || 0
    };
    ['eq', 'ivp', 'hrp'].forEach(function (k) {
      var w = weights[k];
      var effective = baseCash * SCALE[k];
      var amt = w > 0 ? Math.round(w * effective) : 0;
      var mini = r.querySelector('.cm-' + k);
      if (mini) mini.textContent = amt > 0 ? '$' + amt.toLocaleString() : '';
      var line = r.querySelector('.wl-' + k);
      if (line) {
        if (w > 0) {
          line.innerHTML = 'Cash: <b>$' + amt.toLocaleString() + '</b> of $'
            + Math.round(effective).toLocaleString() + ' (' + (w * 100).toFixed(2) + '%)';
        } else {
          line.innerHTML = '';
        }
      }
    });
  }
  cashSelect.addEventListener('change', function () {
    var c = parseFloat(cashSelect.value);
    if (!isFinite(c) || c <= 0) return;
    rows.forEach(function (r) { updateOne(r, c); });
  });
})();
</script>"""


def _escape(text) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_weights(weights: dict) -> str:
    parts = [f"{k.title()} {v:.2f}" for k, v in weights.items()]
    return " · ".join(parts) if parts else "(none)"


def _pill_class(v) -> str:
    if pd.isna(v) or v is None:
        return "flat"
    if v >= 0.5:
        return "up-strong"
    if v >= 0.1:
        return "up-light"
    if v <= -0.5:
        return "down-strong"
    if v <= -0.1:
        return "down-light"
    return "flat"


def _fmt_z(z) -> str:
    if pd.isna(z) or z is None:
        return "—"
    return f"{z:+.2f}σ"


def _intensity(z) -> str | None:
    if pd.isna(z) or z is None:
        return None
    a = abs(z)
    if a >= 0.5:
        return "strong"
    if a >= 0.2:
        return "moderate"
    return None  # treat anything closer to zero as no signal worth narrating


def _explain(mom_z, qual_z, val_z) -> str:
    """One-sentence narrative of which factors drove the composite."""
    parts = []
    for label, z in [("momentum", mom_z), ("quality", qual_z), ("value", val_z)]:
        intensity = _intensity(z)
        if intensity is None:
            continue
        direction = "positive" if z > 0 else "negative"
        parts.append(f"{intensity} {direction} {label}")
    if not parts:
        return "All three factors are within ±0.2σ of the universe — no strong signal."
    if len(parts) == 1:
        return f"{parts[0].capitalize()} drives the composite."
    if len(parts) == 2:
        return f"{parts[0].capitalize()} alongside {parts[1]}."
    return f"{parts[0].capitalize()}, {parts[1]}, and {parts[2]}."


def _factor_row(label: str, weight, z) -> str:
    z_html = _fmt_z(z)
    if z is None or pd.isna(z):
        z_cls = "flat"
    else:
        z_cls = _pill_class(float(z))
    if weight is None or weight == 0:
        contrib = '<span class="muted">excluded</span>'
        weight_html = ""
    else:
        if pd.isna(z) or z is None:
            contrib = '<span class="muted">—</span>'
        else:
            contrib = f"{z * weight:+.3f}"
        weight_html = f'<span class="w">{int(round(weight*100))}%</span>'
    return (
        f'<div class="label">{label}</div>'
        f'<div class="z {z_cls}">{z_html}</div>'
        f'<div class="contrib">{contrib} {weight_html}</div>'
    )


def _residual_chart_svg(
    values: list[float],
    width: int = 320, height: int = 110,
    klass: str = "resid-chart",
    grad_id: str = "rsd_grad",
) -> tuple[str, float]:
    """Centred residual chart with dashed zero baseline + vertical gradient stroke.

    The polyline is stroked with a vertical linear gradient in user-space
    coords (green at the top of the chart → neutral grey at the zero line
    → red at the bottom). Each segment picks up its colour from its own
    y-position, so positive history reads green even when the line later
    dips below zero. `cap` is returned for the caller to render matching
    corner labels.
    """
    if not values or len(values) < 2:
        return "", 1.0
    vmin, vmax = min(values), max(values)
    peak = max(abs(vmin), abs(vmax))
    # σ-scale: snap to friendly round caps until peak is large.
    if peak <= 1.0:
        cap = 1.0
    elif peak <= 2.0:
        cap = 2.0
    elif peak <= 3.0:
        cap = 3.0
    elif peak <= 5.0:
        cap = 5.0
    else:
        cap = float(int(peak * 1.1) + 1)
    margin_y = 6
    n = len(values)

    def y_of(v: float) -> float:
        center = height / 2
        scale = (height / 2 - margin_y) / cap
        return center - v * scale

    coords = [(i * width / (n - 1), y_of(v)) for i, v in enumerate(values)]
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    base_y = y_of(0.0)

    # Vertical gradient defined in user-space coords. With viewBox 0..height,
    # a stop at 0% lands at the top (largest positive value), 50% lands at
    # the zero line (height/2), 100% at the bottom (most negative). Stop
    # colours are the same emerald / muted-grey / coral palette used by the
    # composite pill; the grey middle keeps near-zero history honest-looking.
    stroke_grad_def = (
        f'<defs><linearGradient id="{grad_id}" gradientUnits="userSpaceOnUse" '
        f'x1="0" y1="0" x2="0" y2="{height}">'
        f'<stop offset="0%" stop-color="#34d399"/>'
        f'<stop offset="35%" stop-color="#34d399"/>'
        f'<stop offset="50%" stop-color="#9aa0a6"/>'
        f'<stop offset="65%" stop-color="#f87171"/>'
        f'<stop offset="100%" stop-color="#f87171"/>'
        f'</linearGradient></defs>'
    )

    return (
        f'<svg class="{klass}" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
        f'{stroke_grad_def}'
        f'<line x1="0" y1="{base_y:.1f}" x2="{width}" y2="{base_y:.1f}" '
        f'stroke="currentColor" stroke-opacity="0.30" stroke-width="1" '
        f'stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/>'
        f'<polyline fill="none" stroke="url(#{grad_id})" stroke-width="1.7" '
        f'stroke-linejoin="round" stroke-linecap="round" '
        f'vector-effect="non-scaling-stroke" points="{pts}"/>'
        '</svg>'
    ), cap


def _mini_residual_svg(
    values: list[float], grad_id: str = "mini_rsd_grad",
) -> str:
    """Compact residual sparkline for the collapsed row.

    Uses the same value-mapped vertical gradient as the big chart so positive
    history reads green and negative reads red along the same line.
    """
    if not values or len(values) < 2:
        return ""
    vmin, vmax = min(values), max(values)
    peak = max(abs(vmin), abs(vmax))
    if peak <= 0:
        return ""
    width, height = 56, 22
    margin = 2
    n = len(values)

    def y_of(v: float) -> float:
        center = height / 2
        scale = (height / 2 - margin) / max(peak, 1e-6)
        return center - v * scale

    pts = " ".join(
        f"{i * width / (n - 1):.1f},{y_of(v):.1f}"
        for i, v in enumerate(values)
    )
    base_y = y_of(0.0)
    grad_def = (
        f'<defs><linearGradient id="{grad_id}" gradientUnits="userSpaceOnUse" '
        f'x1="0" y1="0" x2="0" y2="{height}">'
        f'<stop offset="0%" stop-color="#34d399"/>'
        f'<stop offset="50%" stop-color="#9aa0a6"/>'
        f'<stop offset="100%" stop-color="#f87171"/>'
        f'</linearGradient></defs>'
    )
    return (
        f'<svg class="mini-spark" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'
        f'{grad_def}'
        f'<line x1="0" y1="{base_y:.1f}" x2="{width}" y2="{base_y:.1f}" '
        f'stroke="currentColor" stroke-opacity="0.25" stroke-width="1" '
        f'stroke-dasharray="2 2" vector-effect="non-scaling-stroke"/>'
        f'<polyline fill="none" stroke="url(#{grad_id})" stroke-width="1.5" '
        f'stroke-linejoin="round" stroke-linecap="round" '
        f'vector-effect="non-scaling-stroke" points="{pts}"/>'
        '</svg>'
    )


def _pullback_indicator_html(z: float | None) -> str:
    """Gradient timing readout for the 21d pullback z-score.

    Position on the bar is anchored so z = 0 sits at centre, z = -2 lands
    at the right (oversold / green end), and z = +2 at the left (extended /
    red end). Linearly interpolated, clamped to [0, 100]%.

    Status thresholds:
        z >= +1.0   →  Extended    (red)
       -1.0 < z < +1.0 → Neutral    (muted)
        z <= -1.0   →  Healthy pullback (green)
    """
    if z is None or pd.isna(z):
        return ""
    z = float(z)
    pos_pct = 50.0 - (z * 25.0)
    pos_pct = max(2.0, min(98.0, pos_pct))

    if z >= 1.0:
        status_label = "Extended"
        status_cls = "down"
    elif z <= -1.0:
        status_label = "Healthy pullback"
        status_cls = "up"
    else:
        status_label = "Neutral"
        status_cls = "neutral"

    z_cls = "up" if z >= 0 else "down"
    z_text = f"Pullback Z: {z:+.1f}σ"

    return (
        '<div class="pullback-block">'
        '<div class="pullback-head">'
        '<div class="pullback-title">'
        '<span class="pullback-label">21D PULLBACK</span>'
        '<span class="pullback-axis">(vs 21D σ)</span>'
        '</div>'
        '<div class="pullback-readout">'
        f'<span class="pullback-z {z_cls}">{z_text}</span>'
        f'<span class="pullback-status {status_cls}">{status_label}</span>'
        '</div>'
        '</div>'
        '<div class="pullback-bar">'
        f'<div class="pullback-marker" style="left:{pos_pct:.1f}%"></div>'
        '</div>'
        '<div class="pullback-legend">'
        '<span class="pullback-leg-l"><b>EXTENDED</b><br>(Overbought)</span>'
        '<span class="pullback-leg-c"><b>NEUTRAL</b><br>(Fair Value)</span>'
        '<span class="pullback-leg-r"><b>OVERSOLD</b><br>(Pullback)</span>'
        '</div>'
        '</div>'
    )


def _show_classes(rank: int) -> str:
    bits = []
    if rank < 25:
        bits.append("in-25")
    if rank < 50:
        bits.append("in-50")
    if rank < 100:
        bits.append("in-100")
    return " ".join(bits)


def _row_html(
    ticker, row, names: dict, weights: dict, cash: float,
    scheme_scales: dict,
    rank_composite: dict, rank_cash: dict, rank_sector: dict,
    rank_ticker: dict, rank_mktcap: dict,
    rank_momentum: dict | None = None,
    rank_quality: dict | None = None,
    rank_value: dict | None = None,
    diagnostics: dict | None = None,
    universe_labels: dict | None = None,
) -> str:
    """Render one <details class=row> card for a single ticker.

    Each row carries three weight values (equal / ivp / hrp) and three cash
    text spans. CSS toggles which scheme is shown based on the active
    weighting radio.
    """
    rank_val = row.get("rank")
    rank = str(int(rank_val)) if pd.notna(rank_val) else "—"
    sector = _escape(row.get("sector") or "—")
    comp_val = row.get("composite")
    composite = float(comp_val) if pd.notna(comp_val) else None
    pill_cls = _pill_class(composite)
    composite_text = f"{composite:+.3f}" if composite is not None else "—"
    ticker_esc = _escape(ticker)

    full_name = names.get(ticker, ticker) or ticker
    short_name = _short_name(full_name)
    name = _escape(short_name)
    full_name_block = ""
    if short_name != full_name:
        full_name_block = f'<div class="full-name">{_escape(full_name)}</div>'

    eq_w = float(row.get("equal_weight") or 0.0)
    ivp_w = float(row.get("ivp_weight") or 0.0)
    hrp_w = float(row.get("hrp_weight") or 0.0)

    cash_eq = cash * scheme_scales.get("equal", 1.0)
    cash_ivp = cash * scheme_scales.get("ivp", 1.0)
    cash_hrp = cash * scheme_scales.get("hrp", 1.0)
    amt_eq = int(round(eq_w * cash_eq)) if eq_w > 0 else 0
    amt_ivp = int(round(ivp_w * cash_ivp)) if ivp_w > 0 else 0
    amt_hrp = int(round(hrp_w * cash_hrp)) if hrp_w > 0 else 0

    def _cm(cls, amt):
        return f'<span class="{cls}">${amt:,}</span>' if amt > 0 else f'<span class="{cls}"></span>'

    cash_minis = (
        '<span class="cash-mini">'
        + _cm("cm-eq", amt_eq)
        + _cm("cm-ivp", amt_ivp)
        + _cm("cm-hrp", amt_hrp)
        + '</span>'
    )

    mom_z = row.get("residual_momentum_z")
    qual_z = row.get("quality_z")
    val_z = row.get("value_z")
    total_cls = _pill_class(composite) if composite is not None else "flat"
    factor_rows = (
        _factor_row("Momentum", weights.get("momentum"), mom_z)
        + _factor_row("Quality", weights.get("quality"), qual_z)
        + _factor_row("Value", weights.get("value"), val_z)
        + (
            '<div class="label total">Composite</div>'
            '<div class="z total"></div>'
            f'<div class="contrib total {total_cls}">{composite_text}</div>'
        )
    )

    def _wl(cls, w, amt, cash_eff):
        if w <= 0:
            return f'<div class="{cls} cash-line"></div>'
        return (
            f'<div class="{cls} cash-line">'
            f'Cash: <b>${amt:,}</b> of ${int(round(cash_eff)):,} '
            f'({w*100:.2f}%)</div>'
        )

    weight_lines = (
        _wl("wl-eq", eq_w, amt_eq, cash_eq)
        + _wl("wl-ivp", ivp_w, amt_ivp, cash_ivp)
        + _wl("wl-hrp", hrp_w, amt_hrp, cash_hrp)
    )

    explanation = _explain(mom_z, qual_z, val_z)

    diag = (diagnostics or {}).get(ticker) or {}
    chart_series = diag.get("chart_m6") or []
    current_m6 = diag.get("current_m6")
    pullback_z = diag.get("pullback_z")

    # Per-ticker gradient id keeps SVG defs from colliding across rows.
    safe_id = _escape(ticker).replace('.', '_').replace('-', '_')

    # Mini residual sparkline + small sigma badge in the collapsed row.
    if chart_series:
        mini_spark_html = _mini_residual_svg(chart_series, grad_id=f"mg_{safe_id}")
        cur_sig = float(current_m6) if current_m6 is not None else 0.0
        pct_cls = "up" if cur_sig >= 0 else "down"
        mini_pct_html = (
            f'<span class="mini-pct {pct_cls}">{cur_sig:+.2f}σ</span>'
        )
    else:
        mini_spark_html = ""
        mini_pct_html = ""
    mini_cell_html = (
        '<span class="mini-spark-cell">'
        f'{mini_spark_html}{mini_pct_html}'
        '</span>'
    )

    exp_val = row.get("expectations_z")
    expectations_block = ""
    if pd.notna(exp_val):
        ez = float(exp_val)
        ez_cls = "up" if ez >= 0 else "down"
        expectations_block = (
            '<div class="exp-row">'
            '<span class="exp-label">Expectations</span>'
            f'<span class="exp-value {ez_cls}">{ez:+.2f}σ</span>'
            '<span class="exp-tag">Diagnostic</span>'
            '</div>'
        )

    # Big 6-1 residual-momentum chart + 21d pullback indicator. Top-25 only.
    diagnostics_block = ""
    if chart_series and rank_composite.get(ticker, 9999) < 25:
        svg, cap = _residual_chart_svg(chart_series, grad_id=f"rg_{safe_id}")
        if svg:
            cur_sig = float(current_m6) if current_m6 is not None else 0.0
            cur_cls = "up" if cur_sig >= 0 else "down"
            cap_label = f"{cap:.1f}σ"
            chart_block = (
                '<div class="resid-block">'
                '<div class="resid-head">'
                '<div class="resid-title">'
                '<span class="resid-label">6-1 RESIDUAL MOMENTUM</span>'
                '<span class="resid-axis">(σ-scaled)</span>'
                '</div>'
                '<div class="resid-readout">'
                f'<span class="resid-value {cur_cls}">{cur_sig:+.2f}σ</span>'
                '</div>'
                '</div>'
                '<div class="resid-chart-wrap">'
                f'<div class="resid-axis-tl">+{cap_label}</div>'
                f'<div class="resid-axis-tr">+{cap_label}</div>'
                f'<div class="resid-axis-bl">−{cap_label}</div>'
                f'<div class="resid-axis-br">−{cap_label}</div>'
                f'<div class="resid-axis-zero">0σ</div>'
                f'{svg}'
                '</div>'
                '<p class="resid-desc">Rolling 6-1 residual momentum sleeve '
                '(126d lookback, 21d skip, divided by 63d residual σ) — '
                'endpoint equals the momentum composite\'s m6 input.'
                + (
                    f' <span class="resid-ema">· EMA({int(diag.get("ema_span") or 1)})</span>'
                    if int(diag.get("ema_span") or 1) > 1 else ''
                )
                + '</p>'
                '</div>'
            )
        else:
            chart_block = ""
        pullback_html = _pullback_indicator_html(pullback_z) if pullback_z is not None else ""
        diagnostics_block = chart_block + pullback_html

    order_style = (
        f"--r-c:{rank_composite.get(ticker, 0)};"
        f"--r-cash:{rank_cash.get(ticker, 0)};"
        f"--r-sec:{rank_sector.get(ticker, 0)};"
        f"--r-tick:{rank_ticker.get(ticker, 0)};"
        f"--r-mkt:{rank_mktcap.get(ticker, 0)};"
        f"--r-mom:{(rank_momentum or {}).get(ticker, 0)};"
        f"--r-qual:{(rank_quality or {}).get(ticker, 0)};"
        f"--r-val:{(rank_value or {}).get(ticker, 0)};"
    )
    tags = (universe_labels or {}).get(ticker) or []
    tags_html = ""
    if tags:
        tag_spans = "".join(f'<span class="tag">{_escape(t)}</span>' for t in tags)
        tags_html = f'<span class="tags">{tag_spans}</span>'

    show_cls = _show_classes(rank_composite.get(ticker, 9999))
    return (
        f'<details class="row {show_cls}" style="{order_style}" '
        f'data-eq="{eq_w}" data-ivp="{ivp_w}" data-hrp="{hrp_w}">'
        '<summary>'
        f'<span class="rank">{rank}</span>'
        f'<span class="ticker">{ticker_esc}</span>'
        f'<span class="pill {pill_cls}">{composite_text}</span>'
        f'<span class="meta">'
        f'<span class="name">{name}</span>'
        f'<span class="dot">·</span>'
        f'<span class="sector">{sector}</span>'
        f'{tags_html}'
        f'</span>'
        f'{mini_cell_html}'
        f'{cash_minis}'
        '</summary>'
        '<div class="expanded">'
        '<div class="divider"></div>'
        f'{full_name_block}'
        f'{diagnostics_block}'
        f'<div class="factors">{factor_rows}</div>'
        f'<div class="explain">{explanation}</div>'
        f'{weight_lines}'
        f'{expectations_block}'
        '</div>'
        '</details>'
    )


_LIST_HEADER = (
    '<div class="list-header">'
    '<span class="col-rank">#</span>'
    '<span class="col-name">Stock</span>'
    '<span class="col-comp">Composite</span>'
    '</div>'
)


_METHODOLOGY_BODY = (
    '<h3>Model summary</h3>'
    '<p>Each stock is scored on three factors — Momentum, Quality, Value — '
    'standardised cross-sectionally and combined into a single composite '
    'z-score. The top 25 composite-ranked names are then sized into a '
    'portfolio using one of three weighting schemes (toggleable in the '
    'Ranking card) and optionally scaled to a target portfolio volatility.</p>'

    '<h3>Momentum</h3>'
    '<p>Residual momentum, risk-adjusted. Daily log returns are first '
    'residualised in two stages: each sector ETF is regressed on the market '
    '(VTI) over the last 504 trading days to extract a market-orthogonal '
    'sector residual, then each stock is regressed on [market, sector '
    'residual] over the same window. The 12-1 sleeve sums residuals from '
    't-252 to t-22; the 6-1 sleeve sums from t-126 to t-22. Both are divided '
    'by a 63-day residual sigma (no skip, not annualised, floored at 1e-6). '
    'Each sleeve is winsorised at 5/95 and z-scored across the universe, '
    'combined 50/50, and z-scored once more.</p>'

    '<h3>Quality</h3>'
    '<p>Sector-relative composite of three components: '
    '(1) gross profitability = grossProfit / totalAssets, '
    '(2) year-over-year change in gross profitability, and '
    '(3) balance-sheet quality = −(totalDebt − cash) / totalAssets. '
    'Each component is winsorised and z-scored within its sector and '
    'combined 0.50 / 0.20 / 0.30. The weighted composite is then '
    'winsorised and z-scored across the full universe so the final '
    'Quality_z sits on the same scale as Momentum_z. Sectors with '
    'fewer than 5 finite members fall back to a universe-wide z-score '
    'at the component step only, so small buckets do not produce '
    'mechanically-±1 outputs.</p>'

    '<h3>Value</h3>'
    '<p>Sector-relative composite of three multiples: EBIT/EV (40%), '
    'FCF/EV (40%), and book/market_cap (20%). Enterprise value = '
    'market_cap + totalDebt − cash. Each component is winsorised and '
    'z-scored within its sector (same small-sector fallback as Quality), '
    'then blended with the weights above. The weighted composite is '
    'winsorised and z-scored across the full universe so Value_z is '
    'comparable to Momentum_z and Quality_z before the MQV combine.</p>'

    '<h3>Composite weights</h3>'
    '<p>Composite = 0.50 · Momentum + 0.30 · Quality + 0.20 · Value. '
    'Missing factors contribute zero. If the share of the universe with a '
    'finite Quality or Value z-score falls below 40%, that factor is dropped '
    'and the surviving weights renormalise.</p>'

    '<h3>Expectations <span class="exp-tag">Diagnostic</span></h3>'
    '<p>An experimental fourth factor reading analyst behaviour on each '
    'name. Two raw components: <b>forward EPS growth</b> = next-year '
    'consensus / current-year consensus − 1 (from FMP analyst-estimates), '
    'and <b>earnings surprise</b> = (actual EPS − estimated EPS) / '
    '|estimated EPS| on the most recent reported quarter (from FMP '
    'earnings-surprises). Each component is winsorised and z-scored within '
    'its sector with the same small-sector fallback as Quality / Value, '
    'blended 50/50, then winsorised and z-scored across the universe to '
    'produce expectations_z. Surfaced on every card\'s expanded panel as '
    'a diagnostic line — <b>not in the composite yet</b>. Step 2 will '
    'orthogonalise it against M/Q/V and promote into the composite at a '
    '0.10 weight if coverage and signal hold up.</p>'

    '<h3>Universe &amp; screener</h3>'
    '<p>Stocks live in data/universe.json plus data/universe_extra.txt. '
    'Share classes are deduped to keep the voting class (GOOGL > GOOG, '
    'BRK.A > BRK.B, PBR > PBR-A). Sector taxonomy uses the 11 SPDR sectors '
    'plus two carve-outs — Semiconductors (SOXX) and Aerospace &amp; Defense '
    '(ITA) — with industry overrides routing semis and A&amp;D names into '
    'their own buckets. expand.py uses FMP\'s screener to add the next N '
    'US-listed names by market cap, skipping anything already in the '
    'universe.</p>'

    '<h3>Universe hygiene</h3>'
    '<p>Before the pipeline runs, each ticker is classified against two '
    'rule sets. <b>Excluded:</b> preferreds, baby bonds and notes, '
    'warrants, rights, SPAC units, ETFs, and mutual / closed-end funds. '
    'Detection uses both ticker-suffix patterns (catches non-common-stock '
    'tickers regardless of profile data) and FMP profile flags (isEtf, '
    'isFund). <b>Kept:</b> common stocks, ADRs, and foreign ordinary '
    'shares. <b>Labelled:</b> ADRs (foreign country of incorporation or '
    'depositary receipts), REITs (industry contains "REIT" or "Real '
    'Estate Investment"), and MLPs (limited / master limited '
    'partnerships). Labels show as small uppercase tags next to the '
    'sector in each row.</p>'

    '<h3>Portfolio weighting</h3>'
    '<p>Three schemes are available and switchable inline:</p>'
    '<p><b>Equal weight</b> — w_i = 1/N. Maximum diversification by name '
    'count, no use of price/return information.</p>'
    '<p><b>Inverse volatility</b> — w_i ∝ 1/σ_i, σ from a 252-day annualised '
    'sample stdev (Maillard, Roncalli &amp; Teiletche, 2010). Tilts away '
    'from high-vol names without considering correlations.</p>'
    '<p><b>HRP — Hierarchical Risk Parity</b> (López de Prado, 2016). '
    'Sample covariance over 504 days of <i>residual</i> daily returns is '
    'converted to a correlation-distance metric d = √(0.5·(1 − ρ)). '
    'Average-link agglomerative clustering produces a leaf order that '
    'groups similar names together. Weights are then assigned by recursive '
    'bisection: at each midpoint of the ordered list, allocate inversely '
    'proportional to the inverse-variance-weighted variance of each side. '
    'Long-only by construction, weights sum to 1, no name caps in v0.1.</p>'

    '<h3>Volatility targeting</h3>'
    '<p>Realised portfolio σ is computed for each scheme using the same '
    'covariance window. If the realised σ exceeds the configured target, '
    'the dollar deployment is scaled down by target/realised so the '
    'expected portfolio σ matches the target — effectively holding cash. '
    'If realised σ is already below the target, weights are left at full '
    'deployment (no leverage). Per-name dollars = weight × deployment × '
    'min(1, target/realised). Configure via VOL_TARGET in config.py; set '
    'to None to disable.</p>'

    '<h3>Data source</h3>'
    '<p>Financial Modeling Prep (stable + legacy v3 endpoints): daily '
    'prices, annual income / balance / cash-flow statements, and company '
    'profiles.</p>'

    '<h3>Cache</h3>'
    '<p>Pickled locally under cache/. Per-ticker freshness for fundamentals '
    'and profiles (30-day refresh); global 5-day refresh for prices. Run '
    'main.py --update to top up missing or stale data; --refresh forces '
    'a full re-pull.</p>'

    '<h3>Caveats</h3>'
    '<p>Annual fundamentals can be up to 12 months stale. Shares outstanding '
    'come from the latest annual income statement. Betas are single-window '
    'OLS estimates over 504 days, not rolling. The HRP covariance has no '
    'shrinkage. Not investment advice.</p>'
)


def _fmt_pct(x, decimals: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x*100:+.{decimals}f}%"


def _fmt_signed(x, decimals: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x:+.{decimals}f}"


def _backtest_row(label: str, bt: dict | None) -> str:
    if not bt:
        return (
            f'<div class="bt-row">'
            f'<span class="bt-label">{label}</span>'
            f'<span class="bt-cell">—</span>'
            f'<span class="bt-cell">—</span>'
            f'<span class="bt-cell">—</span>'
            f'</div>'
        )
    return (
        f'<div class="bt-row">'
        f'<span class="bt-label">{label}</span>'
        f'<span class="bt-cell ret">{_fmt_pct(bt.get("total_return"))}</span>'
        f'<span class="bt-cell">{_fmt_signed(bt.get("sharpe"))}</span>'
        f'<span class="bt-cell dd">{_fmt_pct(bt.get("max_drawdown"))}</span>'
        f'</div>'
    )


def _fmt_mkt_cap(x) -> str:
    if x is None or pd.isna(x) or x <= 0:
        return "—"
    if x >= 1e12:
        return f"${x / 1e12:.2f}T"
    if x >= 1e9:
        return f"${x / 1e9:.1f}B"
    if x >= 1e6:
        return f"${x / 1e6:.0f}M"
    return f"${x:,.0f}"


def _uni_table_rows(rows: list, total: int) -> str:
    """Three-column rows (label / count / pct) for the Universe section."""
    out = []
    for label, count in rows:
        if total > 0:
            pct = count / total * 100.0
            pct_str = f"{pct:.1f}%"
        else:
            pct_str = "—"
        out.append(
            '<div class="uni-row">'
            f'<span class="uni-label">{_escape(label)}</span>'
            f'<span class="uni-count">{count}</span>'
            f'<span class="uni-pct">{pct_str}</span>'
            '</div>'
        )
    return "".join(out)


def _ticker_pair_rows(rows: list) -> str:
    """Two-column rows for ticker + company-name lists in drill-downs.

    `rows` is an iterable of (ticker, name) tuples. Empty names render an
    em-dash so users can spot tickers that actually lack profile data
    (i.e. genuine "unknowns" the pipeline never resolved).
    """
    if not rows:
        return '<div class="uni-empty">None.</div>'
    out = []
    for ticker, name in rows:
        name_text = _escape(name) if name else "—"
        out.append(
            '<div class="uni-pair-row">'
            f'<span class="uni-pair-ticker">{_escape(ticker)}</span>'
            f'<span class="uni-pair-name">{name_text}</span>'
            '</div>'
        )
    return f'<div class="uni-pair-list">{"".join(out)}</div>'


def _unclassified_drilldown(rows: list) -> str:
    """Collapsible drawer showing every active ticker that lacks a sector.

    These are the names the user wants to audit — either FMP returned no
    profile, or the profile came back without a sector. Both cases show
    here so they can decide whether to tighten hygiene or fetch fresher
    profile data (--refresh).
    """
    if not rows:
        return ""
    return (
        '<details class="uni-collapse">'
        f'<summary>Unclassified or unknown sector ({len(rows)})</summary>'
        '<p class="uni-collapse-note">'
        'No profile or no sector returned by FMP. Run main.py --refresh '
        'to top up profile data, or add to baseline hygiene if any of '
        'these are genuinely junk that should be excluded.'
        '</p>'
        f'{_ticker_pair_rows(rows)}'
        '</details>'
    )


def _hygiene_drilldown(by_reason_named: dict) -> str:
    """Collapsible drawer listing every hygiene-excluded ticker, grouped
    by the rule that fired, with company names so the user can spot
    false positives (real common stock mislabelled) and false negatives
    (junk that slipped through to the eligible set)."""
    if not by_reason_named:
        return ""
    total = sum(len(v) for v in by_reason_named.values())
    if total == 0:
        return ""
    blocks = []
    for label in sorted(by_reason_named.keys()):
        pairs = by_reason_named[label]
        blocks.append(
            f'<div class="uni-hyg-group">'
            f'<div class="uni-hyg-label">{_escape(label)} '
            f'<span class="uni-hyg-count">({len(pairs)})</span></div>'
            f'{_ticker_pair_rows(pairs)}'
            '</div>'
        )
    return (
        '<details class="uni-collapse">'
        f'<summary>Excluded by hygiene ({total})</summary>'
        '<p class="uni-collapse-note">'
        'Tickers the baseline hygiene rules dropped before scoring. '
        'Audit the list to confirm each removal was correct — flag any '
        'real common stock that was mislabelled, and look at the active '
        'universe for junk that should have been caught here instead.'
        '</p>'
        f'{"".join(blocks)}'
        '</details>'
    )


def _universe_section_html(factors_used: dict) -> str:
    """Build the Universe card.

    Top: subtitle line summarising raw / eligible / active counts and any
    active filters. Body: composition (Common / ADR / REIT / MLP / unknown),
    sectors, market-cap stats + buckets, an Industries sub-drawer, and an
    Active Filters block surfaced regardless of whether filters fired.
    """
    pulse = factors_used.get("universe_pulse") or {}
    raw_n = factors_used.get("universe_raw_count") or 0
    eligible_n = factors_used.get("universe_eligible_count") or 0
    active_n = factors_used.get("universe_active_count") or pulse.get("n") or 0
    filters = factors_used.get("universe_active_filters") or {}

    # Subtitle
    bits = [f"{active_n} active"]
    if eligible_n != active_n:
        bits.append(f"{eligible_n} eligible")
    if raw_n and raw_n != eligible_n:
        bits.append(f"{raw_n - eligible_n} excluded by hygiene")
    if filters.get("removed_count"):
        names = []
        if filters.get("exclude_adr"):
            names.append("ADRs")
        if filters.get("exclude_reit"):
            names.append("REITs")
        bits.append(
            f"filters: {', '.join(names)} ({filters['removed_count']} dropped)"
        )
    elif filters.get("exclude_adr") or filters.get("exclude_reit"):
        bits.append("filters: active (none matched)")
    subtitle = " · ".join(bits)

    if not pulse or pulse.get("n", 0) == 0:
        body = '<p class="uni-empty">No active universe to summarise.</p>'
    else:
        composition = pulse.get("composition") or []
        sectors = pulse.get("sectors") or []
        industries = pulse.get("industries") or []
        mc = pulse.get("market_cap") or {}
        buckets = pulse.get("buckets") or []
        n = pulse.get("n", 0)

        composition_table = _uni_table_rows(composition, n)
        sector_table = _uni_table_rows(sectors, n)
        bucket_table = _uni_table_rows(buckets, n)
        industry_table = _uni_table_rows(industries, n)

        if mc:
            mc_line = (
                f'<p class="uni-stats">'
                f'Median <b>{_fmt_mkt_cap(mc.get("median"))}</b> · '
                f'Min <b>{_fmt_mkt_cap(mc.get("min"))}</b> · '
                f'Max <b>{_fmt_mkt_cap(mc.get("max"))}</b> · '
                f'{mc.get("n_with_data", 0)} of {n} with data'
                '</p>'
            )
        else:
            mc_line = (
                '<p class="uni-stats uni-empty">No market-cap data available '
                'yet — run main.py --update once.</p>'
            )

        # Active filters block — always rendered so users see the controls
        # exist, even when all are off.
        def _row(label: str, on: bool, cli: str) -> str:
            mark = "On" if on else "Off"
            cls = "on" if on else "off"
            return (
                f'<div class="uni-filter-row">'
                f'<span class="uni-label">{_escape(label)}</span>'
                f'<span class="uni-filter-state {cls}">{mark}</span>'
                f'<span class="uni-filter-cli">{_escape(cli)}</span>'
                '</div>'
            )
        filters_block = (
            _row("Exclude ADRs", bool(filters.get("exclude_adr")), "--exclude-adr")
            + _row("Exclude REITs", bool(filters.get("exclude_reit")), "--exclude-reit")
            + '<div class="uni-filter-row">'
              '<span class="uni-label">Min / max market cap</span>'
              '<span class="uni-filter-state off">Deferred</span>'
              '<span class="uni-filter-cli">v0.2</span>'
              '</div>'
            + '<div class="uni-filter-row">'
              '<span class="uni-label">Sector / industry exclusions</span>'
              '<span class="uni-filter-state off">Deferred</span>'
              '<span class="uni-filter-cli">v0.2</span>'
              '</div>'
        )

        body = (
            '<h4 class="uni-h">Composition</h4>'
            f'<div class="uni-table">{composition_table}</div>'
            '<h4 class="uni-h">Sectors</h4>'
            f'<div class="uni-table">{sector_table}</div>'
            '<h4 class="uni-h">Market cap</h4>'
            f'{mc_line}'
            f'<div class="uni-table">{bucket_table}</div>'
            '<h4 class="uni-h">Active filters</h4>'
            f'<div class="uni-filters">{filters_block}</div>'
            f'<details class="uni-collapse">'
            f'<summary>Industries ({len(industries)})</summary>'
            f'<div class="uni-table uni-industries">{industry_table}</div>'
            '</details>'
            f'{_unclassified_drilldown(pulse.get("unclassified") or [])}'
            f'{_hygiene_drilldown(factors_used.get("universe_excluded_named_by_reason") or {})}'
        )

    return (
        '<details class="section">'
        '<summary>'
        '<div class="section-head">'
        '<div class="section-title">Universe</div>'
        f'<div class="section-subtitle">{_escape(subtitle)}</div>'
        '</div>'
        '</summary>'
        f'<div class="section-body">{body}</div>'
        '</details>'
    )


def _backtest_section_html(bt: dict) -> str:
    lookback = bt.get("lookback_days") or 0
    eq = bt.get("equal")
    ivp = bt.get("ivp")
    hrp = bt.get("hrp")
    market = bt.get("market")
    if not any([eq, ivp, hrp, market]):
        return ""
    # Period from any available leg
    start = end = ""
    for leg in (hrp, ivp, eq, market):
        if leg and leg.get("start_date"):
            start = leg["start_date"]
            end = leg["end_date"]
            break
    period_text = f"{start} → {end}" if start and end else f"{lookback} trading days"
    subtitle = f"v0.1 lookback · {period_text}"
    rows = (
        '<div class="bt-row bt-head">'
        '<span class="bt-label"></span>'
        '<span class="bt-cell">Total return</span>'
        '<span class="bt-cell">Sharpe (ann.)</span>'
        '<span class="bt-cell">Max drawdown</span>'
        '</div>'
        + _backtest_row("HRP", hrp)
        + _backtest_row("Inv Vol", ivp)
        + _backtest_row("Equal", eq)
        + _backtest_row(f"{MARKET_TICKER_LABEL} (benchmark)", market)
    )
    caveat = (
        '<p class="bt-caveat">Holds today\'s top-25 weights statically over '
        'the past period — a current-portfolio attribution, not a true '
        'rolling-rebalance backtest. Selection uses present data, so this '
        'has look-ahead bias on stock picking. Useful as a recent risk/'
        'return sanity check only.</p>'
    )
    return (
        '<details class="section">'
        '<summary>'
        '<div class="section-head">'
        '<div class="section-title">Backtest</div>'
        f'<div class="section-subtitle">{subtitle}</div>'
        '</div>'
        '</summary>'
        '<div class="section-body">'
        f'<div class="bt-table">{rows}</div>'
        f'{caveat}'
        '</div>'
        '</details>'
    )


# Imported at module scope to avoid an extra import inside the helper.
try:
    from config import MARKET_TICKER as MARKET_TICKER_LABEL
except ImportError:
    MARKET_TICKER_LABEL = "Market"


def _snapshot_archive_html() -> str:
    """Tiny collapsed status line at the bottom of the page.

    Reads only metadata.json from each snapshot dir, never the CSVs, so this
    is cheap to call. Surfaces latest timestamp + version + active count and
    the last N entries inside the drawer.
    """
    import config as _config
    limit = int(getattr(_config, "SNAPSHOTS_INDEX_LIMIT", 20))
    entries = snapshots.list_snapshots(limit=limit)
    if not entries:
        return (
            '<details class="snap-archive">'
            '<summary>Snapshot archive · none yet</summary>'
            '<p class="snap-empty">Snapshots are saved automatically after '
            'every run to <code>snapshots/</code>. Run main.py once to '
            'create the first one.</p>'
            '</details>'
        )
    latest = entries[0]
    ts = (latest.get("timestamp") or "").replace("T", " ")[:16]
    summary = (
        f'Snapshot archive · {len(entries)} listed · '
        f'last {ts or "unknown"} · '
        f'v{latest.get("version") or "?"} '
        f'({"stable" if latest.get("stable") else "dev"})'
    )
    rows = []
    for e in entries:
        ets = (e.get("timestamp") or "").replace("T", " ")[:16]
        ver = e.get("version") or "?"
        stab = "stable" if e.get("stable") else "dev"
        active = e.get("active") if e.get("active") is not None else "—"
        topn = e.get("top_n") if e.get("top_n") is not None else "—"
        rows.append(
            '<div class="snap-row">'
            f'<span class="snap-ts">{_escape(ets or "—")}</span>'
            f'<span class="snap-ver">v{_escape(str(ver))} {stab}</span>'
            f'<span class="snap-meta">active={active} top={topn}</span>'
            '</div>'
        )
    body = (
        '<p class="snap-note">Background data collection. '
        'Dev snapshots are not comparable to future stable snapshots.</p>'
        f'<div class="snap-list">{"".join(rows)}</div>'
    )
    return (
        '<details class="snap-archive">'
        f'<summary>{_escape(summary)}</summary>'
        f'{body}'
        '</details>'
    )


def render(
    ranked_df: pd.DataFrame, names: dict, factors_used: dict,
    diagnostics: dict | None = None,
) -> str:
    weights = factors_used.get("weights", {})
    scheme = factors_used.get("weighting_scheme", "")
    top_n = factors_used.get("top_n")
    cash = float(factors_used.get("cash_deployment") or 0)
    initial_sort = factors_used.get("sort", "composite")
    raw_scheme = (factors_used.get("weighting_scheme") or "hrp").lower()
    if raw_scheme in ("inverse_vol", "inv_vol", "ivp"):
        initial_scheme = "ivp"
    elif raw_scheme in ("equal", "equal_weight", "ew"):
        initial_scheme = "equal"
    else:
        initial_scheme = "hrp"
    # Default Show pick: 100 if at least 100 rendered, else next-smaller.
    n_rendered = len(ranked_df)
    if n_rendered >= 100:
        initial_show = "100"
    elif n_rendered >= 50:
        initial_show = "50"
    else:
        initial_show = "25"

    # Pre-compute the order index for each ticker under each sort key.
    if not ranked_df.empty:
        idx_composite = ranked_df.sort_values(
            "composite", ascending=False, kind="mergesort"
        ).index.tolist()
        cash_sort_col = "hrp_weight" if "hrp_weight" in ranked_df.columns else "composite"
        idx_cash = ranked_df.sort_values(
            cash_sort_col, ascending=False, kind="mergesort"
        ).index.tolist()
        idx_sector = ranked_df.sort_values(
            ["sector", "composite"], ascending=[True, False], kind="mergesort"
        ).index.tolist()
        idx_ticker = ranked_df.sort_index(
            ascending=True, kind="mergesort"
        ).index.tolist()
        if "market_cap" in ranked_df.columns:
            idx_mktcap = ranked_df.sort_values(
                "market_cap", ascending=False, kind="mergesort", na_position="last",
            ).index.tolist()
        else:
            idx_mktcap = idx_composite

        def _z_idx(col: str) -> list:
            if col in ranked_df.columns:
                return ranked_df.sort_values(
                    col, ascending=False, kind="mergesort", na_position="last",
                ).index.tolist()
            return idx_composite

        idx_momentum = _z_idx("residual_momentum_z")
        idx_quality = _z_idx("quality_z")
        idx_value = _z_idx("value_z")
    else:
        idx_composite = idx_cash = idx_sector = idx_ticker = idx_mktcap = []
        idx_momentum = idx_quality = idx_value = []
    rank_composite = {t: i for i, t in enumerate(idx_composite)}
    rank_cash = {t: i for i, t in enumerate(idx_cash)}
    rank_sector = {t: i for i, t in enumerate(idx_sector)}
    rank_ticker = {t: i for i, t in enumerate(idx_ticker)}
    rank_mktcap = {t: i for i, t in enumerate(idx_mktcap)}
    rank_momentum = {t: i for i, t in enumerate(idx_momentum)}
    rank_quality = {t: i for i, t in enumerate(idx_quality)}
    rank_value = {t: i for i, t in enumerate(idx_value)}

    # Compact page header (criteria summary + cash dropdown).
    header_bits = [f"<b>{_format_weights(weights)}</b>"]
    if scheme and top_n:
        header_bits.append(f"Top {top_n} weighted by {scheme.replace('_', ' ')}")
    prices_as_of = factors_used.get("prices_as_of")
    if prices_as_of:
        header_bits.append(f"Prices as of {_escape(prices_as_of)}")
    cash_options = ""
    for v in (25000, 30000, 35000, 40000):
        sel = " selected" if int(round(cash)) == v else ""
        cash_options += f'<option value="{v}"{sel}>${v:,}</option>'
    cash_picker = (
        '<span class="cash-picker">Cash deployed: '
        f'<select id="cashSelect">{cash_options}</select></span>'
    )
    header_html = " &middot; ".join(header_bits) + " &middot; " + cash_picker

    scheme_scales = factors_used.get("scheme_scales") or {
        "equal": 1.0, "ivp": 1.0, "hrp": 1.0,
    }
    scheme_vols = factors_used.get("scheme_vols") or {}
    vol_target = factors_used.get("vol_target")

    # --- Section 1: Ranking (default open) — single scrolling list with the
    # weighting toggle. Top N stocks have non-zero weights and show cash;
    # rest just show composite.
    universe_labels = factors_used.get("universe_labels") or {}
    rows_html = "".join(
        _row_html(t, r, names, weights, cash, scheme_scales,
                  rank_composite, rank_cash, rank_sector, rank_ticker, rank_mktcap,
                  rank_momentum=rank_momentum,
                  rank_quality=rank_quality,
                  rank_value=rank_value,
                  diagnostics=diagnostics, universe_labels=universe_labels)
        for t, r in ranked_df.iterrows()
    )
    universe_total = factors_used.get("universe_total") or len(ranked_df)
    raw_count = factors_used.get("universe_raw_count")
    excluded_count = len(factors_used.get("universe_excluded") or {})
    weighted_count = (ranked_df["hrp_weight"] > 0).sum() if "hrp_weight" in ranked_df.columns else 0
    weighted_suffix = f" · top {int(weighted_count)} weighted" if weighted_count else ""
    vol_suffix = f" · {vol_target*100:.0f}% vol target" if vol_target else ""
    excluded_suffix = (
        f" · {excluded_count} excluded" if excluded_count else ""
    )

    def _make_sub(visible_n: int) -> str:
        actual = min(visible_n, len(ranked_df))
        if universe_total > actual:
            return (
                f"Top {actual} of {universe_total} eligible"
                f"{excluded_suffix}{weighted_suffix}{vol_suffix}"
            )
        return (
            f"{actual} eligible"
            f"{excluded_suffix}{weighted_suffix}{vol_suffix}"
        )

    full_subtitle = (
        f'<span class="sub-25">{_make_sub(25)}</span>'
        f'<span class="sub-50">{_make_sub(50)}</span>'
        f'<span class="sub-100">{_make_sub(100)}</span>'
    )

    weighting_toggle = (
        '<div class="weighting-toggle">'
        '<span class="toolbar-label">Weighting</span>'
        '<label for="wt-hrp" class="sort-btn">HRP</label>'
        '<label for="wt-ivp" class="sort-btn">Inv Vol</label>'
        '<label for="wt-equal" class="sort-btn">Equal</label>'
        '</div>'
    )

    show_toggle = (
        '<div class="weighting-toggle">'
        '<span class="toolbar-label">Show</span>'
        '<label for="show-25" class="sort-btn">Top 25</label>'
        '<label for="show-50" class="sort-btn">Top 50</label>'
        '<label for="show-100" class="sort-btn">Top 100</label>'
        '</div>'
    )

    full_section = (
        '<details class="section" open>'
        '<summary>'
        '<div class="section-head">'
        '<div class="section-title">Ranking</div>'
        f'<div class="section-subtitle">{full_subtitle}</div>'
        '</div>'
        '</summary>'
        '<div class="section-body">'
        f'{weighting_toggle}'
        f'{show_toggle}'
        f'{_LIST_HEADER}'
        f'<div class="list">{rows_html}</div>'
        '</div>'
        '</details>'
    )

    # --- Section 3: Methodology & details (default closed) ---
    js_block = (
        _JS
        .replace("__SCALE_EQ__", str(scheme_scales.get("equal", 1.0)))
        .replace("__SCALE_IVP__", str(scheme_scales.get("ivp", 1.0)))
        .replace("__SCALE_HRP__", str(scheme_scales.get("hrp", 1.0)))
    )

    backtest_section = _backtest_section_html(factors_used.get("backtest") or {})
    universe_section = _universe_section_html(factors_used)

    raw_count = factors_used.get("universe_raw_count")
    eligible_count = factors_used.get("universe_eligible_count")
    excluded_by_reason = factors_used.get("universe_excluded_by_reason") or {}
    counts_block = ""
    if raw_count is not None and eligible_count is not None:
        excluded_n = sum(len(v) for v in excluded_by_reason.values())
        counts_block = (
            '<h3>This run</h3>'
            f'<p>Raw universe {raw_count} · '
            f'eligible {eligible_count} · '
            f'excluded {excluded_n}.</p>'
        )
    if excluded_by_reason:
        parts = ['<h3>Excluded this run</h3>']
        for reason in sorted(excluded_by_reason.keys()):
            tickers_list = excluded_by_reason[reason]
            parts.append(
                f'<p><b>{_escape(reason)}</b> ({len(tickers_list)}): '
                f'{_escape(", ".join(tickers_list))}</p>'
            )
        excluded_block = "".join(parts)
    elif raw_count is not None:
        excluded_block = '<h3>Excluded this run</h3><p>None.</p>'
    else:
        excluded_block = ""

    methodology_section = (
        '<details class="section">'
        '<summary>'
        '<div class="section-head">'
        '<div class="section-title">Methodology &amp; details</div>'
        '<div class="section-subtitle">Model summary, formulas, data sources</div>'
        '</div>'
        '</summary>'
        '<div class="section-body methodology-body">'
        f'{counts_block}{_METHODOLOGY_BODY}{excluded_block}'
        '</div>'
        '</details>'
    )

    return (
        '<!doctype html>'
        '<html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<title>Portfolio Report</title>'
        f'<style>{_CSS}</style>'
        '</head><body>'
        # Hidden sort + weighting radios at the top of body so the CSS general-
        # sibling selector reaches both the sticky toolbar and the rows below.
        f'<input type="radio" name="sort" id="sort-composite" class="sort-radio"{ " checked" if initial_sort == "composite" else "" }>'
        f'<input type="radio" name="sort" id="sort-cash" class="sort-radio"{ " checked" if initial_sort == "cash" else "" }>'
        f'<input type="radio" name="sort" id="sort-sector" class="sort-radio"{ " checked" if initial_sort == "sector" else "" }>'
        f'<input type="radio" name="sort" id="sort-ticker" class="sort-radio"{ " checked" if initial_sort == "ticker" else "" }>'
        f'<input type="radio" name="sort" id="sort-mktcap" class="sort-radio"{ " checked" if initial_sort == "mktcap" else "" }>'
        f'<input type="radio" name="sort" id="sort-momentum" class="sort-radio"{ " checked" if initial_sort == "momentum" else "" }>'
        f'<input type="radio" name="sort" id="sort-quality" class="sort-radio"{ " checked" if initial_sort == "quality" else "" }>'
        f'<input type="radio" name="sort" id="sort-value" class="sort-radio"{ " checked" if initial_sort == "value" else "" }>'
        f'<input type="radio" name="weighting" id="wt-hrp" class="sort-radio"{ " checked" if initial_scheme == "hrp" else "" }>'
        f'<input type="radio" name="weighting" id="wt-ivp" class="sort-radio"{ " checked" if initial_scheme == "ivp" else "" }>'
        f'<input type="radio" name="weighting" id="wt-equal" class="sort-radio"{ " checked" if initial_scheme == "equal" else "" }>'
        f'<input type="radio" name="show" id="show-25" class="sort-radio"{ " checked" if initial_show == "25" else "" }>'
        f'<input type="radio" name="show" id="show-50" class="sort-radio"{ " checked" if initial_show == "50" else "" }>'
        f'<input type="radio" name="show" id="show-100" class="sort-radio"{ " checked" if initial_show == "100" else "" }>'
        '<div class="page-title">Portfolio Report</div>'
        f'<div class="header">{header_html}</div>'
        '<div class="sticky-top">'
        '<div class="toolbar">'
        '<span class="toolbar-label">Sort</span>'
        '<label for="sort-composite" class="sort-btn">Composite</label>'
        '<label for="sort-momentum" class="sort-btn">Momentum</label>'
        '<label for="sort-quality" class="sort-btn">Quality</label>'
        '<label for="sort-value" class="sort-btn">Value</label>'
        '<label for="sort-cash" class="sort-btn">Cash</label>'
        '<label for="sort-mktcap" class="sort-btn">Market Cap</label>'
        '<label for="sort-sector" class="sort-btn">Sector</label>'
        '<label for="sort-ticker" class="sort-btn">Ticker</label>'
        '</div>'
        '</div>'
        f'{full_section}'
        f'{universe_section}'
        f'{backtest_section}'
        f'{methodology_section}'
        f'{_snapshot_archive_html()}'
        f'{js_block}'
        '</body></html>'
    )


def write_report(html: str, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")


def write_csv(ranked_df: pd.DataFrame, path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ranked_df.to_csv(p, index=True)
