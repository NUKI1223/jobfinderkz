"""Gemini REST adapter: structured JSON, no SDK retries, no key in the URL."""
import httpx
from . import RequestRejected
from ..config import settings


def generate(system, content, schema, max_output):
    body = {
        'systemInstruction': {'parts': [{'text': system}]},
        'contents': [{'role': 'user', 'parts': [{'text': content}]}],
        'generationConfig': {'responseMimeType': 'application/json',
            'responseJsonSchema': schema.model_json_schema(), 'maxOutputTokens': max_output},
    }
    with httpx.Client(timeout=180, follow_redirects=False) as client:
        response = client.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent',
            headers={'x-goog-api-key': settings.gemini_api_key}, json=body)
    if response.status_code in (400, 401, 403, 404, 429):
        messages = {
            400: 'Gemini отклонил параметры запроса. Проверьте модель и поддержку схемы.',
            401: 'Gemini не принял ключ. Проверьте GEMINI_API_KEY.',
            403: 'Gemini запретил доступ. Проверьте ключ, регион и разрешения проекта.',
            404: 'Модель Gemini недоступна. Проверьте GEMINI_MODEL.',
            429: 'Достигнут лимит Gemini. Дождитесь восстановления квоты и нажмите «Продолжить».',
        }
        raise RequestRejected(messages[response.status_code])
    response.raise_for_status()
    data = response.json()
    candidates = data.get('candidates', [])
    if not candidates or candidates[0].get('finishReason') != 'STOP':
        raise ValueError('Gemini не завершил структурированный ответ')
    text = ''.join(part.get('text', '') for part in candidates[0].get('content', {}).get('parts', []) if not part.get('thought'))
    parsed = schema.model_validate_json(text)
    usage = data.get('usageMetadata', {})
    if not settings.gemini_free_tier and ('promptTokenCount' not in usage or 'candidatesTokenCount' not in usage):
        raise ValueError('Gemini не вернул сведения о расходе')
    cost = 0 if settings.gemini_free_tier else (
        usage['promptTokenCount'] * settings.gemini_input_usd_per_million
        + (usage['candidatesTokenCount'] + usage.get('thoughtsTokenCount', 0)) * settings.gemini_output_usd_per_million) / 1e6
    return parsed.model_dump(), cost
