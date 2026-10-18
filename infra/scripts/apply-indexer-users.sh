#!/usr/bin/env bash
# Initialize / re-apply the indexer security configuration (users, roles) from
# the files in the container, incl. siem/config/wazuh_indexer/internal_users.yml.
# Needed if the security index was never initialized ("Not yet initialized")
# or was initialized earlier with other passwords. Does not touch indexed data.
#   sudo ./scripts/apply-indexer-users.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../siem"
docker compose exec -T wazuh.indexer bash -c '
  set -e
  D=/usr/share/wazuh-indexer
  export JAVA_HOME=$D/jdk
  bash $D/plugins/opensearch-security/tools/securityadmin.sh \
    -cd $D/config/opensearch-security/ \
    -icl -nhnv -h localhost -p 9200 \
    -cacert $D/config/certs/root-ca.pem \
    -cert $D/config/certs/admin.pem \
    -key $D/config/certs/admin-key.pem'
echo "Applied. Restarting dashboard and manager so they reconnect with the new passwords."
docker compose restart wazuh.dashboard wazuh.manager
