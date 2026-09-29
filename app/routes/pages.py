from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from ..config import ROOT

router = APIRouter()
templates = Jinja2Templates(directory=str(ROOT / "templates"))


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"page": "chat"})


@router.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    return templates.TemplateResponse(request=request, name="settings.html", context={"page": "settings"})


@router.get("/debug", response_class=HTMLResponse)
def debug(request: Request):
    return templates.TemplateResponse(request=request, name="debug.html", context={"page": "debug"})
