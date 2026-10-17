import React, { useState, useMemo, useRef } from 'react';
import { 
  Plus, 
  Trash2, 
  Play, 
  CheckCircle2, 
  XCircle, 
  AlertCircle, 
  Search, 
  Layers, 
  RefreshCw, 
  Loader2, 
  Copy, 
  Check, 
  Clock, 
  ChevronRight, 
  ChevronDown, 
  FileCode, 
  Upload, 
  EyeOff,
  Sparkles,
  Database
} from 'lucide-react';
import { api, API_BASE_URL } from '../api/client';
import type { 
  ToolMetadata, 
  ToolExecuteResponse 
} from '../api/types';

export interface ApiIntegration {
  id: string;
  name: string;
  title: string;
  generation_id: string;
  package_name: string;
  base_url: string;
  read_only: boolean;
  status: 'verified' | 'unverified' | 'failed';
  tool_count: number;
  tools: ToolMetadata[];
  created_at: string;
  last_tested?: string;
  error?: string;
}

export interface UnifiedTool {
  composite_id: string;
  api_id: string;
  api_name: string;
  api_status: 'verified' | 'unverified' | 'failed';
  generation_id: string;
  name: string;
  method: string;
  path: string;
  description: string;
  is_read_only: boolean;
  input_schema: Record<string, any>;
}

// Built-in sample spec 2: Store & Inventory Service (to easily demonstrate multi-API with duplicate tools)
const SAMPLE_STORE_API_SPEC = `openapi: 3.0.3
info:
  title: Store & Inventory API
  version: 2.1.0
  description: E-Commerce Catalog and Warehouse Inventory API
servers:
  - url: /demo-target
paths:
  /items:
    get:
      operationId: list_items
      summary: List inventory products
      description: Retrieve catalog products with stock levels.
      responses:
        '200':
          description: OK
    post:
      operationId: create_item
      summary: Add new inventory product
      description: Register a new product in the catalog.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - title
                - price
              properties:
                title:
                  type: string
                  description: Product display name
                price:
                  type: number
                  description: Price in USD
                in_stock:
                  type: boolean
                  default: true
      responses:
        '201':
          description: Created
  /items/{item_id}:
    get:
      operationId: get_item_by_id
      summary: Get inventory product details
      parameters:
        - name: item_id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: OK
    delete:
      operationId: delete_item
      summary: Remove product from inventory
      parameters:
        - name: item_id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Deleted
  /tasks:
    get:
      operationId: list_tasks
      summary: Cross-system store background tasks
      description: Returns store maintenance jobs (demonstrates cross-API duplicate tool name handling).
      responses:
        '200':
          description: OK
`;

