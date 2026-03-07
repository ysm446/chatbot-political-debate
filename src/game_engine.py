"""
尋問ゲーム エンジン

ゲームセッション管理・キャラクタープロンプト生成・会話履歴管理
"""
import random
import logging
from typing import Dict, List, Any, Optional, Generator

logger = logging.getLogger(__name__)

from src.scenarios import SCENARIOS


class GameSession:
    def __init__(self, scenario_id: str, boss_suspect_id: str, suspects: List[Dict[str, Any]]):
        self.scenario_id = scenario_id
        self.boss_suspect_id = boss_suspect_id
        self.suspects = suspects  # ロール情報が解決済みの容疑者リスト
        self.conversations: Dict[str, List[Dict[str, str]]] = {
            s["id"]: [] for s in suspects
        }
        self.is_finished = False
        self.player_won: Optional[bool] = None
        self.accused_id: Optional[str] = None

    def to_state_dict(self) -> Dict[str, Any]:
        scenario = SCENARIOS[self.scenario_id]
        return {
            "scenario_id": self.scenario_id,
            "scenario_title": scenario["title"],
            "scenario_description": scenario["description"],
            "suspects": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "age": s["age"],
                    "occupation": s["occupation"],
                    "background": s["background"],
                    "alibi": s["alibi"],
                }
                for s in self.suspects
            ],
            "is_finished": self.is_finished,
            "player_won": self.player_won,
            "accused_id": self.accused_id,
        }


def start_game(scenario_id: str) -> GameSession:
    """シナリオを選択してゲームセッションを開始する。ボスはランダムに決定。"""
    if scenario_id not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_id}")

    scenario = SCENARIOS[scenario_id]
    suspects_template = scenario["suspects"]

    boss_idx = random.randint(0, len(suspects_template) - 1)
    boss_suspect_id = suspects_template[boss_idx]["id"]

    resolved_suspects = []
    for i, template in enumerate(suspects_template):
        role = "boss" if i == boss_idx else "member"
        role_knowledge = template["role_knowledge"][role]
        suspect = {
            **template,
            "role": role,
            "role_desc": role_knowledge["role_desc"],
            "secrets": role_knowledge["secrets"],
            "knowledge": role_knowledge["knowledge"],
        }
        resolved_suspects.append(suspect)

    logger.info("Game started: scenario=%s, boss=%s", scenario_id, boss_suspect_id)
    return GameSession(scenario_id, boss_suspect_id, resolved_suspects)


def build_system_prompt(session: GameSession, suspect_id: str) -> str:
    """指定した容疑者のシステムプロンプトを生成する。"""
    scenario = SCENARIOS[session.scenario_id]
    suspect = next(s for s in session.suspects if s["id"] == suspect_id)
    speech_style = suspect.get("speech_style", suspect["personality"])

    return f"""あなたは「{suspect['name']}」（{suspect['age']}歳、{suspect['occupation']}）として振る舞ってください。

【事件の概要】
{scenario['description']}
事件発生日時: {scenario['incident_date']}

【あなたの基本情報】
- 名前: {suspect['name']}
- 年齢: {suspect['age']}歳
- 職業: {suspect['occupation']}
- 経歴: {suspect['background']}
- アリバイ: {suspect['alibi']}

【あなたの立場（絶対に明かさないこと）】
{suspect['role_desc']}

【あなたが隠していること】
{suspect['secrets']}

【あなたが知っていること・知らないこと】
{suspect['knowledge']}

【話し方・性格】
{suspect['personality']}

【話し方の指示】
{speech_style}

【重要なルール】
1. あなたは尋問を受けている容疑者です。刑事（プレイヤー）からの質問に答えてください。
2. 日本語で、キャラクターとして自然に答えること。
3. 毎回の返答で上記の話し方を維持し、語尾・言い回し・テンポに反映すること。
4. 絶対にゲームのキャラクターであることを明かさないこと。
5. 絶対にボスが誰かを自分から明かさないこと。
6. 嘘をついたり、話をはぐらかしたり、一部の真実だけを話すことは許可されています。
7. 答えは3〜5文程度で、リアルな尋問の会話として自然に振る舞うこと。
8. 話し方の説明をメタに語らず、その口調でそのまま返答すること。
/no_think"""


