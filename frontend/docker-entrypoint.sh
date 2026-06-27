#!/bin/sh
# Render the nginx config from the template (only ${SAT_MAX_UPLOAD} is
# substituted; nginx's own $variables are left intact), then run nginx.
set -e
: "${SAT_MAX_UPLOAD:=0}"
envsubst '${SAT_MAX_UPLOAD}' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf
exec nginx -g 'daemon off;'
