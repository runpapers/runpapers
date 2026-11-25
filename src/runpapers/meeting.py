"""`rp meeting "<topic>"`: assemble a multi-paper workspace built on pack `[profile]` metadata.

Selects verified packs matching a topic or explicit paper IDs, computes shared vs paper-specific `[profile]`
axes (`species`, `tissues`, `assays`, `cell_types`, `key_genes`) and combined `data_terms`, materializes
isolated workspaces under `papers/<doi slug>/`, mirrors each paper's `SKILL.md` for progressive disclosure,
and writes cross-paper scientific guardrails (`MEETING.md`, `AGENTS.md`)."""
import re
import sys
from pathlib import Path

from . import __version__, search, verify, workspace
from .catalog import open_catalog
from .registry import write_json

MEETING_FILE = ".runpapers-meeting.json"
PROFILE_KEYS = ("species", "tissues", "assays", "cell_types", "key_genes")


def _slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:40].rstrip("-") or "topic"


def compute_overlap(entries):
    """Compare `[profile]` fields and `data_terms` across selected pack entries."""
    # Map normalized term -> (canonical display string, set of paper slugs containing it)
    shared = {}
    by_paper = {e["slug"]: {} for e in entries}
    for key in PROFILE_KEYS:
        occ = {}
        for e in entries:
            ck = e["slug"]
            for raw in (e.get("profile") or {}).get(key) or []:
                val = str(raw).strip()
                if not val:
                    continue
                norm = val.lower()
                disp, holders = occ.setdefault(norm, (val, []))
                if ck not in holders:
                    holders.append(ck)
        shared_terms = [disp for _, (disp, holders) in occ.items() if len(holders) >= 2]
        shared[key] = shared_terms
        for e in entries:
            ck = e["slug"]
            uniq = [disp for _, (disp, holders) in occ.items() if holders == [ck]]
            if uniq:
                by_paper[ck][key] = uniq
    all_terms = sorted({t for e in entries for t in (e.get("data_terms") or []) if t})
    terms_by_paper = {e["slug"]: list(e.get("data_terms") or []) for e in entries}
    return {
        "shared": shared,
        "by_paper": by_paper,
        "data_terms": all_terms,
        "data_terms_by_paper": terms_by_paper,
    }


def _meeting_md(topic, selected, overlap, planned_matches, rp_cmd):
    lines = [
        f"# RunPapers meeting: {topic}", "",
        f"This workspace brings together **{len(selected)}** verified RunPapers pack(s) so you and your AI agent(s) "
        f"can compare findings across papers and run cross-paper analyses without mixing up taxonomies or double-counting shared donors.",
        "", "## Selected paper packs", "",
        "| Workspace | Paper | DOI / PMID | Stage & badges | Recipes |",
        "|---|---|---|---|---|",
    ]
    for e in selected:
        badges = ", ".join(k for k, v in (e.get("badges") or {}).items() if v == "pass") or e["stage"]
        ids_col = f"`{e['doi']}`" + (f" / PMID `{e['pmid']}`" if e.get("pmid") else "")
        recs = ", ".join(f"`{r['id']}` ({r.get('panel', '')})" for r in (e.get("recipes") or [])) or "—"
        lines.append(
            f"| `papers/{e['folder']}/` | **{e['title']}** ({e.get('first_author', '')} et al., *{e.get('journal', '')}* {e.get('year', '')}) "
            f"| {ids_col} | {badges} | {recs} |"
        )

    lines += ["", "## Biological profile comparison (`[profile]`)", ""]
    any_shared = False
    for k in PROFILE_KEYS:
        vals = overlap["shared"].get(k) or []
        if vals:
            any_shared = True
            lines.append(f"- **Shared `{k}` (>= 2 papers):** {', '.join(vals)}")
    if not any_shared:
        lines.append("- **Shared `[profile]` terms:** none recorded across >= 2 packs (compare via explicit metadata joins or orthogonal modalities).")
    for e in selected:
        uniq = overlap["by_paper"].get(e["slug"]) or {}
        if uniq:
            parts = [f"{k}: {', '.join(v)}" for k, v in uniq.items()]
            lines.append(f"- **Unique to `{e['folder']}`:** " + "; ".join(parts))

    lines += [
        "", "## Cross-paper scientific guardrails (read before comparing)", "",
        "1. **Check for shared donors before pooling or meta-analyzing (pseudoreplication check):** "
        "Consortium studies (for example, BICAN / Allen Brain Cell Atlas companion papers) often profile overlapping human or animal donors "
        "(`donor_label` / `donor.csv`). Never treat overlapping donors across two packs as independent biological replicates.",
        "2. **Donors or animals — never individual cells — are the replicate unit:** "
        "Compute per-donor summaries inside each pack first before comparing effect sizes across species, regions, or studies.",
        "3. **Align cell-type taxonomies explicitly:** "
        "Different papers (or preprints vs published versions) may rename cell types or report different hierarchy levels. "
        "Write explicit label-mapping tables in `synthesis/` grounded in each pack's `SKILL.md` rather than matching strings blindly.",
        "4. **Respect modality and data scope boundaries:** "
        "If one pack covers cell-level metadata and composition while another includes expression or chromatin matrices, state plainly what each pack's files can and cannot test.",
    ]

    lines += ["", "## Data terms and citations", ""]
    if overlap["data_terms"]:
        for t in overlap["data_terms"]:
            lines.append(f"- {t}")
    else:
        lines.append("- Check each pack's `papers/<workspace>/pack.toml` and `SKILL.md` before commercial use or publication.")
    lines.append("")
    lines.append("Cite every paper's DOI, its original data repository per the terms above, and the corresponding RunPapers pack version.")

    if planned_matches:
        lines += [
            "", "## Matching planned papers (not yet packed)", "",
            f"These collection papers also matched the topic but do not have a verified pack yet (upvote with `{rp_cmd} request <DOI>`):", "",
        ]
        for p in planned_matches:
            pmid_txt = f" · PMID {p['pmid']}" if p.get("pmid") else ""
            lines.append(f"- **{p.get('title', p['doi'])}** ({p.get('first_author', '')} et al., *{p.get('journal', '')}* {p.get('year', '')}) — DOI `{p['doi']}`{pmid_txt}")

    return "\n".join(lines) + "\n"


