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


_CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Segoe UI', sans-serif;
  font-size: 15px; line-height: 1.4;
  color: #1c1c1e; background: #f5f5f7;
  padding: 14px 12px 32px;
}
.header {
  font-size: 12px; line-height: 1.5;
  color: #6b6b70; margin-bottom: 14px;
  user-select: none; -webkit-user-select: none;
}
.header b { color: #1c1c1e; font-weight: 600; }
.header select {
  font-family: inherit; font-size: 12px;
  padding: 2px 8px; margin-left: 4px;
  border-radius: 6px; border: 1px solid #d8d8db;
  background: #fff; color: #1c1c1e;
}

.sticky-top {
  position: sticky; top: 0; z-index: 10;
  margin: 0 -12px 8px;
  background: #f5f5f7;
  border-bottom: 1px solid #e8e8eb;
}
.toolbar {
  display: flex; gap: 6px; flex-wrap: wrap;
  padding: 8px 14px 6px;
  align-items: center;
  user-select: none; -webkit-user-select: none;
}
.toolbar-label {
  font-size: 11px; font-weight: 600; color: #8e8e93;
  text-transform: uppercase; letter-spacing: 0.05em;
  margin-right: 4px;
}
.sort-radio { position: absolute; opacity: 0; pointer-events: none; }
.sort-btn {
  font: inherit; font-size: 12px; font-weight: 500;
  border: 1px solid #d8d8db; background: #fff; color: #1c1c1e;
  border-radius: 999px; padding: 4px 10px;
  cursor: pointer; user-select: none; -webkit-user-select: none;
}
#sort-composite:checked ~ .sticky-top label[for="sort-composite"],
#sort-cash:checked      ~ .sticky-top label[for="sort-cash"],
#sort-sector:checked    ~ .sticky-top label[for="sort-sector"],
#sort-ticker:checked    ~ .sticky-top label[for="sort-ticker"] {
  background: #1c1c1e; color: #fff; border-color: #1c1c1e;
}

#sort-composite:checked ~ .section .list .row { order: var(--r-c, 0); }
#sort-cash:checked      ~ .section .list .row { order: var(--r-cash, 0); }
#sort-sector:checked    ~ .section .list .row { order: var(--r-sec, 0); }
#sort-ticker:checked    ~ .section .list .row { order: var(--r-tick, 0); }
#sort-mktcap:checked    ~ .section .list .row { order: var(--r-mkt, 0); }

/* Weighting scheme toggle: hide all three cash-mini variants by default,
   then reveal whichever one the active radio matches. */
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
  background: #1c1c1e; color: #fff; border-color: #1c1c1e;
}

.list { display: flex; flex-direction: column; gap: 6px; }

