"""
Research-Bot API エントリーポイント
Gradioを廃止し、Electron UI向けに FastAPI + SSE を提供する。
"""
import argparse
import asyncio
import json
import logging
import re
import sys
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Windows端末での文字化け対策: stdout/stderr を UTF-8 に固定
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = Field(default_factory=list)
    show_thinking: bool = True
    enable_thinking_mode: bool = True
    temperature: float = 0.6
    max_tokens: int = 8192


class ModelSwitchRequest(BaseModel):
    model_key: str


class ModelDownloadRequest(BaseModel):
    model_key: str


class SettingsRequest(BaseModel):
    enable_thinking_mode: bool
    show_thinking: bool
    temperature: float
    max_tokens: int


def load_components(config: dict):
    """LLMHandlerを初期化"""
    from src.llm_handler import LLMHandler
    from src.utils import check_model_exists

    model_config = config.get("model", {})
    model_path = model_config.get("path", "./models/Qwen3-30B-A3B-Q4_K_M.gguf")

    if not check_model_exists(model_path):
        logger.warning("起動時モデルが見つからないため未ロードで開始します: %s", model_path)
        return None

    logger.info("LLMを初期化中: %s", model_path)
    llm = LLMHandler(model_path=model_path, config=model_config)

    return llm


def _resolve_startup_model(config: dict) -> tuple[dict, str, str]:
    from src import model_manager
    from src.utils import check_model_exists, load_settings

    resolved_config = dict(config)
    resolved_model_config = dict(config.get("model", {}))
    resolved_config["model"] = resolved_model_config

    saved_model_key = load_settings().get("active_model_key", "")
    if saved_model_key and model_manager.is_downloaded(saved_model_key):
        model_path = model_manager.get_model_path(saved_model_key)
        resolved_model_config["path"] = model_path
        return resolved_config, model_path, saved_model_key

    model_path = resolved_model_config.get("path", "./models/Qwen3-30B-A3B-Q4_K_M.gguf")
    return resolved_config, model_path, _detect_active_model(model_path) if check_model_exists(model_path) else ""


def _normalize_history(history: List[Any]) -> List[dict]:
    """履歴を role/content 形式へ正規化する。"""
    normalized: List[dict] = []
    for msg in history or []:
        if isinstance(msg, dict):
            role = msg.get("role")
            content = msg.get("content")
            if role in {"user", "assistant"} and content is not None:
                normalized.append({"role": role, "content": str(content)})
            continue

        if isinstance(msg, (list, tuple)) and len(msg) == 2:
            user_text, assistant_text = msg
            if user_text:
                normalized.append({"role": "user", "content": str(user_text)})
            if assistant_text:
                normalized.append({"role": "assistant", "content": str(assistant_text)})

    return normalized


def _format_context_usage_text(usage: dict) -> str:
    usage_percent = float(usage.get("usage_percent", 0.0))
    prompt_percent = float(usage.get("prompt_percent", 0.0))
    prompt_tokens = int(usage.get("prompt_tokens", 0))
    reserve_tokens = int(usage.get("reserve_tokens", 0))
    n_ctx = int(usage.get("n_ctx", 0))

    if usage_percent >= 95:
        level = "終了推奨"
    elif usage_percent >= 85:
        level = "注意"
    else:
        level = "余裕あり"

    return (
        f"{usage_percent:.1f}% ({level}) | "
        f"prompt {prompt_percent:.1f}% [{prompt_tokens}] + "
        f"reserve [{reserve_tokens}] / n_ctx {n_ctx}"
    )


def _detect_active_model(model_path: str) -> str:
    from src.model_manager import AVAILABLE_MODELS

    for key, info in AVAILABLE_MODELS.items():
        if info["local_path"].replace("\\", "/") in model_path.replace("\\", "/"):
            return key
    return ""


