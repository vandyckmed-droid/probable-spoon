"""The phone build: payload -> App.js. No network, no Expo."""
import json
import re

import pytest

import config
import sector_snack


def _payload(n=3):
    """Minimal ranking payload shaped like sector_index writes it."""
    def sector(name, rank, score, etf):
        return {
            "sector": name,
            "rank": rank,
            "score": score,
            "ann_log_return": score * 0.2,
            "ann_vol": 0.2,
            "breadth": 0.6,
            "n_constituents": n,
            "window_start": "2025-11-05",
            "window_end": "2026-07-10",
            "window_obs": 168,
            "median_dollar_volume": 1e9,
            "log_return_9_1": score * 0.13,
            "constituents": [
                {
                    "ticker": f"{name[:2].upper()}{i}",
                    "name": f"{name} Holdings, Inc",
                    "industry": "x",
                    "market_cap": 1e10,
                    "median_dollar_volume": 1e8,
                    "score": None if i == n - 1 else 1.0 - i,
                    "sector_z": None if i == n - 1 else 1.0 - i,
                    "sector_rank": None if i == n - 1 else i + 1,
                    "ann_log_return": 0.1,
                    "ann_vol": 0.2,
                }
                for i in range(n)
            ],
        }

    return {
        "as_of": "2026-08-10",
        "generated": "2026-08-11T04:00:00",
        "method": "...",
        "sectors": [sector("Technology", 1, 2.3, "XLK"), sector("Utilities", 2, -0.4, "XLU")],
        "benchmark": {
            "etfs": {
                "Technology": {"etf": "XLK", "score": 1.9},
                "Utilities": {"etf": "XLU", "score": -0.2},
            },
            "rank_correlation": 0.74,
        },
    }


# ---------- helpers ----------

@pytest.mark.parametrize("raw, want", [
    ("Sandisk Corporation", "Sandisk"),
    ("Cisco Systems, Inc.", "Cisco Systems"),
    ("Linde plc", "Linde"),
    ("Prologis Trust, Inc", "Prologis"),
    ("Alphabet Inc.", "Alphabet"),
    ("3M", "3M"),                       # nothing to strip
])
def test_trim_company_drops_legal_boilerplate(raw, want):
    assert sector_snack.trim_company(raw) == want


def test_trim_company_never_empties_a_name():
    assert sector_snack.trim_company("Inc.") == "Inc."


def test_pretty_date():
    assert sector_snack.pretty_date("2026-08-10") == "10 August 2026"
    assert sector_snack.pretty_date("not-a-date") == "not-a-date"


# ---------- payload -> render data ----------

def test_build_data_keeps_every_sector_and_name():
    data = sector_snack.build_data(_payload())

    assert [s["rank"] for s in data["sectors"]] == [1, 2]
    assert all(len(s["constituents"]) == s["n"] for s in data["sectors"])
    assert all(s["gloss"] for s in data["sectors"])          # every sector reads in plain words


def test_rising_count_is_whole_names_not_a_fraction():
    data = sector_snack.build_data(_payload(n=25))
    top = data["sectors"][0]

    assert top["rising"] == 15                                # 0.6 of 25
    assert top["n"] == 25
    assert isinstance(top["rising"], int)


def test_unscorable_names_survive_as_nulls():
    data = sector_snack.build_data(_payload())
    last = data["sectors"][0]["constituents"][-1]

    assert last["score"] is None and last["z"] is None
    assert last["ticker"]                                     # still listed, just blank-scored


def test_meta_reads_in_plain_words():
    meta = sector_snack.build_data(_payload())["meta"]

    assert meta["asOf"] == "10 August 2026"
    assert len(meta["details"]) >= 4
    assert all(d["title"] and d["body"] for d in meta["details"])
    assert "74%" in meta["details"][-1]["body"]               # benchmark agreement, as a percent
    assert str(config.SECTOR_INDEX_SIZE) in json.dumps(meta)  # basket size is data-driven


def test_meta_survives_a_payload_with_no_benchmark():
    payload = _payload()
    del payload["benchmark"]
    meta = sector_snack.build_data(payload)["meta"]

    assert meta["details"]
    assert sector_snack.build_data(payload)["sectors"][0]["etfScore"] is None


# ---------- render ----------

def test_render_bakes_the_data_into_the_bundle():
    src = sector_snack.render_app(_payload())

    assert "__DATA__" not in src
    assert src.startswith("import React")
    baked = json.loads(re.search(r"^const BAKED = (.*);$", src, re.M).group(1))
    assert len(baked["sectors"]) == 2


