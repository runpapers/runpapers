"""Model Context Protocol (MCP) server for RunPapers (`rp mcp`).

Implements JSON-RPC 2.0 over `stdio` using only the Python standard library so `uvx runpapers mcp` starts
instantly with zero extra dependencies, plus an optional Streamable HTTP adapter when `runpapers[mcp]` is installed.

Exposes:
  - Tools: `search_papers`, `get_paper`, `get_skill` (Skills over MCP), `list_recipes`, `request_paper`
  - Resources: `skill://runpapers/<doi-prefix>/<doi-suffix>/SKILL.md` (+ `references/{path}` template)
  - Prompts: `use_paper`
"""
import json
import sys
import urllib.parse

from . import __version__, ids, search
from .catalog import parse_skill_frontmatter
from .verify import STAGES

SUPPORTED_PROTOCOLS = ("2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL = "2025-03-26"

SERVER_INSTRUCTIONS = (
    "RunPapers provides verified, agent-ready packs for published scientific papers. "
    "Use `search_papers` to find papers by topic, species, tissue, assay, cell type, gene, DOI, or PMID; "
    "`get_paper` for metadata, verification badges, and source-specific data terms; "
    "`get_skill` (or `skill://runpapers/...` resources) to load a paper's Agent Skills guardrails (`SKILL.md`); "
    "`list_recipes` to inspect figure-reproducing scripts and locked paper target numbers; and "
    "`request_paper` to request or upvote an unpacked paper."
)

READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

TOOLS = [
    {
        "name": "search_papers",
        "description": "Search available RunPapers packs and requested papers by free-text query and five-group tags (species, tissue_cell, data_type, disease, collection).",
        "annotations": READ_ONLY_ANNOTATIONS,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text query: topic, title, author, gene, cell type, tag synonym, DOI, or PMID."},
                "species": {"type": "array", "items": {"type": "string"}, "description": "Filter by species slug or label (e.g. 'marmoset', 'Human')."},
                "tissue_cell": {"type": "array", "items": {"type": "string"}, "description": "Filter by tissue, brain region, or cell line (e.g. 'putamen', 'HEK293')."},
                "data_type": {"type": "array", "items": {"type": "string"}, "description": "Filter by data type (e.g. 'patch-seq', 'Single-nucleus multiome')."},
                "disease": {"type": "array", "items": {"type": "string"}, "description": "Filter by disease (e.g. 'none', \"Parkinson's disease\")."},
                "tissues": {"type": "array", "items": {"type": "string"}, "description": "Alias for tissue_cell."},
                "assays": {"type": "array", "items": {"type": "string"}, "description": "Alias for data_type."},
                "cell_types": {"type": "array", "items": {"type": "string"}, "description": "Optional [profile] cell-type filter (e.g. 'D2 SPN', 'astrocyte')."},
                "genes": {"type": "array", "items": {"type": "string"}, "description": "Optional [profile] key-gene filter (e.g. 'HTR7', 'SMYD2')."},
                "collection": {
                    "anyOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "string"},
                    ],
                    "description": "Filter by collection slug(s) or label(s) (e.g. ['bican-2026'] or 'BICAN basal ganglia 2026').",
                },
                "sort": {"type": "string", "enum": ["most_used", "newest", "title"], "default": "most_used", "description": "Sort order when query is empty."},
                "min_stage": {"type": "string", "enum": STAGES, "description": "Minimum verification stage (e.g. 'runs', 'reproduces')."},
                "include_planned": {"type": "boolean", "default": True, "description": "Include requested and unpacked papers after available packs."},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
        },
    },
    {
        "name": "get_paper",
        "description": "Get full metadata, verification badges, data manifest, source-specific data terms, and workspace setup command for a paper by DOI, PMID, PMCID, or URL.",
        "annotations": READ_ONLY_ANNOTATIONS,
        "inputSchema": {
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string", "description": "DOI, PMID, PMCID, preprint DOI, or doi.org/PubMed URL."},
            },
        },
    },
    {
        "name": "get_skill",
        "description": "Skills over MCP: load a paper pack's Agent Skills instructions (`SKILL.md`), a specific `## ` section (e.g. 'Guardrails'), or an on-demand file from `references/`.",
        "annotations": READ_ONLY_ANNOTATIONS,
        "inputSchema": {
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string", "description": "DOI, PMID, PMCID, or URL of the paper."},
                "section": {"type": "string", "description": "Optional `## ` heading filter inside SKILL.md (e.g. 'Data', 'Guardrails')."},
                "reference": {"type": "string", "description": "Optional relative filename under `references/` for progressive disclosure."},
            },
        },
    },
    {
        "name": "list_recipes",
        "description": "List figure-reproducing recipes in a paper's pack, their resource needs (data size, memory, GPU, minutes), and locked target numbers from `targets.toml`.",
        "annotations": READ_ONLY_ANNOTATIONS,
        "inputSchema": {
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string", "description": "DOI, PMID, PMCID, or URL of the paper."},
                "max_memory_gb": {"type": "number", "description": "Optional maximum memory budget in GB."},
                "gpu": {"type": "boolean", "description": "Optional filter on whether the recipe requires a GPU."},
                "include_targets": {"type": "boolean", "default": True, "description": "Include expected paper metrics and tolerances."},
            },
        },
    },
    {
        "name": "request_paper",
        "description": "Request a paper to be packed by RunPapers or add a vote to an existing request.",
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        "inputSchema": {
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string", "description": "DOI, PMID, PMCID, or article URL."},
                "note": {"type": "string", "default": "", "description": "Optional note on which figure or question matters most."},
                "resolve_online": {"type": "boolean", "default": False, "description": "Allow NCBI/Crossref ID lookup when a PMID/PMCID is not in the local catalog."},
            },
        },
    },
]

