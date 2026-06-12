# 依赖安装

```python
pip3 install pycryptodome PyExecJS requests rsa flask loguru
# Windows安装
pip install numpy opencv-python onnxruntime torch torchvision

# 服务器安装
pip install numpy opencv-python-headless onnxruntime torch torchvision requests pycryptodome flask loguru PyExecJS2

# Node JS 依赖
npm install
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