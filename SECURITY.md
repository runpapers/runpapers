# Security

Packs contain code (recipes) that runs on scientists' computers, so we treat anything that could make a pack or the
`rp` tool unsafe as a security problem: a recipe that does more than read its data and write `out/`, instructions in
a pack that try to steer an agent outside its task (prompt injection), downloads from anywhere other than a paper's
original repository, or leaked credentials.

Please report it privately: on GitHub, open the repository's **Security** tab and choose **Report a vulnerability**.
Do not open a public issue. We will reply within a few days and credit you if you wish.

Every pack is linted for prompt injection, hidden characters, piped shell installs and credentials before review,
and every badge is bound to the exact content that was checked.
