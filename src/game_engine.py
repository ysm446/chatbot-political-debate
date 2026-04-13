"""
政治討論シミュレーターのセッション管理。

司会者の問いに対し、各党の議員がターン制で応答する。
各議員は共有の討論履歴を参照し、他党の発言を踏まえて反論できる。
"""
import logging
import random
import re
from typing import Any, Dict, Generator, List, Optional

from src.debate_data import DEBATE_TOPICS, PARTIES, POLITICIANS

logger = logging.getLogger(__name__)

MAX_ACTIVE_SPEAKERS = 5
MAX_SPEAKERS_PER_ROUND = 4


class DebateSession:
    def __init__(self, topic_id: str, speakers: List[Dict[str, Any]]):
        self.topic_id = topic_id
        self.speakers = speakers
        self.conversations: Dict[str, List[Dict[str, str]]] = {
            speaker["id"]: [] for speaker in speakers
        }
        self.memories: Dict[str, List[str]] = {speaker["id"]: [] for speaker in speakers}
        self.timeline: List[Dict[str, str]] = []
        self.shared_history: List[Dict[str, str]] = []
        self.round_count = 0
        self.is_finished = False

    def to_state_dict(self) -> Dict[str, Any]:
        topic = DEBATE_TOPICS[self.topic_id]
        return {
            "topic_id": self.topic_id,
            "topic_title": topic["title"],
            "topic_summary": topic["summary"],
            "topic_points": topic.get("key_points", []),
            "speaker_count": len(self.speakers),
            "round_count": self.round_count,
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
    return [
        {
            "id": topic_id,
            "title": topic["title"],
            "description": topic["summary"],
        }
        for topic_id, topic in DEBATE_TOPICS.items()
    ]


def _pick_speakers() -> List[Dict[str, Any]]:
    available_party_ids = [
        party_id
        for party_id in PARTIES.keys()
        if any(
            politician.get("party_id") == party_id
            for politician in POLITICIANS.values()
        )
    ]
    if len(available_party_ids) < MAX_ACTIVE_SPEAKERS:
        raise ValueError(
            f"At least {MAX_ACTIVE_SPEAKERS} parties with politicians are required, "
            f"but only {len(available_party_ids)} are available"
        )

    selected_party_ids = set(random.sample(available_party_ids, MAX_ACTIVE_SPEAKERS))

    speakers: List[Dict[str, Any]] = []
    for party_id, party in PARTIES.items():
        if party_id not in selected_party_ids:
            continue
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


def get_round_order(session: DebateSession) -> List[Dict[str, Any]]:
    if not session.speakers:
        return []

    shift = session.round_count % len(session.speakers)
    return session.speakers[shift:] + session.speakers[:shift]


def _topic_policy_key(topic_id: str) -> str:
    mapping = {
        "nuclear_deterrence": "核武装",
        "social_security_reform": "社会保障",
        "economic_stimulus": "経済対策",
        "energy_transition": "エネルギー",
        "population_decline": "少子化",
    }
    return mapping.get(topic_id, "")


def _speaker_bloc(party_id: str) -> str:
    blocs = {
        "ldp": "conservative",
        "komeito": "moderate",
        "cdp": "liberal",
        "ishin": "reform",
        "dpfp": "centrist",
        "jcp": "left",
        "reiwa": "left_populist",
        "sanseito": "national_conservative",
    }
    return blocs.get(party_id, "other")


def _bloc_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    pair = {a, b}
    if pair <= {"left", "left_populist"}:
        return 1
    if pair <= {"conservative", "national_conservative"}:
        return 1
    if pair <= {"moderate", "centrist"}:
        return 1
    if "left" in pair or "left_populist" in pair:
        return 3
    if "national_conservative" in pair and "liberal" in pair:
        return 3
    return 2


def _stance_signature(text: str) -> set[str]:
    keywords = re.findall(r"[A-Za-z]+|[一-龠ぁ-んァ-ヶー]{2,}", text or "")
    stopwords = {
        "重視", "慎重", "反対", "支持", "強化", "拡大", "維持", "改革", "主張",
        "重視する", "重視し", "現実", "路線", "中心", "優先", "活用", "対策",
    }
    return {word for word in keywords if word not in stopwords}


def _stance_distance(a: str, b: str) -> int:
    if not a or not b:
        return 1
    if a == b:
        return 0
    neg_words = ("反対", "廃止", "ゼロ", "慎重")
    pos_words = ("推進", "強化", "活用", "拡大", "重視", "容認")
    a_neg = any(word in a for word in neg_words)
    b_neg = any(word in b for word in neg_words)
    a_pos = any(word in a for word in pos_words)
    b_pos = any(word in b for word in pos_words)
    if (a_neg and b_pos) or (a_pos and b_neg):
        return 3

    overlap = len(_stance_signature(a) & _stance_signature(b))
    return 1 if overlap > 0 else 2


def _candidate_score(
    session: DebateSession,
    previous_speaker: Dict[str, Any],
    candidate: Dict[str, Any],
    latest_content: str = "",
) -> int:
    policy_key = _topic_policy_key(session.topic_id)
    prev_stance = previous_speaker.get("policy_stances", {}).get(policy_key, "")
    cand_stance = candidate.get("policy_stances", {}).get(policy_key, "")
    score = _bloc_distance(_speaker_bloc(previous_speaker["party_id"]), _speaker_bloc(candidate["party_id"])) * 10
    score += _stance_distance(prev_stance, cand_stance) * 5
    if candidate["party_id"] in {"jcp", "reiwa", "sanseito", "ishin"}:
        score += 1
    if latest_content:
        if candidate["name"] in latest_content:
            score += 8
        if candidate["party_name"] in latest_content:
            score += 6
    return score


def _find_targeted_speaker(session: DebateSession, user_message: str) -> Optional[Dict[str, Any]]:
    normalized_message = (
        user_message.replace(" ", "")
        .replace("　", "")
        .replace("さん", "")
        .replace("氏", "")
        .replace("議員", "")
    )

    for speaker in session.speakers:
        full_name = speaker["name"].replace(" ", "").replace("　", "")
        parts = [part for part in re.split(r"\s+", speaker["name"].replace("　", " ")) if part]
        surname = parts[0] if parts else ""
        given_name = parts[1] if len(parts) > 1 else ""

        if full_name and full_name in normalized_message:
            return speaker
        if surname and surname in normalized_message:
            return speaker
        if given_name and given_name in normalized_message:
            return speaker

    for speaker in session.speakers:
        if speaker["party_name"] in user_message:
            return speaker
    return None


def select_initial_speaker(session: DebateSession, user_message: str) -> Optional[Dict[str, Any]]:
    targeted = _find_targeted_speaker(session, user_message)
    if targeted is not None:
        return targeted

    order = get_round_order(session)
    if not order:
        return None

    return order[0]


def select_next_speaker(
    session: DebateSession,
    previous_speaker: Dict[str, Any],
    latest_content: str,
    already_spoken_ids: set[str],
) -> Optional[Dict[str, Any]]:
    remaining = [
        speaker for speaker in session.speakers
        if speaker["id"] not in already_spoken_ids
    ]
    if not remaining:
        return None

    next_speaker = max(
        remaining,
        key=lambda speaker: _candidate_score(session, previous_speaker, speaker, latest_content),
    )
    score = _candidate_score(session, previous_speaker, next_speaker, latest_content)
    if score < 15:
        return None
    return next_speaker


def build_predicted_round_order(session: DebateSession, user_message: str) -> List[Dict[str, Any]]:
    first = select_initial_speaker(session, user_message)
    if first is None:
        return []

    selected = [first]
    already_spoken_ids = {first["id"]}
    latest_content = user_message

    while len(selected) < min(MAX_SPEAKERS_PER_ROUND, len(session.speakers)):
        previous = selected[-1]
        next_speaker = select_next_speaker(
            session=session,
            previous_speaker=previous,
            latest_content=latest_content,
            already_spoken_ids=already_spoken_ids,
        )
        if next_speaker is None:
            break
        selected.append(next_speaker)
        already_spoken_ids.add(next_speaker["id"])
        latest_content = next_speaker.get("party_position", "")

    return selected


def _timeline_text(session: DebateSession, current_speaker_id: str, limit: int = 12) -> str:
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


def _memory_text(session: DebateSession, speaker_id: str, limit: int = 10) -> str:
    memories = session.memories.get(speaker_id, [])
    if not memories:
        return "まだ個別のやり取りは少なく、明確な個人メモはありません。"
    return "\n".join(f"- {memory}" for memory in memories[-limit:])


def _recent_opponents_text(session: DebateSession, current_speaker_id: str, limit: int = 4) -> str:
    opponents = [
        item for item in reversed(session.timeline)
        if item["speaker_id"] not in {"moderator", current_speaker_id}
    ]
    if not opponents:
        return "まだ他党の明確な主張は少ない。最初は自党の立場を鮮明に出すこと。"
    return "\n".join(
        f"- {item['speaker_name']}: {item['content']}" for item in opponents[:limit]
    )


def _format_style_items(value: Any) -> str:
    if not value:
        return "- 未設定"
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return "- 未設定"
        lines = [line.strip(" ・-") for line in stripped.splitlines() if line.strip()]
        return "\n".join(f"- {line}" for line in lines) if lines else "- 未設定"
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(f"- {item}" for item in items) if items else "- 未設定"
    return f"- {str(value).strip()}"


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
    phrase_bank = _format_style_items(speaker.get("phrase_bank"))
    speech_habits = _format_style_items(speaker.get("speech_habits"))

    return f"""あなたは日本の政治討論番組に出演している国会議員「{speaker['name']}」として振る舞ってください。

【番組設定】
- プレイヤーは司会者です。
- あなたは {speaker['party_name']} 所属の {speaker['role_title']} です。
- 今は複数政党が流れに応じて応答する討論です。

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
- 抽象化したモデル元: {speaker.get('inspiration_note', '未設定')}
- 話し方の特徴: {speaker.get('speech_traits', '未設定')}
- 重点政策: {speaker.get('policy_focus', '未設定')}
- デバッグ観点: {speaker.get('debug_expectation', '未設定')}

【あなたの記憶】
{_memory_text(session, speaker_id)}

【直近の討論の流れ】
{_timeline_text(session, speaker_id)}

【特に反応すべき他党発言】
{_recent_opponents_text(session, speaker_id)}

【話し方の指示】
{speech_style}

【口調の癖】
{speech_habits}

【よく使う言い回し】
{phrase_bank}

【重要なルール】
1. あなたは実在政治家本人ではなく、政党の特色と議員キャラクターを組み合わせた架空の議員です。
2. 日本語で、テレビ討論らしく簡潔かつ主張のある返答をしてください。
3. まず司会者の問いに正面から答えてください。
4. 他党議員の発言に反応する場合は、賛成でも反論でもよいですが、立場の違いを明確にしてください。
5. これまでの討論履歴を踏まえ、前の発言と矛盾しないようにしてください。
6. 自党に都合の悪い論点でも完全に逃げず、反論・条件付き賛成・論点ずらしのいずれかで応答してください。
7. 毎回200〜300文字程度、目安として3〜4文で返答し、抽象論だけで終わらず、政策の方向性を入れてください。
8. 話し方の説明をメタに語らず、その口調でそのまま返答してください。
9. 勝敗判定やゲームの内部仕様には触れないでください。
10. phrase_bank の言い回しは毎回使う必要はありません。使っても0〜1個までにし、同じ表現の繰り返しは避けてください。
11. speech_habits は雰囲気として反映し、口癖や定型句の連発にならないようにしてください。
12. 返答は普通の会話文だけで出力し、** や * などの Markdown 記法、箇条書き、見出し、記号装飾は使わないでください。
/no_think"""


def build_round_messages(
    session: DebateSession,
    speaker_id: str,
    user_message: str,
) -> List[Dict[str, str]]:
    system_prompt = build_system_prompt(session, speaker_id)
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(session.shared_history)
    messages.append({"role": "user", "content": user_message})
    return messages


def estimate_round_context_usage(
    session: DebateSession,
    user_message: str,
    llm,
    sampling_config: Optional[Dict] = None,
) -> Dict[str, Any]:
    cfg = sampling_config or {}
    n_ctx = int(getattr(llm, "config", {}).get("n_ctx", 32768))
    reserve_tokens = int(cfg.get("max_tokens", 512))
    usages: List[Dict[str, Any]] = []

    for speaker in build_predicted_round_order(session, user_message):
        messages = build_round_messages(session, speaker["id"], user_message)
        prompt_tokens = llm._count_prompt_tokens(messages)
        total_tokens = prompt_tokens + reserve_tokens
        usages.append(
            {
                "speaker_id": speaker["id"],
                "speaker_name": speaker["name"],
                "prompt_tokens": prompt_tokens,
                "reserve_tokens": reserve_tokens,
                "total_tokens": total_tokens,
                "prompt_percent": (prompt_tokens / n_ctx) * 100 if n_ctx > 0 else 0.0,
                "usage_percent": (total_tokens / n_ctx) * 100 if n_ctx > 0 else 0.0,
            }
        )

    if not usages:
        return {
            "n_ctx": n_ctx,
            "prompt_tokens": 0,
            "reserve_tokens": reserve_tokens,
            "total_tokens": reserve_tokens,
            "prompt_percent": 0.0,
            "usage_percent": 0.0,
            "speaker_name": "",
            "per_speaker": [],
        }

    heaviest = max(usages, key=lambda row: row["total_tokens"])
    return {
        **heaviest,
        "n_ctx": n_ctx,
        "per_speaker": usages,
    }


def add_message(
    session: DebateSession,
    speaker_id: str,
    role: str,
    content: str,
    speaker_name: Optional[str] = None,
) -> None:
    session.conversations[speaker_id].append({"role": role, "content": content})
    if role == "user":
        session.memories[speaker_id].append(f"司会者から『{content}』と問われた。")
        return

    resolved_name = speaker_name or next(
        s["name"] for s in session.speakers if s["id"] == speaker_id
    )
    session.shared_history.append({"role": "assistant", "content": content})
    session.timeline.append(
        {
            "speaker_id": speaker_id,
            "speaker_name": resolved_name,
            "content": content,
        }
    )
    session.memories[speaker_id].append(f"自分は『{content}』と応答した。")
    for other in session.speakers:
        if other["id"] == speaker_id:
            continue
        session.memories[other["id"]].append(
            f"{resolved_name} が『{content}』と述べた。必要に応じて反論材料に使える。"
        )


def add_moderator_prompt(session: DebateSession, content: str) -> None:
    session.shared_history.append({"role": "user", "content": content})
    session.timeline.append(
        {
            "speaker_id": "moderator",
            "speaker_name": "司会者",
            "content": content,
        }
    )
    for speaker in session.speakers:
        session.conversations[speaker["id"]].append({"role": "user", "content": content})
        session.memories[speaker["id"]].append(f"司会者から『{content}』と問われた。")


def _stream_single_speaker_reply(
    session: DebateSession,
    speaker_id: str,
    llm,
    sampling_config: Optional[Dict] = None,
) -> Generator[Dict[str, Any], None, None]:
    cfg = sampling_config or {}
    system_prompt = build_system_prompt(session, speaker_id)
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(session.shared_history)
    # llama-server (OpenAI 互換 API) は最後のメッセージが "user" でないと 400 を返す。
    # 2番目以降の登壇者は shared_history が assistant で終わるため、明示的に発言を促す。
    if messages[-1]["role"] != "user":
        messages.append({"role": "user", "content": "（あなたの番です。発言してください）"})
    # Qwen3/3.5 の思考モードを確実に無効化するため /no_think をユーザーメッセージに付加する。
    # （system プロンプト末尾の /no_think だけでは Qwen3.5 で効かない場合がある）
    for i in range(len(messages) - 1, -1, -1):
        if messages[i]["role"] == "user":
            if "/no_think" not in messages[i]["content"]:
                messages[i] = {**messages[i], "content": messages[i]["content"] + "\n/no_think"}
            break

    answer_text = ""
    try:
        stream_cfg = {
            "temperature": float(cfg.get("temperature", 0.7)),
            "top_p": float(cfg.get("top_p", 0.95)),
            "top_k": int(cfg.get("top_k", 20)),
            "max_tokens": int(cfg.get("max_tokens", 512)),
            "repeat_penalty": 1.05,
        }

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
            yield {"event": "answer", "speaker_id": speaker_id, "text": text}

        for chunk in llm.create_chat_completion_stream(messages, stream_cfg):
            delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
            if not delta:
                continue
            buffer += delta

            if state == "preamble":
                if "<think>" in buffer:
                    buffer = buffer.split("<think>", 1)[1]
                    state = "skip_thinking"
                    yield {"event": "thinking_status", "speaker_id": speaker_id}
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
        logger.error("LLM generation error for %s: %s", speaker_id, exc)
        yield {"event": "error", "speaker_id": speaker_id, "text": str(exc)}
        return

    speaker_name = next(s["name"] for s in session.speakers if s["id"] == speaker_id)
    add_message(session, speaker_id, "assistant", answer_text, speaker_name=speaker_name)
    yield {"event": "speaker_done", "speaker_id": speaker_id, "text": ""}


def generate_interrogation_stream(
    session: DebateSession,
    user_message: str,
    llm,
    sampling_config: Optional[Dict] = None,
) -> Generator[Dict[str, Any], None, None]:
    session.round_count += 1
    first_speaker = select_initial_speaker(session, user_message)
    round_order = [first_speaker] if first_speaker is not None else []

    yield {
        "event": "round_start",
        "round": session.round_count,
        "order": [
            {"speaker_id": speaker["id"], "speaker_name": speaker["name"]}
            for speaker in round_order
        ],
    }

    add_moderator_prompt(session, user_message)

    spoken_ids: set[str] = set()
    latest_content = user_message

    while round_order and len(spoken_ids) < min(MAX_SPEAKERS_PER_ROUND, len(session.speakers)):
        speaker = round_order.pop(0)
        if speaker["id"] in spoken_ids:
            continue

        yield {
            "event": "speaker_start",
            "round": session.round_count,
            "speaker_id": speaker["id"],
            "speaker_name": speaker["name"],
            "party_name": speaker["party_name"],
        }
        final_text = ""
        for event in _stream_single_speaker_reply(
            session=session,
            speaker_id=speaker["id"],
            llm=llm,
            sampling_config=sampling_config,
        ):
            if event.get("event") == "answer":
                final_text += event.get("text", "")
            yield event

        spoken_ids.add(speaker["id"])
        latest_content = final_text or latest_content
        next_speaker = select_next_speaker(
            session=session,
            previous_speaker=speaker,
            latest_content=latest_content,
            already_spoken_ids=spoken_ids,
        )
        if next_speaker is not None:
            round_order.append(next_speaker)

    yield {"event": "done", "text": ""}