details.section {
  background: #ffffff;
  border-radius: 12px;
  margin-bottom: 12px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
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
  border: solid #b0b0b5; border-width: 0 2px 2px 0;
  padding: 4px;
  transform: rotate(45deg);
  margin-left: 12px; flex: 0 0 auto;
  transition: transform 0.15s;
}
details.section[open] > summary::after { transform: rotate(-135deg); }
.section-head { display: flex; flex-direction: column; flex: 1 1 auto; min-width: 0; }
.section-title { font-size: 16px; font-weight: 600; color: #1c1c1e; }
.section-subtitle { font-size: 12px; color: #6b6b70; margin-top: 2px; }
.section-body { padding: 0 12px 12px; }
.weighting-toggle {
  display: flex; gap: 6px; flex-wrap: wrap;
  align-items: center;
  padding: 4px 4px 10px;
  user-select: none; -webkit-user-select: none;
}
.section-body .list-header {
  padding: 4px 4px 8px;
  display: grid;
  grid-template-columns: 30px 1fr 80px;
  column-gap: 10px;
  font-size: 11px; font-weight: 600;
  color: #8e8e93;
  text-transform: uppercase; letter-spacing: 0.05em;
  user-select: none; -webkit-user-select: none;
}
.section-body .list-header .col-rank { text-align: center; }
.section-body .list-header .col-comp { text-align: right; }

.hrp-row {
  background: #ffffff;
  border-radius: 10px;
  padding: 10px 14px;
  display: grid;
  grid-template-columns: 30px 1fr 80px;
  grid-template-rows: auto auto;
  column-gap: 10px; row-gap: 2px;
  align-items: center;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.hrp-row .rank {
  grid-row: 1 / span 2; grid-column: 1;
  font-size: 13px; color: #8e8e93;
  font-variant-numeric: tabular-nums; text-align: center;
}
.hrp-row .ticker {
  grid-row: 1; grid-column: 2;
  font-weight: 600; font-size: 17px; letter-spacing: -0.01em;
}
.hrp-pill {
  grid-row: 1; grid-column: 3;
  justify-self: end;
  font-variant-numeric: tabular-nums;
  font-weight: 600; font-size: 14px;
  padding: 3px 10px; border-radius: 999px;
  background: #ececef; color: #1c1c1e;
  white-space: nowrap;
}
.hrp-row .meta {
  grid-row: 2; grid-column: 2;
  font-size: 13px; color: #6b6b70;
  display: flex; align-items: baseline; gap: 6px;
  min-width: 0;
}
.hrp-row .meta .name {
  flex: 1 1 auto; min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: #1c1c1e;
}
.hrp-row .meta .dot { flex: 0 0 auto; opacity: 0.5; }
.hrp-row .meta .sector { flex: 0 0 auto; white-space: nowrap; }
.hrp-row .cash-mini {
  grid-row: 2; grid-column: 3;
  justify-self: end; text-align: right;
  font-size: 12px; color: #6b6b70;
  font-variant-numeric: tabular-nums; white-space: nowrap;
}

details.sub-drawer {
  margin-top: 12px;
  padding: 8px 12px;
  background: #f5f5f7;
  border-radius: 8px;
}
details.sub-drawer > summary {
  cursor: pointer; list-style: none;
  font-size: 13px; font-weight: 600;
  color: #4b4b50;
  user-select: none; -webkit-user-select: none;
}
details.sub-drawer > summary::-webkit-details-marker { display: none; }
details.sub-drawer > summary::before {
  content: '\\203A'; color: #b0b0b5;
  margin-right: 6px;
  display: inline-block;
  transition: transform 0.15s;
}
details.sub-drawer[open] > summary::before { transform: rotate(90deg); }
details.sub-drawer p {
  font-size: 13px; line-height: 1.5;
  color: #4b4b50; margin: 8px 0;
}

.bt-table {
  display: flex; flex-direction: column;
  font-size: 13px;
}
.bt-row {
  display: grid;
  grid-template-columns: 1.2fr repeat(3, 1fr);
  column-gap: 8px;
  padding: 6px 4px;
  align-items: baseline;
  border-bottom: 1px solid #ececef;
}
.bt-row:last-child { border-bottom: none; }
.bt-row.bt-head { color: #8e8e93; font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.04em;
}
.bt-label { color: #1c1c1e; font-weight: 500; }
.bt-cell {
  font-variant-numeric: tabular-nums; text-align: right;
  color: #1c1c1e;
}
.bt-cell.ret { font-weight: 600; }
.bt-cell.dd { color: #b8434b; }
.bt-caveat {
  font-size: 12px; line-height: 1.5;
  color: #8e8e93; margin: 12px 0 0;
}

.methodology-body h3 {
  font-size: 13px; font-weight: 600;
  margin: 14px 0 4px; color: #1c1c1e;
}
.methodology-body h3:first-child { margin-top: 4px; }
.methodology-body p {
  font-size: 13px; line-height: 1.5;
  color: #4b4b50; margin: 0 0 8px;
}

details.row {
  background: #ffffff;
  border-radius: 10px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  overflow: hidden;
}
details.row > summary {
  list-style: none;
  cursor: pointer;
  padding: 10px 14px;
  display: grid;
  grid-template-columns: 30px 1fr 80px;
  grid-template-rows: auto auto;
  column-gap: 10px;
  row-gap: 2px;
  align-items: center;
}
details.row > summary::-webkit-details-marker { display: none; }
details.row > summary::marker { display: none; }
.rank {
  grid-row: 1 / span 2; grid-column: 1;
  font-size: 13px; color: #8e8e93;
  font-variant-numeric: tabular-nums;
  text-align: center;
}
.ticker {
  grid-row: 1; grid-column: 2;
  font-weight: 600; font-size: 17px;
  letter-spacing: -0.01em;
}
.pill {
  grid-row: 1; grid-column: 3;
  justify-self: end;
  font-variant-numeric: tabular-nums;
  font-weight: 600; font-size: 14px;
  padding: 3px 10px; border-radius: 999px;
  white-space: nowrap;
}
.cash-mini {
  grid-row: 2; grid-column: 3;
  justify-self: end; text-align: right;
  font-size: 12px; color: #6b6b70;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.meta {
  grid-row: 2; grid-column: 2;
  font-size: 13px; color: #6b6b70;
  display: flex; align-items: baseline; gap: 6px;
  min-width: 0;
}
.meta .name {
  flex: 1 1 auto; min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: #1c1c1e;
}
.meta .dot { flex: 0 0 auto; opacity: 0.5; }
.meta .sector { flex: 0 0 auto; white-space: nowrap; }
.full-name {
  font-size: 13px; color: #6b6b70;
  margin-top: 10px; margin-bottom: -2px;
}

.expanded { padding: 0 14px 14px; }
.expanded .divider { border-top: 1px solid #e8e8eb; margin: 0 0 12px; }

.factors {
  display: grid;
  grid-template-columns: 1fr auto auto;
  column-gap: 18px; row-gap: 6px;
  font-size: 14px;
}
.factors .label { color: #1c1c1e; }
.factors .z, .factors .contrib {
  font-variant-numeric: tabular-nums; text-align: right;
}
.factors .z { color: #6b6b70; }
.factors .contrib { color: #1c1c1e; font-weight: 500; }
.factors .contrib .w { color: #8e8e93; font-weight: 400; margin-left: 4px; }
.factors .total .label,
.factors .total .contrib { font-weight: 600; }
.factors .total .label,
.factors .total .z,
.factors .total .contrib {
  border-top: 1px solid #e8e8eb;
  padding-top: 6px; margin-top: 2px;
}
.factors .muted { color: #b0b0b5; }

.explain {
  font-size: 13px; line-height: 1.5;
  color: #4b4b50; margin-top: 14px;
}
.cash-line {
  font-size: 13px; color: #1c1c1e;
  margin-top: 10px;
}
.cash-line b { font-weight: 600; }

.pill.up-strong   { background: #2ecc71; color: #0d3a1f; }
.pill.up-light    { background: #d4f1e0; color: #0d3a1f; }
.pill.down-strong { background: #e74c3c; color: #4a0e08; }
.pill.down-light  { background: #fbe1de; color: #4a0e08; }
.pill.flat        { background: #ececef; color: #1c1c1e; }

@media (prefers-color-scheme: dark) {
  body { color: #ececec; background: #000000; }
  .header { color: #8e8e93; }
  .header b { color: #ececec; }
  .header select { background: #1c1c1e; color: #ececec; border-color: #3a3a3c; }
  .sticky-top { background: #000000; border-bottom-color: #2c2c2e; }
  .toolbar-label { color: #8e8e93; }
  .sort-btn { background: #1c1c1e; color: #ececec; border-color: #3a3a3c; }
  #sort-composite:checked ~ .sticky-top label[for="sort-composite"],
  #sort-cash:checked      ~ .sticky-top label[for="sort-cash"],
  #sort-sector:checked    ~ .sticky-top label[for="sort-sector"],
  #sort-ticker:checked    ~ .sticky-top label[for="sort-ticker"] {
    background: #ececec; color: #000; border-color: #ececec;
  }
  .section-body .list-header { color: #8e8e93; }
  details.section { background: #1c1c1e; box-shadow: none; }
  details.section > summary::after { border-color: #8e8e93; }
  .section-title { color: #ececec; }
  .section-subtitle { color: #8e8e93; }
  .methodology-body h3 { color: #ececec; }
  .methodology-body p { color: #aeaeb2; }
  .bt-row { border-bottom-color: #2c2c2e; }
  .bt-label { color: #ececec; }
  .bt-cell { color: #ececec; }
  .bt-cell.dd { color: #ff6e75; }
  .bt-caveat { color: #8e8e93; }
  details.row { background: #1c1c1e; box-shadow: none; }
  .hrp-row { background: #1c1c1e; box-shadow: none; }
  .hrp-row .ticker { color: #ececec; }
  .hrp-row .meta { color: #8e8e93; }
  .hrp-row .meta .name { color: #ececec; }
  .hrp-row .rank, .hrp-row .cash-mini { color: #8e8e93; }
  .hrp-pill { background: #2c2c2e; color: #ececec; }
  details.sub-drawer { background: #2c2c2e; }
  details.sub-drawer > summary { color: #aeaeb2; }
  details.sub-drawer p { color: #aeaeb2; }
  .cash-mini { color: #8e8e93; }
  .ticker { color: #ececec; }
  .meta { color: #8e8e93; }
  .meta .name { color: #ececec; }
  .full-name { color: #8e8e93; }
  .rank { color: #8e8e93; }
  .expanded .divider { border-top-color: #2c2c2e; }
  .factors .label, .factors .contrib { color: #ececec; }
  .factors .z { color: #8e8e93; }
  .factors .contrib .w { color: #6b6b70; }
  .factors .total .label, .factors .total .z, .factors .total .contrib {
    border-top-color: #2c2c2e;
  }
  .factors .muted { color: #6b6b70; }
  .explain { color: #aeaeb2; }
  .cash-line { color: #ececec; }
  .pill.up-light    { background: #14401f; color: #79e29c; }
  .pill.down-light  { background: #4a1410; color: #ff9c91; }
  .pill.flat        { background: #2c2c2e; color: #ececec; }
}
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
        f'<div class="z">{z_html}</div>'
        f'<div class="contrib">{contrib} {weight_html}</div>'
    )


def _row_html(
    ticker, row, names: dict, weights: dict, cash: float,
    scheme_scales: dict,
    rank_composite: dict, rank_cash: dict, rank_sector: dict,
    rank_ticker: dict, rank_mktcap: dict,
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
    factor_rows = (
        _factor_row("Momentum", weights.get("momentum"), mom_z)
        + _factor_row("Quality", weights.get("quality"), qual_z)
        + _factor_row("Value", weights.get("value"), val_z)
        + (
            '<div class="label total">Composite</div>'
            '<div class="z total"></div>'
            f'<div class="contrib total">{composite_text}</div>'
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
    order_style = (
        f"--r-c:{rank_composite.get(ticker, 0)};"
        f"--r-cash:{rank_cash.get(ticker, 0)};"
        f"--r-sec:{rank_sector.get(ticker, 0)};"
        f"--r-tick:{rank_ticker.get(ticker, 0)};"
        f"--r-mkt:{rank_mktcap.get(ticker, 0)};"
    )
    return (
        f'<details class="row" style="{order_style}" '
        f'data-eq="{eq_w}" data-ivp="{ivp_w}" data-hrp="{hrp_w}">'
        '<summary>'
        f'<span class="rank">{rank}</span>'
        f'<span class="ticker">{ticker_esc}</span>'
        f'<span class="pill {pill_cls}">{composite_text}</span>'
        f'<span class="meta">'
        f'<span class="name">{name}</span>'
        f'<span class="dot">·</span>'
        f'<span class="sector">{sector}</span>'
        f'</span>'
        f'{cash_minis}'
        '</summary>'
        '<div class="expanded">'
        '<div class="divider"></div>'
        f'{full_name_block}'
        f'<div class="factors">{factor_rows}</div>'
        f'<div class="explain">{explanation}</div>'
        f'{weight_lines}'
        '</div>'
        '</details>'
    )


def _hrp_row_html(
    ticker, row, names: dict, cash: float,
    rank_composite: dict, rank_cash: dict, rank_sector: dict, rank_ticker: dict,
) -> str:
    """Compact non-collapsible row for the Weighted Top 25 card."""
    rank_val = row.get("rank")
    rank = str(int(rank_val)) if pd.notna(rank_val) else "—"
    sector = _escape(row.get("sector") or "—")
    ticker_esc = _escape(ticker)
    full_name = names.get(ticker, ticker) or ticker
    short_name = _short_name(full_name)
    name = _escape(short_name)

    hrp_val = row.get("hrp_weight")
    hrp_w = float(hrp_val) if pd.notna(hrp_val) else 0.0
    weight_pct = f"{hrp_w*100:.2f}%" if hrp_w > 0 else "—"
    cash_amt = int(round(hrp_w * cash)) if hrp_w > 0 and cash > 0 else 0
    cash_text = f"${cash_amt:,}" if cash_amt > 0 else ""

    order_style = (
        f"--r-c:{rank_composite.get(ticker, 0)};"
        f"--r-cash:{rank_cash.get(ticker, 0)};"
        f"--r-sec:{rank_sector.get(ticker, 0)};"
        f"--r-tick:{rank_ticker.get(ticker, 0)};"
    )
    return (
        f'<div class="hrp-row" style="{order_style}" data-weight="{hrp_w}">'
        f'<span class="rank">{rank}</span>'
        f'<span class="ticker">{ticker_esc}</span>'
        f'<span class="hrp-pill">{weight_pct}</span>'
        f'<span class="meta">'
        f'<span class="name">{name}</span>'
        f'<span class="dot">·</span>'
        f'<span class="sector">{sector}</span>'
        f'</span>'
        f'<span class="cash-mini">{cash_text}</span>'
        '</div>'
    )


_LIST_HEADER = (
    '<div class="list-header">'
    '<span class="col-rank">#</span>'
    '<span class="col-name">Stock</span>'
    '<span class="col-comp">Composite</span>'
    '</div>'
)

_HRP_LIST_HEADER = (
    '<div class="list-header">'
    '<span class="col-rank">#</span>'
    '<span class="col-name">Stock</span>'
    '<span class="col-comp">Weight</span>'
    '</div>'
)


_HRP_METHODOLOGY = (
    '<details class="sub-drawer">'
    '<summary>How HRP weights are computed</summary>'
    '<p>Hierarchical Risk Parity (López de Prado, 2016). On the top 25 by '
    'composite score, build a 25×25 sample covariance from the last 504 '
    'trading days of <i>residual</i> daily log returns (each stock already '
    'orthogonalised against the market and its sector residual upstream). '
    'Convert correlations to a distance metric d_ij = √(0.5·(1 − ρ_ij)), '
    'cluster with average-link agglomerative clustering, and use the leaf '
    'order from that tree as the asset ordering.</p>'
    '<p>Recursively bisect the ordered list at each midpoint. At every split, '
    'compute the inverse-variance-weighted variance of each side and allocate '
    'weight inversely proportional to those variances. Long-only by '
    'construction; weights sum to 1.</p>'
    '<p><b>Not yet wired (future):</b> volatility targeting (scale weights to '
    'a target portfolio sigma), name caps, sector caps, shrinkage on the '
    'covariance estimator. v0.1 keeps the framework minimal so the moving '
    'parts are visible.</p>'
    '</details>'
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
    'Each component is winsorised and z-scored within its sector, combined '
    '0.50 / 0.20 / 0.30, and z-scored within sector again. Sectors with '
    'fewer than 5 finite members fall back to a universe-wide z-score so '
    'small buckets do not produce mechanically-±1 outputs.</p>'

    '<h3>Value</h3>'
    '<p>Sector-relative composite of EBIT/EV (40%) and FCF/EV (60%), where '
    'enterprise value = market_cap + totalDebt − cash. Same winsorise-and-z-'
    'within-sector treatment as Quality, with the same small-sector fallback.</p>'

    '<h3>Composite weights</h3>'
    '<p>Composite = 0.50 · Momentum + 0.30 · Quality + 0.20 · Value. '
    'Missing factors contribute zero. If the share of the universe with a '
    'finite Quality or Value z-score falls below 40%, that factor is dropped '
    'and the surviving weights renormalise.</p>'

    '<h3>Universe &amp; screener</h3>'
    '<p>Stocks live in data/universe.json plus data/universe_extra.txt. '
    'Share classes are deduped to keep the voting class (GOOGL > GOOG, '
    'BRK.A > BRK.B, PBR > PBR-A). Sector taxonomy uses the 11 SPDR sectors '
    'plus two carve-outs — Semiconductors (SOXX) and Aerospace &amp; Defense '
    '(ITA) — with industry overrides routing semis and A&amp;D names into '
    'their own buckets. expand.py uses FMP\'s screener to add the next N '
    'US-listed names by market cap, skipping anything already in the '
    'universe.</p>'

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


def render(ranked_df: pd.DataFrame, names: dict, factors_used: dict) -> str:
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
    else:
        idx_composite = idx_cash = idx_sector = idx_ticker = idx_mktcap = []
    rank_composite = {t: i for i, t in enumerate(idx_composite)}
    rank_cash = {t: i for i, t in enumerate(idx_cash)}
    rank_sector = {t: i for i, t in enumerate(idx_sector)}
    rank_ticker = {t: i for i, t in enumerate(idx_ticker)}
    rank_mktcap = {t: i for i, t in enumerate(idx_mktcap)}

    # Compact page header (criteria summary + cash dropdown).
    header_bits = [f"<b>{_format_weights(weights)}</b>"]
    if scheme and top_n:
        header_bits.append(f"Top {top_n} weighted by {scheme.replace('_', ' ')}")
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
    rows_html = "".join(
        _row_html(t, r, names, weights, cash, scheme_scales,
                  rank_composite, rank_cash, rank_sector, rank_ticker, rank_mktcap)
        for t, r in ranked_df.iterrows()
    )
    universe_total = factors_used.get("universe_total") or len(ranked_df)
    if factors_used.get("display_limit") and universe_total > len(ranked_df):
        full_subtitle = f"Top {len(ranked_df)} of {universe_total} stocks"
    else:
        full_subtitle = f"{len(ranked_df)} stocks"
    weighted_count = (ranked_df["hrp_weight"] > 0).sum() if "hrp_weight" in ranked_df.columns else 0
    if weighted_count:
        full_subtitle += f" · top {int(weighted_count)} weighted"
    if vol_target:
        full_subtitle += f" · {vol_target*100:.0f}% vol target"

    weighting_toggle = (
        '<div class="weighting-toggle">'
        '<span class="toolbar-label">Weighting</span>'
        '<label for="wt-hrp" class="sort-btn">HRP</label>'
        '<label for="wt-ivp" class="sort-btn">Inv Vol</label>'
        '<label for="wt-equal" class="sort-btn">Equal</label>'
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

    methodology_section = (
        '<details class="section">'
        '<summary>'
        '<div class="section-head">'
        '<div class="section-title">Methodology &amp; details</div>'
        '<div class="section-subtitle">Model summary, formulas, data sources</div>'
        '</div>'
        '</summary>'
        f'<div class="section-body methodology-body">{_METHODOLOGY_BODY}</div>'
        '</details>'
    )

    return (
        '<!doctype html>'
        '<html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<title>M/Q/V Ranking</title>'
        f'<style>{_CSS}</style>'
        '</head><body>'
        # Hidden sort + weighting radios at the top of body so the CSS general-
        # sibling selector reaches both the sticky toolbar and the rows below.
        f'<input type="radio" name="sort" id="sort-composite" class="sort-radio"{ " checked" if initial_sort == "composite" else "" }>'
        f'<input type="radio" name="sort" id="sort-cash" class="sort-radio"{ " checked" if initial_sort == "cash" else "" }>'
        f'<input type="radio" name="sort" id="sort-sector" class="sort-radio"{ " checked" if initial_sort == "sector" else "" }>'
        f'<input type="radio" name="sort" id="sort-ticker" class="sort-radio"{ " checked" if initial_sort == "ticker" else "" }>'
        f'<input type="radio" name="sort" id="sort-mktcap" class="sort-radio"{ " checked" if initial_sort == "mktcap" else "" }>'
        f'<input type="radio" name="weighting" id="wt-hrp" class="sort-radio"{ " checked" if initial_scheme == "hrp" else "" }>'
        f'<input type="radio" name="weighting" id="wt-ivp" class="sort-radio"{ " checked" if initial_scheme == "ivp" else "" }>'
        f'<input type="radio" name="weighting" id="wt-equal" class="sort-radio"{ " checked" if initial_scheme == "equal" else "" }>'
        f'<div class="header">{header_html}</div>'
        '<div class="sticky-top">'
        '<div class="toolbar">'
        '<span class="toolbar-label">Sort</span>'
        '<label for="sort-composite" class="sort-btn">Composite</label>'
        '<label for="sort-cash" class="sort-btn">Cash</label>'
        '<label for="sort-sector" class="sort-btn">Sector</label>'
        '<label for="sort-ticker" class="sort-btn">Ticker</label>'
        '<label for="sort-mktcap" class="sort-btn">Market Cap</label>'
        '</div>'
        '</div>'
        f'{full_section}'
        f'{backtest_section}'
        f'{methodology_section}'
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
