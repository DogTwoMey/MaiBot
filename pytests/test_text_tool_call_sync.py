import pytest

from src.llm_models.text_tool_call import TextToolCallError, parse_text_tool_calls


SCHEMAS = {"reply": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"], "additionalProperties": False}}


def test_text_tool_call_keeps_plain_text_and_validates_schema():
    result = parse_text_tool_calls('prefix <reply>{"content":"hello"}</reply> suffix', SCHEMAS)
    assert result.text == "prefix  suffix"
    assert len(result.calls) == 1
    assert result.calls[0].name == "reply"
    assert result.calls[0].arguments == {"content": "hello"}


def test_text_tool_call_keeps_code_quotes():
    text = '`<reply>{"content":"hello"}</reply>`'
    result = parse_text_tool_calls(text, SCHEMAS)
    assert result.text == text
    assert not result.calls


@pytest.mark.parametrize("text", [
    '<reply>{"content":42}</reply>',
    '<reply>{}</reply>',
    '<reply>{"content":"hello"}',
    '<invoke name="unavailable"><parameter name="content">hello</parameter></invoke>',
])
def test_text_tool_call_rejects_invalid_and_unavailable_tools(text):
    with pytest.raises(TextToolCallError):
        parse_text_tool_calls(text, SCHEMAS)
