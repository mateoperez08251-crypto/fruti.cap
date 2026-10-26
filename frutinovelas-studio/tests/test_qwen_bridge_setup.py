import json

import pytest
from scripts.configurar_qwen_puente import install, update


def test_only_url_and_model_change_and_keep_backup(tmp_path):
    path = tmp_path / "settings/providers.json"
    path.parent.mkdir()
    original = {"providers": {"openai-compatible": {"settings": {
        "apiKey": "preserved-private-key", "baseUrl": "https://qwen.example/v1", "model": "old", "headers": {"custom": "keep"}}}, "other": {"keep": 1}}}
    path.write_text(json.dumps(original))
    raw = path.read_bytes()
    assert install(tmp_path, "https://qwen.example/v1", "http://127.0.0.1:8765/api/v1/qwen/v1", "real") == 1
    result = json.loads(path.read_text())
    settings = result["providers"]["openai-compatible"]["settings"]
    assert settings["apiKey"] == "preserved-private-key"
    assert settings["headers"] == {"custom": "keep"}
    assert result["providers"]["other"] == original["providers"]["other"]
    assert next(path.parent.glob("*.bak")).read_bytes() == raw
    assert install(tmp_path, "https://qwen.example/v1", settings["baseUrl"], "real") == 0


def test_other_provider_is_not_replaced():
    with pytest.raises(ValueError):
        update({"openAiBaseUrl": "https://other.example"}, "global", "https://qwen.example", "http://localhost", "real")


def test_plan_and_act_use_permitted_model_only_for_matching_provider():
    original = {"openAiBaseUrl": "https://qwen.example", "planModeApiProvider": "openai", "actModeApiProvider": "other", "actModeOpenAiModelId": "keep"}
    result = update(original, "global", "https://qwen.example", "http://localhost", "real")
    assert result["planModeOpenAiModelId"] == "real"
    assert result["actModeOpenAiModelId"] == "keep"
    assert original["openAiBaseUrl"] == "https://qwen.example"
