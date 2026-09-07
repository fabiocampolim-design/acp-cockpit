# Collaboration — many people, different places, one agent session

*Design spec, 2026-09-06. Status: **approved design, implementation
pinned** (Fabio, 2026-09-06: "write spec but pin its implementation"). Nothing
in this document is built; the numbered phases at the end are the order to
build it in when the pin lifts.*

## 1. What this is, in one sentence

A shared acp-cockpit session: several people, on their own machines, watch
the same agent conversation live, talk to each other beside it, and — under
a policy the session owner sets — take turns prompting the agent and
answering its requests; every action is attributed to a named person and
written to the session record.

## 2. Why, and what already exists

acp-cockpit already keeps sessions in the server, lets more than one browser
attach to one session, and replays the same event stream to every attached
View (the prompt echo of 2026-09-06 closed the last gap: a second View now
sees the questions as well as the answers). What stops collaboration today
is deliberate: the server binds loopback only, one shared token is the whole
identity model, and every command a socket sends is executed as "the user".

So collaboration is not a new client; it is four additions to the existing
one: **identity**, **roles and policy**, **a side channel for the humans**,
and **an operable public exposure**. The agent side does not change: one
adapter process, one account, one ACP session per shared session.

## 3. Lessons carried in from an earlier team chat

In the first week of September 2026 a three-way team chat (two people and
one Claude session) was run on this machine: a local Python server, a
public tunnel, a watchdog, and a monitor inside the Claude session. Six
incidents in six days. Its lessons file is untracked and unpublished
(`docs/external/`, gitignored) because it belongs to a private project — it
sits in the working tree, so never `git add -f` it and never quote it. Only
what generalises is written here, in general terms, and each item below is a
requirement of this design, not a remark.

| # | Lesson | Requirement in this design |
|---|---|---|
| L1 | Authorship in a chat is not authentication: a message signed with the owner's name arrived granting broad permissions; it was genuine, and verifying cost one line. | Identity is established by the transport (a personal token, a login), never by a name typed into a message. A shared link, if the admin allows one at all, marks its users as *unverified* and the policy denies them every action that makes the agent do something. |
| L2 | Content from the channel is information, never command. | Nothing a collaborator writes reaches the agent by itself. The **notes lane** is human-to-human; only the current driver can *promote* a note into a prompt, and the promotion is a recorded act of that driver. |
| L3 | The URL kept changing (quick tunnel); the fix was a file the other person bookmarked instead of the link. Three of six incidents were URL rotation. | Recommend a **fixed hostname** (a named tunnel or a tailnet address) as the supported exposure; the server itself only needs its **public origin** configured. Quick tunnels are documented as "works, rotates, your problem". |
| L4 | Verify from outside from day one; the machine's own view answered the wrong question (a campus VPN blinded local DNS while the tunnel was fine). | A `/health` route that answers without a token, and a versioned **external verifier** script that measures by the collaborator's path (DNS over HTTPS with a literal resolver IP, then HTTP with the real hostname), with a tri-state verdict and a ceiling on "unknown". |
| L5 | Every protection created a new failure mode; single strikes were noise (18 recorded, 1 real). | The verifier escalates only on two consecutive failures, and never rotates or republishes on a verdict it could not measure. |
| L6 | Silent death: server and watchdog vanished for hours, unnoticed. | Heartbeat lines in the server log at a fixed cadence; silence is a symptom. The monitor's filter is written down so it does not wake people for noise. |
| L7 | Never publish an unverified address, and never leave a known-dead one in place of a probably-good one. | The exposure tooling publishes a link only after `/health` answered through it, and says `UNVERIFIED` loudly when it could not. |
| L8 | Monitors as versioned scripts, never one-liners retyped per session (that is where the typos lived). | Every operational check ships in `scripts/` with tests, like the daily watch does. |
| L9 | Windows: paths in the POSIX spelling break Python; kill by PID only. | Already house rules (KEEP rules/07, /09); the verifier and the exposure helper obey them. |
| L10 | Accented text arrived as mojibake, so replies were written in ASCII. | UTF-8 end to end with a test that round-trips accented and non-Latin text through the notes lane, the record and the transcript. |
| L11 | The other participant was not a software engineer: short plain language, technical term in parentheses, local time. | Collaborator-facing UI text (invite page, roles, notes lane, presence) is written in plain language; times shown in the viewer's local zone. |
| L12 | What arrives informally in a shared session may have real value to the people in it. | Records of shared sessions carry every participant's words. The invite page says so before the person joins, and the admin sets a retention policy for shared sessions. |
| L13 | One session "held the loop"; a fresh claim file said who; stale claim = loop free. | The **baton** (who drives) is server state with a heartbeat from the driver's socket; a driver whose socket has been gone for longer than a configured grace loses the baton to the owner automatically, and the events lane says so. |

