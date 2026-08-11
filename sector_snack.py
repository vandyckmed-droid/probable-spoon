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
SNACK_DEPENDENCIES = {
    "expo-haptics": "*",
    "@react-native-async-storage/async-storage": "*",
}

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
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  SafeAreaView, ScrollView, View, Text, Pressable, useColorScheme,
  StatusBar, Platform, RefreshControl, useWindowDimensions,
} from 'react-native';
import * as Haptics from 'expo-haptics';
import AsyncStorage from '@react-native-async-storage/async-storage';

// The watchlist outlives the session; losing it on every launch would make
// it pointless. Storage failures degrade to in-memory, never to a crash.
const WL_KEY = 'watchlist-v1';
const saveWl = (wl) => { try { AsyncStorage.setItem(WL_KEY, JSON.stringify(wl)).catch(() => {}); } catch (e) {} };

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
 * One design system, both colour schemes, brokerage-dark first. The palette
 * appears only at full strength — dots, bars, numbers — never as a tinted
 * area fill: blending acid green into a dark surface is how the old build
 * turned to pea soup. Position carries magnitude now; colour only carries
 * direction. Light mode keeps the same vocabulary with the green pulled down
 * to hold contrast on white.
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

const pct = (x) => (x === null || x === undefined ? '—' : Math.round(x * 100) + '%');
const signed = (x) => (x >= 0 ? '+' : '') + x.toFixed(2);

function ordinal(n) {
  const tail = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (tail[(v - 20) % 10] || tail[v] || tail[0]);
}

const toneOf = (z, t) => (z === null || z === undefined ? t.faint : z < 0 ? t.neg : t.pos);

// ---- the strip plot ---------------------------------------------------------

const DOT = 8;        // dot diameter
const LANE = 11;      // vertical pitch between stacked dots
const MAX_LANES = 6;  // beyond this the mid-pack may overlap; that reads as density

/**
 * Position along the axis for a z-score. Clamped at ±2.5σ so one freak name
 * cannot squash everyone else onto the centre line; 47 keeps the outermost
 * dot inside the track.
 */
function X(z) {
  const c = Math.max(-2.5, Math.min(2.5, z / 2.5));
  return 50 + c * 47;
}

/**
 * Stack colliding dots into lanes, greedily: each dot takes the first lane
 * with room, and when every lane is crowded it takes the least-crowded one
 * and accepts the overlap. Items must arrive sorted by x.
 */
function packLanes(items, plotW) {
  const minGap = plotW > 0 ? ((DOT + 2) / plotW) * 100 : 4;
  const last = [];
  return items.map((it) => {
    let lane = last.findIndex((x) => it.x - x >= minGap);
    if (lane === -1) {
      if (last.length < MAX_LANES) { lane = last.length; last.push(it.x); }
      else {
        let best = 0;
        for (let i = 1; i < last.length; i++) if (last[i] < last[best]) best = i;
        lane = best; last[best] = it.x;
      }
    } else {
      last[lane] = it.x;
    }
    return lane;
  });
}

/**
 * Every company in the sector as one dot on a shared axis: right of the
 * centre line leading, left lagging, distance is strength. Full-saturation
 * colour on a small mark stays crisp where a tinted cell went muddy.
 */
