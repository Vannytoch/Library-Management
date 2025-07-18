import base64
with open("Iron_Man.png", "rb") as img:
    print(base64.b64encode(img.read())).decode('utf-8')