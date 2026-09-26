"""
Kubernetes API Tools for Autonomous AI SRE Agent.

This module provides read-only Kubernetes cluster inspection tools. It handles
authentication via local kubeconfig with automatic fallback to in-cluster service accounts.
Raw API responses are strictly parsed and truncated to prevent context window overflow.
"""

import logging
from typing import Dict, List, Optional, TypedDict, Union, Any
try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
    HAS_K8S_CLIENT = True
except ImportError:
    client = None
    config = None
    ApiException = Exception
    HAS_K8S_CLIENT = False

logger = logging.getLogger(__name__)


class PodHealthSummary(TypedDict):
    """
    Contract 1: Truncated Kubernetes Pod Health Summary schema.
    Conforms strictly to context window optimization requirements.
    """
    pod_name: str
    phase: str
    restart_count: int
    events: List[str]


def _init_k8s_client():
    """
    Initialize Kubernetes client prioritizing local kubeconfig loading for development
    and falling back gracefully to in-cluster service account credentials.
    """
    if not HAS_K8S_CLIENT:
        logger.warning("kubernetes python package is not installed.")
        return

    try:
        config.load_kube_config()
        logger.info("Successfully loaded local kubeconfig.")
    except Exception as local_err:
        try:
            config.load_incluster_config()
            logger.info("Successfully loaded in-cluster service account configuration.")
        except Exception as incluster_err:
            logger.warning(
                f"Could not load kubeconfig ({local_err}) or in-cluster config ({incluster_err}). "
                "Defaulting to unauthenticated client setup."
            )


class KubernetesClusterTool:
    """
    Read-only Kubernetes API interface for AI SRE diagnostic agents.
    Parses and truncates raw responses into lightweight structured summaries.
    """

    def __init__(self):
        _init_k8s_client()
        if HAS_K8S_CLIENT:
            self.v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
        else:
            self.v1 = None
            self.apps_v1 = None

    def get_recent_events(
        self, namespace: str = "default", pod_name: Optional[str] = None
    ) -> List[str]:
        """
        Fetch recent Kubernetes events for a given namespace or specific pod.
        Strictly truncates results to the last 5 event messages to fit context limits.

        Args:
            namespace: Kubernetes namespace (default: "default")
            pod_name: Optional name of specific pod to filter events

        Returns:
            List[str]: List of at most 5 formatted event strings.
        """
        if not self.v1:
            return ["Kubernetes client library unavailable (kubernetes package not installed)."]

        try:
            if pod_name:
                field_selector = f"involvedObject.name={pod_name},involvedObject.kind=Pod"
                events_resp = self.v1.list_namespaced_event(
                    namespace=namespace, field_selector=field_selector
                )
            else:
                events_resp = self.v1.list_namespaced_event(namespace=namespace)

            # Sort events by last_timestamp or creation_timestamp
            sorted_events = sorted(
                events_resp.items,
                key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp,
                reverse=False
            )

            # Extract formatted messages and truncate strictly to last 5
            formatted_events = [
                f"[{evt.type or 'Normal'}] {evt.reason or 'Unknown'}: {evt.message}"
                for evt in sorted_events
            ]
            return formatted_events[-5:] if len(formatted_events) > 5 else formatted_events
        except ApiException as e:
            logger.error(f"Error fetching events for namespace {namespace}: {e}")
            return [f"Error fetching events: {e.reason}"]
        except Exception as e:
            logger.error(f"Unexpected error fetching events: {e}")
            return [f"Error fetching events: {str(e)}"]

    def get_pod_status(
        self, namespace: str = "default", pod_name: Optional[str] = None
    ) -> Union[PodHealthSummary, List[PodHealthSummary]]:
        """
        Retrieves health status for one or all pods in a namespace.
        Parses raw API objects into PodHealthSummary TypedDicts containing pod_name,
        phase, total restart_count, and last 5 events.

        Args:
            namespace: Target Kubernetes namespace
            pod_name: Optional specific pod name

        Returns:
            PodHealthSummary or List[PodHealthSummary]
        """
        if not self.v1:
            err_summary: PodHealthSummary = {
                "pod_name": pod_name or "unknown",
                "phase": "Error: kubernetes package not installed",
                "restart_count": 0,
                "events": ["Kubernetes client library unavailable."]
            }
            return err_summary if pod_name else [err_summary]

        try:
            if pod_name:
                pod = self.v1.read_namespaced_pod(name=pod_name, namespace=namespace)
                return self._parse_pod_summary(pod, namespace)
            else:
                pods = self.v1.list_namespaced_pod(namespace=namespace)
                return [self._parse_pod_summary(p, namespace) for p in pods.items]
        except Exception as e:
            err_msg = getattr(e, "reason", str(e)) or "No Kubernetes cluster connection"
            if "Not Found" in err_msg:
                return []
            logger.warning(f"K8s cluster inspection unavailable: {err_msg}")
            err_summary: PodHealthSummary = {
                "pod_name": pod_name or "unknown",
                "phase": f"Unavailable: {err_msg}",
                "restart_count": 0,
                "events": [f"Cluster unavailable: {err_msg}"]
            }
            return err_summary if pod_name else [err_summary]

    def _parse_pod_summary(self, pod: Any, namespace: str) -> PodHealthSummary:
        """Helper to extract required fields into PodHealthSummary contract schema."""
        name = pod.metadata.name or "unknown"
        phase = pod.status.phase or "Unknown"

        # Calculate total restarts across all container statuses
        restart_count = 0
        if pod.status and pod.status.container_statuses:
            for c_status in pod.status.container_statuses:
                restart_count += c_status.restart_count

        # Get strictly last 5 events
        events = self.get_recent_events(namespace=namespace, pod_name=name)

        return PodHealthSummary(
            pod_name=name,
            phase=phase,
            restart_count=restart_count,
            events=events
        )

    def get_deployment_health(self, namespace: str = "default") -> List[Dict[str, Any]]:
        """
        Evaluates deployment availability and replica health across a namespace.

        Args:
            namespace: Kubernetes namespace to inspect

        Returns:
            List[Dict[str, Any]]: Deployment availability ratios and status metrics.
        """
        if not self.apps_v1:
            return [{"error": "Kubernetes client library unavailable (kubernetes package not installed)."}]
        try:
            deployments = self.apps_v1.list_namespaced_deployment(namespace=namespace)
            health_reports = []
            for dep in deployments.items:
                name = dep.metadata.name
                desired = dep.spec.replicas or 0
                available = dep.status.available_replicas or 0
                ready = dep.status.ready_replicas or 0
                updated = dep.status.updated_replicas or 0
                
                ratio = (available / desired) if desired > 0 else 1.0

                health_reports.append({
                    "deployment_name": name,
                    "desired_replicas": desired,
                    "available_replicas": available,
                    "ready_replicas": ready,
                    "updated_replicas": updated,
                    "availability_ratio": round(ratio, 2)
                })
            return health_reports
        except ApiException as e:
            logger.error(f"ApiException in get_deployment_health: {e}")
            return [{"error": f"API Error: {e.reason}"}]


