FROM docker:cli
RUN apk upgrade --no-cache && apk add --no-cache git bash curl

# cosign fuer die Signaturpruefung der Images (siehe update-images.sh,
# UPDATE_VERIFY_SIGNATURES). Version und Pruefsumme sind gepinnt: ein
# Downloader, der irgendein Binary akzeptiert, waere selbst die Luecke, die er
# schliessen soll. Pruefsummen aus cosign_checksums.txt des Releases.
ARG COSIGN_VERSION=3.1.3
ARG COSIGN_SHA256_AMD64=4629c757b7618056f8ddd7e2625ae9fdd94c0372a65049520bc7d9df9efc7f71
ARG COSIGN_SHA256_ARM64=c5d324e091826b0d7a78eb16fef316450b4eb9aaec045611c08ba06f5e73220a
RUN set -eu; \
    case "$(apk --print-arch)" in \
        x86_64)  cosign_arch=amd64; cosign_sha="${COSIGN_SHA256_AMD64}" ;; \
        aarch64) cosign_arch=arm64; cosign_sha="${COSIGN_SHA256_ARM64}" ;; \
        *) echo "cosign: nicht unterstuetzte Architektur $(apk --print-arch)" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/cosign \
        "https://github.com/sigstore/cosign/releases/download/v${COSIGN_VERSION}/cosign-linux-${cosign_arch}"; \
    echo "${cosign_sha}  /usr/local/bin/cosign" | sha256sum -c -; \
    chmod +x /usr/local/bin/cosign; \
    cosign version

COPY update.sh /update.sh
COPY update-images.sh /update-images.sh
COPY region-hook.sh /region-hook.sh
COPY graphhopper-deploy.sh /graphhopper-deploy.sh
COPY switch-region.sh /switch-region.sh
COPY merge-extracts.sh /merge-extracts.sh
RUN chmod +x /update.sh /update-images.sh /region-hook.sh /graphhopper-deploy.sh /switch-region.sh /merge-extracts.sh
# Default entrypoint: git-based updater (for install.sh deployments)
# portainer-stack.yml overrides this with update-images.sh
ENTRYPOINT ["/bin/bash", "/update.sh"]
