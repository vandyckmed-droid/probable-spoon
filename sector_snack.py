"""Emit the sector ranking as an Expo Snack app and publish it.

The desktop 11 x 25 heatmap is kept, not inverted: each sector wraps its 25
tickers into a grid sized to the screen, shaded on the same within-sector z,
so all 275 names are on one scroll with nothing hidden behind a tap. Tapping a
cell costs one line and returns the company name. Labels are plain words with
the maths behind a "How this works" panel. The numbers are fetched at run time
with the published snapshot as the offline fallback.

    python3 sector_snack.py            # write feed/sector_feed.json + out/App.js
    python3 sector_snack.py --publish  # ...and push it to snack.expo.dev
"""
import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

import config

SNACK_SAVE_URL = "https://exp.host/--/api/v2/snack/save"
SNACK_SDK_VERSION = "57.0.0"

SHORT_NAMES = {
    "Communication Services": "Communication",
    "Consumer Cyclical": "Consumer — wants",
    "Consumer Defensive": "Consumer — needs",
    "Basic Materials": "Materials",
}

# Plain-word gloss for each sector, so the list reads without a finance degree.
SECTOR_GLOSS = {
    "Technology": "chips, software, hardware",
    "Industrials": "machinery, aerospace, transport",
    "Energy": "oil, gas, drilling, pipelines",
    "Basic Materials": "metals, mining, chemicals",
    "Consumer Defensive": "food, drink, household staples",
    "Consumer Cyclical": "cars, retail, travel, leisure",
    "Real Estate": "landlords and property owners",
    "Healthcare": "drugs, devices, insurers, hospitals",
    "Communication Services": "telecom, media, internet",
    "Utilities": "power, water, gas networks",
    "Financial Services": "banks, insurers, payments",
}

