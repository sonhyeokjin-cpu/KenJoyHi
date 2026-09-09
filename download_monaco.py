import os
import urllib.request
from pathlib import Path

BASE_URL = "https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.52.2/min/vs"
BASE_DIR = "static/js/monaco-editor/v0.52.2/min/vs"

# Create directories
os.makedirs(f"{BASE_DIR}/editor", exist_ok=True)
os.makedirs(f"{BASE_DIR}/basic-languages/python", exist_ok=True)
os.makedirs(f"{BASE_DIR}/language/python", exist_ok=True)

# Files to download
files = [
    "loader.js",
    "editor/editor.main.js",
    "editor/editor.main.css",
    "editor/editor.main.nls.js",
    "basic-languages/python/python.js",
    "language/python/python.js"
]

# Download files
for file in files:
    url = f"{BASE_URL}/{file}"
    local_path = f"{BASE_DIR}/{file}"
    print(f"Downloading {url} to {local_path}")
    try:
        urllib.request.urlretrieve(url, local_path)
        print(f"Successfully downloaded {file}")
    except Exception as e:
        print(f"Error downloading {file}: {str(e)}") 