RESOURCE_TEMPLATES = [
    {
        "uriTemplate": "skill://runpapers/{doi_prefix}/{doi_suffix}/SKILL.md",
        "name": "paper-skill",
        "title": "RunPapers Paper Agent Skill (SKILL.md)",
        "description": "Agent Skills instructions, data schema, recipes, and scientific guardrails for one published paper.",
        "mimeType": "text/markdown",
    },
    {
        "uriTemplate": "skill://runpapers/{doi_prefix}/{doi_suffix}/references/{path}",
        "name": "paper-skill-reference",
        "title": "RunPapers Pack Reference Document",
        "description": "Optional detailed reference file inside a pack's `references/` directory.",
        "mimeType": "text/markdown",
    },
]

PROMPTS = [
    {
        "name": "use_paper",
        "description": "Set up a local RunPapers workspace for a paper, follow its SKILL.md guardrails, reproduce a figure panel, and answer a scientific question.",
        "arguments": [
            {"name": "id", "description": "DOI, PMID, PMCID, or URL of the paper.", "required": True},
            {"name": "question", "description": "Scientific question to investigate after reproducing a published panel.", "required": False},
        ],
    }
]


# --------------------------------------------------------------------------- pure handlers
def _fmt_search_markdown(payload):
    matches = payload["matches"]
    if not matches:
        return "No matching papers found."
    lines = [f"Found {payload['total']} matching paper(s):"]
    for m in matches:
        badges = ", ".join(k for k, v in (m.get("badges") or {}).items() if v == "pass")
        b_txt = f"badges: {badges}" if badges else f"status: {m.get('status') or m.get('stage', 'available')}"
        pmid_txt = f", PMID {m['pmid']}" if m.get("pmid") else ""
        lines.append(f"- **{m['title']}** ({m.get('first_author', '')} et al., *{m.get('journal', '')}* {m.get('year', '')}) — DOI `{m['doi']}`{pmid_txt} [{b_txt}]")
    return "\n".join(lines)


