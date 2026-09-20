"""
Kubernetes API tools for the AI SRE Agent.
"""
from typing import Dict, Any, List
from kubernetes import client, config
from langchain_core.tools import tool

class KubernetesClusterTool:
    def __init__(self):
        try:
            # Prioritize local kubeconfig for development and interacting with Kind
            config.load_kube_config()
        except config.config_exception.ConfigException:
            # Fall back to in-cluster service account tokens if deployed in cluster
            config.load_incluster_config()
        self.v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

    def get_pod_status(self, namespace: str = "default") -> str:
        """Retrieves the status of pods in the specified namespace."""
        pods = self.v1.list_namespaced_pod(namespace)
        results = []
        for pod in pods.items:
            # Truncate JSON response to prevent context window exhaustion
            restarts = sum(container.restart_count for container in (pod.status.container_statuses or []))
            results.append(
                f"Pod: {pod.metadata.name} | Phase: {pod.status.phase} | Restarts: {restarts}"
            )
        return "\n".join(results)

    def get_recent_events(self, namespace: str = "default", limit: int = 20) -> str:
        """Retrieves recent events in the specified namespace."""
        events = self.v1.list_namespaced_event(namespace)
        # Sort by creation timestamp descending and truncate
        sorted_events = sorted(
            events.items, 
            key=lambda x: x.metadata.creation_timestamp or '', 
            reverse=True
        )[:limit]
        
        results = []
        for event in sorted_events:
             results.append(f"Reason: {event.reason} | Message: {event.message} | Object: {event.involved_object.name}")
        return "\n".join(results)

    def get_deployment_health(self, namespace: str = "default") -> str:
        """Retrieves health status of deployments in the specified namespace."""
        deployments = self.apps_v1.list_namespaced_deployment(namespace)
        results = []
        for dep in deployments.items:
             ready = dep.status.ready_replicas or 0
             desired = dep.spec.replicas or 0
             results.append(f"Deployment: {dep.metadata.name} | Ready/Desired: {ready}/{desired}")
        return "\n".join(results)

    def delete_pod(self, pod_name: str, namespace: str = "default") -> str:
        """Mutating action to delete a pod for remediation."""
        self.v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
        return f"Pod {pod_name} deleted in namespace {namespace}."

k8s_client = KubernetesClusterTool()

@tool
def get_pod_status(namespace: str = "default") -> str:
    """Retrieves the status of pods in the specified namespace."""
    return k8s_client.get_pod_status(namespace)

@tool
def get_recent_events(namespace: str = "default") -> str:
    """Retrieves recent events in the specified namespace."""
    return k8s_client.get_recent_events(namespace)

@tool
def get_deployment_health(namespace: str = "default") -> str:
    """Retrieves health status of deployments in the specified namespace."""
    return k8s_client.get_deployment_health(namespace)

@tool
def restart_pod(pod_name: str, namespace: str = "default") -> str:
    """Mutating action to restart a pod by deleting it."""
    return k8s_client.delete_pod(pod_name, namespace)

# Grouped tools for easy import
read_only_tools = [get_pod_status, get_recent_events, get_deployment_health]
mutating_tools = [restart_pod]
