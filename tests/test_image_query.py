import types
import pytest

import drone_tools.image_query as iq


class _FakeImageData:
    def __init__(self, url):
        self.url = url


class _FakeImagesAPI:
    def __init__(self, capture):
        self._capture = capture

    def generate(self, **kwargs):
        self._capture["called"] = True
        self._capture["kwargs"] = kwargs
        urls = self._capture.get("urls", ["https://example.com/img1.png"])
        return types.SimpleNamespace(data=[_FakeImageData(u) for u in urls])


class _FakeClient:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.images = _FakeImagesAPI(_fake_capture)


_fake_capture = {}


@pytest.fixture(autouse=True)
def reset_capture(monkeypatch):
    global _fake_capture
    _fake_capture = {}
    import openai
    monkeypatch.setattr(openai, "OpenAI", _FakeClient)
    yield
    _fake_capture = {}


def test_query_image_returns_urls(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    urls = iq.query_image("a drone flying")
    assert urls == ["https://example.com/img1.png"]
    assert _fake_capture["called"] is True
    assert _fake_capture["kwargs"]["prompt"] == "a drone flying"
    assert _fake_capture["kwargs"]["n"] == 1
    assert _fake_capture["kwargs"]["size"] == "1024x1024"


def test_query_image_custom_params(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    _fake_capture["urls"] = ["https://example.com/a.png", "https://example.com/b.png"]
    urls = iq.query_image("two drones", n=2, size="512x512")
    assert len(urls) == 2
    assert _fake_capture["kwargs"]["n"] == 2
    assert _fake_capture["kwargs"]["size"] == "512x512"


def test_query_image_missing_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
        iq.query_image("test")


def test_main_no_args_returns_1(capsys, monkeypatch):
    monkeypatch.setattr(iq, "sys", types.SimpleNamespace(argv=["prog"], stderr=iq.sys.stderr))
    ret = iq.main(None)
    captured = capsys.readouterr()
    assert ret == 1
    assert "Usage" in captured.out


def test_main_success_prints_urls(capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    ret = iq.main(["a", "cool", "drone"])
    captured = capsys.readouterr()
    assert ret == 0
    assert "https://example.com/img1.png" in captured.out
    assert _fake_capture["kwargs"]["prompt"] == "a cool drone"


def test_main_error_returns_1(capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def _boom(**kwargs):
        raise RuntimeError("api down")

    def _factory(*_, **__):
        client = _FakeClient(api_key="sk-test")
        client.images.generate = _boom
        return client

    monkeypatch.setattr(iq.openai, "OpenAI", _factory)

    ret = iq.main(["test prompt"])
    captured = capsys.readouterr()
    assert ret == 1
    assert "api down" in captured.err
