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
.sort-btn {
  font: inherit; font-size: 12px; font-weight: 500;
  border: 1px solid #d8d8db; background: #fff; color: #1c1c1e;
  border-radius: 999px; padding: 4px 10px;
  cursor: pointer;
}
.sort-btn.active { background: #1c1c1e; color: #fff; border-color: #1c1c1e; }

.list-header {
  padding: 6px 14px 8px;
  display: grid;
  grid-template-columns: 30px 1fr 80px;
  column-gap: 10px;
  font-size: 11px; font-weight: 600;
  color: #8e8e93;
  text-transform: uppercase; letter-spacing: 0.05em;
  user-select: none; -webkit-user-select: none;
}
.list-header .col-rank { text-align: center; }
.list-header .col-comp { text-align: right; }
.list { display: flex; flex-direction: column; gap: 6px; }

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

details.methodology {
  margin-top: 18px;
  background: #ffffff;
  border-radius: 14px;
  padding: 12px 14px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
details.methodology > summary {
  cursor: pointer; list-style: none;
  font-weight: 600; font-size: 14px;
  color: #1c1c1e;
  display: flex; justify-content: space-between; align-items: center;
}
details.methodology > summary::-webkit-details-marker { display: none; }
details.methodology > summary::after { content: '\\203A'; color: #b0b0b5; transition: transform 0.15s; }
details.methodology[open] > summary::after { transform: rotate(90deg); }
details.methodology h3 {
  font-size: 13px; font-weight: 600;
  margin: 14px 0 4px; color: #1c1c1e;
}
details.methodology p {
  font-size: 13px; line-height: 1.5;
  color: #4b4b50; margin: 0 0 8px;
}

@media (prefers-color-scheme: dark) {
  body { color: #ececec; background: #000000; }
  .header { color: #8e8e93; }
  .header b { color: #ececec; }
  .header select { background: #1c1c1e; color: #ececec; border-color: #3a3a3c; }
  .sticky-top { background: #000000; border-bottom-color: #2c2c2e; }
  .toolbar-label { color: #8e8e93; }
  .sort-btn { background: #1c1c1e; color: #ececec; border-color: #3a3a3c; }
  .sort-btn.active { background: #ececec; color: #000; border-color: #ececec; }
  .list-header { color: #8e8e93; }
  details.row { background: #1c1c1e; box-shadow: none; }
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
  details.methodology { background: #1c1c1e; box-shadow: none; }
  details.methodology > summary { color: #ececec; }
  details.methodology h3 { color: #ececec; }
  details.methodology p { color: #aeaeb2; }
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
  var list = document.querySelector('.list');
  if (!list) return;
  var rows = Array.prototype.slice.call(list.querySelectorAll('details.row'));
  var btns = document.querySelectorAll('.sort-btn');
  var cashSelect = document.getElementById('cashSelect');

  function applySort(key) {
    var asc = (key === 'sector' || key === 'ticker');
    var sorted = rows.slice().sort(function (a, b) {
      var av = a.dataset[key], bv = b.dataset[key];
      if (key === 'composite' || key === 'cash') {
        av = parseFloat(av); bv = parseFloat(bv);
        if (!isFinite(av)) av = -Infinity;
        if (!isFinite(bv)) bv = -Infinity;
      } else {
        av = (av || '').toLowerCase(); bv = (bv || '').toLowerCase();
      }
      if (av < bv) return asc ? -1 : 1;
      if (av > bv) return asc ? 1 : -1;
      return 0;
    });
    sorted.forEach(function (r) { list.appendChild(r); });
    btns.forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-sort') === key);
    });
  }

  function applyCash() {
    if (!cashSelect) return;
    var c = parseFloat(cashSelect.value);
    if (!isFinite(c) || c <= 0) return;
    rows.forEach(function (r) {
      var w = parseFloat(r.dataset.weight) || 0;
      var amt = w > 0 ? Math.round(w * c) : 0;
      r.dataset.cash = amt;
      var mini = r.querySelector('.cash-mini');
      if (mini) mini.textContent = amt > 0 ? '$' + amt.toLocaleString() : '';
      var line = r.querySelector('.cash-line');
      if (line && amt > 0) {
        line.innerHTML = 'Cash: <b>$' + amt.toLocaleString() + '</b> of $'
          + Math.round(c).toLocaleString() + ' (' + (w * 100).toFixed(2) + '%)';
      } else if (line) {
        line.innerHTML = '';
      }
    });
    var active = document.querySelector('.sort-btn.active');
    if (active && active.getAttribute('data-sort') === 'cash') applySort('cash');
  }

  btns.forEach(function (b) {
    b.addEventListener('click', function () {
      applySort(b.getAttribute('data-sort'));
    });
  });
  if (cashSelect) cashSelect.addEventListener('change', applyCash);

  applySort('{INITIAL}');
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


def render(ranked_df: pd.DataFrame, names: dict, factors_used: dict) -> str:
    weights = factors_used.get("weights", {})
    scheme = factors_used.get("weighting_scheme", "")
    top_n = factors_used.get("top_n")
    cash = float(factors_used.get("cash_deployment") or 0)
    initial_sort = factors_used.get("sort", "composite")

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

    rows_html = []
    for ticker, row in ranked_df.iterrows():
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

        weight_val = row.get("weight")
        weight = float(weight_val) if pd.notna(weight_val) else 0.0

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

        cash_amt = int(round(weight * cash)) if weight > 0 and cash > 0 else 0
        cash_mini_html = (
            f'<span class="cash-mini">${cash_amt:,}</span>' if cash_amt > 0 else
            '<span class="cash-mini"></span>'
        )
        cash_block = ""
        if cash_amt > 0:
            cash_block = (
                f'<div class="cash-line">Cash: <b>${cash_amt:,}</b> '
                f'of ${int(round(cash)):,} ({weight*100:.2f}%)</div>'
            )

        explanation = _explain(mom_z, qual_z, val_z)
        comp_data = composite if composite is not None else ""
        sector_raw = (row.get("sector") or "").replace('"', "")

        rows_html.append(
            f'<details class="row" '
            f'data-composite="{comp_data}" '
            f'data-cash="{cash_amt}" '
            f'data-weight="{weight}" '
            f'data-sector="{_escape(sector_raw)}" '
            f'data-ticker="{ticker_esc}">'
            '<summary>'
            f'<span class="rank">{rank}</span>'
            f'<span class="ticker">{ticker_esc}</span>'
            f'<span class="pill {pill_cls}">{composite_text}</span>'
            f'<span class="meta">'
            f'<span class="name">{name}</span>'
            f'<span class="dot">·</span>'
            f'<span class="sector">{sector}</span>'
            f'</span>'
            f'{cash_mini_html}'
            '</summary>'
            '<div class="expanded">'
            '<div class="divider"></div>'
            f'{full_name_block}'
            f'<div class="factors">{factor_rows}</div>'
            f'<div class="explain">{explanation}</div>'
            f'{cash_block}'
            '</div>'
            '</details>'
        )

    methodology = (
        '<details class="methodology">'
        '<summary>Methodology &amp; details</summary>'
        '<h3>Momentum</h3>'
        '<p>Risk-adjusted residual momentum. Each stock\'s daily log returns are '
        'residualised in two stages: first the sector ETF is regressed on the '
        'market (VTI) over the last 504 trading days to extract a market-orthogonal '
        'sector residual, then each stock is regressed on [market, sector residual] '
        'over the same window. The 12-1 sleeve sums residuals over t-252 to t-22; '
        'the 6-1 sleeve sums over t-126 to t-22. Both are scaled by a 63-day '
        'residual sigma (no skip, not annualised, with a 1e-6 floor). Each sleeve '
        'is winsorised at 5/95 and z-scored across the universe, combined 50/50, '
        'and z-scored once more.</p>'
        '<h3>Quality</h3>'
        '<p>Sector-relative composite of (1) gross profitability = grossProfit / '
        'totalAssets, (2) year-over-year change in gross profitability, and (3) '
        'balance-sheet quality = −(totalDebt − cash) / totalAssets. Each component '
        'is winsorised and z-scored within sector, combined 0.50 / 0.20 / 0.30, '
        'and z-scored within sector again. Sectors with fewer than 5 finite '
        'members fall back to a universe-wide z-score for those names.</p>'
        '<h3>Value</h3>'
        '<p>Sector-relative composite of EBIT/EV (40%) and FCF/EV (60%). '
        'Enterprise value = market_cap + totalDebt − cash. Same winsorise-and-z-'
        'within-sector treatment as Quality, with the same small-sector fallback.</p>'
        '<h3>Composite</h3>'
        '<p>Weighted sum of factor z-scores: 0.50 momentum + 0.30 quality + 0.20 '
        'value. Missing factors contribute zero. If the share of universe with a '
        'finite quality or value z-score falls below 40%, that factor is dropped '
        'and the surviving weights renormalise.</p>'
        '<h3>Universe</h3>'
        '<p>Stocks loaded from data/universe.json plus data/universe_extra.txt. '
        'Share classes deduped to keep the voting class (GOOGL > GOOG, BRK.A > '
        'BRK.B, PBR > PBR-A). Sector ETFs: the 11 SPDRs plus SOXX (Semiconductors) '
        'and ITA (Aerospace &amp; Defense), with industry overrides routing semis '
        'and A&amp;D names into their own buckets.</p>'
        '<h3>Portfolio weighting</h3>'
        '<p>The top N composite-ranked names are weighted by the configured scheme '
        '(equal, inverse volatility, or equal risk contribution) over a 252-day '
        'daily-returns window. Cash per name = weight × deployment, rounded.</p>'
        '<h3>Data source &amp; cache</h3>'
        '<p>Financial Modeling Prep (stable + legacy v3): daily prices, annual '
        'income / balance / cash-flow statements, and company profiles. Cached '
        'locally with per-ticker freshness for fundamentals and profiles, and '
        'global freshness (5 days) for prices.</p>'
        '<h3>Caveats</h3>'
        '<p>Annual fundamentals can be up to 12 months stale. Shares outstanding '
        'come from the latest annual income statement. Beta is a single-window '
        'estimate over 504 days, not rolling. Not investment advice.</p>'
        '</details>'
    )

    return (
        '<!doctype html>'
        '<html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<title>M/Q/V Ranking</title>'
        f'<style>{_CSS}</style>'
        '</head><body>'
        f'<div class="header">{header_html}</div>'
        '<div class="sticky-top">'
        '<div class="toolbar">'
        '<span class="toolbar-label">Sort</span>'
        '<button class="sort-btn" data-sort="composite">Composite</button>'
        '<button class="sort-btn" data-sort="cash">Cash</button>'
        '<button class="sort-btn" data-sort="sector">Sector</button>'
        '<button class="sort-btn" data-sort="ticker">Ticker</button>'
        '</div>'
        '<div class="list-header">'
        '<span class="col-rank">#</span>'
        '<span class="col-name">Stock</span>'
        '<span class="col-comp">Composite</span>'
        '</div>'
        '</div>'
        f'<div class="list">{"".join(rows_html)}</div>'
        f'{methodology}'
        f'{_JS.replace("{INITIAL}", initial_sort)}'
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
