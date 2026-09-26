from fastapi import Request

FLASH_KEY = "_flash"

def flash(request: Request, message: str, level: str = "success"):
    messages = request.session.get(FLASH_KEY, [])
    messages.append({"message": message, "level": level})
    request.session[FLASH_KEY] = messages

def get_flashed(request: Request):
    return request.session.pop(FLASH_KEY, [])
