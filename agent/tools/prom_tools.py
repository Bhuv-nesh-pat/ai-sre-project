"""
Prometheus and Loki Telemetry Tools for Autonomous AI SRE Agent.

This module provides tools for executing PromQL queries and Loki LogQL queries.
It features embedded PromQL query templates in docstrings to guide LLM reasoning,
strict truncation (max 50 log lines), and runtime sanitization of Loki log outputs
to defend against indirect prompt injection and shell syntax execution risks.
"""

import re
import logging
import requests
from typing import Dict, List, Optional, Union, Any

try:
    from prometheus_api_client import PrometheusConnect
    HAS_PROM_CLIENT = True
except ImportError:
    PrometheusConnect = None
    HAS_PROM_CLIENT = False

logger = logging.getLogger(__name__)

PROMETHEUS_DEFAULT_URL = "http://localhost:9090"
LOKI_DEFAULT_URL = "http://localhost:3100"

# Regular expressions for stripping shell execution syntax & indirect prompt injection patterns
SHELL_SYNTAX_REGEX = re.compile(r'[\$\(\);&\|<>`\\]')
PROMPT_INJECTION_PATTERNS = [
    re.compile(r'ignore\s+previous\s+instructions', re.IGNORECASE),
    re.compile(r'ignore\s+above\s+instructions', re.IGNORECASE),
    re.compile(r'system\s*:\s*', re.IGNORECASE),
    re.compile(r'execute\s+kubectl', re.IGNORECASE),
    re.compile(r'rm\s+-rf', re.IGNORECASE),
    re.compile(r'drop\s+database', re.IGNORECASE),
]


def sanitize_loki_logs(raw_logs: Union[str, List[str]], max_lines: int = 50) -> str:
    """
    Sanitizes raw log strings or lists of log entries to defend against indirect prompt injection
    and shell execution vulnerability exploits.

    1. Enforces strict truncation to a maximum of the most recent `max_lines` (default 50).
    2. Strips shell execution syntax characters ($ ( ) ; & | < > ` \\).
    3. Neutralizes malicious prompt injection instruction patterns (e.g. 'Ignore previous instructions').
    4. Combines results into a single sanitized string payload.

    Args:
        raw_logs: String or list of log strings received from Loki.
        max_lines: Maximum number of recent log lines to include (max 50).

    Returns:
        str: Single sanitized log text payload.
    """
    if isinstance(raw_logs, str):
        lines = raw_logs.strip().splitlines()
    elif isinstance(raw_logs, list):
        lines = [str(line) for line in raw_logs]
    else:
        lines = [str(raw_logs)]

    # Limit to maximum 50 most recent log lines
    recent_lines = lines[-max_lines:] if len(lines) > max_lines else lines

    sanitized_lines = []
    for line in recent_lines:
        # Strip shell execution syntax characters
        clean_line = SHELL_SYNTAX_REGEX.sub('', line)
        
        # Neutralize indirect prompt injection patterns
        for pattern in PROMPT_INJECTION_PATTERNS:
            clean_line = pattern.sub('[REDACTED_SECURITY_THREAT]', clean_line)
            
        sanitized_lines.append(clean_line)

    return "\n".join(sanitized_lines)


