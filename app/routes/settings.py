from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from ..dependencies import runtime
from ..config import Settings
from ..errors import ServiceError
from ..models import Conversation, PromptProfile
from ..repository import get_prompt, serialize
from ..schemas import PromptInput

router = APIRouter(prefix="/api")


@router.get("/prompts")
def prompts(rt=Depends(runtime)):
    with rt.db.session() as session:
        return [serialize(row) for row in session.scalars(select(PromptProfile).order_by(PromptProfile.id))]


def write_prompt(body, session, row=None):
    if row is not None and row.is_default and not body.is_default:
        raise ServiceError("请先将另一个 Prompt 设为默认", 409)
    if body.is_default:
        session.execute(update(PromptProfile).values(is_default=False))
    if row is None:
        row = PromptProfile()
        session.add(row)
    row.name, row.content, row.is_default = body.name, body.content, body.is_default
    session.flush()
    return serialize(row)


@router.post("/prompts", status_code=201)
def create_prompt(body: PromptInput, rt=Depends(runtime)):
    with rt.pipeline.exclusive(), rt.db.session.begin() as session:
        return write_prompt(body, session)


@router.put("/prompts/{prompt_id}")
def edit_prompt(prompt_id: int, body: PromptInput, rt=Depends(runtime)):
    with rt.pipeline.exclusive(), rt.db.session.begin() as session:
        return write_prompt(body, session, get_prompt(session, prompt_id))


@router.delete("/prompts/{prompt_id}")
def delete_prompt(prompt_id: int, rt=Depends(runtime)):
    with rt.pipeline.exclusive(), rt.db.session.begin() as session:
        row = get_prompt(session, prompt_id)
        if row.is_default or session.scalar(select(Conversation.id).where(Conversation.system_prompt_id == prompt_id).limit(1)):
            raise ServiceError("默认 Prompt 或仍被对话使用的 Prompt 不能删除，请先更改绑定", 409)
        session.delete(row)
        return {"success": True}


@router.get("/settings")
def get_settings(rt=Depends(runtime)):
    saved = rt.config.load()
    return {"config": saved.model_dump(), "active": rt.config.active.model_dump(),
            "restart_required": saved != rt.config.active}


@router.put("/settings")
def save_settings(body: Settings, rt=Depends(runtime)):
    with rt.pipeline.exclusive():
        rt.config.save(body)
    return {"success": True, "restart_required": body != rt.config.active,
            "message": "已保存到 config.yaml；重启服务后生效。Prompt 修改立即生效。"}