def add_message(session: GameSession, suspect_id: str, role: str, content: str) -> None:
    """会話履歴にメッセージを追加する。"""
    session.conversations[suspect_id].append({"role": role, "content": content})


def get_conversation(session: GameSession, suspect_id: str) -> List[Dict[str, str]]:
    return session.conversations.get(suspect_id, [])


def accuse(session: GameSession, suspect_id: str) -> Dict[str, Any]:
    """プレイヤーが容疑者を指名する。勝敗を判定して返す。"""
    session.is_finished = True
    session.accused_id = suspect_id
    session.player_won = suspect_id == session.boss_suspect_id

    boss = next(s for s in session.suspects if s["id"] == session.boss_suspect_id)
    accused = next(s for s in session.suspects if s["id"] == suspect_id)
    return {
        "player_won": session.player_won,
        "boss_id": session.boss_suspect_id,
        "boss_name": boss["name"],
        "accused_id": suspect_id,
        "accused_name": accused["name"],
    }


def generate_interrogation_stream(
    session: GameSession,
    suspect_id: str,
    user_message: str,
    llm,
    sampling_config: Optional[Dict] = None,
) -> Generator[Dict[str, Any], None, None]:
    """尋問の返答をSSEストリームで生成する。"""
    cfg = sampling_config or {}
    system_prompt = build_system_prompt(session, suspect_id)
    history = get_conversation(session, suspect_id)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    add_message(session, suspect_id, "user", user_message)

    answer_text = ""
    try:
        stream = llm.llm.create_chat_completion(
            messages=messages,
            temperature=float(cfg.get("temperature", 0.7)),
            top_p=float(cfg.get("top_p", 0.95)),
            top_k=int(cfg.get("top_k", 20)),
            max_tokens=int(cfg.get("max_tokens", 512)),
            repeat_penalty=1.05,
            stream=True,
        )

        # <think>...</think> をストリーミング中にスキップする状態機械
        _MAX_TAG = len("</think>")
        buffer = ""
        state = "preamble"  # preamble → skip_thinking → answer
        first_answer = True  # 最初の回答チャンクか

        def emit_answer(text: str):
            nonlocal answer_text, first_answer
            if first_answer:
                text = text.lstrip()  # 先頭の空白・改行を除去
                first_answer = False
                if not text:
                    return
            answer_text += text
            yield {"event": "answer", "text": text}

        for chunk in stream:
            delta = chunk["choices"][0]["delta"].get("content", "")
            if not delta:
                continue
            buffer += delta

            if state == "preamble":
                if "<think>" in buffer:
                    buffer = buffer.split("<think>", 1)[1]
                    state = "skip_thinking"
                elif len(buffer) > 64:
                    state = "answer"
                    yield from emit_answer(buffer)
                    buffer = ""

            elif state == "skip_thinking":
                if "</think>" in buffer:
                    state = "answer"
                    after = buffer.split("</think>", 1)[1]
                    buffer = after
                    if buffer:
                        yield from emit_answer(buffer)
                        buffer = ""
                else:
                    if len(buffer) > _MAX_TAG:
                        buffer = buffer[-_MAX_TAG:]

            else:  # answer
                yield from emit_answer(buffer)
                buffer = ""

        # 残りバッファをフラッシュ
        if buffer.strip() and state == "answer":
            yield from emit_answer(buffer)

    except Exception as exc:
        logger.error("LLM生成エラー: %s", exc)
        yield {"event": "error", "text": str(exc)}
        return

    add_message(session, suspect_id, "assistant", answer_text)
    yield {"event": "done", "text": ""}
