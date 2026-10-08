"""Registry guard behaviour (FEAT-04 d)."""
import pytest

from heatwave.forecast.registry import FORBIDDEN_NAME_PATTERN, FeatureSpec, Registry


def spec(name="f", **kw):
    base = dict(name=name, family="recent_heat", kind="panel", max_lookahead=0, window_weeks=1,
                description="d", fn=lambda ctx: None)
    base.update(kw)
    return FeatureSpec(**base)


@pytest.mark.parametrize("bad", [1, -1, 0.0, True, False, None])
def test_lookahead_must_be_int_zero(bad):
    with pytest.raises(ValueError):
        Registry().register(spec(max_lookahead=bad))


def test_duplicate_unknown_and_missing_fn():
    r = Registry()
    r.register(spec("a"))
    with pytest.raises(ValueError):
        r.register(spec("a"))
    with pytest.raises(ValueError):
        r.register(spec("b", family="nope"))
    with pytest.raises(ValueError):
        r.register(spec("c", kind="nope"))
    with pytest.raises(ValueError):
        r.register(spec("d", fn=None))


@pytest.mark.parametrize(
    "bad",
    ["ward_id", "wardcode", "ward", "location", "year", "iso_year", "year_index", "target_year",
     "heatwave_week", "label", "target", "heatwave_event_count", "ward_lat"],
)
def test_forbidden_names(bad):
    with pytest.raises(ValueError):
        Registry().register(spec(bad))


def test_lga_average_ward_accepted():
    r = Registry()
    r.register(spec("lga_average_ward", kind="static", family="static", window_weeks=0, fn=None))
    assert "lga_average_ward" in r
    assert not FORBIDDEN_NAME_PATTERN.search("lga_average_ward")


def test_copy_is_independent():
    r = Registry()
    r.register(spec("a"))
    c = r.copy()
    c.register(spec("b"))
    assert len(r) == 1 and len(c) == 2
    assert r.names() == ("a",) and c.names() == ("a", "b")


def test_default_registry_passes_guard():
    from heatwave.forecast.features import REGISTRY

    fresh = Registry()
    for s in REGISTRY:
        assert s.max_lookahead == 0
        assert not FORBIDDEN_NAME_PATTERN.search(s.name)
        fresh.register(s)
    assert len(fresh) == len(REGISTRY) == 58
