export interface OperationSummary {
  tool_name: string;
  method: string;
  path: string;
  summary?: string;
  is_read_only: boolean;
  parameters_count: number;
  has_request_body: boolean;
}

export interface SpecValidateResponse {
  valid: boolean;
  title?: string;
  version?: string;
  operation_count: number;
  operations: OperationSummary[];
  errors: string[];
}

export interface ToolMetadata {
  name: string;
  description: string;
  method: string;
  path: string;
  is_read_only: boolean;
  input_schema: Record<string, any>;
}

export interface ServerGenerateResponse {
  generation_id: string;
  package_name: string;
  api_title: string;
  api_version: string;
  read_only: boolean;
  base_url: string;
  tool_count: number;
  tool_names: string[];
  download_url: string;
  created_at: string;
  tools?: ToolMetadata[];
}

export interface ToolsInspectResponse {
  generation_id: string;
  package_name: string;
  tool_count: number;
  tools: ToolMetadata[];
}

export interface DemoSpecResponse {
  filename: string;
  spec: string;
  format: string;
  title: string;
  version: string;
  operation_count: number;
  default_base_url: string;
}

export interface AgentStatusResponse {
  status: string;
  service: string;
  server_script: string;
  target_base_url: string;
  total_tasks: number;
  counts_by_status: Record<string, number>;
  timestamp: string;
}

export interface AgentTool {
  name: string;
  description: string;
  input_schema: Record<string, any>;
}

export interface ToolInvocation {
  tool_name: string;
  arguments?: Record<string, any>;
  is_error?: boolean;
  status_code?: number;
  response?: any;
}

export interface AgentExecuteResponse {
  success: boolean;
  message: string;
  tool_invocations: ToolInvocation[];
  data?: any;
  requires_confirmation: boolean;
  pending_action?: {
    tool_name?: string;
    arguments?: Record<string, any>;
    requires_confirmation?: boolean;
    confirmation_prompt?: string;
  };
}

export interface AgentResetResponse {
  success: boolean;
  requires_confirmation: boolean;
  message: string;
  total_tasks?: number;
}
