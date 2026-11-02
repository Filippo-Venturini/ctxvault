import asyncio

from ctxvault.mcp.server import mcp

# Free-text arguments stay plain `str` with a "" default: with `str | None` the SDK
# JSON-decodes them, so JSON-looking text would be rejected.
FREE_TEXT_PARAMS = {("query_episodes", "query"), ("invalidate_episode", "reason")}


def _tools():
    return asyncio.run(mcp.list_tools())


def _null_default_params():
    for tool in _tools():
        for name, prop in tool.inputSchema.get("properties", {}).items():
            if "default" in prop and prop["default"] is None:
                yield tool, name, prop


def _validate(tool_name, required, arguments):
    # Same steps FastMCP runs on tools/call before the tool function is invoked;
    # nothing here touches a vault.
    metadata = mcp._tool_manager.get_tool(tool_name).fn_metadata
    args = {name: "x" for name in required}
    args.update(arguments)
    return metadata.arg_model.model_validate(metadata.pre_parse_json(args))


class TestToolSchemas:
    def test_params_defaulting_to_none_accept_null(self):
        checked = 0
        for tool, name, prop in _null_default_params():
            types = [option.get("type") for option in prop.get("anyOf", [prop])]
            assert "null" in types, f"{tool.name}.{name} defaults to null but its schema rejects null"
            _validate(tool.name, tool.inputSchema.get("required", []), {name: None})
            checked += 1
        assert checked > 0

    def test_free_text_params_default_to_empty_string(self):
        tools = {tool.name: tool for tool in _tools()}
        for tool_name, name in FREE_TEXT_PARAMS:
            prop = tools[tool_name].inputSchema["properties"][name]
            assert prop.get("type") == "string" and prop.get("default") == "", f"{tool_name}.{name}: {prop}"
            # JSON-looking text stays text instead of being decoded.
            parsed = _validate(tool_name, tools[tool_name].inputSchema.get("required", []), {name: '["Giuseppe"]'})
            assert getattr(parsed, name) == '["Giuseppe"]'

