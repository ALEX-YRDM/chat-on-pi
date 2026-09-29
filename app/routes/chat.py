from fastapi import APIRouter, Depends
from ..dependencies import runtime
from ..schemas import ChatInput

router = APIRouter(prefix="/api")


@router.post("/chat")
def chat(body: ChatInput, rt=Depends(runtime)):
    return rt.pipeline.chat(body.conversation_id, body.message, body.synthesize, body.play)