def process_query(
    query: str,
    history: List[dict],
    llm,
    config: dict,
    show_thinking: bool = True,
    enable_thinking_mode: bool = True,
) -> Generator[Dict[str, Any], None, None]:
    from src.utils import format_thinking_html

    sampling_config = config.get("sampling", {})

    normalized_history = _normalize_history(history)
    llm_history: List[Dict[str, str]] = []
    for msg in normalized_history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            llm_history.append({"role": "user", "content": content})
        elif role == "assistant":
            llm_history.append({"role": "assistant", "content": re.sub(r"<[^>]+>", "", content)})

    thinking_text = ""
    answer_text = ""
    status = "💭 思考中..."
    context_usage_text = "計算中..."

    try:
        usage = llm.estimate_context_usage(
            query=query,
            context=None,
            history=llm_history if llm_history else None,
            sampling_config=sampling_config,
            enable_thinking=enable_thinking_mode,
        )
        context_usage_text = _format_context_usage_text(usage)
    except Exception as exc:
        logger.warning("コンテキスト使用率の計算に失敗: %s", exc)
        context_usage_text = "計算失敗"

    yield {
        "event": "status",
        "status": status,
        "context_usage": context_usage_text,
        "answer": "💭 考えています...",
        "thinking": "",
    }

    try:
        for chunk in llm.generate_with_context(
            query=query,
            context=None,
            history=llm_history if llm_history else None,
            sampling_config=sampling_config,
            enable_thinking=enable_thinking_mode,
        ):
            chunk_type = chunk.get("type")
            chunk_text = chunk.get("text", "")

            if chunk_type == "thinking_chunk":
                thinking_text += chunk_text
                if show_thinking:
                    yield {
                        "event": "thinking",
                        "status": "💭 思考中...",
                        "context_usage": context_usage_text,
                        "thinking": format_thinking_html(thinking_text),
                        "answer": answer_text,
                    }

            elif chunk_type == "answer_chunk":
                answer_text += chunk_text
                yield {
                    "event": "answer",
                    "status": "✍️ 回答生成中...",
                    "context_usage": context_usage_text,
                    "thinking": format_thinking_html(thinking_text) if (show_thinking and thinking_text) else "",
                    "answer": answer_text,
                }

            elif chunk_type == "done":
                break

    except Exception as exc:
        logger.error("LLM生成エラー: %s", exc)
        answer_text = f"エラーが発生しました: {str(exc)}"
        status = "❌ エラー"

    final_thinking = format_thinking_html(thinking_text) if (show_thinking and thinking_text) else ""

    yield {
        "event": "final",
        "status": "✅ 完了" if status != "❌ エラー" else status,
        "context_usage": context_usage_text,
        "thinking": final_thinking,
        "answer": answer_text,
    }