function Strip({ s, t, zOf, plotW, pick, wl, onPick }) {
  const placed = s.constituents
    .map((c, i) => ({ c, i, z: zOf(c), x: X(zOf(c) === null || zOf(c) === undefined ? 0 : zOf(c)) }))
    .sort((a, b) => a.x - b.x);
  const laneOf = packLanes(placed, plotW);
  const laneCount = Math.max(...laneOf, 0) + 1;
  const height = laneCount * LANE + DOT;

  return (
    <View style={{ height, marginTop: 10 }}>
      {/* centre line and the ±1.5σ hairlines give the dots their scale */}
      <View style={{ position: 'absolute', left: X(-1.5) + '%', top: 0, bottom: 0, width: 1, backgroundColor: t.ruleSoft }} />
      <View style={{ position: 'absolute', left: X(1.5) + '%', top: 0, bottom: 0, width: 1, backgroundColor: t.ruleSoft }} />
      <View style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, backgroundColor: t.rule }} />
      {placed.map((p, k) => {
        const c = p.c;
        const unscored = p.z === null || p.z === undefined;
        const chosen = pick && pick.ticker === c.ticker && pick.sector === s.name && pick.tier === s.tier;
        const kin = pick && pick.kinSet[c.ticker];
        const dim = pick && !chosen && !kin;
        const ring = chosen ? t.ink : kin ? t.accent : wl[c.ticker] ? t.ink : 'transparent';
        return (
          <Pressable
            key={c.ticker}
            onPress={() => onPick(s, c, p.i)}
            hitSlop={7}
            style={{
              position: 'absolute',
              left: p.x + '%',
              top: laneOf[k] * LANE + (chosen ? 0 : 1),
              marginLeft: -(DOT / 2) - (chosen ? 1 : 0),
              opacity: dim ? 0.25 : 1,
            }}
          >
            <View
              style={{
                width: DOT + (chosen ? 2 : 0),
                height: DOT + (chosen ? 2 : 0),
                borderRadius: DOT,
                backgroundColor: unscored ? 'transparent' : toneOf(p.z, t),
                borderWidth: unscored ? 1 : chosen || kin || wl[c.ticker] ? 1.5 : 0,
                borderColor: unscored ? t.faint : ring,
              }}
            />
          </Pressable>
        );
      })}
    </View>
  );
}

/** One named company: place, ticker, name, a thin bar sized like its dot. */
function NameRow({ c, place, t, zOf, pick, wl, onPress }) {
  const z = zOf(c);
  const tone = toneOf(c.score === null ? null : z, t);
  const frac = z === null || z === undefined ? 0 : Math.min(Math.abs(z) / 2.5, 1);
  const dim = pick && !pick.kinSet[c.ticker] && pick.ticker !== c.ticker;
  return (
    <Pressable onPress={onPress} style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 4.5, opacity: dim ? 0.35 : 1 }}>
      <Text style={{ color: t.faint, fontFamily: MONO, fontSize: 10, width: 22 }}>{place}</Text>
      <Text style={{ color: pick && pick.ticker === c.ticker ? t.accent : t.ink, fontFamily: MONO, fontSize: 11.5, width: 52 }}>
        {c.ticker}
      </Text>
      <Text numberOfLines={1} style={{ color: t.muted, fontSize: 11.5, flex: 1, marginRight: 8 }}>
        {c.name}{wl[c.ticker] ? ' ★' : ''}
      </Text>
      <View style={{ width: 54, height: 3, borderRadius: 2, backgroundColor: t.ruleSoft, marginRight: 8 }}>
        <View style={{ width: frac * 100 + '%', height: 3, borderRadius: 2, backgroundColor: tone, alignSelf: z < 0 ? 'flex-end' : 'flex-start' }} />
      </View>
      <Text style={{ color: c.score === null ? t.faint : tone, fontFamily: MONO, fontSize: 11.5, width: 44, textAlign: 'right' }}>
        {c.score === null ? '—' : signed(c.score)}
      </Text>
    </Pressable>
  );
}

/**
 * What the selected name is, and how much of its family lives outside its own
 * sector — the number that makes the cross-sector highlighting worth having.
 */
function Readout({ p, t, watched, onWatch }) {
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
      <Pressable
        onPress={onWatch}
        style={{
          alignSelf: 'flex-start',
          borderWidth: 1,
          borderColor: t.accent,
          borderRadius: 6,
          paddingVertical: 4,
          paddingHorizontal: 10,
          marginTop: 8,
        }}
      >
        <Text style={{ color: t.accent, fontSize: 11.5, fontWeight: '600' }}>
          {watched ? 'On watchlist — tap to remove' : 'Add to watchlist'}
        </Text>
      </Pressable>
    </View>
  );
}

