import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
from hetzner_manager import get_ssh_client, run_remote, upload_content, safe_print

def update_nginx():
    client = get_ssh_client()
    try:
        sftp = client.open_sftp()
        with sftp.file('/etc/nginx/sites-enabled/learnai.betterfreelife.com', 'r') as f:
            content = f.read().decode('utf-8')

        if 'location /family-relay/' in content:
            safe_print("[*] /family-relay/ already present in nginx config.")
            return

        relay_block = """
    # Family Messages Cloud Relay
    location /family-relay/ {
        proxy_pass http://127.0.0.1:8090/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
"""
        target = "    listen 443 ssl;"
        new_content = content.replace(target, relay_block + "\n" + target)

        # Write to temp file then move
        with sftp.file('/tmp/learnai.nginx.conf', 'w') as f:
            f.write(new_content)
        sftp.close()

        code, out, err = run_remote(
            "sudo cp /etc/nginx/sites-enabled/learnai.betterfreelife.com /etc/nginx/sites-enabled/learnai.betterfreelife.com.bak-relay && "
            "sudo cp /tmp/learnai.nginx.conf /etc/nginx/sites-enabled/learnai.betterfreelife.com && "
            "sudo nginx -t && sudo systemctl reload nginx"
        )
        if code == 0:
            safe_print("[+] Nginx reloaded successfully with /family-relay/ proxy!")
        else:
            safe_print(f"[-] Nginx reload failed: {err}")
    finally:
        client.close()

if __name__ == "__main__":
    update_nginx()
