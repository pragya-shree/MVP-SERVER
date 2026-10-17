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
  requires_approval?: boolean;
  approval_id?: string;
  pending_action?: {
    tool_name?: string;
    arguments?: Record<string, any>;
    reasoning?: string;
    approval_id?: string;
    requires_confirmation?: boolean;
    confirmation_prompt?: string;
  };
  policy_decision?: string;
  execution_status?: string;
  secrets_redacted?: boolean;
  redaction_count?: number;
}

export interface AgentResetResponse {
  success: boolean;
  requires_confirmation: boolean;
  message: string;
  total_tasks?: number;
}

export interface SecurityConfig {
  dry_run: boolean;
  require_approval: boolean;
  mask_secrets: boolean;
  denied_operations: string[];
  denied_methods: string[];
  active_policy: string;
}

export interface ApprovalRequestItem {
  approval_id: string;
  tool_name: string;
  method: string;
  path: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED' | 'EXECUTED';
  safe_arguments: Record<string, any>;
  reason: string;
  created_at: string;
  expires_at: string;
  ttl_remaining_seconds: number;
}

export interface AuditLogEntry {
  id: string;
  timestamp: string;
  tool_name: string;
  method: string;
  sanitized_path: string;
  policy_decision: string;
  execution_status: string;
  is_mutating: boolean;
  secrets_redacted: boolean;
  redaction_count: number;
  safe_arguments?: Record<string, any>;
  reason?: string;
  status_code?: number;
  approval_id?: string;
}

export interface IntegrationVariable {
  name: string;
  description: string;
  required: boolean;
  placeholder: string;
}

export interface IntegrationConfigItem {
  id: string;
  name: string;
  transport: string;
  format: string;
  target_file?: string;
  snippet: string;
  prerequisites: string[];
  setup_steps: string[];
  environment_variables: IntegrationVariable[];
  is_available: boolean;
  notes?: string;
}

export interface IntegrationsResponse {
  generation_id: string;
  package_name: string;
  server_path: string;
  base_url: string;
  read_only: boolean;
  available_transports: string[];
  integrations: IntegrationConfigItem[];
}

export interface ConnectionTestResponse {
  success: boolean;
  generation_id: string;
  package_name: string;
  transport: string;
  tool_count: number;
  discovered_tools: string[];
  tested_at: string;
  message: string;
  error?: string;
}

export interface ToolExecuteRequest {
  tool_name: string;
  arguments?: Record<string, any>;
  approval_id?: string;
}

export interface ToolExecuteResponse {
  success: boolean;
  generation_id: string;
  tool_name: string;
  arguments: Record<string, any>;
  result?: any;
  content?: string;
  is_error: boolean;
  status_code?: number;
  policy_decision?: string;
  execution_status?: string;
  secrets_redacted: boolean;
  redaction_count: number;
  requires_approval: boolean;
  approval_id?: string;
  pending_action?: {
    tool_name?: string;
    method?: string;
    path?: string;
    arguments?: Record<string, any>;
    approval_id?: string;
    expires_at?: number;
  };
  error?: string;
}