APP_TEMPLATE = r"""
import React, { useCallback, useEffect, useState } from 'react';
import {
  SafeAreaView, ScrollView, View, Text, Pressable, useColorScheme,
  StatusBar, Platform, RefreshControl, useWindowDimensions,
} from 'react-native';

// The numbers baked in when this bundle was published — the offline fallback,
// and the whole story when no feed is configured.
const BAKED = __DATA__;

// Where to look for fresher numbers. Keeping the numbers out of the bundle is
// what lets this link stay valid: the code never changes, so it never needs
// republishing, so the link never moves.
const FEED = __FEED__;

const LIGHT = {
  ground: '#f6f7f6', surface: '#ffffff', ink: '#14201d', muted: '#5d6c68',
  faint: '#8a9994', rule: '#dfe4e1', ruleSoft: '#ecefed',
  pos: '#1d6b5f', neg: '#a64a32',
  n3: '#c9765c', n2: '#ddA48d', n1: '#eecdbe', z0: '#dde3e0',
  p1: '#bcdcd4', p2: '#8ec8ba', p3: '#4fa694', na: '#e4e8e6',
};
const DARK = {
  ground: '#0f1513', surface: '#161e1c', ink: '#e6ece9', muted: '#8fa09b',
  faint: '#6d7d78', rule: '#26302e', ruleSoft: '#1d2624',
  pos: '#58bfad', neg: '#d8735a',
  n3: '#a4523b', n2: '#7b3d2c', n1: '#4a2c22', z0: '#2a3432',
  p1: '#204740', p2: '#2b6a5c', p3: '#3f9482', na: '#1a201f',
};

const MONO = Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' });

function shade(z) {
  if (z === null || z === undefined) return 'na';
  if (z < -1.5) return 'n3';
  if (z < -0.75) return 'n2';
  if (z < -0.25) return 'n1';
  if (z < 0.25) return 'z0';
  if (z < 0.75) return 'p1';
  if (z < 1.5) return 'p2';
  return 'p3';
}

const pct = (x) => (x === null || x === undefined ? '—' : Math.round(x * 100) + '%');
const signed = (x) => (x >= 0 ? '+' : '') + x.toFixed(2);

function ordinal(n) {
  const tail = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (tail[(v - 20) % 10] || tail[v] || tail[0]);
}

/** One ticker, shaded on its within-sector z. The whole screen is these. */
function Cell({ c, t, w, picked, onPress }) {
  return (
    <Pressable onPress={onPress} style={{ width: w, padding: 1 }}>
      <View
        style={{
          backgroundColor: t[shade(c.z)],
          borderRadius: 2,
          paddingVertical: 3,
          alignItems: 'center',
          borderWidth: 1,
          borderColor: picked ? t.ink : 'transparent',
        }}
      >
        <Text numberOfLines={1} style={{ color: t.ink, fontFamily: MONO, fontSize: 9.5 }}>
          {c.ticker}
        </Text>
      </View>
    </Pressable>
  );
}

/** Tapping a cell trades one line of height for the name behind the ticker. */
function Readout({ p, t }) {
  const tone = p.score === null ? t.muted : p.score < 0 ? t.neg : t.pos;
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'baseline',
        marginTop: 6,
        paddingTop: 6,
        borderTopWidth: 1,
        borderTopColor: t.ruleSoft,
      }}
    >
      <Text style={{ color: t.ink, fontFamily: MONO, fontSize: 11 }}>{p.ticker}</Text>
      <Text style={{ color: t.muted, fontSize: 11, flex: 1, marginLeft: 8 }} numberOfLines={1}>
        {p.name}
      </Text>
      <Text style={{ color: t.faint, fontSize: 10, marginLeft: 6 }}>
        {p.score === null ? 'unscored' : ordinal(p.place) + ' of ' + p.of}
      </Text>
      <Text style={{ color: tone, fontFamily: MONO, fontSize: 11, marginLeft: 8 }}>
        {p.score === null ? '—' : signed(p.score)}
      </Text>
    </View>
  );
}

function SectorBlock({ s, t, cols, peak, pick, onPick }) {
  const tone = s.score < 0 ? t.neg : t.pos;
  const w = 100 / cols + '%';
  const mine = pick && pick.sector === s.name ? pick : null;

  return (
    <View style={{ marginBottom: 12 }}>
      <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
        <Text style={{ color: t.faint, fontFamily: MONO, fontSize: 11, width: 18 }}>{s.rank}</Text>
        <Text style={{ color: t.ink, fontSize: 15, fontWeight: '600', flex: 1 }}>{s.name}</Text>
        <Text style={{ color: tone, fontFamily: MONO, fontSize: 15, fontWeight: '700' }}>
          {signed(s.score)}
        </Text>
      </View>

      <Text numberOfLines={1} style={{ color: t.faint, fontSize: 10, marginLeft: 18, marginTop: 1 }}>
        {s.gloss} · {pct(s.ret)}/yr · swing {pct(s.vol)} · {s.rising}/{s.n} up
        {s.etf ? ' · ' + s.etf + ' ' + signed(s.etfScore) : ''}
      </Text>

      {/* Length is the score's size, colour its direction — ranking at a glance. */}
      <View style={{ height: 3, marginTop: 5, marginLeft: 18, flexDirection: 'row' }}>
        <View
          style={{
            width: Math.min(Math.abs(s.score) / peak, 1) * 100 + '%',
            backgroundColor: tone,
            borderRadius: 2,
          }}
        />
      </View>

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 6 }}>
        {s.constituents.map((c, i) => (
          <Cell
            key={c.ticker}
            c={c}
            t={t}
            w={w}
            picked={!!mine && mine.ticker === c.ticker}
            onPress={() =>
              onPick(
                mine && mine.ticker === c.ticker
                  ? null
                  : { sector: s.name, ticker: c.ticker, name: c.name, score: c.score, place: i + 1, of: s.n }
              )
            }
          />
        ))}
      </View>

      {mine && <Readout p={mine} t={t} />}
    </View>
  );
}


function Legend({ t }) {
  const keys = ['n3', 'n2', 'n1', 'z0', 'p1', 'p2', 'p3'];
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 7, flexWrap: 'wrap' }}>
      <Text style={{ color: t.faint, fontSize: 10, marginRight: 5 }}>weakest</Text>
      {keys.map((k) => (
        <View
          key={k}
          style={{
            width: 18, height: 9, backgroundColor: t[k], borderRadius: 2,
            borderWidth: 1, borderColor: t.rule, marginRight: 2,
          }}
        />
      ))}
      <Text style={{ color: t.faint, fontSize: 10, marginLeft: 3 }}>strongest in its own sector</Text>
    </View>
  );
}

function Freshness({ state, asOf, t }) {
  // The as-of date shows in every state, including while the feed is in flight —
  // a screen of numbers with no date on it is worse than a slightly stale one.
  const line = {
    baked: 'Numbers from ' + asOf + '.',
    checking: 'Showing ' + asOf + ' — checking for newer…',
    live: 'Up to date — numbers from ' + asOf + '.',
    stale: 'Offline, so showing the saved numbers from ' + asOf + '.',
  }[state];
  const dot = { baked: t.faint, checking: t.faint, live: t.pos, stale: t.neg }[state];

  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 12 }}>
      <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: dot, marginRight: 7 }} />
      <Text style={{ color: t.faint, fontSize: 12, flex: 1, lineHeight: 17 }}>
        {line}
        {FEED.url ? ' Pull down to refresh.' : ''}
      </Text>
    </View>
  );
}

function Details({ t, open, onToggle, meta }) {
  return (
    <View
      style={{
        backgroundColor: t.surface,
        borderColor: t.rule,
        borderWidth: 1,
        borderRadius: 6,
        paddingHorizontal: 12,
        paddingVertical: 9,
        marginBottom: 16,
      }}
    >
      <Pressable onPress={onToggle}>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Text style={{ color: t.ink, fontSize: 14, fontWeight: '600', flex: 1 }}>
            How this works
          </Text>
          <Text style={{ color: t.faint, fontFamily: MONO, fontSize: 13 }}>{open ? '−' : '+'}</Text>
        </View>
      </Pressable>

      {open &&
        meta.details.map((d) => (
          <View key={d.title} style={{ marginTop: 12 }}>
            <Text style={{ color: t.ink, fontSize: 12, fontWeight: '600' }}>{d.title}</Text>
            <Text style={{ color: t.muted, fontSize: 12, lineHeight: 18, marginTop: 3 }}>
              {d.body}
            </Text>
          </View>
        ))}

      {open && (
        <Text style={{ color: t.faint, fontFamily: MONO, fontSize: 10, lineHeight: 15, marginTop: 12 }}>
          {meta.stamp}
        </Text>
      )}
    </View>
  );
}

/** A feed is only usable if it carries the shape the screen renders. */
function usable(d) {
  return !!(d && d.meta && d.meta.asOf && Array.isArray(d.sectors) && d.sectors.length);
}

export default function App() {
  const dark = useColorScheme() === 'dark';
  const t = dark ? DARK : LIGHT;
  const [pick, setPick] = useState(null);
  const [how, setHow] = useState(false);
  // Cells stay legible rather than stretching: more room means more columns.
  const { width } = useWindowDimensions();
  const cols = width >= 430 ? 8 : width >= 380 ? 7 : width >= 340 ? 6 : 5;
  const [data, setData] = useState(BAKED);
  const [state, setState] = useState(FEED.url ? 'checking' : 'baked');
  const [busy, setBusy] = useState(false);

  const load = useCallback((manual) => {
    if (!FEED.url) return;
    if (manual) setBusy(true);
    else setState('checking');

    // No AbortController needed: a losing race just leaves the old numbers up.
    const giveUp = new Promise((_, reject) =>
      setTimeout(() => reject(new Error('timed out')), FEED.timeoutMs)
    );
    const ask = fetch(FEED.url, { headers: { 'Cache-Control': 'no-cache' } }).then((r) => {
      if (!r.ok) throw new Error('http ' + r.status);
      return r.json();
    });

    Promise.race([ask, giveUp])
      .then((fresh) => {
        if (!usable(fresh)) throw new Error('unusable feed');
        setData(fresh);
        setState('live');
      })
      .catch(() => setState('stale'))
      .finally(() => setBusy(false));
  }, []);

  useEffect(() => { load(false); }, [load]);

  const peak = Math.max(...data.sectors.map((s) => Math.abs(s.score)));

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: t.ground }}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      <ScrollView
        contentContainerStyle={{ padding: 16, paddingBottom: 48 }}
        showsVerticalScrollIndicator={false}
        refreshControl={
          FEED.url ? (
            <RefreshControl refreshing={busy} onRefresh={() => load(true)} tintColor={t.faint} />
          ) : undefined
        }
      >
        <Text style={{ color: t.ink, fontSize: 21, fontWeight: '700', lineHeight: 25 }}>
          Which sectors are climbing?
        </Text>
        <Text style={{ color: t.muted, fontSize: 12, marginTop: 5, lineHeight: 17 }}>
          {data.meta.blurb}
        </Text>

        <Freshness state={state} asOf={data.meta.asOf} t={t} />
        <Legend t={t} />

        <View style={{ height: 14 }} />

        <Details t={t} open={how} onToggle={() => setHow(!how)} meta={data.meta} />

        {data.sectors.map((s) => (
          <SectorBlock
            key={s.name}
            s={s}
            t={t}
            cols={cols}
            peak={peak}
            pick={pick}
            onPick={setPick}
          />
        ))}

        <Text style={{ color: t.faint, fontSize: 11, lineHeight: 17, marginTop: 8 }}>
          {data.meta.footer}
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}
"""


