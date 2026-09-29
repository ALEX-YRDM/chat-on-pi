from fastapi import Request


def runtime(request: Request):
    return request.app.state.runtime
