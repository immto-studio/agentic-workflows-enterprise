# The skeleton's harness as a Microsoft Foundry hosted agent: chapter 7's image for Google's Agent
# Runtime, with the same entry point (ch07/image/entrypoint.py, reused rather than copied) serving
# Foundry's routes, GET /readiness and POST /invocations, on port 8088.
#
# Build context: companion/labs, so that ch01, ch05 and ch07 are visible. From there:
#
#   docker build --platform linux/amd64 -f ch08/image/Dockerfile -t harness-foundry .
#
# The build needs ch08/image/private-ca.pem, Larkspur's private root CA, and fails without it. The
# reader writes it there before the build, as chapter 7's pipeline writes gateway-ca.pem; *.pem is
# git-ignored, so it is never committed.
#
# Foundry runs linux/amd64 images only. Push the image to Azure Container Registry and give the
# hosted agent's version its digest. The project's managed identity pulls it and needs Container
# Registry Repository Reader on the registry. A registry behind a private endpoint works only for
# projects created after 25 June 2026; an older project needs the registry's public endpoint.
#
# What differs from Google's image (ch07/image/Dockerfile):
# - No egress proxy CA and none of the three bundle variables. Google's Agent Gateway needs its
#   CA built into the image. Foundry's egress controls (in preview) inspect TLS as well, but the
#   runtime injects its egress proxy's CA into the sandbox and sets SSL_CERT_FILE,
#   REQUESTS_CA_BUNDLE and GRPC_DEFAULT_SSL_ROOTS_FILE_PATH itself. That CA rotates, about every
#   30 days, and differs between clusters, and Microsoft says not to persist it in an image. A
#   firewall on the agent subnet shouldn't inspect TLS either: Microsoft's private networking page
#   says to check that it doesn't.
# - Larkspur's private root goes in as a file of its own, /app/custom-roots.pem, because the model
#   gateway, the MCP server and the collector present certificates it signed; on Google the Agent
#   Gateway checks those itself. It stays out of the system store. The entry point combines it
#   with the runtime's bundle, or certifi's when the runtime sets none, at start and again before
#   every question (ch07/image/ca_bundle.py), as Microsoft's page on egress controls says to.
# - RUNTIME is set here. The hosted agent's version sets the rest of the entry point's contract,
#   with GATEWAY_KEY as a ${{connections.<name>.credentials.<field>}} placeholder that Foundry
#   resolves when the sandbox starts, never as a value.
# - PYTHONNOUSERSITE=1. $HOME is the session's storage, which callers can upload files into, so
#   Python must not load user site-packages from it. Microsoft asks for the setting in the
#   version's environment too.
#
# Base image: python:3.12-slim, looked up on Docker Hub's registry API on 2026-10-29: Python
# 3.12.16 on Debian 13 (trixie). It is the same digest as chapter 7's image.
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONNOUSERSITE=1

# Chapter 5's pinned set, from wheels only, so no package's build code runs here. The file carries
# no hashes, so there is no --require-hashes. It lists litellm without the [proxy] extra, which
# would pull in litellm-enterprise (proprietary); the second command fails the build if it is here.
COPY ch05/requirements.txt /app/labs/ch05/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore \
        --only-binary=:all: -r /app/labs/ch05/requirements.txt \
 && ! pip show litellm-enterprise

# Larkspur's private root CA, where the entry point looks for it by default (CUSTOM_ROOTS_FILE names
# another place). The openssl line prints its subject and expiry, and fails the build on a file that
# holds no certificate.
COPY ch08/image/private-ca.pem /app/custom-roots.pem
RUN openssl x509 -in /app/custom-roots.pem -noout -subject -enddate

# A user of its own, with no login shell. The files below stay root's, readable but not writable.
RUN groupadd --gid 10001 harness \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin harness

# The code in the repository's layout, outside $HOME, because each file finds its neighbours from
# where it sits: the chapter 1 loop the harness runs, the chapter 5 files the entry point imports,
# the lock that both the harness's check and the model's tool list read, and chapter 7's entry point
# with the module that builds the CA bundle.
WORKDIR /app
COPY ch01/agent_loop.py /app/labs/ch01/
COPY ch05/adapter/runtime_adapter.py /app/labs/ch05/adapter/
COPY ch05/harness/client.py ch05/harness/gateway_model.py ch05/harness/rule_model.py /app/labs/ch05/harness/
COPY ch05/tracing/trace_setup.py /app/labs/ch05/tracing/
COPY ch05/mcp-server/tools.lock.json /app/labs/ch05/mcp-server/
COPY ch07/image/entrypoint.py ch07/image/ca_bundle.py /app/labs/ch07/image/

ENV RUNTIME=foundry
USER 10001:10001
EXPOSE 8088
CMD ["python", "/app/labs/ch07/image/entrypoint.py"]
