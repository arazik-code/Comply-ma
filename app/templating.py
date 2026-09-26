from datetime import datetime
from pathlib import Path
from fastapi.templating import Jinja2Templates
from app.flash import get_flashed

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["now"] = datetime.now
templates.env.globals["get_flashed"] = get_flashed
