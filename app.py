"""
Mac Studio MCP Server
Wraps the Tailscale Funnel endpoint as an MCP-compatible server
"""

import os
import json
import httpx
from flask import Flask, request, jsonify
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

MAC_FUNNEL_URL = os.environ.get("MAC_FUNNEL_URL", "https://mac-studio-1556.tailfb6577.ts.net")

TOOLS = [
    {
        "name": "run_command",
        "description": "Execute a shell command on Mac Studio. Returns stdout, stderr, and return code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute (e.g., 'ls -la', 'brew list', 'python3 script.py')"
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "ssh_to_pi",
        "description": "Execute a command on Raspberry Pi via SSH from Mac Studio",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Command to run on the Pi"
                },
                "host": {
                    "type": "string",
                    "description": "Pi IP address (default: 192.168.25.225)"
                },
                "user": {
                    "type": "string",
                    "description": "SSH user (default: jstewartrr)"
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "health_check",
        "description": "Check if Mac Studio is reachable and get system info",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "list_files",
        "description": "List files in a directory on Mac Studio",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path (default: home directory)"
                }
            },
            "required": []
        }
    },
    {
        "name": "read_file",
        "description": "Read contents of a file on Mac Studio",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Full path to file"
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines to read (default: all). Use negative for tail."
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Write content to a file on Mac Studio",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Full path to file"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write"
                },
                "append": {
                    "type": "boolean",
                    "description": "Append instead of overwrite (default: false)"
                }
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "get_system_info",
        "description": "Get Mac Studio system information (CPU, memory, disk, processes)",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]

async def call_mac(endpoint: str, method: str = "GET", data: dict = None):
    """Call the Mac Funnel endpoint"""
    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        url = f"{MAC_FUNNEL_URL}{endpoint}"
        if method == "GET":
            response = await client.get(url)
        else:
            response = await client.post(url, json=data)
        return response.json()

def run_async(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

def handle_tool_call(name: str, arguments: dict):
    """Handle MCP tool calls"""
    try:
        if name == "run_command":
            result = run_async(call_mac("/run", "POST", {"command": arguments["command"]}))
            return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
        
        elif name == "ssh_to_pi":
            data = {
                "command": arguments["command"],
                "host": arguments.get("host", "192.168.25.225"),
                "user": arguments.get("user", "jstewartrr")
            }
            result = run_async(call_mac("/ssh", "POST", data))
            return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
        
        elif name == "health_check":
            result = run_async(call_mac("/health", "GET"))
            return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
        
        elif name == "list_files":
            path = arguments.get("path", "~")
            cmd = f"ls -la {path}"
            result = run_async(call_mac("/run", "POST", {"command": cmd}))
            return {"content": [{"type": "text", "text": result.get("stdout", result.get("error", str(result)))}]}
        
        elif name == "read_file":
            path = arguments["path"]
            lines = arguments.get("lines")
            if lines:
                if lines < 0:
                    cmd = f"tail -n {abs(lines)} '{path}'"
                else:
                    cmd = f"head -n {lines} '{path}'"
            else:
                cmd = f"cat '{path}'"
            result = run_async(call_mac("/run", "POST", {"command": cmd}))
            return {"content": [{"type": "text", "text": result.get("stdout", result.get("error", str(result)))}]}
        
        elif name == "write_file":
            path = arguments["path"]
            content = arguments["content"]
            append = arguments.get("append", False)
            
            # Escape content for shell
            escaped = content.replace("'", "'\\''")
            op = ">>" if append else ">"
            cmd = f"echo '{escaped}' {op} '{path}'"
            result = run_async(call_mac("/run", "POST", {"command": cmd}))
            
            if result.get("returncode", 1) == 0:
                return {"content": [{"type": "text", "text": f"Successfully wrote to {path}"}]}
            return {"content": [{"type": "text", "text": f"Error: {result.get('stderr', str(result))}"}], "isError": True}
        
        elif name == "get_system_info":
            cmd = """echo '=== HOSTNAME ===' && hostname && \
echo '=== UPTIME ===' && uptime && \
echo '=== CPU ===' && sysctl -n machdep.cpu.brand_string && \
echo '=== MEMORY ===' && vm_stat | head -5 && \
echo '=== DISK ===' && df -h / && \
echo '=== TOP PROCESSES ===' && ps aux | head -10"""
            result = run_async(call_mac("/run", "POST", {"command": cmd}))
            return {"content": [{"type": "text", "text": result.get("stdout", result.get("error", str(result)))}]}
        
        else:
            return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
    
    except Exception as e:
        logger.error(f"Tool call error: {e}")
        return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

def process_mcp_message(data):
    method = data.get("method", "")
    params = data.get("params", {})
    request_id = data.get("id", 1)
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "mac-studio-mcp", "version": "1.0.0"}
            }
        }
    
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": TOOLS}
        }
    
    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result = handle_tool_call(tool_name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result
        }
    
    elif method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }

@app.route("/", methods=["GET"])
def health():
    # Also check if Mac is reachable
    try:
        result = run_async(call_mac("/health", "GET"))
        mac_status = "connected" if result.get("status") == "ok" else "error"
    except:
        mac_status = "unreachable"
    
    return jsonify({
        "status": "healthy",
        "service": "mac-studio-mcp",
        "version": "1.0.0",
        "mac_funnel_url": MAC_FUNNEL_URL,
        "mac_status": mac_status,
        "tools": len(TOOLS)
    })

@app.route("/mcp", methods=["POST"])
def mcp_handler():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}), 400
        response = process_mcp_message(data)
        return jsonify(response)
    except Exception as e:
        logger.error(f"MCP handler error: {e}")
        return jsonify({"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": str(e)}}), 500

if __name__ == "__main__":
    logger.info("Mac Studio MCP Server starting...")
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
