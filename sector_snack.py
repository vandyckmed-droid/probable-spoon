"""Emit the sector ranking as an Expo Snack app and publish it.

The heatmap does not survive a phone screen as an 11 x 25 grid, so the phone
build inverts it: a tappable list of sectors, each opening into its own 25
names as rows shaded on the same within-sector z. Labels are written in plain
words with the maths tucked behind a "How this works" panel, and the data is
baked into the bundle, so the app needs no network once Expo Go has loaded it.

    python3 sector_snack.py            # write out/App.js
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
  StatusBar, Platform, RefreshControl,
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

// Plain-word verdict for a sector's score, so the ranking reads without maths.
function verdict(score) {
  if (score >= 1.75) return 'Climbing hard';
  if (score >= 1.0) return 'Climbing steadily';
  if (score >= 0.4) return 'Drifting up';
  if (score > -0.4) return 'Going nowhere';
  if (score > -1.0) return 'Drifting down';
  return 'Falling';
}

const pct = (x) => (x === null || x === undefined ? '—' : Math.round(x * 100) + '%');
const signed = (x) => (x >= 0 ? '+' : '') + x.toFixed(2);

function Bar({ score, peak, t }) {
  const frac = Math.min(Math.abs(score) / peak, 1);
  const up = score >= 0;
  return (
    <View style={{ flexDirection: 'row', height: 6, marginTop: 12 }}>
      <View style={{ flex: 1, alignItems: 'flex-end' }}>
        {!up && (
          <View style={{ width: (frac * 100) + '%', height: 6, borderRadius: 1, backgroundColor: t.neg }} />
        )}
      </View>
      <View style={{ width: 1, backgroundColor: t.rule }} />
      <View style={{ flex: 1 }}>
        {up && (
          <View style={{ width: (frac * 100) + '%', height: 6, borderRadius: 1, backgroundColor: t.pos }} />
        )}
      </View>
    </View>
  );
}

function Stat({ label, value, t, tone }) {
  return (
    <View style={{ flex: 1 }}>
      <Text style={{ color: t.faint, fontSize: 10, lineHeight: 13 }}>{label}</Text>
      <Text style={{ color: tone || t.ink, fontFamily: MONO, fontSize: 14, marginTop: 3 }}>
        {value}
      </Text>
    </View>
  );
}

function NameRow({ c, t, last }) {
  const tone = c.score === null ? t.muted : c.score < 0 ? t.neg : t.pos;
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        paddingVertical: 7,
        borderBottomWidth: last ? 0 : 1,
        borderBottomColor: t.ruleSoft,
      }}
    >
      <View style={{ width: 4, height: 22, borderRadius: 2, backgroundColor: t[shade(c.z)] }} />
      <Text style={{ color: t.ink, fontFamily: MONO, fontSize: 12, width: 58, marginLeft: 9 }}>
        {c.ticker}
      </Text>
      <Text style={{ color: t.muted, fontSize: 12, flex: 1 }} numberOfLines={1}>
        {c.name}
      </Text>
      <Text style={{ color: tone, fontFamily: MONO, fontSize: 12, marginLeft: 8 }}>
        {c.score === null ? '—' : signed(c.score)}
      </Text>
    </View>
  );
}

function SectorCard({ s, peak, t, open, onToggle }) {
  const tone = s.score < 0 ? t.neg : t.pos;
  return (
    <Pressable
      onPress={onToggle}
      style={{
        backgroundColor: t.surface,
        borderColor: t.rule,
        borderWidth: 1,
        borderRadius: 8,
        padding: 14,
        marginBottom: 10,
      }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
        <Text style={{ color: t.faint, fontFamily: MONO, fontSize: 12, width: 22 }}>{s.rank}</Text>
        <Text style={{ color: t.ink, fontSize: 18, fontWeight: '600', flex: 1 }}>{s.name}</Text>
        <Text style={{ color: tone, fontFamily: MONO, fontSize: 18, fontWeight: '700' }}>
          {signed(s.score)}
        </Text>
      </View>

      <View style={{ flexDirection: 'row', marginLeft: 22, marginTop: 3 }}>
        <Text style={{ color: t.faint, fontSize: 12, flex: 1 }} numberOfLines={1}>
          {s.gloss}
        </Text>
        <Text style={{ color: tone, fontSize: 12, marginLeft: 8 }}>{verdict(s.score)}</Text>
      </View>

      <Bar score={s.score} peak={peak} t={t} />

      <View style={{ flexDirection: 'row', marginTop: 14, gap: 8 }}>
        <Stat label={'Gain over' + '\n' + 'the year'} value={pct(s.ret)} t={t} tone={s.ret < 0 ? t.neg : t.ink} />
        <Stat label={'Typical' + '\n' + 'swing'} value={pct(s.vol)} t={t} />
        <Stat label={'Names' + '\n' + 'rising'} value={s.rising + ' of ' + s.n} t={t} />
        <Stat
          label={'Big-fund' + '\n' + 'version'}
          value={s.etfScore === null ? '—' : signed(s.etfScore) + ' ' + s.etf}
          t={t}
        />
      </View>

      {open && (
        <View style={{ marginTop: 14, borderTopWidth: 1, borderTopColor: t.ruleSoft, paddingTop: 10 }}>
          <Text style={{ color: t.faint, fontSize: 11, marginBottom: 6, lineHeight: 16 }}>
            All {s.n} companies, strongest first. The colour bar compares a company with the
            others in its own sector — never across sectors.
          </Text>
          {s.constituents.map((c, i) => (
            <NameRow key={c.ticker} c={c} t={t} last={i === s.constituents.length - 1} />
          ))}
        </View>
      )}

      <Text style={{ color: t.faint, fontSize: 11, marginTop: 10 }}>
        {open ? 'Tap to close' : 'Tap to see all 25 companies'}
      </Text>
    </Pressable>
  );
}

function Legend({ t }) {
  const keys = ['n3', 'n2', 'n1', 'z0', 'p1', 'p2', 'p3'];
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 10, flexWrap: 'wrap' }}>
      <Text style={{ color: t.faint, fontSize: 10, marginRight: 6 }}>weakest</Text>
      {keys.map((k) => (
        <View
          key={k}
          style={{
            width: 20, height: 10, backgroundColor: t[k], borderRadius: 2,
            borderWidth: 1, borderColor: t.rule, marginRight: 2,
          }}
        />
      ))}
      <Text style={{ color: t.faint, fontSize: 10, marginLeft: 4 }}>strongest in its sector</Text>
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
        borderRadius: 8,
        padding: 14,
        marginBottom: 18,
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
  const [open, setOpen] = useState(null);
  const [how, setHow] = useState(false);
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
        <Text style={{ color: t.faint, fontSize: 11, letterSpacing: 1.2, textTransform: 'uppercase' }}>
          US shares
        </Text>
        <Text style={{ color: t.ink, fontSize: 28, fontWeight: '700', marginTop: 6, lineHeight: 33 }}>
          Which corners of the{'\n'}market are climbing?
        </Text>
        <Text style={{ color: t.muted, fontSize: 14, marginTop: 12, lineHeight: 21 }}>
          {data.meta.blurb}
        </Text>

        <Freshness state={state} asOf={data.meta.asOf} t={t} />

        <Legend t={t} />

        <View style={{ height: 18 }} />

        <Details t={t} open={how} onToggle={() => setHow(!how)} meta={data.meta} />

        {data.sectors.map((s) => (
          <SectorCard
            key={s.name}
            s={s}
            peak={peak}
            t={t}
            open={open === s.name}
            onToggle={() => setOpen(open === s.name ? null : s.name)}
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
                f"Eleven corners of the US stock market, ranked by how steadily they have "
                f"climbed over the past nine months. Tap any one to see the "
                f"{config.SECTOR_INDEX_SIZE} companies inside it."
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
