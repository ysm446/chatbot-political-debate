"""
政治討論シミュレーター用データローダー。

- debate_topics.yaml: 討論テーマ
- group.yaml: 政党の特色
- characters.yaml: 議員キャラクター
"""
from pathlib import Path
from typing import Any, Dict

import yaml

_ROOT = Path(__file__).parent.parent
_TOPICS_FILE = _ROOT / "debate_topics.yaml"
_PARTIES_FILE = _ROOT / "group.yaml"
_POLITICIANS_FILE = _ROOT / "characters.yaml"


def _load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


DEBATE_TOPICS: Dict[str, Any] = _load_yaml(_TOPICS_FILE)
PARTIES: Dict[str, Any] = _load_yaml(_PARTIES_FILE)
POLITICIANS: Dict[str, Any] = _load_yaml(_POLITICIANS_FILE)