def _fmt_paper_markdown(det):
    st_label = det.get("stage") or det.get("status", "available")
    lines = [
        f"# {det['title']}",
        f"{det.get('first_author', '')} et al., *{det.get('journal', '')}* {det.get('year', '')} · DOI `{det['doi']}`"
        + (f" · PMID `{det['pmid']}`" if det.get("pmid") else ""),
        f"Stage: `{st_label}`" + (f" · Version: `{det['version']}` · Hash: `{det['pack_hash']}`" if det.get("packed") else ""),
    ]
    if det.get("verification_warning"):
        lines.append(f"Warning: {det['verification_warning']}")
    if not det.get("packed"):
        lines.append(det.get("request_hint", ""))
        return "\n\n".join(x for x in lines if x)
    passing = ", ".join(k for k, v in (det.get("badges") or {}).items() if v == "pass") or "none"
    lines.append(f"Passing badges: {passing}")
    if det.get("summary"):
        lines.append(det["summary"])
    if det.get("data_terms"):
        lines.append("Data terms: " + "; ".join(det["data_terms"]))
    lines.append(f"Local workspace setup: `{det['workspace_command']}`")
    return "\n\n".join(lines)


def handle_tool_call(catalog, name, arguments):
    args = arguments or {}
    if name not in {t["name"] for t in TOOLS}:
        raise LookupError(f"unknown tool: {name!r}")
    try:
        if name == "search_papers":
            hits = search.search_entries(
                catalog.entries(include_planned=bool(args.get("include_planned", True))),
                query=args.get("query", ""),
                species=args.get("species") or (),
                tissue_cell=[*(args.get("tissue_cell") or ()), *(args.get("tissues") or ())],
                data_type=[*(args.get("data_type") or ()), *(args.get("assays") or ())],
                disease=args.get("disease") or (),
                cell_types=args.get("cell_types") or (),
                genes=args.get("genes") or (),
                collection=args.get("collection"),
                min_stage=args.get("min_stage"),
                include_planned=bool(args.get("include_planned", True)),
                sort=args.get("sort", "most_used"),
                voc=catalog.vocab(),
                limit=int(args.get("limit", 20)),
            )
            matches = []
            for score, e in hits:
                matches.append({
                    "score": score,
                    "doi": e["doi"],
                    "pmid": e.get("pmid"),
                    "title": e["title"],
                    "first_author": e.get("first_author"),
                    "senior_author": e.get("senior_author"),
                    "journal": e.get("journal"),
                    "year": e.get("year"),
                    "slug": e.get("slug"),
                    "packed": e.get("packed", False),
                    "status": search.public_status(e),
                    "status_reason": e.get("status_reason"),
                    "votes": int(e.get("votes") or 0),
                    "issue_url": e.get("issue_url"),
                    "published_at": e.get("published_at"),
                    "stage": e.get("stage") or ("released" if search.public_status(e) == "available" else "planned"),
                    "badges": e.get("badges", {}),
                    "summary": e.get("summary", ""),
                    "tags": e.get("tags", {}),
                    "profile": e.get("profile", {}),
                    "data_bytes": e.get("data_bytes", 0),
                    "data_terms": e.get("data_terms", []),
                    "recipes": [{"id": r["id"], "panel": r.get("panel", ""), "data_bytes": r.get("data_bytes", 0),
                                 "memory_gb": r.get("memory_gb", 8), "gpu": bool(r.get("gpu", False)), "minutes": r.get("minutes", 20)}
                                for r in (e.get("recipes") or [])],
                })
            payload = {"total": len(matches), "matches": matches}
            return {"content": [{"type": "text", "text": _fmt_search_markdown(payload)}], "structuredContent": payload, "isError": False}

        if name == "get_paper":
            if not args.get("id"):
                raise ValueError("missing required argument 'id'")
            det = catalog.paper_detail(args["id"])
            return {"content": [{"type": "text", "text": _fmt_paper_markdown(det)}], "structuredContent": det, "isError": False}

        if name == "get_skill":
            if not args.get("id"):
                raise ValueError("missing required argument 'id'")
            sk = catalog.get_skill(args["id"], section=args.get("section"), reference=args.get("reference"))
            header = [f"<!-- RunPapers skill {sk['skill_name']} v{sk['version']} ({sk['doi']}) | status: {sk.get('stage') or sk.get('status', 'available')} -->"]
            if sk.get("verification_warning"):
                header.append(f"> Warning: {sk['verification_warning']}")
            if sk.get("data_terms"):
                header.append(f"> Data terms: {'; '.join(sk['data_terms'])}")
            text = "\n".join(header) + "\n\n" + sk["content_markdown"]
            return {"content": [{"type": "text", "text": text}], "structuredContent": sk, "isError": False}

        if name == "list_recipes":
            if not args.get("id"):
                raise ValueError("missing required argument 'id'")
            res = catalog.list_recipes(
                args["id"],
                max_memory_gb=args.get("max_memory_gb"),
                gpu=args.get("gpu"),
                include_targets=bool(args.get("include_targets", True)),
            )
            lines = [f"Recipes for DOI `{res['doi']}` (stage: `{res.get('stage') or res.get('status', 'available')}`):"]
            for r in res["recipes"]:
                nt = len(r.get("targets") or [])
                t_info = f", {nt} target(s)" if "targets" in r else ""
                hw = f"{r['memory_gb']:g} GB RAM, {'GPU' if r['gpu'] else 'CPU'}, {r['minutes']:g}m"
                lines.append(f"- `{r['id']}` ({r['panel']}, {hw}): {r['title']}{t_info} — run: `{r['run_command']}`")
            return {"content": [{"type": "text", "text": "\n".join(lines)}], "structuredContent": res, "isError": False}

        if name == "request_paper":
            if not args.get("id"):
                raise ValueError("missing required argument 'id'")
            res = catalog.request_paper(
                args["id"],
                note=args.get("note") or "",
                by="local:mcp",
                resolve_online=bool(args.get("resolve_online", False)),
            )
            state = "Recorded new request" if res.get("new") else "Request/vote already recorded"
            txt = f"{state} for DOI `{res['doi']}` (votes: {res.get('votes', 1)}). Public issue link: {res['issue_url']}"
            return {"content": [{"type": "text", "text": txt}], "structuredContent": res, "isError": False}

    except (ids.IdError, KeyError, ValueError, PermissionError, FileNotFoundError, SystemExit) as exc:
        return {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}


