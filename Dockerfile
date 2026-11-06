FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

COPY installers/forticlient_vpn_7.4.3.5411_amd64.deb /tmp/forticlient-vpn.deb

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
    && sed -i 's|http://|https://|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
      /tmp/forticlient-vpn.deb dbus iproute2 iputils-ping microsocks supervisor sudo \
    && rm -f /tmp/forticlient-vpn.deb \
    && rm -rf /var/lib/apt/lists/*

COPY supervisord.conf /etc/supervisor/conf.d/forticlient.conf
COPY start-forticlient-service /usr/local/bin/start-forticlient-service
COPY start-container /usr/local/bin/start-container
COPY vpn_session.py /usr/local/bin/vpn-login
RUN chmod +x /usr/local/bin/start-forticlient-service /usr/local/bin/start-container /usr/local/bin/vpn-login \
    && printf '%s\n' 'ubuntu ALL=(root) NOPASSWD: /usr/local/bin/start-forticlient-service ""' \
       > /etc/sudoers.d/forticlient \
    && chmod 0440 /etc/sudoers.d/forticlient \
    && visudo -cf /etc/sudoers.d/forticlient \
    && install -d -m 0700 -o ubuntu -g ubuntu /run/user/1000

ENV XDG_RUNTIME_DIR=/run/user/1000
EXPOSE 1080
USER ubuntu
CMD ["/usr/bin/dbus-run-session", "--", "/usr/local/bin/start-container"]
