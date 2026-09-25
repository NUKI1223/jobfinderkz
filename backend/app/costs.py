"""Calculation metadata contains no prompts, audio, credentials or personal data."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Cost:
    usd: Decimal
    details: dict


def token_cost(input_tokens, output_tokens, input_rate, output_rate, *, cached_tokens=0,
               cached_rate=None, reasoning_tokens=0, provider='openai', request_id=None):
    if min(input_tokens, output_tokens, cached_tokens, reasoning_tokens) < 0 or cached_tokens > input_tokens:
        raise ValueError('Invalid provider usage')
    cached_rate = input_rate if cached_rate is None else cached_rate
    amount = ((input_tokens - cached_tokens) * Decimal(str(input_rate))
              + cached_tokens * Decimal(str(cached_rate))
              + output_tokens * Decimal(str(output_rate))) / Decimal(1_000_000)
    return Cost(amount, {'method': 'api_tokens', 'provider': provider, 'request_id': request_id,
        'input_tokens': input_tokens, 'cached_input_tokens': cached_tokens,
        'output_tokens': output_tokens, 'reasoning_tokens': reasoning_tokens,
        'rates': {'input_per_million': input_rate, 'cached_input_per_million': cached_rate,
                  'output_per_million': output_rate}, 'currency': 'USD'})
