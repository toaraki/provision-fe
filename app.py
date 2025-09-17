import os
import requests
from flask import Flask, render_template, request, redirect, url_for

# PORT環境変数からポート番号を読み込む（デフォルトは8080）
APP_PORT = int(os.environ.get('PORT', 8080))
app = Flask(__name__)

# OpenShift APIのエンドポイントと認証情報を環境変数から取得
OPENSHIFT_API_URL = os.environ.get('OPENSHIFT_API_URL')
TOKEN = os.environ.get('TOKEN')
NAMESPACE = os.environ.get('NAMESPACE')

@app.route('/', methods=['GET'])
def index():
    return """
    <h1>コンテナデプロイ</h1>
    <p>デプロイしたいコンテナイメージ名を入力してください。{NAMESPACE}</p>
    <form action="/deploy" method="post">
        <label for="image_name">コンテナイメージ名：</label>
        <input type="text" id="image_name" name="image_name" placeholder="例: quay.io/openshift/hello-openshift" required>
        <button type="submit">デプロイ</button>
    </form>
    """

@app.route('/deploy', methods=['POST'])
def deploy():
    image_name = request.form['image_name']
    
    # ユーザー入力からJobマニフェストを生成
    job_manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "generateName": "container-deployer-"
        },
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "deployer-job",
                            "image": "docker.io/curlimages/curl", # curlを使ってOpenShift APIを叩くイメージ
                            "command": [
                                "/bin/sh",
                                "-c",
                                f"curl -s -k --header 'Authorization: Bearer {TOKEN}' --request POST --data '{{\"apiVersion\":\"v1\",\"kind\":\"Pod\",\"metadata\":{{\"generateName\":\"{image_name.replace('/', '-')}-pod-\"}},\"spec\":{{\"containers\":[{{\"name\":\"{image_name.replace('/', '-')}-container\",\"image\":\"{image_name}\"}}],\"restartPolicy\":\"Never\"}}}}' {OPENSHIFT_API_URL}/api/v1/namespaces/{NAMESPACE}/pods"
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

    # JobマニフェストをOpenShift APIにPOST
    try:
        api_url = f"{OPENSHIFT_API_URL}/apis/batch/v1/namespaces/{NAMESPACE}/jobs"
        response = requests.post(api_url, json=job_manifest, headers=headers, verify=False)
        if response.status_code == 201:
            return f"<h1>デプロイ開始！</h1><p>イメージ: {image_name} のデプロイを開始しました。</p>"
        else:
            return f"<h1>デプロイ失敗</h1><p>エラー: {response.text}</p>"
    except Exception as e:
        return f"<h1>通信エラー</h1><p>エラー: {str(e)}</p>"

if __name__ == '__main__':
    ## app.run(host='0.0.0.0', port=8081)
    app.run(host='0.0.0.0', port=APP_PORT)
