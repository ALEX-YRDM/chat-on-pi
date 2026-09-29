from fastapi import APIRouter, Depends
from sqlalchemy import select
from ..dependencies import runtime
from ..models import Conversation, Message, PromptProfile
from ..repository import get_conversation, get_prompt, serialize
from ..schemas import ConversationCreate, ConversationUpdate

router = APIRouter(prefix="/api/conversations")


@router.get("")
def list_conversations(rt=Depends(runtime)):
    with rt.db.session() as session:
        return [serialize(row) for row in session.scalars(select(Conversation).order_by(Conversation.updated_at.desc()))]


@router.post("", status_code=201)
def create_conversation(body: ConversationCreate, rt=Depends(runtime)):
    with rt.pipeline.exclusive(), rt.db.session.begin() as session:
        prompt_id = body.system_prompt_id or session.scalar(select(PromptProfile.id).where(PromptProfile.is_default.is_(True)))
        get_prompt(session, prompt_id)
        row = Conversation(title=body.title, system_prompt_id=prompt_id)
        session.add(row)
        session.flush()
        return serialize(row)


@router.get("/{conversation_id}")
def conversation_detail(conversation_id: int, rt=Depends(runtime)):
    with rt.db.session() as session:
        return serialize(get_conversation(session, conversation_id))


@router.put("/{conversation_id}")
def bind_prompt(conversation_id: int, body: ConversationUpdate, rt=Depends(runtime)):
    with rt.pipeline.exclusive(), rt.db.session.begin() as session:
        row = get_conversation(session, conversation_id)
        get_prompt(session, body.system_prompt_id)
        row.system_prompt_id = body.system_prompt_id
        session.flush()
        return serialize(row)


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: int, rt=Depends(runtime)):
    with rt.pipeline.exclusive():
        with rt.db.session.begin() as session:
            row = get_conversation(session, conversation_id)
            paths = session.scalars(select(Message.audio_path).where(Message.conversation_id == conversation_id, Message.audio_path.is_not(None))).all()
            session.delete(row)
        for path in paths:
            with rt.db.session() as session:
                referenced = session.scalar(select(Message.id).where(Message.audio_path == path).limit(1))
            if referenced is None:
                rt.audio.delete(path)
        return {"success": True}


@router.get("/{conversation_id}/messages")
def list_messages(conversation_id: int, rt=Depends(runtime)):
    with rt.db.session() as session:
        get_conversation(session, conversation_id)
        return [serialize(row) for row in session.scalars(select(Message).where(
            Message.conversation_id == conversation_id).order_by(Message.id))]
