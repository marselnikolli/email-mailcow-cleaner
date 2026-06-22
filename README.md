# Mailcow Cleaner

Web-based tool to bulk-delete emails from mailcow mailboxes by sender, subject, age, and folder.

## How it works

- Uses the **mailcow REST API** (`/api/v1/get/*`) to list domains and mailboxes in the UI
- Uses **`doveadm expunge`** — executed inside the dovecot container via the Docker socket — to search and delete messages directly on the mail store
- Runs as a **standalone Docker container** alongside your mailcow stack (no SSH needed)

```
┌────────────────────┐     HTTP / HTTPS      ┌──────────────┐
│  mailcow-cleaner   │ ───────────────────────▸│ mailcow-API  │
│  (your browser)    │                         │ (nginx)      │
└────────┬───────────┘                        └──────────────┘
         │ docker exec doveadm expunge
         ▼
┌──────────────────┐
│ dovecot-mailcow  │  ← uses the actual mail store
└──────────────────┘
```

## Prerequisites

No changes needed on the mailcow side beyond creating an API key. The tool talks to mailcow externally:

- **Docker** with `docker compose` on the mailcow host
- **Mailcow API key** with read-write access (see setup below)
- The default Dovecot container name **must be `dovecot-mailcow`** (it is unless you renamed it)

## Mailcow Setup

### 1. Create an API key

1. Log into your **mailcow admin panel**
2. Go to **Access** → **API** (or `https://your-mailcow/admin/api`)
3. Click **Add**
4. Set:
   - **API key**: generate a random string (or let mailcow generate one)
   - **Access**: `Read-Write (rw)` — write access is required to delete messages
   - **Allow from**: leave blank (allow all) or restrict to your cleaner container's IP
5. Click **Add**
6. Copy the API key — you will need it in the web UI

### 2. Verify the dovecot container name

```bash
docker ps | grep dovecot
```

Expected output (yours will have a different container ID):
```
abc123   dovecot-mailcow   ...
```

If your container is named differently (e.g. `mailcow_dovecot_1`), note the name — you can configure it in the web UI.

### 3. Ensure the Docker socket is available

The cleaner needs access to `/var/run/docker.sock` on the host. This is **always present** on the mailcow host by default. No action needed.

## Deployment

### Option A: Standalone container (recommended)

Clone this repo on your mailcow host and run:

```bash
git clone <this-repo> /opt/mailcow-cleaner
cd /opt/mailcow-cleaner

# Build and start
docker compose up -d --build

# Open in browser
echo "http://$(hostname -I | awk '{print $1}'):5000"
```

The `docker-compose.yml` handles everything:
- Builds the image
- Creates a `data/` volume for config persistence
- Mounts the Docker socket (read-only)
- Joins the `mailcow-network` so it can resolve the mailcow API internally

### Option B: Add to your mailcow override file

Append this to your existing `docker-compose.override.yml` in your mailcow directory:

```yaml
version: '3.8'

services:
  mailcow-cleaner:
    build: /path/to/mailcow-cleaner
    container_name: mailcow-cleaner
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - /opt/mailcow-cleaner/data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - SECRET_KEY=generate-a-random-string-here
    networks:
      - mailcow-network
```

Then run from your mailcow directory:

```bash
docker compose up -d
```

## First-time configuration

Open `http://your-server:5000` in a browser.

1. Go to the **Connection** section
2. Enter your **Mailcow URL** — the external URL of your mailcow instance, e.g. `https://mail.example.com`
   - If the cleaner is on the same Docker network, you can also use the internal URL: `https://nginx-mailcow` (port 443)
3. Paste your **API key**
4. Adjust the **Dovecot Container** name if yours differs from `dovecot-mailcow`
5. Click **Test** — you should see a green "Connection OK" message
6. Click **Save config**

The domains dropdown and mailbox list will now populate.

## Usage

### 1. Select targets

- **Domain mode**: pick a domain — all mailboxes in that domain will be cleaned
- **Mailbox mode**: select individual mailboxes from the checklist

### 2. Set filters

| Filter | Example | Behavior |
|---|---|---|
| **From** | `newsletter@co.com, spam@mail.com` | Comma-separated sender addresses to match |
| **Subject** | `Your monthly invoice` | Messages whose subject contains this text |
| **Age** | `30 days` | Messages saved more than N days/weeks/months/years ago |
| **Folders** | `INBOX, Junk, Trash` | Which folders to search |
| **Match logic** | AND or OR | AND = all conditions must match. OR = any condition matches |

### 3. Preview

Click **Preview** to see how many messages match your filters, broken down by mailbox and folder. No messages are deleted at this stage.

### 4. Delete

Click **Delete** → confirm in the dialog. Messages are permanently removed using `doveadm expunge`.

## How the filtering works

The tool translates your UI filter inputs into `doveadm search` / `doveadm expunge` commands. For example:

| UI filter | Doveadm command |
|---|---|
| From `spam@example.com`, OR match | `doveadm expunge -u user@dom.com mailbox INBOX OR from "spam@example.com" from "other@example.com"` |
| From + Subject, AND match | `doveadm expunge -u user@dom.com mailbox INBOX from "spam@example.com" subject "Newsletter"` |
| Age 30 days, INBOX only | `doveadm expunge -u user@dom.com mailbox INBOX savedbefore 30d` |
| Junk folder, 7 days | `doveadm expunge -u user@dom.com mailbox Junk savedbefore 7d` |

The **Header matching** toggle switches between:
- `from "email"` — matches the IMAP envelope FROM (default, faster)
- `HEADER From "email"` — matches the raw From header (more accurate in some edge cases)

## Dovecot time units

| Unit | Suffix |
|---|---|
| Days | `30d` |
| Weeks | `4w` |
| Months | `2M` (capital M) |
| Years | `1y` |

## Security

- The Docker socket is mounted **read-only** (`:ro`) — the container can only read it to exec commands, not manage Docker
- Change the `SECRET_KEY` environment variable to a random string
- Restrict access to port 5000 with a firewall if the tool is exposed to a network
- The API key is stored in the `data/` volume — secure this directory

## Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| "Not configured" in API | API key missing or empty | Enter credentials and click Save |
| Connection test fails | Wrong URL or API key | Verify the URL is reachable and the key has rw access |
| "Docker CLI not found" | Docker not installed in the container | The container installs `docker.io` at build time — rebuild with `docker compose build` |
| "No such container" | Dovecot container has a different name | Run `docker ps` and update the container name in the web UI |
| Preview shows 0 but emails exist | Wrong mailbox folder or filter too strict | Try fewer folders (e.g. just INBOX) or broader filters |
| Timeout errors | Very large mailboxes or slow disk | The doveadm search runs with a 120-second timeout per folder |
| Permission denied on docker socket | Docker socket not mounted or wrong permissions | Ensure `/var/run/docker.sock` exists on the host and is mounted in docker-compose.yml |

## What does NOT need changing on mailcow

- **No** need to modify any mailcow configuration files
- **No** need to restart or reconfigure Postfix, Dovecot, Nginx, or any mailcow container
- **No** need to install anything inside mailcow containers
- **No** need to open additional ports in the mailcow firewall (the cleaner connects to the existing web UI port)

The only mailcow-side requirement is creating the API key (step 1 in the setup).
