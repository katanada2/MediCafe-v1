# F4: inbound outcomes and delayed archive

Status: draft synthetic contract. F4 implementation remains gated on Astra acceptance of F3 and review/merge of this card with an explicit admission record. This planning draft authorizes no runtime change. Owner: Astra; intended delivery owner: Sol.

## Outcome and boundary

An operator admits synthetic lifecycle and remittance deliveries, reviews their exact attribution, accepts supported facts, and sees conserved financial amounts without duplicate postings. Independently, a fake archive receives immutable item projections with per-item readback. Conflicts, missing attribution, uncertain archive writes and archive lag remain visible across restart and outage.

Lifecycle acknowledgment, payer-reported remittance, accepted financial posting, patient liability and cash settlement are distinct. F4 implements the first three under the bounded fixture below. It does not infer patient responsibility, bank settlement, coverage, clinical coding, real payer interoperability, Medisoft compatibility or production authority transfer. All examples, payloads and diagnostics are public synthetic material.

Claims remains authoritative for approved/sent claim identities and delivery evidence. Outcomes owns inbound attribution, accepted lifecycle facts and the synthetic posting ledger. Records owns patient/encounter/services. The archival module owns immutable projections, execution attempts and independently observed readback; its state never becomes canonical records or financial truth.

## Intake and retained evidence

Extend sources admission to accept bounded application/json for two explicit synthetic namespaces: lifecycle and remittance. Reuse its Artifact/Delivery keys, organization-scoped byte retention and verification rather than inventing an outcomes blob store. F1 CSV/DOCX behavior stays intact. JSON is admitted for outcomes interpretation; the F1 row parser must return a stable unsupported-parser reason for these deliveries rather than pretending they contain patient rows.

Bound each inbound JSON document to 1 MiB and 100 remittance lines. Validate file size before application materialization and cumulatively while reading. Admission validates size/media envelope and retains bytes even if subsequent JSON/schema/attribution checks fail. An admitted delivery is not an accepted outcome. Preserve the same source-key/same-digest replay and changed-bytes conflict semantics as F1.

Outcomes calls a narrow sources query to obtain verified bytes and delivery identity. Every actual interpretation records an immutable terminal InboundAttempt with delivery, interpreter version, reason and times. Successful interpretation stores one immutable InboundCandidate per delivery/version and exact parsed fields; failure stores no partial candidate or accepted facts. Concurrent success creates one candidate; every completed computation has a terminal attempt; true replay creates no additional computation or attempt. Missing/corrupt referenced bytes blocks interpretation and new acceptance, with stable artifact_unavailable. Retained accepted ledger/history is not erased by later source unavailability.

Malformed JSON, duplicate object keys, unsupported keys/schema versions, nonfinite numbers, ambiguous identities, wrong currency and out-of-bound values fail explicitly; do not discard extra populated content silently. Monetary fields are decimal strings validated under the fixture precision, never floats. Keep original bytes and source locators alongside normalized values.

## Synthetic inbound schema

Every document contains schema_version=synthetic-outcomes-v1, kind, sender_id, event_id, delivery_key, intent_id, claim_revision_id, receiver_receipt_id and currency where applicable. Identifiers are exact strings/UUIDs; no name/date/amount fuzzy correlation. sender_id is one of the fixed synthetic senders mapped to the F3 pinned receiver identity/version, not an arbitrary transport address.

Lifecycle contains lifecycle_sequence (positive integer), predecessor_event_id (null only for sequence 1), and status ACK_ACCEPTED or ACK_REJECTED. These acknowledge synthetic processing, not adjudication or payment. A later sequence may correct the earlier acknowledgment only by explicitly naming its predecessor.

Remittance contains a nonempty lines array of distinct ClaimLine IDs from that exact sent revision, each with paid_amount and contractual_adjustment as nonnegative USD strings with at most two fractional digits. At least one amount per supplied line must be positive. Partial line membership is explicit: omitted lines receive no posting. There is no implicit zeroing of previously posted values. event_id identifies this remittance contribution, not a replacement of all earlier contributions. Negative amounts, reversal/supersedes instructions, refunds, other adjustment categories, other currencies and patient-liability fields are unsupported and stay in review with a reason; F4 does not guess their semantics.

The declared stable delivery_key, intent, revision, receipt and sender must all identify one exact F3 delivery with independently verified receiver acceptance. Use claims-owned historical delivery queries, not the current Claim head: a sent older revision remains the attribution target after later service/claim changes. Missing receiver evidence is pending_delivery_evidence. Wrong-organization, contradictory or unmatched references remain in review without accepted lifecycle/posting. This inbound document itself does not fabricate the missing F3 receiver readback.

## Durable identity and conflicts