def list_resources(catalog):
    resources = []
    for e in catalog.entries(include_planned=False):
        if not e.get("packed"):
            continue
        doi = e["doi"]
        try:
            fm = parse_skill_frontmatter(catalog.read_pack_file(doi, "SKILL.md"))
        except Exception:
            fm = {"name": f"runpapers-{e['slug']}", "description": e.get("summary", "")}
        badges = ", ".join(k for k, v in (e.get("badges") or {}).items() if v == "pass") or "none"
        terms = "; ".join(e.get("data_terms") or []) or "see pack"
        desc = (fm["description"] or e.get("summary") or e["title"]).strip()
        resources.append({
            "uri": f"skill://runpapers/{ids.doi_relpath(doi)}/SKILL.md",
            "name": fm["name"] or f"runpapers-{e['slug']}",
            "title": e["title"],
            "description": f"{desc} [stage: {e.get('stage') or e.get('status', 'available')}; badges: {badges}; data terms: {terms}]",
            "mimeType": "text/markdown",
        })
    return {"resources": resources}


def parse_skill_uri(uri):
    prefix = "skill://runpapers/"
    if not isinstance(uri, str) or not uri.startswith(prefix):
        raise PermissionError(f"unsupported URI scheme: {uri!r}")
    rest = uri[len(prefix):]
    raw_parts = rest.split("/")
    if ".." in raw_parts or "." in raw_parts or "\\" in rest:
        raise PermissionError(f"unsafe path in resource URI: {uri!r}")
    if rest.endswith("/SKILL.md"):
        doi_part, relpath = rest[: -len("/SKILL.md")], "SKILL.md"
    elif "/references/" in rest:
        doi_part, sub = rest.split("/references/", 1)
        if not sub:
            raise PermissionError(f"missing reference filename in URI: {uri!r}")
        relpath = f"references/{sub}"
    else:
        raise PermissionError(f"only SKILL.md and references/* resources may be read (got {uri!r})")
    doi = ids.normalize_doi(urllib.parse.unquote(doi_part))
    return doi, relpath


def read_resource(catalog, uri):
    doi, relpath = parse_skill_uri(uri)
    text = catalog.read_pack_file(doi, relpath)
    return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text}]}


