/**
 * Long-running listener: persist new messages as they arrive.
 * No history sync - pair with sync-history for initial data.
 *
 * Run: npm run listen
 */
import makeWASocket, { useMultiFileAuthState, DisconnectReason } from "@whiskeysockets/baileys";
import qrcode from "qrcode-terminal";
import "dotenv/config";
import {
  connectDb,
  upsertChat,
  upsertContact,
  upsertMessage,
  getMessageByKey,
  type MessageRow,
} from "./db.js";
import { chatToRow, contactToRow, messageToRow } from "./baileys-helpers.js";

const AUTH_STATE_DIR = process.env.AUTH_STATE_DIR ?? "./auth_state";

async function main() {
  const db = await connectDb();
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_STATE_DIR);

  const chatIdCache = new Map<string, number>();

  async function ensureChatId(jid: string): Promise<number> {
    let id = chatIdCache.get(jid);
    if (id != null) return id;
    const row = chatToRow({ id: jid });
    id = await upsertChat(db, row);
    chatIdCache.set(jid, id);
    return id;
  }

  function connect() {
    const sock = makeWASocket({
      auth: state,
      shouldSyncHistoryMessage: () => false,
      getMessage: async (key) => {
        const row = await getMessageByKey(db, key.remoteJid!, key.id!);
        return row?.message ?? undefined;
      },
    });

    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("connection.update", (update) => {
      if (update.qr) {
        qrcode.generate(update.qr, { small: true });
        console.log("[listen] Scan QR with WhatsApp > Linked Devices");
      }
      if (update.connection === "open") {
        console.log("[listen] Connected. Listening for new messages...");
      }
      if (update.connection === "close") {
        const code = (
          update.lastDisconnect?.error as {
            output?: { statusCode?: number };
          }
        )?.output?.statusCode;
        if (code === DisconnectReason.loggedOut) {
          console.error("[listen] Logged out. Delete auth_state/ and re-scan.");
          process.exit(1);
        }
        if (code === DisconnectReason.restartRequired) {
          console.log("[listen] Restart required. Reconnecting...");
          connect();
          return;
        }
        console.log("[listen] Disconnected (%s). Reconnecting in 5s...", code ?? "unknown");
        setTimeout(() => connect(), 5000);
      }
    });

    sock.ev.on("chats.upsert", async (chats) => {
      for (const c of chats) {
        const jid = c.id;
        if (!jid) continue;
        const row = chatToRow(c);
        const id = await upsertChat(db, row);
        chatIdCache.set(jid, id);
      }
    });

    sock.ev.on("contacts.upsert", async (contacts) => {
      for (const contact of contacts) {
        if (!contact.id) continue;
        await upsertContact(db, contactToRow(contact));
      }
    });

    sock.ev.on("messages.upsert", async ({ messages: msgs }) => {
      for (const m of msgs) {
        const key = m.key;
        if (!key?.remoteJid || !key?.id) continue;
        const chatId = await ensureChatId(key.remoteJid);
        const row = messageToRow(chatId, key, m, key.fromMe ?? false);
        await upsertMessage(db, row as MessageRow);
      }
    });

    return sock;
  }

  connect();
  console.log("[listen] Running. Ctrl+C to stop.");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
