"""Chapter 10's first AWS check: a customer-managed Knowledge Base on S3 Vectors, filtered by a list of groups.

It settles four things the chapter left for the first apply:
1. whether the Knowledge Base takes a page's groups as a list from the S3 metadata file, and whether
   `listContains`, alone and inside `orAll`, filters on that list with S3 Vectors as the store;
2. whether `equals` on a single-valued attribute filters, the fallback the chapter names;
3. whose role embeds the question at `Retrieve`: a role that may call `bedrock:Retrieve` on the
   Knowledge Base and nothing else asks a question;
4. the index's mode, ENHANCED or CLASSIC.

Everything is created under a fresh name, in one Region, and deleted in `finally`; the script then
lists what is left under that name. It writes what AWS returned to --out with account,
organization, and policy IDs removed.
Credentials come from the environment (AWS_PROFILE and the shared files), never from arguments.

Larkspur runs W1 in ca-central-1. An account made with AWS's newer sign-up may create resources
only in the Region AWS assigned it (US East (Ohio) for a Canadian address) and gets AccessDenied
from a service control policy anywhere else; give that Region with --region.

Run (from workflows/w1-knowledge-assistant):
  AWS_PROFILE=<profile> python aws/s3_vectors_check.py --region ca-central-1 \
      --out eval/results/<date>/aws-s3-vectors-check.json
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Any, Callable

import boto3
import yaml
from botocore.exceptions import ClientError

W1 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(W1 / "ingest"))
from ingest import DOCS_DIR, read_document, visible_text  # noqa: E402

EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
ON_CALL_GROUPS = ("lm-all-staff", "lm-eng-all")
PREFIX = "larkspur-w1-check"
INDEX = "w1-pages"  # an index name takes 3 to 63 characters


def redact(value: Any) -> Any:
    """Account, organization, and policy IDs out of everything the script records."""
    text = re.sub(r"\b\d{12}\b", "<account>", json.dumps(value, default=str))
    text = re.sub(r"\bo-[a-z0-9]{10,32}\b", "<organization>", text)
    return json.loads(re.sub(r"\bp-[a-z0-9]{8,128}\b", "<policy>", text))


def wait(what: str, check: Callable[[], bool], timeout: float, every: float = 5.0) -> None:
    start = time.time()
    while not check():
        if time.time() - start > timeout:
            raise TimeoutError(f"{what}: not done after {timeout:.0f} s")
        time.sleep(every)


def retry(call: Callable[[], Any], attempts: int = 12, every: float = 5.0) -> Any:
    """IAM changes take seconds to reach other services; retry a call that fails for that reason."""
    for n in range(attempts):
        try:
            return call()
        except ClientError as exc:
            code, message = exc.response["Error"]["Code"], exc.response["Error"]["Message"]
            explicit = "explicit deny" in message  # a service control policy, not a propagation delay
            if explicit or n == attempts - 1 or code not in {"AccessDenied", "AccessDeniedException",
                                                             "ValidationException"}:
                raise
            time.sleep(every)


def group_filter(groups: list[str]) -> dict:
    """W1's filter: a page passes if its groups share one with the engineer's (store/filters.py)."""
    terms = [{"listContains": {"key": "access_groups", "value": g}} for g in groups]
    return terms[0] if len(terms) == 1 else {"orAll": terms}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--region", default="ca-central-1")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    session = boto3.Session(region_name=args.region)
    region = args.region
    account = session.client("sts").get_caller_identity()["Account"]
    s3, s3v, iam = session.client("s3"), session.client("s3vectors"), session.client("iam")
    agent, runtime = session.client("bedrock-agent"), session.client("bedrock-agent-runtime")

    name = f"{PREFIX}-{secrets.token_hex(3)}"
    bucket = f"{name}-corpus"
    record: dict[str, Any] = {"region": region, "name": name, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                              "embedding_model": EMBEDDING_MODEL, "checks": {}, "teardown": {}}
    created: dict[str, Any] = {}
    questions = yaml.safe_load((W1 / "corpus" / "golden-questions.yaml").read_text(encoding="utf-8"))
    questions = questions["questions"] if isinstance(questions, dict) else questions
    access = [q for q in questions if q.get("trap") == "access"]

    try:
        # The corpus: the text a reader sees, and a metadata file beside each page (extended format,
        # every attribute kept out of the embedding; the groups as a list).
        s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region})
        created["bucket"] = bucket
        pages = 0
        for path in sorted(DOCS_DIR.glob("*.md")):
            meta, body = read_document(path)
            groups = list(meta["access_groups"])

            def attr(kind: str, value: Any) -> dict:
                key = {"STRING": "stringValue", "STRING_LIST": "stringListValue"}[kind]
                return {"value": {"type": kind, key: value}, "includeForEmbedding": False}

            metadata = {"metadataAttributes": {
                "access_groups": attr("STRING_LIST", groups),
                "access_group": attr("STRING", groups[0]),
                "classification": attr("STRING", str(meta["classification"])),
                "doc_id": attr("STRING", path.name),
            }}
            s3.put_object(Bucket=bucket, Key=f"docs/{path.name}", Body=visible_text(body).encode("utf-8"),
                          ContentType="text/markdown")
            s3.put_object(Bucket=bucket, Key=f"docs/{path.name}.metadata.json",
                          Body=json.dumps(metadata).encode("utf-8"), ContentType="application/json")
            pages += 1
        record["pages"] = pages

        # The store: a vector bucket and an index with the Knowledge Base's two keys non-filterable.
        s3v.create_vector_bucket(vectorBucketName=name)
        created["vector_bucket"] = name
        s3v.create_index(vectorBucketName=name, indexName=INDEX, dataType="float32", dimension=1024,
                         distanceMetric="cosine",
                         metadataConfiguration={"nonFilterableMetadataKeys": ["AMAZON_BEDROCK_TEXT",
                                                                              "AMAZON_BEDROCK_METADATA"]})
        created["index"] = INDEX
        index = s3v.get_index(vectorBucketName=name, indexName=INDEX)["index"]
        record["index_mode"] = index.get("indexMode")
        index_arn = index["indexArn"]
        bucket_arn = index_arn.split("/index/")[0]

        # The Knowledge Base's own role: one prefix of one bucket, the embedding model, the index.
        kb_role = f"{name}-kb"
        iam.create_role(RoleName=kb_role, AssumeRolePolicyDocument=json.dumps({
            "Version": "2012-10-17", "Statement": [{
                "Effect": "Allow", "Principal": {"Service": "bedrock.amazonaws.com"}, "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"aws:SourceAccount": account}}}]}))
        created["kb_role"] = kb_role
        iam.put_role_policy(RoleName=kb_role, PolicyName="w1-check", PolicyDocument=json.dumps({
            "Version": "2012-10-17", "Statement": [
                {"Effect": "Allow", "Action": "bedrock:InvokeModel",
                 "Resource": f"arn:aws:bedrock:{region}::foundation-model/{EMBEDDING_MODEL}"},
                {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": f"arn:aws:s3:::{bucket}"},
                {"Effect": "Allow", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/docs/*"},
                {"Effect": "Allow", "Action": ["s3vectors:PutVectors", "s3vectors:GetVectors",
                                               "s3vectors:DeleteVectors", "s3vectors:QueryVectors",
                                               "s3vectors:ListVectors", "s3vectors:GetIndex"],
                 "Resource": [bucket_arn, index_arn]}]}))
        kb_role_arn = iam.get_role(RoleName=kb_role)["Role"]["Arn"]

        kb = retry(lambda: agent.create_knowledge_base(
            name=name, roleArn=kb_role_arn,
            knowledgeBaseConfiguration={"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": f"arn:aws:bedrock:{region}::foundation-model/{EMBEDDING_MODEL}",
                "embeddingModelConfiguration": {"bedrockEmbeddingModelConfiguration": {
                    "dimensions": 1024, "embeddingDataType": "FLOAT32"}}}},
            storageConfiguration={"type": "S3_VECTORS", "s3VectorsConfiguration": {"indexArn": index_arn}}))
        kb_id = kb["knowledgeBase"]["knowledgeBaseId"]
        created["knowledge_base"] = kb_id
        wait("knowledge base", lambda: agent.get_knowledge_base(knowledgeBaseId=kb_id)
             ["knowledgeBase"]["status"] in {"ACTIVE", "FAILED"}, 300)

        ds = agent.create_data_source(
            knowledgeBaseId=kb_id, name="corpus",
            dataSourceConfiguration={"type": "S3", "s3Configuration": {
                "bucketArn": f"arn:aws:s3:::{bucket}", "inclusionPrefixes": ["docs/"]}},
            vectorIngestionConfiguration={"chunkingConfiguration": {
                "chunkingStrategy": "FIXED_SIZE",
                "fixedSizeChunkingConfiguration": {"maxTokens": 300, "overlapPercentage": 20}}})
        ds_id = ds["dataSource"]["dataSourceId"]
        created["data_source"] = ds_id
        job = agent.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)["ingestionJob"]

        def job_state() -> dict:
            return agent.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id,
                                           ingestionJobId=job["ingestionJobId"])["ingestionJob"]

        wait("ingestion", lambda: job_state()["status"] in {"COMPLETE", "FAILED", "STOPPED"}, 900, 10)
        final = job_state()
        record["ingestion"] = {"status": final["status"], "statistics": final.get("statistics"),
                               "failure_reasons": final.get("failureReasons", [])}

        def ask(question: str, flt: dict | None, client: Any = runtime) -> dict:
            config: dict[str, Any] = {"vectorSearchConfiguration": {"numberOfResults": 5}}
            if flt is not None:
                config["vectorSearchConfiguration"]["filter"] = flt
            try:
                results = client.retrieve(knowledgeBaseId=kb_id, retrievalQuery={"text": question},
                                          retrievalConfiguration=config)["retrievalResults"]
            except ClientError as exc:
                return {"error": exc.response["Error"]["Code"], "message": exc.response["Error"]["Message"]}
            return {"returned": [{"doc_id": r.get("metadata", {}).get("doc_id"),
                                  "access_groups": r.get("metadata", {}).get("access_groups"),
                                  "access_group": r.get("metadata", {}).get("access_group"),
                                  "classification": r.get("metadata", {}).get("classification")}
                                 for r in results]}

        checks = record["checks"]
        first = access[0]
        checks["unfiltered"] = {"question": first["id"], "source": first["source_document"],
                                **ask(first["question"], None)}
        checks["on_call"] = []
        checks["member"] = []
        for q in access:
            on_call = ask(q["question"], group_filter(list(ON_CALL_GROUPS)))
            member = ask(q["question"], group_filter([q["required_access_group"], "lm-eng-all"]))
            checks["on_call"].append({"question": q["id"], "source": q["source_document"], **on_call})
            checks["member"].append({"question": q["id"], "source": q["source_document"],
                                     "group": q["required_access_group"], **member})
        checks["list_contains_alone"] = {"question": first["id"], "group": first["required_access_group"],
                                         **ask(first["question"], group_filter([first["required_access_group"]]))}
        checks["equals_single_value"] = {"question": first["id"], "group": first["required_access_group"],
                                         **ask(first["question"], {"equals": {
                                             "key": "access_group", "value": first["required_access_group"]}})}

        # Whose role embeds the question: a role that may call Retrieve on this Knowledge Base and nothing else.
        caller = f"{name}-retrieve"
        iam.create_role(RoleName=caller, AssumeRolePolicyDocument=json.dumps({
            "Version": "2012-10-17", "Statement": [{
                "Effect": "Allow", "Principal": {"AWS": f"arn:aws:iam::{account}:root"},
                "Action": "sts:AssumeRole"}]}))
        created["caller_role"] = caller
        iam.put_role_policy(RoleName=caller, PolicyName="retrieve-only", PolicyDocument=json.dumps({
            "Version": "2012-10-17", "Statement": [{
                "Effect": "Allow", "Action": "bedrock:Retrieve",
                "Resource": f"arn:aws:bedrock:{region}:{account}:knowledge-base/{kb_id}"}]}))
        caller_arn = iam.get_role(RoleName=caller)["Role"]["Arn"]
        creds = retry(lambda: session.client("sts").assume_role(
            RoleArn=caller_arn, RoleSessionName="w1-check")["Credentials"])
        limited = boto3.Session(aws_access_key_id=creds["AccessKeyId"], aws_secret_access_key=creds["SecretAccessKey"],
                                aws_session_token=creds["SessionToken"], region_name=region)
        limited_runtime = limited.client("bedrock-agent-runtime")
        outcome = None
        for _ in range(12):  # the new role's policy takes seconds to reach Bedrock
            outcome = ask(access[0]["question"], group_filter(list(ON_CALL_GROUPS)), client=limited_runtime)
            if "error" not in outcome or "AccessDenied" not in outcome["error"]:
                break
            time.sleep(5)
        checks["retrieve_without_invoke_model"] = outcome
    except Exception as exc:  # recorded, then the teardown runs
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        teardown = record["teardown"]

        def step(label: str, fn: Callable[[], Any]) -> None:
            try:
                fn()
                teardown[label] = "deleted"
            except Exception as exc:  # keep going; the listing below shows what is left
                teardown[label] = f"{type(exc).__name__}: {exc}"

        if "data_source" in created:
            step("data_source", lambda: agent.delete_data_source(knowledgeBaseId=created["knowledge_base"],
                                                                 dataSourceId=created["data_source"]))
        if "knowledge_base" in created:
            def drop_kb() -> None:
                agent.delete_knowledge_base(knowledgeBaseId=created["knowledge_base"])

                def gone() -> bool:
                    try:
                        agent.get_knowledge_base(knowledgeBaseId=created["knowledge_base"])
                        return False
                    except ClientError as exc:
                        return exc.response["Error"]["Code"] == "ResourceNotFoundException"
                wait("knowledge base deletion", gone, 900, 15)  # took over five minutes on 29 October 2026
            step("knowledge_base", drop_kb)
        if "index" in created and teardown.get("knowledge_base", "deleted") == "deleted":
            step("index", lambda: s3v.delete_index(vectorBucketName=name, indexName=INDEX))
        if "vector_bucket" in created and teardown.get("index", "deleted") == "deleted":
            step("vector_bucket", lambda: s3v.delete_vector_bucket(vectorBucketName=name))
        if "bucket" in created:
            def drop_bucket() -> None:
                objects = s3.list_objects_v2(Bucket=bucket).get("Contents", [])
                while objects:
                    s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": o["Key"]} for o in objects]})
                    objects = s3.list_objects_v2(Bucket=bucket).get("Contents", [])
                s3.delete_bucket(Bucket=bucket)
            step("bucket", drop_bucket)
        for label in ("caller_role", "kb_role"):
            if label in created:
                role = created[label]

                def drop_role(role: str = role) -> None:
                    for policy in iam.list_role_policies(RoleName=role)["PolicyNames"]:
                        iam.delete_role_policy(RoleName=role, PolicyName=policy)
                    iam.delete_role(RoleName=role)
                step(label, drop_role)

        def listing(fn: Callable[[], list[str]]) -> list[str] | str:
            try:
                return fn()
            except ClientError as exc:  # a denied listing is recorded, not fatal
                return f"{exc.response['Error']['Code']}: {exc.response['Error']['Message']}"

        def names(client: Any, operation: str, items: str, key: str) -> list[str]:
            pages = client.get_paginator(operation).paginate()
            return [item[key] for page in pages for item in page[items] if item[key].startswith(PREFIX)]

        left = {
            "knowledge_bases": listing(lambda: names(agent, "list_knowledge_bases", "knowledgeBaseSummaries",
                                                     "name")),
            "vector_buckets": listing(lambda: names(s3v, "list_vector_buckets", "vectorBuckets",
                                                    "vectorBucketName")),
            "buckets": listing(lambda: names(s3, "list_buckets", "Buckets", "Name")),
            "roles": listing(lambda: names(iam, "list_roles", "Roles", "RoleName")),
        }
        record["left_after_teardown"] = left
        record["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(redact(record), indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"ingestion": record.get("ingestion", {}).get("status"), "index_mode": record.get("index_mode"),
                          "error": record.get("error"), "left": left}, default=str))
    leftovers = [v for v in left.values() if isinstance(v, list) and v]
    return 1 if record.get("error") or leftovers else 0


if __name__ == "__main__":
    sys.exit(main())
