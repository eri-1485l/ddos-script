# Bounded HTTP load test (`flood.py`)

`flood.py` is a time-bounded HTTP GET load tester used to measure how much concurrent load the lab services tolerate while Fail2Ban and iptables protection are active. It runs on the Windows host (outside Docker) and targets a single `host:port` per run, with an optional path. It is a lab load test: it stops when `DURATION` expires.

The Docker services involved in this lab are `dash-backend` (image `lista-backend`), `dash-frontend` (image `lista-frontend`), `openldap` (image `openldap-protected`), plus `keycloak` and `keycloak-fail2ban`.

---

## Origin

This script derives from the Fail2Ban laboratory provided by the professor. The original version used hardcoded targets. It was modified for the assignment so each run can target one published service from the host while Fail2Ban jails and iptables remain enabled inside the containers.

---

## Changes from the original script

- Replaced the hardcoded `TARGETS` tuple with `argparse` positional arguments `<host>` and `<port>`.
- Added `--path` to target a specific endpoint (default `/`).
- Kept all bounded limits (`DURATION` max 300s, `CONCURRENCY` max 500, `REQUESTS_PER_SECOND` max 500).
- The script now targets one `host:port` per run.

---

## Usage

Requires Python 3 on the Windows host. Use `python` (not `python3`). Set environment variables in PowerShell on their own lines, then run the script.

```powershell
$env:DURATION=15
$env:CONCURRENCY=10
$env:REQUESTS_PER_SECOND=10
python flood.py <host> <port> [--path <path>]
```

### Examples

Backend health endpoint:

```powershell
$env:DURATION=15
$env:CONCURRENCY=10
$env:REQUESTS_PER_SECOND=10
python flood.py localhost 8001 --path /health
```

Frontend root:

```powershell
$env:DURATION=15
$env:CONCURRENCY=10
$env:REQUESTS_PER_SECOND=10
python flood.py localhost 5173 --path /
```

LDAP published port (HTTP GET against the TLS port; LDAP is not an HTTP service):

```powershell
$env:DURATION=15
$env:CONCURRENCY=50
$env:REQUESTS_PER_SECOND=100
python flood.py localhost 636 --path /
```

### Environment variables

| Variable | Default | Maximum | Description |
|---|---|---|---|
| `DURATION` | `20` | `300` | Test length in seconds. The process stops when this window ends. |
| `CONCURRENCY` | `40` | `500` | Number of worker threads. |
| `REQUESTS_PER_SECOND` | `50` | `500` |Aggregate request-start rate limit. |

Stop early with `Ctrl+C`. The script prints periodic counters (`total`, `ok(200)`, `failed`) and a final percentage of non-200 responses.

---

## Methodology: how the load value that does not bring the service down was found

The goal was to find, for each service, the highest load at which the service stayed up with **Fail2Ban and iptables active**.

1. Started the stack in Docker with Fail2Ban and iptables protection enabled (`dash-backend`, `dash-frontend`, `openldap`, and the Keycloak containers). Load was generated from the Windows host, not from inside those images.
2. Ran `flood.py` against the backend at `localhost:8001` with path `/health`, starting at `CONCURRENCY=10`, `REQUESTS_PER_SECOND=10`, `DURATION=15`, then increased concurrency in steps: 10, 50, 100, 200, 500 (with the matching `REQUESTS_PER_SECOND` values in the results tables).
3. Repeated the same ladder for the frontend at `localhost:5173` with path `/`, and tested LDAP at `localhost:636` with path `/` at `CONCURRENCY=50`, `REQUESTS_PER_SECOND=100`, `DURATION=15`.
4. Recorded totals, OK counts, failures, and `% non-200` after each run. For HTTP services, **0% non-200** meant the service was still answering. For LDAP, HTTP 100% non-200 is expected (LDAP is not HTTP); the container remaining healthy is the success criterion.
5. Took the highest concurrency that did not bring the service down (see the summary after the tables). Fail2Ban trigger tests used different paths (`/api/books`, `/nonexistent`) and, for LDAP, failed `ldapsearch` binds; those are documented in the demonstration section, not in the capacity tables.

---

## Results

### Backend (`localhost:8001`, path `/health`)

Container: `dash-backend`. Log: `/var/log/backend-access.log` (uvicorn).

| CONCURRENCY | REQUESTS_PER_SECOND | DURATION | Total | OK | Failed | % non-200 |
|---|---|---|---|---|---|---|
| 10 | 10 | 15s | 150 | 150 | 0 | 0% |
| 50 | 100 | 15s | 1475 | 1475 | 0 | 0% |
| 100 | 200 | 15s | 2757 | 2757 | 0 | 0% |
| 200 | 400 | 15s | 2719 | 2719 | 0 | 0% |
| 500 | 500 | 15s | 2726 | 2726 | 0 | 0% |

### Frontend (`localhost:5173`, path `/`)

