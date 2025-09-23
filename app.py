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
    
    # Jobを作成するマニフェストを生成
    job_manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "generateName": f"vm-deployer-"
        },
        "spec": {
            "template": {
                "spec": {
                    "serviceAccountName": "provisioning-sa",
                    "containers": [
                        {
                            "name": "deployer-job",
                            "image": "registry.redhat.io/openshift4/ose-cli:latest",
                            "command": ["/bin/bash", "-c"],
                            "args": [
                                f"set -e; "
                                f"VM_NAME='{normalized_hostname}'; "
                                f"TEMPLATE_URL='https://raw.githubusercontent.com/toaraki/vm-templates/main/vm-fedora-template.yaml'; "
                                f"export PATH=/usr/local/bin:$PATH; "
                                f"ls /usr/local/bin; "
                                f"curl -s -k -L $TEMPLATE_URL | sed 's/{{{{ .hostname }}}}/{normalized_hostname}/g' | oc apply -f -; "
                                f"echo 'Waiting for VM to be ready...'; "
                                f"oc wait --for=condition=ready --timeout=300s vm/$VM_NAME; "
    
                                f"echo 'Getting VM IP address...'; "
                                f"VM_IP=$(oc get vmi $VM_NAME -o jsonpath='{{.status.interfaces[0].ipAddress}}'); "
    
                                f"echo 'Waiting for network connectivity...'; "
                                f"for i in {{1..20}}; do "
                                f"  if nc -z -w5 $(oc get vm $VM_NAME -o jsonpath='{{.status.interfaces[0].ipAddress}}') 22; then "
                                f"    echo 'SSH port is open, VM is ready.'; "
                                f"    exit 0; "
                                f"  else "
                                f"    echo 'SSH port is not open, waiting...'; "
                                f"    sleep 5; "
                                f"  fi; "
                                f"done; "
    
                                f"echo 'VM network not available within timeout.'; "
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

    try:
        api_url = f"{OPENSHIFT_API_URL}/apis/batch/v1/namespaces/{NAMESPACE}/jobs"
        response = requests.post(api_url, json=job_manifest, headers=headers, verify=False)
        if response.status_code == 201:
            return f"<h1>VM デプロイ開始！</h1><p>VM: {hostname} のデプロイを開始しました。</p>"
        else:
            return f"<h1>VM デプロイ失敗</h1><p>エラー: {response.text}</p>"
    except Exception as e:
        return f"<h1>通信エラー</h1><p>エラー: {str(e)}</p>"

if __name__ == '__main__':
    APP_PORT = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=APP_PORT)
