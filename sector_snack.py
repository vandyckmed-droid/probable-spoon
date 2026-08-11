"""Emit the sector ranking as an Expo Snack app and publish it.

The desktop 11 x 25 heatmap is kept, not inverted: each sector wraps its 25
tickers into a grid sized to the screen, shaded on the same within-sector z,
so all 275 names are on one scroll with nothing hidden behind a tap. Tapping a
cell costs one line and returns the company name. Labels are plain words with
the maths behind a "How this works" panel. The numbers are fetched at run time
with the published snapshot as the offline fallback.

    python3 sector_snack.py              # write out/sector_feed.json + out/App.js
    python3 sector_snack.py --push-feed  # ...and publish the numbers (a refresh)
    python3 sector_snack.py --publish    # ...and re-upload the app itself (new link!)
"""
import argparse
import json
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import config

SNACK_SAVE_URL = "https://exp.host/--/api/v2/snack/save"
SNACK_SDK_VERSION = "57.0.0"
# Ships inside Expo Go, so Snack resolves it without a build step.
SNACK_DEPENDENCIES = {"expo-haptics": "*"}

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

# One neon hue per sector, spaced around the wheel so eleven stay tellable
# apart, and picked to fit what the sector is: circuit cyan for Technology,
# flame for Energy, gold for money, a zap of yellow-green for the power grid.
SECTOR_HUE = {
    "Technology": "#1fe0ff",             # circuit cyan
    "Healthcare": "#2bf5a8",             # clinical spring green
    "Consumer Defensive": "#7bf03a",     # grocery lime
    "Utilities": "#d8f52a",              # electric yellow-green
    "Financial Services": "#ffd21e",     # gold
    "Industrials": "#ff8c1a",            # machine amber
    "Energy": "#ff5a2b",                 # flame
    "Basic Materials": "#ff4d7d",        # molten metal
    "Consumer Cyclical": "#ff3ecb",      # shopfront magenta
    "Communication Services": "#9b5cff", # broadcast violet
    "Real Estate": "#3d8bff",            # blueprint blue
}

