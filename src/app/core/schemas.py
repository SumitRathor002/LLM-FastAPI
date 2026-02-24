
from pydantic import BaseModel
from enum import Enum
from uuid import UUID

class HealthCheck(BaseModel):
    status: str
    environment: str
    version: str
    timestamp: str


class ReadyCheck(BaseModel):
    status: str
    environment: str
    version: str
    app: str
    database: str
    redis: str
    timestamp: str

