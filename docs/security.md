# Security

Orpheus is built to run on a private network you control. This page states plainly
what protection exists, what does not, and what that means for how you should deploy
it. To report a vulnerability, see the [security policy](project-security-policy.md).

**The one-sentence version:** do not expose Orpheus directly to the public
internet. It is a LAN appliance; if you want to share observations publicly, use the
read-only mirror and the public projection rather than opening the dashboard.

## What is listening

| Service | Port | Bound to | Notes |
|---|---|---|---|
| UI backend (API + built frontend) | 8082 | all interfaces | The dashboard. Requires login. |
| Message broker (NATS) | 4222 | loopback by default | Agents connect here. Opening it to the LAN requires credentials — the installer refuses a non-loopback listener without an auth file. |
| Broker monitoring | 8222 | loopback | Health/stats endpoint. |
| Frontend dev server | 5173 | all interfaces | Development only; not present in a deployed install. Vite is configured with `server.host: true`, so it is reachable from the LAN while you are running it. |
| nginx (optional) | 80 | all interfaces | If installed, proxies to the UI backend. |

Nothing dials out to the internet except model downloads you trigger. On your own
network it does connect out, and you should know where: to each camera over HTTP and
RTSP — the RTSP URL carries the camera password in the clear — to a weather station if
you configure one, and, if you run the read-only mirror, to the read host over rsync
and ssh.

## Accounts and sessions

The UI ships with two seeded accounts: an **admin** and a read-only **guest**. Login
issues a JWT.

**Change the defaults before anyone else can reach the box.** The seeded passwords
are well-known (they are in this repository), and they are the first thing anyone
probing your network will try:

```bash
sudo tee -a /opt/orpheus/config/.env >/dev/null <<'EOF'
ORPHEUS_UI_ADMIN_PASSWORD=<a long random password>
ORPHEUS_UI_GUEST_PASSWORD=<another one>
ORPHEUS_UI_JWT_SECRET=<32+ random bytes>
EOF
```

`/opt/orpheus/config/.env` is the file the UI unit reads
(`EnvironmentFile=-/opt/orpheus/config/.env`). Exporting these in your own shell does
not reach a systemd service. Set them **before the first start**, so the seeded users
are created with your values.

**If the UI already started with the defaults, adding them now changes nothing.**
Seeding is guarded on an empty user table, so it never runs twice. Rotate an
already-seeded install one of two ways:

- Sign in and `PATCH /users/me` with a new password — keeps your data and any accounts
  you created.
- Or stop the UI, remove the accounts database (the backend logs its path at startup;
  `/data/orpheus/users.db` on a station), and restart with the variables above set,
  which re-seeds both accounts from them — and destroys any hand-made accounts along
  with them.

