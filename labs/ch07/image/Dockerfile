# The skeleton's harness for Google's Agent Runtime: chapter 5's harness, runtime adapter and
# gateway model, started by ch07/image/entrypoint.py with the environment runtime.tf sets.
#
# Build context: companion/labs, so that ch01 and ch05 are visible next to ch07. From there:
#
#   docker build -f ch07/image/Dockerfile -t harness .
#
# The build needs ch07/image/gateway-ca.pem, the Agent Gateway's CA certificate, and fails without
# it. The pipeline writes it from the gateway resource (agentGatewayCard.rootCertificates) before
# the build; *.pem is git-ignored, so it is never committed. Push the image and give runtime.tf its
# digest.
#
# Base image: python:3.12-slim, looked up on Docker Hub's registry API on 2026-10-29: Python
# 3.12.16 on Debian 13 (trixie). The digest is the tag's multi-platform index.
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Chapter 5's pinned set, from wheels only, so no package's build code runs here. The file carries
# no hashes, so there is no --require-hashes. It lists litellm without the [proxy] extra, which
# would pull in litellm-enterprise (proprietary); the second command fails the build if it is here.
COPY ch05/requirements.txt /app/labs/ch05/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore \
        --only-binary=:all: -r /app/labs/ch05/requirements.txt \
 && ! pip show litellm-enterprise

# The Agent Gateway decrypts and inspects outbound TLS, so the image must trust its CA. The openssl
# line prints the certificate's subject and expiry, and fails the build on a file that holds none;
# update-ca-certificates reads only *.crt files from this directory.
COPY ch07/image/gateway-ca.pem /usr/local/share/ca-certificates/agent-gateway.crt
RUN openssl x509 -in /usr/local/share/ca-certificates/agent-gateway.crt -noout -subject -enddate \
 && update-ca-certificates

# The bundle variables Google's page sets for custom containers. httpx (the model calls) and httpx2
# (the MCP client) read SSL_CERT_FILE; without it httpx trusts certifi's bundle, which doesn't hold
# the gateway's CA. requests (the OTLP exporter) reads REQUESTS_CA_BUNDLE, and gRPC the third.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/etc/ssl/certs/ca-certificates.crt

# A user of its own, with no login shell. The files below stay root's, readable but not writable.
RUN groupadd --gid 10001 harness \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin harness

# The code in the repository's layout, because each file finds its neighbours from where it sits:
# the chapter 1 loop the harness runs, the chapter 5 files the entry point imports, and the lock
# that both the harness's check and the model's tool list read.
WORKDIR /app
COPY ch01/agent_loop.py /app/labs/ch01/
COPY ch05/adapter/runtime_adapter.py /app/labs/ch05/adapter/
COPY ch05/harness/client.py ch05/harness/gateway_model.py ch05/harness/rule_model.py /app/labs/ch05/harness/
COPY ch05/tracing/trace_setup.py /app/labs/ch05/tracing/
COPY ch05/mcp-server/tools.lock.json /app/labs/ch05/mcp-server/
COPY ch07/image/entrypoint.py ch07/image/ca_bundle.py /app/labs/ch07/image/

USER 10001:10001
EXPOSE 8080
CMD ["python", "/app/labs/ch07/image/entrypoint.py"]
