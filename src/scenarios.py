"""
尋問ゲーム シナリオ定義ローダー

シナリオデータは scenarios.yaml で管理する。
"""
from pathlib import Path
from typing import Dict, Any

import yaml

_SCENARIOS_FILE = Path(__file__).parent.parent / "scenarios.yaml"


def _load() -> Dict[str, Any]:
    with open(_SCENARIOS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


SCENARIOS: Dict[str, Any] = _load()