/**
 * One sector: header, plain-words stats, the strip of everyone, then the
 * three best and three worst by name. The middle of a ranked-within-sector
 * list is undifferentiated by construction — it belongs on the strip as
 * shape, not in a table pretending every row matters equally.
 */
function SectorCard({ s, t, plotW, pick, zOf, wl, onPick, onWatch, onLayout }) {
  const tone = s.score < 0 ? t.neg : t.pos;
  const scored = s.constituents.filter((c) => c.score !== null);
  const head = scored.slice(0, 3);
  const tail = scored.slice(-3);
  const hidden = scored.length - head.length - tail.length;
  const mine = pick && pick.sector === s.name && pick.tier === s.tier ? pick : null;

  return (
    <View
      onLayout={onLayout}
      style={{
        backgroundColor: t.surface,
        borderRadius: 10,
        borderWidth: 1,
        borderColor: t.ruleSoft,
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

      <Strip s={s} t={t} zOf={zOf} plotW={plotW} pick={pick} wl={wl} onPick={onPick} />

      <View style={{ marginTop: 6 }}>
        {head.map((c, i) => (
          <NameRow key={c.ticker} c={c} place={i + 1} t={t} zOf={zOf} pick={pick} wl={wl}
            onPress={() => onPick(s, c, s.constituents.indexOf(c))} />
        ))}
        {hidden > 0 && (
          <Text style={{ color: t.faint, fontSize: 10, textAlign: 'center', paddingVertical: 3 }}>
            · {hidden} more in the middle — tap any dot ·
          </Text>
        )}
        {hidden > -3 && tail.map((c, i) => (
          <NameRow key={c.ticker} c={c} place={scored.length - tail.length + i + 1} t={t} zOf={zOf}
            pick={pick} wl={wl} onPress={() => onPick(s, c, s.constituents.indexOf(c))} />
        ))}
      </View>

      {mine && (
        <Readout
          p={mine}
          t={t}
          watched={!!wl[mine.ticker]}
          onWatch={() => onWatch({ ticker: mine.ticker })}
        />
      )}
    </View>
  );
}

/**
 * Every sector on one axis — the first thing on screen answers the page's
 * question before any scrolling. Rows jump to their card.
 */
function MarketMap({ sectors, t, onJump }) {
  // The axis adapts to the data: an all-positive quarter runs the bars from
  // the left edge instead of parking half the row behind an empty negative
  // side; when signs are mixed the zero line moves to where zero really is.
  const lo = Math.min(0, ...sectors.map((s) => s.score));
  const hi = Math.max(0, ...sectors.map((s) => s.score));
  const span = hi - lo || 1;
  const zero = ((0 - lo) / span) * 100;
  return (
    <View
      style={{
        backgroundColor: t.surface,
        borderRadius: 10,
        borderWidth: 1,
        borderColor: t.ruleSoft,
        paddingHorizontal: 12,
        paddingVertical: 10,
        marginTop: 14,
        marginBottom: 10,
      }}
    >
      {sectors.map((s) => {
        const tone = s.score < 0 ? t.neg : t.pos;
        const frac = (Math.abs(s.score) / span) * 100;
        return (
          <Pressable
            key={s.name}
            onPress={() => { tapped(); onJump(s.name); }}
            style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 4.5 }}
          >
            <Text numberOfLines={1} style={{ color: t.ink, fontSize: 12, width: 118 }}>{s.name}</Text>
            <View style={{ flex: 1, height: 12, justifyContent: 'center' }}>
              <View style={{ position: 'absolute', left: zero + '%', top: 0, bottom: 0, width: 1, backgroundColor: t.rule }} />
              <View
                style={{
                  position: 'absolute',
                  height: 4,
                  borderRadius: 2,
                  backgroundColor: tone,
                  width: frac + '%',
                  left: (s.score < 0 ? zero - frac : zero) + '%',
                }}
              />
            </View>
            <Text style={{ color: tone, fontFamily: MONO, fontSize: 11.5, width: 46, textAlign: 'right' }}>
              {signed(s.score)}
            </Text>
          </Pressable>
        );
      })}
      <Text style={{ color: t.faint, fontSize: 10, marginTop: 6 }}>
        Steady-climb score, nine months. Tap a sector to jump to its companies.
      </Text>
    </View>
  );
}

