$ErrorActionPreference = "Stop"

Write-Host "Creating monitoring namespace..."
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

Write-Host "Installing Prometheus stack..."
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/bundle.yaml

Write-Host "Installing Loki stack..."
kubectl apply -f https://raw.githubusercontent.com/grafana/loki/v2.9.3/production/ksonnet/loki/loki.yaml
kubectl apply -f https://raw.githubusercontent.com/grafana/loki/v2.9.3/production/ksonnet/promtail/promtail.yaml

Write-Host "Installing Google Online Boutique demo microservices..."
kubectl apply -f https://raw.githubusercontent.com/GoogleCloudPlatform/microservices-demo/main/release/kubernetes-manifests.yaml

Write-Host "Deployment started! Check pods with: kubectl get pods -A"
