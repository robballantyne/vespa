import tempfile
from functools import cache

import requests


@cache
def get_cert_file_path():
    cert_url = "https://console.vast.ai/static/jvastai_root.cer"
    response = requests.get(cert_url)
    response.raise_for_status()
    # Use a temporary file that is not deleted on close
    with tempfile.NamedTemporaryFile(delete=False, suffix=".cer", mode="wb") as f:
        f.write(response.content)
        return f.name
