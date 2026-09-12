# FUMBBL automated-play route: public-source check

Checked 2026-09-04. Scope was public pages published on FUMBBL-controlled
domains. No account was used and nobody was contacted.

## Finding

I could not establish a currently documented, officially supported route for
an automated coach to play matches on FUMBBL. The public official pages found
do not describe a bot account, automation permission, headless match protocol,
AI competition, sandbox server, or automated test league. This is absence of
public documentation, not proof that FUMBBL prohibits all bots or that staff
could not authorize a private route.

The public custom-ruleset editor documents a `Test Mode` option and a selectable
`Rules Version`, but does not say that Test Mode admits automated clients or
computer-controlled coaches. It also says cross-league matches require the same
ruleset. Those are explicit platform capabilities; treating them as a bot API
would be inference unsupported by the page. [Official custom-ruleset page](https://fumbbl.com/p/ruleset?id=2)

The only official API-like surface found in this search was the FUMBBL-hosted
League Stats application. It documents two read-oriented statistics calls,
`tournamentPerformances` and `teamPerformances`; it does not document match
creation, client control, action submission, or a bot competition endpoint.
[Official FUMBBL League Stats page](https://leaguestats.fumbbl.com/)

An old official staff guide says, “Your account is personal. You may not share
it with others.” It also binds accepted matches to the designated client and
warns that conflicting client versions are rejected. The document is dated
2007 and discusses JavaBBowl, so it is historical evidence about account and
client-integrity principles, not a reliable current bot policy or current
client specification. [Official historical administrator guide](https://fumbbl.com/files/staff/AdminGuide.pdf)

## BB2025/version-adapter consequence

No official page found in this search explicitly documents BB2025 support, a
BB2025 action protocol, or an edition adapter. The current public ruleset editor
does establish that `Rules Version` is an explicit ruleset property, and that
cross-league compatibility depends on the same ruleset. Therefore a later
integration must discover and bind the live ruleset/version identity rather
than infer the edition from a league name or calendar year. This compatibility
requirement is an inference from the documented fields; it is not an official
statement that a particular BB2025 adapter is missing.

One official 2026 tournament page still explicitly labels its competition
“BB2020 ruleset w/ Slann.” That demonstrates why “a 2026 FUMBBL competition”
cannot be treated as evidence of BB2025 semantics. It does not establish the
edition used by other divisions or by FUMBBL globally. [Official tournament group page](https://fumbbl.com/p/group?group=9298&op=view&p=members)

## Practical status

Automated live play remains unverified. Public documentation supports neither
implementing an account-driving adapter nor declaring such use forbidden.
Local engine play, offline evaluation, and replay-derived research remain the
only routes established by the present evidence. Any future live route needs a
current first-party specification or explicit FUMBBL authorization before an
account or match is operated.
