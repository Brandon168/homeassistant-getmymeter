"""Public repository contract tests."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_public_json_and_dashboard_contract() -> None:
    """Public metadata, translations, and synthetic dashboard stay parseable."""
    manifest = json.loads(
        (ROOT / "custom_components/getmymeter/manifest.json").read_text()
    )
    strings = json.loads(
        (ROOT / "custom_components/getmymeter/strings.json").read_text()
    )
    translations = json.loads(
        (ROOT / "custom_components/getmymeter/translations/en.json").read_text()
    )
    hacs = json.loads((ROOT / "hacs.json").read_text())
    dashboard = yaml.safe_load((ROOT / "examples/water-dashboard.yaml").read_text())

    assert manifest["version"] == "0.2.0"
    assert manifest["codeowners"] == ["@Brandon168"]
    assert strings == translations
    assert hacs["name"] == "GetMyMeter"
    card_types = {card["type"] for view in dashboard["views"] for card in view["cards"]}
    assert {
        "energy-date-selection",
        "energy-water-graph",
        "energy-sources-table",
        "statistics-graph",
    } <= card_types
    dashboard_text = (ROOT / "examples/water-dashboard.yaml").read_text()
    assert "type: water" in dashboard_text
    assert "stat_energy_from:" in dashboard_text
    assert "meter_replace_with_identity_hash" in dashboard_text
