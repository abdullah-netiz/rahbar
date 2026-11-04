# Pin exact version tag (no :latest)
FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html

# Non-root user (provided by nginxinc/nginx-unprivileged image, UID 101)
USER 101

EXPOSE 8080

# Exec form CMD
CMD ["nginx", "-g", "daemon off;"]

