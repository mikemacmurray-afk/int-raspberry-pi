import os
import sys
import paramiko

HETZNER_HOST = "89.167.37.84"
HETZNER_USER = "deploy"
SSH_KEY_PATH = os.path.expanduser("~/.ssh/id_rsa")

def safe_print(text: str):
    """Print text safely on Windows terminals with cp1252 encoding."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))

def get_ssh_client():
    key = paramiko.RSAKey.from_private_key_file(SSH_KEY_PATH)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HETZNER_HOST, username=HETZNER_USER, pkey=key, timeout=10)
    return client

def run_remote(cmd: str):
    client = get_ssh_client()
    try:
        safe_print(f"[*] Executing on Hetzner: {cmd}")
        stdin, stdout, stderr = client.exec_command(cmd)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        safe_print(f"[*] Exit code: {code}")
        if out.strip():
            safe_print(f"--- STDOUT ---\n{out.strip()}")
        if err.strip():
            safe_print(f"--- STDERR ---\n{err.strip()}")
        return code, out, err
    finally:
        client.close()

def upload_file(local_path: str, remote_path: str):
    client = get_ssh_client()
    try:
        sftp = client.open_sftp()
        safe_print(f"[*] Uploading {local_path} -> {remote_path}")
        sftp.put(local_path, remote_path)
        sftp.close()
        safe_print("[+] Upload complete.")
    finally:
        client.close()

def upload_content(content: str, remote_path: str):
    client = get_ssh_client()
    try:
        sftp = client.open_sftp()
        safe_print(f"[*] Writing content -> {remote_path}")
        with sftp.file(remote_path, "w") as f:
            f.write(content)
        sftp.close()
        safe_print("[+] Remote file written.")
    finally:
        client.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = " ".join(sys.argv[1:])
        run_remote(cmd)
    else:
        run_remote("uname -a; whoami; python3 --version")
