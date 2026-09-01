import asyncio

from services import ai_service


class RecordingOpenRouterProvider:
    """Test double that records constructor arguments without opening a network session."""

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model


class FakeResponse:
    status = 200

    async def json(self):
        return {
            'choices': [{'message': {'content': 'fake reply'}}],
            'model': 'z-ai/glm-5.2:free',
        }


class FakePostContext:
    async def __aenter__(self):
        return FakeResponse()

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSession:
    def __init__(self):
        self.payload = None

    def post(self, url, *, headers, json):
        self.payload = json
        return FakePostContext()


def test_create_provider_passes_configured_openrouter_model(monkeypatch):
    monkeypatch.setitem(ai_service.settings, 'AI_PROVIDER', 'openrouter')
    monkeypatch.setitem(ai_service.settings, 'OPENROUTER_MODEL', 'z-ai/glm-5.2:free')
    monkeypatch.setattr(ai_service, 'OpenRouterProvider', RecordingOpenRouterProvider)

    provider = ai_service.create_provider()

    assert provider.api_key == ai_service.OPENROUTER_API_KEY
    assert provider.model == 'z-ai/glm-5.2:free'


def test_create_provider_defaults_to_openrouter_free(monkeypatch):
    monkeypatch.setitem(ai_service.settings, 'AI_PROVIDER', 'openrouter')
    monkeypatch.delitem(ai_service.settings, 'OPENROUTER_MODEL', raising=False)
    monkeypatch.setattr(ai_service, 'OpenRouterProvider', RecordingOpenRouterProvider)

    provider = ai_service.create_provider()

    assert provider.model == 'openrouter/free'


def test_openrouter_call_sends_provider_model_in_payload():
    provider = ai_service.OpenRouterProvider('fake-key', 'z-ai/glm-5.2:free')
    fake_session = FakeSession()
    provider.session = fake_session

    reply, actual_model = asyncio.run(
        provider.call([{'role': 'user', 'content': 'hello'}])
    )

    assert fake_session.payload['model'] == provider.model
    assert reply == 'fake reply'
    assert actual_model == 'z-ai/glm-5.2:free'
