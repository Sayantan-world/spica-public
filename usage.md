# SPICA usage

SPICA is an AAC chat app that **speaks as the signed-in user**. A conversation partner types or records a message. The AAC user either taps a picture-board phrase, or waits and then picks one of four generated replies. The app speaks that reply in the chosen voice.

Open the site (local default: http://0.0.0.0:5001). Create an account or log in. After login you are in the chat app.

---

## Who does what

| Role | What they do in the UI |
| --- | --- |
| **Partner** | Types (or records) a message in the input at the bottom and sends it. |
| **AAC user** (the signed-in account) | Optionally uses webcam and/or picture board, then picks a reply (or the picture-board tap *is* the reply). |

The generated text is always first person, as the AAC user. It is grounded in that account’s stored memories when those memories are relevant.

---

## Create an account / log in

On the landing page:

1. **Create account** — username, first name, last name, date of birth, password.
2. **Log in** — username and password.

Account rules:

- Username: 3–40 characters, lowercase letters, numbers, underscore.
- Password: 8–128 characters.
- First / last name: letters, spaces, apostrophes, hyphens.
- Username must be unique. The same first+last name cannot be reused.

Use **Log out** in the sidebar (right of the theme toggle).

---

## First-time setup (sidebar)

Use **Menu** on small screens to open the sidebar.

### 1. Data (required for personal replies)

Click **Data**. You can add personal text so replies sound like this user.

- **Raw text (.txt)** — upload a `.txt` file.
- **Paste text** — paste into the box and submit.

Then click **Process** on that file. Processing extracts facts, relations, and memory chunks and stores them for this account. Wait until it finishes before chatting if you want those memories used.

The eye icon opens **Stored for you** (facts, memory chunks, relations). The X icon closes it. Delete a file if you need a slot.

Without processed data, chat still works, but replies are generic rather than biography-grounded.

### 2. Voice

Click **Voice**. Six Magpie voices: Jason, Leo, Ray (male); Mia, Aria, Sofia (female). Click a chip to hear a sample and save it. That voice is used for spoken replies and picture-board phrases.

Webcam emotion can change Magpie tone on speak (happy → Happy, frustrated → Angry, surprised → Fearful on Sofia/Ray else Neutral, otherwise Neutral / default).

### 3. Picture board (on by default)

**Pictureboard** / **Hide** in the navbar. Twelve phrases:

Yes, No, Help, Bathroom, Hungry, Thirsty, Excuse me, I like it, Don’t like, Tell me more, Wait, Come here.

A tap plays cached audio and can become the turn reply (see chat flow below).

### 4. Webcam (optional)

**Enable webcam** for a 5 second capture after each partner send: emotion, hand gesture, head nod/shake. Those cues shape **chit-chat** and **persona · alternate** when four options are generated.

---

## Chat

1. Open **Sessions** if you need the list (collapsed by default so the thread is wide).
2. **New session** starts a conversation. The first partner line becomes the session title.
3. Partner types a message (or uses the mic; Whisper transcribes) and hits send.
4. Then one of:

**Picture board is on**

- A **5 second** window starts. Tap a phrase in that window: that phrase is saved as the AAC reply, spoken from the board, and **four options are not generated**.
- If you do not tap: after 5 seconds the agent generates four options as usual.

**Picture board is off**

- If webcam is on, the same 5 seconds are used only for sensing, then four options generate.
- If webcam is also off, generation starts immediately.

**Four options** (when generation runs)

| Label | Intent |
| --- | --- |
| Persona · grounded | Answer from profile / facts / memories. |
| Persona · alternate | Same grounding, different angle; uses live webcam cues when present. |
| Chit-chat | Light social reply; uses live webcam cues when present. |
| Turnaround · clarify | Steer or ask what the partner meant. |

Click one card. That text is the AAC turn, is spoken (auto-speak on first select), and is stored. You cannot send another partner message until a pick is made (unless the picture board already closed the turn).

Speak again with the speaker on an AAC bubble. Picture-board “quick” bubbles stay in the thread as italic quick messages.

Delete a session from the sessions list when you hit the session cap or want a clean thread.

Theme (sun / moon) is on the landing page and next to the SPICA title after login.

---

## Limits

These are the defaults. Operators can change them in `.env`.

| Limit | Default | What happens if you hit it |
| --- | --- | --- |
| Text files per account | **5** | Delete a file before adding another. |
| Characters per file / paste | **10,000** | Upload or paste is rejected. |
| Chat sessions per account | **5** | Delete an older session to start a new one. |
| Turns per session | **20** | Partner+AAC pairs. Start a new session. |
| Partner message length | **4,000** characters | Send is rejected. |
| Picture-board phrase length | **400** characters | API cap; the board uses short canned phrases. |
| Capture / picture-board wait | **5 seconds** | Then generate (if no board tap) or continue. |
| Username | 3–40 chars | Registration rejected. |
| Password | 8–128 chars | Registration rejected. |
| Speech upload | **8 MB** | Partner mic clip too large. |
| Login session | **30 days** | Log in again. |

Related (not user-facing caps, but they shape replies):

- Retrieval: **top 2** memory chunks and **top 2** facts per partner turn.
- Prompt history: about the last **8** turns.
- Luna processing input budget: **4096** tokens; chat generation input budget: **8192** tokens.

---

## How a turn is produced (for operators / new developers)

When four options are needed, a central orchestrator calls tools in a fixed order (the model does not pick tools):

1. Load session and profile summary  
2. Retrieve memory (vector search, non-fact chunks)  
3. Retrieve facts (fact chunks, else ranked account facts)  
4. Format recent dialogue  
5. Generate four first-person options (Luna)  
6. Store them as pending until the AAC user picks  

After a pick (or a picture-board direct reply), the turn is committed and durable new details may be written back into facts/memory.

Memory itself: processed uploads are chunked, embedded with nomic (`nomic-ai/nomic-embed-text-v1.5`), and stored in Postgres (`account_memory_chunks` + account facts/relations). Chat reads those stores; it does not fine-tune a model per user.
