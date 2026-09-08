# Reconnect catchup checkpoint — 2026-09-07

`SnapshotStream` now serializes connection attachment, intent handling and
fixed-step advancement with one reentrant state lock. The client-map lock
is not held across reconnect callbacks. A returning socket receives one
hero initialization burst; its following 1134/1137 requests are echoed
without a second 1011 burst. An old disconnected socket cannot submit
actions for the first player by falling through identity lookup.

Catchup recreates the measured bootstrap allocations and static actors,
then current structures, jungle actors, lane minions and retained corpses.
Creation precedes position, HP and death updates. EIDs and compact actor
slots are retained. Already completed bootstrap records are not sent again
to that socket when the original timed bootstrap continues. Old resource
deltas, inventory purchases, timed buffs and ready echoes are excluded from
the bootstrap replay.

The socket's single 1011 contains authoritative current/max HP and energy
at the independently decoded offsets. Subsequent records reconstruct gold,
XP, owned inventory instances, learned-skill notifications and remaining
ability/item cooldowns. Pending passive resource credits are tracked per
socket so the next coarse economy flush can subtract the amount already
included in catchup. Hero death uses retained native 1072 attribution and
1075 remaining respawn time, replacing the old misidentified 1067 death.

The same repair integrates native 1096 item use by authenticated inventory
instance, removes its old ability-upgrade interpretation, and removes the
optional 1086 emitter that was incorrectly called a keepalive. Owned item
requests are echoed even when cooldown prevents another activation, as in
the corpus. Lane kills delegate to the director's measured 1072 death and
approximately 3.8-second corpse/removal lifecycle.

Five new tests in `server/test/test_reconnect_state.py` cover creation
ordering and corpses, stable slots, bootstrap/readiness idempotence,
resource/inventory/skill/cooldown output, item ownership and cooldown-time
ACKs, and state-lock exclusion. Together with the skill-handshake, Adagio
production-minion and locomotion checks, 15 tests pass. `git diff --check`
passes apart from line-ending advisories. No commit was made.

This is a reviewable checkpoint, not live-client acceptance. The 122-byte
nonhero HP form is measured in VGR snapshots; live reconnect consumption
still needs the user's own client check. Native XP-to-level/point display,
current buff/channel/projectile presentation, default Flask/Totem instances
that lack authoritative inventory state, and captured-faction HP templates
remain incomplete. Ability timer duration is recomputed from current rank
and cooldown reduction; exact remaining time is restored, but a purchase or
upgrade during that cooldown can make the historical full duration differ.
The five focused tests do not establish all of these visual semantics.

The prior full-duration benchmark passed on its pinned source before these
repairs. Its authored skill-upgrade packet is now corrected from the old
1096 interpretation to native 1078. No new benchmark or live test was run
after the user paused the long-running work; see
`solo-sandbox-performance.md` for the original metrics and source pin.
