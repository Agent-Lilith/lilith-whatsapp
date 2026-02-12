/**
 * One-time full history sync.
 *
 * Connects with syncFullHistory:true, persists every messaging-history.set
 * batch into Postgres, and exits after IDLE_TIMEOUT_MS of silence.
 *
 * No fetchMessageHistory, no anti-ban delays - the phone pushes everything.
 *
 * Run: npm run sync-history
 */
import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  Browsers,
  type WAMessage,
  type Chat,
  type Contact,
} from "@whiskeysockets/baileys";
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
/** How long to wait after the last batch before considering sync done. */
const IDLE_TIMEOUT_MS = 30_000;

async function main() {
  const db = await connectDb();
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_STATE_DIR);

  const chatIdCache = new Map<string, number>();
  let idleTimer: ReturnType<typeof setTimeout> | null = null;
  let batchCount = 0;
  let totalChats = 0;
  let totalContacts = 0;
  let totalMessages = 0;

  function done() {
    console.log(
      "[sync] No new data for %ds. Sync complete.",
      IDLE_TIMEOUT_MS / 1000
    );
    console.log(
      "[sync] Totals: %d chats, %d contacts, %d messages across %d batches",
      totalChats,
      totalContacts,
      totalMessages,
      batchCount
    );
    process.exit(0);
  }

  function resetIdleTimer() {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(done, IDLE_TIMEOUT_MS);
  }

  async function ensureChatId(jid: string): Promise<number> {
    let id = chatIdCache.get(jid);
    if (id != null) return id;
    const row = chatToRow({ id: jid });
    id = await upsertChat(db, row);
    chatIdCache.set(jid, id);
    return id;
  }

  async function persistBatch(
    chats: Chat[],
    contacts: Contact[],
    messages: WAMessage[]
  ) {
    for (const c of chats) {
      const row = chatToRow(c);
      const id = await upsertChat(db, row);
      chatIdCache.set(row.jid, id);
    }

    for (const contact of contacts) {
      await upsertContact(db, contactToRow(contact));
    }

    for (const msg of messages) {
      const key = msg.key;
      if (!key?.remoteJid || !key?.id) continue;
      const chatId = await ensureChatId(key.remoteJid);
      const row = messageToRow(chatId, key, msg, key.fromMe ?? false);
      await upsertMessage(db, row as MessageRow);
    }

    totalChats += chats.length;
    totalContacts += contacts.length;
    totalMessages += messages.length;
  }

  function connect() {
    const sock = makeWASocket({
      auth: state,
      browser: Browsers.macOS("Desktop"),
      syncFullHistory: true,
      getMessage: async (key) => {
        const row = await getMessageByKey(db, key.remoteJid!, key.id!);
        return row?.message ?? undefined;
      },
    });

    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("connection.update", (update) => {
      if (update.qr) {
        qrcode.generate(update.qr, { small: true });
        console.log("[sync] Scan QR with WhatsApp > Linked Devices");
      }
      if (update.connection === "open") {
        console.log("[sync] Connected. Waiting for history batches...");
        resetIdleTimer();
      }
      if (update.connection === "close") {
        const code = (
          update.lastDisconnect?.error as {
            output?: { statusCode?: number };
          }
        )?.output?.statusCode;
        if (code === DisconnectReason.loggedOut) {
          console.error("[sync] Logged out. Delete auth_state/ and re-scan.");
          process.exit(1);
        }
        if (code === DisconnectReason.restartRequired) {
          console.log("[sync] Restart required (post-pairing). Reconnecting...");
          connect();
          return;
        }
        console.log("[sync] Disconnected (%s). Exiting.", code ?? "unknown");
        process.exit(1);
      }
    });

    sock.ev.on(
      "messaging-history.set",
      async ({ chats, contacts, messages, syncType, progress }) => {
        batchCount++;
        resetIdleTimer();

        console.log(
          "[sync] Batch #%d: %d chats, %d contacts, %d msgs (type=%s, progress=%s%%)",
          batchCount,
          chats.length,
          contacts.length,
          messages.length,
          syncType ?? "?",
          progress ?? "?"
        );

        await persistBatch(chats, contacts, messages);

        console.log(
          "[sync] Running totals: %d chats, %d contacts, %d messages",
          totalChats,
          totalContacts,
          totalMessages
        );
      }
    );

    // LID -> phone number mapping: update contacts and chats when we learn the mapping
    sock.ev.on("lid-mapping.update", async ({ lid, pn }) => {
      resetIdleTimer();
      console.log("[sync] LID mapping: %s -> %s", lid, pn);

      // Update contact: set phone_number on the LID contact
      await upsertContact(db, {
        wa_id: lid,
        phone_number: pn.replace("@s.whatsapp.net", ""),
        lid: lid,
        push_name: null,
      });

      // Update chat: set jid_pn on the LID chat
      await db.query(
        `UPDATE chats SET jid_pn = $1, updated_at = now() WHERE jid = $2 AND jid_pn IS NULL`,
        [pn, lid]
      );
    });

    return sock;
  }

  connect();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
