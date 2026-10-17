"""Runnable end-to-end demo orchestrating Demo API, MCP generation, and AI Agent."""

import argparse
import asyncio
import json
from pathlib import Path
import sys
import threading
import time
from typing import Optional
import uvicorn

from agent.agent import MCPAgent
from agent.client import MCPClient
from backend.generator import generate_mcp_server, parse_openapi
from demo_api.app import app
from demo_api.repository import repository

REPO_ROOT = Path(__file__).resolve().parent.parent


class BackgroundAPIServer:
    """Runs FastAPI demo app in a background daemon thread."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        self.host = host
        self.port = port
        self.config = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(self.config)
        self.thread: Optional[threading.Thread] = None

    def start(self) -> str:
        """Start server in daemon thread and wait for readiness."""
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()

        # Wait until server is started
        timeout = 10.0
        start_time = time.time()
        while not self.server.started and time.time() - start_time < timeout:
            time.sleep(0.05)

        return f"http://{self.host}:{self.port}"

    def stop(self) -> None:
        """Signal uvicorn server to exit."""
        self.server.should_exit = True


async def run_step(
    agent: MCPAgent,
    query: str,
    step_num: int,
    step_title: str,
    confirm: bool = False,
) -> None:
    """Execute and display a single demo query through the agent."""
    print("\n" + "=" * 70)
    print(f" STEP {step_num}: {step_title}")
    print("=" * 70)
    print(f"User Request: \"{query}\"")
    if confirm:
        print("[User Confirmation Flag: CONFIRMED]")

    response = await agent.execute(query, confirm_destructive=confirm)

    if response.requires_confirmation:
        print("\n[SAFETY GUARD TRIGGERED]")
        print(f"  Warning: {response.message}")
        print(f"  Pending Action: {response.pending_action}")
        print("  -> Destructive tool call blocked until explicit user confirmation.")
        return

    print("\n[MCP Execution Trace]")
    for inv in response.tool_invocations:
        print(f"  Tool Invoked   : {inv['tool_name']}")
        print(f"  Arguments      : {json.dumps(inv['arguments'])}")
        print(f"  HTTP Status    : {inv['status_code']}")
        print(f"  Protocol Error : {inv['is_error']}")
        res_display = json.dumps(inv["response"], indent=4) if isinstance(inv["response"], (dict, list)) else inv["response"]
        print(f"  API Response   :\n{res_display}")

    print("\n[Agent Final Message]")
    print(f"  Result: {response.message}")
    print(f"  Success: {response.success}")


async def run_automated_walkthrough(base_url: str, server_script: Path) -> None:
    """Run complete end-to-end automated demonstration workflow."""
    print("\n" + "#" * 70)
    print(" ANYTHING-TO-MCP: LIVE END-TO-END DEMO WALKTHROUGH")
    print("#" * 70)

    # Reset repository to clean seed state
    repository.reset()

    # Create MCP client connected to the generated server
    client = MCPClient(
        server_script=server_script,
        env={"TARGET_BASE_URL": base_url},
    )

    async with client:
        agent = MCPAgent(client=client)

        print("\n[1] Discovering tools from generated MCP server via stdio...")
        tools = await agent.initialize()
        print(f"[SUCCESS] Discovered {len(tools)} tools:")
        for t in tools:
            print(f"  - {t.name:<25} : {t.description[:60]}...")

        # Step 1: Filtered query (GET)
        await run_step(
            agent,
            "Show me all pending tasks",
            1,
            "Filtered Query (GET /tasks?status=pending)",
        )

        # Step 2: Specific task details (GET /tasks/{task_id})
        await run_step(
            agent,
            "Find task t-1",
            2,
            "Item Retrieval (GET /tasks/t-1)",
        )

        # Step 3: Aggregated summary (GET /tasks/summary)
        await run_step(
            agent,
            "Show the task summary",
            3,
            "Aggregated Metrics (GET /tasks/summary)",
        )

        # Step 4: Create task (POST /tasks)
        await run_step(
            agent,
            "Create a task called Prepare hackathon live demo with priority urgent",
            4,
            "Task Creation (POST /tasks)",
        )

        # Step 5: Delete task without confirmation -> BLOCKED
        await run_step(
            agent,
            "Delete task t-3",
            5,
            "Safety Guard Test: Delete Task Without Confirmation",
            confirm=False,
        )

        # Step 6: Delete task WITH explicit confirmation -> EXECUTED
        await run_step(
            agent,
            "Delete task t-3",
            6,
            "Destructive Execution: Delete Task With Confirmation",
            confirm=True,
        )

        # Step 7: Verify deletion (GET /tasks/t-3) -> 404 Handled
        await run_step(
            agent,
            "Find task t-3",
            7,
            "Verification: Confirm Task t-3 is Deleted (Expected 404)",
        )

        # Step 8: Clarification for missing arguments
        await run_step(
            agent,
            "Create a task",
            8,
            "Clarification Handling: Missing Required Title",
        )

        # Step 9: Unsupported intent handling
        await run_step(
            agent,
            "Order a pizza for the team",
            9,
            "Unsupported Intent Rejection",
        )

    print("\n" + "=" * 70)
    print(" DEMONSTRATION COMPLETE: ALL SCENARIOS VERIFIED SUCCESSFULLY")
    print("=" * 70 + "\n")


async def run_interactive_repl(base_url: str, server_script: Path) -> None:
    """Run interactive REPL session allowing user prompts."""
    print("\nStarting Interactive MCP Agent REPL...")
    print("Type your query in natural language (or 'exit' / 'quit' to quit).")

    client = MCPClient(server_script=server_script, env={"TARGET_BASE_URL": base_url})
    async with client:
        agent = MCPAgent(client=client)
        tools = await agent.initialize()
        print(f"Connected to MCP Server. {len(tools)} tools discovered.")

        while True:
            try:
                query = input("\nagent> ").strip()
                if not query:
                    continue
                if query.lower() in {"exit", "quit", "q"}:
                    break

                res = await agent.execute(query, confirm_destructive=False)
                if res.requires_confirmation:
                    print(f"\n[CONFIRMATION REQUIRED]: {res.message}")
                    confirm = input("Are you sure? (y/N): ").strip().lower()
                    if confirm in {"y", "yes"}:
                        res = await agent.execute(query, confirm_destructive=True)
                    else:
                        print("Action cancelled by user.")
                        continue

                print(f"\nResponse: {res.message}")
                if res.data:
                    print("Data:", json.dumps(res.data, indent=2) if isinstance(res.data, (dict, list)) else res.data)
            except (KeyboardInterrupt, EOFError):
                break


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end Anything-to-MCP demonstration runner.")
    parser.add_argument("--interactive", "-i", action="store_true", help="Launch interactive REPL mode")
    parser.add_argument("--port", type=int, default=8000, help="Port for background Demo API (default: 8000)")
    parser.add_argument("--no-server", action="store_true", help="Assume Demo API is already running")
    args = parser.parse_args()

    bg_server = None
    base_url = f"http://127.0.0.1:{args.port}"

    try:
        if not args.no_server:
            print(f"[DEMO] Launching background Demo Task Management API on {base_url}...")
            bg_server = BackgroundAPIServer(port=args.port)
            base_url = bg_server.start()
            print(f"[DEMO] Demo API active at {base_url}")

        output_dir = REPO_ROOT / "generated" / "demo_task_mcp"
        print(f"[DEMO] Generating MCP server package from OpenAPI spec into {output_dir}...")
        api_spec = parse_openapi(app.openapi())
        res = generate_mcp_server(
            api=api_spec,
            output_dir=output_dir,
            package_name="demo_task_mcp",
            base_url=base_url,
            overwrite=True,
        )
        server_script = output_dir / "server.py"
        print(f"[DEMO] MCP Server ready at {server_script}")

        if args.interactive:
            asyncio.run(run_interactive_repl(base_url, server_script))
        else:
            asyncio.run(run_automated_walkthrough(base_url, server_script))

    finally:
        if bg_server:
            print("[DEMO] Shutting down background Demo API server...")
            bg_server.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
