import asyncio

from codegraph_mcp.mcp.tools import TOOL_REGISTRY

async def run_stdio_server() -> None:
    """Minimal JSON-RPC over stdio loop (placeholder)."""
    import sys, json
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        req = json.loads(line)
        method = req.get("method")
        params = req.get("params", {})
        req_id = req.get("id")

        try:
            handler = TOOL_REGISTRY[method]
            result = await handler(**params)
            resp = {"jsonrpc":"2.0","id":req_id,"result":result}
        except Exception as e:
            resp = {"jsonrpc":"2.0","id":req_id,"error":{"code":-32000,"message":str(e)}}

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()

def main() -> None:
    asyncio.run(run_stdio_server())

if __name__ == "__main__":
    main()