Use existing UUID/UTC/organization admission and composite PostgreSQL relationships. All new commands and queries require active membership and organization-scoped lookup. Immutable candidates, accepted events, posting batches/entries, acceptance receipts and interpretation attempts reject UPDATE and DELETE through ordinary application SQL.

Retain every admitted source Delivery independently of semantic event identity. Namespace semantic identity by organization, sender_id, kind and event_id. An accepted event binds a canonical semantic digest including all normalized identities, sequence or ordered line content and amounts. The same event through another source delivery with equal semantic digest is duplicate evidence for the same accepted event; it never posts twice. Changed content under that identity creates an immutable conflict record referencing both evidence versions and cannot replace the accepted event. Normalization and canonical digest rules are versioned and deterministic; transport source key and arrival time are not event identity.

For lifecycle also enforce unique organization/sender/intent/lifecycle_sequence. A second event at an occupied sequence is replay only if it represents the same accepted semantic event identity and content; otherwise record conflict. Accept sequence 1 only with null predecessor, and later sequence N only if N-1 is accepted and its event_id matches predecessor_event_id. Out-of-order/missing predecessors remain pending_sequence_gap until explicit reevaluation. Do not infer current lifecycle from file timestamps, receipt order or max arrival ID.

Current lifecycle shows the highest contiguous accepted sequence and any unresolved conflicts/gaps separately. A conflicting event does not overwrite earlier accepted facts, and a prior accepted acknowledgment does not hide an outstanding conflict. Remittance acceptance does not require ACK_ACCEPTED; these are independent evidence families once exact F3 delivery attribution is established.

## Acceptance commands and concurrency

`interpret_inbound(actor, organization, delivery_id, interpreter_version)` produces the attributable candidate/attempt or stable failure. It does not post money. `accept_lifecycle(actor, organization, request_id, candidate_id)` and `post_remittance(actor, organization, request_id, candidate_id)` are explicit operator decisions. Show exact target, evidence and proposed effects before POST. `reevaluate_candidate(actor, organization, candidate_id)` recomputes blockers against current durable evidence without altering immutable parsed fields or automatically posting.

Use outcomes-owned immutable accepted-command receipts with F2 canonical encoding and organization/request UUID uniqueness across command kinds. Bind complete command kind, target candidate and intent, and accepted semantic digest. Same accepted input replays original IDs; a changed candidate/target/input conflicts even if amounts happen to match. Rejected requests have no accepted receipt or partial ledger mutation and may reuse their request UUID. Active membership is required before replay. A different request confirming the same semantic accepted event returns that existing event and its posting IDs; it must not attribute a second financial posting to the new click.

At acceptance, verify source bytes/current candidate attribution and lock in this order: encounter through records query, Claim through claims owner query, then outcomes event/financial rows. F3 dispatch and F2 preparation already lock encounter before Claim; no reverse owner locks. Recheck all mutable evidence/preconditions under locks. Cross-owner reads use narrow queries and no outcomes write updates a Claim approval or F3 attempt. Use uniqueness constraints/savepoints to classify first-row and identical-request races without broken transactions.

Accepted lifecycle event, evidence link and request receipt commit atomically. Remittance acceptance creates its accepted event, complete PostingBatch, all lines and receipt in one transaction. Any invalid/overallocated line rejects the entire proposed posting; no partial success batch. Keep validation blockers distinct from committed accepted facts.

## Bounded financial ledger

One synthetic financial account per exact delivered ClaimRevision and USD. Its original charge is the immutable sum of that revision's selected ClaimLine amounts; it is not recomputed from current Service heads. Create an immutable charge basis per line when first needed, referencing the exact ClaimLine/charge snapshot. Claims and outcomes queries can show the original charge before any remittance without inventing a paid state.

Append typed nonnegative credit entries for PAYER_REPORTED_PAYMENT and CONTRACTUAL_ADJUSTMENT from each accepted remittance event/line. Never mutate a running balance as the sole authority. Derive totals from immutable charge basis and accepted entries. Enforce unique accepted-event/ClaimLine/entry-kind, and each entry's event, claim revision, line, organization and currency must agree. A zero component need not produce a credit row; retain its zero in the accepted event snapshot.

For each line, cumulative payer-reported credits plus contractual adjustments must not exceed the original line charge. The encounter/Claim lock serializes concurrent remittances before checking cumulative limits. Reject overposting atomically with overallocated_line; never clip amounts or silently apply a subset. A pending candidate rejected for this reason remains reviewable with original evidence. Replaying an accepted event does not repeat this calculation as a new contribution.

Display charge, payer-reported credits, adjustments and unallocated residual separately. Residual = original charge - accepted credits - accepted adjustments. It is not automatically patient responsibility, collectible debt, a denial or confirmed cash. A fully credited claim means synthetic charge allocation is complete; it must not display cash settled or patient balance zero as an inferred fact. Currency and Decimal arithmetic follow F2 bounds; no binary floating point or silent rounding.