There is no password field in the dashboard; the Settings page's Security card is a
placeholder. See [the dashboard guide](ORPHEUS_UI.md#default-users) for the seeded
accounts and where that database lives.

- **If `ORPHEUS_UI_JWT_SECRET` is unset**, the backend generates a random secret at
  startup and logs a warning. Sessions then survive only until the process restarts.
  Set it explicitly on anything you actually use.

### What each account can do

| | Admin | Guest |
|---|---|---|
| Read every dashboard page | yes | yes |
| Play back recorded clips | yes | yes |
| Change stored data (equivalence decisions, playback requests) | yes | no |
| Create accounts | yes | no |
| Read the runtime configuration endpoint | yes | no |

Account creation, role assignment, and the debug configuration endpoint are
restricted to an authenticated admin, and no account can change its own role.

Two caveats worth being blunt about. First, the guest account is *read-only within
the dashboard*, not a security boundary you should lean on with a hostile party — it
still sees everything the dashboard shows, including recordings of your property.
Second, the login page offers one-click guest sign-in, which means that while
`ui.guest_quick_login` is on, viewing the dashboard is open to anyone who can reach
the port. That is the right trade for a station on your own network and the wrong one
for anything reachable from the internet: set `ui.guest_quick_login: false` and the
button disappears along with the endpoint behind it. The page never displays a
password; while a seeded account still accepts a password this project ships it shows
a prompt to change it. That check runs once when the UI starts and the page reads it
once on load, so after you rotate with `PATCH /users/me` the prompt stays up until you
restart `orpheus-ui` and reload the page — it is stale, not wrong. The check
reads the stored password hashes, not the environment — so it tells you what really
logs in, not what you meant to configure.

## What is not hardened

Being explicit, because "it has a login page" invites wrong assumptions:

- **No TLS by default.** The UI speaks HTTP. Credentials and data cross your network
  in the clear unless you put a reverse proxy with a certificate in front.
- **Sign-in brute-force protection is always on.** Five *failed* attempts per five
  minutes per IP: a mistyped password does not lock you out, but a guesser does not
  get unlimited tries at the shipped default. This does not depend on
  `ui.rate_limit_enabled` — the shipped password is public and the login page will
  tell you it is still in use, so throttling guesses cannot be something you have to
  opt into.
- **General API rate limiting and query budgets are off by default**
  (`ui.rate_limit_enabled`, `ui.query_timeout_seconds`). Turn both on for anything
  reachable beyond your own machines; with the limiter on, the API and account routes
  share the configured budget on top of the always-on login limit.
- **Configuration files hold secrets in plain text** — camera credentials, weather
  station URLs, broker passwords. They live under `/opt/orpheus/config/`; keep the
  permissions tight and keep them out of git.
- **The broker trusts its network.** On loopback that is fine. Opening it to other
  hosts requires the auth file the installer insists on, and ideally TLS.
- **Media files are readable by anything on the box.** Recordings of your property
  are ordinary files under the data root. Over the API, though, the clip endpoints
  serve only files inside their own channel or camera directory — a signed-in viewer
  can fetch clips, not arbitrary files under the data root.
- **No audit log.** There is no record of who logged in or what they looked at.
- **Sessions cannot be revoked, and clip URLs carry the session token.** A JWT is
  valid for 24 hours and nothing can retire it early — there is no denylist, and
  changing a password does not invalidate a token already issued. Audio and video
  elements cannot send an `Authorization` header, so the clip endpoints also accept
  the token as a `?token=` query parameter, which means a working credential appears
  in the URL. The UI's own unit runs uvicorn with `--no-access-log` so those URLs stay
  out of the journal, but **anything else in the request path will log them** — put a
  reverse proxy in front for TLS and its access log becomes a file full of live
  session tokens unless you configure that away.

## The platform constraint

The reference deployment is an NVIDIA Jetson, whose vendor image pins Python to 3.9
(`requires-python = ">=3.9, <3.10"`). That floor is not a preference — the ARM64
builds of the ML stack that work on that hardware require it.

The consequence is honest and worth stating: **some dependencies are older than what
a current desktop install would use**, and some upstream security fixes ship only in
versions that require newer Python. We track this rather than pretend otherwise, and
whether the constraint can be lifted is still an open question.

What this means practically: the risk is bounded by not exposing the box. On a
private network, behind your router, with changed credentials, an older dependency
tree is a manageable posture. Directly on the internet it is not.

## Recommended deployment

1. Private network only. No port forwarding to the dashboard.
2. Change the seeded passwords and set a JWT secret.
3. If others should see your data, run the [read-only mirror](operator-manual/index.md#optional-features-and-their-switches)
   on a separate host and share that, with `public.enabled` for privacy-preserving
   projection — day-level timestamps and a site label, never coordinates.
4. If you must reach the dashboard remotely, use a VPN or an authenticated reverse
   proxy with TLS. Not a port forward.
5. Turn on rate limiting and query budgets if anything but you can reach it.

## Privacy

Orpheus records audio continuously and keeps clips that trigger detections. Those
clips can contain human speech and the sounds of your household. Be deliberate about
how long they persist. `orpheus-storage-sweep` deletes oldest-first once a category
passes its `max_gb` ceiling, or sooner if free space falls below `reserve_gb` — but
it also refuses to delete anything inside `floor_days`, so a floor is a *guarantee
that clips are kept*, not a promise that they go away. Nothing ages a clip out on a
schedule: on a quiet station well under its ceiling, audio from a year ago is still
on the disk. If a shorter life is what you want, lower both the ceiling and the
floor for that category, and check the result with `make storage-report`. The public
projection is
deliberately fail-closed: with it enabled and no site label configured, location
renders a placeholder rather than leaking a real position.
