FROM kong:3.9.4

COPY kong.yml.template /etc/kong/kong.yml.template
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/gateway-entrypoint.sh

ENV KONG_DATABASE=off \
    KONG_PROXY_LISTEN="0.0.0.0:8000" \
    KONG_ADMIN_LISTEN=off \
    KONG_STATUS_LISTEN="0.0.0.0:8001" \
    KONG_PROXY_ACCESS_LOG=off \
    KONG_PROXY_ERROR_LOG=/dev/stderr \
    KONG_HEADERS="latency_tokens" \
    KONG_NGINX_HTTP_CLIENT_MAX_BODY_SIZE=2m

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 CMD kong health

ENTRYPOINT ["/usr/local/bin/gateway-entrypoint.sh"]
