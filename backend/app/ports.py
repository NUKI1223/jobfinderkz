"""Small workflow dependencies implemented by the durable provider gateway."""
from typing import Protocol
from pydantic import BaseModel


class TextPort(Protocol):
    def structured(self, job_id: str, step: str, instruction: str, data: dict, schema: type[BaseModel]) -> BaseModel: ...


class EmbeddingPort(Protocol):
    def embed(self, job_id: str, step: str, text: str) -> list[float]: ...
