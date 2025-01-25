from flask import Flask, request, jsonify
import json
import base64
import re

app = Flask(__name__)

def mutate_pod_spec(pod_spec):
    """Add /dev/shm volume and securityContext capabilities to the pod spec."""
    # Add /dev/shm volume
    dev_shm_volume = {
        "name": "dshm",
        "emptyDir": {
            "medium": "Memory"
        }
    }
    volume_mount = {
        "name": "dshm",
        "mountPath": "/dev/shm"
    }

    # Add securityContext capabilities
    security_context = {
        "capabilities": {
            "add": ["IPC_LOCK", "SYS_NICE"]
        }
    }

    # Ensure volumes exist
    if "volumes" not in pod_spec:
        pod_spec["volumes"] = []
    pod_spec["volumes"].append(dev_shm_volume)

    # Add volume mounts and securityContext to all containers
    for container in pod_spec.get("containers", []):
        if "volumeMounts" not in container:
            container["volumeMounts"] = []
        container["volumeMounts"].append(volume_mount)

        # Ensure securityContext exists and add capabilities
        if "securityContext" not in container:
            container["securityContext"] = {}
        if "capabilities" not in container["securityContext"]:
            container["securityContext"]["capabilities"] = {"add": []}
        container["securityContext"]["capabilities"]["add"].extend(["IPC_LOCK", "SYS_NICE"])

def check_gpu_selector(resource_spec):
    """Check if the resource spec includes a matchLabels selector for NVIDIA GPU product."""
    selector = resource_spec.get("selector", {})
    match_labels = selector.get("matchLabels", {})
    return "nvidia.com/gpu.product" in match_labels

@app.route('/mutate', methods=['POST'])
def mutate():
    """Handle mutation requests."""
    admission_review = request.get_json()
    response = {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "uid": admission_review["request"]["uid"],
            "allowed": True
        }
    }

    try:
        # Get the namespace and validate against both patterns
        namespace = admission_review["request"]["namespace"]
        if not (namespace == "hpadmin" or re.match(r"^gs-.*", namespace)):
            # Skip mutation for non-matching namespaces
            return jsonify(response)

        # Get the resource kind
        resource_kind = admission_review["request"]["kind"]["kind"]

        # Extract the resource spec depending on the resource type
        if resource_kind == "Pod":
            resource_spec = admission_review["request"]["object"]["spec"]
        elif resource_kind in {"Deployment", "StatefulSet", "Job"}:
            resource_spec = admission_review["request"]["object"]["spec"]
        else:
            # Unsupported resource type
            return jsonify(response)

        # Check if the resource spec includes a matchLabels selector for NVIDIA GPU product
        if check_gpu_selector(resource_spec):
            # For resources like Deployment, StatefulSet, or Job, we need to get the pod spec from the template
            if resource_kind in {"Deployment", "StatefulSet", "Job"}:
                pod_spec = resource_spec["template"]["spec"]
            else:  # For Pod, the resource_spec is the pod_spec
                pod_spec = resource_spec

            # Mutate the pod spec
            mutate_pod_spec(pod_spec)

            # Generate JSON patch
            patch = []
            if resource_kind == "Pod":
                patch.append({
                    "op": "add",
                    "path": "/spec/volumes",
                    "value": pod_spec["volumes"]
                })
                for idx, container in enumerate(pod_spec.get("containers", [])):
                    patch.append({
                        "op": "add",
                        "path": f"/spec/containers/{idx}/volumeMounts",
                        "value": container["volumeMounts"]
                    })
                    patch.append({
                        "op": "add",
                        "path": f"/spec/containers/{idx}/securityContext",
                        "value": container["securityContext"]
                    })
            else:  # For Deployments, StatefulSets, Jobs
                patch.append({
                    "op": "add",
                    "path": "/spec/template/spec/volumes",
                    "value": pod_spec["volumes"]
                })
                for idx, container in enumerate(pod_spec.get("containers", [])):
                    patch.append({
                        "op": "add",
                        "path": f"/spec/template/spec/containers/{idx}/volumeMounts",
                        "value": container["volumeMounts"]
                    })
                    patch.append({
                        "op": "add",
                        "path": f"/spec/template/spec/containers/{idx}/securityContext",
                        "value": container["securityContext"]
                    })

            # Encode the patch as a base64 string
            patch_bytes = json.dumps(patch).encode("utf-8")
            response["response"]["patchType"] = "JSONPatch"
            response["response"]["patch"] = base64.b64encode(patch_bytes).decode("utf-8")
    except Exception as e:
        print(f"Error mutating request: {e}")

    return jsonify(response)

@app.route('/healthz', methods=['GET'])
def healthz():
    return "ok", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8443, ssl_context=('/etc/webhook/certs/tls.crt', '/etc/webhook/certs/tls.key'))
