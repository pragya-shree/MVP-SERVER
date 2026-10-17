import React, { useState, useEffect } from 'react';
import { 
  Play, 
  AlertTriangle, 
  RotateCcw, 
  ChevronRight, 
  ChevronDown, 
  Loader2,
  CheckCircle2,
  XCircle,
  ShieldAlert
} from 'lucide-react';
import { api } from '../api/client';
import type { 
  AgentTool, 
  AgentExecuteResponse 
} from '../api/types';

export const AgentPlayground: React.FC = () => {
  // Tools & Loading
  const [tools, setTools] = useState<AgentTool[]>([]);
  const [isLoadingTools, setIsLoadingTools] = useState<boolean>(true);
  const [selectedToolName, setSelectedToolName] = useState<string | null>(null);

  // Prompt & Execution
  const [prompt, setPrompt] = useState<string>('Show me all pending tasks');
  const [isExecuting, setIsExecuting] = useState<boolean>(false);
  const [executionResult, setExecutionResult] = useState<AgentExecuteResponse | null>(null);
  const [executionError, setExecutionError] = useState<string | null>(null);

  // Destructive Confirmation Safeguard
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);

  // Reset State
  const [showResetConfirm, setShowResetConfirm] = useState<boolean>(false);
  const [isResetting, setIsResetting] = useState<boolean>(false);
  const [resetMessage, setResetMessage] = useState<string | null>(null);

  // Load available tools
  const loadTools = async () => {
    setIsLoadingTools(true);
    try {
      const discovered = await api.getAgentTools();
      setTools(discovered);
    } catch (err: any) {
      // Contextual error shown only when operation fails
      setExecutionError(err.message || 'Failed to discover agent tools. Verify backend server is running.');
    } finally {
      setIsLoadingTools(false);
    }
  };

  useEffect(() => {
    loadTools();
  }, []);

  // Execute Prompt
  const handleExecute = async (promptToRun = prompt, confirmDestructive = false) => {
    if (!promptToRun.trim()) return;

    setIsExecuting(true);
    setExecutionError(null);
    setResetMessage(null);

    try {
      const result = await api.executeAgentTask(promptToRun, confirmDestructive);
      setExecutionResult(result);

      if (result.requires_confirmation) {
        setPendingPrompt(promptToRun);
      } else {
        setPendingPrompt(null);
      }
    } catch (err: any) {
      setExecutionError(err.message || 'Agent request failed.');
    } finally {
      setIsExecuting(false);
    }
  };

  // Confirm destructive action
  const handleConfirmDestructive = () => {
    if (pendingPrompt) {
      handleExecute(pendingPrompt, true);
    }
  };

  // Cancel destructive action
  const handleCancelDestructive = () => {
    setPendingPrompt(null);
    setExecutionResult(null);
  };

  // Reset Demo Database
  const handleResetData = async () => {
    setIsResetting(true);
    setResetMessage(null);
    try {
      const res = await api.resetAgentData(true);
      setResetMessage(res.message);
      setShowResetConfirm(false);
      setExecutionResult(null);
      loadTools();
    } catch (err: any) {
      setResetMessage(`Reset failed: ${err.message}`);
    } finally {
      setIsResetting(false);
    }
  };

  const sampleQueries = [
    'Show me all pending tasks',
    'Show the task summary',
    'Create a task called Prepare live demo with priority urgent',
    'Delete task t-3',
  ];

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
      {/* Header */}
      <div className="mb-6 pb-5 border-b border-line flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink tracking-tight">Agent Playground</h1>
          <p className="text-xs text-ink-muted mt-0.5">
            Test natural language execution against discovered MCP tools.
          </p>
        </div>

        {/* Reset Control */}
        <div className="relative">
          {!showResetConfirm ? (
            <button
              onClick={() => setShowResetConfirm(true)}
              className="inline-flex items-center space-x-1.5 text-xs px-2.5 py-1.5 rounded border border-line bg-surface hover:bg-canvas text-ink transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5 text-ink-muted" />
              <span>Reset demo data</span>
            </button>
          ) : (
            <div className="flex items-center space-x-2 bg-surface p-1.5 rounded border border-line shadow-card text-xs">
              <span className="text-ink font-medium">Reset to initial tasks?</span>
              <button
                onClick={handleResetData}
                disabled={isResetting}
                className="px-2 py-0.5 rounded bg-danger hover:bg-danger-hover text-white font-medium text-xs transition-colors"
              >
                {isResetting ? 'Resetting...' : 'Yes, reset'}
              </button>
              <button
                onClick={() => setShowResetConfirm(false)}
                className="px-2 py-0.5 rounded border border-line text-ink hover:bg-canvas text-xs"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>

      {resetMessage && (
        <div className="mb-4 p-2.5 rounded bg-accent-light text-accent border border-accent/20 text-xs font-medium">
          {resetMessage}
        </div>
      )}

      {/* Main Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Input and Execution (7 Cols) */}
        <div className="lg:col-span-7 space-y-4">
          <div className="bg-surface border border-line rounded p-4 space-y-3">
            <label className="block text-xs font-medium text-ink">Task Request</label>

            {/* Input with inline Run Button */}
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                type="text"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handleExecute(prompt, false);
                  }
                }}
                placeholder="e.g. Show me all pending tasks"
                className="flex-1 px-3 py-2 text-xs rounded bg-canvas border border-line text-ink placeholder-ink-subtle focus:bg-surface"
              />
              <button
                onClick={() => handleExecute(prompt, false)}
                disabled={isExecuting || !prompt.trim()}
                className="inline-flex items-center justify-center space-x-1.5 px-4 py-2 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium transition-colors disabled:opacity-50 shrink-0 shadow-card"
              >
                {isExecuting ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Running...</span>
                  </>
                ) : (
                  <>
                    <Play className="w-3.5 h-3.5 fill-white" />
                    <span>Run</span>
                  </>
                )}
              </button>
            </div>

            {/* Suggestions */}
            <div className="flex flex-wrap items-center gap-1.5 pt-1 text-[11px] text-ink-muted">
              <span>Examples:</span>
              {sampleQueries.map((query, idx) => (
                <button
                  key={idx}
                  onClick={() => {
                    setPrompt(query);
                    handleExecute(query, false);
                  }}
                  className="px-2 py-0.5 rounded bg-canvas hover:bg-line/40 text-ink border border-line transition-colors text-left"
                >
                  {query}
                </button>
              ))}
            </div>

            {executionError && (
              <div className="p-3 rounded bg-danger-light border border-danger-border text-danger-text text-xs flex items-start space-x-2">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <div>{executionError}</div>
              </div>
            )}
          </div>

          {/* Destructive Action Confirmation Card */}
          {executionResult?.requires_confirmation && (
            <div className="bg-warn-light border border-warn-border p-4 rounded space-y-2.5">
              <div className="flex items-center space-x-2 text-warn-text font-medium text-xs">
                <ShieldAlert className="w-4 h-4" />
                <span>Confirmation required</span>
              </div>
              <p className="text-xs text-ink leading-relaxed">
                {executionResult.message}
              </p>
              <div className="flex items-center space-x-2 pt-1">
                <button
                  onClick={handleConfirmDestructive}
                  disabled={isExecuting}
                  className="px-3 py-1.5 rounded bg-danger hover:bg-danger-hover text-white text-xs font-medium transition-colors shadow-card"
                >
                  Confirm & Execute
                </button>
                <button
                  onClick={handleCancelDestructive}
                  className="px-3 py-1.5 rounded border border-line bg-surface text-ink text-xs hover:bg-canvas transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Execution Result */}
          {executionResult && !executionResult.requires_confirmation && (
            <div className="bg-surface border border-line rounded p-4 space-y-3">
              <div className="flex items-center justify-between pb-2 border-b border-line text-xs">
                <div className="flex items-center space-x-1.5 font-medium">
                  {executionResult.success ? (
                    <>
                      <CheckCircle2 className="w-4 h-4 text-accent" />
                      <span className="text-ink">Execution Succeeded</span>
                    </>
                  ) : (
                    <>
                      <XCircle className="w-4 h-4 text-danger" />
                      <span className="text-danger-text">Execution Error</span>
                    </>
                  )}
                </div>

                {executionResult.tool_invocations?.length > 0 && (
                  <span className="text-[11px] font-mono text-ink-muted">
                    tool: {executionResult.tool_invocations[0].tool_name}
                  </span>
                )}
              </div>

              {/* Agent Message */}
              <div className="text-xs text-ink leading-relaxed">
                {executionResult.message}
              </div>

              {/* Invocations and Arguments */}
              {executionResult.tool_invocations?.length > 0 && (
                <div className="space-y-2 pt-1 border-t border-line text-xs">
                  {executionResult.tool_invocations.map((inv, idx) => (
                    <div key={idx} className="space-y-1.5 font-mono text-[11px]">
                      {inv.arguments && Object.keys(inv.arguments).length > 0 && (
                        <div>
                          <span className="text-ink-muted block text-[10px] uppercase">Arguments:</span>
                          <pre className="p-2 rounded bg-canvas border border-line text-ink overflow-x-auto">
                            {JSON.stringify(inv.arguments, null, 2)}
                          </pre>
                        </div>
                      )}

                      {inv.response && (
                        <div>
                          <span className="text-ink-muted block text-[10px] uppercase">Response Payload:</span>
                          <pre className="p-2 rounded bg-canvas border border-line text-ink overflow-x-auto max-h-48">
                            {JSON.stringify(inv.response, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Column: Available MCP Tools (5 Cols) */}
        <div className="lg:col-span-5 space-y-3">
          <div className="bg-surface border border-line rounded p-4 space-y-3">
            <div className="flex items-center justify-between pb-2 border-b border-line">
              <span className="text-xs font-medium text-ink uppercase tracking-wider">
                Discovered Tools ({tools.length})
              </span>
              {isLoadingTools && <Loader2 className="w-3 h-3 animate-spin text-ink-muted" />}
            </div>

            {tools.length === 0 ? (
              <div className="text-xs text-ink-muted py-2">
                {isLoadingTools ? 'Discovering tools via stdio...' : 'No tools available.'}
              </div>
            ) : (
              <div className="space-y-1 max-h-[500px] overflow-y-auto pr-0.5">
                {tools.map((tool) => {
                  const isExpanded = selectedToolName === tool.name;
                  return (
                    <div
                      key={tool.name}
                      className="border border-line rounded bg-canvas overflow-hidden text-xs"
                    >
                      <div
                        onClick={() => setSelectedToolName(isExpanded ? null : tool.name)}
                        className="p-2 flex items-center justify-between cursor-pointer hover:bg-surface transition-colors"
                      >
                        <div className="font-mono font-medium text-ink truncate pr-2">
                          {tool.name}
                        </div>
                        {isExpanded ? (
                          <ChevronDown className="w-3.5 h-3.5 text-ink-muted shrink-0" />
                        ) : (
                          <ChevronRight className="w-3.5 h-3.5 text-ink-muted shrink-0" />
                        )}
                      </div>

                      {isExpanded && (
                        <div className="p-2.5 border-t border-line bg-surface space-y-2 text-xs">
                          {tool.description && (
                            <p className="text-ink-muted leading-relaxed">{tool.description}</p>
                          )}

                          {tool.input_schema?.properties && (
                            <div>
                              <span className="text-[10px] font-mono text-ink-muted block mb-1 uppercase">Parameters:</span>
                              <div className="flex flex-wrap gap-1 font-mono text-[10px]">
                                {Object.entries(tool.input_schema.properties).map(([name, schema]: [string, any]) => (
                                  <span key={name} className="px-1.5 py-0.5 rounded bg-canvas border border-line text-ink">
                                    {name}: {schema?.type || 'any'}
                                    {tool.input_schema.required?.includes(name) && <span className="text-danger ml-0.5">*</span>}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}

                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              const query = tool.name === 'list_tasks' ? 'Show all tasks'
                                : tool.name === 'get_task_by_id' ? 'Find task t-1'
                                : tool.name === 'delete_task' ? 'Delete task t-3'
                                : `Run ${tool.name}`;
                              setPrompt(query);
                            }}
                            className="text-[11px] text-accent hover:underline font-medium pt-1 block"
                          >
                            Use in prompt
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
