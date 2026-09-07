# Collaboration — many people, different places, one agent session

*Design spec, 2026-09-06. Status: **approved design, implementation
pinned** (Fabio, 2026-09-06: "write spec but pin its implementation"). Nothing
in this document is built; the numbered phases at the end are the order to
build it in when the pin lifts.*

*Revised 2026-09-07 after an independent review of this document. Fifteen
findings, all addressed here — the largest being that `set_mode` and `cancel`
had no policy cell at all (an observer could have switched the session to a
permission mode in which the agent stops asking, deleting the approval gate
the whole of §5 rests on), that attaching a socket was never authorised, that
the nine existing REST routes sat outside the policy entirely, that the OIDC
flow specified no ID-token validation, and that `/join?token=` set an
identity cookie on a GET. Each is marked in place, in bold, with what was
wrong and why the new rule is the rule. The review found no reason to change
the shape of the design — the concepts, the three configurables and the
phase order survive; what was missing was the enforcement surface.*

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
trust_proxy = false                              # see below: OFF by default, and useless without the next key
trusted_proxies = []                             # e.g. ["127.0.0.1"] — X-Forwarded-* is believed ONLY from these
health_heartbeat_seconds = 600                   # log line cadence (L6)

[identity]
providers = ["invite"]            # any of: "invite", "oidc", "shared-link"
# invite: owner-issued personal tokens (default, no third party)
# oidc: sign in with an OpenID Connect provider (needs public_origin + a registered app)
# shared-link: one link for everyone; users are UNVERIFIED (observer at most)

[identity.oidc]                   # only when "oidc" is in providers
issuer = "https://accounts.google.com"
client_id = "..."
client_secret_file = "~/.acp-cockpit/oidc-secret"   # REQUIRED: confidential client, back-channel exchange only
allowed = ["someone@example.org"]  # e-mail allow-list; nobody else gets in

[driving]
mode = "baton"                    # "baton" | "owner-only" | "queue"
grace_seconds = 90                # baton returns to the owner after this long without a LIVE driver socket (L13)
queue_max = 5                     # queue mode: prompts waiting at most

[approvals]
who = "owner"                     # "owner" | "driver"
# The fail-safe timeout of today (reject / decline after an hour) stays in
# every mode; a policy can widen who may answer, never remove the fail-safe.
# A request whose `outside_boundary` is non-empty is OWNER-ONLY in every
# mode: that dialog is the only control over a shell command this client
# cannot confine, and it is not a policy knob.

[notes]
enabled = true
promote = "driver"                # who may turn a note into a prompt: "driver" | "owner"