def build_data(payload: dict) -> dict:
    """Trim the full payload to what the phone build renders."""
    etfs = (payload.get("benchmark") or {}).get("etfs") or {}
    first = payload["sectors"][0]
    obs = first["window_obs"]
    long_days = config.MOM_9_1_LONG_DAYS
    skip_days = config.MOM_9_1_SKIP_DAYS
    rho = (payload.get("benchmark") or {}).get("rank_correlation")

    sectors = []
    for s in payload["sectors"]:
        etf = etfs.get(s["sector"])
        sectors.append({
            "name": SHORT_NAMES.get(s["sector"], s["sector"]),
            "gloss": SECTOR_GLOSS.get(s["sector"], ""),
            "rank": s["rank"],
            "score": round(s["score"], 4),
            "ret": round(s["ann_log_return"], 5),
            "vol": round(s["ann_vol"], 5),
            "n": s["n_constituents"],
            "rising": round(s["breadth"] * s["n_constituents"]),
            "etf": etf["etf"] if etf else "",
            "etfScore": round(etf["score"], 3) if etf else None,
            "constituents": [
                {
                    "ticker": c["ticker"],
                    "name": trim_company(c.get("name") or c["ticker"]),
                    "score": None if c["score"] is None else round(c["score"], 3),
                    "z": None if c["sector_z"] is None else round(c["sector_z"], 3),
                }
                for c in s["constituents"]
            ],
        })

    details = [
        {
            "title": "What the number means",
            "body": (
                "It is a climb-per-bump score: how much a sector rose over the stretch, "
                "divided by how roughly it got there. A sector that ground steadily upward "
                "beats one that ended in the same place after wild swings. Above about 1.0 "
                "is a solid climb; near zero is going nowhere; below zero is falling."
            ),
        },
        {
            "title": "Which stretch of time",
            "body": (
                f"The nine months from {first['window_start']} to {first['window_end']}. "
                "The most recent few weeks are deliberately left out — fresh moves tend to "
                "snap back, and skipping them is the standard guard against being fooled by "
                "a short bounce."
            ),
        },
        {
            "title": "What a sector is here",
            "body": (
                f"Not a real fund. Each one is a made-up basket of that sector's "
                f"{config.SECTOR_INDEX_SIZE} biggest, most-traded US companies, held in equal "
                "amounts. Equal amounts means one giant company cannot speak for the whole "
                "sector. The 'big-fund version' column is the real SPDR fund for that sector, "
                "scored the same way, as a sanity check."
            ),
        },
        {
            "title": "Names rising",
            "body": (
                f"How many of the {config.SECTOR_INDEX_SIZE} companies climbed on their own. "
                "A sector can look strong "
                "while only a handful of names did the work — this column tells you which is "
                "which."
            ),
        },
        {
            "title": "Worth knowing",
            "body": (
                "The baskets use today's most-traded companies applied to past prices, so the "
                "history flatters them a little — the names that stumbled badly are no longer "
                "in the list. This ranks sectors as they stand today. It is not a trading "
                "record, and it is not advice."
                + (f" Agreement with the real sector funds: {rho:.0%}." if rho else "")
            ),
        },
    ]

    return {
        "meta": {
            "asOf": pretty_date(payload["as_of"]),
            "blurb": (
                f"{len(sectors)} corners of the US market, best first, by how steadily they "
                f"climbed over nine months. Every square is one of the "
                f"{config.SECTOR_INDEX_SIZE} companies in that sector — tap one for its name."
            ),
            "footer": (
                "Prices from FMP, adjusted for splits and dividends. Information only — "
                "not investment advice."
            ),
            "stamp": (
                f"window {first['window_start']} → {first['window_end']} · {obs} trading days "
                f"(t−{long_days}d to t−{skip_days}d) · prices through {payload['as_of']} · "
                f"{sum(s['n_constituents'] for s in payload['sectors'])} companies"
            ),
            "details": details,
        },
        "sectors": sectors,
    }


