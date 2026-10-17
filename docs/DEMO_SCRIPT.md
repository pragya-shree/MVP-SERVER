# Anything-to-MCP: Hackathon Live Demo Script (5–7 Minutes)

This script provides a structured, verified 5 to 7 minute live demonstration of **Anything-to-MCP**, showcasing the end-to-end flow from OpenAPI specification to running MCP server and safe agent execution.

---

## Pre-Demo Setup & Service Launch

Open three terminal windows at the repository root `D:\MVP`:

### Terminal 1 — Start the FastAPI Backend & Demo Target API
```powershell
.venv\Scripts\Activate.ps1
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```
*Health Check*: Open [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) — returns `{"status":"ok","service":"anything-to-mcp"}`.

### Terminal 2 — Start the Vite Frontend (or use bundled backend static host)
```powershell
cd frontend
npm run dev
```
*Web App URL*: Open [http://localhost:5173](http://localhost:5173).

### Terminal 3 — CLI & Evolution Demo Terminal
Keep this terminal ready in the project root with the virtual environment activated:
```powershell
.venv\Scripts\Activate.ps1
```

---

## Minute-by-Minute Demonstration Walkthrough

### Minute 0:00 – 1:00: Problem & Product Introduction
1. **The Problem**: 
   > "AI agents need to interact with external tools and internal microservices. Today, writing custom MCP servers for dozens of internal APIs is tedious, repetitive, and error-prone. Meanwhile, thousands of engineering teams already have complete OpenAPI specifications."
2. **The Solution**: 
   > "**Anything-to-MCP** automatically turns any standard OpenAPI 3.0 or 3.1 specification into a fully typed, runnable Model Context Protocol (MCP) server utilizing the official Python MCP SDK and stdio transport."
3. **Show Landing Page** on [http://localhost:5173](http://localhost:5173):
   - Highlight the 3-step workflow: Upload API Spec → Generate MCP Tools → Connect MCP Client.
   - Point to the live architecture diagram in the UI.

---

### Minute 1:00 – 2:30: Spec Loading, Validation, & MCP Generation
1. Click **"Open Generator Workspace"** in the top navigation bar.
2. Click **"Try Task Management API Demo"** button:
   - Notice the UI immediately fetches the bundled OpenAPI 3.0 specification from `GET /api/v1/demo/spec` and auto-populates the editor.
3. Click **"Validate Spec"**:
   - Show the real validation response from `POST /api/v1/specs/validate`:
   - Title: `Task Management API` (v1.0.0).
   - 5 parsed operations displayed with color-coded HTTP badges: `GET /tasks`, `POST /tasks`, `GET /tasks/summary`, `GET /tasks/{task_id}`, `DELETE /tasks/{task_id}`.
4. Review Configuration:
   - Point out **Runtime Authentication Guidance**: Explain that secrets belong in `.env` locally, not sent to the web generator.
   - Mention the **Strict Read-Only Mode** toggle (we will demonstrate this shortly).
5. Click **"Generate MCP Server"**:
   - The backend runs `POST /api/v1/servers/generate`.
   - Show the generated result: unique Generation UUID, Package Name (`task_management_mcp`), and Tool Count (5).
6. **Inspect Discovered Tool Schemas**:
   - Expand the tools in the inspector (e.g. `create_task`).
   - Show the generated JSON Schema: required fields `title`, `priority` enum (`low`, `medium`, `high`, `urgent`), and descriptions.
7. Click **"Download ZIP"**:
   - Triggers browser download of the complete package (`task_management_mcp.zip`) containing `server.py`, `pyproject.toml`, `.env.example`, and README.

---

### Minute 2:30 – 4:00: Interactive Agent Playground & Stdio Client
1. Switch to the **"Agent Playground"** tab in the navigation bar.
2. **Point to Live System Status**:
   - Status: `ready` (connected to real backend and in-memory demo data).
   - Seed database contains 4 initial tasks (`pending: 2, in_progress: 1, completed: 1`).
   - Discovered Tools: 5 dynamically discovered tools over stdio (`list_tasks`, `get_task_by_id`, `create_task`, `delete_task`, `list_projects`).
3. **Demonstrate Natural Language Read Query**:
   - Click the prompt chip: *"Show me all pending tasks"*.
   - Click **"Execute via MCP Agent"**.
   - Show the result:
     - Planner selects tool: `list_tasks` with argument `status: "pending"`.
     - Displays formatted response and raw returned JSON.
4. **Demonstrate Task Creation**:
   - Click or paste: *"Create a task called Prepare hackathon live demo with priority urgent"*.
   - Click **"Execute via MCP Agent"**.
   - Show:
     - Planner maps to `create_task`.
     - Tool creates task `t-5` with priority `urgent`.
     - Notice the Status Bar task count immediately increments from 4 to 5!

---

### Minute 4:00 – 5:00: Destructive Action Safeguards
1. **Attempt Unconfirmed Deletion**:
   - Click prompt chip: *"Delete task t-3"*.
   - Click **"Execute via MCP Agent"**.
2. **Show the Safeguard in Action**:
   - The UI displays an amber warning card: **"DESTRUCTIVE ACTION SAFEGUARD ACTIVE"**.
   - Explain:
     > "The MCP Agent identified a destructive action (`delete_task` on task `t-3`). In an enterprise setting, an agent should never delete data or purge databases without explicit confirmation. Notice no tool was executed and task `t-3` remains safe in the database."
3. **Confirm Execution**:
   - Click **"Confirm & Execute Action"**.
   - The agent now executes `delete_task` with `confirm_destructive=True`.
   - Tool returns `204 No Content` / success message.
   - Status Bar task count updates.
4. **Reset Demo Data**:
   - Click **"Reset Demo DB"** in the top bar.
   - Confirm reset: restores seed state back to 4 tasks.

---

### Minute 5:00 – 6:15: Strict Read-Only Mode & Specification Evolution
1. **Explain Strict Read-Only Mode**:
   - Switch back to **Generator Workspace**.
   - Toggle **"Strict Read-Only Mode"** ON.
   - Click **"Generate MCP Server"**.
   - Show: Only GET tools are generated (`list_tasks`, `get_task_by_id`, `get_task_summary`). All mutating operations (`POST`, `DELETE`) are excluded from code generation.
2. **Demonstrate Specification Evolution (Terminal 3)**:
   - Switch to Terminal 3 and run the evolution demonstration script:
     ```powershell
     python scripts/demo_evolution.py
     ```
   - Show the CLI output:
     - Step 1 generates base package.
     - Step 2 configures a secret `API_KEY=live_demo_secret_token_123` in `.env`.
     - Step 3 applies an updated specification (`examples/evolution_updated.yaml`) containing a new endpoint `POST /tasks/{task_id}/archive` and a renamed tool.
     - Step 4 shows the regenerated package: **new tool `archive_task` is present**, and **the existing `API_KEY` was preserved intact without data loss**.

---

### Minute 6:15 – 7:00: Architecture & Wrap-Up
1. **Summary of What Was Built**:
   - OpenAPI 3.0/3.1 Parser & Normalizer with circular `$ref` resolution.
   - Dynamic MCP tool code generator adhering to the official Python MCP SDK.
   - Strict read-only mode for safe, unprivileged tool exposure.
   - Specification evolution preserving local environment configurations.
   - FastAPI Generator & Agent adapter API.
   - React + Tailwind developer workspace and interactive playground.
   - 106 automated tests passing across the backend pipeline.
2. **Future Roadmap**:
   - Remote Server-Sent Events (SSE) transport.
   - Multi-file specification bundling.
   - Pluggable LLM function-calling adapters (Anthropic Claude / OpenAI GPT-4o).
3. **Q&A**: Invite questions from the judges!

---

## Fallback Plan (If Network or Frontend Fails)

If the web UI or browser experiences issues during the presentation, demonstrate the complete flow directly in the terminal via CLI:

### Full CLI Demo Commands
```powershell
# 1. Run full backend test suite to prove 106 tests passing
pytest -q

# 2. Generate an MCP server via CLI
anything-to-mcp generate examples/task_management_api.yaml -o generated/cli_demo_mcp -p cli_demo_mcp

# 3. Generate strict read-only server via CLI
anything-to-mcp generate examples/task_management_api.yaml -o generated/cli_readonly_mcp --read-only

# 4. Run the interactive MCP Agent CLI demo
python demo.py

# 5. Run the specification evolution demo
python scripts/demo_evolution.py
```

---

## Backup Recording Checklist
- [x] Backend running on `http://127.0.0.1:8000`
- [x] Frontend running on `http://localhost:5173`
- [x] Examples folder verified: `examples/task_management_api.yaml` and `examples/evolution_updated.yaml`
- [x] Demo tasks seeded (4 tasks)
- [x] Terminal font size set to 14pt+ for projection readability
- [x] Browser zoomed to 100%–110%