def get_prompt(catalog, name, arguments):
    if name != "use_paper":
        raise LookupError(f"unknown prompt: {name!r}")
    args = arguments or {}
    ident = args.get("id")
    if not ident:
        raise ValueError("missing required prompt argument 'id'")
    det = catalog.paper_detail(ident)
    if not det.get("packed"):
        raise ValueError(f"{det['doi']} is planned and has no pack yet")
    sk = catalog.get_skill(det["doi"])
    first = next((r for r in det.get("recipes", []) if not r.get("gpu") and (r.get("memory_gb") or 8) <= 14),
                 (det.get("recipes") or [{}])[0])
    panel = first.get("panel") or "a main figure"
    rid = first.get("id") or "<recipe>"
    question = args.get("question") or "<ask the user what question they want answered after reproducing the panel>"
    terms = "; ".join(det.get("data_terms") or []) or "see SKILL.md"
    prompt_txt = (
        f"Work with the verified RunPapers pack for \"{det['title']}\" (DOI {det['doi']}, version {det['version']}).\n\n"
        f"1. Set up the local workspace: `{det['workspace_command']}` and `cd {det['slug']}`.\n"
        f"2. Follow every guardrail in `SKILL.md` below.\n"
        f"3. Reproduce {panel} (`rp run {rid}`) and show the figure alongside the paper-vs-reproduced target numbers.\n"
        f"4. Answer this question using scripts in `analyses/`: {question}\n"
        f"5. Cite DOI {det['doi']} and RunPapers v{det['version']}, and remind the user of data terms: {terms}.\n\n"
        f"---\n{sk['content_markdown']}"
    )
    return {
        "description": f"Use RunPapers pack for {det['title']} (DOI {det['doi']})",
        "messages": [{"role": "user", "content": {"type": "text", "text": prompt_txt}}],
    }


