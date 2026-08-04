#!/usr/bin/env bash
#
# One-shot preparation of a fresh Hetzner Ubuntu 24.04 server.
# Run ONCE, as root, on the new box:
#
#   ssh root@<SERVER_IP>
#   curl -fsSL https://raw.githubusercontent.com/... -o bootstrap.sh   # or scp it up
#   bash bootstrap.sh
#
# Deliberately does NOT harden SSH — that step can lock you out, so it is left
# manual and is printed at the end with a safety procedure. Everything here is
# idempotent and safe to re-run.
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
APP_DIR="${APP_DIR:-/opt/dental}"

if [[ $EUID -ne 0 ]]; then
	echo "Run this as root on the server." >&2
	exit 1
fi

echo "==> Updating base system"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get upgrade -y
apt-get install -y ca-certificates curl git rsync unattended-upgrades

echo "==> Creating '${DEPLOY_USER}' user"
if ! id -u "$DEPLOY_USER" >/dev/null 2>&1; then
	adduser --disabled-password --gecos "" "$DEPLOY_USER"
fi
usermod -aG sudo "$DEPLOY_USER"

# The account has no password (key-only SSH), so sudo needs NOPASSWD or it is
# unusable. Safe here because password authentication is disabled below.
cat >/etc/sudoers.d/90-"$DEPLOY_USER" <<EOF
${DEPLOY_USER} ALL=(ALL) NOPASSWD:ALL
EOF
chmod 440 /etc/sudoers.d/90-"$DEPLOY_USER"

echo "==> Copying SSH keys from root"
if [[ -f /root/.ssh/authorized_keys ]]; then
	install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/${DEPLOY_USER}/.ssh"
	install -m 600 -o "$DEPLOY_USER" -g "$DEPLOY_USER" \
		/root/.ssh/authorized_keys "/home/${DEPLOY_USER}/.ssh/authorized_keys"
else
	echo "!! /root/.ssh/authorized_keys not found."
	echo "!! Add your public key to /home/${DEPLOY_USER}/.ssh/authorized_keys before hardening SSH."
fi

echo "==> Enabling automatic security updates"
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

echo "==> Installing Docker"
if ! command -v docker >/dev/null 2>&1; then
	curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "$DEPLOY_USER"
systemctl enable --now docker

echo "==> Creating ${APP_DIR}"
mkdir -p "${APP_DIR}/www"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "$APP_DIR"

cat <<EOF

============================================================================
Bootstrap complete.

REMAINING MANUAL STEPS
----------------------------------------------------------------------------
1. Verify key-based login as '${DEPLOY_USER}' FROM A SECOND TERMINAL,
   while keeping this root session open:

       ssh ${DEPLOY_USER}@<SERVER_IP>

   Do not continue until that works. If you harden SSH first and the key is
   wrong, you are locked out and need Hetzner's rescue console.

2. Only once step 1 succeeds, harden SSH:

       cat > /etc/ssh/sshd_config.d/99-hardening.conf <<'CONF'
       PermitRootLogin no
       PasswordAuthentication no
       CONF
       systemctl restart ssh

   Then confirm a NEW ssh session still works before closing this one.

3. Firewall — in the Hetzner Cloud Console (not on this box), create a
   firewall with inbound rules and apply it to this server:

       22/tcp    your IP (or 0.0.0.0/0 if your IP is dynamic)
       80/tcp    0.0.0.0/0     <- required for Let's Encrypt
       443/tcp   0.0.0.0/0
       443/udp   0.0.0.0/0     <- HTTP/3

4. Clone the repo and create the env file:

       cd ${APP_DIR}
       git clone -b preprod git@github.com:codecraftsee/dental-ordination-api.git app
       cp app/.env.preprod.example ${APP_DIR}/.env
       nano ${APP_DIR}/.env          # fill in real values
       chmod 600 ${APP_DIR}/.env

   Private repo? Generate a deploy key first:
       ssh-keygen -t ed25519 -C "hetzner-preprod" -f ~/.ssh/id_ed25519 -N ""
       cat ~/.ssh/id_ed25519.pub
   Add it at GitHub -> repo -> Settings -> Deploy keys (read-only).

5. First deploy:

       cd ${APP_DIR}/app
       docker compose --env-file ${APP_DIR}/.env up -d --build
============================================================================
EOF