Container: `dash-frontend`. Log: `/var/log/nginx/access.log` (Nginx proxy to Vite).

| CONCURRENCY | REQUESTS_PER_SECOND | DURATION | Total | OK | Failed | % non-200 |
|---|---|---|---|---|---|---|
| 10 | 10 | 15s | 150 | 150 | 0 | 0% |
| 50 | 100 | 15s | 1473 | 1473 | 0 | 0% |
| 100 | 200 | 15s | 2394 | 2394 | 0 | 0% |
| 200 | 400 | 15s | 2439 | 2439 | 0 | 0% |
| 500 | 500 | 15s | 2291 | 2291 | 0 | 0% |

### LDAP (`localhost:636`, path `/`)

Container: `openldap`. Log: `/var/log/slapd/slapd.log`. HTTP GET against LDAP is expected to fail.

| CONCURRENCY | REQUESTS_PER_SECOND | DURATION | Total | OK | Failed | % non-200 |
|---|---|---|---|---|---|---|
| 50 | 100 | 15s | 381 | 0 | 381 | 100% (expected: LDAP is not HTTP) |

### Highest load that did not bring any service down

| Service | Load | Outcome |
|---|---|---|
| Backend | 500 workers / 500 req/s / 15s | 0% non-200 |
| Frontend | 500 workers / 500 req/s / 15s | 0% non-200 |
| LDAP | 50 workers / 100 req/s / 15s | Container healthy, CPU 0.06% |

---

## Protection layers

Two layers keep the services available.

### Layer 1: iptables

iptables applies kernel-level rate limiting and, after Fail2Ban matches, installs a ban so further packets from the offending IP do not reach the application. After a backend ban, curl to the backend returns `000` (blocked by iptables).

### Layer 2: Fail2Ban

Fail2Ban reads access logs and bans the source IP.

| Service | Jail | Log | Process | maxretry | findtime | bantime |
|---|---|---|---|---|---|---|
| Backend | `backend-auth` | `/var/log/backend-access.log` | uvicorn | 5 | 10s | 600s |
| Frontend | `frontend-flood` | `/var/log/nginx/access.log` | Nginx proxy to Vite | 5 | 10s | 600s |
| LDAP | `ldap-tls` | `/var/log/slapd/slapd.log` | OpenLDAP | 3 | 300s | 7200s |

---

## Demonstrating the protection

These runs prove Fail2Ban bans the attacker IP. They use paths (or LDAP binds) that the jails actually match. Capacity tests on `/health` and `/` return 200 and do not trip `backend-auth`.

### Backend (`dash-backend`, jail `backend-auth`)

`/api/books` returns 401 Unauthorized without a JWT, which is what `backend-auth` looks for. Flooding `/health` would return 200 and never trigger a ban.

```powershell
$env:CONCURRENCY=50
$env:DURATION=30
python flood.py localhost 8001 --path /api/books
```

```powershell
docker exec dash-backend fail2ban-client status backend-auth
```

Expected output:

```text
Status for the jail: backend-auth
|- Filter
|  |- Currently failed: 0
|  |- Total failed:     1065
|  `- File list:        /var/log/backend-access.log
`- Actions
   |- Currently banned: 1
   |- Total banned:     1
   `- Banned IP list:   172.17.0.1
```

After the ban, curl to the backend returns `000` (blocked by iptables).

### Frontend (`dash-frontend`, jail `frontend-flood`)

`/nonexistent` makes Nginx return 499 (client closed) or 404, which `frontend-flood` matches.

```powershell
$env:CONCURRENCY=50
$env:DURATION=30
python flood.py localhost 5173 --path /nonexistent
```

```powershell
docker exec dash-frontend fail2ban-client status frontend-flood
```

Expected output:

```text
Status for the jail: frontend-flood
|- Filter
|  |- Currently failed: 0
|  |- Total failed:     593
|  `- File list:        /var/log/nginx/access.log
`- Actions
   |- Currently banned: 1
   |- Total banned:     1
   `- Banned IP list:   172.17.0.1
```

### LDAP (`openldap`, jail `ldap-tls`)

Failed binds against LDAP (wrong password), from a PowerShell loop:

```powershell
for ($i=1; $i -le 20; $i++) {
    docker exec openldap ldapsearch -x -H ldap://localhost:389 `
        -D "cn=admin,dc=example,dc=com" -w wrongpassword `
        -b "dc=example,dc=com" -s base 2>&1 | Out-Null
}
```

```powershell
docker exec openldap fail2ban-client status ldap-tls
```

---

## Notes

- The script runs on the Windows host with Python 3 (`python`), outside `dash-backend`, `dash-frontend`, and `openldap`.
- It is a bounded load test, not a real DDoS. It stops after the configured `DURATION`.
- A non-200 response can be a ban, an HTTP error, or a connection timeout. Status `000` is used when the connection fails, including when iptables has already blocked the IP.
