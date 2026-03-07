"""
Stable Diffusion (WebUI Forge 2) 連携ハンドラー

Forge 2 は /sdapi/v1/txt2img REST API を廃止し Gradio API のみ提供。
gradio_client を使って /txt2img エンドポイントを呼び出す。

キャラクター画像の生成とキャッシュ管理を担当する。
"""
import io
import logging
import os
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path("./generated_images")

_FORGE_HOST = "http://127.0.0.1"
_FORGE_PORT_START = 7860
_FORGE_PORT_END = 7880
_FORGE_PROBE_TIMEOUT = 0.5


def _find_forge_url(preferred_url: str) -> Optional[str]:
    """preferred_url を試し、失敗したらポートスキャンで探す。"""
    # まず設定の URL を試す
    candidates = [preferred_url]
    # ポートスキャン候補を追加
    for port in range(_FORGE_PORT_START, _FORGE_PORT_END):
        url = f"{_FORGE_HOST}:{port}"
        if url != preferred_url:
            candidates.append(url)

    for url in candidates:
        try:
            from gradio_client import Client
            client = Client(url, verbose=False)
            # /txt2img エンドポイントが存在するか確認
            try:
                api_info = client.view_api(return_format="dict")
                if isinstance(api_info, dict):
                    named = api_info.get("named_endpoints", {})
                    if isinstance(named, dict) and "/txt2img" in named:
                        logger.info("WebUI Forge に接続しました: %s", url)
                        return url
            except Exception:
                pass
        except Exception:
            continue
    return None


