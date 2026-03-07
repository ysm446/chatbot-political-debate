"""
政治討論シミュレーターのセッション管理。

司会者であるプレイヤーが各党の議員に問いかけ、
各議員は党の特色と個人の性格を踏まえて討論する。
"""
import logging
import random
from typing import Any, Dict, Generator, List, Optional

from src.debate_data import DEBATE_TOPICS, PARTIES, POLITICIANS

logger = logging.getLogger(__name__)


class DebateSession:
    def __init__(self, topic_id: str, speakers: List[Dict[str, Any]]):
        self.topic_id = topic_id
        self.speakers = speakers
        self.conversations: Dict[str, List[Dict[str, str]]] = {
            speaker["id"]: [] for speaker in speakers
        }
        self.memories: Dict[str, List[str]] = {speaker["id"]: [] for speaker in speakers}
        self.timeline: List[Dict[str, str]] = []
        self.is_finished = False

    def to_state_dict(self) -> Dict[str, Any]:
        topic = DEBATE_TOPICS[self.topic_id]
        return {
            "topic_id": self.topic_id,
            "topic_title": topic["title"],
            "topic_summary": topic["summary"],
            "topic_points": topic.get("key_points", []),
            "speaker_count": len(self.speakers),
            "speakers": [
                {
                    "id": speaker["id"],
                    "name": speaker["name"],
                    "age": speaker["age"],
                    "role_title": speaker["role_title"],
                    "party_id": speaker["party_id"],
                    "party_name": speaker["party_name"],
                    "party_position": speaker["party_position"],
                    "career": speaker["career"],
                    "personality": speaker["personality"],
                    "catchphrase": speaker["catchphrase"],
                    "public_profile": speaker["public_profile"],
                }
                for speaker in self.speakers
            ],
        }


def list_topics() -> List[Dict[str, Any]]:
    rows = []
    for topic_id, topic in DEBATE_TOPICS.items():
        rows.append(
            {
                "id": topic_id,
                "title": topic["title"],
                "description": topic["summary"],
            }
        )
    return rows


def _pick_speakers() -> List[Dict[str, Any]]:
    speakers: List[Dict[str, Any]] = []
    for party_id, party in PARTIES.items():
        candidates = [
            politician
            for politician in POLITICIANS.values()
            if politician.get("party_id") == party_id
        ]
        if not candidates:
            logger.warning("No politicians found for party=%s", party_id)
            continue

        base = random.choice(candidates)
        speakers.append(
            {
                **base,
                "party_name": party["name"],
                "party_position": party["stance_summary"],
                "party_values": party.get("core_values", []),
                "policy_stances": party.get("policy_stances", {}),
                "coalition_style": party.get("coalition_style", ""),
                "debate_strategy": party.get("debate_strategy", ""),
            }
        )

    return speakers


def start_game(topic_id: str) -> DebateSession:
    if topic_id not in DEBATE_TOPICS:
        raise ValueError(f"Unknown topic: {topic_id}")

    speakers = _pick_speakers()
    if not speakers:
        raise ValueError("No speakers available")

    session = DebateSession(topic_id=topic_id, speakers=speakers)
    logger.info("Debate started: topic=%s, speakers=%s", topic_id, [s["id"] for s in speakers])
    return session


def get_conversation(session: DebateSession, speaker_id: str) -> List[Dict[str, str]]:
    return session.conversations.get(speaker_id, [])


def _timeline_text(session: DebateSession, current_speaker_id: str, limit: int = 10) -> str:
    items = session.timeline[-limit:]
    if not items:
        return "まだ討論は始まったばかりです。"

    lines = []
    for item in items:
        speaker_label = item["speaker_name"]
        if item["speaker_id"] == "moderator":
            speaker_label = "司会者"
        elif item["speaker_id"] == current_speaker_id:
            speaker_label = f"{speaker_label}（あなた）"
        lines.append(f"- {speaker_label}: {item['content']}")
    return "\n".join(lines)


def _memory_text(session: DebateSession, speaker_id: str, limit: int = 8) -> str:
    memories = session.memories.get(speaker_id, [])
    if not memories:
        return "まだ個別のやり取りは少なく、明確な個人メモはありません。"
    return "\n".join(f"- {memory}" for memory in memories[-limit:])


