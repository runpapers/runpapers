# RunPapers words

The words the website, the repository and our profiles use. Edit freely: the website takes its texts from here
once the redesign is built (the engineer copies them into the site templates).

## Name
**RunPapers**, one word, capital R and P. Lowercase `runpapers` only in web addresses, commands and account
names (runpapers.com, `uvx runpapers`, github.com/runpapers).

## Tagline
**Reproduce the paper. Then ask your own question.**

Other versions, for tight spaces:
- Published papers your own AI agent can run.
- Papers your AI agent can run.

## One sentence (meta description, search results, profile bios; under 160 characters)
RunPapers turns published papers into packs your own AI agent can run: it reproduces the figures from the
original data, then answers your questions.

## About (one paragraph)
RunPapers makes published papers usable by any scientist, programmer or not. For each paper we build a pack: the
paper's numbers, the original data's location, and tested instructions for AI agents. You copy one prompt into
your own agent (Claude Code, Codex, Antigravity or another one that can run commands), and in a few minutes it
reproduces a figure from the original data and shows the paper's numbers next to its own. Then it is your
analyst: ask it new questions about the same data. We check every pack against the paper before it is listed.
RunPapers is free, open source and non-profit; we never see your questions and never run a model for you.

## Home page
- Heading: the tagline.
- Under it: "Pick a paper, copy one prompt into your AI agent, and watch it reproduce a figure from the original
  data. Then ask it anything the data can answer."
- Search box placeholder: "Search by title, DOI, PMID, gene, cell type or species"
- Three steps (a real sequence, so numbered):
  1. Find a paper.
  2. Copy its prompt into your AI agent, in an empty folder.
  3. See the figure and the paper's numbers next to your agent's. Then ask your own question.
- Below: "Can't find your paper? Request it. Papers with the most votes are built first."

## Search page
- Heading: "Papers"
- Filters: the five tag groups, nothing else: **Species**, **Tissue/cell** (a tissue or a cell line), **Data type**,
  **Disease**, **Collection**.
- Sort: "Most used" (default), "Newest", "Title".
- Result row, in this order:
  1. Paper title (the paper's own title, in the serif).
  2. First author et al., Journal, year. DOI.
  3. One plain sentence about the paper and its data. Example: "Cell-type composition of the primate basal
     ganglia across human, macaque and marmoset donors."
  4. Its tags.
  5. "Reproduces Figure 1B and Figure 2F."
  6. Counts, small, always shown as they are (also 0): "2,140 views by people, 610 by AI agents, 85 downloads".
     A pack published in the last 7 days also carries "New".
- Requested papers that have no pack yet appear after the available ones, marked "Requested, 12 votes" (or "In
  progress"), with "Vote" and the link to GitHub.
- No results: "No pack matches "<query>" yet. Request it: papers with the most votes are built first." with a
  "Request this paper" button that opens the request form with the DOI filled in.

## Paper page (top to bottom)
1. Title, authors, journal, year, DOI, PMID.
2. "What you can do with this pack" (two or three sentences, plain words).
3. The prompt: heading "Copy this into your AI agent", tabs for the agent (Claude Code, Codex, Antigravity, other),
   button "Copy prompt", then "Copied". Line under it: "Run it in an empty folder. Your agent downloads about
   560 MB from the original source." Everything runs on a laptop; if a pack has an analysis that needs a computing
   cluster, the agent explains that part and how to do it.
4. "Figures it reproduces" (each with what it shows and how close our numbers are to the paper's, in words).
5. "Questions this data can answer" and "Questions it can't answer".
6. "Data and terms": where the data stays, who provides it, the terms in one sentence, link to the full terms.
7. "Cite": the paper first, then the pack's archive DOI.
8. Counts and tags (sidebar on wide screens), "How we count" link.
9. "Something wrong? Report a problem" (opens the problem form with the DOI filled in).

## Requests page
- Heading: "Requested papers"
- Intro: "Ask for a paper you want to use with your agent. Each thumbs-up on GitHub is a vote, and papers with
  the most votes are built first. We check every request for open data and data terms before building."
- Button: "Request a paper"
- Status words: "Requested", "Checking the data", "Being built", "Being checked", "Available", "Not possible"
  (with the reason, e.g. "the data are controlled-access").

## How we count (linked from every count)
"Views by people are counted with a cookie-free counter that stores no personal data. Views by AI agents are
fetches of a paper's agent instructions, which every copied prompt makes; search-engine and AI-training crawlers
are not counted. Downloads are pack downloads plus the archive's downloads on Zenodo and Hugging Face. Numbers
are updated every night."

## Profiles
- GitHub organization: "Published papers your own AI agent can run. Free, open source, non-profit." Website
  runpapers.com.
- Hugging Face organization: "Data tables and outputs from RunPapers packs: published papers your own AI agent
  can run. Each dataset keeps the source data's terms."
- Zenodo community: "Archived versions of RunPapers packs. Each record is one version of one paper's pack, with
  the paper's numbers, figure recipes and agent instructions."

## Voice
- Write for a biologist who has never opened a terminal. Plain verbs, sentence case, the paper's own names.
- Say what something does, not how it is built ("your agent downloads the data", not "the CLI fetches the manifest").
- Never promise more than the data can do; say what it can't answer.
- No "revolutionary", "seamless", "unlock", "empower". No exclamation marks.
