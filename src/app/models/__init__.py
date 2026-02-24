from ..core.db.database import Base

# import every model so SQLAlchemy registers them onto Base.metadata
from .chat import *           # your existing chat models
