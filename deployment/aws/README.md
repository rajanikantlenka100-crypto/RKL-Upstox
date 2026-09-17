# RKL Upstox AWS EC2 Deployment Preparation

This directory prepares an Ubuntu 24.04 EC2 deployment. It does not connect to AWS, deploy, restart services, or enable live orders.

## Required host preparation

```bash
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3-pip curl rsync
sudo useradd --system --home /var/lib/rkl-upstox --shell /usr/sbin/nologin rkl || true
sudo install -d -o rkl -g rkl /opt/rkl-upstox /var/lib/rkl-upstox/data /var/lib/rkl-upstox/logs /etc/rkl-upstox
```

The EC2 public address must be the Upstox-registered static order IP. Do not substitute the local Windows public IP.

## Protected environment

Copy `env.example` to `/etc/rkl-upstox/rkl-upstox.env`, edit it on the EC2 host, and protect it:

```bash
sudo install -o rkl -g rkl -m 600 env.example /etc/rkl-upstox/rkl-upstox.env
```

Populate broker credentials and `UPSTOX_ORDER_IP` only through the approved operator process. Keep `OPEN_BROWSER=OFF` on EC2.

## Install and validate

```bash
sudo rsync -a --delete --exclude .env --exclude data/ --exclude logs/ ./ /opt/rkl-upstox/release/
sudo python3.12 -m venv /opt/rkl-upstox/venv
sudo /opt/rkl-upstox/venv/bin/pip install -r /opt/rkl-upstox/release/requirements.txt
sudo chown -R rkl:rkl /opt/rkl-upstox /var/lib/rkl-upstox
cd /opt/rkl-upstox/release
sudo -u rkl /opt/rkl-upstox/venv/bin/python -m pytest -q
sudo -u rkl /opt/rkl-upstox/venv/bin/python -m compileall -q .
```

Install the service only after the operator has reviewed the exact release and protected environment:

```bash
sudo install -o root -g root -m 644 systemd/rkl-upstox.service /etc/systemd/system/rkl-upstox.service
sudo systemctl daemon-reload
sudo systemctl enable rkl-upstox
sudo systemctl restart rkl-upstox
sudo systemctl status rkl-upstox --no-pager -l
journalctl -u rkl-upstox -n 200 --no-pager
```

## Readiness checks

```bash
curl --fail http://127.0.0.1:8876/health
curl --fail http://127.0.0.1:8876/ready
```

`/ready` must remain unavailable/degraded until authentication, history, broker reconciliation, order reconciliation, database health, and production preflight all pass. A failed static-IP check must remain a blocker.

## Stop and rollback

```bash
sudo systemctl stop rkl-upstox
sudo systemctl disable rkl-upstox
sudo systemctl status rkl-upstox --no-pager -l
```

Do not enable real execution or place a live order as part of installation validation.
