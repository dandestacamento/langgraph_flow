# Sample conversation 2 - image attachments

Files used (in [`files/`](./files/)): `washing-machine-error-E21.png`,
`refrigerator-error-E05.png`.

Click **+ New conversation** first. Attach files with the **+** button, by **dragging them
onto the composer**, or by **pasting a screenshot** (copy an image, then Ctrl+V in the
message box). While a file uploads, its pill shows *uploading…* - the vision extraction
happens at upload time, so the chat turn itself is not slowed down.

---

### Turn 1 - a photo grounds a knowledge-base question

Attach `washing-machine-error-E21.png`, then:

> **You:** My washing machine shows this error - what does it mean?

**Expected:** The vision model reads "E21" off the image, the question is condensed to
*"What does washing machine error E21 mean?"*, and the **unchanged knowledge-base pipeline**
answers: "E21: Drainage problem. Check the pump filter and drain hose for blockages…" with
real citations in Routing details. Your message shows the image thumbnail above it. The
generated title mentions E21.

### Turn 2 - follow-up still works with the image context

> **You:** How do I fix it?

**Expected:** Drainage-fix guidance (pump filter / drain hose), still cited - "it" resolves
to the E21 fault from turn 1.

---

### New conversation - asking about the image itself

Click **+ New conversation**, attach `refrigerator-error-E05.png`, then:

> **You:** What's in this image?

**Expected:** A direct description - e.g. *"A display for a SMARTHOME REFRIGERATOR RF-450
showing error code E05…"* - with **no Routing details panel**: describing an attachment is
not a knowledge-base question, so nothing is routed and no citations are invented.

### Turn 2 - then pivot into the knowledge base

> **You:** What does that error code mean for this fridge?

**Expected:** Back through the pipeline: "E05 indicates an evaporator fan failure", with
refrigerator troubleshooting citations - the attachment's extracted E05 plus conversation
memory feed the condense step.

### Turn 3 - attachments-only message

Attach either image again and press **Send with the text box empty**.

**Expected:** Sending works (attachments alone are a valid message) and you get a
description of the image.

---

### Also verify

- Thumbnails persist: press **F5** - the image thumbnails re-render inside the restored
  conversation (they are fetched with your auth token; another user's token gets a 403).
- Paste path: screenshot any window (Win+Shift+S), click into the message box, Ctrl+V -
  a `pasted-image.png` pill appears and uploads like a picked file.
- Oversized/unsupported files are rejected with a clear inline error on the pill
  (limit: 5 MB; images are PNG/JPEG/WebP/GIF - SVG is deliberately not accepted).
