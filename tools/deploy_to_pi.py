"""
Deploys updated conductor code, family messages app, and configs to Pi 5 (192.168.3.169).
"""

import os
import sys
import paramiko

PI_HOST = "192.168.3.169"
PI_USER = "mike"
SSH_KEY_PATH = os.path.expanduser("~/.ssh/id_rsa")
REMOTE_ROOT = "/home/mike/int-raspberry-pi"

FILES_TO_DEPLOY = [
    ("config/config.yaml", f"{REMOTE_ROOT}/config/config.yaml"),
    ("config/settings.py", f"{REMOTE_ROOT}/config/settings.py"),
    ("core/messages_manager.py", f"{REMOTE_ROOT}/core/messages_manager.py"),
    ("web/server.py", f"{REMOTE_ROOT}/web/server.py"),
    ("apps/family_messages/manifest.json", f"{REMOTE_ROOT}/apps/family_messages/manifest.json"),
    ("apps/family_messages/index.html", f"{REMOTE_ROOT}/apps/family_messages/index.html"),
    ("web/static/desktop.html", f"{REMOTE_ROOT}/web/static/desktop.html"),
    ("web/static/index.html", f"{REMOTE_ROOT}/web/static/index.html"),
    ("web/static/portal.html", f"{REMOTE_ROOT}/web/static/portal.html"),
    ("web/static/github_hub.html", f"{REMOTE_ROOT}/web/static/github_hub.html"),
    ("web/static/system_diag.html", f"{REMOTE_ROOT}/web/static/system_diag.html"),
]

def safe_print(text: str):
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))

def deploy():
    safe_print(f"[*] Connecting to Pi 5 ({PI_HOST})...")
    key = paramiko.RSAKey.from_private_key_file(SSH_KEY_PATH)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(PI_HOST, username=PI_USER, pkey=key, timeout=10)

    try:
        # Ensure directories exist
        stdin, stdout, stderr = client.exec_command(f"mkdir -p {REMOTE_ROOT}/apps/family_messages {REMOTE_ROOT}/data")
        stdout.channel.recv_exit_status()

        sftp = client.open_sftp()
        for local_file, remote_file in FILES_TO_DEPLOY:
            if os.path.exists(local_file):
                safe_print(f"[*] Transferring {local_file} -> {remote_file}")
                sftp.put(local_file, remote_file)
            else:
                safe_print(f"[!] Warning: local file {local_file} not found, skipping.")
        sftp.close()

        # Restart conductor process / service
        safe_print("[*] Restarting home conductor on Pi 5...")
        restart_cmd = (
            "echo 'M4n4g3r$' | sudo -S systemctl restart home-conductor.service 2>/dev/null || "
            "(pkill -f 'main.py' || true; sleep 2; cd /home/mike/int-raspberry-pi && "
            "nohup /home/mike/int-raspberry-pi/.venv/bin/python3 main.py > conductor.log 2>&1 &)"
        )
        stdin, stdout, stderr = client.exec_command(restart_cmd)
        stdout.channel.recv_exit_status()
        safe_print("[+] Conductor restarted.")

        # Give it a moment to boot
        import time
        time.sleep(3)

        # Health check
        stdin, stdout, stderr = client.exec_command("curl -s http://127.0.0.1:8050/api/family/state")
        out = stdout.read().decode("utf-8", errors="replace")
        safe_print(f"[+] Local Pi 5 family state preview:\n{out[:300]}")

    finally:
        client.close()

if __name__ == "__main__":
    deploy()
