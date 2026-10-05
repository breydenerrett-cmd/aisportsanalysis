# Braves at Dodgers, 2026-10-04, version 2: three answers to one frozen request

Preserved 2026-10-05 so the disagreement between the answers can be studied and so the record
shows exactly which answer was published. **Nothing published was changed.** The published answer
(`evidence/analyst_pilot/2026-10-04_ATL-LAD/answer.json`), the ledger row, the usage log and the packet
store are untouched; every file here is a copy or a reference.

All three answers were written by a Claude session (claude-sonnet-5-5) to the same frozen request:
packet `ccef50623366` (full hash in `frozen_inputs_reference.json`), prompt `analyst_prompt_v5`, built
2026-10-04T21:21:24Z.

| File | What it is | Published? |
|---|---|---|
| `attempt1_transcript_record.md` | **PARTIAL.** The answer file for attempt 1 was overwritten by attempt 2, so this is only what the parent session printed from it (checker result, summary text, the call table with selections, prices, books and fair estimates). It is not the answer file and holds no reasons or evidence. Byte copy of the session scratch record, sha256 `b6b7cc65960c34f4753743669a5a42af99e8dde6828f4c965e6cf4acf16dab28`. | No. Rejected by the checker: 14 calls, 12 kept, 2 struck (moneyline, prop_11), for rule violations unrelated to prop_01. |
| `attempt2_published_answer.json` | Byte copy of the published `answer.json` (sha256 `8ba554b3...e317`, identical to the original). Written after attempt 1's four rejection lines were passed back, with nothing else added. | **Yes**, ledger version 2, row hash `1e4e26f8624a5fb9...`. |
| `sample3_unpublished_answer.json` | A third, independent answer to the same request with no rejection lines (sha256 `ca9a1cf9...ef221`). Complete. | No. Never submitted to `pilot publish`. |
| `frozen_request.json` | Byte copy of the request all three answered (67 KB, sha256 `b5e1392c...0843`). | n/a |
| `frozen_inputs_reference.json` | Path and sha256 of the frozen `request.json`, `packet.json` and `prepare.json`, the packet's canonical hash and the ledger row. The packet (80 KB) is referenced, not copied. | n/a |

**Line endings.** The hashes above are of the Windows working-copy bytes (CRLF, `core.autocrlf=true`).
The repository stores these files with LF, so on a Linux checkout the same files hash differently. LF
hashes (the repository form): `attempt2_published_answer.json` and the published `answer.json`
`a8da6b323f2eced8ccd390b2c7c84f24933b2763ca8b6f280c70b77abb2a0a57`; `sample3_unpublished_answer.json`
`420c5d343e94acab8c3354b916c5fc2964e47680430073fa64ba5362f81533f2`; `request.json` / `frozen_request.json`
`46bbc71fdb458ca63f8f8d52bf4a087ae378b3896be7c758181b32db7d01ebdf`; `packet.json`
`211594ce7813bf281b6a9dff50c42dc2357ee17c86ad77924835cf7fa5ac48a4`; `prepare.json`
`05df8922911e7477b867761640bcac26e962627612f8615126430140bf24dc50`. The packet's canonical hash
(`ccef5062...`, over the parsed JSON) does not depend on line endings.

Why this exists: attempt 1 took "Snell strikeouts Under 6.5 at +120" (TAKE_OTHER_SIDE on `prop_01`),
attempt 2 passed on that slot, sample 3 took the Under again. The publication rule that came out of this
(first answer is the candidate, re-answer only on a checker rejection, the latest attempt is the one
published, every attempt kept) is enforced by `pilot check` and `pilot publish` and described in
`docs/AI_ANALYST.md`. The diagnosis is in `docs/research/ANALYST_CONSISTENCY.md`; the per-slot table is
produced by `scripts/analyst_consistency.py`.

The published answer was not selected among these three. It was the second attempt, written after the
first was rejected; sample 3 was drawn as a stability check and was not offered for publication.
