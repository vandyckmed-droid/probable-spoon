"""Render the sector ranking payload as a standalone HTML page.

No external assets: fonts are system stacks and the heatmap is a CSS grid, so
the page renders offline and inside a strict CSP.
"""
import json
from html import escape
from pathlib import Path

import config

# Column headers in the heatmap are ~4.5rem wide; full sector names do not fit.
SHORT_NAMES = {
    "Technology": "Tech",
    "Financial Services": "Financials",
    "Healthcare": "Health",
    "Consumer Cyclical": "Cons. Cyc",
    "Consumer Defensive": "Cons. Def",
    "Industrials": "Indust.",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Real Estate": "Real Est.",
    "Basic Materials": "Materials",
    "Communication Services": "Comm. Svcs",
}

# Diverging scale on the sector-relative z, clamped at +/-1.5 sigma. The score
# itself is never clipped — only the colour saturates.
_STEPS = ((-1.5, "n3"), (-0.75, "n2"), (-0.25, "n1"), (0.25, "z0"),
          (0.75, "p1"), (1.5, "p2"))


def _step(z: float | None) -> str:
    if z is None:
        return "na"
    for edge, name in _STEPS:
        if z < edge:
            return name
    return "p3"


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def _ranking_rows(payload: dict) -> str:
    etfs = (payload.get("benchmark") or {}).get("etfs") or {}
    peak = max(abs(s["score"]) for s in payload["sectors"])
    rows = []
    for s in payload["sectors"]:
        sign = "neg" if s["score"] < 0 else "pos"
        width = abs(s["score"]) / peak * 50.0
        edge = "right:50%" if s["score"] < 0 else "left:50%"
        etf = etfs.get(s["sector"])
        etf_cell = (
            f"{etf['score']:+.2f} <span class=\"tick\">{escape(etf['etf'])}</span>"
            if etf else "&mdash;"
        )
        rows.append(f"""      <tr>
        <td class="rank">{s['rank']}</td>
        <td class="name">{escape(s['sector'])}</td>
        <td class="plot"><span class="axis"></span><span class="bar {sign}" style="width:{width:.2f}%;{edge}"></span></td>
        <td class="num score {sign}">{s['score']:+.2f}</td>
        <td class="num">{_pct(s['ann_log_return'])}</td>
        <td class="num quiet">{s['ann_vol'] * 100:.1f}%</td>
        <td class="num quiet">{s['breadth'] * 100:.0f}%</td>
        <td class="num quiet etf">{etf_cell}</td>
      </tr>""")
    return "\n".join(rows)


def _heatmap(payload: dict) -> str:
    sectors = payload["sectors"]
    cols = []
    for s in sectors:
        cells = []
        for c in s["constituents"]:
            z = c.get("sector_z")
            score = c.get("score")
            tip = (
                f"{c['name']} — {c['ticker']}\n"
                f"#{c['sector_rank']} in {s['sector']}\n"
                f"score {score:+.2f} · return {_pct(c['ann_log_return'])} · "
                f"vol {c['ann_vol'] * 100:.1f}%"
                if score is not None else f"{c['name']} — not scored"
            )
            cells.append(
                f'<div class="cell {_step(z)}" title="{escape(tip)}">'
                f'{escape(c["ticker"])}</div>'
            )
        cols.append(f"""        <div class="col">
          <div class="colhead">
            <span class="colrank">{s['rank']}</span>
            <span class="colname">{escape(SHORT_NAMES.get(s['sector'], s['sector']))}</span>
            <span class="colscore {'neg' if s['score'] < 0 else 'pos'}">{s['score']:+.2f}</span>
          </div>
{chr(10).join('          ' + c for c in cells)}
        </div>""")
    return "\n".join(cols)


def _legend() -> str:
    labels = [("n3", "−1.5σ"), ("n2", ""), ("n1", ""), ("z0", "peer avg"),
              ("p1", ""), ("p2", ""), ("p3", "+1.5σ")]
    swatches = "".join(
        f'<span class="sw {cls}"></span>' if not label
        else f'<span class="sw {cls}"></span><span class="swlab">{label}</span>'
        for cls, label in labels
    )
    return swatches


