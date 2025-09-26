import os
import re
import requests
import json
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

# 環境変数を読み込み
OPENSHIFT_API_URL = os.environ.get('OPENSHIFT_API_URL')
TOKEN = os.environ.get('TOKEN')
NAMESPACE = os.environ.get('NAMESPACE')

@app.route('/', methods=['GET'])
def index():
    return """
    <h1>VM デプロイ</h1>
    <p>VMのホスト名を入力してください。</p>
    <form action="/deploy" method="post">
        <label for="hostname">ホスト名：</label>
        <input type="text" id="hostname" name="hostname" placeholder="例: my-fedora-vm" required>
        <button type="submit">デプロイ</button>
    </form>
    """

@app.route('/deploy', methods=['POST'])
def deploy():
    hostname = request.form['hostname']
    
    # ホスト名をKubernetesの命名規則に準拠させる
    normalized_hostname = re.sub(r'[^a-z0-9-]', '-', hostname.lower())
    # Jobを追跡するための一意な名前を生成
    job_name = f"vm-deployer-{normalized_hostname}-{os.urandom(4).hex()}"
    
    # Jobを作成するマニフェストを生成
    job_manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name
        },
        "spec": {
            "template": {
                "spec": {
                    "serviceAccountName": "provisioning-sa",
                    "containers": [
                        {
                            "name": "deployer-job",
                            # "image": "registry.redhat.io/openshift4/ose-cli:latest",
                            "image": "image-registry.openshift-image-registry.svc:5000/user20-vm-iac/job-runner-image:latest",
                            "command": ["/bin/bash", "-c"],
                            "args": [
                                #f"/bin/bash",
                                #"-c",
                                f"set -e; "
                                f"VM_NAME='{normalized_hostname}'; "
                                f"TEMPLATE_URL='https://raw.githubusercontent.com/toaraki/vm-templates/main/vm-fedora-template.yaml'; "
                                f"echo 'Deploying VM...'; "
                                f"curl -s -k -L $TEMPLATE_URL | sed 's/{{{{ .hostname }}}}/{normalized_hostname}/g' | oc apply -f -; "
                                f"echo 'Waiting for VM to be ready...'; "
                                f"oc wait --for=condition=ready --timeout=300s vm/$VM_NAME; "
                                f"echo 'Getting VM IP address...'; "
                                f"VM_IP=''; "
                                f"for i in {{1..60}}; do "
                                f"  VM_IP=$(oc get vmi $VM_NAME -o jsonpath='{{.status.interfaces[0].ipAddress}}' || true); "
                                f"  if [ ! -z '$VM_IP' ]; then "
                                f"    echo 'IP address found: '$VM_IP; "
                                f"    break; "
                                f"  fi; "
                                f"  echo 'IP not available, waiting...'; "
                                f"  sleep 2; "
                                f"done; "
                                f"if [ -z '$VM_IP' ]; then echo 'VM IP address not found within timeout.'; exit 1; fi; "
                                f"echo 'Waiting for application to be ready...'; "
                                
                                f"for i in {{1..20}}; do "
                                f"  STATUS_CODE=$(curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 http://$VM_IP:3000 || true); "
                                f"  if [ \"$STATUS_CODE\" -ge 200 ] && [ \"$STATUS_CODE\" -lt 400 ]; then "
                                f"    echo 'Application is ready.'; "
                                # Dynamically get the Route URL from the cluster
                                f"      ROUTER_URL=$(oc get route {normalized_hostname} -o jsonpath='{{.spec.host}}'); "
                                f"      echo 'Creating ConfigMap with VM URL...'; "
                                f"      oc create configmap {job_name}-url --from-literal=url=https://$ROUTER_URL; "
                                f"      echo 'VM_URL=https://$ROUTER_URL'; "
                                f"    exit 0; "
                                f"  else "
                                f"    echo 'Application not ready, waiting...'; "
                                f"    sleep 5; "
                                f"  fi; "
                                f"done; "
                                f"echo 'Application not ready within timeout.'; "
                                f"exit 1;"
                            ]
                        }
                    ],
                    "restartPolicy": "Never"
                }
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }

    # JobをOpenShift APIに送信し、ステータスページにリダイレクト
    try:
        api_url = f"{OPENSHIFT_API_URL}/apis/batch/v1/namespaces/{NAMESPACE}/jobs"
        response = requests.post(api_url, json=job_manifest, headers=headers, verify=False)
        if response.status_code == 201:
            return redirect(url_for('status_page', job_name=job_name))
        else:
            return f"<h1>デプロイ失敗</h1><p>エラー: {response.text}</p>"
    except Exception as e:
        return f"<h1>通信エラー</h1><p>エラー: {str(e)}</p>"



from flask import jsonify

@app.route('/status/<job_name>')
def status_page(job_name):
    # status.html テンプレートをレンダリングし、ジョブ名を渡す
    return render_template('status.html', job_name=job_name)

@app.route('/api/job-status/<job_name>')
def get_job_status(job_name):
    # JobのステータスをチェックするAPIエンドポイント
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        # Check Job status first
        api_url = f"{OPENSHIFT_API_URL}/apis/batch/v1/namespaces/{NAMESPACE}/jobs/{job_name}"
        response = requests.get(api_url, headers=headers, verify=False)
        job = response.json()

        status = job.get('status', {})
        if status.get('succeeded'):
            # Job succeeded, now check for the ConfigMap
            configmap_url = f"{OPENSHIFT_API_URL}/api/v1/namespaces/{NAMESPACE}/configmaps/{job_name}-url"
            configmap_response = requests.get(configmap_url, headers=headers, verify=False)
            
            if configmap_response.status_code == 200:
                configmap_data = configmap_response.json().get('data', {})
                vm_url = configmap_data.get('url', '')
                return jsonify({"status": "succeeded", "url": vm_url})
            else:
                return jsonify({"status": "error", "message": "Job succeeded but URL not found"})

        elif status.get('failed'):
            return jsonify({"status": "failed", "error": "Job failed"})
        else:
            return jsonify({"status": "running", "message": "VMをデプロイ中です..."})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    APP_PORT = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=APP_PORT)


