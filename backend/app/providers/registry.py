"""Text-provider composition. Workflows depend on the same small contract."""
from dataclasses import dataclass
from typing import Callable, Protocol
from pydantic import BaseModel
from ..costs import Cost
from . import gemini, openai_text


class TextGenerator(Protocol):
    def __call__(self, system: str, content: str, schema: type[BaseModel], max_output: int) -> tuple[dict, Cost]: ...


@dataclass(frozen=True)
class TextAdapter:
    provider: str
    model: str
    input_rate: float
    output_rate: float
    generate: TextGenerator


def openai_adapter(settings, client):
    return TextAdapter('openai', settings.text_model, settings.input_usd_per_million,
        settings.output_usd_per_million,
        lambda system, content, schema, maximum: openai_text.generate(client(), system, content, schema, maximum))


def gemini_adapter(settings, client):
    return TextAdapter('gemini', 'gemini/' + settings.gemini_model,
        0 if settings.gemini_free_tier else settings.gemini_input_usd_per_million,
        0 if settings.gemini_free_tier else settings.gemini_output_usd_per_million, gemini.generate)


TEXT_ADAPTERS: dict[str, Callable[..., TextAdapter]] = {'openai': openai_adapter, 'gemini': gemini_adapter}


def text_adapter(settings, client):
    return TEXT_ADAPTERS[settings.text_provider](settings, client)