def test_every_import_is_one_snack_can_resolve():
    """Anything not built in has to be declared, or Expo Go fails to load it."""
    src = sector_snack.render_app(_payload())
    # Anchored on the statement terminator so prose containing "from '" is skipped.
    imports = set(re.findall(r"from '([^']+)';\s*$", src, re.M))

    assert {"react", "react-native"} <= imports
    assert imports - {"react", "react-native"} == set(sector_snack.SNACK_DEPENDENCIES)


def test_haptics_never_take_the_screen_down():
    """A phone with the feature off must lose the buzz, not the app."""
    src = sector_snack.render_app(_payload())

    assert "const buzz = (fn) => { try { fn(); } catch (e) {} };" in src
    for call in ("Haptics.selectionAsync", "Haptics.impactAsync", "Haptics.notificationAsync"):
        assert f"buzz(() => {call}" in src


# ---------- the live feed ----------

def _feed_const(src):
    return json.loads(re.search(r"^const FEED = (.*);$", src, re.M).group(1))


def test_feed_url_is_baked_in_when_given():
    src = sector_snack.render_app(_payload(), feed_url="https://example.test/f.json")
    feed = _feed_const(src)

    assert "__FEED__" not in src
    assert feed["url"] == "https://example.test/f.json"
    assert feed["timeoutMs"] == config.SECTOR_FEED_TIMEOUT_MS


def test_no_feed_url_leaves_the_app_on_the_baked_snapshot():
    src = sector_snack.render_app(_payload())

    assert _feed_const(src)["url"] == ""
    assert "__FEED__" not in src


def test_feed_and_baked_snapshot_are_the_same_object():
    """A phone on the feed and a phone offline must render identically."""
    payload = _payload()
    src = sector_snack.render_app(payload, feed_url="https://example.test/f.json")
    baked = json.loads(re.search(r"^const BAKED = (.*);$", src, re.M).group(1))

    assert baked == sector_snack.build_data(payload)


def test_every_sector_gets_its_own_colour():
    data = sector_snack.build_data(_payload())
    hues = [s["hue"] for s in data["sectors"]]

    assert all(re.fullmatch(r"#[0-9a-f]{6}", h) for h in hues)
    assert len(set(hues)) == len(hues)
    # Every sector the pipeline can emit needs one, or it silently falls back.
    assert set(sector_snack.SECTOR_HUE) == set(sector_snack.SECTOR_GLOSS)
    assert len(set(sector_snack.SECTOR_HUE.values())) == len(sector_snack.SECTOR_HUE)


def test_peers_ride_along_as_compact_pairs():
    payload = _payload()
    payload["peers"] = {
        "TE0": [{"ticker": "UT1", "r": 0.81}, {"ticker": "TE1", "r": 0.62}],
        "TE1": [],                                    # nothing correlated enough
    }
    peers = sector_snack.build_data(payload)["peers"]

    assert peers["TE0"] == [["UT1", 0.81], ["TE1", 0.62]]
    assert "TE1" not in peers                         # empty lists are dead weight


def test_a_payload_with_no_peers_still_builds():
    """Older payloads predate the correlation pass; the app must not care."""
    payload = _payload()
    payload.pop("peers", None)

    assert sector_snack.build_data(payload)["peers"] == {}


def test_feed_carries_a_parseable_date_for_the_staleness_check():
    """asOf is prose for the reader; asOfISO is what the age arithmetic needs."""
    meta = sector_snack.build_data(_payload())["meta"]

    assert meta["asOfISO"] == "2026-08-10"
    assert meta["asOf"] == "10 August 2026"


def test_staleness_threshold_travels_with_the_feed_config():
    src = sector_snack.render_app(_payload(), feed_url="https://example.test/f.json")

    assert _feed_const(src)["staleAfterDays"] == config.SECTOR_STALE_AFTER_DAYS
    assert "function ageInDays(" in src


def test_the_app_guards_against_a_broken_feed():
    """A 404, a timeout or junk JSON must not blank the screen."""
    src = sector_snack.render_app(_payload(), feed_url="https://example.test/f.json")

    assert "function usable(" in src           # shape check before the feed is trusted
    assert "useState(BAKED)" in src            # the snapshot is what it starts from
    assert ".catch(() => setState('stale'))" in src