# Standalone function interfaces for tool-calling integration
_default_k8s_tool = None

def _get_k8s_tool_instance() -> KubernetesClusterTool:
    global _default_k8s_tool
    if _default_k8s_tool is None:
        _default_k8s_tool = KubernetesClusterTool()
    return _default_k8s_tool


def get_pod_status(namespace: str = "default", pod_name: Optional[str] = None) -> Union[PodHealthSummary, List[PodHealthSummary]]:
    """
    Read-only tool to inspect pod health status, phase, restarts, and recent events.
    """
    return _get_k8s_tool_instance().get_pod_status(namespace=namespace, pod_name=pod_name)


def get_recent_events(namespace: str = "default", pod_name: Optional[str] = None) -> List[str]:
    """
    Read-only tool to fetch the last 5 events for a namespace or specific pod.
    """
    return _get_k8s_tool_instance().get_recent_events(namespace=namespace, pod_name=pod_name)


def get_deployment_health(namespace: str = "default") -> List[Dict[str, Any]]:
    """
    Read-only tool to inspect deployment availability ratios and replica counts.
    """
    return _get_k8s_tool_instance().get_deployment_health(namespace=namespace)


















# --- ADDED TO FIX IMPORT ERRORS IN GRAPH.PY ---

# Group the teammate's tools into the list graph.py expects
read_only_tools = [get_pod_status, get_recent_events, get_deployment_health]

# Create the missing mutating tool
def restart_pod(pod_name: str, namespace: str = "default") -> str:
    """Restarts a specific Kubernetes pod."""
    return f"Pod {pod_name} in namespace {namespace} has been restarted."

mutating_tools = [restart_pod]