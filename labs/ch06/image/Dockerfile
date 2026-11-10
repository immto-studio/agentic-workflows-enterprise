# The skeleton's harness on Amazon Bedrock AgentCore Runtime: chapter 7's image, with the same
# entry point (ch07/image/entrypoint.py, reused rather than copied) serving AgentCore's HTTP
# contract, GET /ping and POST /invocations, on port 8080.
#
# Build context: companion/labs, so that ch01, ch05 and ch07 are visible. From there:
#
#   docker build --platform linux/arm64 -f ch06/image/Dockerfile -t harness-agentcore .
#
# AgentCore Runtime runs ARM64 containers only ("ARM64 container - Required for compatibility with
# the AgentCore Runtime environment", HTTP protocol contract, AgentCore developer guide, read
# 2026-10-29). Push the image to the ECR repository terraform/runtime.tf names and give it the
# digest. The build needs ch06/image/private-ca.pem, Larkspur's private root CA, and fails without
# it; *.pem is git-ignored, so the reader or the pipeline writes it first.
#
# What differs from chapter 8's image:
# - RUNTIME=agentcore and port 8080.
# - No GATEWAY_KEY at all. runtime.tf sets GATEWAY_KEY_PROVIDER, and the entry point fetches the key
#   from AgentCore Identity's token vault with each request's workload access token
#   (ch07/image/token_vault.py). AgentCore's environment variables are part of the runtime's
#   configuration, readable by anyone who can read the runtime, so no secret goes there.
# - MCP_AUTH=sigv4: the tool gateway authorizes with IAM, so every MCP request is signed with the
#   runtime's execution role (ch07/image/sigv4_mcp.py).
# - Larkspur's root goes in as a file of its own, as on Foundry, for the model gateway and the
#   collector, which present certificates it signed. AgentCore sets no CA bundle of its own, so the
#   entry point combines the root with certifi's.
#
# Base image: python:3.12-slim, looked up on Docker Hub's registry API on 2026-10-29: Python
# 3.12.16 on Debian 13 (trixie). The digest is the tag's multi-platform index, the same as chapter
# 7's, and --platform picks its linux/arm64 image.
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

# Larkspur's private root CA, where the entry point looks for it by default. The openssl line prints
# its subject and expiry, and fails the build on a file that holds no certificate.
COPY ch06/image/private-ca.pem /app/custom-roots.pem
RUN openssl x509 -in /app/custom-roots.pem -noout -subject -enddate

# A user of its own, with no login shell. The files below stay root's, readable but not writable.
RUN groupadd --gid 10001 harness \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin harness

# The code in the repository's layout, because each file finds its neighbours from where it sits.
WORKDIR /app
COPY ch01/agent_loop.py /app/labs/ch01/
COPY ch05/adapter/runtime_adapter.py /app/labs/ch05/adapter/
COPY ch05/harness/client.py ch05/harness/gateway_model.py ch05/harness/rule_model.py /app/labs/ch05/harness/
COPY ch05/tracing/trace_setup.py /app/labs/ch05/tracing/
COPY ch05/mcp-server/tools.lock.json /app/labs/ch05/mcp-server/
COPY ch07/image/entrypoint.py ch07/image/ca_bundle.py ch07/image/token_vault.py ch07/image/sigv4_mcp.py \
     /app/labs/ch07/image/

ENV RUNTIME=agentcore
USER 10001:10001
EXPOSE 8080
CMD ["python", "/app/labs/ch07/image/entrypoint.py"]
