# The module chapter 4 promised: a workflow manifest in, the AWS identities it implies out.
#
# - A role for each tool the manifest lists, with the catalog's grants for that tool and nothing
#   more, the platform's permission boundary, and the workflow, tool, server, owner and sponsor in
#   its tags. Its trust policy admits only the tool's server, and only with a person as the source
#   identity and the workflow as the one session tag, so CloudTrail names both on every call.
# - A deny on each tool role for the manifest's never-list entries that have AWS actions.
# - EKS access entries for the tools that act on the cluster.
# - The workflow identity's invoke scopes, as one Cedar permit per tool for the tool gateway.
#
# pipeline/scope_check.py is the other half: it refuses a manifest or catalog change that grows
# any of this without a change record.

locals {
  workflow = var.manifest.workflow
  tools    = var.manifest.tools
  missing  = setsubtract(keys(local.tools), keys(var.catalog.tools))

  entries = { for tool in keys(local.tools) : tool => lookup(var.catalog.tools, tool, null) }
  servers = { for tool, entry in local.entries : tool => var.catalog.servers[entry.server] if entry != null }

  # The base role of each tool's server, the only principal its trust policy admits.
  server_roles = { for tool, server in local.servers : tool => templatestring(server.principal, var.template_vars) }

  role_names = { for tool in keys(local.tools) : tool => substr("${local.workflow}-${replace(tool, "_", "-")}", 0, 64) }

  grants = {
    for tool, entry in local.entries : tool => [
      for statement in entry.aws : {
        actions   = statement.actions
        resources = [for resource in statement.resources : templatestring(resource, var.template_vars)]
      }
    ] if entry != null
  }

  never_actions = sort(distinct(flatten([for item in var.manifest.never : lookup(var.catalog.never, item, [])])))

  # arn:aws:iam::<account>:role/<name> becomes arn:aws:sts::<account>:assumed-role/<name>, the
  # form in which the policy engine sees an IAM caller.
  workflow_principal = replace(replace(var.workflow_role_arn, ":iam::", ":sts::"), ":role/", ":assumed-role/")

  cedar_permits = {
    for tool, spec in local.tools : tool => format("%s%s;",
      join("\n", [
        "permit (",
        "  principal == AgentCore::IamEntity::\"${local.workflow_principal}\",",
        "  action == AgentCore::Action::\"${local.servers[tool].gateway_target}___${tool}\",",
        "  resource == AgentCore::Gateway::\"${var.gateway_arn}\"",
        ")",
      ]),
      length(lookup(spec, "allow", {})) == 0 ? "" : format("\nwhen {\n  %s\n}", join(" &&\n  ", [
        for arg, values in spec.allow : "context.input has ${arg} && ${jsonencode(values)}.contains(context.input.${arg})"
      ]))
    ) if lookup(local.servers, tool, null) != null
  }
}

# The plan stops here, with the reason, when the manifest and the catalog disagree.
resource "terraform_data" "manifest_checks" {
  input = local.workflow

  lifecycle {
    precondition {
      condition     = length(local.missing) == 0
      error_message = "Tools in the manifest of ${local.workflow} that the catalog doesn't have: ${join(", ", sort(local.missing))}."
    }
    precondition {
      condition = alltrue([
        for tool, spec in local.tools : try(lookup(spec, "writes", false) == local.entries[tool].writes, false)
      ])
      error_message = "A tool's writes flag in the manifest of ${local.workflow} differs from the catalog's; a tool that writes is declared as writing in both."
    }
    precondition {
      condition = alltrue([
        for tool, spec in local.tools : length(setsubtract(keys(lookup(spec, "allow", {})), spec.args)) == 0
      ])
      error_message = "An allow list in the manifest of ${local.workflow} names an argument its tool doesn't take."
    }
  }
}

data "aws_iam_policy_document" "trust" {
  for_each = local.servers

  statement {
    sid = "ToolServerForOnePerson"
    actions = [
      "sts:AssumeRole", "sts:SetSourceIdentity", "sts:TagSession",
    ]
    principals {
      type        = "AWS"
      identifiers = [local.server_roles[each.key]]
    }
    condition {
      test     = "StringLike"
      variable = "sts:SourceIdentity"
      values   = ["*@${var.person_domain}"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/workflow"
      values   = [local.workflow]
    }
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "aws:TagKeys"
      values   = ["workflow"]
    }
  }
}

resource "aws_iam_role" "tool" {
  for_each = local.servers

  name                 = local.role_names[each.key]
  description          = "${each.key} for ${local.workflow}, assumed for one request at a time by ${local.entries[each.key].server}"
  assume_role_policy   = data.aws_iam_policy_document.trust[each.key].json
  permissions_boundary = var.permissions_boundary_arn
  max_session_duration = var.max_session_seconds

  tags = {
    workflow = local.workflow
    tool     = each.key
    server   = local.entries[each.key].server
    writes   = tostring(local.entries[each.key].writes)
    owner    = var.manifest.owner
    sponsor  = var.manifest.sponsor
  }

  depends_on = [terraform_data.manifest_checks]
}

data "aws_iam_policy_document" "tool" {
  for_each = local.servers

  dynamic "statement" {
    for_each = local.grants[each.key]
    content {
      sid       = "Grant${statement.key}"
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }

  dynamic "statement" {
    for_each = length(local.never_actions) == 0 ? [] : [local.never_actions]
    content {
      sid       = "NeverList"
      effect    = "Deny"
      actions   = statement.value
      resources = ["*"]
    }
  }
}

resource "aws_iam_role_policy" "tool" {
  for_each = local.servers

  name   = "grants"
  role   = aws_iam_role.tool[each.key].id
  policy = data.aws_iam_policy_document.tool[each.key].json
}

# Kubernetes access for the tools that act on the cluster: a read-only access policy scoped to
# namespaces, or groups that the cluster's RBAC binds to one verb on one resource.
locals {
  eks_access = { for tool, entry in local.entries : tool => entry.eks_access if try(entry.eks_access, null) != null }
}

resource "aws_eks_access_entry" "tool" {
  for_each = local.eks_access

  cluster_name      = var.eks_cluster_name
  principal_arn     = aws_iam_role.tool[each.key].arn
  kubernetes_groups = try(each.value.groups, null)
  type              = "STANDARD"
}

resource "aws_eks_access_policy_association" "tool" {
  for_each = { for tool, access in local.eks_access : tool => access if try(access.policy, null) != null }

  cluster_name  = var.eks_cluster_name
  principal_arn = aws_iam_role.tool[each.key].arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/${each.value.policy}"

  access_scope {
    type       = "namespace"
    namespaces = each.value.namespaces
  }

  depends_on = [aws_eks_access_entry.tool]
}