def build_system_prompt(session: DebateSession, speaker_id: str) -> str:
    topic = DEBATE_TOPICS[session.topic_id]
    speaker = next(s for s in session.speakers if s["id"] == speaker_id)
    speech_style = speaker.get("speech_style", speaker["personality"])

    topic_points = "\n".join(f"- {point}" for point in topic.get("key_points", []))
    party_values = "\n".join(f"- {value}" for value in speaker.get("party_values", []))
    policy_lines = "\n".join(
        f"- {policy}: {stance}"
        for policy, stance in speaker.get("policy_stances", {}).items()
    )

    return f"""あなたは日本の政治討論番組に出演している国会議員「{speaker['name']}」として振る舞ってください。

【番組設定】
- プレイヤーは司会者です。
- あなたは {speaker['party_name']} 所属の {speaker['role_title']} です。
- 司会者の質問や他党議員の発言を踏まえて、自分の立場を明確に述べてください。

【今回の討論テーマ】
- タイトル: {topic['title']}
- 概要: {topic['summary']}
- 注目論点:
{topic_points}

【所属政党の特色】
- 党名: {speaker['party_name']}
- 立ち位置: {speaker['party_position']}
- 重視する価値観:
{party_values}
- 主要政策スタンス:
{policy_lines}
- 他党との向き合い方: {speaker.get('coalition_style', '')}
- 討論での基本戦略: {speaker.get('debate_strategy', '')}

【あなた個人の設定】
- 名前: {speaker['name']}
- 年齢: {speaker['age']}歳
- 役職: {speaker['role_title']}
- 経歴: {speaker['career']}
- 公のプロフィール: {speaker['public_profile']}
- 性格: {speaker['personality']}
- 決め台詞・口癖: {speaker['catchphrase']}
- 議論スタイル: {speaker['debate_style']}
- 弱み: {speaker['pressure_point']}

【あなたの記憶】
{_memory_text(session, speaker_id)}

【直近の討論の流れ】
{_timeline_text(session, speaker_id)}

【話し方の指示】
{speech_style}

【重要なルール】
1. あなたは実在政治家本人ではなく、政党の特色と議員キャラクターを組み合わせた架空の議員です。
2. 日本語で、テレビ討論らしく簡潔かつ主張のある返答をしてください。
3. 司会者の問いに答えつつ、必要なら他党の発言への反論や補足も行ってください。
4. これまでの討論履歴を踏まえ、前の発言と矛盾しないようにしてください。
5. 自党に都合の悪い論点でも完全に逃げず、反論・条件付き賛成・論点ずらしのいずれかで応答してください。
6. 毎回3〜6文で返答し、抽象論だけで終わらず、政策の方向性を入れてください。
7. 話し方の説明をメタに語らず、その口調でそのまま返答してください。
8. 勝敗判定やゲームの内部仕様には触れないでください。
/no_think"""


def add_message(
    session: DebateSession,
    speaker_id: str,
    role: str,
    content: str,
    speaker_name: Optional[str] = None,
) -> None:
    session.conversations[speaker_id].append({"role": role, "content": content})

    if role == "user":
        session.timeline.append(
            {
                "speaker_id": "moderator",
                "speaker_name": "司会者",
                "content": content,
            }
        )
        session.memories[speaker_id].append(f"司会者から『{content}』と問われた。")
    elif role == "assistant":
        resolved_name = speaker_name or next(
            s["name"] for s in session.speakers if s["id"] == speaker_id
        )
        session.timeline.append(
            {
                "speaker_id": speaker_id,
                "speaker_name": resolved_name,
                "content": content,
            }
        )
        session.memories[speaker_id].append(f"自分は『{content}』と応答した。")


def generate_interrogation_stream(
    session: DebateSession,
    suspect_id: str,
    user_message: str,
    llm,
    sampling_config: Optional[Dict] = None,
) -> Generator[Dict[str, Any], None, None]:
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

        max_tag = len("</think>")
        buffer = ""
        state = "preamble"
        first_answer = True

        def emit_answer(text: str):
            nonlocal answer_text, first_answer
            if first_answer:
                text = text.lstrip()
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
                elif len(buffer) > max_tag:
                    buffer = buffer[-max_tag:]

            else:
                yield from emit_answer(buffer)
                buffer = ""

        if buffer.strip() and state == "answer":
            yield from emit_answer(buffer)

    except Exception as exc:
        logger.error("LLM generation error: %s", exc)
        yield {"event": "error", "text": str(exc)}
        return

    speaker_name = next(s["name"] for s in session.speakers if s["id"] == suspect_id)
    add_message(session, suspect_id, "assistant", answer_text, speaker_name=speaker_name)
    yield {"event": "done", "text": ""}
