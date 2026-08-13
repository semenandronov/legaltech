import fs from 'node:fs'
import {
  buildQuoteSearchCandidates,
  scoreTableRowsForCandidates,
} from '../src/utils/citationHighlight.ts'

const input = JSON.parse(fs.readFileSync('/tmp/xlsx_live_cite_score_in.json', 'utf8'))
const rowTexts = input.row_texts as string[]
const dataRows = input.data_rows as string[]
const results = []
for (const cit of input.citations as Array<{
  key: string
  quote?: string
  quote_anchor?: string
  highlight_targets?: string[]
}>) {
  const candidates = buildQuoteSearchCandidates(
    cit.quote_anchor || cit.quote,
    cit.highlight_targets || [],
  )
  const best = scoreTableRowsForCandidates(rowTexts, candidates)
  results.push({
    key: cit.key,
    picked_data_row: best ? dataRows[best.index] : null,
    hits: best?.hits ?? 0,
    uniqueHits: best?.uniqueHits ?? 0,
    ok: Boolean(best),
  })
}
fs.writeFileSync('/tmp/xlsx_live_cite_score_out.json', JSON.stringify(results, null, 2))
