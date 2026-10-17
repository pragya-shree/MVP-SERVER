import type {
  SpecValidateResponse,
  ServerGenerateResponse,
  ToolsInspectResponse,
  DemoSpecResponse,
  AgentStatusResponse,
  AgentTool,
  AgentExecuteResponse,
  AgentResetResponse,
} from './types';

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
).replace(/\/+$/, '');

class ApiError extends Error {
  status: number;
  data?: any;

  constructor(message: string, status: number, data?: any) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

async function fetchWithTimeout(url: string, options: RequestInit = {}, timeoutMs = 15000): Promise<Response> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    return response;
  } catch (err: any) {
    if (err.name === 'AbortError') {
      throw new Error(`Request timed out after ${timeoutMs / 1000} seconds. Please verify the backend service is running.`);
    }
    throw new Error(
      `Network error connecting to ${url}: ${err.message || 'Server may be down or unreachable'}. Check backend service and CORS configuration.`
    );
  } finally {
    clearTimeout(id);
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;
  const headers = new Headers(options.headers || {});

  if (!headers.has('Content-Type') && options.body && typeof options.body === 'string') {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetchWithTimeout(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status} ${response.statusText}`;
    let errorDetail: any = null;
    try {
      const errJson = await response.json();
      errorDetail = errJson;
      if (errJson.detail) {
        errorMessage = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      } else if (errJson.message) {
        errorMessage = errJson.message;
      }
    } catch {
      // Non-JSON error body
      try {
        const text = await response.text();
        if (text) errorMessage = text;
      } catch {
        // fallback
      }
    }
    throw new ApiError(errorMessage, response.status, errorDetail);
  }

  return response.json() as Promise<T>;
}

export const api = {
  getHealth: async (): Promise<{ status: string; service: string; version: string }> => {
    return request('/api/v1/health');
  },

  getDemoSpec: async (): Promise<DemoSpecResponse> => {
    return request('/api/v1/demo/spec');
  },

  validateSpec: async (spec: string): Promise<SpecValidateResponse> => {
    return request('/api/v1/specs/validate', {
      method: 'POST',
      body: JSON.stringify({ spec }),
    });
  },

  generateServer: async (params: {
    spec: string;
    package_name?: string;
    base_url?: string;
    read_only?: boolean;
  }): Promise<ServerGenerateResponse> => {
    return request('/api/v1/servers/generate', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },

  inspectTools: async (generationId: string): Promise<ToolsInspectResponse> => {
    return request(`/api/v1/servers/${generationId}/tools`);
  },

  getDownloadUrl: (generationId: string): string => {
    return `${API_BASE_URL}/api/v1/servers/${generationId}/download`;
  },

  getAgentStatus: async (): Promise<AgentStatusResponse> => {
    return request('/api/v1/agent/status');
  },

  getAgentTools: async (): Promise<AgentTool[]> => {
    return request('/api/v1/agent/tools');
  },

  executeAgentTask: async (
    naturalLanguageRequest: string,
    confirmDestructive = false
  ): Promise<AgentExecuteResponse> => {
    return request('/api/v1/agent/execute', {
      method: 'POST',
      body: JSON.stringify({
        request: naturalLanguageRequest,
        confirm_destructive: confirmDestructive,
      }),
    });
  },

  resetAgentData: async (confirm = false): Promise<AgentResetResponse> => {
    return request('/api/v1/agent/reset', {
      method: 'POST',
      body: JSON.stringify({ confirm }),
    });
  },
};
