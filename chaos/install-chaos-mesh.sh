#!/bin/bash
set -e

echo "Adding Chaos Mesh Helm repository..."
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm repo update

echo "Creating chaos-testing namespace..."
kubectl create ns chaos-testing || true

echo "Installing Chaos Mesh v2.8.0..."
helm install chaos-mesh chaos-mesh/chaos-mesh \
  --namespace chaos-testing \
  --version 2.8.0 \
  --set chaosDaemon.runtime=containerd \
  --set chaosDaemon.socketPath=/run/containerd/containerd.sock

echo "Chaos Mesh installation initiated."
