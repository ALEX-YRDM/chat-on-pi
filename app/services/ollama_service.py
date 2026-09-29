import logging
import time
import httpx
from ..config import OllamaConfig
from ..errors import ServiceError

logger = logging.getLogger("localchat.ollama")


class OllamaService:
    def __init__(self, config: OllamaConfig):
        self.config = config
        self.client = httpx.Client(base_url=config.base_url, timeout=httpx.Timeout(config.timeout_seconds, connect=5), trust_env=False)

    def chat(self, messages: list[dict[str, str]], model: str | None = None,
             temperature: float | None = None) -> str:
        started = time.monotonic()
        try:
            response = self.client.post("/api/chat", json={
                "model": model or self.config.model, "messages": messages, "stream": False,
                "options": {"temperature": self.config.temperature if temperature is None else temperature},
            })
            response.raise_for_status()
            content = response.json()["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ServiceError("Ollama 返回空回答", 502)
        except httpx.TimeoutException:
            raise ServiceError("Ollama 请求超时，请检查模型或增加 timeout_seconds", 504) from None
        except httpx.HTTPStatusError as exc:
            raise ServiceError(f"Ollama HTTP {exc.response.status_code}，请确认模型已下载", 502) from exc
        except httpx.RequestError as exc:
            raise ServiceError("无法连接 Ollama，请检查后台服务和 Base URL") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise ServiceError("Ollama 返回了无效响应", 502) from exc
        logger.info("Response finished latency=%sms", round((time.monotonic() - started) * 1000))
        return content.strip()

    def close(self) -> None:
        self.client.close()
