import React, { useState, useEffect } from 'react';
import { 
  Play, 
  AlertTriangle, 
  RotateCcw, 
  ChevronRight, 
  ChevronDown, 
  Loader2,
  ShieldAlert,
  ShieldCheck,
  Eye,
  EyeOff,
  Clock,
  History,
  Check,
  X
} from 'lucide-react';
import { api } from '../api/client';
import type { 
  AgentTool, 
  AgentExecuteResponse,
  SecurityConfig,
  ApprovalRequestItem,
  AuditLogEntry 
} from '../api/types';

export const AgentPlayground: React.FC = () => {
  // Tools & Loading
  const [tools, setTools] = useState<AgentTool[]>([]);
  const [isLoadingTools, setIsLoadingTools] = useState<boolean>(true);
  const [selectedToolName, setSelectedToolName] = useState<string | null>(null);

  // Security Guardrails State
  const [secConfig, setSecConfig] = useState<SecurityConfig>({
    dry_run: false,
    require_approval: false,
    mask_secrets: true,
    denied_operations: [],
    denied_methods: [],
    active_policy: 'GUARDRAILS ACTIVE',
  });
  const [isUpdatingConfig, setIsUpdatingConfig] = useState<boolean>(false);
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalRequestItem[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);
  const [showAuditHistory, setShowAuditHistory] = useState<boolean>(true);

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

  // Load available tools and security state
  const loadTools = async (retryCount = 0) => {
    setIsLoadingTools(true);
    try {
      const discovered = await api.getAgentTools();
      setTools(discovered);
      setExecutionError(null);
    } catch (err: any) {
      if (retryCount < 2) {
        setTimeout(() => loadTools(retryCount + 1), 1500);
      } else {
        setExecutionError(err.message || 'Failed to discover agent tools. Verify backend server is running.');
      }
    } finally {
      setIsLoadingTools(false);
    }
  };

  const loadSecurityState = async () => {
    try {
      const [config, approvals, audit] = await Promise.all([
        api.getSecurityConfig(),
        api.getApprovals(),
        api.getAuditLog(20),
      ]);
      setSecConfig(config);
      setPendingApprovals(approvals.filter(a => a.status === 'PENDING'));
      setAuditLogs(audit);
    } catch {
      // Non-blocking security state load
    }
  };

  useEffect(() => {
    loadTools();
    loadSecurityState();
    const interval = setInterval(loadSecurityState, 5000);
    return () => clearInterval(interval);
  }, []);

  // Toggle Security Controls
  const handleToggleDryRun = async () => {
    setIsUpdatingConfig(true);
    try {
      const updated = await api.updateSecurityConfig({ dry_run: !secConfig.dry_run });
      setSecConfig(updated);
      loadSecurityState();
    } catch (err: any) {
      setExecutionError(`Failed to update dry-run mode: ${err.message}`);
    } finally {
      setIsUpdatingConfig(false);
    }
  };

  const handleToggleApproval = async () => {
    setIsUpdatingConfig(true);
    try {
      const updated = await api.updateSecurityConfig({ require_approval: !secConfig.require_approval });
      setSecConfig(updated);
      loadSecurityState();
    } catch (err: any) {
      setExecutionError(`Failed to update approval mode: ${err.message}`);
    } finally {
      setIsUpdatingConfig(false);
    }
  };

  const handleToggleMaskSecrets = async () => {
    setIsUpdatingConfig(true);
    try {
      const updated = await api.updateSecurityConfig({ mask_secrets: !secConfig.mask_secrets });
      setSecConfig(updated);
      loadSecurityState();
    } catch (err: any) {
      setExecutionError(`Failed to update secret masking: ${err.message}`);
    } finally {
      setIsUpdatingConfig(false);
    }
  };

  // Execute Prompt
  const handleExecute = async (promptToRun = prompt, confirmDestructive = false, approvalId?: string) => {
    if (!promptToRun.trim()) return;

    setIsExecuting(true);
    setExecutionError(null);
    setResetMessage(null);

    try {
      const result = await api.executeAgentTask(promptToRun, confirmDestructive, approvalId);
      setExecutionResult(result);

      if (result.requires_confirmation && !result.approval_id) {
        setPendingPrompt(promptToRun);
      } else {
        setPendingPrompt(null);
      }
      loadSecurityState();
    } catch (err: any) {
      setExecutionError(err.message || 'Agent request failed.');
    } finally {
      setIsExecuting(false);
    }
  };

  // Confirm destructive action (traditional prompt)
  const handleConfirmDestructive = () => {
    if (pendingPrompt) {
      handleExecute(pendingPrompt, true);
    }
  };

  const handleCancelDestructive = () => {
    setPendingPrompt(null);
    setExecutionResult(null);
  };

  // Human approval handlers for explicit approval mode
  const handleApprove = async (approvalId: string) => {
    try {
      await api.approveRequest(approvalId);
      await handleExecute(prompt, true, approvalId);
      loadSecurityState();
    } catch (err: any) {
      setExecutionError(`Approval failed: ${err.message}`);
    }
  };

  const handleReject = async (approvalId: string) => {
    try {
      await api.rejectRequest(approvalId);
      setExecutionResult(null);
      loadSecurityState();
    } catch (err: any) {
      setExecutionError(`Rejection failed: ${err.message}`);
    }
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
      loadSecurityState();
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
            Real-time security guardrails, policy enforcement, and live tool execution over stdio.
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

      {/* Security Guardrails Bar */}
      <div className="mb-6 p-3.5 rounded border border-line bg-surface shadow-card flex flex-col md:flex-row md:items-center justify-between gap-4">
        {/* Left: Active Policy Status */}
        <div className="flex items-center space-x-3">
          <div className="flex items-center space-x-1.5 text-xs font-semibold px-2.5 py-1 rounded border border-accent/20 bg-accent-light text-accent">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>{secConfig.active_policy}</span>
          </div>
          <span className="text-[11px] text-ink-muted hidden sm:inline">
            Active safeguards protect mutating tools and redact secrets.
          </span>
        </div>

        {/* Right: Real-Time Security Controls */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Dry Run Toggle */}
          <button
            onClick={handleToggleDryRun}
            disabled={isUpdatingConfig}
            className={`inline-flex items-center space-x-1.5 text-xs px-2.5 py-1.5 rounded border transition-colors ${
              secConfig.dry_run
                ? 'bg-warn-light text-warn-text border-warn-border font-medium'
                : 'bg-canvas text-ink-muted border-line hover:text-ink'
            }`}
            title="When active, POST/PUT/PATCH/DELETE requests are intercepted before sending to upstream API"
          >
            <span className={`w-2 h-2 rounded-full ${secConfig.dry_run ? 'bg-warn animate-pulse' : 'bg-ink-muted/40'}`} />
            <span>Dry-Run Mode</span>
            <span className="text-[10px] font-mono uppercase opacity-80">{secConfig.dry_run ? 'ON' : 'OFF'}</span>
          </button>

          {/* Require Approval Toggle */}
          <button
            onClick={handleToggleApproval}
            disabled={isUpdatingConfig}
            className={`inline-flex items-center space-x-1.5 text-xs px-2.5 py-1.5 rounded border transition-colors ${
              secConfig.require_approval
                ? 'bg-accent-light text-accent border-accent/30 font-medium'
                : 'bg-canvas text-ink-muted border-line hover:text-ink'
            }`}
            title="When active, sensitive operations pause and require cryptographic human approval"
          >
            <span className={`w-2 h-2 rounded-full ${secConfig.require_approval ? 'bg-accent' : 'bg-ink-muted/40'}`} />
            <span>Approval Mode</span>
            <span className="text-[10px] font-mono uppercase opacity-80">{secConfig.require_approval ? 'ON' : 'OFF'}</span>
          </button>

          {/* Secret Masking Toggle */}
          <button
            onClick={handleToggleMaskSecrets}
            disabled={isUpdatingConfig}
            className={`inline-flex items-center space-x-1.5 text-xs px-2.5 py-1.5 rounded border transition-colors ${
              secConfig.mask_secrets
                ? 'bg-canvas text-ink border-line'
                : 'bg-danger-light text-danger-text border-danger-border font-medium'
            }`}
            title="Multi-layer masking of Bearer tokens, API keys, credentials, and sensitive headers"
          >
            {secConfig.mask_secrets ? (
              <Eye className="w-3.5 h-3.5 text-accent" />
            ) : (
              <EyeOff className="w-3.5 h-3.5 text-danger" />
            )}
            <span>Secret Masking</span>
            <span className="text-[10px] font-mono uppercase opacity-80">{secConfig.mask_secrets ? 'ENABLED' : 'OFF'}</span>
          </button>
        </div>
      </div>

      {resetMessage && (
        <div className="mb-4 p-2.5 rounded bg-accent-light text-accent border border-accent/20 text-xs font-medium">
          {resetMessage}
        </div>
      )}

      {/* Main Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Input, Approvals, and Execution (7 Cols) */}
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

          {/* Pending Human Approval Cards (Feature 2: Explicit Approval) */}
          {(executionResult?.requires_approval || pendingApprovals.length > 0) && (
            <div className="space-y-2">
              {pendingApprovals.map((appr) => (
                <div key={appr.approval_id} className="bg-warn-light border border-warn-border p-4 rounded space-y-2.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center space-x-2 text-warn-text font-medium text-xs">
                      <ShieldAlert className="w-4 h-4" />
                      <span>Security Approval Required</span>
                    </div>
                    <div className="flex items-center space-x-1 text-[11px] text-ink-muted font-mono">
                      <Clock className="w-3 h-3" />
                      <span>TTL: {appr.ttl_remaining_seconds}s</span>
                    </div>
                  </div>

                  <div className="text-xs text-ink space-y-1">
                    <p className="font-medium text-ink">
                      Action: <span className="font-mono text-danger font-semibold">{appr.method} {appr.path}</span>
                    </p>
                    <p className="text-ink-muted text-[11px]">
                      Approval ID: <span className="font-mono">{appr.approval_id}</span>
                    </p>
                    {appr.safe_arguments && Object.keys(appr.safe_arguments).length > 0 && (
                      <div className="pt-1">
                        <span className="text-[10px] uppercase font-mono text-ink-muted">Bound Arguments:</span>
                        <pre className="p-1.5 rounded bg-surface border border-line text-[11px] font-mono text-ink overflow-x-auto">
                          {JSON.stringify(appr.safe_arguments, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>

                  <div className="flex items-center space-x-2 pt-1">
                    <button
                      onClick={() => handleApprove(appr.approval_id)}
                      disabled={isExecuting}
                      className="inline-flex items-center space-x-1 px-3 py-1.5 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium transition-colors shadow-card"
                    >
                      <Check className="w-3.5 h-3.5" />
                      <span>Approve & Execute</span>
                    </button>
                    <button
                      onClick={() => handleReject(appr.approval_id)}
                      className="inline-flex items-center space-x-1 px-3 py-1.5 rounded border border-line bg-surface text-ink text-xs hover:bg-canvas transition-colors"
                    >
                      <X className="w-3.5 h-3.5 text-danger" />
                      <span>Reject</span>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Destructive Action Confirmation Card (Traditional Model Safeguard) */}
          {executionResult?.requires_confirmation && !executionResult.requires_approval && (
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
                <div className="flex items-center space-x-2 font-medium">
                  {executionResult.execution_status === 'DRY-RUN' ? (
                    <span className="px-2 py-0.5 rounded bg-warn-light text-warn-text border border-warn-border text-[11px] font-mono font-semibold">
                      DRY-RUN INTERCEPTED
                    </span>
                  ) : executionResult.policy_decision === 'DENY' ? (
                    <span className="px-2 py-0.5 rounded bg-danger-light text-danger-text border border-danger-border text-[11px] font-mono font-semibold">
                      BLOCKED BY POLICY
                    </span>
                  ) : executionResult.success ? (
                    <span className="px-2 py-0.5 rounded bg-accent-light text-accent border border-accent/30 text-[11px] font-mono font-semibold">
                      EXECUTED
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded bg-danger-light text-danger-text border border-danger-border text-[11px] font-mono font-semibold">
                      FAILED
                    </span>
                  )}

                  {executionResult.secrets_redacted && (
                    <span className="px-2 py-0.5 rounded bg-accent-light text-accent border border-accent/30 text-[11px] font-mono">
                      SECRETS REDACTED ({executionResult.redaction_count || 1})
                    </span>
                  )}
                </div>

                {executionResult.tool_invocations?.length > 0 && (
                  <span className="text-[11px] font-mono text-ink-muted">
                    tool: {executionResult.tool_invocations[0].tool_name}
                  </span>
                )}
              </div>

              {/* Redaction Notification Alert */}
              {executionResult.secrets_redacted && (
                <div className="p-2.5 rounded bg-accent-light text-accent border border-accent/20 text-xs flex items-center space-x-2">
                  <ShieldCheck className="w-4 h-4 shrink-0" />
                  <span>
                    Sensitive credentials, tokens, or headers were automatically redacted from the response with <code className="bg-white/50 px-1 py-0.5 rounded font-mono">[REDACTED_SECRET]</code>.
                  </span>
                </div>
              )}

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
                          <span className="text-ink-muted block text-[10px] uppercase">
                            {executionResult.execution_status === 'DRY-RUN' ? 'Simulated Operation Details:' : 'Response Payload:'}
                          </span>
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
              <div className="text-xs text-ink-muted py-2 flex items-center justify-between">
                <span>{isLoadingTools ? 'Discovering tools via stdio...' : 'No tools available.'}</span>
                {!isLoadingTools && (
                  <button
                    onClick={() => loadTools()}
                    className="text-xs text-emerald-600 dark:text-emerald-400 hover:underline font-medium ml-2"
                  >
                    Retry
                  </button>
                )}
              </div>
            ) : (
              <div className="space-y-1 max-h-[460px] overflow-y-auto pr-0.5">
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

      {/* Feature 5: Safe Execution History & Audit Trail */}
      <div className="mt-8 border-t border-line pt-6">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center space-x-2">
            <History className="w-4 h-4 text-ink-muted" />
            <h2 className="text-sm font-semibold text-ink">Safe Execution & Audit Trail</h2>
            <span className="text-xs text-ink-muted">({auditLogs.length} events recorded)</span>
          </div>
          <button
            onClick={() => setShowAuditHistory(!showAuditHistory)}
            className="text-xs text-accent hover:underline font-medium"
          >
            {showAuditHistory ? 'Collapse' : 'Expand'}
          </button>
        </div>

        {showAuditHistory && (
          <div className="bg-surface border border-line rounded overflow-hidden shadow-card">
            {auditLogs.length === 0 ? (
              <div className="p-4 text-xs text-ink-muted text-center">
                No execution events recorded yet. Run a prompt above to view real-time audit decisions.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-canvas border-b border-line text-[11px] font-mono text-ink-muted uppercase">
                    <tr>
                      <th className="px-3.5 py-2">Timestamp</th>
                      <th className="px-3.5 py-2">Tool / Action</th>
                      <th className="px-3.5 py-2">Policy Decision</th>
                      <th className="px-3.5 py-2">Status</th>
                      <th className="px-3.5 py-2">Redaction</th>
                      <th className="px-3.5 py-2">Details</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line font-mono text-[11px]">
                    {auditLogs.map((log) => (
                      <tr key={log.id} className="hover:bg-canvas/50 transition-colors">
                        <td className="px-3.5 py-2 text-ink-muted whitespace-nowrap">
                          {log.timestamp.slice(11, 19)}
                        </td>
                        <td className="px-3.5 py-2 text-ink font-semibold whitespace-nowrap">
                          <span className="px-1.5 py-0.5 rounded bg-canvas border border-line mr-1.5 text-[10px]">
                            {log.method}
                          </span>
                          {log.tool_name}
                        </td>
                        <td className="px-3.5 py-2 whitespace-nowrap">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                            log.policy_decision === 'ALLOW' ? 'bg-accent-light text-accent'
                            : log.policy_decision === 'DRY_RUN' ? 'bg-warn-light text-warn-text'
                            : log.policy_decision === 'REQUIRE_APPROVAL' ? 'bg-accent-light text-accent'
                            : 'bg-danger-light text-danger-text'
                          }`}>
                            {log.policy_decision}
                          </span>
                        </td>
                        <td className="px-3.5 py-2 whitespace-nowrap">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                            log.execution_status === 'EXECUTED' ? 'bg-accent-light text-accent'
                            : log.execution_status === 'DRY-RUN' ? 'bg-warn-light text-warn-text'
                            : log.execution_status === 'SECRETS REDACTED' ? 'bg-accent-light text-accent'
                            : log.execution_status === 'PENDING APPROVAL' ? 'bg-warn-light text-warn-text'
                            : log.execution_status === 'APPROVED' ? 'bg-accent-light text-accent'
                            : 'bg-danger-light text-danger-text'
                          }`}>
                            {log.execution_status}
                          </span>
                        </td>
                        <td className="px-3.5 py-2 whitespace-nowrap">
                          {log.secrets_redacted ? (
                            <span className="text-accent flex items-center space-x-1">
                              <ShieldCheck className="w-3.5 h-3.5" />
                              <span>Masked ({log.redaction_count})</span>
                            </span>
                          ) : (
                            <span className="text-ink-muted">None</span>
                          )}
                        </td>
                        <td className="px-3.5 py-2 text-ink-muted max-w-xs truncate">
                          {log.reason || (log.status_code ? `HTTP ${log.status_code}` : 'Simulated')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
