#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — host / physical hardening (run as root on every node).
# Owner: Samaraho Mukherjee.
#
# Applies the software-side physical-security hardening and PRINTS the steps that
# can only be done by a human at the BIOS/firmware (those can't be scripted).
# ===========================================================================
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root."; exit 1; }
say() { printf "\033[1;36m[harden]\033[0m %s\n" "$*"; }

# 1) Auto security updates + fail2ban -------------------------------------
say "Installing unattended-upgrades + fail2ban…"
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades fail2ban || true
dpkg-reconfigure -f noninteractive unattended-upgrades || true
systemctl enable --now fail2ban || true

# 2) SSH hardening ---------------------------------------------------------
say "Hardening SSH (key-only, no root password login)…"
SSHD=/etc/ssh/sshd_config.d/satyameba.conf
cat >"$SSHD" <<'EOF'
PasswordAuthentication no
PermitRootLogin prohibit-password
KbdInteractiveAuthentication no
X11Forwarding no
MaxAuthTries 3
EOF
systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true

# 3) Kernel / sysctl hardening --------------------------------------------
say "Applying sysctl hardening…"
cat >/etc/sysctl.d/99-satyameba.conf <<'EOF'
kernel.kptr_restrict=2
kernel.dmesg_restrict=1
kernel.yama.ptrace_scope=2
net.ipv4.conf.all.rp_filter=1
net.ipv4.conf.all.accept_redirects=0
net.ipv6.conf.all.accept_redirects=0
net.ipv4.tcp_syncookies=1
fs.protected_hardlinks=1
fs.protected_symlinks=1
EOF
sysctl --system >/dev/null 2>&1 || true

# 4) Disable USB mass storage (stop data exfil / boot tricks while running) -
say "Blacklisting USB mass-storage (uncomment to fully block)…"
echo 'blacklist usb-storage' >/etc/modprobe.d/satyameba-usb.conf
# update-initramfs -u  # enable if you want it enforced from early boot

# 5) Lock single-user / recovery shells -----------------------------------
say "Requiring root password for single-user mode…"
# Ensure rescue/emergency targets prompt for root (default on Debian); set a root pw.
passwd -S root 2>/dev/null | grep -q ' P ' || say "  -> set a strong root password: 'passwd root'"

cat <<'GUIDE'

============================================================================
 DO THESE AT THE FIRMWARE / PHYSICALLY (cannot be scripted):
   [ ] Set a BIOS/UEFI admin password.
   [ ] Disable boot from USB / network; lock the boot order.
   [ ] Enable Secure Boot.
   [ ] Set a GRUB password (so single-user/init= edits are blocked):
         grub-mkpasswd-pbkdf2  -> add to /etc/grub.d/40_custom -> update-grub
   [ ] LUKS full-disk encryption (run owner-setup/setup_luks_guide.txt — needs
       a reinstall/repartition; TPM-bind the key so a stolen disk won't open).
   [ ] Lock the machines in a rack / cabinet; tamper-evident seals.
============================================================================
GUIDE
say "Software hardening applied. Complete the firmware checklist above."
