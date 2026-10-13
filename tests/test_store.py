import json
import os
import random
from collections import Counter
from datetime import datetime, timedelta

import pytest

from ht2wv import config, store
from ht2wv.sources.extra import parse_history


def stamp(day, hour=0):
    return (datetime(2026, 1, 5) + timedelta(days=day, hours=hour)).timestamp()


def event(day, hour=0, src="target", **fields):
    return {"t": stamp(day, hour), "src": src, "k": "mark", **fields}


def seed(events):
    for ev in events:
        path = config.day_dir(store.day_of(ev["t"])) / "events.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def rows(src):
    return [e for day in store.days() for e in store.read_events(day) if e["src"] == src]


def multiset(events):
    return Counter(json.dumps(e, sort_keys=True, ensure_ascii=False) for e in events)


def file_bytes():
    return {day: (config.day_dir(day) / "events.jsonl").read_bytes() for day in store.days()}


def test_shorter_recollect_preserves_boundary_morning_and_earlier_days(home):
    original = [event(day, hour) for day in range(3) for hour in (8, 16)]
    store.replace_source("target", original, stamp(0), stamp(3))
    # A rolling one-day collection begins at noon, after the boundary day's morning.
    store.replace_source("target", [original[-1]], stamp(2, 12), stamp(3, 12))
    assert multiset(rows("target")) == multiset(original)


def test_other_sources_are_untouched(home):
    others = [event(day, 9, src="other", text='mentions "src": "target"') for day in range(3)]
    seed(others + [event(day, 10) for day in range(3)])
    untouched_day = file_bytes()[store.day_of(stamp(0))]
    store.replace_source("target", [event(1, 14)], stamp(1), stamp(3))
    assert multiset(rows("other")) == multiset(others)
    assert file_bytes()[store.day_of(stamp(0))] == untouched_day


def test_snapshot_removes_absent_rows_on_days_without_new_events(home):
    before, after = event(0, 8), event(3, 18)
    seed([before, event(0, 12), event(1, 8), event(2, 8), event(3, 12), after])
    replacement = event(2, 15)
    store.replace_source("target", [replacement], stamp(0, 12), stamp(3, 12))
    assert multiset(rows("target")) == multiset([before, replacement, after])


def test_empty_snapshot_removes_only_inclusive_window(home):
    original = [event(0, hour) for hour in (8, 9, 12, 15, 16)] + [event(1, 12)]
    seed(original)
    store.replace_source("target", [], stamp(0, 9), stamp(0, 15))
    assert multiset(rows("target")) == multiset([original[0], original[-2], original[-1]])


def test_source_matching_parses_json_exactly(home):
    path = config.day_dir(store.day_of(stamp(0))) / "events.jsonl"
    # JSON escapes and compact separators defeated the old substring match.
    target = event(0, 10)
    other = event(0, 11, src="target-extra")
    raw_other = json.dumps(other, separators=(",", ":")) + "\n"
    path.write_text(json.dumps(target).replace('"target"', '"tar\\u0067et"') + "\n" + raw_other,
                    encoding="utf-8")
    store.replace_source("target", [], stamp(0), stamp(1))
    assert rows("target") == []
    assert rows("target-extra") == [other]
    assert path.read_text(encoding="utf-8") == raw_other


def test_undated_rows_are_wholly_replaced_when_pinned_time_changes(home):
    dated = event(0, 8, src="shell@local")
    other = event(0, 9, src="shell@other", undated=True)
    seed([dated, other])
    first = parse_history("a\nb\n", stamp(0, 12), "local", stamp(1), 100, [])
    second = parse_history("a\nb\nc\n", stamp(2, 12), "local", stamp(2), 100, [])
    store.replace_source("shell@local", first, stamp(1), stamp(1, 12))
    store.replace_source("shell@local", second, stamp(2), stamp(3))
    assert multiset(rows("shell@local")) == multiset([dated] + second)
    assert rows("shell@other") == [other]
    snapshot = file_bytes()
    store.replace_source("shell@local", second, stamp(2), stamp(3))
    assert file_bytes() == snapshot
    store.replace_source("shell@local", [], stamp(4), stamp(5))
    assert rows("shell@local") == [dated]


