import pg from "pg";

const { Client } = pg;

export interface ChatRow {
  id?: number;
  jid: string;
  jid_pn: string | null;
  name: string | null;
  is_group: boolean;
}

export interface ContactRow {
  id?: number;
  wa_id: string;
  phone_number: string | null;
  lid: string | null;
  push_name: string | null;
}

export interface MessageRow {
  id?: number;
  chat_id: number;
  wa_message_id: string;
  remote_jid: string;
  participant: string | null;
  participant_alt: string | null;
  remote_jid_alt: string | null;
  from_me: boolean;
  timestamp: Date;
  message_type: string;
  body_text: string | null;
  phone_number: string | null;
  metadata_json: Record<string, unknown> | null;
}

let client: pg.Client | null = null;

export function getDb(): pg.Client {
  if (!client) {
    const url = process.env.DATABASE_URL;
    if (!url) throw new Error("DATABASE_URL is not set");
    client = new Client({ connectionString: url });
  }
  return client;
}

let connected = false;

export async function connectDb(): Promise<pg.Client> {
  const c = getDb();
  if (!connected) {
    await c.connect();
    connected = true;
  }
  return c;
}

export async function upsertChat(db: pg.Client, row: ChatRow): Promise<number> {
  const r = await db.query(
    `INSERT INTO chats (jid, jid_pn, name, is_group)
     VALUES ($1, $2, $3, $4)
     ON CONFLICT (jid) DO UPDATE SET
       jid_pn = COALESCE(EXCLUDED.jid_pn, chats.jid_pn),
       name = COALESCE(EXCLUDED.name, chats.name),
       is_group = EXCLUDED.is_group,
       updated_at = now()
     RETURNING id`,
    [row.jid, row.jid_pn, row.name, row.is_group]
  );
  return r.rows[0].id as number;
}

export async function upsertContact(db: pg.Client, row: ContactRow): Promise<number> {
  const r = await db.query(
    `INSERT INTO contacts (wa_id, phone_number, lid, push_name)
     VALUES ($1, $2, $3, $4)
     ON CONFLICT (wa_id) DO UPDATE SET
       phone_number = COALESCE(EXCLUDED.phone_number, contacts.phone_number),
       lid = COALESCE(EXCLUDED.lid, contacts.lid),
       push_name = COALESCE(EXCLUDED.push_name, contacts.push_name),
       updated_at = now()
     RETURNING id`,
    [row.wa_id, row.phone_number, row.lid, row.push_name]
  );
  return r.rows[0].id as number;
}

export async function upsertMessage(db: pg.Client, row: MessageRow): Promise<void> {
  await db.query(
    `INSERT INTO messages (chat_id, wa_message_id, remote_jid, participant, participant_alt, remote_jid_alt, from_me, timestamp, message_type, body_text, phone_number, metadata_json)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
     ON CONFLICT (chat_id, wa_message_id) DO UPDATE SET
       participant = EXCLUDED.participant,
       participant_alt = EXCLUDED.participant_alt,
       remote_jid_alt = EXCLUDED.remote_jid_alt,
       body_text = COALESCE(EXCLUDED.body_text, messages.body_text),
       phone_number = COALESCE(EXCLUDED.phone_number, messages.phone_number),
       metadata_json = COALESCE(EXCLUDED.metadata_json, messages.metadata_json)`,
    [
      row.chat_id,
      row.wa_message_id,
      row.remote_jid,
      row.participant,
      row.participant_alt,
      row.remote_jid_alt,
      row.from_me,
      row.timestamp,
      row.message_type,
      row.body_text,
      row.phone_number,
      row.metadata_json ? JSON.stringify(row.metadata_json) : null,
    ]
  );
}

export async function getChatIdByJid(db: pg.Client, jid: string): Promise<number | null> {
  const r = await db.query("SELECT id FROM chats WHERE jid = $1", [jid]);
  return r.rows[0]?.id ?? null;
}

export async function getMessageByKey(
  db: pg.Client,
  remoteJid: string,
  id: string
): Promise<{ key: { remoteJid: string; id: string }; message?: unknown } | null> {
  const chatId = await getChatIdByJid(db, remoteJid);
  if (!chatId) return null;
  const r = await db.query(
    "SELECT wa_message_id, body_text, metadata_json FROM messages WHERE chat_id = $1 AND wa_message_id = $2",
    [chatId, id]
  );
  const row = r.rows[0];
  if (!row) return null;
  return {
    key: { remoteJid, id: row.wa_message_id },
    message: row.metadata_json ?? undefined,
  };
}

