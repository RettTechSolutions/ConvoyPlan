FROM docker:24-cli
RUN apk add --no-cache git bash
COPY update.sh /update.sh
RUN chmod +x /update.sh
ENTRYPOINT ["/bin/bash", "/update.sh"]
