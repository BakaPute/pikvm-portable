FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server passwd && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /run/sshd /project/tests && touch /__rc13_isolated__ && ln -sf /usr/local/bin/python3 /usr/bin/python3 && ln -sf /usr/sbin/sshd /usr/bin/sshd && ln -sf /usr/sbin/useradd /usr/bin/useradd && ln -sf /usr/sbin/usermod /usr/bin/usermod
ENTRYPOINT ["python3", "-B", "/project/tests/rc13-ssh-integration.py"]
