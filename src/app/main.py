from .api import router
from .core.config import settings
from .core.setup import create_application, lifespan_factory
import uvicorn

app = create_application(router=router, settings=settings, lifespan=lifespan_factory(settings))

if __name__ == "__main__":
    uvicorn.run(app=app, host='0.0.0.0', port=8000)