COMPANY_SUFFIXES = (
    " Corporation", " Incorporated", " Company", ", Inc.", " Inc.", " Corp.",
    " Co., Ltd.", " Ltd.", " plc", " PLC", " N.V.", " S.A.", " Holdings, Inc",
    " Group, Inc", " Company, LLC", " LLC", " L.P.", " Trust, Inc",
)


def trim_company(name: str) -> str:
    """Drop the legal boilerplate so the name fits a phone row."""
    out = name.strip()
    changed = True
    while changed:
        changed = False
        for suffix in COMPANY_SUFFIXES:
            if out.lower().endswith(suffix.lower()):
                out = out[: -len(suffix)].rstrip(" ,")
                changed = True
    return out or name


MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def pretty_date(iso: str) -> str:
    """2026-08-10 -> 10 August 2026, without pulling in a date library."""
    try:
        year, month, day = (int(p) for p in iso.split("-"))
        return f"{day} {MONTHS[month - 1]} {year}"
    except (ValueError, IndexError):
        return iso


def render_app(payload: dict, *, feed_url: str = "") -> str:
    data = json.dumps(build_data(payload), separators=(",", ":"))
    feed = json.dumps(
        {"url": feed_url or "", "timeoutMs": config.SECTOR_FEED_TIMEOUT_MS},
        separators=(",", ":"),
    )
    return (
        APP_TEMPLATE
        .replace("__DATA__", data)
        .replace("__FEED__", feed)
        .lstrip("\n")
    )


