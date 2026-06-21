import os, urllib.request, urllib.parse, json

key = os.environ.get("JQUANTS_API_KEY", "")
print("キーの長さ:", len(key), "先頭:", key[:6] if key else "(空)")

url = "https://api.jquants.com/v2/equities/bars/daily?" + urllib.parse.urlencode(
    {"code": "1306", "from": "2024-01-01", "to": "2024-03-31"})
req = urllib.request.Request(url, headers={"x-api-key": key})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
        print("成功! 件数:", len(data.get("data", [])))
        if data.get("data"):
            print("サンプル:", data["data"][0])
except urllib.error.HTTPError as e:
    print("HTTPエラー:", e.code)
    print("詳細:", e.read().decode())   # ← これがエラーの中身を見せてくれる