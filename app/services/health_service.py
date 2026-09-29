import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import httpx
from sqlalchemy import text

logger = logging.getLogger("localchat.health")


def microphone_check(device: str) -> tuple[bool, str]:
    executable = shutil.which("arecord")
    if not executable:
        return False, "未安装 arecord / alsa-utils"
    try:
        # Enumeration only: does not open/capture from the microphone.
        numeric = re.fullmatch(r"(?:plug)?hw:(\d+),(\d+)", device)
        listing = subprocess.run([executable, "-l" if numeric else "-L"],
                                 capture_output=True, text=True, timeout=3,
                                 env={**os.environ, "LC_ALL": "C"})
        if numeric:
            card, number = numeric.groups()
            available = bool(re.search(rf"card {card}:.*device {number}:", listing.stdout))
        else:
            available = device in [line.strip() for line in listing.stdout.splitlines() if line and not line[0].isspace()]
        ok = listing.returncode == 0 and available
        return ok, ("设备已枚举；实际录音请执行 Microphone Test" if ok else "设备未枚举，请用 arecord -l / -L 检查配置")
    except (OSError, subprocess.TimeoutExpired):
        return False, "无法枚举 ALSA 设备或查询超时"


def health_report(runtime) -> dict:
    config = runtime.config.active
    mic_ok, mic_detail = microphone_check(config.audio.input_device)
    services = {
        "microphone": mic_ok,
        "speaker": shutil.which("aplay") is not None,
        "whisper": (Path(config.whisper.executable).is_file() and os.access(config.whisper.executable, os.X_OK)
                    and Path(config.whisper.model).is_file()),
        "ollama": False,
        "piper": bool(runtime.piper.ready),
        "database": False,
    }
    details = {"microphone": mic_detail, "piper": runtime.piper.error or "API 模型已加载",
               "speaker": "仅检查 aplay 存在；请使用 Play on Raspberry Pi 测试播放",
               "whisper": "仅检查 executable 权限和模型文件；请执行 Transcribe 测试"}
    try:
        response = httpx.get(config.ollama.base_url + "/api/tags", timeout=2, trust_env=False)
        response.raise_for_status()
        models = [m["name"] for m in response.json()["models"]]
        services["ollama"] = True
        details["ollama"] = {"models": models, "configured_model_available": config.ollama.model in models}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        details["ollama"] = "API 不可达或响应无效"
    try:
        with runtime.db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        services["database"] = True
    except Exception:
        logger.exception("Database health check failed")
        details["database"] = "数据库检查失败，请查看日志"
    return {"status": "ok" if all(services.values()) else "degraded", "services": services, "details": details}
