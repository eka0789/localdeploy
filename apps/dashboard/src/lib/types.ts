/** Shared API types (mirrors FastAPI schemas). */

export interface User {
  id: string;
  username: string;
  email: string;
  role_id: string | null;
  role_name: string | null;
  is_active: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string | null;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  application_count: number;
}

export interface Application {
  id: string;
  project_id: string | null;
  name: string;
  slug: string;
  description: string | null;
  source_type: "git" | "dockerfile" | "compose" | "image" | "upload";
  project_type: string | null;
  git_url: string | null;
  git_branch: string | null;
  status: string;
  container_name: string | null;
  container_port: number;
  health_check_path: string | null;
  auto_deploy: boolean;
  cpu_limit: number | null;
  memory_limit_mb: number | null;
  last_deployed_at: string | null;
  created_at: string;
  domain_count: number;
  domains: string[];
}

export interface ApplicationDetail extends Application {
  git_username: string | null;
  dockerfile_path: string | null;
  docker_compose_path: string | null;
  docker_image: string | null;
  install_command: string | null;
  build_command: string | null;
  start_command: string | null;
  container_id: string | null;
  has_git_password: boolean;
}

export interface Deployment {
  id: string;
  application_id: string;
  application_name: string | null;
  application_slug: string | null;
  status: "queued" | "running" | "success" | "failed" | "cancelled" | "timed_out";
  trigger: string;
  git_branch: string | null;
  git_commit_sha: string | null;
  git_message: string | null;
  image_tag: string | null;
  source_type: string | null;
  project_type: string | null;
  error_message: string | null;
  build_duration_ms: number | null;
  created_by_name: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface Domain {
  id: string;
  application_id: string;
  application_name: string | null;
  application_slug: string | null;
  hostname: string;
  target_port: number | null;
  ssl_enabled: boolean;
  ssl_status: string;
  ssl_issuer: string | null;
  ssl_expires_at: string | null;
  verified_at: string | null;
  is_primary: boolean;
  created_at: string;
}

export interface EnvVar {
  id: string;
  key: string;
  is_secret: boolean;
  has_value: boolean;
  created_at: string;
}

export interface DatabaseInstance {
  id: string;
  name: string;
  engine: string;
  image: string;
  version: string;
  username: string;
  database_name: string | null;
  port: number;
  published_port: number | null;
  container_name: string;
  volume_name: string;
  status: string;
  last_error: string | null;
  last_health_at: string | null;
  created_at: string;
}

export interface BackupRecord {
  id: string;
  target_type: string;
  target_id: string;
  target_name: string;
  status: string;
  file: string;
  file_size_bytes: number | null;
  checksum: string | null;
  restore_of_id: string | null;
  created_by_name: string | null;
  error_message: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Volume {
  id: string | null;
  name: string;
  driver: string;
  mountpoint: string | null;
  in_use: boolean;
  managed: boolean;
  created_at: string | null;
}

export interface DockerContainer {
  id: string;
  name: string;
  image: string;
  status: string;
  state: string | null;
  created: string | null;
  ports: Record<string, unknown>;
  labels: Record<string, string>;
  managed: boolean;
}

export interface DockerImage {
  id: string;
  tags: string[];
  size_mb: number;
  created: string | null;
}

export interface DockerNetwork {
  id: string;
  name: string;
  driver: string | null;
  internal: boolean;
  containers: string[];
}

export interface DockerStatus {
  available: boolean;
  error?: string;
  hint?: string;
  version?: string;
  api_version?: string;
  os?: string;
  architecture?: string;
  cpus?: number;
  total_memory_mb?: number;
  containers?: number;
  containers_running?: number;
  containers_paused?: number;
  containers_stopped?: number;
  images?: number;
  server_version?: string;
}

export interface ServerSnapshot {
  cpu_percent: number;
  cpu_count: number;
  memory_used_mb: number;
  memory_total_mb: number;
  memory_percent: number;
  swap_percent: number;
  disk_used_gb: number;
  disk_total_gb: number;
  disk_percent: number;
  net_rx_bps: number;
  net_tx_bps: number;
  load_1: number | null;
  uptime_seconds: number;
  platform: string;
  docker: DockerStatus;
}

export interface ServerMetricPoint {
  sampled_at: string;
  cpu_percent: number;
  memory_percent: number;
  memory_used_mb: number;
  disk_percent: number;
  net_rx_bps: number;
  net_tx_bps: number;
}

export interface AppMetric {
  application_id: string;
  name: string;
  slug: string;
  status: string;
  project_type: string | null;
  cpu_percent: number;
  memory_usage_mb: number;
  memory_limit_mb: number;
  net_rx_bytes: number;
  net_tx_bytes: number;
  sampled_at: string | null;
}

export interface Overview {
  applications: { total: number; running: number; stopped: number; error: number; deploying: number };
  deployments_failed_24h: number;
  server: ServerSnapshot;
  recent_deployments: Array<{
    id: string;
    application_id: string;
    application_name: string;
    status: string;
    trigger: string;
    git_message: string | null;
    created_at: string;
    build_duration_ms: number | null;
  }>;
  recent_activity: Array<{ action: string; username: string | null; resource_type: string | null; created_at: string }>;
}

export interface Tunnel {
  id: string;
  name: string;
  status: string;
  public_hostnames: string[];
  last_connected_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface AuditLogEntry {
  id: string;
  username: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  detail: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}

export interface Role {
  id: string;
  name: string;
  description: string | null;
  is_system: boolean;
  permission_keys: string[];
}
