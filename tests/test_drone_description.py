import base64
import types
import pytest
import sys

# Import the module under test (new structure)
import drone_tools.drone_description as desc


class _FakeChoice:
    def __init__(self, text):
        # mimic openai response shape: choices[0].message.content
        self.message = types.SimpleNamespace(content=text)


class _FakeCreateAPI:
    def __init__(self, capture):
        self._capture = capture

    def create(self, **kwargs):
        # capture call kwargs to assert later
        self._capture["called"] = True
        self._capture["kwargs"] = kwargs
        return types.SimpleNamespace(choices=[_FakeChoice("Quadcopter")])  # default text


class _FakeChatAPI:
    def __init__(self, capture):
        self.completions = _FakeCreateAPI(capture)


class _FakeClient:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.chat = _FakeChatAPI(_fake_capture)


# Global dict the fake client writes into, re-initialized per test
_fake_capture = {}


@pytest.fixture(autouse=True)
def reset_capture(monkeypatch):
    """
    By default, replace openai.OpenAI with a fake client that returns 'Quadcopter'
    and records call kwargs in _fake_capture.
    """
    global _fake_capture
    _fake_capture = {}

    # Patch openai.OpenAI constructor to our default fake
    import openai
    monkeypatch.setattr(openai, "OpenAI", _FakeClient)
    yield
    _fake_capture = {}


def test_describe_drone_success_with_data_url(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    img = tmp_path / "d.jpg"
    data = b"\xff\xd8\xffTESTJPEG"  # JPEG-like header
    img.write_bytes(data)

    text = desc.describe_drone(str(img), prompt="Identify drone")
    assert text == "Quadcopter"

    # Assert: OpenAI called with expected model, tokens, and message content
    assert _fake_capture.get("called") is True
    kwargs = _fake_capture["kwargs"]
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["max_tokens"] == 100

    # Verify messages structure
    msgs = kwargs["messages"]
    assert isinstance(msgs, list) and msgs[0]["role"] == "user"

    # first content part is text prompt
    parts = msgs[0]["content"]
    assert parts[0]["type"] == "text"
    assert parts[0]["text"] == "Identify drone"

    # second content part is data URL with our base64
    assert parts[1]["type"] == "image_url"
    url = parts[1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    b64 = url.split(",", 1)[1]
    assert base64.b64decode(b64) == data  # exact bytes round-trip


def test_describe_drone_uses_custom_prompt_and_returns_text(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    img = tmp_path / "pic.jpg"
    img.write_bytes(b"abc")

    # Custom create that returns a different response text
    def _custom_create(**kwargs):
        return types.SimpleNamespace(choices=[_FakeChoice("Fixed-wing drone")])

    # IMPORTANT: Override the constructor to return a client instance whose
    # .chat.completions.create is our custom function.
    def _factory(*_, **__):
        client = _FakeClient(api_key="sk-test")
        client.chat.completions.create = _custom_create  # override for this test
        return client

    monkeypatch.setattr(desc.openai, "OpenAI", _factory)

    text = desc.describe_drone(str(img), prompt="Be specific")
    assert text == "Fixed-wing drone"


def test_describe_drone_missing_api_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    img = tmp_path / "x.jpg"
    img.write_bytes(b"z")
    with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
        desc.describe_drone(str(img))


def test_describe_drone_propagates_openai_error(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    img = tmp_path / "x.jpg"
    img.write_bytes(b"z")

    # Force the created client's .create to raise for this test
    def _raise(**kwargs):
        raise RuntimeError("boom")

    def _factory(*_, **__):
        client = _FakeClient(api_key="sk-test")
        client.chat.completions.create = _raise
        return client

    monkeypatch.setattr(desc.openai, "OpenAI", _factory)

    with pytest.raises(RuntimeError, match="boom"):
        desc.describe_drone(str(img))


def test_main_usage_no_args_returns_1(capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # Make the module see no CLI args when it does `argv = argv or sys.argv[1:]`
    monkeypatch.setattr(desc, "sys", types.SimpleNamespace(argv=["prog"]))
    ret = desc.main(None)  # triggers the fallback to sys.argv[1:], which is []
    captured = capsys.readouterr()
    assert ret == 1
    assert "Usage: python drone_description.py <image_path>" in captured.out


def test_main_success_prints_description_and_returns_0(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    img = tmp_path / "img.jpg"
    img.write_bytes(b"\x00\x01")

    # Return a specific string for this test
    def _ok(**kwargs):
        return types.SimpleNamespace(choices=[_FakeChoice("Hexacopter")])

    def _factory(*_, **__):
        client = _FakeClient(api_key="sk-test")
        client.chat.completions.create = _ok
        return client

    monkeypatch.setattr(desc.openai, "OpenAI", _factory)

    ret = desc.main([str(img)])
    captured = capsys.readouterr()
    assert ret == 0
    assert "Hexacopter" in captured.out


def test_main_handles_exception_and_returns_1(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    img = tmp_path / "bad.jpg"
    img.write_bytes(b"xxx")

    def _err(**kwargs):
        raise ValueError("nope")

    def _factory(*_, **__):
        client = _FakeClient(api_key="sk-test")
        client.chat.completions.create = _err
        return client

    monkeypatch.setattr(desc.openai, "OpenAI", _factory)

    ret = desc.main([str(img)])
    captured = capsys.readouterr()
    assert ret == 1
    assert "Error describing drone: nope" in captured.err
