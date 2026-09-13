import json
from pathlib import Path
import sys

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_real_mcp_stdio_handshake_tools_and_safe_errors(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"OPERATION_MODE=paper\nENABLE_CHAINLINK_FEED=false\nDATABASE_PATH={tmp_path.as_posix()}/protocol.sqlite\n", encoding="utf-8")
    server = Path(__file__).resolve().parents[1] / "run_mcp.py"

    async def check():
        params = StdioServerParameters(command=sys.executable, args=[str(server)],
                                       env={"POLYMARKET_ENV_FILE": str(env)}, cwd=str(tmp_path))
        with anyio.fail_after(30):
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    initialized = await session.initialize()
                    assert "decisión final" in initialized.instructions
                    listing = await session.list_tools()
                    assert len(listing.tools) == 21
                    assert {"get_movements", "set_stop_loss", "get_metrics"} <= {t.name for t in listing.tools}
                    result = await session.call_tool("get_status", {})
                    payload = json.loads(result.content[0].text)
                    assert payload["ok"] and payload["mode"] == "paper"
                    assert payload["data"]["paper_cash_usd"] == "1000"
                    error = await session.call_tool("execute_trade", {"quote_id": "missing", "reason": "test"})
                    assert json.loads(error.content[0].text)["ok"] is False
                    assert error.isError is True
                    assert error.structuredContent["code"] == "QUOTE_NOT_FOUND"
                    prompt = await session.get_prompt("trading_session")
                    assert prompt.messages

    anyio.run(check)
