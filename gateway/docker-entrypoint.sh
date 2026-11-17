#!/bin/sh
# Render the declarative config with the shared JWT secret, then start Kong.
set -eu

if [ -z "${JWT_SECRET:-}" ]; then
  echo "JWT_SECRET is not set" >&2
  exit 1
fi

# The secret is URL-safe base64 (A-Z a-z 0-9 - _), so '|' is a safe sed delimiter; refuse anything else.
case "$JWT_SECRET" in
  *[!A-Za-z0-9_-]*) echo "JWT_SECRET may only contain A-Z a-z 0-9 - _" >&2; exit 1 ;;
esac

sed "s|\${JWT_SECRET}|${JWT_SECRET}|g" /etc/kong/kong.yml.template > /tmp/kong.yml
export KONG_DECLARATIVE_CONFIG=/tmp/kong.yml

exec /docker-entrypoint.sh kong docker-start