def _agents_md(topic, selected, rp_cmd):
    pack_bullets = "\n".join(
        f"   - `papers/{e['folder']}/`: {e['title']} (DOI {e['doi']}, v{e['version']})"
        for e in selected
    )
    return f"""# RunPapers multi-paper meeting workspace: {topic}

You are coordinating a rigorous cross-paper scientific analysis across {len(selected)} verified RunPapers pack(s).

## Workflow

1. **Read `MEETING.md` completely** to see the selected packs, their shared vs unique `[profile]` axes, and the mandatory cross-paper guardrails.
2. **Ground each paper independently first** (if your environment supports subagents, assign one specialist subagent per folder; otherwise inspect them one by one):
{pack_bullets}
   Inside each `papers/<name>/` folder, read its `SKILL.md` in full and run baseline recipes (`{rp_cmd} run <recipe>`) when needed before writing new code.
3. **Synthesize in `synthesis/`:**
   - Write cross-paper comparison scripts and explicit taxonomy/donor-overlap tables in `synthesis/`.
   - Check whether donor IDs overlap across packs before claiming independent replication or combining statistics.
   - Keep direct data observations (`[DATA]`), literature claims (`[LIT]`), and your interpretations (`[INTERP]`) clearly separated.
4. **Citations and data terms:** Report donor counts (`N` donors per group), cite every paper DOI and RunPapers pack version, and remind the user of source-specific data terms from `MEETING.md` before commercial use or publication.
"""