/** Same score, two yardsticks: a name against its sector, or against everyone. */
function ViewToggle({ view, onPick, t }) {
  const opts = [
    { k: 'sector', label: 'By sector' },
    { k: 'global', label: 'Whole market' },
  ];
  return (
    <View
      style={{
        flexDirection: 'row',
        backgroundColor: t.ruleSoft,
        borderRadius: 9,
        padding: 3,
        marginTop: 10,
      }}
    >
      {opts.map((o) => {
        const on = view === o.k;
        return (
          <Pressable
            key={o.k}
            onPress={() => { if (!on) { tapped(); onPick(o.k); } }}
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
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function Legend({ t, view }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 10 }}>
      <View style={{ width: DOT, height: DOT, borderRadius: DOT, backgroundColor: t.pos, marginRight: 5 }} />
      <Text style={{ color: t.faint, fontSize: 10.5, marginRight: 10 }}>leading</Text>
      <View style={{ width: DOT, height: DOT, borderRadius: DOT, backgroundColor: t.neg, marginRight: 5 }} />
      <Text style={{ color: t.faint, fontSize: 10.5, flex: 1 }}>
        lagging — each dot is one company; the further from the line, the stronger
        {view === 'global' ? ', against every company on the page' : ', against its own sector'}
      </Text>
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

/** Names the active family, and is the one obvious way out of it. */
function FamilyBar({ pick, t, onClear }) {
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
        Lit up: what moves with {pick.ticker}
        {pick.kin.length ? ' · ' + pick.kin.length + ' names' : ''}
      </Text>
      <Text style={{ color: t.accent, fontSize: 11.5, fontWeight: '600' }}>Clear</Text>
    </Pressable>
  );
}

/** The tapped-together list. Chips, not rows — it should stay one glance tall. */
function WatchCard({ wl, lookup, t, onRemove }) {
  const rows = Object.keys(wl).filter((k) => lookup[k]).sort();
  if (!rows.length) return null;
  return (
    <View
      style={{
        backgroundColor: t.surface,
        borderWidth: 1,
        borderColor: t.rule,
        borderRadius: 10,
        paddingHorizontal: 12,
        paddingVertical: 10,
        marginBottom: 10,
      }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
        <Text style={{ color: t.ink, fontSize: 13.5, fontWeight: '600', flex: 1 }}>Watchlist</Text>
        <Text style={{ color: t.faint, fontSize: 10.5 }}>{rows.length} · tap a name to remove</Text>
      </View>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 7 }}>
        {rows.map((k) => {
          const c = lookup[k];
          const tone = c.score === null ? t.muted : c.score < 0 ? t.neg : t.pos;
          return (
            <Pressable
              key={k}
              onPress={() => onRemove(k)}
              style={{
                flexDirection: 'row',
                alignItems: 'baseline',
                borderWidth: 1,
                borderColor: t.rule,
                borderRadius: 6,
                paddingVertical: 4,
                paddingHorizontal: 8,
                marginRight: 4,
                marginBottom: 4,
              }}
            >
              <Text style={{ color: t.ink, fontFamily: MONO, fontSize: 11 }}>{k}</Text>
              <Text style={{ color: tone, fontFamily: MONO, fontSize: 10, marginLeft: 5 }}>
                {c.score === null ? '—' : signed(c.score)}
              </Text>
            </Pressable>
          );
        })}
      </View>
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
  const [view, setView] = useState('sector');
  const [wl, setWl] = useState({});
  // The strip needs its own width in points to know when two dots collide.
  const { width } = useWindowDimensions();
  const plotW = width - 2 * 14 - 2 * 12;   // screen padding, card padding
  const scroller = useRef(null);
  const cardY = useRef({});
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

  useEffect(() => {
    try {
      AsyncStorage.getItem(WL_KEY)
        .then((raw) => { if (raw) setWl(JSON.parse(raw)); })
        .catch(() => {});
    } catch (e) {}
  }, []);

  const toggleWatch = useCallback((c) => {
    tapped();
    setWl((prev) => {
      const next = { ...prev };
      if (next[c.ticker]) delete next[c.ticker];
      else next[c.ticker] = true;
      saveWl(next);
      return next;
    });
  }, []);

  const tiers = React.useMemo(() => tiersOf(data), [data]);
  const active = tiers[Math.min(tab, tiers.length - 1)];

  // Which sector and which list every ticker sits in. Peers cross both, so the
  // readout can only count what is off-screen if it knows where everything is.
  const homeOf = React.useMemo(() => {
    const m = {};
    tiers.forEach((tier) =>
      tier.sectors.forEach((s) =>
        s.constituents.forEach((c) => {
          m[c.ticker] = { sector: s.name, tier: tier.key, name: c.name, score: c.score };
        })
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

  const zOf = view === 'global' ? (c) => c.g : (c) => c.z;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: t.ground }}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      <ScrollView
        ref={scroller}
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

        <MarketMap
          sectors={active.sectors}
          t={t}
          onJump={(name) => {
            const y = cardY.current[active.key + ':' + name];
            if (scroller.current && y !== undefined) scroller.current.scrollTo({ y: y - 6, animated: true });
          }}
        />

        {tiers.length > 1 && (
          <Tabs tiers={tiers} active={tiers.indexOf(active)} onPick={setTab} t={t} />
        )}

        <ViewToggle view={view} onPick={setView} t={t} />

        <Legend t={t} view={view} />

        <View style={{ height: 14 }} />

        <WatchCard wl={wl} lookup={homeOf} t={t} onRemove={(k) => toggleWatch({ ticker: k })} />

        {pick && <FamilyBar pick={pick} t={t} onClear={() => { tapped(); setPick(null); }} />}

        <Details t={t} open={how} onToggle={() => setHow(!how)} meta={data.meta} />

        {active.sectors.map((s) => (
          <SectorCard
            key={s.name}
            s={s}
            t={t}
            plotW={plotW}
            pick={pick}
            zOf={zOf}
            wl={wl}
            onPick={choose}
            onWatch={toggleWatch}
            onLayout={(e) => { cardY.current[active.key + ':' + s.name] = e.nativeEvent.layout.y; }}
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

    # Global z: the same score sized against every name on the page rather
    # than the ~50 in its own sector — the whole-market shading view.
    everyone = [c for tier in rendered for s in tier for c in s["constituents"]]
    scored = [c["score"] for c in everyone if c["score"] is not None]
    if len(scored) > 1:
        mean = sum(scored) / len(scored)
        sd = (sum((x - mean) ** 2 for x in scored) / (len(scored) - 1)) ** 0.5
    else:
        mean, sd = 0.0, 0.0
    for c in everyone:
        c["g"] = (
            None if (c["score"] is None or sd == 0)
            else round((c["score"] - mean) / sd, 3)
        )

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
            "title": "Two ways to shade",
            "body": (
                "'By sector' colours each company against the others in its own "
                "sector, so every sector shows its own leaders and laggards. "
                "'Whole market' colours everyone against the full page on one "
                "scale — a strong sector goes green nearly wall to wall, a weak "
                "one sinks together."
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
            # Describes the data only. What the screen looks like is the
            # app's business — a feed line about squares outlived the squares.
            "blurb": (
                f"{len(rendered[0])} corners of the US market, best first, by how "
                f"steadily they climbed over nine months. Tap a company to see "
                f"everything that moves with it, and to add it to your watchlist."
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