export const MultiApiWorkspace: React.FC = () => {
  // In-memory workspace integrations list
  const [integrations, setIntegrations] = useState<ApiIntegration[]>([]);
  const [selectedApiId, setSelectedApiId] = useState<string>('all');

  // Add API Modal/Form State
  const [isAddingApi, setIsAddingApi] = useState<boolean>(false);
  const [newSpecContent, setNewSpecContent] = useState<string>('');
  const [newPackageName, setNewPackageName] = useState<string>('');
  const [newBaseUrl, setNewBaseUrl] = useState<string>('');
  const [newReadOnly, setNewReadOnly] = useState<boolean>(false);
  const [isSubmittingApi, setIsSubmittingApi] = useState<boolean>(false);
  const [addApiError, setAddApiError] = useState<string | null>(null);

  // Unified Tool Explorer State
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [methodFilter, setMethodFilter] = useState<string>('ALL');
  const [selectedTool, setSelectedTool] = useState<UnifiedTool | null>(null);

  // Tool Execution State
  const [argumentsJson, setArgumentsJson] = useState<string>('{}');
  const [isExecutingTool, setIsExecutingTool] = useState<boolean>(false);
  const [executionResult, setExecutionResult] = useState<ToolExecuteResponse | null>(null);
  const [executionError, setExecutionError] = useState<string | null>(null);
  const [copiedResult, setCopiedResult] = useState<boolean>(false);

  // Testing Individual Connection
  const [testingApiId, setTestingApiId] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load Preset Spec: Task Management
  const handleLoadDemoTaskSpec = async () => {
    try {
      setAddApiError(null);
      const demo = await api.getDemoSpec();
      setNewSpecContent(demo.spec);
      setNewPackageName('task_management_mcp');
      setNewBaseUrl(demo.default_base_url || `${API_BASE_URL}/demo-target`);
    } catch (err: any) {
      setAddApiError(err.message || 'Failed to load task demo specification.');
    }
  };

  // Load Preset Spec: Store & Inventory
  const handleLoadStoreSpec = () => {
    setAddApiError(null);
    setNewSpecContent(SAMPLE_STORE_API_SPEC);
    setNewPackageName('store_inventory_mcp');
    setNewBaseUrl(`${API_BASE_URL}/demo-target`);
  };

  // Handle File Upload for Add API
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.endsWith('.yaml') && !file.name.endsWith('.yml') && !file.name.endsWith('.json')) {
      setAddApiError('Please select a valid .yaml, .yml, or .json file.');
      return;
    }

    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      setNewSpecContent(content);
      if (!newPackageName) {
        const cleanName = file.name.replace(/\.[^/.]+$/, '').replace(/[^a-zA-Z0-9_]/g, '_');
        setNewPackageName(cleanName);
      }
    };
    reader.readAsText(file);
  };

  // Submit and Generate New API Integration
  const handleAddApiSubmit = async () => {
    if (!newSpecContent.trim()) {
      setAddApiError('Specification content is required.');
      return;
    }

    setIsSubmittingApi(true);
    setAddApiError(null);

    try {
      // 1. Generate MCP server through existing backend generator
      const genResult = await api.generateServer({
        spec: newSpecContent,
        package_name: newPackageName.trim() || undefined,
        base_url: newBaseUrl.trim() || undefined,
        read_only: newReadOnly,
      });

      // 2. Fetch tool schemas
      const toolsResult = await api.inspectTools(genResult.generation_id);

      // 3. Verify connection over real stdio process
      let connStatus: 'verified' | 'unverified' | 'failed' = 'unverified';
      let connError: string | undefined = undefined;
      let testedAt: string | undefined = undefined;

      try {
        const testRes = await api.testServerConnection(genResult.generation_id);
        connStatus = testRes.success ? 'verified' : 'failed';
        connError = testRes.error;
        testedAt = testRes.tested_at;
      } catch (err: any) {
        connStatus = 'failed';
        connError = err.message || 'Connection test failed';
      }

      const newIntegration: ApiIntegration = {
        id: `api_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
        name: genResult.package_name || genResult.api_title,
        title: genResult.api_title,
        generation_id: genResult.generation_id,
        package_name: genResult.package_name,
        base_url: genResult.base_url,
        read_only: genResult.read_only,
        status: connStatus,
        tool_count: toolsResult.tool_count,
        tools: toolsResult.tools || [],
        created_at: genResult.created_at,
        last_tested: testedAt,
        error: connError,
      };

      setIntegrations(prev => [...prev, newIntegration]);
      setIsAddingApi(false);
      setNewSpecContent('');
      setNewPackageName('');
      setNewBaseUrl('');
      setNewReadOnly(false);
    } catch (err: any) {
      setAddApiError(err.message || 'Failed to generate and integrate MCP server.');
    } finally {
      setIsSubmittingApi(false);
    }
  };

  // Remove Integration
  const handleRemoveIntegration = (apiId: string) => {
    setIntegrations(prev => prev.filter(i => i.id !== apiId));
    if (selectedTool?.api_id === apiId) {
      setSelectedTool(null);
      setExecutionResult(null);
    }
  };

  // Retest Individual Connection
  const handleRetestConnection = async (apiId: string) => {
    const target = integrations.find(i => i.id === apiId);
    if (!target) return;

    setTestingApiId(apiId);
    try {
      const testRes = await api.testServerConnection(target.generation_id);
      setIntegrations(prev => prev.map(item => {
        if (item.id === apiId) {
          return {
            ...item,
            status: testRes.success ? 'verified' : 'failed',
            last_tested: testRes.tested_at,
            error: testRes.error,
          };
        }
        return item;
      }));
    } catch (err: any) {
      setIntegrations(prev => prev.map(item => {
        if (item.id === apiId) {
          return {
            ...item,
            status: 'failed',
            last_tested: new Date().toISOString(),
            error: err.message || 'Connection test failed',
          };
        }
        return item;
      }));
    } finally {
      setTestingApiId(null);
    }
  };

  // Compile Unified Tools list with composite IDs and parent API context
  const unifiedTools = useMemo(() => {
    const list: UnifiedTool[] = [];
    integrations.forEach(int => {
      int.tools.forEach(tool => {
        list.push({
          composite_id: `${int.id}::${tool.name}`,
          api_id: int.id,
          api_name: int.name,
          api_status: int.status,
          generation_id: int.generation_id,
          name: tool.name,
          method: tool.method,
          path: tool.path,
          description: tool.description,
          is_read_only: tool.is_read_only,
          input_schema: tool.input_schema,
        });
      });
    });
    return list;
  }, [integrations]);

  // Filtered Tools based on Search, Selected API, and HTTP Method
  const filteredTools = useMemo(() => {
    return unifiedTools.filter(tool => {
      // API Filter
      if (selectedApiId !== 'all' && tool.api_id !== selectedApiId) {
        return false;
      }
      // Method Filter
      if (methodFilter !== 'ALL' && tool.method.toUpperCase() !== methodFilter) {
        return false;
      }
      // Search Query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesName = tool.name.toLowerCase().includes(q);
        const matchesDesc = tool.description.toLowerCase().includes(q);
        const matchesPath = tool.path.toLowerCase().includes(q);
        const matchesApi = tool.api_name.toLowerCase().includes(q);
        return matchesName || matchesDesc || matchesPath || matchesApi;
      }
      return true;
    });
  }, [unifiedTools, selectedApiId, methodFilter, searchQuery]);

  // When a tool is selected, prepopulate arguments template based on schema
  const handleSelectTool = (tool: UnifiedTool) => {
    setSelectedTool(tool);
    setExecutionResult(null);
    setExecutionError(null);

    const properties = tool.input_schema?.properties || {};
    const defaultArgs: Record<string, any> = {};

    Object.entries(properties).forEach(([key, schema]: [string, any]) => {
      if (schema.default !== undefined) {
        defaultArgs[key] = schema.default;
      } else if (schema.type === 'string') {
        defaultArgs[key] = '';
      } else if (schema.type === 'number' || schema.type === 'integer') {
        defaultArgs[key] = 0;
      } else if (schema.type === 'boolean') {
        defaultArgs[key] = false;
      } else if (schema.type === 'array') {
        defaultArgs[key] = [];
      } else if (schema.type === 'object') {
        defaultArgs[key] = {};
      } else {
        defaultArgs[key] = null;
      }
    });

    setArgumentsJson(JSON.stringify(defaultArgs, null, 2));
  };

  // Execute Tool against its specific API backend
  const handleExecuteTool = async (approvalId?: string) => {
    if (!selectedTool) return;

    let parsedArgs: Record<string, any> = {};
    try {
      parsedArgs = JSON.parse(argumentsJson || '{}');
    } catch {
      setExecutionError('Invalid JSON arguments syntax.');
      return;
    }

    setIsExecutingTool(true);
    setExecutionError(null);
    setExecutionResult(null);

    try {
      const response = await api.executeTool(
        selectedTool.generation_id,
        selectedTool.name,
        parsedArgs,
        approvalId
      );
      setExecutionResult(response);
      if (!response.success && response.error) {
        setExecutionError(response.error);
      }
    } catch (err: any) {
      setExecutionError(err.message || 'Execution request failed.');
    } finally {
      setIsExecutingTool(false);
    }
  };

  const handleCopyResult = () => {
    if (!executionResult) return;
    navigator.clipboard.writeText(JSON.stringify(executionResult.result ?? executionResult.content, null, 2));
    setCopiedResult(true);
    setTimeout(() => setCopiedResult(false), 2000);
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-6">
      {/* Header Banner */}
      <div className="pb-5 border-b border-line flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="text-xl font-semibold text-ink tracking-tight">Multi-API Workspace</h1>
            <span className="text-[10px] font-semibold tracking-wider px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-300/80 font-mono">
              PREMIUM
            </span>
          </div>
          <p className="text-xs text-ink-muted mt-0.5">
            Manage multiple OpenAPI integrations in an unified in-memory workspace with cross-API tool exploration and real execution.
          </p>
        </div>

        <div className="flex items-center space-x-2">
          <button
            onClick={() => setIsAddingApi(true)}
            className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium transition-colors shadow-card"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Add API Integration</span>
          </button>
        </div>
      </div>

      {/* Section 1: API Integrations Cards (Feature 1) */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2 text-xs font-medium text-ink uppercase tracking-wider">
            <Layers className="w-3.5 h-3.5 text-accent" />
            <span>Integrated APIs ({integrations.length})</span>
          </div>

          {integrations.length === 0 && (
            <div className="flex items-center space-x-2 text-xs">
              <span className="text-ink-muted">Quick start:</span>
              <button
                onClick={async () => {
                  await handleLoadDemoTaskSpec();
                  setIsAddingApi(true);
                }}
                className="text-xs text-accent hover:underline font-medium inline-flex items-center space-x-1"
              >
                <Sparkles className="w-3 h-3" />
                <span>Task API</span>
              </button>
              <span className="text-ink-muted">·</span>
              <button
                onClick={() => {
                  handleLoadStoreSpec();
                  setIsAddingApi(true);
                }}
                className="text-xs text-accent hover:underline font-medium inline-flex items-center space-x-1"
              >
                <Database className="w-3 h-3" />
                <span>Store API</span>
              </button>
            </div>
          )}
        </div>

        {integrations.length === 0 ? (
          <div className="bg-surface border border-line rounded p-8 text-center">
            <Layers className="w-8 h-8 text-ink-muted mx-auto mb-2 opacity-50" />
            <div className="text-xs font-medium text-ink">No APIs Added Yet</div>
            <p className="text-xs text-ink-muted mt-1 max-w-sm mx-auto">
              Add multiple OpenAPI specifications to unify their tools and execute requests across services in one interface.
            </p>
            <div className="mt-4 flex items-center justify-center space-x-3">
              <button
                onClick={() => setIsAddingApi(true)}
                className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded bg-accent text-white text-xs font-medium hover:bg-accent-hover shadow-card"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Upload Specification</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {integrations.map((item) => {
              const isTesting = testingApiId === item.id;
              return (
                <div
                  key={item.id}
                  className="bg-surface border border-line rounded p-3.5 space-y-3 shadow-card hover:border-accent/40 transition-colors"
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="font-semibold text-xs text-ink font-mono">{item.name}</div>
                      <div className="text-[11px] text-ink-muted mt-0.5 truncate max-w-[200px]" title={item.base_url}>
                        {item.base_url}
                      </div>
                    </div>

                    {/* Status Pill */}
                    {item.status === 'verified' ? (
                      <span className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-[#E7F3ED] text-[#22543D] border border-[#C6E7D7]">
                        <CheckCircle2 className="w-2.5 h-2.5" />
                        <span>Verified</span>
                      </span>
                    ) : item.status === 'failed' ? (
                      <span className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-[#FFF5F5] text-[#C53030] border border-[#FED7D7]">
                        <XCircle className="w-2.5 h-2.5" />
                        <span>Failed</span>
                      </span>
                    ) : (
                      <span className="inline-flex items-center space-x-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-canvas text-ink-muted border border-line">
                        <Clock className="w-2.5 h-2.5" />
                        <span>Ready</span>
                      </span>
                    )}
                  </div>

                  <div className="flex items-center justify-between pt-1 border-t border-line text-xs">
                    <span className="text-[11px] font-mono text-ink-muted">
                      {item.tool_count} {item.tool_count === 1 ? 'tool' : 'tools'} {item.read_only ? '(read-only)' : ''}
                    </span>

                    <div className="flex items-center space-x-1">
                      <button
                        onClick={() => handleRetestConnection(item.id)}
                        disabled={isTesting}
                        title="Retest connection"
                        className="p-1 rounded text-ink-muted hover:text-ink hover:bg-canvas transition-colors"
                      >
                        <RefreshCw className={`w-3.5 h-3.5 ${isTesting ? 'animate-spin text-accent' : ''}`} />
                      </button>

                      <button
                        onClick={() => handleRemoveIntegration(item.id)}
                        title="Remove API from workspace"
                        className="p-1 rounded text-ink-muted hover:text-danger-text hover:bg-danger-light transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  {item.error && (
                    <div className="text-[10px] font-mono text-danger-text bg-danger-light p-1.5 rounded border border-danger-border truncate" title={item.error}>
                      {item.error}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Section 2 & 3: Unified Tool Explorer & Tool Execution (Features 2 & 3) */}
      {integrations.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Left Column: Unified Tool Explorer (7 Cols) */}
          <div className="lg:col-span-7 bg-surface border border-line rounded p-4 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 pb-3 border-b border-line">
              <div>
                <h2 className="text-xs font-semibold text-ink uppercase tracking-wider">Unified Tool Explorer</h2>
                <p className="text-[11px] text-ink-muted">
                  Showing {filteredTools.length} of {unifiedTools.length} tools across {integrations.length} APIs
                </p>
              </div>

              {/* API Filter Pills */}
              <div className="flex flex-wrap items-center gap-1 text-xs">
                <button
                  onClick={() => setSelectedApiId('all')}
                  className={`px-2 py-0.5 rounded text-xs transition-colors ${
                    selectedApiId === 'all'
                      ? 'bg-accent text-white font-medium shadow-card'
                      : 'bg-canvas text-ink-muted hover:text-ink border border-line'
                  }`}
                >
                  All APIs ({unifiedTools.length})
                </button>
                {integrations.map((int) => (
                  <button
                    key={int.id}
                    onClick={() => setSelectedApiId(int.id)}
                    className={`px-2 py-0.5 rounded text-xs transition-colors truncate max-w-[120px] ${
                      selectedApiId === int.id
                        ? 'bg-accent text-white font-medium shadow-card'
                        : 'bg-canvas text-ink-muted hover:text-ink border border-line'
                    }`}
                    title={int.name}
                  >
                    {int.name} ({int.tool_count})
                  </button>
                ))}
              </div>
            </div>

            {/* Search Bar & Method Filters */}
            <div className="flex flex-col sm:flex-row items-center gap-2 text-xs">
              <div className="relative flex-1 w-full">
                <Search className="w-3.5 h-3.5 text-ink-muted absolute left-2.5 top-2.5" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search tools by name, path, or description..."
                  className="w-full pl-8 pr-3 py-1.5 text-xs rounded bg-canvas border border-line text-ink focus:bg-surface focus:border-accent"
                />
              </div>

              {/* Method Filters */}
              <div className="flex items-center space-x-1 shrink-0 bg-canvas p-0.5 rounded border border-line">
                {['ALL', 'GET', 'POST', 'PUT', 'DELETE'].map((m) => (
                  <button
                    key={m}
                    onClick={() => setMethodFilter(m)}
                    className={`px-2 py-0.5 rounded text-[10px] font-mono font-medium transition-colors ${
                      methodFilter === m
                        ? 'bg-surface text-ink font-bold shadow-card border border-line'
                        : 'text-ink-muted hover:text-ink'
                    }`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>

            {/* Tools List */}
            {filteredTools.length === 0 ? (
              <div className="p-8 text-center text-ink-muted text-xs bg-canvas/40 rounded border border-dashed border-line">
                No matching tools found. Try adjusting your search query or filters.
              </div>
            ) : (
              <div className="space-y-1.5 max-h-[540px] overflow-y-auto pr-1">
                {filteredTools.map((tool) => {
                  const isSelected = selectedTool?.composite_id === tool.composite_id;
                  return (
                    <div
                      key={tool.composite_id}
                      onClick={() => handleSelectTool(tool)}
                      className={`p-2.5 rounded border cursor-pointer text-xs transition-colors ${
                        isSelected
                          ? 'bg-accent-light border-accent text-ink shadow-sm'
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
                          <span className="text-ink-muted text-[11px] truncate hidden sm:inline">
                            {tool.path}
                          </span>
                        </div>

                        {/* Integration Source Tag (Prevents Overwriting Duplicate Names) */}
                        <div className="flex items-center space-x-1.5 shrink-0 ml-2">
                          <span className="text-[10px] px-1.5 py-0.5 rounded font-mono bg-surface border border-line text-ink-muted">
                            {tool.api_name}
                          </span>
                          {isSelected ? (
                            <ChevronDown className="w-3.5 h-3.5 text-accent" />
                          ) : (
                            <ChevronRight className="w-3.5 h-3.5 text-ink-muted" />
                          )}
                        </div>
                      </div>

                      {tool.description && (
                        <p className="text-[11px] text-ink-muted mt-1 line-clamp-1">
                          {tool.description}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Right Column: Real Tool Execution Panel (5 Cols) (Feature 3) */}
          <div className="lg:col-span-5 bg-surface border border-line rounded p-4 space-y-4">
            <div className="pb-3 border-b border-line flex items-center justify-between">
              <div>
                <h2 className="text-xs font-semibold text-ink uppercase tracking-wider">Tool Execution</h2>
                <p className="text-[11px] text-ink-muted">Execute against the selected MCP server process.</p>
              </div>

              {selectedTool && (
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-canvas border border-line text-ink font-medium">
                  {selectedTool.api_name}
                </span>
              )}
            </div>

            {selectedTool ? (
              <div className="space-y-4">
                {/* Selected Tool Details Card */}
                <div className="p-3 rounded bg-canvas border border-line text-xs space-y-1.5">
                  <div className="flex items-center space-x-2 font-mono">
                    <span className={`px-1.5 py-0.2 rounded text-[10px] font-bold ${
                      selectedTool.method === 'GET' ? 'bg-[#E7F3ED] text-[#22543D]' :
                      selectedTool.method === 'POST' ? 'bg-[#EBF8FF] text-[#2B6CB0]' :
                      selectedTool.method === 'DELETE' ? 'bg-[#FFF5F5] text-[#C53030]' :
                      'bg-[#FFFAF0] text-[#C05621]'
                    }`}>
                      {selectedTool.method}
                    </span>
                    <span className="font-semibold text-ink">{selectedTool.name}</span>
                  </div>
                  <div className="text-[11px] text-ink-muted font-mono truncate">
                    {selectedTool.path}
                  </div>
                  {selectedTool.description && (
                    <div className="text-[11px] text-ink-muted pt-1 border-t border-line/60 leading-relaxed">
                      {selectedTool.description}
                    </div>
                  )}
                </div>

                {/* Input Arguments Form / JSON Editor */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <label className="font-medium text-ink">Input Arguments (JSON)</label>
                    <span className="text-[10px] font-mono text-ink-muted">Validated against schema</span>
                  </div>

                  <textarea
                    value={argumentsJson}
                    onChange={(e) => setArgumentsJson(e.target.value)}
                    rows={6}
                    className="w-full font-mono text-xs p-2.5 rounded bg-canvas border border-line text-ink focus:bg-surface focus:border-accent resize-y"
                    spellCheck={false}
                  />
                </div>

                {/* Execute Action Button */}
                <button
                  onClick={() => handleExecuteTool()}
                  disabled={isExecutingTool}
                  className="w-full inline-flex items-center justify-center space-x-2 px-4 py-2 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-card"
                >
                  {isExecutingTool ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>Executing against {selectedTool.api_name}...</span>
                    </>
                  ) : (
                    <>
                      <Play className="w-3.5 h-3.5 fill-current" />
                      <span>Execute Tool</span>
                    </>
                  )}
                </button>

                {/* Requires Approval Guardrail Prompt */}
                {executionResult?.requires_approval && executionResult.approval_id && (
                  <div className="p-3 rounded bg-amber-50 border border-amber-200 text-amber-900 text-xs space-y-2">
                    <div className="font-semibold flex items-center space-x-1.5">
                      <AlertCircle className="w-4 h-4 text-amber-700 shrink-0" />
                      <span>Human Approval Required</span>
                    </div>
                    <p className="text-[11px] leading-relaxed">
                      This mutating operation ({selectedTool.method} {selectedTool.path}) requires explicit approval before dispatch.
                    </p>
                    <button
                      onClick={() => handleExecuteTool(executionResult.approval_id)}
                      disabled={isExecutingTool}
                      className="w-full px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-700 text-white text-xs font-medium transition-colors shadow-sm"
                    >
                      Approve & Execute Operation
                    </button>
                  </div>
                )}

                {/* Execution Error Banner */}
                {executionError && !executionResult?.requires_approval && (
                  <div className="p-3 rounded bg-danger-light border border-danger-border text-danger-text text-xs flex items-start space-x-2">
                    <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                    <div className="font-mono text-[11px] whitespace-pre-wrap">{executionError}</div>
                  </div>
                )}

                {/* Execution Results View */}
                {executionResult && (
                  <div className="space-y-2 pt-2 border-t border-line">
                    <div className="flex items-center justify-between text-xs">
                      <div className="flex items-center space-x-2">
                        <span className={`px-1.5 py-0.2 rounded text-[10px] font-bold ${
                          executionResult.success ? 'bg-[#E7F3ED] text-[#22543D]' : 'bg-[#FFF5F5] text-[#C53030]'
                        }`}>
                          {executionResult.success ? 'SUCCESS' : 'FAILED'}
                        </span>
                        {executionResult.status_code && (
                          <span className="text-[10px] font-mono text-ink-muted">
                            HTTP {executionResult.status_code}
                          </span>
                        )}
                        {executionResult.policy_decision && (
                          <span className="text-[10px] font-mono px-1 py-0.2 rounded bg-canvas border border-line text-ink">
                            {executionResult.policy_decision}
                          </span>
                        )}
                        {executionResult.secrets_redacted && (
                          <span className="inline-flex items-center space-x-1 text-[10px] font-mono px-1 py-0.2 rounded bg-amber-50 text-amber-800 border border-amber-200">
                            <EyeOff className="w-2.5 h-2.5" />
                            <span>Masked</span>
                          </span>
                        )}
                      </div>

                      <button
                        onClick={handleCopyResult}
                        className="inline-flex items-center space-x-1 text-[11px] text-ink-muted hover:text-ink font-mono"
                      >
                        {copiedResult ? <Check className="w-3 h-3 text-accent stroke-[2.5]" /> : <Copy className="w-3 h-3" />}
                        <span>{copiedResult ? 'Copied' : 'Copy'}</span>
                      </button>
                    </div>

                    <pre className="p-3 rounded bg-canvas border border-line text-[11px] font-mono text-ink overflow-x-auto max-h-56 leading-relaxed">
                      {JSON.stringify(executionResult.result ?? executionResult.content, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            ) : (
              <div className="p-8 text-center text-ink-muted text-xs bg-canvas/30 rounded border border-line">
                <FileCode className="w-6 h-6 mx-auto mb-2 opacity-50" />
                <div className="font-medium text-ink">No Tool Selected</div>
                <p className="text-[11px] mt-1">
                  Click any tool in the Unified Tool Explorer on the left to configure arguments and execute it.
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Add API Modal / Dialog */}
      {isAddingApi && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 backdrop-blur-sm p-4">
          <div className="bg-surface border border-line rounded-lg shadow-xl w-full max-w-xl max-h-[90vh] overflow-y-auto p-5 space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-line">
              <div className="flex items-center space-x-2">
                <h3 className="text-sm font-semibold text-ink">Add API to Workspace</h3>
                <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
                  IN-MEMORY
                </span>
              </div>
              <button
                onClick={() => setIsAddingApi(false)}
                className="text-ink-muted hover:text-ink p-1 rounded hover:bg-canvas"
              >
                ✕
              </button>
            </div>

            {/* Quick Preset Buttons */}
            <div className="flex items-center space-x-2 text-xs">
              <span className="text-ink-muted">Sample Presets:</span>
              <button
                onClick={handleLoadDemoTaskSpec}
                className="px-2 py-1 rounded bg-canvas hover:bg-surface border border-line text-ink font-medium transition-colors"
              >
                Task Management API
              </button>
              <button
                onClick={handleLoadStoreSpec}
                className="px-2 py-1 rounded bg-canvas hover:bg-surface border border-line text-ink font-medium transition-colors"
              >
                Store & Inventory API
              </button>
            </div>

            {/* Spec Upload / Editor */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <label className="font-medium text-ink">OpenAPI Specification (YAML or JSON)</label>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="text-accent hover:underline inline-flex items-center space-x-1"
                >
                  <Upload className="w-3 h-3" />
                  <span>Upload File</span>
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".yaml,.yml,.json"
                  onChange={handleFileUpload}
                  className="hidden"
                />
              </div>

              <textarea
                value={newSpecContent}
                onChange={(e) => setNewSpecContent(e.target.value)}
                placeholder="Paste OpenAPI 3.0 / 3.1 YAML or JSON here..."
                rows={9}
                className="w-full font-mono text-xs p-3 rounded bg-canvas border border-line text-ink focus:bg-surface focus:border-accent"
                spellCheck={false}
              />
            </div>

            {/* Options */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              <div>
                <label className="block text-ink-muted mb-1">Package / Service Name</label>
                <input
                  type="text"
                  value={newPackageName}
                  onChange={(e) => setNewPackageName(e.target.value)}
                  placeholder="e.g. store_api_mcp"
                  className="w-full px-2.5 py-1.5 font-mono rounded bg-canvas border border-line text-ink focus:bg-surface"
                />
              </div>

              <div>
                <label className="block text-ink-muted mb-1">Target Base URL (optional)</label>
                <input
                  type="text"
                  value={newBaseUrl}
                  onChange={(e) => setNewBaseUrl(e.target.value)}
                  placeholder={`e.g. ${API_BASE_URL}/demo-target`}
                  className="w-full px-2.5 py-1.5 font-mono rounded bg-canvas border border-line text-ink focus:bg-surface"
                />
              </div>
            </div>

            {/* Read-Only Option */}
            <label className="flex items-center space-x-2 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={newReadOnly}
                onChange={(e) => setNewReadOnly(e.target.checked)}
                className="rounded border-line text-accent focus:ring-accent"
              />
              <span className="text-ink">Strict Read-Only Mode (exclude mutating operations)</span>
            </label>

            {addApiError && (
              <div className="p-2.5 rounded bg-danger-light border border-danger-border text-danger-text text-xs flex items-start space-x-2">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <div className="whitespace-pre-wrap">{addApiError}</div>
              </div>
            )}

            {/* Modal Actions */}
            <div className="flex items-center justify-end space-x-2 pt-2 border-t border-line">
              <button
                onClick={() => setIsAddingApi(false)}
                className="px-3 py-1.5 rounded border border-line bg-surface hover:bg-canvas text-ink text-xs font-medium transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleAddApiSubmit}
                disabled={isSubmittingApi || !newSpecContent.trim()}
                className="inline-flex items-center space-x-1.5 px-4 py-1.5 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium transition-colors disabled:opacity-50 shadow-card"
              >
                {isSubmittingApi ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Generating & Connecting...</span>
                  </>
                ) : (
                  <span>Add to Workspace</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
