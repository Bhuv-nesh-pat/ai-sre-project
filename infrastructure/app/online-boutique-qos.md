# Online Boutique QoS Modification Instructions

To establish guaranteed and burstable Quality of Service (QoS) boundaries for the Google Online Boutique application, you must explicitly inject `requests` and `limits` into the Deployment manifests. This is critical for Chaos Mesh `StressChaos` experiments to reliably trigger CPU throttling or Out-Of-Memory (OOM) kills.

Below are the required YAML snippets to add to the `cartservice` Deployment (and other microservices as needed) under `spec.template.spec.containers[0].resources`.

## Guaranteed QoS (Requests == Limits)

For a Guaranteed QoS class, set the `requests` equal to the `limits`.

```yaml
        resources:
          requests:
            cpu: "200m"
            memory: "256Mi"
          limits:
            cpu: "200m"
            memory: "256Mi"
```

## Burstable QoS (Requests < Limits)

For a Burstable QoS class, set the `requests` lower than the `limits`. This allows the container to burst up to the limit if node resources are available, but it is more susceptible to eviction or throttling during node starvation.

```yaml
        resources:
          requests:
            cpu: "100m"
            memory: "128Mi"
          limits:
            cpu: "300m"
            memory: "512Mi"
```

## Applying to `cartservice`

If using Kustomize, you can apply these patches over the baseline `cartservice` deployment. Otherwise, directly edit the `cartservice` section in the monolithic `kubernetes-manifests.yaml` for Online Boutique.
