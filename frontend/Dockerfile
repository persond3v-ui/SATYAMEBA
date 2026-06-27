# SATYAMEBA edge: nginx serving the SPA and reverse-proxying the cluster.
#
# Set OBFUSCATE=true at build time to ship minified+obfuscated JS to clients.
# (Honest note: this only raises the effort bar for casual snooping; never the
# primary defense. All real authorization is enforced server-side.)
FROM node:20-alpine AS jsbuild
ARG OBFUSCATE=false
WORKDIR /build
COPY public ./public
COPY src ./src
RUN if [ "$OBFUSCATE" = "true" ]; then \
        npm i -g javascript-obfuscator@4 && \
        mkdir -p dist/src && cp -r public/* dist/ && \
        javascript-obfuscator src --output dist/src \
            --compact true --self-defending true --string-array true \
            --string-array-encoding base64 ; \
    else \
        mkdir -p dist && cp -r public/* dist/ && cp -r src dist/src ; \
    fi

FROM nginx:1.27-alpine
RUN rm -rf /usr/share/nginx/html/*
COPY --from=jsbuild /build/dist/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/nginx.conf
COPY proxy_common.conf /etc/nginx/proxy_common.conf
COPY proxy_ws.conf /etc/nginx/proxy_ws.conf
EXPOSE 80 443
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- --no-check-certificate https://localhost/ >/dev/null 2>&1 || exit 1
