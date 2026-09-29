"""Run real TCP HTTP/WS checks with an isolated database and a mock Ollama server.

Run from any working directory: /path/to/.venv/bin/python /path/to/scripts/smoke_http.py
"""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

import httpx
import websockets
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.database import Database
from app.models import Message
from sqlalchemy import select


class OllamaStub(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.reply({"models": [{"name": "qwen2.5:0.5b"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.path == "/api/chat"
        assert body["stream"] is False
        self.calls.append(body["messages"])
        self.reply({"message": {"role": "assistant", "content": "这是一条隔离 HTTP 验收的模拟回答。"}})

    def reply(self, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


async def check_ws(port: int):
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws/status") as connection:
        event = json.loads(await asyncio.wait_for(connection.recv(), 5))
        assert event["state"] == "idle"


def main() -> None:
    mock = ThreadingHTTPServer(("127.0.0.1", 0), OllamaStub)
    thread = threading.Thread(target=mock.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="localchat-smoke-") as directory:
            root = Path(directory)
            config = yaml.safe_load((ROOT / "config.yaml").read_text())
            config["ollama"]["base_url"] = f"http://127.0.0.1:{mock.server_port}"
            config["conversation"]["auto_play_tts"] = False
            config_path = root / "config.yaml"
            config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
            with socket.socket() as candidate:
                candidate.bind(("127.0.0.1", 0))
                port = candidate.getsockname()[1]
            command = [sys.executable, "-c", "from pathlib import Path; import sys, uvicorn; "
                       "from app.main import create_app; "
                       "uvicorn.run(create_app(Path(sys.argv[1]), Path(sys.argv[2])), "
                       "host='127.0.0.1', port=int(sys.argv[3]), log_level='warning')",
                       str(config_path), str(root), str(port)]
            with (root / "server.log").open("w+") as log:
                process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log)
                try:
                    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10, trust_env=False) as client:
                        deadline = time.monotonic() + 15
                        while True:
                            try:
                                response = client.get("/api/health")
                                break
                            except httpx.ConnectError:
                                if process.poll() is not None or time.monotonic() > deadline:
                                    log.seek(0)
                                    raise RuntimeError("Uvicorn did not start:\n" + log.read())
                                time.sleep(.1)
                        assert response.status_code == 200
                        assert response.json()["services"]["database"]
                        assert response.json()["services"]["ollama"]
                        for url in ("/", "/debug", "/settings", "/static/css/style.css", "/static/js/app.js"):
                            assert client.get(url).status_code == 200, url
                        response = client.post("/api/conversations", json={})
                        assert response.status_code == 201
                        conversation_id = response.json()["id"]
                        for message in ("你好", "还记得上一句吗"):
                            response = client.post("/api/chat", json={"conversation_id": conversation_id, "message": message, "synthesize": False})
                            assert response.status_code == 200, response.text
                            assert response.json()["success"]
                        assert len(OllamaStub.calls[-1]) == 4
                        assert len(client.get(f"/api/conversations/{conversation_id}/messages").json()) == 4
                        asyncio.run(check_ws(port))
                        assert client.get("/api/status").status_code == 200
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
            reopened = Database(root / "data/localchat.db")
            try:
                with reopened.session() as session:
                    assert len(session.scalars(select(Message)).all()) == 4
            finally:
                reopened.engine.dispose()
            print("PASS: real Uvicorn + TCP HTTP + WebSocket + pages/static + two-turn chat + SQLite reopen")
            print("Model responses were mocked; no physical hardware or real AI inference was tested.")
    finally:
        mock.shutdown()
        mock.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    main()
