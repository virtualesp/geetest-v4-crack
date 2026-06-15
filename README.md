# 依赖安装

```python
pip install pycryptodome PyExecJS requests rsa flask loguru
# Windows安装
pip install numpy opencv-python onnxruntime torch torchvision

```
## 服务器安装
```python

# 安装python3.10
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3.10-distutils

# 1. 进入项目目录
cd geetest-v4-crack

# 2. 创建一个名为 venv 的 Python 3.10 虚拟环境
python3.10 -m venv venv

# 3. 激活虚拟环境
source venv/bin/activate

# 服务器安装依赖
pip install numpy opencv-python-headless onnxruntime torch torchvision requests pycryptodome flask loguru PyExecJS2 rsa

# Node JS 依赖
npm install

# 后台运行
nohup python flask_word.py > flask.log 2>&1 &
```

# 使用

```python

import requests

url = "http://127.0.0.1:5008/word/verify"

headers = {
    "Content-Type": "application/json"
}

data = {
    'captcha_id': '283ed0bd78efd3d7899888027e9a851f'
}

response = requests.post(url, headers=headers, json=data)

print(response.status_code)
print(response.text)
```