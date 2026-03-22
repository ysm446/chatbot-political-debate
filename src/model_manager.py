"""
モデル管理モジュール
models ディレクトリ配下のローカル GGUF モデル一覧・切り替え用情報を管理する。
"""
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

MODELS_DIR = Path("models")

# 旧バージョンの保存済み active_model_key との互換用
LEGACY_MODEL_ALIASES: Dict[str, str] = {
    "Qwen3-14B-Q4_K_M": "Qwen3-14B-Q4_K_M.gguf",
    "Qwen3-30B-A3B-Q4_K_M": "Qwen3-30B-A3B-Q4_K_M.gguf",
    "Qwen3-30B-A3B-abliterated-Q4_K_M": "huihui-ai.Qwen3-30B-A3B-abliterated.Q4_K_M.gguf",
    "Huihui-Qwen3.5-35B-A3B-abliterated-Q4_K_M": (
        "Huihui-Qwen3.5-35B-A3B-abliterated-GGUF/"
        "Huihui-Qwen3.5-35B-A3B-abliterated.Q4_K_M.gguf"
    ),
}


def _is_hidden_or_cache(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts) or ".cache" in path.parts


def _is_supported_model_file(path: Path) -> bool:
    if path.suffix.lower() != ".gguf":
        return False
    if "mmproj" in path.name.lower():
        return False
    return True


def _resolve_candidate_path(model_key: str) -> Path:
    normalized_key = (model_key or "").replace("\\", "/").strip().lstrip("./")
    legacy_target = LEGACY_MODEL_ALIASES.get(normalized_key, normalized_key)
    return MODELS_DIR / Path(legacy_target)


def list_local_models() -> List[Dict[str, Any]]:
    """models 配下の利用可能な GGUF モデルを再帰的に列挙する。"""
    if not MODELS_DIR.exists():
        return []

    rows: List[Dict[str, Any]] = []
    for path in sorted(MODELS_DIR.rglob("*.gguf")):
        rel_path = path.relative_to(MODELS_DIR)
        if _is_hidden_or_cache(rel_path) or not _is_supported_model_file(path):
            continue

        size_gb = round(path.stat().st_size / (1024 ** 3), 2)
        parent_label = rel_path.parent.as_posix() if rel_path.parent != Path(".") else "models"
        rows.append(
            {
                "key": rel_path.as_posix(),
                "name": path.stem,
                "path": rel_path.as_posix(),
                "size_gb": size_gb,
                "vram_gb": None,
                "description": f"ローカルモデル ({parent_label})",
            }
        )

    return rows


def is_downloaded(model_key: str) -> bool:
    """後方互換用。指定モデルがローカルに存在するかを返す。"""
    return get_model_path(model_key) != ""


def get_downloaded_models() -> list:
    """後方互換用。利用可能モデルのキー一覧を返す。"""
    return [row["key"] for row in list_local_models()]


def get_model_path(model_key: str) -> str:
    """モデルキーから GGUF ファイルの実パスを返す。"""
    if not model_key:
        return ""

    candidate = _resolve_candidate_path(model_key)
    if candidate.exists() and candidate.is_file() and _is_supported_model_file(candidate):
        return str(candidate)

    normalized_key = model_key.replace("\\", "/")
    for row in list_local_models():
        if row["key"] == normalized_key or row["name"] == normalized_key:
            return str(MODELS_DIR / row["path"])

    return ""


def find_model_key(model_path: str) -> str:
    """モデルパスから UI 用のモデルキーを返す。"""
    try:
        rel_path = Path(model_path).resolve().relative_to(MODELS_DIR.resolve())
        rel_key = rel_path.as_posix()
    except Exception:
        rel_key = model_path.replace("\\", "/").strip().lstrip("./")

    for row in list_local_models():
        if row["key"] == rel_key:
            return row["key"]

    for legacy_key, legacy_path in LEGACY_MODEL_ALIASES.items():
        if legacy_path.replace("\\", "/") == rel_key:
            return rel_key

    return ""


def build_status_markdown(active_model_key: str = "") -> str:
    """モデル一覧の Markdown テーブルを生成する。"""
    lines = [
        "| モデル | サイズ | 状態 | 説明 |",
        "|---|---|---|---|",
    ]

    for row in list_local_models():
        active = "使用中" if row["key"] == active_model_key else "利用可"
        lines.append(
            f"| **{row['name']}** | {row['size_gb']}GB | {active} | {row['path']} |"
        )

    return "\n".join(lines)
