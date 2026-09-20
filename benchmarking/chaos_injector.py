import logging
from kubernetes import client, config
from kubernetes.client.rest import ApiException

class ChaosInjector:
    def __init__(self, target_namespace: str = "default"):
        """
        Initializes the ChaosInjector by loading the local kubeconfig as a priority.
        Falls back to in-cluster config if local config fails.
        """
        self.target_namespace = target_namespace
        
        try:
            # Prioritize local kubeconfig for development and testing
            config.load_kube_config()
            logging.info("Loaded local kubeconfig.")
        except config.config_exception.ConfigException:
            # Fall back to in-cluster config for pod-based execution
            try:
                config.load_incluster_config()
                logging.info("Loaded in-cluster kubeconfig.")
            except Exception as e:
                logging.error("Failed to load Kubernetes configuration.")
                raise e
        
        self.api = client.CustomObjectsApi()
        self.group = "chaos-mesh.org"
        self.version = "v1alpha1"

    def inject_fault(self, fault_type: str, target_labels: dict, duration_sec: int):
        """
        Injects a specified fault using Chaos Mesh CRDs.
        """
        if fault_type == "NetworkChaos":
            plural = "networkchaos"
            payload = self._build_network_chaos_payload(target_labels, duration_sec)
        elif fault_type == "StressChaos":
            plural = "stresschaos"
            payload = self._build_stress_chaos_payload(target_labels, duration_sec)
        else:
            raise ValueError(f"Unsupported fault_type: {fault_type}. Choose 'NetworkChaos' or 'StressChaos'.")
        
        try:
            response = self.api.create_namespaced_custom_object(
                group=self.group,
                version=self.version,
                namespace=self.target_namespace,
                plural=plural,
                body=payload
            )
            logging.info(f"Successfully injected {fault_type}.")
            return response
        except ApiException as e:
            logging.error(f"Exception when creating {fault_type}: {e}")
            raise e

    def _build_network_chaos_payload(self, target_labels: dict, duration_sec: int) -> dict:
        """
        Constructs the internal JSON payload for a NetworkChaos packet delay.
        """
        return {
            "apiVersion": f"{self.group}/{self.version}",
            "kind": "NetworkChaos",
            "metadata": {
                "generateName": "network-delay-",
                "namespace": self.target_namespace,
            },
            "spec": {
                "action": "delay",
                "mode": "all",
                "selector": {
                    "namespaces": [self.target_namespace],
                    "labelSelectors": target_labels
                },
                "delay": {
                    "latency": "200ms",
                    "correlation": "100",
                    "jitter": "0ms"
                },
                "duration": f"{duration_sec}s"
            }
        }

    def _build_stress_chaos_payload(self, target_labels: dict, duration_sec: int) -> dict:
        """
        Constructs the internal JSON payload for a StressChaos memory worker exhaustion.
        """
        return {
            "apiVersion": f"{self.group}/{self.version}",
            "kind": "StressChaos",
            "metadata": {
                "generateName": "memory-stress-",
                "namespace": self.target_namespace,
            },
            "spec": {
                "mode": "all",
                "selector": {
                    "namespaces": [self.target_namespace],
                    "labelSelectors": target_labels
                },
                "stressors": {
                    "memory": {
                        "workers": 2, # Number of workers to consume memory
                        "size": "256MB" # Amount of memory to consume per worker
                    }
                },
                "duration": f"{duration_sec}s"
            }
        }
