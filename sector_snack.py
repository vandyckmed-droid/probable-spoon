"""Emit the sector ranking as an Expo Snack app and publish it.

Each tier renders as sector cards, each wrapping its 25 tickers into a grid
sized to the screen and shaded on the same within-sector z — one restrained
diverging scale (teal leading, rust lagging), one design system across both
tiers and both colour schemes. Tapping a cell names the company and lights its
correlation family; labels are plain words with the maths behind a "How this
works" panel. The numbers are fetched at run time with the published snapshot
as the offline fallback.

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

/**
 * One design system, both colour schemes, brokerage-dark first: near-black
 * ground, acid green for names leading their sector, signal orange for names
 * lagging it. Everything else stays neutral so the data is the only thing
 * with a voice. Light mode keeps the same vocabulary with the green pulled
 * down to hold contrast on white.
 */
const LIGHT = {
  ground: '#fafbf8', surface: '#ffffff', ink: '#151a12', muted: '#5a6357',
  faint: '#8a9385', rule: '#e2e6dc', ruleSoft: '#eef1e8',
  pos: '#4f9c00', neg: '#d9542e', accent: '#3e7d00',
};
const DARK = {
  ground: '#0a0c0a', surface: '#131613', ink: '#eef2ea', muted: '#9aa596',
  faint: '#6c7568', rule: '#242923', ruleSoft: '#1a1e19',
  pos: '#9fe519', neg: '#ff6a45', accent: '#ccff5e',
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
 * Cell fill for a within-sector z. Direction picks the side of the scale,
 * magnitude picks the depth, saturating at ±1.5σ. The tint is capped so the
 * theme ink stays readable on every cell — no per-cell text colour juggling.
 */
function cellFill(z, t, dark) {
  if (z === null || z === undefined) return dark ? t.ruleSoft : t.ruleSoft;
  const side = z < 0 ? t.neg : t.pos;
  const m = Math.min(Math.abs(z) / 1.5, 1);
  const base = dark ? t.surface : '#ffffff';
  return mix(base, side, dark ? 0.09 + 0.48 * m : 0.07 + 0.36 * m);
}

const pct = (x) => (x === null || x === undefined ? '—' : Math.round(x * 100) + '%');
const signed = (x) => (x >= 0 ? '+' : '') + x.toFixed(2);

function ordinal(n) {
  const tail = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (tail[(v - 20) % 10] || tail[v] || tail[0]);
}

/**
 * One ticker. Selection dims the unrelated rather than blacking them out —
 * the page should still read as a page, just with one family in focus.
 */
function Cell({ c, t, w, dark, state, onPress }) {
  return (
    <Pressable
      onPress={onPress}
      style={{ width: w, padding: 1.5, opacity: state === 'muted' ? 0.28 : 1 }}
    >
      <View
        style={{
          backgroundColor: cellFill(c.z, t, dark),
          borderRadius: 4,
          paddingVertical: 4,
          alignItems: 'center',
          borderWidth: 1,
          borderColor:
            state === 'chosen' ? t.ink : state === 'kin' ? t.accent : 'transparent',
        }}
      >
        <Text numberOfLines={1} style={{ color: t.ink, fontFamily: MONO, fontSize: 10 }}>
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
function Readout({ p, t }) {
  const tone = p.score === null ? t.muted : p.score < 0 ? t.neg : t.pos;
  const away = p.kin.filter((k) => k.sector !== p.sector).length;
  const family = p.kin.length
    ? p.kin.length + ' move with it' + (away ? ', ' + away + ' outside this sector' : '')
    : 'nothing else moves closely with it';

  return (
    <View style={{ marginTop: 8, paddingTop: 8, borderTopWidth: 1, borderTopColor: t.ruleSoft }}>
      <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
        <Text style={{ color: t.ink, fontFamily: MONO, fontSize: 11.5, fontWeight: '700' }}>
          {p.ticker}
        </Text>
        <Text style={{ color: t.muted, fontSize: 11.5, flex: 1, marginLeft: 8 }} numberOfLines={1}>
          {p.name}
        </Text>
        <Text style={{ color: t.faint, fontSize: 10, marginLeft: 6 }}>
          {p.score === null ? 'unscored' : ordinal(p.place) + ' of ' + p.of}
        </Text>
        <Text style={{ color: tone, fontFamily: MONO, fontSize: 11.5, marginLeft: 8 }}>
          {p.score === null ? '—' : signed(p.score)}
        </Text>
      </View>
      <Text style={{ color: t.faint, fontSize: 10.5, marginTop: 3, lineHeight: 15 }} numberOfLines={2}>
        {family}
        {p.kin.length ? ' · ' + p.kin.map((k) => k.ticker).join(' ') : ''}
      </Text>
    </View>
  );
}

function SectorBlock({ s, t, dark, cols, peak, pick, onPick }) {
  const tone = s.score < 0 ? t.neg : t.pos;
  const w = 100 / cols + '%';
  const mine = pick && pick.sector === s.name && pick.tier === s.tier ? pick : null;

  const stateOf = (ticker) => {
    if (!pick) return 'plain';
    if (pick.tier === s.tier && pick.sector === s.name && pick.ticker === ticker) {
      return 'chosen';
    }
    return pick.kinSet[ticker] ? 'kin' : 'muted';
  };

  return (
    <View
      style={{
        backgroundColor: t.surface,
        borderRadius: 10,
        borderWidth: 1,
        borderColor: dark ? t.ruleSoft : t.rule,
        paddingHorizontal: 12,
        paddingVertical: 11,
        marginBottom: 10,
      }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
        <Text style={{ color: t.faint, fontFamily: MONO, fontSize: 11, width: 20 }}>{s.rank}</Text>
        <Text style={{ color: t.ink, fontSize: 15, fontWeight: '600', flex: 1 }}>{s.name}</Text>
        <Text style={{ color: tone, fontFamily: MONO, fontSize: 15, fontWeight: '700' }}>
          {signed(s.score)}
        </Text>
      </View>

      <Text numberOfLines={1} style={{ color: t.faint, fontSize: 10.5, marginLeft: 20, marginTop: 2 }}>
        {s.gloss} · {pct(s.ret)}/yr · swing {pct(s.vol)} · {s.rising}/{s.n} up
        {s.etf ? ' · ' + s.etf + ' ' + signed(s.etfScore) : ''}
      </Text>

      {/* Length is the score's size against the best sector; colour its direction. */}
      <View
        style={{
          height: 3, marginTop: 7, marginLeft: 20, borderRadius: 2,
          backgroundColor: t.ruleSoft, flexDirection: 'row', overflow: 'hidden',
        }}
      >
        <View
          style={{
            width: Math.min(Math.abs(s.score) / peak, 1) * 100 + '%',
            backgroundColor: tone,
            borderRadius: 2,
          }}
        />
      </View>

      <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 8 }}>
        {s.constituents.map((c, i) => (
          <Cell
            key={c.ticker}
            c={c}
            t={t}
            w={w}
            dark={dark}
            state={stateOf(c.ticker)}
            onPress={() => onPick(s, c, i)}
          />
        ))}
      </View>

      {mine && <Readout p={mine} t={t} />}
    </View>
  );
}

/** A quiet segmented control — the standard phone idiom for two views of one thing. */
function Tabs({ tiers, active, onPick, t }) {
  return (
    <View
      style={{
        flexDirection: 'row',
        backgroundColor: t.ruleSoft,
        borderRadius: 9,
        padding: 3,
        marginTop: 12,
      }}
    >
      {tiers.map((tier, i) => {
        const on = i === active;
        return (
          <Pressable
            key={tier.key}
            onPress={() => { if (!on) { tapped(); onPick(i); } }}
            style={{
              flex: 1,
              paddingVertical: 6,
              alignItems: 'center',
              borderRadius: 7,
              backgroundColor: on ? t.surface : 'transparent',
              borderWidth: 1,
              borderColor: on ? t.rule : 'transparent',
            }}
          >
            <Text style={{ color: on ? t.ink : t.faint, fontSize: 12.5, fontWeight: '600' }}>
              {tier.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/**
 * A selection made on the other list still lights names here, so say whose
 * family is on screen — otherwise the dimming looks like a fault.
 */
function CrossTier({ pick, here, t, onClear }) {
  return (
    <Pressable
      onPress={onClear}
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        backgroundColor: t.surface,
        borderWidth: 1,
        borderColor: t.rule,
        borderRadius: 8,
        paddingVertical: 7,
        paddingHorizontal: 10,
        marginBottom: 10,
      }}
    >
      <Text style={{ color: t.muted, fontSize: 11.5, flex: 1 }} numberOfLines={1}>
        Lit up: what moves with {pick.ticker} · {here} of {pick.kin.length} on this list
      </Text>
      <Text style={{ color: t.accent, fontSize: 11.5, fontWeight: '600' }}>Clear</Text>
    </Pressable>
  );
}

function Legend({ t, dark }) {
  const steps = [-1.5, -0.75, 0, 0.75, 1.5];
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 10, flexWrap: 'wrap' }}>
      <Text style={{ color: t.faint, fontSize: 10.5, marginRight: 6 }}>lagging</Text>
      {steps.map((z) => (
        <View
          key={z}
          style={{
            width: 18, height: 9, borderRadius: 2.5, marginRight: 2,
            backgroundColor: cellFill(z, t, dark),
            borderWidth: 1, borderColor: t.ruleSoft,
          }}
        />
      ))}
      <Text style={{ color: t.faint, fontSize: 10.5, marginLeft: 4 }}>
        leading — always against its own sector
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
    <View style={{ flexDirection: 'row', marginTop: 10 }}>
      <View
        style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: dot, marginRight: 7, marginTop: 5 }}
      />
      <Text style={{ color: t.faint, fontSize: 11.5, flex: 1, lineHeight: 16 }}>
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
        borderRadius: 10,
        paddingHorizontal: 12,
        paddingVertical: 10,
        marginBottom: 10,
      }}
    >
      <Pressable onPress={onToggle}>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Text style={{ color: t.ink, fontSize: 13.5, fontWeight: '600', flex: 1 }}>
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

/** The tiers the feed actually carries, oldest shape included. */
function tiersOf(data) {
  const specs = data.meta.tiers || [{ key: 'top', label: 'Top 25', note: '' }];
  const lists = [data.sectors, data.sectors2];
  return specs
    .map((spec, i) => ({ ...spec, sectors: lists[i] || [] }))
    .filter((tier) => tier.sectors.length);
}

export default function App() {
  const dark = useColorScheme() === 'dark';
  const t = dark ? DARK : LIGHT;
  const [pick, setPick] = useState(null);
  const [how, setHow] = useState(false);
  const [tab, setTab] = useState(0);
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

  const tiers = React.useMemo(() => tiersOf(data), [data]);
  const active = tiers[Math.min(tab, tiers.length - 1)];

  // Which sector and which list every ticker sits in. Peers cross both, so the
  // readout can only count what is off-screen if it knows where everything is.
  const homeOf = React.useMemo(() => {
    const m = {};
    tiers.forEach((tier) =>
      tier.sectors.forEach((s) =>
        s.constituents.forEach((c) => { m[c.ticker] = { sector: s.name, tier: tier.key }; })
      )
    );
    return m;
  }, [tiers]);

  const choose = useCallback((sector, c, i) => {
    tapped();
    setPick((prev) => {
      if (prev && prev.tier === sector.tier && prev.ticker === c.ticker) return null;
      const kin = ((data.peers || {})[c.ticker] || []).map(([ticker, r]) => ({
        ticker,
        r,
        sector: (homeOf[ticker] || {}).sector,
        tier: (homeOf[ticker] || {}).tier,
      }));
      // A lookup rather than a list: every cell on screen asks this question.
      const kinSet = {};
      kin.forEach((k) => { kinSet[k.ticker] = true; });
      return {
        tier: sector.tier, sector: sector.name, ticker: c.ticker, name: c.name,
        score: c.score, place: i + 1, of: sector.n, kin, kinSet,
      };
    });
  }, [data, homeOf]);

  const peak = Math.max(...active.sectors.map((s) => Math.abs(s.score)));
  const elsewhere = pick && pick.tier !== active.key;
  const kinHere = elsewhere ? pick.kin.filter((k) => k.tier === active.key).length : 0;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: t.ground }}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      <ScrollView
        contentContainerStyle={{ padding: 14, paddingBottom: 48 }}
        showsVerticalScrollIndicator={false}
        refreshControl={
          FEED.url ? (
            <RefreshControl refreshing={busy} onRefresh={() => load(true)} tintColor={t.faint} />
          ) : undefined
        }
      >
        <Text style={{ color: t.ink, fontSize: 22, fontWeight: '700', lineHeight: 27, marginTop: 4 }}>
          Which sectors are climbing?
        </Text>
        <Text style={{ color: t.muted, fontSize: 12.5, marginTop: 6, lineHeight: 18 }}>
          {data.meta.blurb}
        </Text>

        <Freshness state={state} asOf={data.meta.asOf} asOfISO={data.meta.asOfISO} t={t} />

        {tiers.length > 1 && (
          <Tabs tiers={tiers} active={tiers.indexOf(active)} onPick={setTab} t={t} />
        )}
        {!!active.note && (
          <Text style={{ color: t.faint, fontSize: 11, marginTop: 8, lineHeight: 16 }}>
            {active.note}
          </Text>
        )}

        <Legend t={t} dark={dark} />

        <View style={{ height: 14 }} />

        {elsewhere && (
          <CrossTier pick={pick} here={kinHere} t={t} onClear={() => { tapped(); setPick(null); }} />
        )}

        <Details t={t} open={how} onToggle={() => setHow(!how)} meta={data.meta} />

        {active.sectors.map((s) => (
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

    def render_sector(s, tier_key, etfs):
        etf = etfs.get(s["sector"])
        return {
            "tier": tier_key,
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
        }

    tiers = payload.get("tiers") or [
        {"key": "top", "label": "Top 25", "note": "", "sectors": payload["sectors"]}
    ]
    by_tier = (payload.get("benchmark_by_tier") or {})
    rendered = [
        [
            render_sector(s, tier["key"], (by_tier.get(tier["key"]) or {}).get("etfs") or etfs)
            for s in tier["sectors"]
        ]
        for tier in tiers
    ]

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
            "tiers": [
                {"key": t["key"], "label": t["label"], "note": t["note"]}
                for t in tiers
            ],
            "blurb": (
                f"{len(rendered[0])} corners of the US market, best first, by how steadily "
                f"they climbed over nine months. Green squares are leading their sector, "
                f"orange squares are lagging it — the deeper, the stronger. Tap any "
                f"company to light up everything that moves with it."
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
        # The first tier keeps the old top-level name so a bundle published
        # before the split still finds something to render.
        "sectors": rendered[0],
        "sectors2": rendered[1] if len(rendered) > 1 else [],
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
