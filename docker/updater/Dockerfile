FROM docker:24-cli
RUN apk add --no-cache git bash curl
COPY update.sh /update.sh
COPY update-images.sh /update-images.sh
RUN chmod +x /update.sh /update-images.sh
# Default entrypoint: git-based updater (for install.sh deployments)
# portainer-stack.yml overrides this with update-images.sh
ENTRYPOINT ["/bin/bash", "/update.sh"]
