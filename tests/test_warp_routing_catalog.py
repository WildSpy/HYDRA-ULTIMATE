from hydra.plugins.warp.routing_catalog import build_routing_catalog, category_target
from hydra.plugins.warp.manager import _compact_destination_options, _remove_legacy_yaml_routes
from hydra.core.state import PluginState


def test_catalog_merges_sources_by_user_category():
    external = {
        "geoblock": {"name": "GEO-block", "desc": "built in"},
        "geoblock-extra": {"name": "GEO-block extra", "category": "geoblock"},
        "russia": {"name": "РФ-сервисы", "desc": "built in"},
    }

    categories = build_routing_catalog(external, {})
    by_key = {category.key: category for category in categories}

    assert by_key["geoblock"].label == "Обход блокировок"
    assert set(by_key["geoblock"].source_keys) == {
        "ext:geoblock", "ext:geoblock-extra",
    }
    assert by_key["ru_services"].source_keys == ("ext:russia",)


def test_category_target_reports_uniform_and_mixed_routes():
    category = build_routing_catalog({
        "geoblock": {"name": "GEO-block"},
        "geoblock-extra": {"name": "Extra", "category": "geoblock"},
    }, {})[0]
    assert category_target(category, {}) == "none"
    assert category_target(category, {
        "ext:geoblock": "warp_nl",
        "ext:geoblock-extra": "warp_nl",
    }) == "warp_nl"
    assert category_target(category, {
        "ext:geoblock": "warp_nl",
        "ext:geoblock-extra": "direct",
    }) == "mixed"


def test_default_hydra_domains_join_ai_category():
    categories = build_routing_catalog({}, {"default": {"domains": ["openai.com"]}})
    assert len(categories) == 1
    assert categories[0].key == "ai"
    assert categories[0].label == "AI-сервисы"


def test_destination_menu_prioritises_selected_locations_without_duplicates():
    class Plugin:
        @staticmethod
        def available_destinations():
            return [
                ("direct", "direct"),
                ("warp_ultimate", "selector"),
                ("warp_ultimate_auto", "auto"),
                ("warp_ultimate_nl", "Netherlands"),
                ("warp_ultimate_ru", "Russia"),
                ("warp", "WGCF"),
            ]

    bundle = {"endpoints": [
        {"tag": "warp_ultimate_nl", "name": "Netherlands"},
        {"tag": "warp_ultimate_ru", "name": "Russia"},
    ]}
    ps = PluginState(config={
        "ultimate_selected_tag": "warp_ultimate_nl",
        "ultimate_route_tags": ["warp_ultimate_nl", "warp_ultimate_ru"],
    })

    options = _compact_destination_options(Plugin(), ps, bundle)
    assert [tag for tag, _label in options] == [
        "direct", "warp_ultimate_auto", "warp_ultimate_nl", "warp_ultimate_ru", "warp",
    ]
    assert "Netherlands" in options[2][1]


def test_legacy_yaml_routes_are_removed_without_touching_hydra_lists():
    ps = PluginState(config={"list_targets": {
        "yaml:youtube": "warp_ultimate_nl",
        "ext:geoblock": "warp_ultimate_nl",
        "local:custom": "direct",
    }})
    assert _remove_legacy_yaml_routes(ps) is True
    assert ps.config["list_targets"] == {
        "ext:geoblock": "warp_ultimate_nl",
        "local:custom": "direct",
    }
    assert _remove_legacy_yaml_routes(ps) is False
