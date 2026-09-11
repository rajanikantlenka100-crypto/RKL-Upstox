# DigitalOcean Deployment

This package is for a dedicated Ubuntu LTS host with a reserved/static public IP. Real orders remain disabled unless the operator explicitly supplies a protected production environment with `EXECUTION_MODE=PRODUCTION`, `REAL_ORDERS_ENABLED=ON`, a valid Upstox order IP, and a passed runtime preflight.

## Layout

- `systemd/rkl-upstox.service`: non-root service definition.
- `nginx/rkl-upstox.conf`: localhost-only reverse-proxy template; add authentication and TLS before remote access.
- `env.example`: deployment variables without credentials.
- `deploy.sh`: test, migrate/start, readiness-gated deployment.
- `rollback.sh`: restore the previous release and restart only after validation.

## Installation outline

1. Create an unprivileged `rkl` user and `/opt/rkl-upstox` release directory.
2. Attach a reserved DigitalOcean IP and restrict SSH/application access with the firewall.
3. Copy the release and a secret environment file readable only by `rkl`.
4. Install the service and run `deploy.sh` as an operator with the required service permissions.
5. Keep the dashboard bound to localhost behind authenticated HTTPS reverse proxy access.
6. Verify `/health` for liveness and `/ready` for operational readiness.

The deployment scripts never create orders. Broker-backed sandbox or production validation remains an explicit, separately authorized operation.