[records]
shared_retention_days = 0         # 0 = keep for ever (as today); shared sessions only
consent_text = "This session is recorded: everything you write here is kept in the owner's session record."
```

**Malformed or unknown policy.** A `collab.toml` that does not parse, names
an unknown provider or mode, or sets a key this version does not know is a
**refusal to start**, naming the key — the same rule agent profiles already
follow (`profiles.py` raises; `branding.py`'s silent fallback is for a
cosmetic string, and this file is the safety surface). There is no CLI
override: a flag that could widen a security policy from a shell line would
defeat the file being the one place it is written. `acp-cockpit collab check`
prints the parsed policy and exits non-zero if it would be refused.

**`trust_proxy` is off by default, and `trusted_proxies` is what makes it
mean anything.** It maps to Tornado's `xheaders`, which takes `X-Real-Ip`
from the request itself; with no trusted-downstream list, any client that can
reach the server sets its own apparent address, and every per-IP rate limit
(§9) counts one hit per attacker-chosen value. With the list set, the header
is believed only when the immediate peer is on it. **A per-IP limit is not
the mechanism anyway** — behind a local tunnel every request's peer is
`127.0.0.1`, so an IP bucket throttles the owner and the attacker together.
§9 says what the limits actually key on.

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

**The queue is re-authorised at DEQUEUE, not only at submit.** A prompt sits
in the queue across turns, and in between its author can be revoked, the
session can be unshared, or their role can change. `CollabPolicy.may()` is
asked again the moment a queued prompt is about to be sent; a prompt that no
longer passes is discarded with `collab.change = "dropped"` naming the author
and the reason. The same event fires for every queued prompt when the session
is unshared, when the author is revoked, or when the session fails — a queue
that strands silently would lose named people's work with no record of it.
Beyond `queue_max` a submission is REFUSED at submit time (`policy-refused`,
reason `queue-full`), never accepted-then-dropped.

**Every command has a cell — including the ones that are not prompts.**
`set_mode`, `set_config_option` and `cancel` are commands `SessionWS`
dispatches, so they are policy-checked like the rest, and the table in §10
covers them:

| action | owner-only | baton | queue |
|---|---|---|---|
| `prompt` | owner | baton holder | any `driver` (submit; re-checked at dequeue) |
| `cancel` | owner | owner **or** the baton holder | owner **or** the author of the running turn |
| `set_config_option` | owner | owner or holder | owner or running author |
| `set_mode` | **owner, always** | **owner, always** | **owner, always** |
| `note` | any participant | any participant | any participant |
| `promote` | per `[notes].promote` | per `[notes].promote` | per `[notes].promote` |
| `attach` | per §4 sharing | per §4 sharing | per §4 sharing |

`set_mode` is owner-only in every mode because it is the switch that turns
the approval gate off: the shipped profile offers a permission mode in which
the agent stops asking at all, so a participant who could set it would delete
the whole of the approvals policy without ever answering a dialog. `cancel`
is not owner-only — aborting a turn is safe and sometimes urgent — but it is
not open to observers either.

**Approval modes.** `owner`: permission requests and elicitations are shown
to everyone but only the owner's answer is accepted; the dialog on other
screens is read-only and says who can answer. `driver`: the baton holder may
answer too. In queue mode `driver` means the author of the prompt whose turn
is running — **and if that author's socket is gone, the approver falls back
to the owner at once**, rather than leaving a dialog nobody may click until
the hour-long fail-safe fires. In `owner-only` mode there is no driver, so
`[notes].promote = "driver"` means the owner; the promote button appears on
no other screen.

**In every approvals mode, a request whose `outside_boundary` is non-empty
is answerable by the owner alone.** `docs/UI-PROTOCOL.md` already states that
such a request must be shown prominently because "shell execution is
agent-side and the user's answer is the only control". Widening *who may
prompt* is the point of this design; widening who may hand the owner's
credentials a path outside the project is not.

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
- **Therefore the ENGINE emits them, not the server.** `seq` is allocated
  only by `AcpSession._seq` inside `_emit`, and `_emit` does not touch the
  recorder — every recorded client action calls `recorder.append` separately
  and passes the returned line number as `raw_ref`. A note or presence event
  minted anywhere else has no way to get either. So `AcpSession` gains
  `note(text, by)` and `collab(change, by, **detail)`: each appends its
  record line and emits with that line as `raw_ref`, exactly like `prompt`.
  `server/collab.py` decides *whether*; the engine does the emitting. A
  second seq counter in the server would be the one failure `replay_truncated`
  exists to make impossible — `BufferedSink.attach` replays `if seq > after`,
  so a duplicated seq vanishes for every reconnecting View and a leapfrogged
  one pushes real events below the cursor.
- A `CollabPolicy` value object: the parsed policy file with `may(actor,
  action, session) -> allowed | reason`. Pure; the server asks it before
  every command **and before every attach**. Tested exhaustively; this is
  the safety surface.

**server/** (Tornado)
- `identity.py`: the provider registry. `invite`: personal tokens created
  by `acp-cockpit invite --name <n> --role <r>` (printed once, stored
  hashed, revocable by `acp-cockpit revoke <n>`, listed by `acp-cockpit
  participants`). **The join link is a page, not a side effect.**
  `GET <public_origin>/join?token=…` renders the consent page and sets
  NOTHING; the cookie is set by the `POST` that its button makes, carrying a
  form token bound to that page. A `Set-Cookie` on the GET would be
  login-CSRF: a cross-site top-level navigation carries no `Origin` header
  at all, `auth.origin_ok()` returns True when `Origin` is absent, and
  `SameSite` does not stop a top-level GET — so anyone holding any valid
  invite could pin a victim's browser to *their* identity, and every action
  the victim took would be recorded as the attacker's. That inverts the one
  guarantee Phase 1 exists for.
- `oidc`: authorization-code flow with PKCE **and a confidential-client
  back-channel exchange** — the code is redeemed server-to-server over TLS
  using `client_secret_file`; an ID token is never trusted from the browser.
  The ID token is validated in full before anyone is admitted: signature
  against the issuer's published keys, `iss` equal to the configured issuer,
  `aud` equal to our `client_id`, `exp`/`iat` in range, and `nonce` equal to
  the one this flow issued. Without the `aud` and `nonce` checks a genuine,
  correctly-signed token minted for *someone else's* application is accepted:
  an attacker runs any site with "Sign in with Google", gets an allow-listed
  person to sign in there once, and replays that token here. **Identity is
  `(iss, sub)`, not the e-mail**, and an address is only matched against
  `allowed` when the token says `email_verified` — an address can be
  self-asserted at a permissive issuer, and a reassigned one would otherwise
  inherit a departed participant's access and their attribution in the
  record. `tornado` is the only dependency, so the validating code is ours:
  §10 requires it be tested against tampered, mis-audienced, expired and
  replayed tokens, not only against a stub that says yes.
- `shared-link`: one token, cookie marks the user `unverified`. The owner's
  launch token stays what it is: the admin's credential.
- `collab.py`: the per-session collaboration state — participants attached,
  baton holder and its liveness, the prompt queue — and the policy checks in
  front of `SessionWS.on_message`. A refused command answers the sender with
  an `anomaly` (`policy-refused`, `{reason}`) **and is recorded**; there is
  one refusal shape, not two (an earlier draft also described a `not-driver`
  anomaly "shown to the sender only" — same thing, and `policy-refused` is
  the name). `category` is `policy-refused` so it joins the anomaly
  vocabulary the View already renders.
- `ws.py`: the socket knows who it is (from the cookie at upgrade), and
  **`open()` asks `CollabPolicy.may(actor, "attach", session)` before it
  attaches**. Without that, §4's "a session is private unless the owner
  shares it" has no mechanism anywhere: `open()` checks only the cookie and
  that the session exists, then replays up to `BufferedSink.CAP` events and
  subscribes to every future one — so an invited observer who guesses or is
  told a session id reads a private conversation, prompts, file contents and
  all, without ever sending a command for the gate to refuse. Presence
  (`joined`/`left`) is emitted on attach/detach.
- **Baton liveness is not "the socket exists".** `make_app` sets no
  `websocket_ping_interval`, so Tornado sends no pings and a driver whose
  laptop sleeps or drops off Wi-Fi never closes: no FIN arrives, `on_close`
  never runs, and `BufferedSink.emit` prunes a handler only when a write
  raises. On Windows the default TCP keepalive is two hours, so
  `grace_seconds = 90` would never fire and the session would sit with an
  absent driver — exactly the L13 incident this rule was written to end. The
  app sets `websocket_ping_interval` and `websocket_ping_timeout`, and the
  grace timer runs from the last **pong**, not from the last message.
- `app.py`: `GET /health`, `GET /api/me`, `GET
  /api/sessions/<sid>/participants`, `POST /api/sessions/<sid>/share`
  (owner), `POST …/baton` (`pass` | `take` | `release` — one vocabulary,
  used in §7 and the UI too), `POST …/notes/<n>/promote`.
- **The `Host`/`Origin` guard lives in two places and both must change.**
  `SessionWS` does not inherit `Guard`: it carries its own `prepare()` with
  the literal `("127.0.0.1", "localhost")` tuple, its own `check_origin` and
  its own cookie check. Widening only `app.py` gives a collaborator a page
  whose REST calls all answer and whose WebSocket 403s "bad host", and the
  View's reconnect backoff then retries for ever with nothing on screen.
  `auth.origin_ok()` also builds the expected origin as `"http://" + host`,
  so an `https` `public_origin` — the example value in §5 — can never match:
  the scheme comes from `public_origin` now. The cookie gains `Secure` when
  that origin is `https`, decided from the configured value and not from an
  `X-Forwarded-Proto` header the client may have set.
- `/health` is the ONE route outside the guard, and that is the point: it is
  what the external verifier calls. So it must answer with **no session data
  at all** (`{ok, version, heartbeat}` and nothing else), and §8 must not
  treat it as proof that the collaborator's path works — it shares no code
  with a guarded route. A green `/health` through a public hostname says the
  tunnel is up, not that anyone can join; the verifier says exactly that.
- `--bind` stays loopback by default: the tunnel or reverse proxy on the
  same machine is the public face, so the server never listens on a public
  interface itself. **`--port` must be given a fixed value when exposing**
  — it defaults to `0` (OS-assigned), and a fixed public hostname pointing
  at a port that moves on every restart is L3 with extra steps.

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
- Commands: `note {text}`, `promote {note_seq}`, `baton {op: pass | take |
  release, to?}`, and the existing ones, now policy-checked.
- REST: **every route, not only the new ones.** All nine existing handlers
  subclass `BaseHandler(Guard, …)`, whose whole authorization is "the cookie
  verifies" — which was the owner's token and will become any participant's.
  Left as they are, an observer could `GET /api/sessions` (every session on
  the server, with its `cwd`, its agent-written title and the id needed for
  the attach above), `POST /api/sessions` (spawn a fresh adapter under the
  owner's credentials in any directory, unshared, with no baton and no
  approvals policy — a complete escape from this design by not using a
  shared session), `DELETE /api/sessions/<sid>` (kill the owner's session
  mid-turn; the shipped View already has that button), `GET /api/dirs`
  (walk the owner's filesystem by name), or `POST …/archive` (write the
  conversation anywhere the server can write, and spawn the archiver).
  So: session creation, deletion, `/api/dirs`, `/api/settings` and archiving
  are **owner-only**; `GET /api/sessions` returns only sessions the actor
  may attach to; `/api/profiles` and `/api/drift` are readable by any
  participant. §9's "a policy engine in front of every command" is true of
  REST or it is not true.
- `GET /api/sessions` gains `shared`, `participants` (count) and `driver`.
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
  `health_heartbeat_seconds` (L6). **It needs somewhere durable to go**: the
  package imports `logging` nowhere and has four `print()` calls in total, so
  a heartbeat on stdout exists only for as long as someone is watching the
  console — which is not what L6 was about. Phase 1 gives the server a
  logging destination (a rotating file beside the records) and the heartbeat
  is its first user.
- **`expose.py` and `verify_public.py` cannot live only in `scripts/`.**
  AGENTS.md: "the wheel is the product", and `scripts/` is not shipped in
  it, so an installed cockpit would have neither. They belong in the package
  with console entry points (as `acp-cockpit expose` / `acp-cockpit verify`),
  with `scripts/` keeping at most the scheduler wrapper. Same for the
  `invite`/`revoke`/`participants`/`collab check` subcommands: `__main__.py`
  today parses flags only and has no subcommand dispatch, so Phase 1 adds
  one.
- `KEEP/ports.yaml` gets the cockpit's port reserved when it is exposed.

## 9. Security model (additions to the one in README)

- Threats considered: a leaked join link (personal tokens are revocable and
  named; a shared link is observer-only and unverified by construction); a
  participant making the agent act (policy engine in front of every
  command; approvals owner-only by default; notes never reach the agent);
  a forged identity in text (L1: identity comes from the cookie the
  provider set, names in text mean nothing); cross-origin requests from
  the public hostname (Origin must equal `public_origin` exactly — **and an
  ABSENT `Origin` is not a pass on any state-changing route**, which is why
  `/join` sets no cookie on a GET; `auth.origin_ok()` returns True for a
  missing header today, which is right for a same-origin `fetch` and wrong
  for a cross-site navigation); cookies `Secure`, `HttpOnly`, and
  `SameSite=Lax` **only for the short-lived OIDC state cookie**, which is
  what the redirect needs — the identity cookie itself stays
  `SameSite=Strict` on every origin, because nothing navigates into the app
  carrying it; replay of a revoked token (tokens hashed at rest, revocation
  checked per request).
- **Revocation and unsharing sweep live sockets.** "Checked per request" and
  "`4403 revoked` on the next message" never reach a participant who is only
  reading: their handler stays in `BufferedSink._handlers`, which is pruned
  only by `on_close`/`detach` or a failed write, so `emit` keeps streaming
  prompts, tool calls, file contents and dialogs for as long as their tab is
  open. `acp-cockpit revoke` and turning `share` off both close that
  person's sockets at once (`4403 revoked` / `4403 unshared`) — the sweep §4
  already promises for unsharing, owed equally to revocation. Anything less
  makes "revocable" a claim about writes only.
- Rate limits on `/join`, `/login` and `note`. **Keyed on the credential,
  not the address**: `note` and the other authenticated routes bucket per
  participant id; `/join` and `/login` bucket per presented token — so
  trying a different token each time gains nothing — plus a global ceiling
  per route, because an attack's first request has no identity yet. Per-IP
  is not available behind a local tunnel (every peer is `127.0.0.1`) and is
  forgeable when `trust_proxy` is on without `trusted_proxies` (§5).
- Records: a shared session's record holds other people's words. **The
  retention this promises does not exist yet and Phase 4 has to build it**:
  today's `prune()` is directory-wide, keyed on file mtime, runs once at
  start-up, and defaults to `0 = keep for ever`. Per-session retention needs
  the record to know it was shared and needs a sweep that runs while the
  server is up — otherwise a server that stays up for a month never deletes
  anything, and a `--records-keep-days` set for the owner's own sessions
  silently applies to other people's too. The consent text is shown on the
  join page; `shared_retention_days` applies
  to those records only; the archive panel names the participants in the
  transcript header.
- Not solved here, said plainly: a driver can still ask the agent to do
  anything the owner's agent may do in the project directory, and shell
  commands are agent-side (the existing caveat). Collaboration widens who
  can ask; the answer to *what may happen* is still the owner's approval.

## 10. Testing

- `CollabPolicy`: a test per cell of the §5 table — every (mode, role,
  action), `attach` and `set_mode` included, since a table with a missing
  cell is how the `set_mode` hole survived being written down. **The table
  is a module-level list the tests loop over, NOT `@pytest.mark.parametrize`:
  `tests/test_docs_guard.py` fails any test file that uses it, because the
  README's check count is a static count of `def test_` and parametrize
  would make it wrong.** The fail-safe timeout is asserted to survive every
  policy, and a request with a non-empty `outside_boundary` is asserted
  owner-only in every approvals mode.
- Identity: invite create/revoke/list round-trips; hashed at rest; a revoked
  cookie is `4403 revoked` on the next message **and a revoked reader who
  sends nothing is disconnected too**; a GET to `/join` sets no cookie; a
  cross-site POST without an `Origin` is refused. OIDC not merely "against a
  stub issuer" but against tampered, wrong-`aud`, expired, wrong-`nonce` and
  replayed tokens, and one whose `email_verified` is false — a stub that
  only ever says yes would pass the naive implementation this design exists
  to rule out. Shared-link users are `unverified` and denied `prompt`.
- Engine: `by` on every client-originated record line and event; notes
  never produce an outgoing frame (assert `proc.sent` unchanged).
- e2e with two browser contexts on one session: presence chips on both;
  the driver's prompt appears on both with the driver's name; the observer's
  prompt is refused and the refusal is visible only to them; a note appears
  on both and reaches no adapter; baton pass and grace-timeout hand-back;
  approval dialog read-only on the observer.
- Encoding: a note and a prompt with accented and non-Latin text round-trip
  through the record, the replay and the Markdown transcript (L10). **That
  last leg needs `core/transcript.py` to change**, and no section names it:
  `render_markdown` keeps only prompts, agent text, thinking and tool-call
  titles, so it drops every note, and it labels every prompt `### You` —
  which in a shared session is a lie about who spoke. It gains the notes
  lane and per-participant headings, and the archive header names the
  participants (§9).
