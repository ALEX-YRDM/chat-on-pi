from app.config import ConfigStore, ROOT
import os
from pathlib import Path
import uvicorn

if __name__ == "__main__":
    config = ConfigStore(Path(os.environ.get("LOCALCHAT_CONFIG", ROOT / "config.yaml"))).active
    uvicorn.run("app.main:app", host=config.app.host, port=config.app.port, workers=1)
