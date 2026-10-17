import subprocess
import time
import urllib.request
import json

SSH_KEY = r"C:\Users\mikem\.ssh\id_rsa"
PI_HOST = "mike@192.168.3.169"

def run_ssh(cmd_str):
    cmd = ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", PI_HOST, cmd_str]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout.strip(), res.stderr.strip(), res.returncode

print("[1] Checking process...")
out, err, code = run_ssh("ps aux | grep 'python.*main.py' | grep -v grep")
print("Process:\n", out)

if not out:
    print("[2] Starting main.py in background on Pi...")
    run_ssh("nohup /home/mike/int-raspberry-pi/venv/bin/python /home/mike/int-raspberry-pi/main.py > /home/mike/int-raspberry-pi/conductor.log 2>&1 &")
    time.sleep(3)

print("[3] Testing HTTP endpoints on Pi (Port 8050)...")
for url in ["http://192.168.3.169:8050/api/apps", "http://192.168.3.169:8050/api/system/metrics", "http://192.168.3.169:8050/", "http://192.168.3.169:8050/desktop.html"]:
    try:
        req = urllib.request.urlopen(url, timeout=5)
        print(f"[+] {url} -> Status {req.status}")
    except Exception as e:
        print(f"[!] {url} -> Error: {e}")