- Verifier: the tri-state verdict with stubbed DoH and HTTP; two strikes;
  the `None` ceiling; the log filter matches only the lines it should.
- The docs guard extends to the collaborator-facing strings table and the
  policy file's documented keys.

## 11. Phases (implementation pinned; this is the order)

- **Phase 0 — today, no code, and only half of it works.** An **SSH port
  forward** to the owner's machine plus the existing token URL gives a
  trusted group a live shared view now, because it lands every browser back
  on loopback. **A tailnet address does not**: the server binds `127.0.0.1`
  with no `--bind` flag, and both the REST guard and `SessionWS`'s own
  refuse a `Host` that is not loopback — behaviour pinned by
  `tests/test_security.py`. Everyone is anonymous and anyone can act.
  Documented as such **in the manual**, with the warning — which the commit
  that wrote this spec did not do, and `docs/DESIGN.md` and `README.md` must
  agree (they were reconciled on 2026-09-07).
- **Phase 1 — identity and attribution.** Invite tokens, `by` on every
  action and event, participants strip, `/health` + heartbeat + a logging
  destination, `public_origin` and the proxy trust, the CLI subcommand
  dispatch, and the policy gate on **attach** and on every REST route.
  Shared sessions are owner-driven, owner-approved (the defaults). This
  phase alone makes the record honest about who did what.
  **The join page's consent text ships in Phase 1, not Phase 3.** This is
  the first phase in which other people's words enter the owner's record,
  and consent that arrives two releases later is not consent. The
  plain-language *design* of the page can improve in Phase 3; the sentence
  saying "this is recorded" cannot wait. `shared_retention_days` still lands
  in Phase 4, so Phase 1's page says plainly that records are kept
  indefinitely for now.
