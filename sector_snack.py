"""Emit the sector ranking as an Expo Snack app and publish it.

The heatmap does not survive a phone screen as an 11 x 25 grid, so the phone
build inverts it: a tappable list of sectors, each opening into its own 25
names shaded on the same within-sector z. Data is baked into the bundle, so
the app needs no network once Expo Go has loaded it.

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
    "Communication Services": "Comm. Services",
    "Consumer Cyclical": "Consumer Cyc.",
    "Consumer Defensive": "Consumer Def.",
}

APP_TEMPLATE = r"""
import React, { useState } from 'react';
import {
  SafeAreaView, ScrollView, View, Text, Pressable, useColorScheme,
  StatusBar, Platform,
} from 'react-native';

const DATA = __DATA__;

const LIGHT = {
  ground: '#f6f7f6', surface: '#ffffff', ink: '#14201d', muted: '#5d6c68',
  rule: '#dfe4e1', ruleSoft: '#ecefed', pos: '#1d6b5f', neg: '#a64a32',
  n3: '#e5b09c', n2: '#eec9b9', n1: '#f5e0d6', z0: '#e9eeec',
  p1: '#d5e8e3', p2: '#b0d8ce', p3: '#86c4b6', na: '#e4e8e6',
};
const DARK = {
  ground: '#0f1513', surface: '#161e1c', ink: '#e6ece9', muted: '#8fa09b',
  rule: '#26302e', ruleSoft: '#1d2624', pos: '#58bfad', neg: '#d8735a',
  n3: '#6b3527', n2: '#4f2b21', n1: '#33221d', z0: '#1d2624',
  p1: '#1e3b36', p2: '#235349', p3: '#2c6f61', na: '#1a201f',
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

const pct = (x) => (x === null || x === undefined ? '—' : (x * 100).toFixed(1) + '%');
const signed = (x) => (x >= 0 ? '+' : '') + x.toFixed(2);

function Bar({ score, peak, t }) {
  const frac = Math.min(Math.abs(score) / peak, 1);
  const up = score >= 0;
  return (
    <View style={{ flexDirection: 'row', height: 6, marginTop: 10 }}>
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
      <Text style={{ color: t.muted, fontSize: 10, letterSpacing: 0.8, textTransform: 'uppercase' }}>
        {label}
      </Text>
      <Text style={{ color: tone || t.ink, fontFamily: MONO, fontSize: 13, marginTop: 2 }}>
        {value}
      </Text>
    </View>
  );
}

function Chip({ c, t }) {
  return (
    <View
      style={{
        backgroundColor: t[shade(c.z)],
        borderRadius: 3,
        paddingVertical: 5,
        paddingHorizontal: 7,
        margin: 2,
        minWidth: 62,
        alignItems: 'center',
      }}
    >
      <Text style={{ color: t.ink, fontFamily: MONO, fontSize: 11 }}>{c.ticker}</Text>
      <Text style={{ color: t.muted, fontFamily: MONO, fontSize: 9, marginTop: 1 }}>
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
        borderRadius: 6,
        padding: 14,
        marginBottom: 10,
      }}
    >
      <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
        <Text style={{ color: t.muted, fontFamily: MONO, fontSize: 12, width: 22 }}>{s.rank}</Text>
        <Text style={{ color: t.ink, fontSize: 17, fontWeight: '600', flex: 1 }}>{s.name}</Text>
        <Text style={{ color: tone, fontFamily: MONO, fontSize: 17, fontWeight: '700' }}>
          {signed(s.score)}
        </Text>
      </View>

      <Bar score={s.score} peak={peak} t={t} />

      <View style={{ flexDirection: 'row', marginTop: 12, gap: 8 }}>
        <Stat label="Ann ret" value={pct(s.ret)} t={t} tone={s.ret < 0 ? t.neg : t.ink} />
        <Stat label="Ann vol" value={pct(s.vol)} t={t} />
        <Stat label="Breadth" value={Math.round(s.breadth * 100) + '%'} t={t} />
        <Stat label="SPDR" value={s.etfScore === null ? '—' : signed(s.etfScore) + ' ' + s.etf} t={t} />
      </View>

      {open && (
        <View style={{ marginTop: 14, borderTopWidth: 1, borderTopColor: t.ruleSoft, paddingTop: 12 }}>
          <Text style={{ color: t.muted, fontSize: 11, marginBottom: 8, lineHeight: 16 }}>
            All 25 names, best first. Shading is each name’s z-score against the other 24 —
            never across sectors.
          </Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
            {s.constituents.map((c) => <Chip key={c.ticker} c={c} t={t} />)}
          </View>
        </View>
      )}

      <Text style={{ color: t.muted, fontSize: 11, marginTop: 10 }}>
        {open ? 'Tap to collapse' : 'Tap for all 25 names'}
      </Text>
    </Pressable>
  );
}

function Legend({ t }) {
  const keys = ['n3', 'n2', 'n1', 'z0', 'p1', 'p2', 'p3'];
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 4, flexWrap: 'wrap' }}>
      <Text style={{ color: t.muted, fontFamily: MONO, fontSize: 10, marginRight: 6 }}>−1.5σ</Text>
      {keys.map((k) => (
        <View
          key={k}
          style={{
            width: 20, height: 10, backgroundColor: t[k], borderRadius: 2,
            borderWidth: 1, borderColor: t.rule, marginRight: 2,
          }}
        />
      ))}
      <Text style={{ color: t.muted, fontFamily: MONO, fontSize: 10, marginLeft: 4 }}>+1.5σ</Text>
      <Text style={{ color: t.muted, fontSize: 10, marginLeft: 8 }}>z within sector</Text>
    </View>
  );
}

