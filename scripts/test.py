import base64
import json
import requests

with open("workflow.png", "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

payload = {
    "model": "Qwen/Qwen3-VL-8B-Instruct-FP8",
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": "请简单描述以下图片"},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "auto"}}
        ]
    }]
}

resp = requests.post(
    "http://127.0.0.1:1234/v1/chat/completions",
    headers={"Content-Type": "application/json"},
    data=json.dumps(payload),
    timeout=60,
)
print(resp.text)
