# W1: the plan's decisions

The README and the code cite these decisions by number, W1-D1 to W1-D28. W1-D1 to W1-D13 were set on 29
October 2026, when the lab was planned; the details the fact-checking added, and W1-D14 to W1-D28, followed the
same day, after a review of chapter 10's draft against its facts. W1-D5 and W1-D6 were settled on 29 October.
Where the README describes the lab as built, the README is right. A number such as D-018 is one of the book's
own decisions, listed in [docs/book-decisions.md](../../docs/book-decisions.md). The pages behind the facts are
under chapter 10 in [LINKS.md](../../LINKS.md).

## The plan (29 October 2026)

- **W1-D1. Local first, no cloud spend (D-018).** Chat and embedding models are called through chapter 5's LiteLLM gateway, on Ollama with gpt-oss:20b and gemma4:12b. The embedding model gets chosen by measurement. The AWS form is checked offline only: the access filter in Bedrock's `RetrievalFilter` syntax, and the Knowledge Base itself from `labs/ch06`.
- **W1-D2. Ingestion classifies before it indexes.** A document without `classification`, `access_groups`, `owner_team` and `last_reviewed` is rejected, not indexed. HTML comments are stripped, because a reader of the wiki never sees them and one injection hides in one. The baseline chunking matches the Knowledge Base (300 tokens, 20 percent overlap), and heading-aware chunks are measured as a variant. Every chunk carries its document's metadata.
- **W1-D3. The store filters before it ranks.** The lab uses a NumPy store, brute force over about 1,500 chunks, small enough to print. A second kind of store (sqlite-vec, if its extension loads on Windows; LanceDB otherwise) exists for the exit drill.
- **W1-D4. Access comes from the delegated identity, never from tool arguments.** The knowledge MCP server takes the engineer's object ID from the forwarded token and reads their groups from a membership table synced nightly from Entra (a mocked Graph export in the lab). It passes "the chunk's `access_groups` share at least one group with the caller's" to the store. The model never sees a chunk the caller can't read. The chapter states the cost: a removed member keeps access until the next sync, unless the token's own groups claim, where present, narrows it the same day.
- **W1-D5. Refusals don't reveal that a restricted document exists.** The answer is "nothing in the documents you can read answers this", with no title and no "it's in a document you can't access". Saying where the answer lives would need an unfiltered search, and it leaks existence. "When is the LPAS mainframe going to be retired?" would confirm an unannounced plan. The corpus README asked for the other behavior, so this decision was left open until 29 October (below). The golden checks for access questions become: no restricted content, no restricted title, and the right answer for a member of the group.
- **W1-D6. Each call carries the class of its prompt (chapter 2's rule).** The harness labels each model call with the highest classification among the chunks in its prompt, and the gateway's grid routes it. Restricted and Confidential go to the self-hosted alias in the lab. On AWS, Confidential would go to Nova Lite in Canada and Restricted to self-hosted. W1's manifest allows up to Restricted, on the self-hosted route only. The alternative is to keep Restricted documents out of W1's index altogether.
- **W1-D7. Stale documents.** Answers cite each source's `last_reviewed` date and prefer the newest when two disagree. The governance fix the chapter recommends, a `superseded_by` field the pipeline requires when a page is replaced, is not added to the corpus, which stays like a real wiki.
- **W1-D8. Injection.** Retrieved text is framed as quoted data, and W1 has one read-only tool. Answers are plain text, without links or images, so nothing renders out. The evaluation fails an answer that repeats the injected advice: `kubectl delete namespace fnol-prod`, approving public-read, or closing a Sev1 without a postmortem.
- **W1-D9. Citations.** Every answer names its sources by title and `last_reviewed` date. An answer without a citation fails, and so does one that cites a document the caller can't read.
- **W1-D10. Evaluation in two layers.**
  - Deterministic retrieval tests in pytest, with no model:
    - the source document appears in the top k for a permitted persona;
    - no restricted chunk is returned to an unpermitted persona, a hard assertion over all 20 questions and personas;
    - the current document ranks above its stale twin where both appear.
  - Model runs through the gateway with gpt-oss:20b and gemma4:12b:
    - key facts, citations, stale preference, injection, and refusals;
    - a judge as in chapter 5;
    - results recorded with versions and dates.
- **W1-D11. Exit drill.** Dump the index to JSONL, restore it into the second kind of store, and rerun the retrieval tests. The drill passes when the results match within the manifest's tolerance.
- **W1-D12. "Where Google and Microsoft differ", offline.** The same access filter is rendered for Bedrock Knowledge Bases, Azure AI Search, and Vertex AI Search, and checked against each provider's documented syntax and limits. One limit is already known: Bedrock's `andAll` and `orAll` take "up to 5 filter types", which matters for an engineer in twenty groups. A short fact sheet comes first.
- **W1-D13. Out of scope for the lab:** the Slack and portal integration (the chapter describes it) and the managed apply.

## What the fact sheet added (29 October 2026)

Every quotation in W1's fact sheet was compared by a script with its saved page, and the lab was reconciled with it.

**W1-D4 holds, with details**
- Entra access tokens live 60 to 90 minutes by default, so a removal takes effect within that window once the token can only narrow the table.
- `hasgroups` signals an overage too. The overage URL is legacy Azure AD Graph, and the server never calls it.
- The nightly sync rebuilds the table from each group's `transitiveMembers` rather than following deltas. A delta reports direct members only, misses users removed by deletion, and expires after seven days.

**W1-D12, the filter on each platform** (`store/filters.py` renders each form; tests check the shapes and limits)
- **Bedrock Knowledge Bases.** `listContains` inside `orAll`. Each `orAll` takes two to five members with one level of nesting, so one filter holds at most 25 groups.
  - AWS calls list operators "best supported" on OpenSearch Serverless, and Bedrock's setup page lists S3 vector metadata types without lists. The list form on S3 Vectors stays unconfirmed until the first managed apply.
  - While every page has one group, a single-valued attribute with `equals` avoids the question.
  - The Knowledge Base enforces no permissions of its own, so `bedrock:Retrieve` belongs to the knowledge server's role alone.
- **S3 Vectors.** Indexes in buckets created on or after 30 September 2026 filter before the search (ENHANCED, 100 constraints a query). An older index can return fewer than k results under a selective filter; switching it is in place and free.
- **Azure AI Search.** `search.in` over a string collection is GA, with no cap on values beyond the 16 MB request.
  - Document-level permissions with Entra are still preview (2026-08-01-preview).
  - Foundry IQ knowledge bases return unfiltered results when the user's token header is missing, so a server must treat a missing token as an error.
- **Google Agent Search** (Vertex AI Search's new name). `ANY()` on a string array.
  - Document ACLs are preview and are chosen when the data store is created.
  - The user's identity comes through Workforce Identity Federation: 200 groups from an Entra JWT, 400 with extra attributes.
- **Many groups.** The filter carries only the caller's groups that gate some page, 11 at most in the lab. With none, no retrieval call is made at all, because on several platforms an empty filter means everything.

**W1-D11, the exit drill.** sqlite-vec 0.1.9 loads on Windows from the standard `sqlite3`. It has no list column, so the groups go in a side table and the KNN query takes `chunk_id IN (SELECT ...)`, which filters before the search (local check). It is pre-v1 and quiet since May 2026, which is enough for a drill.

**Embeddings.**
- The query and document prefixes are confirmed on Nomic's, Google's, and Qwen's model cards.
- qwen3-embedding's Apache 2.0 license appears only on its Hugging Face card, and the chapter cites it as such.
- Ollama truncates silently by default, so every call sends `truncate: false` and checks the vector width.

## W1-D14 to W1-D28, from the review of chapter 10 (29 October 2026)

A reader's review of chapter 10's draft checked 96 of its claims against the facts, and 77 held. These decisions came out of that review.

- **W1-D14 Path.** W1's harness reaches the knowledge server through the tool gateway, like every workflow (chapter 3's "one way to reach a tool per cloud"; chapter 6: "a caller that reached a server directly would bypass the gateway's policies"). The policy engine permits W1's harness `search_docs` and `caller_class` and nothing else, and the server learns the workflow from the gateway's token (`azp`). Chapter 3's workflow map changes to match. The lab connects directly, standing in for the gateway, which passes `X-Larkspur-Actor` through.
- **W1-D15 Knowledge Base.** W1's pages go into a Knowledge Base of their own, beside chapter 6's runbook Knowledge Base, reached by W1's tool and role only. It holds only the classes W1's manifest allows, so on AWS the filter carries the group test alone (up to 25 groups); the lab's store applies the manifest's class cap as well.
- **W1-D16 Token and removals.** The knowledge server's tokens carry no groups claim (chapter 6: a header value can't exceed 4 KB), so the membership table decides alone. The sync applies Graph's delta query on the tracked groups' direct members every five minutes and rebuilds the table from transitive members every night, which also drops deleted accounts. A direct member removed from a tracked group stops reading within minutes; a change inside a nested group waits for the night.
- **W1-D17 Group identity.** Pages name groups; security engineering keeps a reviewed map from each name to its group's object ID, and the sync tracks those IDs only, so a second group with the same display name never counts (Entra doesn't keep display names unique, and members can create security groups by default). A tracked ID that disappears stops the sync and raises an alarm. A page that names a group the map doesn't know is refused at ingestion.
- **W1-D18 What a page may say about itself.** The gate refuses a Confidential or Restricted page that names a broad group (all staff, all engineering). In production the pipeline also compares a page's groups with the source's own permissions (Confluence space permissions and page restrictions; the repository's teams) and refuses a page whose front matter is wider. The lab has no source system and implements the first rule only.
- **W1-D19 Token checks.** Beyond signature, issuer, audience, and expiry, the server requires its delegated scope in `scp`, an `azp` from an allowlist, and a user token (no app-only tokens). The sync writes users only.
- **W1-D20 The forwarded token.** The bot sends the runtime one token. Inside the runtime, AgentCore Identity's on-behalf-of exchange (Microsoft's on-behalf-of flow) makes the token for the knowledge server, as chapter 6 expects.
- **W1-D21 A call's class.** A conversation starts at the highest class the engineer may read, which the server reports through `caller_class`, a read-only tool the model is never offered. W1 keeps no history between questions. A tool result W1 can't read counts as Restricted.
- **W1-D22 Searches.** The harness allows two searches a question, the system prompt's own rule, and a failed search ends in "W1 couldn't search" rather than in the refusal.
- **W1-D23 Where answers go.** W1 answers in Teams' personal scope only, since a channel answer reaches members the filter never checked. The Slack app answers only while the conversation stays Internal and points to Teams for the rest.
- **W1-D24 Logs.** The harness's JSON log keeps the question (as the search's argument) and the answer, as chapter 5 decided for its audit record, so W1's log is a Restricted store; so is the server's audit line, which names pages.
- **W1-D25 Other ways to the text.** A service control policy denies `Retrieve` and `RetrieveAndGenerate` on W1's Knowledge Base, S3 Vectors reads on its index, and reads of W1's prefix to every principal but the knowledge tool's role, the Knowledge Base's role, and the pipeline's; a bucket policy admits writes to the prefix from the pipeline's role alone.
- **W1-D26 The gate on changes.** The scorer checks one to three key facts a question; a refusal that hints a page exists fails; an injection case fails on the planted conclusion in any words. Until chapter 15's judge, a person reads every refusal and injection answer before a change ships. The golden set and its results are Restricted data.
- **W1-D27 The membership table.** A versioned object in S3 under its own key, written only by the sync job's role. The server reloads it when it changes and, once it is older than a day and a half, grants only the broad groups.
- **W1-D28 Refusals.** Every refusal ends with one fixed sentence, the same whether or not a page exists: for anything outside your documents, ask the team that owns the system, or the incident commander during an incident. This gives the refused engineer a route and confirms nothing.

Built only in production and described in the README rather than run: W1-D20 (the on-behalf-of exchange), W1-D23 (Teams' personal scope, the Slack rule), and W1-D25 (the service control policy).

## W1-D5 and W1-D6 settled (29 October 2026)

W1-D5 holds: a refusal never says a restricted page exists. W1-D6 takes the first branch: Restricted pages are indexed, and Larkspur's data protection officer, Yuki Tanaka, signs for the managed embedding, the index, and `Retrieve`. The lab needs no such signature, since its embedding model runs on the workstation. W1-D14 to W1-D28 stand.