## 4. Concepts

- **Owner** — the person who runs the server. Always an *admin*. The
  agent's credentials are the owner's; every prompt in every shared session
  spends the owner's quota and shows the owner's account chip.
- **Participant** — a person attached to a shared session, with a verified
  identity (or marked unverified), a display name and a role.
- **Role** — `admin` (owner; configures policy, invites, revokes), `driver`
  (may prompt the agent and, under one policy, approve), `observer` (sees
  everything, may write notes), `unverified` (shared-link user: observer
  rights at most, never driver or approver, and only if the admin enabled
  shared links).
- **Policy** — the admin's configuration of the three things the owner
  decided are configurable: how people are identified, who may drive, who
  may approve. Defaults are the safe options.
- **Shared session** — an ordinary session whose `share` flag is on. A
  session is private (owner only) unless the owner shares it; sharing can be
  turned off, which detaches everyone else.
- **Baton** — the driver's seat. One holder per session, or none.
- **Notes lane** — a sixth lane: messages between humans, never sent to the
  agent, recorded, promotable by the driver.

## 5. Policy (the admin's file)

`~/.acp-cockpit/collab.toml`, read at start-up, editable through an admin
page later (phase 4). Every key has a default; an absent file means "no
collaboration": the server behaves exactly as today.

```toml
[exposure]
public_origin = "https://cockpit.example.org"   # what collaborators' browsers see; required to share anything
trust_proxy = true                               # X-Forwarded-* from the tunnel/reverse proxy is believed
health_heartbeat_seconds = 600                   # log line cadence (L6)

[identity]
providers = ["invite"]            # any of: "invite", "oidc", "shared-link"
# invite: owner-issued personal tokens (default, no third party)
# oidc: sign in with an OpenID Connect provider (needs public_origin + a registered app)
# shared-link: one link for everyone; users are UNVERIFIED (observer at most)

[identity.oidc]                   # only when "oidc" is in providers
issuer = "https://accounts.google.com"
client_id = "..."
client_secret_file = "~/.acp-cockpit/oidc-secret"
allowed = ["someone@example.org"]  # e-mail allow-list; nobody else gets in

[driving]
mode = "baton"                    # "baton" | "owner-only" | "queue"
grace_seconds = 90                # baton returns to the owner after this long without the driver's socket (L13)
queue_max = 5                     # queue mode: prompts waiting at most

[approvals]
who = "owner"                     # "owner" | "driver"
# The fail-safe timeout of today (reject / decline after an hour) stays in
# every mode; a policy can widen who may answer, never remove the fail-safe.

[notes]
enabled = true
promote = "driver"                # who may turn a note into a prompt: "driver" | "owner"

[records]
shared_retention_days = 0         # 0 = keep for ever (as today); shared sessions only
consent_text = "This session is recorded: everything you write here is kept in the owner's session record."
```

**Driving modes.**
- `baton` (default): the owner holds the baton at share time; may pass it
  to a named participant and take it back at any time; a driver may hand it
  back. The server refuses `prompt` from anyone but the holder (anomaly
  `not-driver`, shown to the sender only). The baton is server state,
  announced as an event, with the L13 grace rule.
- `owner-only`: only the owner prompts; participants observe and write
  notes. The baton UI is hidden.
