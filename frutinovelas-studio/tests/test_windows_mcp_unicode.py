import json

import pytest
from mcp.types import JSONRPCResponse
from pydantic import BaseModel, Field, RootModel
from pydantic_core import PydanticSerializationError

from frutinovelas.services.windows_mcp_entry import normalize_unicode, safe_model_dump_json


def test_protocol_message_with_truncated_windows_unicode_does_not_crash_transport():
    text = "UserFLEX · acción " + chr(0xD83C)
    message = RootModel[JSONRPCResponse].model_validate({"jsonrpc": "2.0", "id": 42,
        "result": {"content": [{"type": "text", "text": text}], "isError": False}})
    with pytest.raises(PydanticSerializationError):
        message.model_dump_json(by_alias=True, exclude_unset=True)
    encoded = safe_model_dump_json(message, by_alias=True, exclude_unset=True)
    decoded = json.loads(encoded)
    assert decoded == {"jsonrpc": "2.0", "id": 42, "result": {
        "content": [{"type": "text", "text": "UserFLEX · acción \ufffd"}], "isError": False}}
    # Reparse as the actual MCP envelope, not just generic Python JSON.
    assert RootModel[JSONRPCResponse].model_validate_json(encoded)
    assert message.root.result["content"][0]["text"] == text


def test_normalization_preserves_valid_emoji_literal_text_and_aliases():
    class Message(BaseModel):
        text: str = Field(alias="messageText")
        omitted: str | None = None
    original = Message(messageText="  Literal: acción.\n" + chr(0xD83C) + chr(0xDF4E))
    encoded = safe_model_dump_json(original, by_alias=True, exclude_unset=True)
    assert json.loads(encoded) == {"messageText": "  Literal: acción.\n🍎"}
    assert original.model_fields_set == {"text"}
    assert original.text.endswith(chr(0xD83C) + chr(0xDF4E))
    normal = {"text": "Texto normal con tildes y 🍎", "data": [1, True, None]}
    assert normalize_unicode(normal) is normal


def test_only_the_child_installs_the_serializer_override():
    from frutinovelas.services.windows_mcp_entry import _DUMP_JSON
    assert BaseModel.model_dump_json is _DUMP_JSON