export default function App() {
  const dark = useColorScheme() === 'dark';
  const t = dark ? DARK : LIGHT;
  const [open, setOpen] = useState(null);
  const peak = Math.max(...DATA.sectors.map((s) => Math.abs(s.score)));

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: t.ground }}>
      <StatusBar barStyle={dark ? 'light-content' : 'dark-content'} />
      <ScrollView
        contentContainerStyle={{ padding: 16, paddingBottom: 48 }}
        showsVerticalScrollIndicator={false}
      >
        <Text style={{ color: t.muted, fontSize: 10, letterSpacing: 1.4, textTransform: 'uppercase' }}>
          Equal-weight sector indices · 25 names each
        </Text>
        <Text style={{ color: t.ink, fontSize: 26, fontWeight: '700', marginTop: 6, lineHeight: 31 }}>
          Volatility-adjusted{'\n'}9-1 momentum
        </Text>
        <Text style={{ color: t.muted, fontSize: 13, marginTop: 10, lineHeight: 19 }}>
          {DATA.meta.blurb}
        </Text>

        <View
          style={{
            borderTopWidth: 1, borderTopColor: t.rule, marginTop: 14, paddingTop: 10, marginBottom: 18,
          }}
        >
          <Text style={{ color: t.muted, fontFamily: MONO, fontSize: 11, lineHeight: 17 }}>
            window {DATA.meta.windowStart} → {DATA.meta.windowEnd}{'\n'}
            {DATA.meta.obs} obs · prices through {DATA.meta.asOf} · {DATA.meta.names} names
          </Text>
          <Legend t={t} />
        </View>

        {DATA.sectors.map((s) => (
          <SectorCard
            key={s.name}
            s={s}
            peak={peak}
            t={t}
            open={open === s.name}
            onToggle={() => setOpen(open === s.name ? null : s.name)}
          />
        ))}

        <Text style={{ color: t.muted, fontSize: 11, lineHeight: 17, marginTop: 8 }}>
          {DATA.meta.method}
        </Text>
        <Text style={{ color: t.muted, fontSize: 11, lineHeight: 17, marginTop: 10 }}>
          {DATA.meta.caveat}
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
            "rank": s["rank"],
            "score": round(s["score"], 4),
            "ret": round(s["ann_log_return"], 5),
            "vol": round(s["ann_vol"], 5),
            "breadth": round(s["breadth"], 4),
            "etf": etf["etf"] if etf else "",
            "etfScore": round(etf["score"], 3) if etf else None,
            "constituents": [
                {
                    "ticker": c["ticker"],
                    "score": None if c["score"] is None else round(c["score"], 3),
                    "z": None if c["sector_z"] is None else round(c["sector_z"], 3),
                }
                for c in s["constituents"]
            ],
        })

    return {
        "meta": {
            "asOf": payload["as_of"],
            "windowStart": first["window_start"],
            "windowEnd": first["window_end"],
            "obs": obs,
            "names": sum(s["n_constituents"] for s in payload["sectors"]),
            "blurb": (
                f"{len(sectors)} synthetic sector ETFs, each an equal-weight basket of "
                f"that sector's {config.SECTOR_INDEX_SIZE} most liquid US-listed stocks, "
                f"rebalanced daily. Tap any sector for its names."
            ),
            "method": (
                f"Score = annualised 9-1 log return over annualised vol, both measured on "
                f"the same {obs}-day window (t−{long_days}d to t−{skip_days}d, skipping the "
                f"last month). Breadth is the share of the 25 names positive on their own."
            ),
            "caveat": (
                "Membership is today's most liquid names applied to past prices, so the "
                "history carries that survivorship. Ranks sectors as they stand; not a "
                "tradable backtest."
                + (f" Rank correlation with the SPDR sector ETFs: {rho:.2f}." if rho else "")
            ),
        },
        "sectors": sectors,
    }


def render_app(payload: dict) -> str:
    data = json.dumps(build_data(payload), separators=(",", ":"))
    return APP_TEMPLATE.replace("__DATA__", data).lstrip("\n")


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
    args = ap.parse_args()

    src = Path(config.SECTOR_OUTPUT_DIR) / "sector_etf_ranking.json"
    if not src.exists():
        raise SystemExit(f"{src} not found — run sector_index.py first")
    with open(src, encoding="utf-8") as f:
        payload = json.load(f)

    source = render_app(payload)
    out = Path(config.SECTOR_OUTPUT_DIR) / "App.js"
    out.write_text(source, encoding="utf-8")
    print(f"wrote {out} ({len(source):,} bytes)")

    if args.publish:
        try:
            result = publish(
                source,
                name="Sector momentum 9-1",
                description=f"Vol-adjusted 9-1 sector ranking, prices through {payload['as_of']}",
            )
        except urllib.error.HTTPError as e:
            raise SystemExit(f"snack save failed: {e.code} {e.read().decode()[:300]}")
        snack_id = result.get("hashId") or result.get("id")
        print(f"snack id   {snack_id}")
        print(f"web        https://snack.expo.dev/{snack_id}")
        print(f"expo go    exp://exp.host/@snack/{snack_id}")


if __name__ == "__main__":
    main()