def build_meeting(
    topic,
    papers=(),
    collection=None,
    species=(),
    tissues=(),
    assays=(),
    cell_types=(),
    genes=(),
    max_papers=5,
    min_stage="runs",
    fetch_data=False,
    dest=None,
    source=None,
    rp_cmd="rp",
    quiet=False,
    **_ignored,
):
    """Build a multi-paper meeting folder for `topic`. Returns `(target_path, manifest_dict)`."""
    if min_stage not in search.STAGE_RANK:
        raise SystemExit(f"unknown --min-stage {min_stage!r}; choose from {', '.join(verify.STAGES)}")
    min_rank = search.STAGE_RANK[min_stage]

    cat = open_catalog(source)
    all_entries = cat.entries(include_planned=True)
    by_doi = {e["doi"]: e for e in all_entries}

    selected = []
    seen_dois = set()
    for raw_id in papers or ():
        for part in str(raw_id).split(","):
            ident = part.strip()
            if not ident:
                continue
            doi = cat.resolve_known(ident)
            if not doi or doi not in by_doi:
                raise SystemExit(f"unknown paper {ident!r}: not found in catalog")
            entry = by_doi[doi]
            if not entry.get("packed"):
                raise SystemExit(f"{doi} is planned and has no pack yet (`rp request {doi}`)")
            if search.STAGE_RANK.get(entry["stage"], 0) < min_rank:
                raise SystemExit(f"{doi} is at stage {entry['stage']!r} (below --min-stage {min_stage!r})")
            if doi not in seen_dois:
                seen_dois.add(doi)
                selected.append(dict(entry))

    hits = search.search_entries(
        all_entries,
        query=topic,
        species=species,
        tissues=tissues,
        assays=assays,
        cell_types=cell_types,
        genes=genes,
        collection=collection,
        include_planned=True,
        limit=100,
    )

    planned_matches = []
    for _score, e in hits:
        if e["doi"] in seen_dois:
            continue
        if not e.get("packed"):
            if len(planned_matches) < 10:
                planned_matches.append({k: e.get(k) for k in ("doi", "pmid", "title", "first_author", "journal", "year")})
            continue
        if search.STAGE_RANK.get(e["stage"], 0) < min_rank:
            continue
        if len(selected) < int(max_papers):
            seen_dois.add(e["doi"])
            selected.append(dict(e))

    if not selected:
        hint = f" ({len(planned_matches)} planned paper(s) matched; upvote with `{rp_cmd} request <DOI>`)" if planned_matches else ""
        raise SystemExit(f"no packs at stage >= {min_stage!r} matched {topic!r}{hint}")

    target = Path(dest).resolve() if dest else (Path.cwd() / f"meeting-{_slugify(topic)}")
    if target.exists() and any(target.iterdir()) and not (target / MEETING_FILE).is_file():
        raise SystemExit(f"{target} exists and is not a RunPapers meeting workspace")
    (target / "papers").mkdir(parents=True, exist_ok=True)
    (target / "synthesis").mkdir(parents=True, exist_ok=True)

    used_folders = set()
    notes = []
    for e in selected:
        base_folder = e.get("slug") or _slugify(e["doi"])
        folder = base_folder
        idx = 2
        while folder in used_folders:
            folder = f"{base_folder}-{idx}"
            idx += 1
        used_folders.add(folder)
        e["folder"] = folder
        ws_dir = target / "papers" / folder
        _, ws_notes = workspace.get(
            e["doi"],
            dest=ws_dir,
            source=cat.source_str,
            fetch_data=fetch_data,
            rp_cmd=rp_cmd,
            quiet=True,
        )
        notes.extend(ws_notes)
        skill_txt = (ws_dir / "SKILL.md").read_text(encoding="utf-8")
        for sroot in (".agents/skills", ".claude/skills", ".gemini/skills"):
            sd = target / sroot / f"runpapers-{folder}"
            sd.mkdir(parents=True, exist_ok=True)
            (sd / "SKILL.md").write_text(skill_txt, encoding="utf-8")

    # Key overlap by folder name so multi-pack slugs stay unambiguous.
    for e in selected:
        e["slug"] = e["folder"]
    overlap = compute_overlap(selected)

    (target / "MEETING.md").write_text(_meeting_md(topic, selected, overlap, planned_matches, rp_cmd), encoding="utf-8")
    agents_txt = _agents_md(topic, selected, rp_cmd)
    (target / "AGENTS.md").write_text(agents_txt, encoding="utf-8")
    (target / "GEMINI.md").write_text(agents_txt, encoding="utf-8")
    (target / "CLAUDE.md").write_text("@AGENTS.md\n@MEETING.md\n", encoding="utf-8")
    (target / "synthesis" / "README.md").write_text(
        "# Synthesis workspace\n\n"
        "Place cross-paper scripts, donor-overlap checks, taxonomy alignment tables, and the synthesis report here.\n"
        "Read `../MEETING.md` and each pack's `../papers/<doi slug>/SKILL.md` before running comparisons.\n",
        encoding="utf-8",
    )

    manifest = {
        "topic": topic,
        "created_at": verify.now(),
        "rp_version": __version__,
        "workspace": str(target),
        "min_stage": min_stage,
        "packs": [
            {
                "doi": e["doi"],
                "pmid": e.get("pmid"),
                "title": e["title"],
                "slug": e["folder"],
                "folder": f"papers/{e['folder']}",
                "version": e.get("version"),
                "pack_hash": e.get("pack_hash"),
                "stage": e["stage"],
                "badges": e.get("badges", {}),
                "profile": e.get("profile", {}),
                "data_terms": e.get("data_terms", []),
            }
            for e in selected
        ],
        "profile_overlap": overlap,
        "data_terms": overlap["data_terms"],
        "planned_matches": planned_matches,
        "notes": notes,
    }
    write_json(target / MEETING_FILE, manifest)
    if not quiet:
        print(f"meeting workspace ready ({len(selected)} pack(s)): {target}", file=sys.stderr)
    return target, manifest