def create_app(config: dict, llm_container: dict) -> FastAPI:
    from src import model_manager
    from src.llm_handler import LLMHandler
    from src.utils import load_settings, save_settings

    app = FastAPI(title="Research-Bot API", version="2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    initial_active_model_key = ""
    if llm_container.get("llm") is not None:
        initial_active_model_key = (
            llm_container.get("active_model_key")
            or load_settings().get("active_model_key")
            or _detect_active_model(config.get("model", {}).get("path", ""))
        )

    app_state = {"active_model_key": initial_active_model_key}

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"status": "ok"}

    @app.get("/api/bootstrap")
    async def bootstrap() -> Dict[str, Any]:
        settings = load_settings()
        downloaded = set(model_manager.get_downloaded_models())

        models = []
        for key, info in model_manager.AVAILABLE_MODELS.items():
            models.append(
                {
                    "key": key,
                    "downloaded": key in downloaded,
                    "size_gb": info.get("size_gb"),
                    "vram_gb": info.get("vram_gb"),
                    "description": info.get("description", ""),
                }
            )

        return {
            "settings": settings,
            "defaults": {
                "show_thinking": config.get("display", {}).get("show_thinking", True),
                "temperature": config.get("sampling", {}).get("temperature", 0.6),
                "max_tokens": config.get("sampling", {}).get("max_tokens", 8192),
            },
            "active_model_key": app_state.get("active_model_key", ""),
            "models": models,
        }

    @app.post("/api/settings")
    async def update_settings(payload: SettingsRequest) -> Dict[str, Any]:
        new_settings = payload.model_dump()
        new_settings["active_model_key"] = app_state.get("active_model_key", "")
        save_settings(new_settings)
        return {"ok": True}

    @app.post("/api/chat/stream")
    async def chat_stream(payload: ChatRequest):
        if llm_container.get("llm") is None:
            raise HTTPException(
                status_code=503,
                detail="モデルが読み込まれていません。モデル管理ページからダウンロードまたは切り替えを行ってください",
            )

        sampling_config = {
            **config.get("sampling", {}),
            "temperature": payload.temperature,
            "max_tokens": int(payload.max_tokens),
        }
        current_config = {**config, "sampling": sampling_config}

        def generate_events() -> Generator[str, None, None]:
            for event_payload in process_query(
                query=payload.message,
                history=[msg.model_dump() for msg in payload.history],
                llm=llm_container["llm"],
                config=current_config,
                show_thinking=payload.show_thinking,
                enable_thinking_mode=payload.enable_thinking_mode,
            ):
                yield f"data: {json.dumps(event_payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(generate_events(), media_type="text/event-stream")

    @app.get("/api/models")
    async def models() -> Dict[str, Any]:
        downloaded = set(model_manager.get_downloaded_models())
        rows = []
        for key, info in model_manager.AVAILABLE_MODELS.items():
            rows.append(
                {
                    "key": key,
                    "downloaded": key in downloaded,
                    "active": key == app_state.get("active_model_key", ""),
                    "size_gb": info.get("size_gb"),
                    "vram_gb": info.get("vram_gb"),
                    "description": info.get("description", ""),
                }
            )
        return {"models": rows}

    @app.post("/api/models/download/stream")
    async def download_stream(payload: ModelDownloadRequest):
        if not payload.model_key:
            raise HTTPException(status_code=400, detail="model_key is required")

        async def event_gen() -> AsyncGenerator[str, None]:
            for msg in model_manager.download_model(payload.model_key):
                event = {"event": "progress", "message": msg}
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0)

            refreshed = {
                "event": "done",
                "models": (await models())["models"],
            }
            yield f"data: {json.dumps(refreshed, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    @app.post("/api/models/unload")
    async def unload_model() -> Dict[str, Any]:
        if llm_container.get("llm") is None:
            return {"ok": False, "message": "モデルはすでにアンロード済みです"}

        import gc

        llm_container["llm"].shutdown()
        llm_container["llm"] = None
        app_state["active_model_key"] = ""
        gc.collect()

        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

        return {"ok": True, "message": "アンロード完了。VRAMを解放しました"}

    @app.post("/api/models/switch")
    async def switch_model(payload: ModelSwitchRequest) -> Dict[str, Any]:
        model_key = payload.model_key
        if not model_key:
            raise HTTPException(status_code=400, detail="model_key is required")

        if not model_manager.is_downloaded(model_key):
            raise HTTPException(status_code=400, detail=f"{model_key} はダウンロードされていません")

        if model_key == app_state.get("active_model_key", ""):
            return {"ok": True, "message": f"{model_key} はすでに使用中です"}

        try:
            import gc

            old_llm = llm_container.get("llm")
            if old_llm is not None:
                old_llm.shutdown()
                del old_llm
                llm_container["llm"] = None
                gc.collect()
                try:
                    import torch

                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass

            model_path = model_manager.get_model_path(model_key)
            model_config = config.get("model", {})
            new_llm = LLMHandler(model_path=model_path, config=model_config)
            llm_container["llm"] = new_llm
            app_state["active_model_key"] = model_key

            from src.utils import save_settings, load_settings

            current = load_settings()
            current["active_model_key"] = model_key
            save_settings(current)

            return {"ok": True, "message": f"{model_key} への切り替えが完了しました"}
        except Exception as exc:
            logger.exception("モデル切り替えエラー: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    # ===== ゲーム用エンドポイント =====
    from src import game_engine
    from src.sd_handler import SDHandler

    game_state: Dict[str, Any] = {"session": None}

    # SDHandler の初期化（SD無効または未インストール時は None）
    sd_cfg = config.get("stable_diffusion", {})
    sd_handler: Optional[SDHandler] = None
    if sd_cfg.get("enabled", False):
        sd_handler = SDHandler(
            api_url=sd_cfg.get("api_url", "http://127.0.0.1:7860"),
            width=sd_cfg.get("width", 512),
            height=sd_cfg.get("height", 768),
            steps=sd_cfg.get("steps", 20),
            cfg_scale=float(sd_cfg.get("cfg_scale", 7.0)),
            sampler_name=sd_cfg.get("sampler_name", "DPM++ 2M"),
            prompt_prefix=sd_cfg.get("prompt_prefix", ""),
            prompt_suffix=sd_cfg.get("prompt_suffix", ""),
            prompt_bg=sd_cfg.get("prompt_bg", ""),
            prompt_lighting=sd_cfg.get("prompt_lighting", ""),
            prompt_camera=sd_cfg.get("prompt_camera", ""),
            negative_prefix=sd_cfg.get("negative_prefix", ""),
            negative_suffix=sd_cfg.get("negative_suffix", ""),
        )

    # generated_images ディレクトリを静的ファイルとして配信
    import os
    os.makedirs("generated_images", exist_ok=True)
    app.mount("/generated_images", StaticFiles(directory="generated_images"), name="generated_images")

    class GameStartRequest(BaseModel):
        topic_id: str

    class InterrogateRequest(BaseModel):
        message: str

    @app.get("/api/game/scenarios")
    async def game_scenarios() -> Dict[str, Any]:
        return {"scenarios": game_engine.list_topics()}

    @app.post("/api/game/start")
    async def game_start(payload: GameStartRequest) -> Dict[str, Any]:
        try:
            session = game_engine.start_game(payload.topic_id)
            game_state["session"] = session
            return {"ok": True, "state": session.to_state_dict()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/game/state")
    async def game_get_state() -> Dict[str, Any]:
        session = game_state.get("session")
        if session is None:
            raise HTTPException(status_code=404, detail="討論が開始されていません")
        return session.to_state_dict()

    @app.post("/api/game/interrogate/stream")
    async def game_interrogate_stream(payload: InterrogateRequest):
        session = game_state.get("session")
        if session is None:
            raise HTTPException(status_code=404, detail="討論が開始されていません")
        if session.is_finished:
            raise HTTPException(status_code=400, detail="討論はすでに終了しています")
        if llm_container.get("llm") is None:
            raise HTTPException(status_code=503, detail="モデルが読み込まれていません")
        if not payload.message.strip():
            raise HTTPException(status_code=400, detail="質問を入力してください")

        sampling_config = config.get("sampling", {})

        def generate_events() -> Generator[str, None, None]:
            context_usage_text = "計算失敗"
            try:
                usage = game_engine.estimate_round_context_usage(
                    session=session,
                    user_message=payload.message,
                    llm=llm_container["llm"],
                    sampling_config=sampling_config,
                )
                context_usage_text = _format_context_usage_text(usage)
                if usage.get("speaker_name"):
                    context_usage_text += f" | 最重: {usage['speaker_name']}"
            except Exception as exc:
                logger.warning("討論コンテキスト使用率の計算に失敗: %s", exc)

            for event_payload in game_engine.generate_interrogation_stream(
                session=session,
                user_message=payload.message,
                llm=llm_container["llm"],
                sampling_config=sampling_config,
            ):
                if event_payload.get("event") == "round_start":
                    event_payload["context_usage"] = context_usage_text
                yield f"data: {json.dumps(event_payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(generate_events(), media_type="text/event-stream")

    @app.get("/api/game/character_image/{speaker_id}")
    async def game_character_image(speaker_id: str):
        session = game_state.get("session")
        if session is None:
            raise HTTPException(status_code=404, detail="討論が開始されていません")

        speaker = next((s for s in session.speakers if s["id"] == speaker_id), None)
        if speaker is None:
            raise HTTPException(status_code=404, detail="登壇者が見つかりません")

        if sd_handler is None:
            raise HTTPException(status_code=503, detail="Stable Diffusionが無効です")

        appearance = speaker.get("appearance", {})
        sd_prompt = appearance.get("sd_prompt", "1person, portrait, photorealistic")
        sd_negative = appearance.get("sd_negative", "nsfw, worst quality, low quality")
        cache_key = f"{session.topic_id}_{speaker_id}"

        image_path = await asyncio.get_event_loop().run_in_executor(
            None, sd_handler.get_or_generate, cache_key, sd_prompt, sd_negative
        )

        if image_path is None:
            raise HTTPException(status_code=503, detail="画像生成に失敗しました。AUTOMATIC1111が起動しているか確認してください")

        return FileResponse(str(image_path), media_type="image/png")
    return app


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    from src.utils import load_config, setup_logging

    try:
        config = load_config("config.yaml")
    except FileNotFoundError:
        logger.error("config.yaml が見つかりません。プロジェクトルートから実行してください。")
        sys.exit(1)

    setup_logging(level="INFO", log_file="logs/research_bot.log")

    resolved_config, startup_model_path, active_model_key = _resolve_startup_model(config)

    logger.info("Research-Bot API を起動しています...")
    llm = None
    try:
        llm = load_components(resolved_config)
    except Exception as exc:
        logger.exception("起動時モデルの初期化に失敗したため、未ロード状態で続行します: %s", exc)
        logger.warning("起動時モデル候補: %s", startup_model_path)

    llm_container = {"llm": llm, "active_model_key": active_model_key}
    app = create_app(resolved_config, llm_container)

    import uvicorn

    logger.info("APIサーバー起動: http://%s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


def main() -> None:
    parser = argparse.ArgumentParser(description="Research-Bot backend server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