class PrometheusTool:
    """
    Prometheus PromQL Diagnostic Tool.
    Exposes quantitative metric querying capabilities with embedded PromQL templates.
    """

    def __init__(self, prometheus_url: str = PROMETHEUS_DEFAULT_URL):
        self.url = prometheus_url.rstrip("/")
        if PrometheusConnect is not None:
            try:
                self.prom_client = PrometheusConnect(url=self.url, disable_ssl=True)
            except Exception as e:
                logger.warning(f"Could not initialize PrometheusConnect client: {e}")
                self.prom_client = None
        else:
            self.prom_client = None

    def query_cpu_usage_rate(self, time_window: str = "5m") -> Dict[str, Any]:
        """
        Calculates per-second CPU core usage rate per pod to identify StressChaos starvation.

        Embedded PromQL Template:
            sum by (pod) (rate(container_cpu_usage_seconds_total[5m]))

        Args:
            time_window: PromQL rate evaluation window (default "5m")

        Returns:
            Dict[str, Any]: Prometheus query result per pod.
        """
        query = f"sum by (pod) (rate(container_cpu_usage_seconds_total[{time_window}]))"
        return self.execute_promql(query)

    def query_memory_limit_utilization(self) -> Dict[str, Any]:
        """
        Compares pod working set memory against container memory limits to detect impending OOM kills.

        Embedded PromQL Template:
            sum by (pod) (container_memory_working_set_bytes) / sum by (pod) (kube_pod_container_resource_limits{resource="memory"}) * 100

        Returns:
            Dict[str, Any]: Memory utilization percentage by pod.
        """
        query = (
            'sum by (pod) (container_memory_working_set_bytes) / '
            'sum by (pod) (kube_pod_container_resource_limits{resource="memory"}) * 100'
        )
        return self.execute_promql(query)

    def query_p99_latency(self, time_window: str = "5m") -> Dict[str, Any]:
        """
        Measures 99th percentile request latency across microservices to diagnose NetworkChaos latency injections.

        Embedded PromQL Template:
            histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))

        Args:
            time_window: Rate evaluation window (default "5m")

        Returns:
            Dict[str, Any]: P99 latency quantiles.
        """
        query = f"histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[{time_window}])) by (le))"
        return self.execute_promql(query)

    def query_deployment_availability_ratio(self) -> Dict[str, Any]:
        """
        Evaluates the ratio of available replicas to desired replicas during PodChaos experiments.

        Embedded PromQL Template:
            sum by (deployment) (kube_deployment_status_replicas_available) / sum by (deployment) (kube_deployment_status_replicas_desired)

        Returns:
            Dict[str, Any]: Available vs desired replica ratios by deployment.
        """
        query = (
            "sum by (deployment) (kube_deployment_status_replicas_available) / "
            "sum by (deployment) (kube_deployment_status_replicas_desired)"
        )
        return self.execute_promql(query)

    def execute_promql(self, query: str) -> Dict[str, Any]:
        """
        Executes an arbitrary PromQL instant query against Prometheus API.

        Args:
            query: Valid PromQL query string

        Returns:
            Dict[str, Any]: Prometheus query response payload.
        """
        if self.prom_client:
            try:
                res = self.prom_client.custom_query(query=query)
                return {"status": "success", "data": res}
            except Exception as e:
                logger.warning(f"PrometheusConnect query failed, falling back to HTTP: {e}")

        # Fallback HTTP query
        try:
            endpoint = f"{self.url}/api/v1/query"
            response = requests.get(endpoint, params={"query": query}, timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error executing PromQL query '{query}': {e}")
            return {"status": "error", "message": str(e), "query": query}


class LokiLogTool:
    """
    Loki LogQL Aggregation Tool with Indirect Prompt Injection Security Protections.
    Strictly limits returned log output to max 50 sanitized log lines.
    """

    def __init__(self, loki_url: str = LOKI_DEFAULT_URL):
        self.url = loki_url.rstrip("/")

    def query_logs(self, logql_query: str, limit: int = 50) -> str:
        """
        Executes a LogQL query against Loki, enforces maximum 50 line truncation,
        and applies security sanitization to strip shell syntax and prompt injection strings.

        Embedded LogQL Example:
            {app="cartservice"} |= "error"

        Args:
            logql_query: LogQL filter expression
            limit: Maximum log lines to request (capped strictly at 50)

        Returns:
            str: Single sanitized, truncated string of log lines.
        """
        max_allowed_limit = min(limit, 50)
        try:
            endpoint = f"{self.url}/loki/api/v1/query_range"
            params = {
                "query": logql_query,
                "limit": max_allowed_limit
            }
            response = requests.get(endpoint, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()

            extracted_lines = []
            results = data.get("data", {}).get("result", [])
            for stream in results:
                values = stream.get("values", [])
                for ts_val in values:
                    if isinstance(ts_val, list) and len(ts_val) > 1:
                        extracted_lines.append(ts_val[1])
                    else:
                        extracted_lines.append(str(ts_val))

            return sanitize_loki_logs(extracted_lines, max_lines=max_allowed_limit)

        except Exception as e:
            logger.error(f"Error querying Loki with query '{logql_query}': {e}")
            return sanitize_loki_logs([f"Error querying Loki: {str(e)}"], max_lines=max_allowed_limit)


# Standalone function wrappers for easy registration in agent tools
_default_prom_tool = PrometheusTool()
_default_loki_tool = LokiLogTool()


def get_pod_cpu_usage(pod_name: str) -> Dict[str, Any]:
    """
    Fetches the CPU usage rate for a specific pod. Pass the exact pod name.
    """
    query = f'sum by (pod) (rate(container_cpu_usage_seconds_total{{pod="{pod_name}"}}[5m]))'
    return _default_prom_tool.execute_promql(query)


def get_pod_memory_usage(pod_name: str) -> Dict[str, Any]:
    """
    Fetches the Memory utilization percentage for a specific pod. Pass the exact pod name.
    """
    query = (
        f'sum by (pod) (container_memory_working_set_bytes{{pod="{pod_name}"}}) / '
        f'sum by (pod) (kube_pod_container_resource_limits{{resource="memory", pod="{pod_name}"}}) * 100'
    )
    return _default_prom_tool.execute_promql(query)

def get_service_p99_latency(service_name: str) -> Dict[str, Any]:
    """
    Fetches the 99th percentile request latency for a specific service. Pass the exact service name.
    """
    query = f'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{{app="{service_name}"}}[5m])) by (le))'
    return _default_prom_tool.execute_promql(query)

def query_loki_logs(logql_query: str, limit: int = 50) -> str:
    """
    Queries Loki logs with mandatory runtime sanitization (stripping shell characters & prompt injection)
    and returning a maximum of 50 log lines as a single string.
    
    CRITICAL: Loki only accepts valid LogQL syntax starting with a label selector. You must use stream selectors like {app="cartservice"} or {namespace="default"}. Do NOT use Prometheus metric names or custom field selectors like type:Pod. To query pod resource limits, CPU, or memory metrics, you MUST use the get_pod_cpu_usage or get_pod_memory_usage tools instead.
    """
    return _default_loki_tool.query_logs(logql_query, limit=limit)









# --- ADDED TO FIX IMPORT ERRORS IN GRAPH.PY ---
prom_tools = [get_pod_cpu_usage, get_pod_memory_usage, get_service_p99_latency, query_loki_logs]