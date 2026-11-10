# The runbook corpus as a customer-managed Knowledge Base. AWS doesn't offer its Managed Knowledge
# Base in Canada, so the vector store is Larkspur's own: S3 Vectors in the workflow's Region,
# ca-central-1, embedded with Titan Text Embeddings V2 in the same Region. Nothing here bills by the
# hour.

locals {
  embedding_model_arn = "arn:aws:bedrock:${var.region}::foundation-model/amazon.titan-embed-text-v2:0"
}

resource "aws_s3_bucket" "corpus" {
  bucket_prefix = "${local.workflow}-runbooks-"
  force_destroy = var.force_destroy_stores
  depends_on    = [aws_budgets_budget.account]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "corpus" {
  bucket = aws_s3_bucket.corpus.id
  rule {
    bucket_key_enabled = true
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.workflow.arn
    }
  }
}

resource "aws_s3_bucket_public_access_block" "corpus" {
  bucket                  = aws_s3_bucket.corpus.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "corpus" {
  bucket = aws_s3_bucket.corpus.id
  versioning_configuration {
    status = "Enabled"
  }
}

# The vector bucket's encryption is fixed when it is created, so the key comes with the first apply.
resource "aws_s3vectors_vector_bucket" "runbooks" {
  vector_bucket_name = "${local.workflow}-runbooks"
  force_destroy      = var.force_destroy_stores
  encryption_configuration = [{
    sse_type    = "aws:kms"
    kms_key_arn = aws_kms_key.workflow.arn
  }]
}

resource "aws_s3vectors_index" "runbooks" {
  vector_bucket_name = aws_s3vectors_vector_bucket.runbooks.vector_bucket_name
  index_name         = "runbooks"
  data_type          = "float32"
  dimension          = 1024
  distance_metric    = "cosine"

  # The Knowledge Base keeps each chunk's text and its own metadata in these two keys, which AWS's
  # setup page says to mark non-filterable. Fixed at creation.
  metadata_configuration {
    non_filterable_metadata_keys = ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]
  }
}

data "aws_iam_policy_document" "knowledge_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock:${var.region}:${var.account_id}:knowledge-base/*"]
    }
  }
}

resource "aws_iam_role" "knowledge" {
  name               = "${local.workflow}-knowledge-base"
  description        = "The runbook knowledge base: read the corpus, embed in the Region, write the index"
  assume_role_policy = data.aws_iam_policy_document.knowledge_trust.json
  depends_on         = [aws_budgets_budget.account]
}

data "aws_iam_policy_document" "knowledge" {
  statement {
    sid       = "EmbedInTheRegion"
    actions   = ["bedrock:InvokeModel"]
    resources = [local.embedding_model_arn]
  }
  statement {
    sid       = "ReadTheCorpus"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.corpus.arn}/runbooks/*"]
  }
  statement {
    sid       = "ListTheRunbooksOnly"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.corpus.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["runbooks/*"]
    }
  }
  statement {
    sid       = "DecryptTheCorpusAndTheIndex"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.workflow.arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.region}.amazonaws.com", "s3vectors.${var.region}.amazonaws.com"]
    }
  }
  statement {
    sid = "WriteTheIndex"
    actions = [
      "s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:QueryVectors",
      "s3vectors:DeleteVectors", "s3vectors:GetIndex",
    ]
    resources = [aws_s3vectors_index.runbooks.index_arn]
  }
}

resource "aws_iam_role_policy" "knowledge" {
  name   = "ingest"
  role   = aws_iam_role.knowledge.id
  policy = data.aws_iam_policy_document.knowledge.json
}

resource "aws_bedrockagent_knowledge_base" "runbooks" {
  name     = "${local.workflow}-runbooks"
  role_arn = aws_iam_role.knowledge.arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = local.embedding_model_arn
      embedding_model_configuration {
        bedrock_embedding_model_configuration {
          dimensions          = 1024
          embedding_data_type = "FLOAT32"
        }
      }
    }
  }

  storage_configuration {
    type = "S3_VECTORS"
    s3_vectors_configuration {
      index_arn = aws_s3vectors_index.runbooks.index_arn
    }
  }

  depends_on = [aws_iam_role_policy.knowledge]
}

# The default parser, which calls no model.
resource "aws_bedrockagent_data_source" "runbooks" {
  knowledge_base_id    = aws_bedrockagent_knowledge_base.runbooks.id
  name                 = "runbooks"
  data_deletion_policy = "DELETE"

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn         = aws_s3_bucket.corpus.arn
      inclusion_prefixes = ["runbooks/"]
    }
  }

  vector_ingestion_configuration {
    chunking_configuration {
      chunking_strategy = "FIXED_SIZE"
      fixed_size_chunking_configuration {
        max_tokens         = 300
        overlap_percentage = 20
      }
    }
  }
}
