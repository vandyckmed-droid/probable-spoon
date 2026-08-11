"""Emit the sector ranking as an Expo Snack app and publish it.

The phone build is an ordinary drill-down app, not a chart: a list of sectors,
tap one for its companies, tap one of those for its detail and its correlation
family. Every target is a full-width row. The numbers are fetched at run time
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

# The score in plain words. The reader should never have to know that 0.75 is
# "good" — the row says so. Thresholds are deliberately coarse: five buckets a
# person can hold in their head, not a continuous scale nobody can read.
VERDICTS = (
    (1.50, "climbing hard"),
    (0.75, "climbing steadily"),
    (0.25, "drifting up"),
    (-0.25, "going nowhere"),
    (-0.75, "drifting down"),
)
VERDICT_FLOOR = "falling"


def verdict_for(score: float) -> str:
    for cut, phrase in VERDICTS:
        if score >= cut:
            return phrase
    return VERDICT_FLOOR


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
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  SafeAreaView, ScrollView, View, Text, Pressable, useColorScheme,
  StatusBar, Platform, RefreshControl, BackHandler,
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
 * Brokerage-dark first, acid green leading and signal orange lagging — the
 * user's standing palette. It appears only at full strength on type and on
 * hairline bars; nothing is ever a tinted area fill.
 */
const LIGHT = {
  ground: '#f4f6f2', surface: '#ffffff', ink: '#151a12', muted: '#5a6357',
  faint: '#8a9385', rule: '#e2e6dc', ruleSoft: '#edf0e9',
  pos: '#4f9c00', neg: '#d9542e', accent: '#3e7d00',
};
const DARK = {
  ground: '#0a0c0a', surface: '#141714', ink: '#eef2ea', muted: '#9aa596',
  faint: '#6c7568', rule: '#252a24', ruleSoft: '#1b1f1a',
  pos: '#9fe519', neg: '#ff6a45', accent: '#ccff5e',
};

const MONO = Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' });

const pct = (x) => (x === null || x === undefined ? '—' : Math.round(x * 100) + '%');
const signed = (x) => (x === null || x === undefined ? '—' : (x >= 0 ? '+' : '') + x.toFixed(2));

function ordinal(n) {
  const tail = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (tail[(v - 20) % 10] || tail[v] || tail[0]);
}

const toneOf = (v, t) => (v === null || v === undefined ? t.faint : v < 0 ? t.neg : t.pos);

/**
 * A hairline under a row: length is the number's size against the biggest on
 * the screen, colour its direction. It sits behind the type as texture — the
 * row is readable with the bar ignored entirely.
 */
function Bar({ value, peak, t, width }) {
  const frac = value === null || value === undefined ? 0 : Math.min(Math.abs(value) / (peak || 1), 1);
  return (
    <View style={{ height: 3, borderRadius: 2, backgroundColor: t.ruleSoft, width: width || '100%', marginTop: 8 }}>
      <View style={{ height: 3, borderRadius: 2, width: frac * 100 + '%', backgroundColor: toneOf(value, t) }} />
    </View>
  );
}

/**
 * Month-by-month returns as bars off a zero line: up green, down orange, one
 * bar per month, oldest on the left. Heights are scaled to the biggest month
 * on screen, so the shape is comparable within a chart and never across one.
 * Each bar carries its own number — the picture shows the shape, the label
 * gives the fact.
 */
const CHART_H = 58;

function Bars({ values, t, end }) {
  if (!values || !values.length) return null;
  const peak = Math.max(...values.map((v) => Math.abs(v)), 1);
  return (
    <View>
      <View style={{ flexDirection: 'row', height: CHART_H, alignItems: 'stretch' }}>
        {/* the zero line the bars hang off */}
        <View
          pointerEvents="none"
          style={{ position: 'absolute', left: 0, right: 0, top: CHART_H / 2, height: 1, backgroundColor: t.rule }}
        />
        {values.map((v, i) => {
          const h = Math.max((Math.abs(v) / peak) * (CHART_H / 2 - 2), 1.5);
          return (
            <View key={i} style={{ flex: 1, marginHorizontal: 1.5 }}>
              <View style={{ height: CHART_H / 2, justifyContent: 'flex-end' }}>
                {v >= 0 ? (
                  <View style={{ height: h, borderRadius: 2, backgroundColor: t.pos }} />
                ) : null}
              </View>
              <View style={{ height: CHART_H / 2, justifyContent: 'flex-start' }}>
                {v < 0 ? (
                  <View style={{ height: h, borderRadius: 2, backgroundColor: t.neg }} />
                ) : null}
              </View>
            </View>
          );
        })}
      </View>
      <View style={{ flexDirection: 'row', marginTop: 5 }}>
        {values.map((v, i) => (
          <Text
            key={i}
            numberOfLines={1}
            style={{
              flex: 1, textAlign: 'center', fontFamily: MONO, fontSize: 8.5,
              color: v < 0 ? t.neg : t.muted,
            }}
          >
            {/* one decimal: a +0.3% month must not render as "+0" */}
            {(v >= 0 ? '+' : '') + v.toFixed(1)}
          </Text>
        ))}
      </View>
      <Text style={{ color: t.faint, fontSize: 11, marginTop: 8, lineHeight: 16 }}>
        Each bar is one month, oldest on the left, ending {end}. Percent change in that month.
      </Text>
    </View>
  );
}

/** A screen-wide press target. Every interaction in this app is one of these. */
function Row({ t, onPress, children, last }) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => ({
        paddingHorizontal: 16,
        paddingVertical: 13,
        backgroundColor: pressed ? t.ruleSoft : t.surface,
        borderBottomWidth: last ? 0 : 1,
        borderBottomColor: t.ruleSoft,
      })}
    >
      {children}
    </Pressable>
  );
}

/** The grouped-list container: one card, rows inside it, iOS-style. */
function Card({ t, children, style }) {
  return (
    <View
      style={{
        backgroundColor: t.surface,
        borderRadius: 12,
        borderWidth: 1,
        borderColor: t.rule,
        overflow: 'hidden',
        ...(style || {}),
      }}
    >
      {children}
    </View>
  );
}

function GroupLabel({ t, children, right }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'flex-end', marginTop: 22, marginBottom: 7, paddingHorizontal: 4 }}>
      <Text style={{ color: t.faint, fontSize: 11.5, letterSpacing: 0.7, textTransform: 'uppercase', flex: 1 }}>
        {children}
      </Text>
      {right ? <Text style={{ color: t.faint, fontSize: 11.5 }}>{right}</Text> : null}
    </View>
  );
}

/**
 * The bar every screen but the first carries. Back names where it goes —
 * "‹ Technology", not "‹ Back" — so the way out is legible without having to
 * remember the route in.
 */
function NavBar({ t, title, back, onBack, action }) {
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        paddingHorizontal: 8,
        paddingVertical: 6,
        borderBottomWidth: 1,
        borderBottomColor: t.ruleSoft,
        backgroundColor: t.ground,
      }}
    >
      <Pressable
        onPress={onBack}
        hitSlop={12}
        style={({ pressed }) => ({ paddingHorizontal: 8, paddingVertical: 7, opacity: pressed ? 0.5 : 1 })}
      >
        <Text numberOfLines={1} style={{ color: t.accent, fontSize: 16, fontWeight: '600' }}>
          {'‹ ' + back}
        </Text>
      </Pressable>
      <Text numberOfLines={1} style={{ color: t.ink, fontSize: 15, fontWeight: '600', flex: 1, textAlign: 'center' }}>
        {title}
      </Text>
      <View style={{ minWidth: 74, alignItems: 'flex-end', paddingRight: 8 }}>{action}</View>
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
  const dot = stale ? t.neg : { baked: t.faint, checking: t.faint, live: t.pos, stale: t.neg }[state];

  return (
    <View style={{ flexDirection: 'row', alignItems: 'flex-start', paddingHorizontal: 4 }}>
      <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: dot, marginRight: 7, marginTop: 5 }} />
      <Text style={{ color: t.faint, fontSize: 11.5, flex: 1, lineHeight: 16 }}>
        {line}
        {FEED.url ? ' Pull down to refresh.' : ''}
        {stale ? <Text style={{ color: t.neg }}>{' '}These are {age} days old — nobody has refreshed them.</Text> : null}
      </Text>
    </View>
  );
}

// ---- screen 1: the sectors --------------------------------------------------

/**
 * The whole market as eleven rows. Rank, name, what it did in plain words,
 * the score, and a hairline for size. Nothing to decode and nothing to aim
 * at — the row is the target and it spans the screen.
 */
function SectorsScreen({ data, tiers, tab, setTab, t, peak, wlCount, onOpenSector, onOpenWatchlist, onOpenHow, state }) {
  const active = tiers[Math.min(tab, tiers.length - 1)];
  return (
    <View style={{ paddingHorizontal: 14, paddingBottom: 40 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 8, marginBottom: 8 }}>
        <Text style={{ color: t.ink, fontSize: 26, fontWeight: '700', flex: 1, letterSpacing: -0.4 }}>
          Sectors
        </Text>
        <Pressable
          onPress={onOpenWatchlist}
          hitSlop={10}
          style={({ pressed }) => ({ paddingHorizontal: 10, paddingVertical: 6, opacity: pressed ? 0.5 : 1 })}
        >
          <Text style={{ color: t.accent, fontSize: 14, fontWeight: '600' }}>
            Watchlist{wlCount ? ' ' + wlCount : ''}
          </Text>
        </Pressable>
      </View>

      <Freshness state={state} asOf={data.meta.asOf} asOfISO={data.meta.asOfISO} t={t} />

      {tiers.length > 1 && (
        <View style={{ flexDirection: 'row', backgroundColor: t.ruleSoft, borderRadius: 9, padding: 3, marginTop: 12 }}>
          {tiers.map((tier, i) => {
            const on = i === tiers.indexOf(active);
            return (
              <Pressable
                key={tier.key}
                onPress={() => { if (!on) { tapped(); setTab(i); } }}
                style={{
                  flex: 1, paddingVertical: 7, alignItems: 'center', borderRadius: 7,
                  backgroundColor: on ? t.surface : 'transparent',
                }}
              >
                <Text style={{ color: on ? t.ink : t.faint, fontSize: 13, fontWeight: '600' }}>{tier.label}</Text>
              </Pressable>
            );
          })}
        </View>
      )}

      <GroupLabel t={t} right="best first">Nine months, steadiest climb first</GroupLabel>

      <Card t={t}>
        {active.sectors.map((s, i) => (
          <Row key={s.name} t={t} onPress={() => onOpenSector(s)} last={i === active.sectors.length - 1}>
            <View style={{ flexDirection: 'row', alignItems: 'center' }}>
              <Text style={{ color: t.faint, fontFamily: MONO, fontSize: 12, width: 24 }}>{s.rank}</Text>
              <View style={{ flex: 1, paddingRight: 10 }}>
                <Text style={{ color: t.ink, fontSize: 17, fontWeight: '600' }}>{s.name}</Text>
                <Text numberOfLines={1} style={{ color: t.muted, fontSize: 12.5, marginTop: 2 }}>
                  {s.verdict} · {s.rising} of {s.n} companies up
                </Text>
              </View>
              <Text style={{ color: toneOf(s.score, t), fontFamily: MONO, fontSize: 17, fontWeight: '700' }}>
                {signed(s.score)}
              </Text>
              <Text style={{ color: t.faint, fontSize: 19, marginLeft: 8, marginTop: -2 }}>›</Text>
            </View>
            <Bar value={s.score} peak={peak} t={t} />
          </Row>
        ))}
      </Card>

      <Pressable
        onPress={onOpenHow}
        style={({ pressed }) => ({ marginTop: 18, paddingVertical: 12, alignItems: 'center', opacity: pressed ? 0.5 : 1 })}
      >
        <Text style={{ color: t.accent, fontSize: 14, fontWeight: '600' }}>What does the score mean?</Text>
      </Pressable>

      <Text style={{ color: t.faint, fontSize: 11, lineHeight: 17, marginTop: 4, paddingHorizontal: 4 }}>
        {data.meta.footer}
      </Text>
    </View>
  );
}

// ---- screen 2: one sector ---------------------------------------------------

/**
 * Every company in one sector as a plain ranked list. The whole point of this
 * screen is that it is boring: rank, ticker, name, score, one hairline. Fifty
 * rows scroll in a second and every one is a comfortable target.
 */
function SectorScreen({ s, t, wl, peak, windowEnd, onOpenCompany }) {
  const scored = s.constituents.filter((c) => c.score !== null);
  const unscored = s.constituents.filter((c) => c.score === null);
  return (
    <View style={{ paddingHorizontal: 14, paddingBottom: 40 }}>
      <View style={{ marginTop: 10, marginBottom: 2, paddingHorizontal: 4 }}>
        <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
          <Text style={{ color: t.ink, fontSize: 25, fontWeight: '700', flex: 1, letterSpacing: -0.4 }}>{s.name}</Text>
          <Text style={{ color: toneOf(s.score, t), fontFamily: MONO, fontSize: 25, fontWeight: '700' }}>
            {signed(s.score)}
          </Text>
        </View>
        <Text style={{ color: t.muted, fontSize: 13, marginTop: 6, lineHeight: 19 }}>
          {s.gloss}. {s.verdict[0].toUpperCase() + s.verdict.slice(1)} over the nine months —
          up {pct(s.ret)} a year with a typical swing of {pct(s.vol)}, and {s.rising} of its {s.n} companies
          climbing on their own.
        </Text>
        {s.etf ? (
          <Text style={{ color: t.faint, fontSize: 12, marginTop: 6 }}>
            The real {s.etf} fund scores {signed(s.etfScore)} over the same stretch.
          </Text>
        ) : null}
      </View>

      {s.m && s.m.length ? (
        <Card t={t} style={{ marginTop: 16 }}>
          <View style={{ paddingHorizontal: 16, paddingVertical: 14 }}>
            <Text style={{ color: t.muted, fontSize: 13, marginBottom: 12 }}>
              The basket, month by month
            </Text>
            <Bars values={s.m} t={t} end={windowEnd} />
          </View>
        </Card>
      ) : null}

      <GroupLabel t={t} right={scored.length + ' companies'}>Strongest first</GroupLabel>

      <Card t={t}>
        {scored.map((c, i) => (
          <Row key={c.ticker} t={t} onPress={() => onOpenCompany(c, s)} last={i === scored.length - 1 && !unscored.length}>
            <View style={{ flexDirection: 'row', alignItems: 'center' }}>
              <Text style={{ color: t.faint, fontFamily: MONO, fontSize: 12, width: 24 }}>{i + 1}</Text>
              <View style={{ flex: 1, paddingRight: 10 }}>
                <Text style={{ color: t.ink, fontFamily: MONO, fontSize: 14, fontWeight: '600' }}>
                  {c.ticker}{wl[c.ticker] ? ' ★' : ''}
                </Text>
                <Text numberOfLines={1} style={{ color: t.muted, fontSize: 12.5, marginTop: 2 }}>{c.name}</Text>
              </View>
              <Text style={{ color: toneOf(c.score, t), fontFamily: MONO, fontSize: 15, fontWeight: '600' }}>
                {signed(c.score)}
              </Text>
              <Text style={{ color: t.faint, fontSize: 19, marginLeft: 8, marginTop: -2 }}>›</Text>
            </View>
            <Bar value={c.score} peak={peak} t={t} />
          </Row>
        ))}
        {unscored.map((c, i) => (
          <Row key={c.ticker} t={t} onPress={() => onOpenCompany(c, s)} last={i === unscored.length - 1}>
            <View style={{ flexDirection: 'row', alignItems: 'center' }}>
              <Text style={{ color: t.faint, fontFamily: MONO, fontSize: 12, width: 24 }}>–</Text>
              <View style={{ flex: 1, paddingRight: 10 }}>
                <Text style={{ color: t.muted, fontFamily: MONO, fontSize: 14 }}>{c.ticker}</Text>
                <Text numberOfLines={1} style={{ color: t.faint, fontSize: 12.5, marginTop: 2 }}>
                  {c.name} · too new to score
                </Text>
              </View>
            </View>
          </Row>
        ))}
      </Card>
    </View>
  );
}

// ---- screen 3: one company --------------------------------------------------

/**
 * One company, and the answer to the only two questions worth asking about
 * it: where does it stand, and what moves with it. The family is a list of
 * rows like everything else, so following one is the same gesture as
 * everything else.
 */
function CompanyScreen({ c, home, kin, t, watched, windowEnd, onWatch, onOpenCompany }) {
  const away = kin.filter((k) => k.sector !== home.sector).length;
  return (
    <View style={{ paddingHorizontal: 14, paddingBottom: 40 }}>
      <View style={{ marginTop: 10, paddingHorizontal: 4 }}>
        <Text style={{ color: t.ink, fontFamily: MONO, fontSize: 27, fontWeight: '700' }}>{c.ticker}</Text>
        <Text style={{ color: t.muted, fontSize: 15, marginTop: 3 }}>{c.name}</Text>
      </View>

      <Card t={t} style={{ marginTop: 16 }}>
        <View style={{ paddingHorizontal: 16, paddingVertical: 14 }}>
          <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
            <Text style={{ color: t.muted, fontSize: 13, flex: 1 }}>Steady-climb score</Text>
            <Text style={{ color: toneOf(c.score, t), fontFamily: MONO, fontSize: 24, fontWeight: '700' }}>
              {signed(c.score)}
            </Text>
          </View>
          <Text style={{ color: t.faint, fontSize: 12.5, marginTop: 8, lineHeight: 18 }}>
            {c.score === null
              ? 'Not scored — it has not been listed long enough to cover the nine months.'
              : ordinal(c.place) + ' of ' + c.of + ' in ' + home.sector +
                (c.gr ? ', and ' + ordinal(c.gr) + ' of ' + c.universe + ' across every sector' : '') + '.'}
          </Text>
        </View>
      </Card>

      {c.m && c.m.length ? (
        <Card t={t} style={{ marginTop: 14 }}>
          <View style={{ paddingHorizontal: 16, paddingVertical: 14 }}>
            <Text style={{ color: t.muted, fontSize: 13, marginBottom: 12 }}>Month by month</Text>
            <Bars values={c.m} t={t} end={windowEnd} />
          </View>
        </Card>
      ) : null}

      <Pressable
        onPress={onWatch}
        style={({ pressed }) => ({
          marginTop: 14,
          paddingVertical: 14,
          borderRadius: 12,
          borderWidth: 1,
          borderColor: watched ? t.rule : t.accent,
          backgroundColor: pressed ? t.ruleSoft : 'transparent',
          alignItems: 'center',
        })}
      >
        <Text style={{ color: watched ? t.muted : t.accent, fontSize: 15, fontWeight: '600' }}>
          {watched ? 'On your watchlist — tap to remove' : 'Add to watchlist'}
        </Text>
      </Pressable>

      <GroupLabel t={t} right={kin.length ? kin.length + ' names' : ''}>What moves with it</GroupLabel>

      {kin.length ? (
        <>
          <Text style={{ color: t.faint, fontSize: 12, lineHeight: 17, marginBottom: 8, paddingHorizontal: 4 }}>
            These rose and fell alongside {c.ticker} day by day
            {away ? ' — ' + away + ' of them from other sectors' : ''}.
          </Text>
          <Card t={t}>
            {kin.map((k, i) => (
              <Row key={k.ticker} t={t} onPress={() => onOpenCompany(k.ticker)} last={i === kin.length - 1}>
                <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                  <View style={{ flex: 1, paddingRight: 10 }}>
                    <Text style={{ color: t.ink, fontFamily: MONO, fontSize: 14, fontWeight: '600' }}>{k.ticker}</Text>
                    <Text numberOfLines={1} style={{ color: t.muted, fontSize: 12.5, marginTop: 2 }}>
                      {k.name} · {k.sector}
                    </Text>
                  </View>
                  <Text style={{ color: toneOf(k.score, t), fontFamily: MONO, fontSize: 14 }}>{signed(k.score)}</Text>
                  <Text style={{ color: t.faint, fontSize: 19, marginLeft: 8, marginTop: -2 }}>›</Text>
                </View>
              </Row>
            ))}
          </Card>
        </>
      ) : (
        <Text style={{ color: t.faint, fontSize: 12.5, lineHeight: 18, paddingHorizontal: 4 }}>
          Nothing else on the page moved closely with it — it went its own way.
        </Text>
      )}
    </View>
  );
}

// ---- watchlist and the explainer -------------------------------------------

function WatchlistScreen({ wl, lookup, t, onOpenCompany }) {
  const rows = Object.keys(wl).filter((k) => lookup[k]).sort();
  if (!rows.length) {
    return (
      <View style={{ paddingHorizontal: 18, paddingTop: 40 }}>
        <Text style={{ color: t.muted, fontSize: 14, lineHeight: 21, textAlign: 'center' }}>
          Nothing saved yet.{'\n'}Open any company and tap “Add to watchlist”.
        </Text>
      </View>
    );
  }
  return (
    <View style={{ paddingHorizontal: 14, paddingBottom: 40 }}>
      <GroupLabel t={t} right={rows.length + ' saved'}>Your watchlist</GroupLabel>
      <Card t={t}>
        {rows.map((k, i) => {
          const c = lookup[k];
          return (
            <Row key={k} t={t} onPress={() => onOpenCompany(k)} last={i === rows.length - 1}>
              <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                <View style={{ flex: 1, paddingRight: 10 }}>
                  <Text style={{ color: t.ink, fontFamily: MONO, fontSize: 14, fontWeight: '600' }}>{k}</Text>
                  <Text numberOfLines={1} style={{ color: t.muted, fontSize: 12.5, marginTop: 2 }}>
                    {c.name} · {c.sector}
                  </Text>
                </View>
                <Text style={{ color: toneOf(c.score, t), fontFamily: MONO, fontSize: 14 }}>{signed(c.score)}</Text>
                <Text style={{ color: t.faint, fontSize: 19, marginLeft: 8, marginTop: -2 }}>›</Text>
              </View>
            </Row>
          );
        })}
      </Card>
    </View>
  );
}

function HowScreen({ meta, t }) {
  return (
    <View style={{ paddingHorizontal: 18, paddingBottom: 44 }}>
      {meta.details.map((d) => (
        <View key={d.title} style={{ marginTop: 22 }}>
          <Text style={{ color: t.ink, fontSize: 15, fontWeight: '600' }}>{d.title}</Text>
          {/* Each paragraph is its own element rather than one blob with
              newlines in it: the breaks are what make this screen readable,
              and spacing between views cannot silently collapse. */}
          {d.body.split('\n\n').map((para, i) => (
            <Text
              key={i}
              style={{
                color: t.muted, lineHeight: d.mono ? 19 : 20, marginTop: i ? 10 : 5,
                fontSize: d.mono ? 12.5 : 13.5,
                fontFamily: d.mono ? MONO : undefined,
              }}
            >
              {para}
            </Text>
          ))}
        </View>
      ))}
      <Text style={{ color: t.faint, fontFamily: MONO, fontSize: 10.5, lineHeight: 16, marginTop: 24 }}>
        {meta.stamp}
      </Text>
    </View>
  );
}

// ---- plumbing ---------------------------------------------------------------

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
  const [data, setData] = useState(BAKED);
  const [state, setState] = useState(FEED.url ? 'checking' : 'baked');
  const [busy, setBusy] = useState(false);
  const [wl, setWl] = useState({});
  const [tab, setTab] = useState(0);
  // A plain navigation stack. Screens are pushed and popped; the hardware
  // back button pops it, so Android behaves the way Android should.
  const [stack, setStack] = useState([{ k: 'sectors' }]);
  const here = stack[stack.length - 1];

  const push = useCallback((screen) => { tapped(); setStack((s) => s.concat([screen])); }, []);
  const pop = useCallback(() => { tapped(); setStack((s) => (s.length > 1 ? s.slice(0, -1) : s)); }, []);

  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (stack.length > 1) { pop(); return true; }
      return false;
    });
    return () => { try { sub.remove(); } catch (e) {} };
  }, [stack.length, pop]);

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
        setStack([{ k: 'sectors' }]);   // the open screens described the old numbers
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

  const toggleWatch = useCallback((ticker) => {
    tapped();
    setWl((prev) => {
      const next = { ...prev };
      if (next[ticker]) delete next[ticker];
      else next[ticker] = true;
      saveWl(next);
      return next;
    });
  }, []);

  const tiers = useMemo(() => tiersOf(data), [data]);
  const active = tiers[Math.min(tab, tiers.length - 1)];

  // Where every ticker lives, with the numbers a row needs. Peers cross
  // sectors and tiers, so a company screen can only describe its family if it
  // can look any ticker up from anywhere.
  const lookup = useMemo(() => {
    const m = {};
    const universe = [];
    tiers.forEach((tier) =>
      tier.sectors.forEach((s) => {
        const scored = s.constituents.filter((c) => c.score !== null);
        s.constituents.forEach((c) => {
          const place = scored.indexOf(c) + 1;
          m[c.ticker] = {
            ticker: c.ticker, name: c.name, score: c.score, sector: s.name,
            tier: tier.key, place: place || null, of: scored.length, m: c.m || [],
          };
          if (c.score !== null) universe.push(m[c.ticker]);
        });
      })
    );
    universe.sort((a, b) => b.score - a.score);
    universe.forEach((c, i) => { c.gr = i + 1; c.universe = universe.length; });
    return m;
  }, [tiers]);

  /**
   * Every company screen sits exactly three deep, whichever route reached it:
   * sectors → its own sector → the company. Following one related name to the
   * next therefore *replaces* the company screen instead of stacking another,
   * so the way out never grows into a trail to tap back through. A company
   * opened from the watchlist keeps the watchlist as its parent, because that
   * is the list the reader was working through.
   */
  const openCompany = useCallback((ticker) => {
    const c = lookup[ticker];
    if (!c) return;
    tapped();
    setStack((s) => {
      const fromWatchlist = s.some((x) => x.k === 'watchlist');
      const parent = fromWatchlist
        ? { k: 'watchlist' }
        : { k: 'sector', name: c.sector, tier: c.tier };
      return [{ k: 'sectors' }, parent, { k: 'company', ticker }];
    });
  }, [lookup]);

  const peak = Math.max(...active.sectors.map((s) => Math.abs(s.score)), 0.01);
  const namePeak = 3;   // scores past ±3 are rare; a fixed peak keeps bars comparable across sectors

  const BACK_LABELS = { sectors: 'Sectors', watchlist: 'Watchlist', how: 'How this works' };
  const under = stack[stack.length - 2];
  const back = under ? (under.k === 'sector' ? under.name : BACK_LABELS[under.k] || 'Back') : 'Back';

  let title = '';
  let body = null;
  if (here.k === 'sectors') {
    body = (
      <SectorsScreen
        data={data} tiers={tiers} tab={tab} setTab={setTab} t={t} peak={peak}
        state={state} wlCount={Object.keys(wl).filter((k) => lookup[k]).length}
        onOpenSector={(s) => push({ k: 'sector', name: s.name, tier: s.tier })}
        onOpenWatchlist={() => push({ k: 'watchlist' })}
        onOpenHow={() => push({ k: 'how' })}
      />
    );
  } else if (here.k === 'sector') {
    const s = (tiers.find((x) => x.key === here.tier) || active).sectors.find((x) => x.name === here.name);
    title = here.name;
    body = s ? (
      <SectorScreen
        s={s} t={t} wl={wl} peak={namePeak} windowEnd={data.meta.windowEnd}
        onOpenCompany={(c) => openCompany(c.ticker)}
      />
    ) : null;
  } else if (here.k === 'company') {
    const c = lookup[here.ticker];
    title = here.ticker;
    const kin = ((data.peers || {})[here.ticker] || [])
      .map(([ticker]) => lookup[ticker])
      .filter(Boolean);
    body = c ? (
      <CompanyScreen
        c={c} home={c} kin={kin} t={t} watched={!!wl[here.ticker]} windowEnd={data.meta.windowEnd}
        onWatch={() => toggleWatch(here.ticker)} onOpenCompany={openCompany}
      />
    ) : null;
  } else if (here.k === 'watchlist') {
    title = 'Watchlist';
    body = <WatchlistScreen wl={wl} lookup={lookup} t={t} onOpenCompany={openCompany} />;
  } else if (here.k === 'how') {
    title = 'How this works';
    body = <HowScreen meta={data.meta} t={t} />;
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: t.ground }}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      {stack.length > 1 && (
        <NavBar
          t={t}
          title={title}
          back={back}
          onBack={pop}
          action={
            here.k === 'company' ? (
              <Pressable onPress={() => toggleWatch(here.ticker)} hitSlop={12} style={{ paddingVertical: 7 }}>
                <Text style={{ color: wl[here.ticker] ? t.accent : t.faint, fontSize: 17 }}>
                  {wl[here.ticker] ? '★' : '☆'}
                </Text>
              </Pressable>
            ) : null
          }
        />
      )}
      <ScrollView
        // Keyed by screen so every push lands at the top of the new screen
        // rather than halfway down the last one.
        key={here.k + ':' + (here.ticker || here.name || '')}
        contentContainerStyle={{ paddingBottom: 24 }}
        showsVerticalScrollIndicator={false}
        refreshControl={
          FEED.url && here.k === 'sectors' ? (
            <RefreshControl refreshing={busy} onRefresh={() => load(true)} tintColor={t.faint} />
          ) : undefined
        }
      >
        {body}
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
            "verdict": verdict_for(s["score"]),
            "m": s.get("monthly") or [],
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
                    "m": c.get("monthly") or [],
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

    # The explainer states the arithmetic outright and works one real example
    # from this very payload, so a reader can check the number on screen
    # against the sentence. Vague hedges ("about 1.0", "a few weeks", "flatters
    # them a little") and any mention of a control the app no longer has are
    # bugs here, not style.
    lead = rendered[0][0]
    lead_ret = round(lead["ret"] * 100, 1)
    lead_vol = round(lead["vol"] * 100, 1)
    sizes = sorted({s["n"] for tier in rendered for s in tier})
    short = [s for tier in rendered for s in tier if s["n"] < config.SECTOR_INDEX_SIZE]

    details = [
        {
            "title": "The formula",
            "mono": True,
            "body": (
                "score  =  rise ÷ swing\n\n"
                "rise    yearly % gain over the nine months\n"
                "swing   yearly % up-and-down over the same days\n\n"
                f"{lead['name']}\n"
                f"{lead_ret} ÷ {lead_vol} = {lead['score']:.2f}"
            ),
        },
        {
            "title": "Reading it",
            "body": (
                "Above 1.00 the sector rose faster than it moved around. "
                "0 is flat. Below 0 it fell.\n\n"
                "Swing is the number each sector page calls its typical swing."
            ),
        },
        {
            "title": "Which nine months",
            "body": (
                f"{pretty_date(first['window_start'])} to "
                f"{pretty_date(first['window_end'])} — {obs} trading days.\n\n"
                f"That window ends {skip_days} trading days (one month) before the "
                f"latest prices, and those {skip_days} days are left out of every "
                "number on the screen. A share that jumped in the last few weeks "
                "often gives it back, so counting that jump would make a sector look "
                "stronger than it is."
            ),
        },
        {
            "title": "What a sector is here",
            "body": (
                "Not a real fund — a list built from scratch.\n\n"
                "Every US-listed company worth more than "
                f"${config.SCREEN_MIN_MARKET_CAP / 1e9:.0f} billion is sorted by how "
                "much of it is bought and sold on an average day. The busiest "
                f"{config.SECTOR_INDEX_SIZE} in each sector make the list.\n\n"
                f"All {config.SECTOR_INDEX_SIZE} count the same amount — "
                f"{100 / config.SECTOR_INDEX_SIZE:.0f}% each — so one giant company "
                "cannot speak for the whole sector."
                + (
                    "\n\n"
                    + "; ".join(
                        f"{x['name']} has {x['n']}" for x in short
                    )
                    + f" instead of {config.SECTOR_INDEX_SIZE}, because that is how "
                    "many companies in it clear the size and trading bar."
                    if short
                    else ""
                )
            ),
        },
        {
            "title": "The “x of 50 up” line",
            "body": (
                "Every company is scored on its own with the same arithmetic. That "
                "line counts how many finished above zero.\n\n"
                "It matters because a sector can score well on the strength of a few "
                "names while most of it went nowhere. A high count means the whole "
                "sector moved; a low count means a handful carried it."
            ),
        },
        {
            "title": "The real fund on each sector page",
            "body": (
                "Each sector page names the matching SPDR fund — XLK for technology, "
                "XLE for energy — and scores it over the identical nine months.\n\n"
                "It will not match. That fund holds companies in proportion to their "
                f"size and holds more than {config.SECTOR_INDEX_SIZE} of them; this "
                "basket holds the busiest "
                f"{config.SECTOR_INDEX_SIZE} in equal amounts. It is there as a check "
                "that the sector is being read roughly right, not as the same thing."
            ),
        },
        {
            "title": "What this does not tell you",
            "body": (
                f"The {config.SECTOR_INDEX_SIZE} companies in each list are chosen "
                "using today's trading, and then their prices are read backwards over "
                "the past nine months. Companies that collapsed and dropped off the "
                "list are not in it. That makes the past look better than it was, and "
                "it means these are not returns anyone could have earned.\n\n"
                "This ranks sectors as they stand today. It is not a trading record "
                "and it is not advice."
                + (
                    "\n\nPut in the same order as the eleven real SPDR sector funds "
                    f"over these nine months, the two orderings line up at {rho:.2f} — "
                    "1.00 would be identical, 0 would be unrelated."
                    if rho else ""
                )
            ),
        },
    ]

    return {
        "meta": {
            "asOf": pretty_date(payload["as_of"]),
            "asOfISO": payload["as_of"],
            "windowEnd": pretty_date(first["window_end"]),
            "tiers": [
                {"key": t["key"], "label": t["label"], "note": t["note"]}
                for t in tiers
            ],
            # Describes the data only. What the screen looks like — and how it
            # is touched — is the app's business; a feed line about squares
            # once outlived the squares.
            "blurb": (
                f"{len(rendered[0])} corners of the US market, best first, by how "
                f"steadily they climbed over nine months."
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
