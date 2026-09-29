import time
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from ..dependencies import runtime
from ..models import PipelineRun
from ..pipeline import State
from ..repository import serialize
from ..schemas import AudioInput, TextInput

router = APIRouter(prefix="/api/debug")


@router.post("/record")
def microphone_test(rt=Depends(runtime)):
    recording = rt.pipeline.start_recording(min(5, rt.config.active.audio.max_record_seconds))
    time.sleep(min(5, rt.config.active.audio.max_record_seconds))
    return rt.pipeline.stop_recording(recording["recording_id"])


@router.post("/whisper")
def whisper_test(body: AudioInput, rt=Depends(runtime)):
    path = rt.audio.validate_wav(body.audio_path, require_stt=True)
    return rt.pipeline.diagnostic(State.TRANSCRIBING, rt.whisper.transcribe, str(path))


@router.post("/ollama")
def ollama_test(body: TextInput, rt=Depends(runtime)):
    return rt.pipeline.diagnostic(State.THINKING, rt.ollama.chat, [{"role": "user", "content": body.text}])


@router.post("/piper")
def piper_test(body: TextInput, rt=Depends(runtime)):
    result = rt.pipeline.diagnostic(State.SYNTHESIZING, rt.piper.synthesize, body.text)
    result["filename"] = rt.audio.resolve(result.pop("output")).name
    result["audio_url"] = rt.audio.url(result["filename"])
    return result


@router.post("/pipeline")
def full_pipeline_test(conversation_id: int = Query(gt=0), rt=Depends(runtime)):
    return rt.pipeline.full_test(conversation_id)


@router.get("/runs")
def recent_runs(rt=Depends(runtime)):
    with rt.db.session() as session:
        return [serialize(run) for run in session.scalars(select(PipelineRun).order_by(PipelineRun.id.desc()).limit(20))]
