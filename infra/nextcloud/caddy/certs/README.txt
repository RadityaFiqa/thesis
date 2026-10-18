Only needed if CADDY_TLS is set to use a Cloudflare Origin CA certificate.

Cloudflare dashboard -> SSL/TLS -> Origin Server -> Create Certificate
  hostnames: nextcloud.gbb-landu.my.id, wazuh.gbb-landu.my.id (or *.gbb-landu.my.id)
Save the certificate as origin.pem and the private key as origin-key.pem here,
then in nextcloud/.env set:
  CADDY_TLS=/etc/caddy/certs/origin.pem /etc/caddy/certs/origin-key.pem
and set Cloudflare SSL/TLS mode to "Full (strict)". Restart: docker compose up -d caddy
