import os
import re
import requests
import json
import secrets
import string
import subprocess
import logging
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

# 環境変数を読み込み
OPENSHIFT_API_URL = os.environ.get('OPENSHIFT_API_URL')
TOKEN = os.environ.get('TOKEN')
NAMESPACE = os.environ.get('NAMESPACE')

@app.route('/', methods=['GET'])
def index():
##    return """
##    <h1>VM デプロイ</h1>
##    <p>VMのホスト名を入力してください。</p>
##    <form action="/deploy" method="post">
##        <label for="hostname">ホスト名：</label>
##        <input type="text" id="hostname" name="hostname" placeholder="例: my-fedora-vm" required>
##        <button type="submit">デプロイ</button>
##    </form>
##    """
      return render_template('index.html')

@app.route('/deploy', methods=['POST'])
def deploy():
    hostname = request.form['hostname']
    
    # サーバーサイドでのホスト名検証
    # RFC 1123 DNS ラベルのルールに準拠しているか確認
    # 小文字の英数字とハイフンのみ、先頭と末尾は英数字
    # if not re.match(r'^[a-z0-9]([-a-z0-9]*[a-z0-9])?$', hostname):
    if not re.match(r'^[a-z]([-a-z0-9]*[a-z0-9])?$', hostname) or len(hostname) > 63:
        # ホスト名が無効な場合
        flash('無効なホスト名です。英数字とハイフンのみ使用可能で、ハイフンで始まり/終わることはできません。', 'error')
        return redirect(url_for('index'))
    
    # ホスト名をKubernetesの命名規則に準拠させる
    normalized_hostname = re.sub(r'[^a-z0-9-]', '-', hostname.lower())
    alphabet = string.ascii_letters + string.digits
    guestpassword = ''.join(secrets.choice(alphabet) for i in range(8))


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
                            #"image": "image-registry.openshift-image-registry.svc:5000/user20-vm-iac/job-runner-image:latest",
                            "image": "image-registry.openshift-image-registry.svc:5000/virt-provision/job-runner-image:latest",
                            "command": ["/bin/bash", "-c"],
                            "args": [
                                #f"/bin/bash",
                                #"-c",
                                f"set -e; "
                                f"VM_NAME='{normalized_hostname}'; "
                                f"TEMPLATE_URL='https://raw.githubusercontent.com/toaraki/vm-templates/main/vm-fedora-template.yaml'; "
                                f"echo 'Deploying VM...'; "
                                f"curl -s -k -L $TEMPLATE_URL | sed 's/{{{{ .hostname }}}}/{normalized_hostname}/g' | sed 's/{{{{ .password }}}}/{guestpassword}/g' | oc apply -f -; "
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
                                
                                f"for i in {{1..30}}; do "
                                f"  STATUS_CODE=$(curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 http://$VM_IP:3000 || true); "
                                f"  if [ \"$STATUS_CODE\" -ge 200 ] && [ \"$STATUS_CODE\" -lt 400 ]; then "
                                f"    echo 'Application is ready.'; "
                                # Dynamically get the Route URL from the cluster
                                f"      ROUTER_URL=$(oc get route {normalized_hostname} -o jsonpath='{{.spec.host}}'); "
                                f"      echo 'Creating ConfigMap with VM URL...'; "
                                f"      oc create configmap {job_name}-url --from-literal=url=https://$ROUTER_URL; "
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
    ##try:
    ##    api_url = f"{OPENSHIFT_API_URL}/apis/batch/v1/namespaces/{NAMESPACE}/jobs"
    ##    response = requests.post(api_url, json=job_manifest, headers=headers, verify=False)
    ##    if response.status_code == 201:
    ##        return redirect(url_for('status_page', job_name=job_name))
    ##    else:
    ##        return f"<h1>デプロイ失敗</h1><p>エラー: {response.text}</p>"
    ##except Exception as e:
    ##    return f"<h1>通信エラー</h1><p>エラー: {str(e)}</p>"
    try:
        api_url = f"{OPENSHIFT_API_URL}/apis/batch/v1/namespaces/{NAMESPACE}/jobs"
        response = requests.post(api_url, json=job_manifest, headers=headers, verify=False)
        
        # OpenShift APIからのレスポンスを詳細にチェック
        if response.status_code == 201:
            logging.info(f"Successfully created Job: {job_name}")
            return redirect(url_for('status_page', job_name=job_name))
        
        elif response.status_code == 401:
            logging.error("OpenShift API Unauthorized. Check your TOKEN.")
            return "<h1>デプロイ失敗</h1><p>エラー: 認証に失敗しました。トークンを確認してください。</p>", 401

        elif response.status_code == 403:
            logging.error(f"OpenShift API Forbidden. Check ServiceAccount permissions. Response: {response.text}")
            return "<h1>デプロイ失敗</h1><p>エラー: 権限がありません。サービスアカウントの権限を確認してください。</p>", 403

        else:
            logging.error(f"Failed to create Job. Status: {response.status_code}, Response: {response.text}")
            return f"<h1>デプロイ失敗</h1><p>エラー: OpenShift APIから予期せぬエラーが返されました。<br>詳細: {response.text}</p>", response.status_code

    except requests.exceptions.RequestException as e:
        logging.error(f"Network or API communication error: {str(e)}")
        return f"<h1>通信エラー</h1><p>エラー: OpenShift APIに接続できません。<br>詳細: {str(e)}</p>", 503 # Service Unavailable

    except Exception as e:
        # 上記以外の予期せぬエラー
        logging.exception("An unexpected error occurred during deployment.")
        return f"<h1>デプロイ処理で予期せぬエラーが発生しました</h1><p>エラー: {str(e)}</p>", 500


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


from flask import jsonify, Response

@app.route('/api/job-logs/<job_name>', methods=['GET'])
def get_job_logs(job_name):
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }

    try:
        # JobのPod名を取得
        pod_names_url = f"{OPENSHIFT_API_URL}/api/v1/namespaces/{NAMESPACE}/pods?labelSelector=job-name%3D{job_name}"
        pod_response = requests.get(pod_names_url, headers=headers, verify=False)
        pod_items = pod_response.json().get('items', [])
        
        if not pod_items:
            # Podがまだ見つからない場合
            return jsonify({"status": "error", "message": "Pod not available yet."})

        # Podのログを取得
        pod_name = pod_items[0]['metadata']['name']
        logs_url = f"{OPENSHIFT_API_URL}/api/v1/namespaces/{NAMESPACE}/pods/{pod_name}/log"
        
        logs_response = requests.get(logs_url, headers=headers, verify=False)
        
        if logs_response.status_code == 200:
            return Response(logs_response.text, mimetype="text/plain")
        else:
            return jsonify({"status": "error", "message": "Log stream not available."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


if __name__ == '__main__':
    APP_PORT = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=APP_PORT)


