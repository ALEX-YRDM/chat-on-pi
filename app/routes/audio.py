from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from ..dependencies import runtime
from ..pipeline import State
from ..schemas import AudioInput, VoiceInput

router = APIRouter(prefix="/api")


@router.post("/record/start")
def start_recording(rt=Depends(runtime)):
    return rt.pipeline.start_recording()


@router.post("/record/stop")
def stop_recording(recording_id: str | None = None, rt=Depends(runtime)):
    return rt.pipeline.stop_recording(recording_id)


@router.post("/voice/process")
def process_voice(body: VoiceInput, rt=Depends(runtime)):
    return rt.pipeline.voice(body.conversation_id, body.recording_id, body.audio_path, body.play)


@router.get("/audio")
def list_audio(rt=Depends(runtime)):
    paths = sorted((path for path in rt.audio.directory.glob("*.wav") if not path.is_symlink()),
                   key=lambda path: path.stat().st_mtime, reverse=True)[:100]
    return [{"filename": path.name, "audio_url": rt.audio.url(path)} for path in paths]


@router.get("/audio/{filename}")
def get_audio(filename: str, rt=Depends(runtime)):
    path = rt.audio.resolve(filename)
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.post("/audio/play")
def play_audio(body: AudioInput, rt=Depends(runtime)):
    return rt.pipeline.diagnostic(State.PLAYING, rt.player.play, body.audio_path)