def render(payload: dict) -> str:
    first = payload["sectors"][0]
    bench = payload.get("benchmark") or {}
    rho = bench.get("rank_correlation")
    rho_line = (
        f" Rank correlation with the cap-weighted SPDR ETFs on this window: "
        f"{rho:.2f}."
        if rho is not None else ""
    )
    n_names = sum(s["n_constituents"] for s in payload["sectors"])
    long_days = config.MOM_9_1_LONG_DAYS
    skip_days = config.MOM_9_1_SKIP_DAYS
    obs = first["window_obs"]

    return f"""<title>Sector momentum: vol-adjusted 9-1</title>
<style>
  :root {{
    --ground:#f6f7f6; --surface:#ffffff; --ink:#14201d; --muted:#5d6c68;
    --rule:#dfe4e1; --rule-soft:#ecefed; --pos:#1d6b5f; --neg:#a64a32;
    --n3:#e5b09c; --n2:#eec9b9; --n1:#f5e0d6; --z0:#e9eeec;
    --p1:#d5e8e3; --p2:#b0d8ce; --p3:#86c4b6; --na:#e4e8e6;
    --serif:ui-serif,"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
    --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --ground:#0f1513; --surface:#161e1c; --ink:#e6ece9; --muted:#8fa09b;
      --rule:#26302e; --rule-soft:#1d2624; --pos:#58bfad; --neg:#d8735a;
      --n3:#6b3527; --n2:#4f2b21; --n1:#33221d; --z0:#1d2624;
      --p1:#1e3b36; --p2:#235349; --p3:#2c6f61; --na:#1a201f;
    }}
  }}
  :root[data-theme="dark"] {{
    --ground:#0f1513; --surface:#161e1c; --ink:#e6ece9; --muted:#8fa09b;
    --rule:#26302e; --rule-soft:#1d2624; --pos:#58bfad; --neg:#d8735a;
    --n3:#6b3527; --n2:#4f2b21; --n1:#33221d; --z0:#1d2624;
    --p1:#1e3b36; --p2:#235349; --p3:#2c6f61; --na:#1a201f;
  }}

  body {{
    background:var(--ground); color:var(--ink); font-family:var(--serif);
    line-height:1.55; -webkit-font-smoothing:antialiased;
  }}
  .wrap {{
    max-width:60rem; margin:0 auto;
    padding:clamp(2rem,5vw,4.5rem) clamp(1rem,4vw,2rem) 5rem;
    display:flex; flex-direction:column; gap:3.5rem;
  }}
  .eyebrow {{
    font-family:var(--sans); font-size:.68rem; font-weight:600;
    letter-spacing:.14em; text-transform:uppercase; color:var(--muted);
  }}
  h1 {{
    font-size:clamp(2rem,4.6vw,3.1rem); line-height:1.08; font-weight:600;
    letter-spacing:-.02em; text-wrap:balance; margin:.5rem 0 0;
  }}
  h2 {{
    font-size:1.35rem; font-weight:600; letter-spacing:-.01em; margin:0;
    text-wrap:balance;
  }}
  .masthead p {{ max-width:62ch; color:var(--muted); margin:.9rem 0 0; }}
  .facts {{
    display:flex; flex-wrap:wrap; gap:0 2.25rem; margin-top:1.6rem;
    padding-top:1.2rem; border-top:1px solid var(--rule);
    font-family:var(--mono); font-size:.8rem; color:var(--muted);
  }}
  .facts b {{ color:var(--ink); font-weight:500; }}

  section {{ display:flex; flex-direction:column; gap:1.1rem; }}
  .lede {{ color:var(--muted); max-width:64ch; margin:0; }}
  .scroll {{ overflow-x:auto; }}

  table {{
    width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums;
    min-width:44rem;
  }}
  th {{
    font-family:var(--sans); font-size:.66rem; font-weight:600;
    letter-spacing:.12em; text-transform:uppercase; color:var(--muted);
    text-align:right; padding:0 0 .7rem 1.5rem;
    border-bottom:1px solid var(--rule); white-space:nowrap;
  }}
  th.l {{ text-align:left; padding-left:0; }}
  td {{ padding:.62rem 0; border-bottom:1px solid var(--rule-soft); }}
  tr:last-child td {{ border-bottom:0; }}
  .rank {{
    font-family:var(--mono); font-size:.78rem; color:var(--muted);
    width:2.2rem; padding-right:.6rem;
  }}
  .name {{ font-size:1.02rem; padding-right:1.25rem; white-space:nowrap; }}
  .num {{
    font-family:var(--mono); font-size:.86rem; text-align:right;
    padding-left:1.5rem; white-space:nowrap;
  }}
  .quiet {{ color:var(--muted); }}
  .score {{ font-size:.95rem; font-weight:600; }}
  .pos {{ color:var(--pos); }}
  .neg {{ color:var(--neg); }}
  .etf .tick {{ font-size:.72rem; opacity:.7; }}
  .plot {{ position:relative; width:26%; min-width:7rem; height:1.5rem; }}
  .axis {{
    position:absolute; left:50%; top:.1rem; bottom:.1rem; width:1px;
    background:var(--rule);
  }}
  .bar {{
    position:absolute; top:.35rem; height:.55rem; border-radius:1px;
    background:var(--pos);
  }}
  .bar.neg {{ background:var(--neg); }}

  .map {{ display:flex; gap:2px; min-width:46rem; }}
  .col {{ flex:1; display:flex; flex-direction:column; gap:2px; }}
  .colhead {{
    display:flex; flex-direction:column; gap:.1rem; padding:0 .1rem .45rem;
    border-bottom:1px solid var(--rule); margin-bottom:.25rem; min-height:3.4rem;
  }}
  .colrank {{ font-family:var(--mono); font-size:.65rem; color:var(--muted); }}
  .colname {{
    font-family:var(--sans); font-size:.7rem; font-weight:600;
    line-height:1.2; letter-spacing:-.01em;
  }}
  .colscore {{
    font-family:var(--mono); font-size:.72rem; font-weight:600; margin-top:auto;
  }}
  .cell {{
    font-family:var(--mono); font-size:.63rem; letter-spacing:-.02em;
    text-align:center; padding:.28rem .1rem; border-radius:2px;
    background:var(--z0); color:var(--ink); cursor:default;
  }}
  .cell.n3 {{ background:var(--n3); }} .cell.n2 {{ background:var(--n2); }}
  .cell.n1 {{ background:var(--n1); }} .cell.z0 {{ background:var(--z0); }}
  .cell.p1 {{ background:var(--p1); }} .cell.p2 {{ background:var(--p2); }}
  .cell.p3 {{ background:var(--p3); }}
  .cell.na {{ background:var(--na); color:var(--muted); }}
  .cell:hover {{ outline:1px solid var(--ink); }}

  .legend {{
    display:flex; align-items:center; gap:.35rem; flex-wrap:wrap;
    font-family:var(--mono); font-size:.7rem; color:var(--muted);
  }}
  .sw {{
    width:1.6rem; height:.75rem; border-radius:2px; display:inline-block;
    border:1px solid var(--rule);
  }}
  .sw.n3 {{ background:var(--n3); }} .sw.n2 {{ background:var(--n2); }}
  .sw.n1 {{ background:var(--n1); }} .sw.z0 {{ background:var(--z0); }}
  .sw.p1 {{ background:var(--p1); }} .sw.p2 {{ background:var(--p2); }}
  .sw.p3 {{ background:var(--p3); }}
  .swlab {{ margin:0 .5rem 0 .15rem; }}

  .method {{
    background:var(--surface); border:1px solid var(--rule);
    padding:clamp(1.25rem,3vw,2rem); display:flex; flex-direction:column; gap:1rem;
  }}
  .method p {{ margin:0; max-width:66ch; }}
  .formula {{
    font-family:var(--mono); font-size:.78rem; line-height:1.9; color:var(--ink);
    background:var(--ground); border:1px solid var(--rule); border-radius:2px;
    padding:.9rem 1rem; overflow-x:auto; white-space:pre;
  }}
  .caveat {{
    border-left:2px solid var(--neg); padding-left:1rem; color:var(--muted);
    max-width:66ch;
  }}
  footer {{
    font-family:var(--mono); font-size:.72rem; color:var(--muted);
    border-top:1px solid var(--rule); padding-top:1.2rem;
  }}
  @media (max-width:34rem) {{ .plot {{ display:none; }} }}
</style>

<div class="wrap">
  <header class="masthead">
    <span class="eyebrow">Equal-weight sector indices &middot; {config.SECTOR_INDEX_SIZE} names each</span>
    <h1>Volatility-adjusted 9-1 momentum, sector by sector</h1>
    <p>
      {len(payload['sectors'])} synthetic sector &ldquo;ETFs&rdquo;, each an equal-weight
      basket of that sector&rsquo;s {config.SECTOR_INDEX_SIZE} most liquid US-listed
      stocks, rebalanced daily and scored on the nine months ending one month ago.
      Return and risk are measured on the same window and both annualised, so the
      score reads as return per unit of risk.
    </p>
    <div class="facts">
      <span>window <b>{first['window_start']} &rarr; {first['window_end']}</b></span>
      <span>obs <b>{obs}</b></span>
      <span>prices through <b>{payload['as_of']}</b></span>
      <span><b>{n_names}</b> names</span>
    </div>
  </header>

  <section>
    <h2>The ranking</h2>
    <p class="lede">
      Bars run from a zero axis. Breadth is the share of the 25 constituents with
      a positive score on their own &mdash; it separates a sector carried by a
      handful of names from one moving together. The last column is the
      cap-weighted SPDR ETF scored on the identical window, as a cross-check.
    </p>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th class="l" colspan="2">Sector</th>
            <th></th>
            <th>Score</th>
            <th>Ann. return</th>
            <th>Ann. vol</th>
            <th>Breadth</th>
            <th>SPDR</th>
          </tr>
        </thead>
        <tbody>
{_ranking_rows(payload)}
        </tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>Every name, shaded against its own sector</h2>
    <p class="lede">
      Each column is one sector, best-scoring name at the top. Shading is the
      name&rsquo;s z-score <em>within its own 25</em>, so colour compares a stock only
      against its sector peers, never across the page. Read each column for where
      teal turns to clay: high in the column means a sector held up by a few
      names, low means the move was broad.
    </p>
    <div class="legend">{_legend()}<span class="swlab">z within sector</span></div>
    <div class="scroll">
      <div class="map">
{_heatmap(payload)}
      </div>
    </div>
  </section>

  <section>
    <h2>How it is scored</h2>
    <div class="method">
      <p>
        9-1 momentum measures the nine months ending one month ago &mdash; the most
        recent month is skipped, the standard guard against short-term reversal. In
        trading days that is t&minus;{long_days}d to t&minus;{skip_days}d, a
        {obs}-day window. Constituents are scored exactly the same way the index is.
      </p>
      <div class="formula">numerator   = ln(L[t-{skip_days}d] / L[t-{long_days}d]) x 252 / {obs}
denominator = stdev(daily log returns, ddof=1) x sqrt(252)
score       = numerator / denominator</div>
      <p>
        Both legs sit on that same {obs}-day window and both are annualised, so the
        skipped month cannot leak into one leg without the other. The ratio is
        unitless and invariant to index level.
      </p>
      <p class="caveat">
        Membership is <em>today&rsquo;s</em> most liquid names applied to past prices, so
        the index history carries the survivorship that implies. This ranks sectors
        as they stand now; it is not a tradable backtest.{rho_line}
      </p>
    </div>
  </section>

  <footer>
    Source: Financial Modeling Prep adjusted closes, generated
    {payload['generated']}. Prices through {payload['as_of']}.
    Not investment advice.
  </footer>
</div>
"""


def write_report(payload: dict, path: Path | None = None) -> Path:
    out = path or Path(config.SECTOR_OUTPUT_DIR) / "sector_report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(payload), encoding="utf-8")
    return out


def main() -> None:
    src = Path(config.SECTOR_OUTPUT_DIR) / "sector_etf_ranking.json"
    if not src.exists():
        raise SystemExit(f"{src} not found — run sector_index.py first")
    with open(src, encoding="utf-8") as f:
        payload = json.load(f)
    print(f"wrote {write_report(payload)}")


if __name__ == "__main__":
    main()