# --------------------------------------------------------------------------- JSON-RPC 2.0 dispatch & stdio loop
def dispatch_rpc(catalog, msg):
    """Handle one JSON-RPC 2.0 message dict. Returns a response dict, or None for notifications."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                "error": {"code": -32600, "message": "Invalid JSON-RPC 2.0 request"}}
    method = msg.get("method")
    is_notification = "id" not in msg
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if is_notification:
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": str(message)}}

    try:
        if method == "initialize":
            want = params.get("protocolVersion", DEFAULT_PROTOCOL)
            proto = want if want in SUPPORTED_PROTOCOLS else DEFAULT_PROTOCOL
            return ok({
                "protocolVersion": proto,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "serverInfo": {"name": "runpapers", "version": __version__},
                "instructions": SERVER_INSTRUCTIONS,
            })
        if method == "ping":
            return ok({})
        if method == "tools/list":
            return ok({"tools": TOOLS})
        if method == "tools/call":
            return ok(handle_tool_call(catalog, params.get("name"), params.get("arguments")))
        if method == "resources/list":
            return ok(list_resources(catalog))
        if method == "resources/templates/list":
            return ok({"resourceTemplates": RESOURCE_TEMPLATES})
        if method == "resources/read":
            return ok(read_resource(catalog, params.get("uri")))
        if method == "prompts/list":
            return ok({"prompts": PROMPTS})
        if method == "prompts/get":
            return ok(get_prompt(catalog, params.get("name"), params.get("arguments")))
        return err(-32601, f"Method not found: {method}")
    except LookupError as exc:
        return err(-32602, exc)
    except (ids.IdError, KeyError, ValueError, PermissionError, FileNotFoundError) as exc:
        return err(-32602, exc)
    except Exception as exc:
        return err(-32603, f"Internal error: {exc}")


def _read_rpc_message(in_stream):
    """Read one JSON-RPC message supporting MCP newline-delimited JSON (and optional Content-Length framing)."""
    while True:
        line = in_stream.readline()
        if line == "":
            return None, "eof"
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("content-length:"):
            length = int(stripped.split(":", 1)[1].strip())
            while True:
                hdr = in_stream.readline()
                if hdr in ("", "\r\n", "\n"):
                    break
            body = in_stream.read(length)
            return json.loads(body), "lsp"
        return json.loads(stripped), "line"


def _write_rpc_message(out_stream, resp, mode="line"):
    payload = json.dumps(resp, separators=(",", ":"), ensure_ascii=False)
    if mode == "lsp":
        raw = payload.encode("utf-8")
        out_stream.write(f"Content-Length: {len(raw)}\r\n\r\n{payload}")
    else:
        out_stream.write(payload + "\n")
    out_stream.flush()


def serve_stdio(catalog, in_stream=None, out_stream=None):
    """Run the stdlib MCP JSON-RPC 2.0 server over stdio with stdout guarded against stray writes."""
    inp = in_stream or sys.stdin
    out = out_stream or sys.stdout
    orig_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        while True:
            try:
                msg, mode = _read_rpc_message(inp)
            except json.JSONDecodeError as exc:
                _write_rpc_message(out, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}})
                continue
            if mode == "eof":
                break
            if isinstance(msg, list):
                resps = [r for item in msg if (r := dispatch_rpc(catalog, item)) is not None]
                if resps:
                    _write_rpc_message(out, resps, mode=mode)
            else:
                resp = dispatch_rpc(catalog, msg)
                if resp is not None:
                    _write_rpc_message(out, resp, mode=mode)
    finally:
        sys.stdout = orig_stdout


def serve_streamable_http(catalog, host="127.0.0.1", port=8766):
    """Optional Streamable HTTP transport powered by the `mcp` package (`uvx 'runpapers[mcp]' mcp ...`)."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        raise SystemExit("Streamable HTTP transport requires the optional 'mcp' dependency: "
                         "run `uvx 'runpapers[mcp]' mcp --transport streamable-http`")
    srv = FastMCP("runpapers", instructions=SERVER_INSTRUCTIONS, host=host, port=port)

    @srv.tool(description=TOOLS[0]["description"])
    def search_papers(query: str = "", species: list[str] | None = None, tissue_cell: list[str] | None = None,
                      data_type: list[str] | None = None, disease: list[str] | None = None,
                      tissues: list[str] | None = None, assays: list[str] | None = None,
                      cell_types: list[str] | None = None, genes: list[str] | None = None,
                      collection: list[str] | str | None = None, sort: str = "most_used",
                      min_stage: str | None = None, include_planned: bool = True, limit: int = 20) -> dict:
        return handle_tool_call(catalog, "search_papers", {
            "query": query, "species": species, "tissue_cell": tissue_cell, "data_type": data_type,
            "disease": disease, "tissues": tissues, "assays": assays,
            "cell_types": cell_types, "genes": genes, "collection": collection, "sort": sort,
            "min_stage": min_stage, "include_planned": include_planned, "limit": limit,
        })["structuredContent"]

    @srv.tool(description=TOOLS[1]["description"])
    def get_paper(id: str) -> dict:
        res = handle_tool_call(catalog, "get_paper", {"id": id})
        if res["isError"]:
            raise ValueError(res["content"][0]["text"])
        return res["structuredContent"]

    @srv.tool(description=TOOLS[2]["description"])
    def get_skill(id: str, section: str | None = None, reference: str | None = None) -> dict:
        res = handle_tool_call(catalog, "get_skill", {"id": id, "section": section, "reference": reference})
        if res["isError"]:
            raise ValueError(res["content"][0]["text"])
        return res["structuredContent"]

    @srv.tool(description=TOOLS[3]["description"])
    def list_recipes(id: str, max_memory_gb: float | None = None, gpu: bool | None = None, include_targets: bool = True) -> dict:
        res = handle_tool_call(catalog, "list_recipes", {"id": id, "max_memory_gb": max_memory_gb, "gpu": gpu, "include_targets": include_targets})
        if res["isError"]:
            raise ValueError(res["content"][0]["text"])
        return res["structuredContent"]

    @srv.tool(description=TOOLS[4]["description"])
    def request_paper(id: str, note: str = "", resolve_online: bool = False) -> dict:
        res = handle_tool_call(catalog, "request_paper", {"id": id, "note": note, "resolve_online": resolve_online})
        if res["isError"]:
            raise ValueError(res["content"][0]["text"])
        return res["structuredContent"]

    srv.run(transport="streamable-http")