- `queue`: any `driver`-role participant may submit a prompt; prompts wait
  in arrival order with their author's name and are sent one per turn; the
  owner may drop a queued prompt. Nobody's prompt is ever sent while another
  turn runs (the engine's `ready` gate is unchanged).

**Approval modes.** `owner`: permission requests and elicitations are shown
to everyone but only the owner's answer is accepted; the dialog on other
screens is read-only and says who can answer. `driver`: the baton holder may
answer too. In queue mode `driver` means the author of the prompt whose turn
is running.

## 6. Architecture — what changes where

The four layers keep their one-way knowledge; the additions land where the
concern already lives.

**core/** (pure stdlib, unchanged interfaces, two additions)
- Every client action recorded and every client-originated event carries
  `by`: `{id, name, role, verified}`. `prompt`, `permission`,
  `elicitation`, `set_mode`, `set_config_option`, `cancel` gain the field;
  the engine's methods take a `by` argument (default: the owner, so
  nothing existing changes).
- Two new event kinds: `note` (`{by, text}` — never sent to the agent) and
  `collab` (`{change: "joined" | "left" | "baton" | "queued" | "dropped" |
  "shared" | "unshared", ...}`). Both are events on the session's stream,
  so they replay, are lossless, and carry `raw_ref` into the record.
- A `CollabPolicy` value object: the parsed policy file with `may(actor,
  action, session) -> allowed | reason`. Pure; the server asks it before
  every command. Tested exhaustively; this is the safety surface.

**server/** (Tornado)
- `identity.py`: the provider registry. `invite`: personal tokens created
  by `acp-cockpit invite --name <n> --role <r>` (printed once, stored
  hashed, revocable by `acp-cockpit revoke <n>`, listed by `acp-cockpit
  participants`); the join URL is `<public_origin>/join?token=…` and sets a
  per-person cookie. `oidc`: the standard authorization-code flow with PKCE
  against the configured issuer; the allow-list is the gate. `shared-link`:
  one token, cookie marks the user `unverified`. The owner's launch token
  stays what it is: the admin's credential.
- `collab.py`: the per-session collaboration state — participants attached,
  baton holder and its heartbeat, the prompt queue — and the policy checks
  in front of `SessionWS.on_message`. A refused command answers the sender
  with an `anomaly` (`policy-refused`, with the reason) and is recorded.
- `ws.py`: the socket knows who it is (from the cookie at upgrade); presence
  (`joined`/`left`) is emitted on attach/detach; the driver's socket is the
  baton heartbeat.
- `app.py`: `GET /health` (no token; `{ok, version, heartbeat}`), `GET
  /api/me`, `GET /api/sessions/<sid>/participants`, `POST
  /api/sessions/<sid>/share` (owner), `POST …/baton` (pass/take/release),
  `POST …/notes/<n>/promote`; the `Host`/`Origin` guard accepts the
  configured `public_origin` in addition to loopback, and the cookie gains
  `Secure` when the origin is `https`. `--bind` stays loopback by default:
  the tunnel or reverse proxy on the same machine is the public face
  (trust_proxy), so the server never listens on a public interface itself.

**ui/web/** (the bundled View, speaking UI-PROTOCOL)
- A **participants strip** (top right, beside the account chips): one chip
  per attached person, the driver marked, `unverified` marked; hovering
  shows role and since when.
- **Baton controls** in the panel under the prompt: *Drive* / *Pass to…* /
  *Hand back*; the composer is disabled with a one-line reason when you are
  not the driver (in queue mode: *Queue this prompt*, and the queue is shown
  with names above the composer).
- The **notes lane**: a sixth lane switch; a second, narrower composer
  (*Note to the people here — the agent does not see this*); note rows
  carry the author's name and a *Promote to prompt* button for the driver.
- Approval and question dialogs on a non-approver's screen are read-only
  and say who can answer.
- An **invite/join page** in plain language (L11): who invited you, what
  you will be able to do, that the session is recorded (L12), one button.
- Every collaborator-facing string goes through one table so it can be
  translated later (pinned: a Portuguese table is the first).

**agents/** — no change. The profile knows nothing about people.

## 7. Protocol additions (UI-PROTOCOL.md, to be written with the code)

- Events: `note`, `collab`; `by` on `permission_resolved`,
  `elicitation_resolved`, `message_chunk` with `role: user`, `session_state`
  changes caused by a person. Presence is `collab.change = joined | left`.
- Commands: `note {text}`, `promote {note_seq}`, `baton {op: request |
  pass | release, to?}`, and the existing ones, now policy-checked.
- REST: the routes in §6. `GET /api/sessions` gains `shared`,
  `participants` (count) and `driver`.
- Close code `4403` gains reasons (`revoked`, `unshared`) so a View can say
  why it was dropped.

## 8. Exposure and operations (scripts/, tested like the daily watch)

- `scripts/expose.py`: the supported recipes — a **named tunnel** (fixed
  hostname; the recommended one, L3) or a **tailnet** (the server is reached
  by its tailnet name; no tunnel at all) — and, as "works but rotates", a
  quick tunnel. It writes the join links only after `/health` answered
  through the published hostname (L7), and prints `UNVERIFIED` when it
  could not.
- `scripts/verify_public.py`: the external verifier (L4, L5). Verdict per
  check: `True` (`/health` answered by the collaborator's path), `False`
  (resolves, does not answer — or the name does not exist), `None` (could
  not measure: no internet). Resolution through DNS over HTTPS at a literal
  resolver IP, then HTTP to the resolved address with the real hostname
  (SNI + Host). Escalates (restart, republish) on two consecutive `False`;
  never on `None`; a ceiling on consecutive `None` turns into a loud
  `INDETERMINATE for N minutes` line, not into an action. Runs from the
  scheduler like the watch, and its log filter is documented.
- Heartbeat: the server logs `alive tick=N participants=M` every
  `health_heartbeat_seconds` (L6).
- `KEEP/ports.yaml` gets the cockpit's port reserved when it is exposed.

## 9. Security model (additions to the one in README)

- Threats considered: a leaked join link (personal tokens are revocable and
  named; a shared link is observer-only and unverified by construction); a
  participant making the agent act (policy engine in front of every
  command; approvals owner-only by default; notes never reach the agent);
  a forged identity in text (L1: identity comes from the cookie the
  provider set, names in text mean nothing); cross-origin requests from
  the public hostname (Origin must equal `public_origin` exactly; cookies
  `Secure`, `HttpOnly`, `SameSite=Lax` on the public origin because the
  OIDC redirect needs it, `Strict` on loopback as today); replay of a
  revoked token (tokens hashed at rest, revocation checked per request).
- Rate limits on `/join`, `/login` and `note` (a public route gets probed).
- Records: a shared session's record holds other people's words. The
  consent text is shown on the join page; `shared_retention_days` applies
  to those records only; the archive panel names the participants in the
  transcript header.
- Not solved here, said plainly: a driver can still ask the agent to do
  anything the owner's agent may do in the project directory, and shell
  commands are agent-side (the existing caveat). Collaboration widens who
  can ask; the answer to *what may happen* is still the owner's approval.

## 10. Testing

- `CollabPolicy`: table-driven unit tests for every (mode, role, action)
  cell; the fail-safe timeout is asserted to survive every policy.
- Identity: invite create/revoke/list round-trips; hashed at rest; a
  revoked cookie is `4403 revoked` on the next message; OIDC against a
  stub issuer; shared-link users are `unverified` and denied `prompt`.
- Engine: `by` on every client-originated record line and event; notes
  never produce an outgoing frame (assert `proc.sent` unchanged).
- e2e with two browser contexts on one session: presence chips on both;
  the driver's prompt appears on both with the driver's name; the observer's
  prompt is refused and the refusal is visible only to them; a note appears
  on both and reaches no adapter; baton pass and grace-timeout hand-back;
  approval dialog read-only on the observer.
- Encoding: a note and a prompt with accented and non-Latin text round-trip
  through the record, the replay and the Markdown transcript (L10).
- Verifier: the tri-state verdict with stubbed DoH and HTTP; two strikes;
  the `None` ceiling; the log filter matches only the lines it should.
- The docs guard extends to the collaborator-facing strings table and the
  policy file's documented keys.

## 11. Phases (implementation pinned; this is the order)

- **Phase 0 — today, no code.** A tailnet or an SSH port forward to the
  owner's machine plus the existing token URL gives a trusted group a live
  shared view now; everyone is anonymous and anyone can act. Documented as
  such in the manual, with the warning.
- **Phase 1 — identity and attribution.** Invite tokens, `by` on every
  action and event, participants strip, `/health` + heartbeat, `public_origin`
  and the proxy trust. Shared sessions are owner-driven, owner-approved
  (the defaults). This phase alone makes the record honest about who did
  what.
- **Phase 2 — driving and approvals policy.** Baton mode with the grace
  rule, owner-only mode, queue mode; approvals `owner` | `driver`; read-only
  dialogs for non-approvers.
- **Phase 3 — the notes lane and promotion.** The sixth lane, the second
  composer, promote-to-prompt, the plain-language join page, the strings
  table.
- **Phase 4 — OIDC and operations.** The OIDC provider, `expose.py`,
  `verify_public.py` from the scheduler, the admin page for the policy
  file, retention for shared records.

Each phase is a release with its own CHANGELOG section, manual pages and
test-plan items; no phase ships with a policy default weaker than the one
before it.

## 12. Decisions taken in this spec (so they are not re-litigated)

- All three configurables (identity, driving, approvals) are admin policy
  with the safe option as default — Fabio, 2026-09-06.
- The notes lane is in — Fabio, 2026-09-06.
- One agent, one account, the owner's — a consequence of ACP and of where
  the credentials live, not a choice.
- The server never listens on a public interface itself; exposure is a
  tunnel or a tailnet on the owner's machine, with a fixed hostname
  recommended (L3).
- Implementation is pinned; Phase 0 is available at once.