def test_random_collection_windows_preserve_union_and_are_byte_idempotent(home, monkeypatch):
    for seed_number in range(4):
        monkeypatch.setenv("HT2WV_HOME", str(home / f"seed-{seed_number}"))
        rng = random.Random(seed_number)
        truth = [event(day, hour, text=str(rng.randrange(4)))
                 for day in range(3) for hour in (0, 8, 12, 20)]
        truth += [truth[7].copy()]  # Preserve legitimate duplicate rows as a multiset.
        others = [event(day, 7, src="other") for day in range(3)]
        others += [event(-2, 7, src="other", undated=True)]
        seed(others)
        collected = set()
        # Guarantee partial boundary days, inclusive midnight, and a final shorter window.
        windows = [(12, 24), (24, 36)]
        windows += [tuple(sorted(rng.randrange(3 * 24 + 1) for _ in range(2))) for _ in range(3)]
        windows += [(48, 60)]
        for call_number, (left, right) in enumerate(windows):
            since, until = stamp(0, left), stamp(0, right)
            indices = [i for i, e in enumerate(truth) if since <= e["t"] <= until]
            # Synthetic history moves between days outside every dated collection window.
            pinned_day = -2 + call_number % 2
            undated = [event(pinned_day, 12, undated=True, text="history",
                             t=stamp(pinned_day, 12) + call_number / 1000)]
            batch = [truth[i] for i in indices] + undated
            rng.shuffle(batch)
            store.replace_source("target", iter(batch), since, until)
            collected.update(indices)
        assert multiset(rows("target")) == multiset([truth[i] for i in collected] + undated), seed_number
        assert multiset(rows("other")) == multiset(others), seed_number
        snapshot = file_bytes()
        store.replace_source("target", iter(batch), since, until)
        assert file_bytes() == snapshot, seed_number


def test_default_until_includes_now_and_future_new_events(home, monkeypatch):
    monkeypatch.setattr(store.time, "time", lambda: stamp(1, 12))
    seed([event(1, 8), event(3, 8)])
    store.replace_source("target", [], stamp(0))
    assert rows("target") == [event(3, 8)]
    future = event(2, 12)
    store.replace_source("target", [future], stamp(0))
    snapshot = file_bytes()
    store.replace_source("target", [future], stamp(0))
    assert multiset(rows("target")) == multiset([future, event(3, 8)])
    assert file_bytes() == snapshot


def test_output_is_deterministic_for_ties_and_input_order(home):
    batch = [event(0, 12, text=text) for text in ("z", "a", "a")]
    store.replace_source("target", batch, stamp(0), stamp(1))
    snapshot = file_bytes()
    store.replace_source("target", [dict(reversed(list(e.items()))) for e in reversed(batch)], stamp(0), stamp(1))
    assert file_bytes() == snapshot
    assert multiset(rows("target")) == multiset(batch)


def test_day_write_is_atomic_and_failed_replace_preserves_original(home, monkeypatch):
    seed([event(0, 8)])
    path = config.day_dir(store.day_of(stamp(0))) / "events.jsonl"
    original = path.read_bytes()
    called = []

    def fail_replace(temp, destination):
        temp, destination = type(path)(temp), type(path)(destination)
        assert destination == path and temp.parent == path.parent and temp != path
        assert path.read_bytes() == original
        assert json.loads(temp.read_text(encoding="utf-8")) == event(0, 12)
        called.append(temp)
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        store.replace_source("target", [event(0, 12)], stamp(0), stamp(1))
    assert called and path.read_bytes() == original
    assert list(path.parent.iterdir()) == [path]


def test_since_is_required():
    with pytest.raises(TypeError):
        store.replace_source("target", [])
