#!/bin/sh
# Runs as www-data on every container start, after install/upgrade.
# Idempotent: re-applies logging, audit and cron settings (PRD INF-09, INF-10).
set -eu

occ() { php /var/www/html/occ "$@"; }

if ! occ status --output=json 2>/dev/null | grep -q '"installed":true'; then
    echo "[thesis] Nextcloud not installed yet; skipping configuration hook"
    exit 0
fi

echo "[thesis] Applying logging, audit and background-job settings"

# Persistent file logs on the shared, agent-readable volume
occ config:system:set log_type --value=file
occ config:system:set logfile --value=/var/log/nextcloud/nextcloud.log
occ config:system:set log_type_audit --value=file
occ config:system:set logfile_audit --value=/var/log/nextcloud/audit.log
# 1 = info: needed so audit events and normal activity are written
occ config:system:set loglevel --type=integer --value=1
occ config:system:set logtimezone --value=UTC
occ config:system:set logdateformat --value='Y-m-d\TH:i:s.uP'
occ config:system:set log_rotate_size --type=integer --value=104857600

# Audit log app (logins, file read/write/delete, sharing, user management)
occ app:enable admin_audit

# System cron (the "cron" service runs cron.php every 5 minutes)
occ background:cron

# Housekeeping recommended by Nextcloud's admin overview
occ config:system:set default_phone_region --value=ID
# 18:00 UTC = 02:00 WITA: start of the 4-hour window for heavy background jobs
occ config:system:set maintenance_window_start --type=integer --value=18

echo "[thesis] Done"