Reversal, corrected remittance, refund and write-off policies remain explicit unsupported review cases in F4. Unsupported evidence may be retained and classified but cannot create fabricated corrective ledger entries. Later production policy must define them before any relevant cutover.

## Projection capture and canonical independence

The archival module reads published owner queries and creates `ArchiveProjection` for one organization/encounter, with immutable UUID, monotonically increasing version, predecessor, source fingerprint, schema version, exact deterministic JSON bytes/digest and capture actor/time. The projection includes synthetic patient/encounter identity, accepted service revision identities/values, claim revision/line identities, historical delivery evidence, accepted lifecycle and financial totals/entry identities. Omit raw notes, uploaded filenames and credentials. This is a synthetic archival schema, not Medisoft compatibility.

Capture takes the encounter lock and coherent owner snapshots in the same short canonical transaction. F2/F3/F4 state mutations that change projected values must follow that encounter lock protocol. No receiver/archive network call occurs during capture. A versioned fingerprint covers exact accepted head/event/entry identities and values, excluding volatile observation/capture timestamps and queue bookkeeping. Same current fingerprint returns the existing projection; changed fingerprint appends a successor with exact retained bytes. Enforce unique encounter/version and one successor per predecessor. No head rewind or cross-encounter pointer.

`capture_archive_projection(actor, organization, request_id, encounter_id, expected_projection_id)` is an explicit idempotent command using archival-owned accepted receipts. A stale expected head conflicts rather than overwrites newer capture. `queue_archive_projection` atomically creates at most one current work row per immutable projection; repeated requests do not regenerate payloads. Keep capture, queue and delivery status visible separately. An absent projection is not an archived encounter.

Canonical records, claims, remittance acceptance and ledger transactions do not call the archive or require its availability. Archive capture/enqueue is explicit in F4; production scheduling is deferred. Current archive lag compares the latest canonical fingerprint with the newest independently confirmed projection fingerprint. An old projection's successful readback is historical success, not proof that subsequent canonical changes are archived.

## Fake archive, attempts and per-item readback

Run a separate loopback archive process with its own durable PostgreSQL schema/connection. The application writes/reads it only through the archive adapter; tests inspect independent storage. Reuse simple transport utilities if useful, but no shared canonical transaction or direct table writes by the producer. Receiver identity and route are fixed synthetic fixture configuration, not user-supplied endpoints.

The target stores immutable versions under organization/encounter/projection identity, exact received bytes/digest and projection version. Same projection ID/same bytes returns the original receipt. Same ID/different bytes conflicts. Its latest-version pointer only advances; delivering an older version after a newer version cannot demote it. Per-item readback returns exact stored bytes, identity, version and receiver-generated receipt. Verify these against the immutable projection before marking that item confirmed. A batch-level boolean or echoed expected digest is insufficient.

`ArchiveWork` is narrow execution bookkeeping per projection with persisted lease/fencing generation and finite timeouts. `ArchiveAttempt` records exact projection, bytes/digest, destination and possible-write marker committed before I/O; terminal outcomes and later readback observations preserve history. Use the F3 lease discipline: no network transaction lock, no new authorization from a stale fence, and expiry after a possible write remains unknown. An already committed network call may arrive late. The fixture's durable per-projection idempotency permits safe automatic retries of the same exact item/key after readback is inconclusive, bounded to three attempts total before operator attention. Manual retry still uses the same projection identity and cannot clear earlier uncertainty by assigning a new ID.

Batches are execution groupings of 1 through 100 explicit projection IDs, not aggregate business identity. Track outcome/readback separately for every item. A partial batch may confirm some items while others are failed, pending or unknown; never report complete until all requested exact items have verified readback. Repeating a batch reuses the same projections and cannot duplicate target versions or conceal earlier per-item history. Wrong item/version/digest/receiver remains a conflict. Newer canonical state or projections do not erase unresolved older attempts.

An archive outage changes archive work/status only. Operator views show current canonical work, last confirmed projection, current lag and each item's retry/reconciliation reason. Do not infer archive success from a nonempty output directory, local write, HTTP 200 alone, process exit or producer flag.

## Operator surfaces and status precedence

Add scoped inbound worklist, candidate detail/attribution, explicit lifecycle acceptance/remittance posting, lifecycle history, synthetic ledger detail, projection capture and archive item/batch status. Session/CSRF apply to every mutation, including reevaluation if it persists observations; request UUIDs and expected targets survive form errors. Management commands call the same owner commands. No domain admin writes.