- **Phase 2 — driving and approvals policy.** Baton mode with the grace
  rule, owner-only mode, queue mode; approvals `owner` | `driver`; read-only
  dialogs for non-approvers.
- **Phase 3 — the notes lane and promotion.** The sixth lane, the second
  composer, promote-to-prompt, the plain-language join page, the strings
  table.
- **Phase 4 — OIDC, shared links and operations.** The OIDC provider with
  the full token validation of §6, **the `shared-link` provider and the
  `unverified` role** (fully specified in §4 and §5 and built by no earlier
  phase — until this ships, `providers = ["shared-link"]` must be refused at
  load rather than silently doing nothing), `expose` and `verify` as
  packaged subcommands driven from the scheduler, the admin page for the
  policy file, and per-session retention for shared records.

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
- Implementation is pinned; **the SSH-forward half of** Phase 0 is available
  at once.

Added by the 2026-09-07 review, so they are not re-litigated either:

- `set_mode` is owner-only in every driving mode — it is the switch that
  turns the approval gate off, not a driving preference.
- A permission request with a non-empty `outside_boundary` is owner-only in
  every approvals mode.
- Attaching is an authorised action, not a consequence of knowing a session
  id; and every REST route is policy-checked, not only the new ones.
- `note` and `collab` are emitted by the ENGINE, because `seq` and `raw_ref`
  exist nowhere else.
- OIDC is a confidential client with full ID-token validation, and identity
  is `(iss, sub)` with `email_verified` required — never a bare e-mail claim.
- `/join` sets no cookie on a GET.
- Revocation disconnects, it does not only refuse.
- `trust_proxy` defaults to off, and rate limits key on the credential.
