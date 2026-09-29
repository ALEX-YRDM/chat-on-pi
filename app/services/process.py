"""Bounded subprocess execution; never invoke a shell."""
import logging
import subprocess
from ..errors import ServiceError

logger = logging.getLogger("localchat.process")


def run_command(args: list[str], timeout: float, label: str, **kwargs) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, **kwargs)
    except FileNotFoundError as exc:
        raise ServiceError(f"{label} 可执行文件不存在") from exc
    except subprocess.TimeoutExpired:
        # Do not log command arguments: Piper CLI arguments can contain private text.
        logger.error("%s timed out after %ss", label, timeout)
        raise ServiceError(f"{label} 超时，请检查模型和 timeout_seconds", 504) from None
    except OSError as exc:
        raise ServiceError(f"{label} 无法启动，请检查路径和权限") from exc
    if result.returncode:
        logger.error("%s exited with code %s", label, result.returncode)
        raise ServiceError(f"{label} 执行失败（退出码 {result.returncode}），请在终端单独测试")
    return result