APP_TEMPLATE = r"""
import React, { useCallback, useEffect, useState } from 'react';
import {
  SafeAreaView, ScrollView, View, Text, Pressable, useColorScheme,
  StatusBar, Platform, RefreshControl, useWindowDimensions,
} from 'react-native';
import * as Haptics from 'expo-haptics';

// Haptics are decoration: a simulator, a web preview or a phone with the
// feature switched off must not take the screen down with it.
const buzz = (fn) => { try { fn(); } catch (e) {} };
const tapped = () => buzz(() => Haptics.selectionAsync());
const pulled = () => buzz(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium));
const landed = () => buzz(() => Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success));

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

/** Blend two hex colours. t=0 keeps `from`, t=1 lands on `to`. */
function mix(from, to, t) {
  const parts = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const a = parts(from);
  const b = parts(to);
  return '#' + a
    .map((v, i) => Math.round(v + (b[i] - v) * t).toString(16).padStart(2, '0'))
    .join('');
}

/**
 * Where a name sits in its sector, 0 (weakest) to 1 (strongest). Colour now
 * says *which sector*, so brightness has to carry the score on its own — the
 * scale saturates at the same +/-1.5 sigma the old red-green ramp did.
 */
function lift(z) {
  if (z === null || z === undefined) return 0;
  return Math.max(0, Math.min(1, (z + 1.5) / 3));
}

const pct = (x) => (x === null || x === undefined ? '—' : Math.round(x * 100) + '%');
const signed = (x) => (x >= 0 ? '+' : '') + x.toFixed(2);

function ordinal(n) {
  const tail = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (tail[(v - 20) % 10] || tail[v] || tail[0]);
}

/**
 * One ticker, lit in its sector's hue at a brightness set by its score. When
 * a name is selected, everything unrelated to it drops away to near-nothing —
 * the point is to see the family, so the rest has to stop competing.
 */
function Cell({ c, t, w, hue, dark, state, onPress }) {
  const heat = lift(c.z);
  const bg = dark
    ? mix(t.ground, hue, 0.07 + 0.88 * heat)
    : mix('#ffffff', hue, 0.14 + 0.72 * heat);
  const ink = dark ? (heat > 0.5 ? '#04100d' : '#c2cfcb') : '#14201d';

  // Glow is a dark-mode affair; on a light ground it just muddies the cell.
  const glow = dark
    ? {
        shadowColor: hue,
        shadowOffset: { width: 0, height: 0 },
        shadowOpacity: 0.25 + 0.6 * heat,
        shadowRadius: 1 + 7 * heat,
        elevation: Math.round(1 + 5 * heat),
      }
    : null;

  return (
    <Pressable
      onPress={onPress}
      style={{ width: w, padding: 1, opacity: state === 'muted' ? 0.11 : 1 }}
    >
      <View
        style={{
          backgroundColor: bg,
          borderRadius: 2,
          paddingVertical: 3,
          alignItems: 'center',
          borderWidth: 1,
          borderColor:
            state === 'chosen' ? t.ink : state === 'kin' ? hue : 'transparent',
          ...(glow || {}),
        }}
      >
        <Text numberOfLines={1} style={{ color: ink, fontFamily: MONO, fontSize: 9.5 }}>
          {c.ticker}
        </Text>
      </View>
    </Pressable>
  );
}

/**
 * What the selected name is, and how much of its family lives outside its own
 * sector — the number that makes the cross-sector highlighting worth having.
 */
function Readout({ p, t, hue }) {
  const tone = p.score === null ? t.muted : p.score < 0 ? t.neg : t.pos;
  const away = p.kin.filter((k) => k.sector !== p.sector).length;
  const family = p.kin.length
    ? p.kin.length + ' move with it' + (away ? ', ' + away + ' outside this sector' : '')
    : 'nothing else moves closely with it';

  return (
    <View style={{ marginTop: 7, paddingTop: 7, borderTopWidth: 1, borderTopColor: t.ruleSoft }}>
      <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
        <Text style={{ color: hue, fontFamily: MONO, fontSize: 11 }}>{p.ticker}</Text>
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
      <Text style={{ color: t.faint, fontSize: 10, marginTop: 3, lineHeight: 14 }} numberOfLines={2}>
        {family}
        {p.kin.length ? ' · ' + p.kin.map((k) => k.ticker).join(' ') : ''}
      </Text>
    </View>
  );
}

function SectorBlock({ s, t, dark, cols, peak, pick, onPick }) {
  const hue = s.hue;
  const tone = s.score < 0 ? t.neg : t.pos;
  const w = 100 / cols + '%';
  const mine = pick && pick.sector === s.name ? pick : null;

  const stateOf = (ticker) => {
    if (!pick) return 'plain';
    if (pick.sector === s.name && pick.ticker === ticker) return 'chosen';
    return pick.kinSet[ticker] ? 'kin' : 'muted';
  };

  return (
    <View style={{ marginBottom: 12 }}>
      <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
        <Text style={{ color: t.faint, fontFamily: MONO, fontSize: 11, width: 18 }}>{s.rank}</Text>
        <Text style={{ color: dark ? hue : t.ink, fontSize: 15, fontWeight: '600', flex: 1 }}>
          {s.name}
        </Text>
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
            backgroundColor: dark ? hue : tone,
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
            hue={hue}
            dark={dark}
            state={stateOf(c.ticker)}
            onPress={() => onPick(s, c, i)}
          />
        ))}
      </View>

      {mine && <Readout p={mine} t={t} hue={hue} />}
    </View>
  );
}

function Legend({ t, dark, hue }) {
  const steps = [0, 0.25, 0.5, 0.75, 1];
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 7, flexWrap: 'wrap' }}>
      <Text style={{ color: t.faint, fontSize: 10, marginRight: 5 }}>weakest</Text>
      {steps.map((h) => (
        <View
          key={h}
          style={{
            width: 18,
            height: 9,
            borderRadius: 2,
            marginRight: 2,
            backgroundColor: dark
              ? mix(t.ground, hue, 0.07 + 0.88 * h)
              : mix('#ffffff', hue, 0.14 + 0.72 * h),
          }}
        />
      ))}
      <Text style={{ color: t.faint, fontSize: 10, marginLeft: 3 }}>
        strongest in its own sector · each sector has its own colour
      </Text>
    </View>
  );
}

/**
 * Whole days since the prices were taken. The feed reports "up to date" about
 * itself, which says nothing about whether the feed is being refreshed at all —
 * this is the number that catches an abandoned feed.
 */
function ageInDays(iso) {
  const then = Date.parse(iso + 'T00:00:00Z');
  if (isNaN(then)) return null;
  return Math.floor((Date.now() - then) / 86400000);
}

function Freshness({ state, asOf, asOfISO, t }) {
  const age = ageInDays(asOfISO);
  const stale = age !== null && age > FEED.staleAfterDays;
  // The as-of date shows in every state, including while the feed is in flight —
  // a screen of numbers with no date on it is worse than a slightly stale one.
  const line = {
    baked: 'Numbers from ' + asOf + '.',
    checking: 'Showing ' + asOf + ' — checking for newer…',
    live: 'Up to date — numbers from ' + asOf + '.',
    stale: 'Offline, so showing the saved numbers from ' + asOf + '.',
  }[state];
  const dot = stale
    ? t.neg
    : { baked: t.faint, checking: t.faint, live: t.pos, stale: t.neg }[state];

  return (
    <View style={{ flexDirection: 'row', marginTop: 12 }}>
      <View
        style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: dot, marginRight: 7, marginTop: 5 }}
      />
      <Text style={{ color: t.faint, fontSize: 12, flex: 1, lineHeight: 17 }}>
        {line}
        {FEED.url ? ' Pull down to refresh.' : ''}
        {stale && (
          <Text style={{ color: t.neg }}>
            {' '}
            These are {age} days old — nobody has refreshed them.
          </Text>
        )}
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
    if (manual) { setBusy(true); pulled(); }
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
        setPick(null);          // the selection described the old numbers
        if (manual) landed();
      })
      .catch(() => setState('stale'))
      .finally(() => setBusy(false));
  }, []);

  useEffect(() => { load(false); }, [load]);

  // Which sector each ticker sits in, so the readout can count the family
  // members that live outside the tapped name's own sector.
  const homeOf = React.useMemo(() => {
    const m = {};
    data.sectors.forEach((s) => s.constituents.forEach((c) => { m[c.ticker] = s.name; }));
    return m;
  }, [data]);

  const choose = useCallback((sector, c, i) => {
    tapped();
    setPick((prev) => {
      if (prev && prev.sector === sector.name && prev.ticker === c.ticker) return null;
      const kin = ((data.peers || {})[c.ticker] || []).map(([ticker, r]) => ({
        ticker, r, sector: homeOf[ticker],
      }));
      // A lookup rather than a list: every cell on screen asks this question.
      const kinSet = {};
      kin.forEach((k) => { kinSet[k.ticker] = true; });
      return {
        sector: sector.name, ticker: c.ticker, name: c.name, score: c.score,
        place: i + 1, of: sector.n, kin, kinSet,
      };
    });
  }, [data, homeOf]);

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

        <Freshness state={state} asOf={data.meta.asOf} asOfISO={data.meta.asOfISO} t={t} />
        <Legend t={t} dark={dark} hue={data.sectors[0].hue} />

        <View style={{ height: 14 }} />

        <Details t={t} open={how} onToggle={() => setHow(!how)} meta={data.meta} />

        {data.sectors.map((s) => (
          <SectorBlock
            key={s.name}
            s={s}
            t={t}
            dark={dark}
            cols={cols}
            peak={peak}
            pick={pick}
            onPick={choose}
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
            "hue": SECTOR_HUE.get(s["sector"], "#7ad9c8"),
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
            "asOfISO": payload["as_of"],
            "blurb": (
                f"{len(sectors)} corners of the US market, best first, by how steadily they "
                f"climbed over nine months. Each sector has its own colour; the brighter a "
                f"square, the stronger that company is inside it. Tap one to light up "
                f"everything that moves with it."
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
        # [ticker, correlation] pairs, already sorted best first. Arrays rather
        # than objects: 273 names x 8 peers, and the keys would be half the bytes.
        "peers": {
            ticker: [[peer["ticker"], peer["r"]] for peer in peers]
            for ticker, peers in (payload.get("peers") or {}).items()
            if peers
        },
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
        {
            "url": feed_url or "",
            "timeoutMs": config.SECTOR_FEED_TIMEOUT_MS,
            "staleAfterDays": config.SECTOR_STALE_AFTER_DAYS,
        },
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
            "dependencies": SNACK_DEPENDENCIES,
        },
        "code": {"App.js": {"contents": source, "type": "CODE"}},
        "dependencies": {
            name: {"version": version} for name, version in SNACK_DEPENDENCIES.items()
        },
    }
    req = urllib.request.Request(
        SNACK_SAVE_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def push_feed(source: Path) -> str:
    """Copy the built feed onto the data-only branch and push it.

    The branch is checked out in a throwaway worktree rather than here: the
    feed branch shares no history with the code branches, and switching this
    working tree onto it would be a large, pointless, and easily-botched
    checkout.
    """
    branch = config.SECTOR_FEED_BRANCH
    run = lambda *a: subprocess.run(a, check=True, capture_output=True, text=True)

    run("git", "fetch", "origin", branch)
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / branch
        run("git", "worktree", "add", "--quiet", str(tree), f"origin/{branch}")
        try:
            target = tree / config.SECTOR_FEED_BRANCH_FILE
            if target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8"):
                return "unchanged — nothing to push"
            shutil.copyfile(source, target)
            stamp = json.loads(source.read_text(encoding="utf-8"))["meta"]["asOfISO"]
            run("git", "-C", str(tree), "add", config.SECTOR_FEED_BRANCH_FILE)
            run("git", "-C", str(tree), "commit", "-m", f"Refresh the feed: prices through {stamp}")
            run("git", "-C", str(tree), "push", "origin", f"HEAD:{branch}")
            return f"pushed — prices through {stamp}"
        finally:
            run("git", "worktree", "remove", "--force", str(tree))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--publish", action="store_true", help="upload to snack.expo.dev")
    ap.add_argument(
        "--push-feed", action="store_true",
        help=f"push the rebuilt feed to the {config.SECTOR_FEED_BRANCH} branch (this is a refresh)",
    )
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
    # This copy is a build artefact; the published one on the feed branch is
    # the single source of truth, and its commit history is what a "what moved
    # this week" view would eventually read.
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

    if args.push_feed:
        print(f"feed       {push_feed(feed)}")

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
