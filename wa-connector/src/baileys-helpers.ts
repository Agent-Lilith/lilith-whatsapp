/**
 * Map Baileys v7 types to DB rows.
 *
 * Field sources (from Baileys history.js processHistoryMessage):
 *   Contact: { id, name?, lid?, phoneNumber?, notify?, verifiedName? }
 *   Chat:    IConversation & { lastMessageRecvTimestamp? }
 *            key fields: id, name, displayName, pnJid, lidJid
 *   Message: WAMessage with key, messageTimestamp, message, pushName
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;

/* ------------------------------------------------------------------ */
/*  Message helpers                                                    */
/* ------------------------------------------------------------------ */

export function extractMessageType(msg: Any): string {
  if (!msg) return "unknown";
  if (msg.conversation) return "text";
  if (msg.extendedTextMessage) return "text";
  if (msg.imageMessage) return "image";
  if (msg.videoMessage) return "video";
  if (msg.audioMessage) return "audio";
  if (msg.documentMessage) return "document";
  if (msg.stickerMessage) return "sticker";
  if (msg.contactMessage) return "contact";
  if (msg.contactsArrayMessage) return "contact";
  if (msg.locationMessage) return "location";
  if (msg.liveLocationMessage) return "location";
  if (msg.reactionMessage) return "reaction";
  if (msg.pollCreationMessage || msg.pollCreationMessageV3) return "poll";
  if (msg.viewOnceMessage || msg.viewOnceMessageV2) {
    return extractMessageType(msg.viewOnceMessage?.message ?? msg.viewOnceMessageV2?.message);
  }
  return "unknown";
}

export function extractBodyText(msg: Any): string | null {
  if (!msg) return null;
  const t =
    msg.conversation ??
    msg.extendedTextMessage?.text ??
    msg.imageMessage?.caption ??
    msg.videoMessage?.caption ??
    msg.documentMessage?.caption ??
    null;
  return typeof t === "string" ? t : null;
}

/* ------------------------------------------------------------------ */
/*  Chat                                                               */
/* ------------------------------------------------------------------ */

/** Extract phone number from a JID like 31612345678@s.whatsapp.net */
function phoneFromJid(jid: string | undefined | null): string | null {
  if (!jid || typeof jid !== "string") return null;
  const m = jid.match(/^(\d+)@s\.whatsapp\.net$/);
  return m ? m[1]! : null;
}

/**
 * Map a Baileys Chat (IConversation) to our DB shape.
 *
 * IConversation fields we care about:
 *   id         - JID (could be @s.whatsapp.net, @g.us, or @lid)
 *   name       - saved contact name or group subject
 *   displayName
 *   pnJid      - phone-number JID (@s.whatsapp.net)
 *   lidJid     - LID JID (@lid)
 */
export function chatToRow(c: Any): {
  jid: string;
  jid_pn: string | null;
  name: string | null;
  is_group: boolean;
} {
  const jid: string = c.id ?? "";
  const name: string | null = c.name ?? c.displayName ?? null;
  const isGroup = jid.endsWith("@g.us");

  // pnJid from proto, or derive from JID if it's a phone JID
  const pnJid: string | null = c.pnJid ?? (jid.endsWith("@s.whatsapp.net") ? jid : null);

  return {
    jid,
    jid_pn: typeof pnJid === "string" ? pnJid : null,
    name: typeof name === "string" ? name : null,
    is_group: isGroup,
  };
}

/* ------------------------------------------------------------------ */
/*  Contact                                                            */
/* ------------------------------------------------------------------ */

/**
 * Map a Baileys Contact to our DB shape.
 *
 * Baileys Contact interface:
 *   id          - JID (preferred format)
 *   lid         - LID format (@lid)
 *   phoneNumber - phone number string
 *   name        - saved contact name
 *   notify      - push name (set by the contact)
 *   verifiedName
 *
 * From history processing, contacts arrive as:
 *   { id, name, lid, phoneNumber } or { id, notify }
 */
export function contactToRow(contact: Any): {
  wa_id: string;
  phone_number: string | null;
  lid: string | null;
  push_name: string | null;
} {
  const rawId: string = contact.id ?? "";

  // Phone number: explicit field, or extract from JID
  const phoneNumber: string | null =
    contact.phoneNumber ?? phoneFromJid(rawId) ?? null;

  // LID: explicit field, or if the ID itself is a LID
  const lid: string | null =
    contact.lid ?? (rawId.includes("@lid") ? rawId : null);

  // Display name: saved name > push name (notify) > verified business name
  const pushName: string | null =
    contact.name ?? contact.notify ?? contact.verifiedName ?? null;

  return {
    wa_id: rawId,
    phone_number: typeof phoneNumber === "string" ? phoneNumber : null,
    lid: typeof lid === "string" ? lid : null,
    push_name: typeof pushName === "string" ? pushName : null,
  };
}

/* ------------------------------------------------------------------ */
/*  Message                                                            */
/* ------------------------------------------------------------------ */

export function messageToRow(
  chatId: number,
  key: {
    remoteJid?: string | null;
    id?: string | null;
    participant?: string | null;
    remoteJidAlt?: string;
    participantAlt?: string | null;
    fromMe?: boolean | null;
  },
  msg: Any,
  fromMe: boolean
): {
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
} {
  // Parse timestamp with validation: Baileys messageTimestamp is Unix seconds.
  // Some messages from history sync have timestamps shifted ~20 years into the
  // future (likely a protobuf Long deserialization issue). Clamp to now() if
  // the resulting date is more than 1 day in the future.
  let ts: Date;
  if (msg?.messageTimestamp) {
    const epochMs = Number(msg.messageTimestamp) * 1000;
    const candidate = new Date(epochMs);
    const oneDayFromNow = Date.now() + 86_400_000;
    if (candidate.getTime() > oneDayFromNow) {
      console.warn(
        `[baileys] Future timestamp detected: ${candidate.toISOString()} (epoch=${msg.messageTimestamp}), using current time`
      );
      ts = new Date();
    } else {
      ts = candidate;
    }
  } else {
    ts = new Date();
  }

  // Phone number of the other party:
  //   Groups: participant is the actual sender
  //   DMs: remoteJid is the counterparty (same regardless of direction)
  const isGroup = key.remoteJid?.endsWith("@g.us");
  const phoneJid = isGroup ? key.participant : key.remoteJid;
  const phoneNumber = phoneFromJid(phoneJid ?? undefined);

  return {
    chat_id: chatId,
    wa_message_id: key.id ?? "",
    remote_jid: key.remoteJid ?? "",
    participant: key.participant ?? null,
    participant_alt: key.participantAlt ?? null,
    remote_jid_alt: key.remoteJidAlt ?? null,
    from_me: fromMe,
    timestamp: ts,
    message_type: extractMessageType(msg?.message ?? msg),
    body_text: extractBodyText(msg?.message ?? msg),
    phone_number: phoneNumber,
    metadata_json: msg?.message ? { ...msg.message } : null,
  };
}
