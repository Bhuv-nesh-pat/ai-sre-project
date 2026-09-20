"""
Prometheus and PromQL querying tools for the AI SRE Agent.
"""
import requests
from typing import Dict, Any
from langchain_core.tools import tool

PROMETHEUS_URL = "http://localhost:9090" # Target local port-forwarded instance

class PrometheusTool:
    def __init__(self, url: str = PROMETHEUS_URL):
        self.url = url

    def query(self, promql: str) -> str:
        """
        Executes a PromQL query against the Prometheus server.
        """
        try:
            response = requests.get(f"{self.url}/api/v1/query", params={'query': promql}, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Extract relevant metric data to avoid context overflow
            if data.get('status') == 'success':
                results = data['data']['result']
                formatted_results = []
                for res in results:
                    metric = res.get('metric', {})
                    value = res.get('value', [None, None])[1]
                    formatted_results.append(f"Metric: {metric} | Value: {value}")
                return "\n".join(formatted_results) if formatted_results else "No data returned."
            return f"Prometheus API Error: {data}"
        except requests.exceptions.RequestException as e:
            return f"Error connecting to Prometheus at {self.url}: {str(e)}"

prom_client = PrometheusTool()

@tool
def execute_promql(query: str) -> str:
    """
    Executes a PromQL query against the Prometheus server.
    
    Use the following PromQL patterns dynamically based on the suspected fault:
    - Identify CPU starvation caused by StressChaos: 
      sum by (pod) (rate(container_cpu_usage_seconds_total[5m]))
    - Detect impending OOM kills: 
      sum by (pod) (container_memory_working_set_bytes) / sum by (pod) (kube_pod_container_resource_limits{resource="memory"}) * 100
    - Diagnose NetworkChaos latency injections (99th percentile): 
      histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, pod))
    - Assess deployment availability during PodChaos: 
      sum by (deployment) (kube_deployment_status_replicas_available) / sum by (deployment) (kube_deployment_status_replicas)
    """
    return prom_client.query(query)

# Grouped tools for easy import
prom_tools = [execute_promql]
