import React, { useState, useRef } from 'react';
import { 
  Upload, 
  Download, 
  ChevronRight, 
  ChevronDown, 
  Check, 
  AlertCircle,
  Loader2,
  FileCode
} from 'lucide-react';
import { api } from '../api/client';
import type { 
  SpecValidateResponse, 
  ServerGenerateResponse, 
  ToolMetadata 
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
    } catch (err: any) {
      setGenerationError(err.message || 'Server generation failed.');
    } finally {
      setIsGenerating(false);
      setIsLoadingTools(false);
    }
  };

  // Download Trigger
  const handleDownload = () => {
    if (!generationResult) return;
    window.location.href = api.getDownloadUrl(generationResult.generation_id);
  };

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
      {/* Page Header */}
      <div className="mb-6 pb-5 border-b border-line flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink tracking-tight">OpenAPI to MCP</h1>
          <p className="text-xs text-ink-muted mt-0.5">
            Generate a standalone MCP server from your API specification.
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
        {/* Left Column: Spec Input & Controls (7 Cols) */}
        <div className="lg:col-span-7 space-y-4">
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
                rows={12}
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
                    Valid: {validationResult.title || 'API'} (v{validationResult.version || '1.0'}) · {validationResult.operation_count} operations
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

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
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

        {/* Right Column: Results & Tool Inspector (5 Cols) */}
        <div className="lg:col-span-5 space-y-4">
          {generationResult ? (
            <div className="bg-surface border border-line rounded p-4 space-y-4">
              {/* Header with Tool Count and Download */}
              <div className="flex items-center justify-between pb-3 border-b border-line">
                <div>
                  <div className="text-xs font-semibold text-ink">
                    {generationResult.tool_count} {generationResult.tool_count === 1 ? 'tool' : 'tools'} generated
                  </div>
                  <div className="text-[11px] text-ink-muted font-mono mt-0.5">
                    {generationResult.package_name} {generationResult.read_only ? '(read-only)' : ''}
                  </div>
                </div>

                <button
                  onClick={handleDownload}
                  className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium transition-colors shadow-card"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>Download ZIP</span>
                </button>
              </div>

              {/* Tools List */}
              <div className="space-y-2">
                <div className="text-xs font-medium text-ink uppercase tracking-wider">Generated Tools</div>
                
                {isLoadingTools ? (
                  <div className="text-xs text-ink-muted flex items-center space-x-2 py-4">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Loading tool schemas...</span>
                  </div>
                ) : inspectedTools.length === 0 ? (
                  <div className="text-xs text-ink-muted py-2">No tools in this package.</div>
                ) : (
                  <div className="space-y-1">
                    {inspectedTools.map((tool) => {
                      const isSelected = selectedToolName === tool.name;
                      return (
                        <div
                          key={tool.name}
                          onClick={() => setSelectedToolName(isSelected ? null : tool.name)}
                          className={`p-2 rounded border cursor-pointer text-xs transition-colors ${
                            isSelected 
                              ? 'bg-accent-light border-accent text-ink' 
                              : 'bg-canvas hover:bg-surface border-line text-ink'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center space-x-2 truncate font-mono">
                              <span className={`px-1 py-0.2 rounded text-[10px] font-bold ${
                                tool.method === 'GET' ? 'bg-[#E7F3ED] text-[#22543D]' :
                                tool.method === 'POST' ? 'bg-[#EBF8FF] text-[#2B6CB0]' :
                                tool.method === 'DELETE' ? 'bg-[#FFF5F5] text-[#C53030]' :
                                'bg-[#FFFAF0] text-[#C05621]'
                              }`}>
                                {tool.method}
                              </span>
                              <span className="font-medium truncate">{tool.name}</span>
                            </div>
                            {isSelected ? <ChevronDown className="w-3.5 h-3.5 text-ink-muted shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-ink-muted shrink-0" />}
                          </div>

                          {/* Selected Schema Inspector */}
                          {isSelected && (
                            <div className="mt-2.5 pt-2.5 border-t border-line/60 space-y-2 text-xs font-sans">
                              {tool.description && (
                                <p className="text-ink-muted leading-relaxed">{tool.description}</p>
                              )}
                              <div>
                                <span className="text-[11px] font-mono text-ink-muted block mb-1">Input Schema:</span>
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

              {/* Minimal Next Step */}
              <div className="pt-2 border-t border-line text-[11px] text-ink-muted leading-relaxed">
                Credentials for the server belong in its local <code className="px-1 py-0.5 rounded bg-canvas text-ink font-mono">.env</code> file after extracting the ZIP package.
              </div>
            </div>
          ) : (
            /* Empty State */
            <div className="bg-surface border border-line rounded p-8 text-center">
              <FileCode className="w-6 h-6 text-ink-muted mx-auto mb-2 opacity-60" />
              <div className="text-xs font-medium text-ink">No server generated yet</div>
              <p className="text-xs text-ink-muted mt-1 max-w-xs mx-auto">
                Validate your specification and click Generate MCP Server to inspect tool schemas and download.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
