# Presentation — 3 minutes

**Open [`presentation.html`](presentation.html) in any browser and press `F`.**
Arrow keys or space to advance, `P` to print to PDF. No internet needed, no
slide software, nothing to install — same rule as the rest of the build.

**12 slides · ~15 seconds each.** The slides carry the headline; the notes
below are what the speaker says. Don't read the slide aloud — the room can
already read it.

---

### 1 · Title — *20s*
> **Communities talk to the Council. The Council talks back.**

Open with the number: **a third of council call-centre volume during an event
is people asking what happened to something they already reported.** Every one
of those calls is somebody who helped, and got nothing back. That's the gap.

---

### 2 · The problem — *15s*
> **Information flows out. It doesn't flow back.**

Reports arrive through several unrelated channels and may never reach the
people who can use them. Problem 02's graded wording is that communities *see
that their information has been received* — that's the part everyone skips.

---

### 3 · The loop — *20s*
> **One line in. An answer back.**

One sentence to report. No account, no password. You get a **reference code** —
that's the whole login. It acknowledges itself, so no human has to be free for
that to happen.

**And you can answer back.** Still happening, getting worse, *it's cleared*.
That last one **releases a crew**, and nothing else in the system could ever
tell WCC that.

---

### 4 · Five stages — *15s*
> **Received → Being checked → On the way → Crew on site → Fixed**

"Responding" was doing too much work. A crew driving across town and a crew
already on site with a shovel are wildly different **if you're the one
waiting**. Each stage is a fact with a time on it, not an estimate.

*(This split came off the team's own workflow board.)*

---

### 5 · Evidence stacks — *15s*
> **Five photos of one flooded road = five witnesses**

Most systems collapse duplicates to reduce clutter — that optimises for a
*reader*. A duty officer is deciding whether something is **real**, so
repetition *is* the evidence. The circle gets bigger, and the count is the
signal.

---

### 6 · Two questions — *20s*
> **Are we coming? And roughly when?**

Kept separate on purpose. *"Likely, but not before tomorrow"* is useful.
*"In progress"* is not.

And **"we can't get to this" is a first-class answer**, with a reason. During
a real event it's sometimes the true one — saying it early lets a neighbour
step in instead of everybody waiting on a status that never changes.

---

### 7 · Photos — *15s*
> **The photo already knows where it was taken.**

EXIF GPS places the pin itself — nobody's interacting with a map in the rain.
But that same data is a precise record of where a person was. So we read it,
**show them what we read**, then **strip all metadata** from the published
copy. Reporting a flood must not publish where you live.

---

### 8 · Access cards — *15s*
> **A printed card in a wallet.**

No email, no SMS, no single sign-on — in an emergency those are precisely the
things that fail. Unambiguous alphabet with a check character, so a typo is
rejected **as a typo**. And a card can only ever issue a card **below its own
level**, so a leaked card can never manufacture its own replacement.

---

### 9 · Moderation — *15s*
> **Nothing is ever deleted.**

A flagged message leaves the public feed and a **visible marker stays behind**.
On a public emergency board, moderation that leaves a trace is the difference
between trustworthy and censored.

The board also notices who's consistently useful — scored on **reports WCC
acted on**, not on volume — and a bot can grant *moderator* and nothing more.

---

### 10 · Climate & sustainability — *20s*
> **Correlation, stated as correlation.**

Today's reports against flood-hazard areas WCC has already mapped, plus the
deprivation of the areas carrying the impact. **Never called a trend** — with
six hours of data that would be fiction.

And one map request instead of 300 tile fetches. The thing that survives a
dead network is also the thing that costs least to run.

---

### 11 · Built to survive — *15s*
> **Standard library. Nothing else.**

Zero dependencies. The map is inline SVG from real WCC GeoJSON, so it works
offline. 2,829 Wellington streets shipped with the page, which is why your
location never has to leave your browser. `/api/geojson` means any other
team's map can read ours.

---

### 12 · Close — *15s*
> **See it working.**

It's live at **impact-lab.bitn.cloud** with real NZTA road events and river
gauges. Demo cards are published — **one tap to sign in as WCC** and try the
official side yourself.

Finish on the honest line: *hazard-planning data, not live emergency
information. In an emergency, call 111.*

---

## Speaking notes

- **Don't read the slides.** They're headlines; you're the detail.
- **The three lines that land**, delivered flat:
  - *"Five photos of one flooded road is five witnesses, not four duplicates."*
  - *"On the way and crew on site sound similar right up until you're the one waiting."*
  - *"Posting needs a card, so nobody can put words in Fire and Emergency's mouth. Which felt worth preventing."*
- **If you're running long**, drop slides 7 and 9 — the loop, the two
  questions and the climate signal are the argument.
- **If a demo is possible**, do it live between slides 3 and 4: report
  something, tap a status, watch it change. Three clicks.
