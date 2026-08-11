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

    top = [sector("Technology", 1, 2.3, "XLK"), sector("Utilities", 2, -0.4, "XLU")]
    nxt = [sector("Technology", 1, 1.1, "XLK")]
    for s in nxt:                                   # tier 2 holds different names
        for i, c in enumerate(s["constituents"]):
            c["ticker"] = "N" + c["ticker"]
    return {
        "as_of": "2026-08-10",
        "generated": "2026-08-11T04:00:00",
        "method": "...",
        "tiers": [
            {"key": "top", "label": "Top 25", "note": "the most-traded", "sectors": top},
            {"key": "next", "label": "Next 25", "note": "one rung down", "sectors": nxt},
        ],
        "sectors": top,
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
    # A rank correlation is not a percentage of agreement; say what it is.
    assert "0.74" in meta["details"][-1]["body"]
    assert "1.00 would be identical" in meta["details"][-1]["body"]
    assert "74%" not in json.dumps(meta)
    assert str(config.SECTOR_INDEX_SIZE) in json.dumps(meta)  # basket size is data-driven


def test_the_explainer_states_the_arithmetic_and_works_an_example():
    """A reader must be able to check the sentence against the number on the
    row, so the example is computed from this very payload."""
    body = sector_snack.build_data(_payload())["meta"]["details"][0]["body"]
    top = sector_snack.build_data(_payload())["sectors"][0]

    assert "÷" in body and "one divided by the other" in body
    assert f"{round(top['ret'] * 100, 1)}" in body
    assert f"{round(top['vol'] * 100, 1)}" in body
    assert f"= {top['score']:.2f}" in body


def test_the_explainer_never_hedges_or_describes_a_control_that_is_gone():
    """Vague hedges and stale UI references are bugs on this screen. Two
    sections once described a heatmap's shading toggle and a 'column' that no
    longer exist, and the score was called a 'climb-per-bump'."""
    meta = sector_snack.build_data(_payload())["meta"]
    prose = " ".join(d["title"] + " " + d["body"] for d in meta["details"]).lower()

    for gone in ("two ways to shade", "colours each company", "column",
                 "climb-per-bump", "whole market"):
        assert gone not in prose, gone
    for hedge in ("about 1.0", "a few weeks are", "flatters them a little",
                  "roughly right —", "a little "):
        assert hedge not in prose, hedge


def test_each_paragraph_is_its_own_element():
    """The breaks carry the structure of this screen, so they are laid out
    rather than embedded as newlines in one blob of text."""
    src = sector_snack.render_app(_payload())

    assert "d.body.split('\\n\\n').map((para, i) =>" in src
    assert "marginTop: i ? 10 : 5" in src


def test_the_explainer_is_honest_about_what_it_cannot_tell_you():
    body = sector_snack.build_data(_payload())["meta"]["details"][-1]["body"].lower()

    assert "not returns anyone could have earned" in body
    assert "not a trading record" in body and "not advice" in body
    assert "dropped off the list" in body            # survivorship, stated outright


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


def test_every_target_is_a_full_width_row():
    """The chart is gone. No dot plot, no scrub surface, no axis maths — the
    app is screens of rows, and a row is the only thing anyone presses."""
    src = sector_snack.render_app(_payload())

    for gone in ("function X(", "packLanes", "onResponderGrant", "locationX",
                 "cellFill", "function mix(", "Strip", "MarketMap"):
        assert gone not in src, gone
    assert "function Row({ t, onPress, children, last })" in src
    assert "paddingVertical: 13," in src                      # comfortable target


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


# ---------- two tiers ----------

def test_both_tiers_render_and_stay_separate():
    data = sector_snack.build_data(_payload())

    assert [s["tier"] for s in data["sectors"]] == ["top", "top"]
    assert [s["tier"] for s in data["sectors2"]] == ["next"]
    top = {c["ticker"] for s in data["sectors"] for c in s["constituents"]}
    nxt = {c["ticker"] for s in data["sectors2"] for c in s["constituents"]}
    assert not (top & nxt)                       # a name belongs to exactly one list


def test_tier_labels_reach_the_app():
    meta = sector_snack.build_data(_payload())["meta"]

    assert [t["key"] for t in meta["tiers"]] == ["top", "next"]
    assert all(t["label"] and t["note"] for t in meta["tiers"])
    # The app keys its two visual languages off exactly these.
    assert set(t["key"] for t in meta["tiers"]) <= {"top", "next"}


def test_a_sector_missing_from_tier_two_is_simply_absent():
    """Communication Services has too few clean names for a second basket."""
    data = sector_snack.build_data(_payload())

    assert len(data["sectors"]) == 2
    assert len(data["sectors2"]) == 1
    assert "Utilities" not in [s["name"] for s in data["sectors2"]]


def test_a_single_tier_payload_still_builds():
    """The shape that predates the split must not need a second list."""
    payload = _payload()
    payload.pop("tiers")
    data = sector_snack.build_data(payload)

    assert data["sectors2"] == []
    assert [t["key"] for t in data["meta"]["tiers"]] == ["top"]


def test_the_app_hides_the_tab_bar_when_there_is_one_list():
    src = sector_snack.render_app(_payload())

    assert "tiers.length > 1 &&" in src
    assert ".filter((tier) => tier.sectors.length)" in src


def test_both_tiers_share_one_design_system():
    """No per-tier skins, no glow — one calm idiom everywhere."""
    src = sector_snack.render_app(_payload())

    assert "SKINS" not in src
    assert "shadowColor" not in src
    assert "shadowRadius" not in src


# ---------- watchlist, views, gestures ----------

def test_global_z_travels_beside_the_sector_z():
    data = sector_snack.build_data(_payload())
    everyone = [c for key in ("sectors", "sectors2") for s in data[key] for c in s["constituents"]]
    gs = [c["g"] for c in everyone if c["g"] is not None]

    assert all("g" in c for c in everyone)
    assert abs(sum(gs) / len(gs)) < 1e-6                      # centred on the whole page
    assert all(c["g"] is None for c in everyone if c["score"] is None)


def test_global_z_is_a_different_yardstick_from_sector_z():
    """A middling name in a strong sector should read stronger globally."""
    data = sector_snack.build_data(_payload())
    everyone = [c for key in ("sectors", "sectors2") for s in data[key] for c in s["constituents"]]

    assert any(c["g"] != c["z"] for c in everyone if c["g"] is not None)


def test_navigation_is_a_stack_the_back_button_pops():
    """Three screens deep with a real back stack — including Android's
    hardware button, which must pop rather than leave the app."""
    src = sector_snack.render_app(_payload())

    assert "const [stack, setStack] = useState([{ k: 'sectors' }]);" in src
    assert "BackHandler.addEventListener('hardwareBackPress'" in src
    assert "if (stack.length > 1) { pop(); return true; }" in src
    for screen in ("SectorsScreen", "SectorScreen", "CompanyScreen",
                   "WatchlistScreen", "HowScreen"):
        assert "function " + screen in src, screen
    assert "onLongPress" not in src                        # one gesture: press a row


def test_following_related_names_never_builds_a_trail():
    """Tapping through related companies must not stack screens: every company
    screen sits exactly three deep, so the way out is always two taps."""
    src = sector_snack.render_app(_payload())

    assert "return [{ k: 'sectors' }, parent, { k: 'company', ticker }];" in src
    # no route into a company screen bypasses that rule
    assert "push({ k: 'company'" not in src
    assert "onOpenCompany={(c) => openCompany(c.ticker)}" in src


def test_a_company_opened_from_the_watchlist_goes_back_to_it():
    """Entry context is preserved — the parent is the list you were working
    through, not the company's sector."""
    src = sector_snack.render_app(_payload())

    assert "const fromWatchlist = s.some((x) => x.k === 'watchlist');" in src
    assert "? { k: 'watchlist' }" in src


def test_the_back_button_names_where_it_goes():
    src = sector_snack.render_app(_payload())

    assert "{'‹ ' + back}" in src
    assert "under.k === 'sector' ? under.name" in src
    assert "'‹ Back'" not in src


def test_a_push_lands_at_the_top_of_the_new_screen():
    """Keying the scroller by screen remounts it, so a pushed screen never
    opens halfway down the previous one's scroll position."""
    src = sector_snack.render_app(_payload())

    assert "key={here.k + ':' + (here.ticker || here.name || '')}" in src


def test_fresh_numbers_drop_you_back_to_the_top_screen():
    """The open screens describe the old numbers; a refresh invalidates them."""
    src = sector_snack.render_app(_payload(), feed_url="https://example.test/f.json")

    assert "setStack([{ k: 'sectors' }]);" in src


def test_no_tinted_fills_anywhere():
    """The pea-soup rule survives the rewrite: the palette appears only at
    full strength on type and hairlines, never blended into a surface."""
    src = sector_snack.render_app(_payload())

    assert "cellFill" not in src
    assert "function mix(" not in src
    assert "backgroundColor: toneOf(value, t)" in src         # the 3pt bar, at full strength


def test_watchlist_survives_restarts_and_storage_failures():
    src = sector_snack.render_app(_payload())

    assert "AsyncStorage.getItem(WL_KEY)" in src
    assert "AsyncStorage.setItem(WL_KEY, JSON.stringify(wl))" in src
    # Storage failures degrade to in-memory, never to a crash.
    assert ".catch(() => {}); } catch (e) {}" in src


def test_standing_is_told_in_words_not_a_mode_switch():
    """The old by-sector/whole-market toggle is gone: a company screen simply
    states both ranks in a sentence, so there is no mode to be lost in."""
    src = sector_snack.render_app(_payload())

    assert "ViewToggle" not in src
    assert "' of ' + c.of + ' in ' + home.sector" in src
    assert "' of ' + c.universe + ' across every sector'" in src

def test_the_score_is_translated_into_plain_words():
    """A reader should never have to know that 0.75 is 'good' — the row says
    so. Coarse buckets on purpose: five phrases, not a continuous scale."""
    assert sector_snack.verdict_for(2.10) == "climbing hard"
    assert sector_snack.verdict_for(1.00) == "climbing steadily"
    assert sector_snack.verdict_for(0.40) == "drifting up"
    assert sector_snack.verdict_for(0.00) == "going nowhere"
    assert sector_snack.verdict_for(-0.50) == "drifting down"
    assert sector_snack.verdict_for(-1.20) == "falling"

    data = sector_snack.build_data(_payload())
    assert all(s["verdict"] for s in data["sectors"])


def test_a_sector_row_says_what_happened_without_the_number():
    """Rank, name, verdict, breadth — the row reads even with the score and
    the bar ignored entirely."""
    src = sector_snack.render_app(_payload())

    assert "{s.verdict} · {s.rising} of {s.n} companies up" in src


def test_unscored_names_are_listed_and_explained_not_hidden():
    src = sector_snack.render_app(_payload())

    assert "too new to score" in src
    assert "it has not been listed long enough" in src
