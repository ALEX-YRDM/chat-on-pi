"""Short database transactions; never hold a transaction during model inference."""
from datetime import timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from .errors import ServiceError
from .models import Conversation, Message, PromptProfile, utcnow


def get_conversation(session: Session, conversation_id: int) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise ServiceError("对话不存在", 404)
    return conversation


def get_prompt(session: Session, prompt_id: int) -> PromptProfile:
    prompt = session.get(PromptProfile, prompt_id)
    if prompt is None:
        raise ServiceError("Prompt 不存在", 404)
    return prompt


def build_messages(session: Session, conversation: Conversation, current: str, limit: int) -> list[dict[str, str]]:
    prompt = get_prompt(session, conversation.system_prompt_id)
    history = session.scalars(select(Message).where(
        Message.conversation_id == conversation.id, Message.role.in_(["user", "assistant"])
    ).order_by(Message.id.desc()).limit(limit)).all()
    return ([{"role": "system", "content": prompt.content}]
            + [{"role": message.role, "content": message.content} for message in reversed(history)]
            + [{"role": "user", "content": current}])


def add_user(session: Session, conversation: Conversation, content: str,
             audio_path: str | None = None, latency_ms: int | None = None) -> Message:
    first_id = session.scalar(select(Message.id).where(Message.conversation_id == conversation.id).limit(1))
    if first_id is None and conversation.title == "新对话":
        conversation.title = content[:20]
    conversation.updated_at = utcnow()
    message = Message(conversation_id=conversation.id, role="user", content=content,
                      audio_path=audio_path, latency_ms=latency_ms)
    session.add(message)
    session.flush()
    return message


def serialize(row) -> dict:
    result = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    for key in ("created_at", "updated_at"):
        if key in result:
            result[key] = result[key].replace(tzinfo=timezone.utc).isoformat()
    if isinstance(row, Message):
        result["audio_url"] = f"/api/audio/{row.audio_path}" if row.audio_path else None
    return result
