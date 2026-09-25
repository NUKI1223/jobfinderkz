"""Existing OpenAI implementation retained for TEXT_PROVIDER=openai."""
from ..config import settings


def generate(client, system, content, schema, max_output):
    response = client.responses.parse(model=settings.text_model,
        input=[{'role': 'system', 'content': system}, {'role': 'user', 'content': content}],
        text_format=schema, max_output_tokens=max_output, store=False)
    if response.output_parsed is None:
        raise ValueError('Модель не вернула проверенный ответ')
    cost = (response.usage.input_tokens * settings.input_usd_per_million
            + response.usage.output_tokens * settings.output_usd_per_million) / 1e6
    return response.output_parsed.model_dump(), cost
