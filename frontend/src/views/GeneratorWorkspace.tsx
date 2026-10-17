import React, { useState, useRef, useEffect } from 'react';
import { 
  Upload, 
  Download, 
  ChevronRight, 
  ChevronDown, 
  Check, 
  AlertCircle,
  Loader2,
  FileCode,
  Copy,
  Terminal,
  Activity,
  RefreshCw,
  Play,
  CheckCircle2,
  XCircle,
  EyeOff
} from 'lucide-react';
import { api } from '../api/client';
import type { 
  SpecValidateResponse, 
  ServerGenerateResponse, 
  ToolMetadata,
  IntegrationsResponse,
  ConnectionTestResponse,
  AuditLogEntry
} from '../api/types';

export const GeneratorWorkspace: React.FC = () => {
  // Input mode
  const [inputMode, setInputMode] = useState<'paste' | 'upload'>('paste');
  const [specContent, setSpecContent] = useState<string>('');
  const [specFilename, setSpecFilename] = useState<string>('openapi.yaml');

  // Options
  const [packageName, setPackageName] = useState<string>('');
  const [baseUrl, setBaseUrl] = useState<string>('');
  const [readOnly, setReadOnly] = useState<boolean>(false);

  // Validation State
  const [isValidating, setIsValidating] = useState<boolean>(false);
  const [validationResult, setValidationResult] = useState<SpecValidateResponse | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  // Generation State
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [generationResult, setGenerationResult] = useState<ServerGenerateResponse | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);

  // Tool Inspection
  const [isLoadingTools, setIsLoadingTools] = useState<boolean>(false);
  const [inspectedTools, setInspectedTools] = useState<ToolMetadata[]>([]);
  const [selectedToolName, setSelectedToolName] = useState<string | null>(null);

  // Connection Hub State
  const [integrationsData, setIntegrationsData] = useState<IntegrationsResponse | null>(null);
  const [isLoadingIntegrations, setIsLoadingIntegrations] = useState<boolean>(false);
  const [activeIntegrationId, setActiveIntegrationId] = useState<string>('claude-desktop');
  const [copiedTabId, setCopiedTabId] = useState<string | null>(null);

  // Connection Verification
  const [isTestingConnection, setIsTestingConnection] = useState<boolean>(false);
  const [connectionTestResult, setConnectionTestResult] = useState<ConnectionTestResponse | null>(null);

  // Hub View Tabs
  const [activeHubTab, setActiveHubTab] = useState<'integrations' | 'tools' | 'activity'>('integrations');

  // Live Audit Activity
  const [auditEntries, setAuditEntries] = useState<AuditLogEntry[]>([]);
  const [isLoadingAudit, setIsLoadingAudit] = useState<boolean>(false);
  const [expandedAuditId, setExpandedAuditId] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load Bundled Demo Spec
  const handleLoadDemoSpec = async () => {
    try {
      setIsValidating(true);
      setValidationError(null);
      const demo = await api.getDemoSpec();
      setSpecContent(demo.spec);
      setSpecFilename(demo.filename);
      setInputMode('paste');
      setBaseUrl(demo.default_base_url || '');
      setPackageName('task_management_mcp');

      const val = await api.validateSpec(demo.spec);
      setValidationResult(val);
    } catch (err: any) {
      setValidationError(err.message || 'Failed to load demo specification.');
    } finally {
      setIsValidating(false);
    }
  };

  // Handle File Upload
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.endsWith('.yaml') && !file.name.endsWith('.yml') && !file.name.endsWith('.json')) {
      setValidationError('Please select a valid .yaml, .yml, or .json file.');
      return;
    }

    setSpecFilename(file.name);
    const reader = new FileReader();
    reader.onload = async (event) => {
      const content = event.target?.result as string;
      setSpecContent(content);
      triggerValidation(content);
    };
    reader.readAsText(file);
  };

  // Validate Specification
  const triggerValidation = async (specToValidate = specContent) => {
    if (!specToValidate.trim()) {
      setValidationError('Specification text is empty.');
      return;
    }
    setIsValidating(true);
    setValidationError(null);
    setValidationResult(null);

    try {
      const result = await api.validateSpec(specToValidate);
      setValidationResult(result);
      if (!result.valid && result.errors.length > 0) {
        setValidationError(result.errors.join('\n'));
      }
    } catch (err: any) {
      setValidationError(err.message || 'Validation request failed.');
    } finally {
      setIsValidating(false);
    }
  };

  // Fetch Live Audit Log
  const fetchAuditLogs = async () => {
    try {
      setIsLoadingAudit(true);
      const logs = await api.getAuditLog(20);
      setAuditEntries(logs || []);
    } catch {
      // quiet fallback
    } finally {
      setIsLoadingAudit(false);
    }
  };

  // Generate Server
  const handleGenerateServer = async () => {
    if (!specContent.trim()) {
      setGenerationError('Please provide a specification before generating.');
      return;
    }

    setIsGenerating(true);
    setGenerationError(null);
    setGenerationResult(null);
    setInspectedTools([]);
    setConnectionTestResult(null);
    setIntegrationsData(null);

    try {
      const result = await api.generateServer({
        spec: specContent,
        package_name: packageName.trim() || undefined,
        base_url: baseUrl.trim() || undefined,
        read_only: readOnly,
      });

      setGenerationResult(result);

      // Fetch tool list
      setIsLoadingTools(true);
      const toolsResponse = await api.inspectTools(result.generation_id);
      setInspectedTools(toolsResponse.tools || []);
      if (toolsResponse.tools && toolsResponse.tools.length > 0) {
        setSelectedToolName(toolsResponse.tools[0].name);
      }

      // Fetch client integration configurations
      setIsLoadingIntegrations(true);
      try {
        const integrations = await api.getServerIntegrations(result.generation_id);
        setIntegrationsData(integrations);
      } catch (err) {
        console.error('Failed to load integration configurations', err);
      }

      // Fetch initial audit log
      fetchAuditLogs();
    } catch (err: any) {
      setGenerationError(err.message || 'Server generation failed.');
    } finally {
      setIsGenerating(false);
      setIsLoadingTools(false);
      setIsLoadingIntegrations(false);
    }
  };

  // Test Server Connection
  const handleTestConnection = async () => {
    if (!generationResult) return;
    setIsTestingConnection(true);
    try {
      const res = await api.testServerConnection(generationResult.generation_id);
      setConnectionTestResult(res);
      await fetchAuditLogs();
    } catch (err: any) {
      setConnectionTestResult({
        success: false,
        generation_id: generationResult.generation_id,
        package_name: generationResult.package_name,
        transport: 'stdio',
        tool_count: 0,
        discovered_tools: [],
        tested_at: new Date().toISOString(),
        message: 'Connection test failed',
        error: err.message || 'Failed to initialize MCP stdio connection.',
      });
      await fetchAuditLogs();
    } finally {
      setIsTestingConnection(false);
    }
  };

  // Copy Snippet Handler
  const handleCopySnippet = (tabId: string, snippet: string) => {
    navigator.clipboard.writeText(snippet);
    setCopiedTabId(tabId);
    setTimeout(() => {
      setCopiedTabId(null);
    }, 2000);
  };

  // Poll audit log every 5 seconds when a server is generated
  useEffect(() => {
    if (!generationResult) return;
    fetchAuditLogs();
    const interval = setInterval(fetchAuditLogs, 5000);
    return () => clearInterval(interval);
  }, [generationResult]);

  // Download Trigger
  const handleDownload = () => {
    if (!generationResult) return;
    window.location.href = api.getDownloadUrl(generationResult.generation_id);
  };

  const activeIntegration = integrationsData?.integrations.find(i => i.id === activeIntegrationId);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
      {/* Page Header */}
      <div className="mb-6 pb-5 border-b border-line flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink tracking-tight">OpenAPI to MCP</h1>
          <p className="text-xs text-ink-muted mt-0.5">
            Generate, test, and integrate standalone MCP servers from OpenAPI specifications.
          </p>
        </div>

        <button
          onClick={handleLoadDemoSpec}
          disabled={isValidating}
          className="self-start sm:self-auto text-xs px-2.5 py-1.5 rounded border border-line bg-surface hover:bg-canvas text-ink transition-colors disabled:opacity-50"
        >
          Load demo specification
        </button>
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Spec Input & Controls (5 Cols) */}
        <div className="lg:col-span-5 space-y-4">
          <div className="bg-surface border border-line rounded p-4 space-y-3">
            {/* Input Mode Selector */}
            <div className="flex items-center justify-between text-xs pb-2 border-b border-line">
              <span className="font-medium text-ink">Specification</span>
              <div className="flex items-center space-x-1 p-0.5 rounded bg-canvas border border-line">
                <button
                  onClick={() => setInputMode('paste')}
                  className={`px-2.5 py-0.5 rounded text-xs transition-colors ${
                    inputMode === 'paste' ? 'bg-surface text-ink font-medium shadow-card' : 'text-ink-muted hover:text-ink'
                  }`}
                >
                  Paste
                </button>
                <button
                  onClick={() => setInputMode('upload')}
                  className={`px-2.5 py-0.5 rounded text-xs transition-colors ${
                    inputMode === 'upload' ? 'bg-surface text-ink font-medium shadow-card' : 'text-ink-muted hover:text-ink'
                  }`}
                >
                  Upload
                </button>
              </div>
            </div>

            {/* Spec Editor / Upload Box */}
            {inputMode === 'upload' ? (
              <div 
                onClick={() => fileInputRef.current?.click()}
                className="border border-dashed border-line hover:border-accent rounded p-8 text-center cursor-pointer transition-colors bg-canvas/50"
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".yaml,.yml,.json"
                  onChange={handleFileUpload}
                  className="hidden"
                />
                <Upload className="w-5 h-5 text-ink-muted mx-auto mb-2" />
                <p className="text-xs font-medium text-ink">
                  {specContent ? `Selected: ${specFilename}` : 'Click to select an OpenAPI specification'}
                </p>
                <p className="text-[11px] text-ink-muted mt-1">Accepts .yaml, .yml, or .json</p>
              </div>
            ) : (
              <textarea
                value={specContent}
                onChange={(e) => setSpecContent(e.target.value)}
                placeholder={`openapi: 3.0.3\ninfo:\n  title: My Service API\n  version: 1.0.0\npaths:\n  /items:\n    get:\n      operationId: list_items\n      responses:\n        '200':\n          description: OK`}
                rows={11}
                className="w-full font-mono text-xs p-3 rounded bg-canvas border border-line text-ink placeholder-ink-subtle focus:bg-surface resize-y"
                spellCheck={false}
              />
            )}

            {/* Validation Controls */}
            <div className="flex items-center justify-between pt-1">
              <button
                onClick={() => triggerValidation()}
                disabled={isValidating || !specContent.trim()}
                className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded border border-line bg-surface hover:bg-canvas text-ink text-xs font-medium transition-colors disabled:opacity-50"
              >
                {isValidating ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-ink-muted" />
                    <span>Validating...</span>
                  </>
                ) : (
                  <span>Validate specification</span>
                )}
              </button>

              {validationResult && validationResult.valid && (
                <div className="text-xs text-accent font-medium flex items-center space-x-1.5">
                  <Check className="w-3.5 h-3.5 stroke-[2.5]" />
                  <span>
                    Valid: {validationResult.title || 'API'} · {validationResult.operation_count} ops
                  </span>
                </div>
              )}
            </div>

            {/* Validation Errors */}
            {validationError && (
              <div className="p-3 rounded bg-danger-light border border-danger-border text-danger-text text-xs font-mono whitespace-pre-wrap flex items-start space-x-2">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <div>{validationError}</div>
              </div>
            )}
          </div>

          {/* Generator Controls */}
          <div className="bg-surface border border-line rounded p-4 space-y-4">
            <h2 className="text-xs font-medium text-ink uppercase tracking-wider">Generation Settings</h2>

            <div className="space-y-3">
              <div>
                <label className="block text-xs text-ink-muted mb-1">Package Name (optional)</label>
                <input
                  type="text"
                  value={packageName}
                  onChange={(e) => setPackageName(e.target.value)}
                  placeholder="e.g. task_management_mcp"
                  className="w-full px-2.5 py-1.5 text-xs font-mono rounded bg-canvas border border-line text-ink focus:bg-surface"
                />
              </div>

              <div>
                <label className="block text-xs text-ink-muted mb-1">Target Base URL (optional)</label>
                <input
                  type="text"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="e.g. http://127.0.0.1:8000/demo-target"
                  className="w-full px-2.5 py-1.5 text-xs font-mono rounded bg-canvas border border-line text-ink focus:bg-surface"
                />
              </div>
            </div>

            {/* Strict Read-Only Option */}
            <div className="p-3 rounded bg-canvas border border-line">
              <label className="flex items-start space-x-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={readOnly}
                  onChange={(e) => setReadOnly(e.target.checked)}
                  className="mt-0.5 rounded border-line text-accent focus:ring-accent"
                />
                <div>
                  <span className="text-xs font-medium text-ink block">Strict read-only mode</span>
                  <span className="text-[11px] text-ink-muted block mt-0.5">
                    Only GET operations are included. POST, PUT, and DELETE operations are excluded.
                  </span>
                </div>
              </label>
            </div>

            {/* Generate Action */}
            <div className="pt-1">
              <button
                onClick={handleGenerateServer}
                disabled={isGenerating || !specContent.trim()}
                className="w-full inline-flex items-center justify-center space-x-2 px-4 py-2 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-card"
              >
                {isGenerating ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Generating MCP server...</span>
                  </>
                ) : (
                  <span>Generate MCP Server</span>
                )}
              </button>
            </div>

            {generationError && (
              <div className="p-3 rounded bg-danger-light border border-danger-border text-danger-text text-xs flex items-start space-x-2">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <div>{generationError}</div>
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Connection Hub & Server Inspector (7 Cols) */}
        <div className="lg:col-span-7 space-y-4">
          {generationResult ? (
            <div className="space-y-4">
              {/* Summary Card (Phase 2) */}
              <div className="bg-surface border border-line rounded p-4 space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3 border-b border-line">
                  <div>
                    <div className="flex items-center space-x-2">
                      <span className="text-sm font-semibold text-ink font-mono">{generationResult.package_name}</span>
                      {connectionTestResult?.success ? (
                        <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#E7F3ED] text-[#22543D] border border-[#C6E7D7]">
                          <CheckCircle2 className="w-3 h-3" />
                          <span>Connection Verified</span>
                        </span>
                      ) : connectionTestResult && !connectionTestResult.success ? (
                        <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#FFF5F5] text-[#C53030] border border-[#FED7D7]">
                          <XCircle className="w-3 h-3" />
                          <span>Connection Failed</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-canvas text-ink-muted border border-line">
                          <span>Ready to Connect (Not Tested)</span>
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] text-ink-muted mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                      <span>Transport: <code className="font-mono text-ink">stdio</code></span>
                      <span>·</span>
                      <span>Target: <code className="font-mono text-ink">{generationResult.base_url}</code></span>
                      <span>·</span>
                      <span>Mode: <strong className="text-ink">{generationResult.read_only ? 'Read-Only' : 'Full'}</strong></span>
                    </div>
                  </div>

                  <div className="flex items-center space-x-2 shrink-0">
                    <button
                      onClick={handleTestConnection}
                      disabled={isTestingConnection}
                      className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded border border-line bg-surface hover:bg-canvas text-ink text-xs font-medium transition-colors disabled:opacity-50 shadow-card"
                    >
                      {isTestingConnection ? (
                        <>
                          <Loader2 className="w-3.5 h-3.5 animate-spin text-accent" />
                          <span>Testing...</span>
                        </>
                      ) : (
                        <>
                          <Play className="w-3 h-3 fill-current text-accent" />
                          <span>Test Connection</span>
                        </>
                      )}
                    </button>

                    <button
                      onClick={handleDownload}
                      className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium transition-colors shadow-card"
                    >
                      <Download className="w-3.5 h-3.5" />
                      <span>Download ZIP</span>
                    </button>
                  </div>
                </div>

                {/* Metadata Pills */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 text-xs">
                  <div className="p-2 rounded bg-canvas border border-line">
                    <span className="text-[10px] uppercase font-mono text-ink-muted block">Tools</span>
                    <span className="font-medium text-ink mt-0.5 block">{generationResult.tool_count} generated</span>
                  </div>
                  <div className="p-2 rounded bg-canvas border border-line">
                    <span className="text-[10px] uppercase font-mono text-ink-muted block">Transport</span>
                    <span className="font-medium text-ink mt-0.5 block">stdio (JSON-RPC)</span>
                  </div>
                  <div className="p-2 rounded bg-canvas border border-line">
                    <span className="text-[10px] uppercase font-mono text-ink-muted block">Security Policy</span>
                    <span className="font-medium text-ink mt-0.5 block">{generationResult.read_only ? 'Strict Read-Only' : 'Guardrails Active'}</span>
                  </div>
                  <div className="p-2 rounded bg-canvas border border-line">
                    <span className="text-[10px] uppercase font-mono text-ink-muted block">Secret Redaction</span>
                    <span className="font-medium text-accent mt-0.5 block">Active (Masking ON)</span>
                  </div>
                </div>

                {/* Connection Test Banner (Phase 4) */}
                {connectionTestResult && (
                  <div className={`p-3 rounded border text-xs ${
                    connectionTestResult.success 
                      ? 'bg-[#F2FAF6] border-[#C6E7D7] text-[#1E4D3A]' 
                      : 'bg-[#FFF5F5] border-[#FED7D7] text-[#C53030]'
                  }`}>
                    <div className="flex items-start justify-between">
                      <div className="flex items-start space-x-2">
                        {connectionTestResult.success ? (
                          <CheckCircle2 className="w-4 h-4 text-[#22543D] shrink-0 mt-0.5" />
                        ) : (
                          <XCircle className="w-4 h-4 text-[#C53030] shrink-0 mt-0.5" />
                        )}
                        <div>
                          <div className="font-semibold">
                            {connectionTestResult.success 
                              ? `MCP Initialization & Tool Discovery Verified (${connectionTestResult.tool_count} tools discovered)` 
                              : 'MCP Connection Test Failed'}
                          </div>
                          <div className="text-[11px] mt-0.5 opacity-90">
                            {connectionTestResult.message}
                          </div>
                          {connectionTestResult.error && (
                            <div className="mt-1 font-mono text-[11px] bg-surface/80 p-1.5 rounded border border-line/60">
                              {connectionTestResult.error}
                            </div>
                          )}
                          {connectionTestResult.success && connectionTestResult.discovered_tools.length > 0 && (
                            <div className="mt-2 flex flex-wrap gap-1">
                              {connectionTestResult.discovered_tools.map((tName) => (
                                <span key={tName} className="font-mono text-[10px] px-1.5 py-0.5 bg-surface rounded border border-line text-ink">
                                  {tName}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                      <span className="text-[10px] opacity-75 font-mono shrink-0 ml-2">
                        {new Date(connectionTestResult.tested_at).toLocaleTimeString()}
                      </span>
                    </div>
                  </div>
                )}
              </div>

              {/* Hub Tabs Navigation */}
              <div className="bg-surface border border-line rounded p-4 space-y-4">
                <div className="flex items-center space-x-1 pb-3 border-b border-line text-xs">
                  <button
                    onClick={() => setActiveHubTab('integrations')}
                    className={`inline-flex items-center space-x-1.5 px-3 py-1.5 rounded font-medium transition-colors ${
                      activeHubTab === 'integrations'
                        ? 'bg-accent text-white shadow-card'
                        : 'bg-canvas hover:bg-surface text-ink border border-line'
                    }`}
                  >
                    <Terminal className="w-3.5 h-3.5" />
                    <span>Client Integrations</span>
                  </button>

                  <button
                    onClick={() => setActiveHubTab('tools')}
                    className={`inline-flex items-center space-x-1.5 px-3 py-1.5 rounded font-medium transition-colors ${
                      activeHubTab === 'tools'
                        ? 'bg-accent text-white shadow-card'
                        : 'bg-canvas hover:bg-surface text-ink border border-line'
                    }`}
                  >
                    <FileCode className="w-3.5 h-3.5" />
                    <span>Tool Schemas ({inspectedTools.length})</span>
                  </button>

                  <button
                    onClick={() => setActiveHubTab('activity')}
                    className={`inline-flex items-center space-x-1.5 px-3 py-1.5 rounded font-medium transition-colors ${
                      activeHubTab === 'activity'
                        ? 'bg-accent text-white shadow-card'
                        : 'bg-canvas hover:bg-surface text-ink border border-line'
                    }`}
                  >
                    <Activity className="w-3.5 h-3.5" />
                    <span>Live Activity & Guardrails</span>
                    {auditEntries.length > 0 && (
                      <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                        activeHubTab === 'activity' ? 'bg-white/20 text-white' : 'bg-surface text-ink-muted'
                      }`}>
                        {auditEntries.length}
                      </span>
                    )}
                  </button>
                </div>

                {/* Tab 1: Client Integrations (Phase 3) */}
                {activeHubTab === 'integrations' && (
                  isLoadingIntegrations ? (
                    <div className="text-xs text-ink-muted flex items-center space-x-2 py-6 justify-center">
                      <Loader2 className="w-4 h-4 animate-spin text-accent" />
                      <span>Loading integration configurations...</span>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {/* Integration Client Tabs */}
                      <div className="flex flex-wrap gap-1.5 p-1 bg-canvas rounded border border-line text-xs">
                      {integrationsData?.integrations.map((item) => {
                        const isSelected = activeIntegrationId === item.id;
                        return (
                          <button
                            key={item.id}
                            onClick={() => setActiveIntegrationId(item.id)}
                            className={`px-2.5 py-1 rounded transition-colors text-xs font-medium flex items-center space-x-1.5 ${
                              isSelected
                                ? 'bg-surface text-ink font-semibold shadow-card border border-line'
                                : 'text-ink-muted hover:text-ink hover:bg-surface/50'
                            }`}
                          >
                            <span>{item.name}</span>
                            <span className={`text-[9px] px-1 py-0.2 rounded font-mono ${
                              item.transport === 'stdio'
                                ? 'bg-[#E7F3ED] text-[#22543D]'
                                : 'bg-[#FFF5F5] text-[#C53030]'
                            }`}>
                              {item.transport}
                            </span>
                          </button>
                        );
                      })}
                    </div>

                    {/* Active Integration Content */}
                    {activeIntegration && (
                      <div className="space-y-3.5 text-xs">
                        {/* Integration Header */}
                        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 pb-2 border-b border-line">
                          <div>
                            <div className="font-semibold text-ink flex items-center space-x-2">
                              <span>{activeIntegration.name} Integration</span>
                              <span className="text-[11px] font-normal text-ink-muted">
                                ({activeIntegration.transport === 'stdio' ? 'Local stdio process' : 'Remote HTTP transport'})
                              </span>
                            </div>
                            {activeIntegration.target_file && (
                              <div className="text-[11px] text-ink-muted mt-0.5 font-mono">
                                Config path: {activeIntegration.target_file}
                              </div>
                            )}
                          </div>

                          <button
                            onClick={() => handleCopySnippet(activeIntegration.id, activeIntegration.snippet)}
                            className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded border border-line bg-surface hover:bg-canvas text-ink text-xs font-medium transition-colors"
                          >
                            {copiedTabId === activeIntegration.id ? (
                              <>
                                <Check className="w-3.5 h-3.5 text-accent stroke-[2.5]" />
                                <span className="text-accent font-medium">Copied!</span>
                              </>
                            ) : (
                              <>
                                <Copy className="w-3.5 h-3.5 text-ink-muted" />
                                <span>Copy Config</span>
                              </>
                            )}
                          </button>
                        </div>

                        {/* If integration is unavailable (e.g. Hosted MCP) */}
                        {!activeIntegration.is_available && (
                          <div className="p-3 rounded bg-amber-50 border border-amber-200 text-amber-900 text-xs">
                            <div className="font-semibold flex items-center space-x-1.5">
                              <AlertCircle className="w-4 h-4 text-amber-700 shrink-0" />
                              <span>Hosted Remote MCP Not Active</span>
                            </div>
                            <div className="mt-1 leading-relaxed">
                              This generated MCP server runs locally via standard <strong>stdio</strong> transport. A hosted remote HTTP/SSE streaming gateway is not deployed for this instance. To integrate with AI clients, use the local stdio configuration tabs above (Claude Desktop, Claude Code, Cursor, VS Code, or Docker).
                            </div>
                          </div>
                        )}

                        {/* Prerequisites */}
                        {activeIntegration.prerequisites && activeIntegration.prerequisites.length > 0 && (
                          <div>
                            <span className="font-medium text-ink block mb-1">Prerequisites:</span>
                            <ul className="list-disc list-inside text-ink-muted space-y-0.5 text-[11px]">
                              {activeIntegration.prerequisites.map((req, idx) => (
                                <li key={idx}>{req}</li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {/* Setup Steps */}
                        {activeIntegration.setup_steps && activeIntegration.setup_steps.length > 0 && (
                          <div>
                            <span className="font-medium text-ink block mb-1">Setup Instructions:</span>
                            <ol className="list-decimal list-inside text-ink-muted space-y-0.5 text-[11px]">
                              {activeIntegration.setup_steps.map((step, idx) => (
                                <li key={idx}>{step}</li>
                              ))}
                            </ol>
                          </div>
                        )}

                        {/* Copyable Code Snippet */}
                        <div>
                          <span className="font-medium text-ink block mb-1">Configuration Snippet:</span>
                          <div className="relative">
                            <pre className="p-3 rounded bg-canvas border border-line text-[11px] font-mono text-ink overflow-x-auto max-h-64 leading-relaxed whitespace-pre">
                              {activeIntegration.snippet}
                            </pre>
                            <button
                              onClick={() => handleCopySnippet(activeIntegration.id, activeIntegration.snippet)}
                              aria-label="Copy snippet"
                              className="absolute top-2 right-2 p-1.5 rounded bg-surface border border-line hover:bg-canvas text-ink-muted hover:text-ink transition-colors shadow-sm"
                            >
                              {copiedTabId === activeIntegration.id ? (
                                <Check className="w-3.5 h-3.5 text-accent stroke-[2.5]" />
                              ) : (
                                <Copy className="w-3.5 h-3.5" />
                              )}
                            </button>
                          </div>
                        </div>

                        {/* Environment Variables Reference */}
                        {activeIntegration.environment_variables && activeIntegration.environment_variables.length > 0 && (
                          <div className="pt-2">
                            <span className="font-medium text-ink block mb-1.5">Environment Variables Reference:</span>
                            <div className="border border-line rounded overflow-hidden">
                              <table className="w-full text-left text-[11px]">
                                <thead className="bg-canvas border-b border-line text-ink-muted font-mono">
                                  <tr>
                                    <th className="px-2.5 py-1.5 font-medium">Variable</th>
                                    <th className="px-2 py-1.5 font-medium">Placeholder / Default</th>
                                    <th className="px-2.5 py-1.5 font-medium">Purpose</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-line">
                                  {activeIntegration.environment_variables.map((env) => (
                                    <tr key={env.name} className="hover:bg-canvas/50">
                                      <td className="px-2.5 py-1.5 font-mono text-ink font-medium whitespace-nowrap">
                                        {env.name}
                                        {env.required && <span className="ml-1 text-[9px] text-accent">*</span>}
                                      </td>
                                      <td className="px-2 py-1.5 font-mono text-ink-muted whitespace-nowrap">
                                        {env.placeholder}
                                      </td>
                                      <td className="px-2.5 py-1.5 text-ink-muted leading-tight">
                                        {env.description}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                            <div className="text-[10px] text-ink-muted mt-1">
                              * No real credentials are embedded in generated configurations. Fill in authorization tokens in your local client or .env file.
                            </div>
                          </div>
                        )}

                        {/* Integration Note */}
                        {activeIntegration.notes && (
                          <div className="p-2.5 rounded bg-canvas border border-line text-[11px] text-ink-muted leading-relaxed">
                            <strong>Note:</strong> {activeIntegration.notes}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                  )
                )}

                {/* Tab 2: Tool Schemas (Phase 1 & Phase 2 Inspection) */}
                {activeHubTab === 'tools' && (
                  <div className="space-y-2 text-xs">
                    {isLoadingTools ? (
                      <div className="text-xs text-ink-muted flex items-center space-x-2 py-4">
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        <span>Loading tool schemas...</span>
                      </div>
                    ) : inspectedTools.length === 0 ? (
                      <div className="text-xs text-ink-muted py-2">No tools exposed in this package.</div>
                    ) : (
                      <div className="space-y-1.5">
                        {inspectedTools.map((tool) => {
                          const isSelected = selectedToolName === tool.name;
                          return (
                            <div
                              key={tool.name}
                              onClick={() => setSelectedToolName(isSelected ? null : tool.name)}
                              className={`p-2.5 rounded border cursor-pointer text-xs transition-colors ${
                                isSelected 
                                  ? 'bg-accent-light border-accent text-ink' 
                                  : 'bg-canvas hover:bg-surface border-line text-ink'
                              }`}
                            >
                              <div className="flex items-center justify-between">
                                <div className="flex items-center space-x-2 truncate font-mono">
                                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                    tool.method === 'GET' ? 'bg-[#E7F3ED] text-[#22543D]' :
                                    tool.method === 'POST' ? 'bg-[#EBF8FF] text-[#2B6CB0]' :
                                    tool.method === 'DELETE' ? 'bg-[#FFF5F5] text-[#C53030]' :
                                    'bg-[#FFFAF0] text-[#C05621]'
                                  }`}>
                                    {tool.method}
                                  </span>
                                  <span className="font-semibold truncate">{tool.name}</span>
                                  <span className="text-ink-muted text-[11px] hidden sm:inline">({tool.path})</span>
                                </div>
                                {isSelected ? (
                                  <ChevronDown className="w-3.5 h-3.5 text-ink-muted shrink-0" />
                                ) : (
                                  <ChevronRight className="w-3.5 h-3.5 text-ink-muted shrink-0" />
                                )}
                              </div>

                              {/* Selected Schema Inspector */}
                              {isSelected && (
                                <div className="mt-2.5 pt-2.5 border-t border-line/60 space-y-2 text-xs font-sans">
                                  {tool.description && (
                                    <p className="text-ink-muted leading-relaxed">{tool.description}</p>
                                  )}
                                  <div>
                                    <span className="text-[11px] font-mono text-ink-muted block mb-1">Input Schema (JSON Schema):</span>
                                    <pre className="p-2 rounded bg-surface border border-line text-[11px] font-mono text-ink overflow-x-auto max-h-48">
                                      {JSON.stringify(tool.input_schema, null, 2)}
                                    </pre>
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                {/* Tab 3: Live Tool Activity (Phase 5) */}
                {activeHubTab === 'activity' && (
                  <div className="space-y-3 text-xs">
                    <div className="flex items-center justify-between pb-2 border-b border-line">
                      <div>
                        <span className="font-semibold text-ink block">Sanitized Tool Execution Activity</span>
                        <span className="text-[11px] text-ink-muted block mt-0.5">
                          Real-time tool invocations, security policy decisions, and credentials redactions.
                        </span>
                      </div>

                      <button
                        onClick={fetchAuditLogs}
                        disabled={isLoadingAudit}
                        className="inline-flex items-center space-x-1 px-2 py-1 rounded border border-line bg-surface hover:bg-canvas text-ink text-xs transition-colors"
                      >
                        <RefreshCw className={`w-3 h-3 ${isLoadingAudit ? 'animate-spin text-accent' : 'text-ink-muted'}`} />
                        <span>Refresh</span>
                      </button>
                    </div>

                    {auditEntries.length === 0 ? (
                      <div className="p-6 text-center bg-canvas rounded border border-line text-ink-muted">
                        <Activity className="w-5 h-5 mx-auto mb-1.5 opacity-50 text-ink" />
                        <div className="font-medium text-ink">No Tool Execution Events Yet</div>
                        <p className="text-[11px] mt-1 max-w-sm mx-auto">
                          Execute tasks via the <strong>Agent Playground</strong> or connect an MCP client to observe live tool calls, dry-run interceptions, and secret redactions.
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
                        {auditEntries.map((entry) => {
                          const isExpanded = expandedAuditId === entry.id;
                          return (
                            <div key={entry.id} className="p-2.5 rounded bg-canvas border border-line text-xs space-y-1.5">
                              <div className="flex items-center justify-between">
                                <div className="flex items-center space-x-2 font-mono">
                                  <span className="text-[10px] text-ink-muted">
                                    {new Date(entry.timestamp).toLocaleTimeString()}
                                  </span>
                                  <span className="font-semibold text-ink">{entry.tool_name}</span>
                                  <span className="text-[10px] text-ink-muted hidden sm:inline">
                                    {entry.method} {entry.sanitized_path}
                                  </span>
                                </div>

                                <div className="flex items-center space-x-1.5">
                                  {entry.secrets_redacted && (
                                    <span className="inline-flex items-center space-x-1 px-1.5 py-0.2 rounded text-[10px] font-medium bg-[#FFF5F5] text-[#C53030] border border-[#FED7D7]">
                                      <EyeOff className="w-2.5 h-2.5" />
                                      <span>Redacted</span>
                                    </span>
                                  )}

                                  <span className={`px-1.5 py-0.2 rounded text-[10px] font-bold ${
                                    entry.execution_status === 'EXECUTED' ? 'bg-[#E7F3ED] text-[#22543D]' :
                                    entry.execution_status === 'DRY-RUN' ? 'bg-[#EBF8FF] text-[#2B6CB0]' :
                                    entry.execution_status === 'BLOCKED' ? 'bg-[#FFF5F5] text-[#C53030]' :
                                    'bg-[#FFFAF0] text-[#C05621]'
                                  }`}>
                                    {entry.execution_status}
                                  </span>
                                </div>
                              </div>

                              {/* Details Toggle */}
                              <div className="flex items-center justify-between text-[11px] text-ink-muted pt-1 border-t border-line/60">
                                <span className="font-mono">
                                  Policy: <strong className="text-ink">{entry.policy_decision}</strong>
                                </span>

                                {entry.safe_arguments && Object.keys(entry.safe_arguments).length > 0 && (
                                  <button
                                    onClick={() => setExpandedAuditId(isExpanded ? null : entry.id)}
                                    className="text-accent hover:underline text-[10px] font-medium"
                                  >
                                    {isExpanded ? 'Hide Arguments' : 'View Arguments'}
                                  </button>
                                )}
                              </div>

                              {/* Safe Arguments Expandable Box */}
                              {isExpanded && entry.safe_arguments && (
                                <pre className="p-2 rounded bg-surface border border-line text-[10px] font-mono text-ink overflow-x-auto mt-1">
                                  {JSON.stringify(entry.safe_arguments, null, 2)}
                                </pre>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ) : (
            /* Empty State */
            <div className="bg-surface border border-line rounded p-12 text-center">
              <FileCode className="w-8 h-8 text-ink-muted mx-auto mb-3 opacity-60" />
              <div className="text-sm font-semibold text-ink">MCP Server Connection Hub</div>
              <p className="text-xs text-ink-muted mt-1.5 max-w-sm mx-auto leading-relaxed">
                Validate your OpenAPI specification and generate an MCP server to unlock one-click connection testing, copyable client configurations for Claude, Cursor, and VS Code, and live execution activity.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
