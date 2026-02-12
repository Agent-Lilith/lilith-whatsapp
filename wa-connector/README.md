# WhatsApp connector

Syncs WhatsApp into PostgreSQL using [Baileys v7](https://github.com/WhiskeySockets/Baileys) (7.0.0-rc.9).

## Setup

```bash
cd wa-connector
cp .env.example .env
npm install
```
## Scripts

**Full history sync** (runs once, exits when done):

> [!IMPORTANT]
> Whatsapp only syncs on first connect, delete auth_state everytime you run this.


```bash
npm run sync-history
```

First run shows a QR code to scan.

**Live listener** (long-running, new messages only):
```bash
npm run listen
```
