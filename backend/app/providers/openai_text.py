"""Existing OpenAI implementation retained for TEXT_PROVIDER=openai."""
from ..config import settings
from ..costs import token_cost


def generate(client, system, content, schema, max_output):
    response = client.responses.parse(model=settings.text_model,
        input=[{'role': 'system', 'content': system}, {'role': 'user', 'content': content}],
        text_format=schema, max_output_tokens=max_output, store=False)
    usage = response.usage
    cost = token_cost(usage.input_tokens, usage.output_tokens,
        settings.input_usd_per_million, settings.output_usd_per_million,
        cached_tokens=getattr(getattr(usage, 'input_tokens_details', None), 'cached_tokens', 0) or 0,
        cached_rate=settings.cached_input_usd_per_million,
        reasoning_tokens=getattr(getattr(usage, 'output_tokens_details', None), 'reasoning_tokens', 0) or 0,
        request_id=getattr(response, '_request_id', None))
    # A generated refusal still consumes tokens. Checkpoint it to prevent rebilling.
    if response.output_parsed is None:
        return {'_provider_error': 'Модель не предоставила результат: отказ или незавершённый ответ.'}, cost
    return response.output_parsed.model_dump(), cost