def publish(source: str, *, name: str, description: str) -> dict:
    body = {
        "manifest": {
            "sdkVersion": SNACK_SDK_VERSION,
            "name": name,
            "description": description,
            "dependencies": {},
        },
        "code": {"App.js": {"contents": source, "type": "CODE"}},
        "dependencies": {},
    }
    req = urllib.request.Request(
        SNACK_SAVE_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--publish", action="store_true", help="upload to snack.expo.dev")
    ap.add_argument(
        "--feed-url",
        default=config.SECTOR_FEED_URL,
        help="URL the app polls for fresher numbers (default: config.SECTOR_FEED_URL)",
    )
    args = ap.parse_args()

    src = Path(config.SECTOR_OUTPUT_DIR) / "sector_etf_ranking.json"
    if not src.exists():
        raise SystemExit(f"{src} not found — run sector_index.py first")
    with open(src, encoding="utf-8") as f:
        payload = json.load(f)

    out_dir = Path(config.SECTOR_OUTPUT_DIR)

    # The feed and the baked snapshot are the same object, so a phone running
    # the published bundle and one running off the feed render identically.
    # It lands in a tracked directory, not out/: this file is the thing that
    # gets published, and its history is what a "what moved this week" view
    # would eventually read.
    feed = Path(config.SECTOR_FEED_FILE)
    feed.parent.mkdir(parents=True, exist_ok=True)
    feed.write_text(
        json.dumps(build_data(payload), separators=(",", ":")), encoding="utf-8"
    )
    print(f"wrote {feed} ({feed.stat().st_size:,} bytes)")

    source = render_app(payload, feed_url=args.feed_url)
    out = out_dir / "App.js"
    out.write_text(source, encoding="utf-8")
    print(f"wrote {out} ({len(source):,} bytes)")
    if args.feed_url:
        print(f"feed url   {args.feed_url}")
    else:
        print("feed url   (none — the app runs on the baked snapshot)")

    if args.publish:
        try:
            result = publish(
                source,
                name="Which sectors are climbing?",
                description=(
                    "US stock sectors ranked on a steady-climb score, "
                    f"prices through {payload['as_of']}"
                ),
            )
        except urllib.error.HTTPError as e:
            raise SystemExit(f"snack save failed: {e.code} {e.read().decode()[:300]}")
        snack_id = result.get("hashId") or result.get("id")
        print(f"snack id   {snack_id}")
        print(f"web        https://snack.expo.dev/{snack_id}")
        print(f"expo go    exp://exp.host/@snack/{snack_id}")


if __name__ == "__main__":
    main()