class SDHandler:
    def __init__(self, api_url: str, width: int = 512, height: int = 768,
                 steps: int = 20, cfg_scale: float = 7.0, sampler_name: str = "DPM++ 2M",
                 prompt_prefix: str = "", prompt_suffix: str = "",
                 prompt_bg: str = "", prompt_lighting: str = "", prompt_camera: str = "",
                 negative_prefix: str = "", negative_suffix: str = ""):
        self.api_url = api_url.rstrip("/")
        self.width = width
        self.height = height
        self.steps = steps
        self.cfg_scale = cfg_scale
        self.sampler_name = sampler_name
        self.prompt_prefix = prompt_prefix
        self.prompt_suffix = prompt_suffix
        self.prompt_bg = prompt_bg
        self.prompt_lighting = prompt_lighting
        self.prompt_camera = prompt_camera
        self.negative_prefix = negative_prefix
        self.negative_suffix = negative_suffix
        self._client = None
        self._forge_url = None
        CACHE_DIR.mkdir(exist_ok=True)

    def _build_prompt(self, sd_prompt: str, sd_negative: str) -> tuple[str, str]:
        """各プロンプトパーツを結合する。
        順序: prefix, キャラ固有, bg, lighting, camera, suffix
        """
        parts = [p for p in [
            self.prompt_prefix,
            sd_prompt,
            self.prompt_bg,
            self.prompt_lighting,
            self.prompt_camera,
            self.prompt_suffix,
        ] if p.strip()]
        neg_parts = [p for p in [self.negative_prefix, sd_negative, self.negative_suffix] if p.strip()]
        return ", ".join(parts), ", ".join(neg_parts)

    def _cache_path(self, cache_key: str) -> Path:
        safe_key = cache_key.replace("/", "_").replace("\\", "_")
        return CACHE_DIR / f"{safe_key}.png"

    def _get_client(self):
        """Gradio クライアントを取得（遅延初期化・キャッシュ）。"""
        if self._client is not None:
            return self._client
        try:
            from gradio_client import Client
        except ImportError:
            logger.error("gradio_client がインストールされていません: pip install gradio-client")
            return None

        url = _find_forge_url(self.api_url)
        if url is None:
            logger.warning("WebUI Forge が見つかりませんでした（ポート %d〜%d）",
                           _FORGE_PORT_START, _FORGE_PORT_END - 1)
            return None
        self._forge_url = url
        self._client = Client(url, verbose=False)
        return self._client

    def is_available(self) -> bool:
        """WebUI Forge が起動しているか確認する。"""
        return self._get_client() is not None

    def generate(self, sd_prompt: str, sd_negative: str = "") -> Optional[bytes]:
        """Forge 2 Gradio API で画像を生成してバイト列を返す。失敗時は None。"""
        client = self._get_client()
        if client is None:
            return None

        final_prompt, final_negative = self._build_prompt(sd_prompt, sd_negative)
        logger.info("SD 画像生成開始: steps=%d, size=%dx%d, sampler=%s",
                    self.steps, self.width, self.height, self.sampler_name)
        logger.debug("positive: %s", final_prompt)
        logger.debug("negative: %s", final_negative)

        # 152パラメータ構成（discover_forge_api.py で確認済み）
        # fmt: off
        args = [
            "",                  # [00] parameter_47
            final_prompt,        # [01] Prompt
            final_negative,      # [02] Negative prompt
            [],                  # [03] Styles
            1,                   # [04] Batch count
            1,                   # [05] Batch size
            self.cfg_scale,      # [06] CFG Scale
            3.5,                 # [07] Distilled CFG Scale
            int(self.height),    # [08] Height
            int(self.width),     # [09] Width
            False,               # [10] Hires. fix
            0.7,                 # [11] Denoising strength
            2.0,                 # [12] Upscale by
            "Latent",            # [13] Upscaler
            0.0,                 # [14] Hires steps
            0.0,                 # [15] Resize width to
            0.0,                 # [16] Resize height to
            "Use same checkpoint",  # [17] Hires Checkpoint
            [],                  # [18] Hires VAE / Text Encoder
            "Use same sampler",  # [19] Hires sampling method
            "Use same scheduler",# [20] Hires schedule type
            "",                  # [21] Hires prompt
            "",                  # [22] Hires negative prompt
            0.0,                 # [23] Hires CFG Scale
            0.0,                 # [24] Hires Distilled CFG Scale
            [],                  # [25] Override settings
            "None",              # [26] Script
            int(self.steps),     # [27] Sampling steps
            self.sampler_name,   # [28] Sampling method
            "Automatic",         # [29] Schedule type
            False,               # [30] Refiner
            "",                  # [31] Checkpoint
            0.8,                 # [32] Switch at
            float(-1),           # [33] Seed
            False,               # [34] Extra seed
            -1.0,                # [35] Variation seed
            0.0,                 # [36] Variation strength
            0.0,                 # [37] Resize seed from width
            0.0,                 # [38] Resize seed from height
            # Dynamic Prompts [39-56]
            False, False, 1.0, False, False, False,
            1.1, 1.5, 100.0, 0.7, False, False, False,
            False, False, 0.0,
            "Gustavosta/MagicPrompt-Stable-Diffusion", "",
            # CFG Combinator [57-68]
            False, 7.0, 1.0, "Constant", 0.0, "Constant",
            0.0, 4.0, "enable", "MEAN", "AD", 1.0,
            # FreeU [69-75]
            False, 1.3, 1.4, 0.9, 0.2, 0.0, 1.0,
            # SAG [76-79]
            False, 0.75, 2.0, 0.0,
            # PAG [80-84]
            False, 3.0, 0.0, 0.0, 1.0,
            # Kohya HRFix [85-92]
            False, 3.0, 2.0, 0.0, 0.35, True, "bicubic", "bicubic",
            # Sharpness/Tonemap/CFG Combat [93-113]
            False, 2.0, "anisotropic", 1.0, "reinhard", 100.0,
            0.0, "subtract", 0.0, 0.0, "gaussian", "add",
            0.0, 100.0, 127.0, 0.0, "hard_clamp", 5.0,
            0.0, "None", "None",
            # MultiDiffusion [114-121]
            False, "MultiDiffusion", 96.0, 96.0, 48.0, 4.0, False, 1.0,
            # Memory [122-123]
            False, False,
            # Script args [124-151]
            False, False, "positive", "comma", 0.0,
            False, False, "start", "",
            False,
            "Nothing", "", [], "Nothing", "", [], "Nothing", "", [],
            True, False, False, False, False, False, False, 0.0, False,
        ]
        # fmt: on

        try:
            result = client.predict(*args, api_name="/txt2img")
        except Exception as e:
            logger.warning("Gradio API 呼び出し失敗、再接続して再試行: %s", e)
            self._client = None
            client = self._get_client()
            if client is None:
                return None
            try:
                result = client.predict(*args, api_name="/txt2img")
            except Exception as e2:
                logger.error("SD 画像生成エラー: %s", e2)
                return None

        try:
            return self._result_to_bytes(result)
        except Exception as e:
            logger.error("画像データ変換エラー: %s", e)
            return None

    def _result_to_bytes(self, result) -> bytes:
        """gradio_client の戻り値から PNG バイト列を取得する。"""
        from PIL import Image

        if isinstance(result, (list, tuple)):
            gallery = result[0] if result else None
        else:
            gallery = result

        if gallery is None:
            raise RuntimeError("Forge から画像が返されませんでした。")

        if isinstance(gallery, (list, tuple)) and len(gallery) > 0:
            entry = gallery[0]
        else:
            entry = gallery

        img = self._load_image_from_entry(entry)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _load_image_from_entry(self, entry):
        """単一の画像エントリを PIL.Image に変換する。"""
        from PIL import Image

        if hasattr(entry, "path") and entry.path:
            return Image.open(entry.path).copy()

        if isinstance(entry, dict):
            for key in ("image", "name", "path", "url"):
                val = entry.get(key)
                if val is not None:
                    return self._load_image_from_entry(val)

        if isinstance(entry, str) and os.path.isfile(entry):
            return Image.open(entry).copy()

        raise RuntimeError(
            f"画像データの形式を認識できませんでした: type={type(entry)}, value={entry!r}"
        )

    def get_or_generate(self, cache_key: str, sd_prompt: str, sd_negative: str = "") -> Optional[Path]:
        """キャッシュ済みならそのパスを返す。なければ生成してキャッシュし、パスを返す。"""
        path = self._cache_path(cache_key)
        if path.exists():
            logger.debug("キャッシュヒット: %s", cache_key)
            return path

        logger.info("画像生成開始: %s", cache_key)
        image_bytes = self.generate(sd_prompt, sd_negative)
        if image_bytes is None:
            return None

        path.write_bytes(image_bytes)
        logger.info("画像保存: %s", path)
        return path

    def clear_cache(self, cache_key: Optional[str] = None) -> None:
        """キャッシュを削除する。cache_key が None の場合はすべて削除。"""
        if cache_key is not None:
            path = self._cache_path(cache_key)
            if path.exists():
                path.unlink()
        else:
            for f in CACHE_DIR.glob("*.png"):
                f.unlink()