Inbound classification uses ordered blockers: artifact_unavailable, malformed_or_unsupported, conflicting_identity_or_content, unmatched_target, pending_delivery_evidence, pending_sequence_gap, overallocated_line, unaccepted. Report all applicable blockers in that order with the first as primary. Accepted historical facts remain visible alongside current availability/conflict alerts; they are never overwritten by a newer failed candidate.

Archive status distinguishes evidence conflict, unknown possible write, pending/failed execution, historically confirmed item and current fingerprint lag. Confirmed old items retain confirmation even if later canonical changes create lag. Missing current capture, pending delivery and unavailable readback are different explanations. Financial views always distinguish remittance-derived credits from cash evidence and unallocated residual from patient liability.

## Acceptance evidence

Run complete F1-F3 suites plus these PostgreSQL-backed F4 scenarios, using independently running receiver/archive processes where relevant and fresh-process durability checks.

1. Admit and interpret each schema; malformed/duplicate-key JSON, oversize/extra data, unsupported semantics, wrong amounts/currency and missing/corrupt bytes produce stable attributable failure without accepted facts or partial ledger state.
2. Same source-key replay/conflict, same semantic event through a new delivery, changed content under existing event ID, identical/different concurrent requests, and wrong candidate request UUID reuse. Exact duplicates never double-post; conflicts remain retained and explained.
3. Exact historical intent/revision/receipt attribution after current claim/service changes; mismatched sender/receipt/line/organization and missing F3 receiver evidence block acceptance. Readback becoming available permits explicit reevaluation, not automatic posting.
4. Out-of-order lifecycle gap, correct predecessor arrival, same-sequence conflict and higher-sequence explicit correction. Current acknowledgment follows contiguous accepted sequence, independently of remittance and without payment inference.
5. Partial remittances over multiple events and line subsets conserve original charge. Duplicate event replay creates no credit; a multi-line event with one overallocated line creates no posting at all. Concurrent distinct events competing for residual cannot overpost.
6. Zero components, maximum amounts, decimal precision, negative/reversal/refund inputs and omitted lines. Display exact charge/credit/adjustment/residual and verify no patient-liability or cash-settlement inference from remittance or zero residual.
7. Direct SQL rejects cross-organization and mismatched event/revision/line/currency references, duplicate posting identity, immutable-history rewrites and projection head rewind. Active membership is enforced on every command/query, including replay; web CSRF and error retention are covered.
8. Restart preserves accepted events, ledger entries and derived totals. Later reparse/new source interpretation cannot rewrite accepted posting. Sensitive synthetic sentinel stays absent from logs/errors and outside authorized evidence views.
9. Capture a consistent projection, replay same fingerprint and capture a changed successor. Exact projected bytes match owner snapshots. Later canonical changes create visible lag without invalidating historical readback.
10. Archive independent readback proves exact item bytes/version/identity. Same ID changed bytes, wrong receiver, stale version, partial batch, acceptance with dropped response and worker/target restart remain per-item attributable.
11. Repeated batch and concurrent workers do not duplicate immutable target versions. Older delayed write cannot replace a newer target head. Expired fences do not grant new writes; uncertain same-key retries use durable target idempotency and stop at the bounded limit.
12. Stop the archive and execute ordinary service/claim review and remittance posting successfully. Preserve queued/unknown archive work, restart the target, reconcile each item and show remaining current lag accurately. Do not claim all items complete from one batch acknowledgment.

Evidence packet includes exact head, resolved versions, executed command/process scenarios, independent target contents/readback, all test results, unrun checks, limitations and a draft PR. No live Medisoft, payer, bank, real patient data or deployment.

## Decisions and remaining production gaps

Proposed synthetic choices: two independent inbound families, exact F3 historical attribution, explicit operator acceptance, contiguous lifecycle sequence, additive bounded remittance contributions, immutable credit ledger, no automatic residual liability, explicit projection capture and idempotent per-item archival readback.

Rejected: deriving payment from acknowledgment, deriving cash from remittance, fuzzy financial matching, applying valid lines from a rejected batch, overwriting accepted postings from latest source, archive as authoritative store, archive outage blocking canonical transactions and batch success without item evidence.

Production gaps remain real inbound schemas/transport, corrections/reversals/COB, opening balances, pricing/coverage, patient responsibility and communications, cash/deposit reconciliation, actual Medisoft mapping, scheduling, retention, identity correction and qualified operational recovery. Completion of F4 must publish a final synthetic acceptance matrix and this gap handoff; it cannot claim a complete production replacement.

After predecessor acceptance and this card's reviewed admission, Sol owns outcomes and archival production seams, with at most one disjoint fixtures/test lane after interfaces settle. No overlapping writers to schema/settings/owner queries. Public synthetic inputs only. Stop at draft PR/evidence for Astra; no merge or production work. Escalate contradictions or two failures of one approach.
