FROM docker:cli
RUN apk upgrade --no-cache && apk add --no-cache git bash curl
COPY update.sh /update.sh
COPY update-images.sh /update-images.sh
COPY region-hook.sh /region-hook.sh
COPY switch-region.sh /switch-region.sh
RUN chmod +x /update.sh /update-images.sh /region-hook.sh /switch-region.sh
# Default entrypoint: git-based updater (for install.sh deployments)
# portainer-stack.yml overrides this with update-images.sh
ENTRYPOINT ["/bin/bash", "/update.sh"]
