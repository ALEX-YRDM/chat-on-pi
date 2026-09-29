"""Basic LAN browser protection without a login or an authentication system."""
from urllib.parse import urlparse
from starlette.responses import JSONResponse
from starlette.datastructures import Headers


class LocalAPIMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            origin = headers.get("origin")
            if (origin and urlparse(origin).netloc != headers.get("host")) or headers.get("sec-fetch-site") == "cross-site":
                return await JSONResponse({"detail": "拒绝跨站修改请求"}, status_code=403)(scope, receive, send)
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > 128 * 1024:
                    return await JSONResponse({"detail": "请求体超过 128 KB"}, status_code=413)(scope, receive, send)
                if not message.get("more_body", False):
                    break
            if body and headers.get("content-type", "").split(";")[0] != "application/json":
                return await JSONResponse({"detail": "请求需要 application/json"}, status_code=415)(scope, receive, send)
            consumed = False

            async def replay():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            return await self.app(scope, replay, send)
        await self.app(scope, receive, send)
