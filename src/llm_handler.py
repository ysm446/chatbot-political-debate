"""
llama-cpp server LLMハンドラー
llama-server.exe をサブプロセスで起動し、OpenAI 互換 API 経由で推論する。
"""
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, Generator, Optional, Tuple, Any

import requests

logger = logging.getLogger(__name__)

# <think>...</think> タグのパターン
THINKING_PATTERN = re.compile(r"<think>(.*?)</think>", re.DOTALL)
_MAX_TAG_LEN = len("</think>")

_DEFAULT_SERVER_PORT = 8766


class LLMHandler:
    """llama-server.exe をサブプロセスで管理し、HTTP 経由で推論を行うクラス"""

    def __init__(self, model_path: str, config: Optional[Dict] = None):
        """
        Args:
            model_path: GGUF モデルファイルのパス
            config: モデル設定
                - server_bin: llama-server.exe のパス
                - server_port: llama-server が使用するポート (デフォルト 8766)
                - server_host: llama-server のホスト (デフォルト 127.0.0.1)
                - n_gpu_layers: int (-1 = 全レイヤーを GPU にオフロード)
                - n_ctx: int (コンテキスト長、デフォルト 32768)
                - n_threads: int (CPU スレッド数、デフォルト 4)
        """
        self.model_path = model_path
        self.config = config or {}
        self._server_bin = self.config.get("server_bin", "llama-server")
        self._server_port = int(self.config.get("server_port", _DEFAULT_SERVER_PORT))
        self._server_host = self.config.get("server_host", "127.0.0.1")
        self._base_url = f"http://{self._server_host}:{self._server_port}"
        self._process: Optional[subprocess.Popen] = None
        self._log_fd = None
        self._start_server()

    # ------------------------------------------------------------------
    # サーバー起動・停止
    # ------------------------------------------------------------------

    def _start_server(self) -> None:
        """llama-server.exe を起動する"""
        n_gpu_layers = int(self.config.get("n_gpu_layers", -1))
        n_ctx = int(self.config.get("n_ctx", 32768))
        n_threads = int(self.config.get("n_threads", 4))

        model_path = str(Path(self.model_path).resolve())

        cmd = [
            self._server_bin,
            "--model", model_path,
            "--n-gpu-layers", str(n_gpu_layers),
            "--ctx-size", str(n_ctx),
            "--threads", str(n_threads),
            "--host", self._server_host,
            "--port", str(self._server_port),
            "--cont-batching",
        ]

        logger.info("llama-server を起動しています: %s", " ".join(cmd))

        os.makedirs("logs", exist_ok=True)
        self._log_fd = open("logs/llama-server.log", "w", encoding="utf-8", errors="replace")

        self._process = subprocess.Popen(
            cmd,
            stdout=self._log_fd,
            stderr=self._log_fd,
            cwd=str(Path(self._server_bin).parent) if Path(self._server_bin).is_absolute() else None,
        )

        self._wait_for_server()

    def _wait_for_server(self, timeout: int = 300, interval: float = 2.0) -> None:
        """llama-server が /health に応答するまでポーリングする"""
        deadline = time.time() + timeout
        logger.info("llama-server の起動を待機中... (最大 %d 秒)", timeout)

        while time.time() < deadline:
            # プロセスが死んでいないか確認
            if self._process and self._process.poll() is not None:
                raise RuntimeError(
                    f"llama-server が起動直後に終了しました (終了コード: {self._process.returncode})。"
                    " 詳細は logs/llama-server.log を確認してください。"
                )

            try:
                resp = requests.get(f"{self._base_url}/health", timeout=2)
                if resp.status_code in (200, 503):
                    # 200 = ok / 503 = loading_model（起動中） どちらも生きている証拠
                    status = resp.json().get("status", "")
                    if status == "ok":
                        logger.info("✅ llama-server が起動しました (port=%d)", self._server_port)
                        return
                    # loading_model の場合は待機継続
            except requests.exceptions.ConnectionError:
                pass
            except Exception as exc:
                logger.debug("llama-server 待機中の例外: %s", exc)

            time.sleep(interval)

        raise TimeoutError(
            f"llama-server の起動がタイムアウトしました ({timeout} 秒)。"
            " 詳細は logs/llama-server.log を確認してください。"
        )

    def shutdown(self) -> None:
        """llama-server を停止してリソースを解放する"""
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            self._process = None
            logger.info("llama-server をシャットダウンしました")

        if self._log_fd is not None:
            try:
                self._log_fd.close()
            except Exception:
                pass
            self._log_fd = None

    # ------------------------------------------------------------------
    # メッセージ構築
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        query: str,
        context: Optional[str] = None,
        history: Optional[list] = None,
        enable_thinking: bool = True,
    ) -> list:
        """Qwen3 用のメッセージリストを構築"""
        messages = []

        system_content = (
            "あなたは優秀なアシスタントです。"
            "ユーザーの質問に対して、正確で詳細な回答を提供してください。"
            "回答は日本語で行ってください。"
        )
        messages.append({"role": "system", "content": system_content})

        if history:
            messages.extend(history)

        user_content = query
        if context:
            user_content = (
                f"{context}\n\n---\n\n"
                f"以上の情報を参考に、次の質問に回答してください:\n{query}"
            )

        if not enable_thinking:
            user_content += "\n/no_think"

        messages.append({"role": "user", "content": user_content})
        return messages

    # ------------------------------------------------------------------
    # トークン数推定
    # ------------------------------------------------------------------

    def _count_prompt_tokens(self, messages: list) -> int:
        """メッセージのトークン数を推定する（llama-server の /tokenize エンドポイント使用）"""
        try:
            text = "".join(
                f"<|{msg.get('role', '')}|>\n{msg.get('content', '')}\n"
                for msg in messages
            )
            resp = requests.post(
                f"{self._base_url}/tokenize",
                json={"content": text, "add_special": False},
                timeout=10,
            )
            if resp.status_code == 200:
                tokens = resp.json().get("tokens", [])
                if tokens:
                    return len(tokens)
        except Exception:
            pass

        # フォールバック: 日本語混在テキストの概算（4 文字 ≒ 1 token）
        rough_chars = sum(len(str(msg.get("content", ""))) for msg in messages)
        return max(1, rough_chars // 4)

    def estimate_context_usage(
        self,
        query: str,
        context: Optional[str] = None,
        history: Optional[list] = None,
        sampling_config: Optional[Dict] = None,
        enable_thinking: bool = True,
    ) -> Dict[str, Any]:
        """現在の会話でのコンテキスト使用率（%）を返す"""
        cfg = sampling_config or {}
        n_ctx = int(self.config.get("n_ctx", 32768))
        reserve_tokens = int(cfg.get("max_tokens", 8192))
        messages = self._build_messages(query, context, history, enable_thinking)
        prompt_tokens = self._count_prompt_tokens(messages)
        total_tokens = prompt_tokens + reserve_tokens

        return {
            "n_ctx": n_ctx,
            "prompt_tokens": prompt_tokens,
            "reserve_tokens": reserve_tokens,
            "total_tokens": total_tokens,
            "prompt_percent": (prompt_tokens / n_ctx) * 100 if n_ctx > 0 else 0.0,
            "usage_percent": (total_tokens / n_ctx) * 100 if n_ctx > 0 else 0.0,
        }

    # ------------------------------------------------------------------
    # HTTP ストリーミング
    # ------------------------------------------------------------------

    def _stream_chat_completion(
        self,
        messages: list,
        cfg: dict,
    ) -> Generator[Dict[str, Any], None, None]:
        """llama-server の /v1/chat/completions に POST して SSE チャンクを yield する"""
        payload = {
            "messages": messages,
            "temperature": float(cfg.get("temperature", 0.6)),
            "top_p": float(cfg.get("top_p", 0.95)),
            "top_k": int(cfg.get("top_k", 20)),
            "max_tokens": int(cfg.get("max_tokens", 8192)),
            "repeat_penalty": float(cfg.get("repeat_penalty", 1.05)),
            "stream": True,
        }

        with requests.post(
            f"{self._base_url}/v1/chat/completions",
            json=payload,
            stream=True,
            timeout=600,
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    yield json.loads(data_str)
                except json.JSONDecodeError:
                    continue

    def create_chat_completion_stream(
        self,
        messages: list,
        cfg: dict,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        game_engine 向け: メッセージを直接受け取り OpenAI 形式のチャンクを yield する。
        各チャンクは {"choices": [{"delta": {"content": "..."}}]} 形式。
        """
        return self._stream_chat_completion(messages, cfg)

    # ------------------------------------------------------------------
    # 高レベル生成（thinking/answer 分離）
    # ------------------------------------------------------------------

    def parse_thinking(self, response: str) -> Tuple[str, str]:
        """
        レスポンスから <think>...</think> を分離する

        Returns:
            (thinking_text, answer_text)
        """
        match = THINKING_PATTERN.search(response)
        if match:
            thinking = match.group(1).strip()
            answer = THINKING_PATTERN.sub("", response).strip()
        else:
            thinking = ""
            answer = response.strip()
        return thinking, answer

    def generate_with_context(
        self,
        query: str,
        context: Optional[str] = None,
        history: Optional[list] = None,
        sampling_config: Optional[Dict] = None,
        enable_thinking: bool = True,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        コンテキスト付きでテキストを生成し、Thinking と回答をストリーミングで返す

        Yields:
            {"type": "thinking_chunk", "text": "..."}  ← 思考トークン（逐次）
            {"type": "answer_chunk",   "text": "..."}  ← 回答トークン（逐次）
            {"type": "done",           "text": ""}
        """
        cfg = sampling_config or {}
        messages = self._build_messages(query, context, history, enable_thinking)

        buffer = ""
        state = "answer" if not enable_thinking else "preamble"
        _filter_thinking = not enable_thinking

        for chunk in self._stream_chat_completion(messages, cfg):
            delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
            if not delta:
                continue

            buffer += delta

            if state == "preamble":
                if "<think>" in buffer:
                    after = buffer.split("<think>", 1)[1]
                    buffer = after
                    state = "filtering_thinking" if _filter_thinking else "thinking"
                elif buffer:
                    # Thinkingタグが出ない通常応答は最初の受信分から流す
                    state = "answer"
                    yield {"type": "answer_chunk", "text": buffer}
                    buffer = ""

            elif state == "filtering_thinking":
                if "</think>" in buffer:
                    state = "answer"
                    after = buffer.split("</think>", 1)[1].lstrip("\n")
                    buffer = after
                    if buffer:
                        yield {"type": "answer_chunk", "text": buffer}
                        buffer = ""
                else:
                    if len(buffer) > _MAX_TAG_LEN:
                        buffer = buffer[-_MAX_TAG_LEN:]

            elif state == "thinking":
                if "</think>" in buffer:
                    state = "answer"
                    parts = buffer.split("</think>", 1)
                    if parts[0]:
                        yield {"type": "thinking_chunk", "text": parts[0]}
                    buffer = parts[1].lstrip("\n")
                    if buffer:
                        yield {"type": "answer_chunk", "text": buffer}
                        buffer = ""
                else:
                    safe_len = max(0, len(buffer) - _MAX_TAG_LEN)
                    if safe_len > 0:
                        yield {"type": "thinking_chunk", "text": buffer[:safe_len]}
                        buffer = buffer[safe_len:]

            else:  # state == "answer"
                yield {"type": "answer_chunk", "text": buffer}
                buffer = ""

        # 残りバッファをフラッシュ
        if buffer.strip():
            if state == "thinking":
                yield {"type": "thinking_chunk", "text": buffer.replace("</think>", "").strip()}
            elif state == "answer":
                yield {"type": "answer_chunk", "text": buffer}

        yield {"type": "done", "text": ""}
