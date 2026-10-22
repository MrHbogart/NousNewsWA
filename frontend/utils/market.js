// Shared formatting for prices, changes and article bodies (auto-imported by Nuxt).

// FX quotes need 4 decimals; indices, gold and crypto read better with 2.
export function formatPrice(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '–'
  const digits = Math.abs(number) < 10 ? 4 : 2
  return number.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function formatChange(pct) {
  const number = Number(pct)
  if (!Number.isFinite(number)) return '–'
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`
}

export function changeDirection(pct) {
  const number = Number(pct)
  if (!Number.isFinite(number) || Math.abs(number) < 0.005) return 'flat'
  return number > 0 ? 'up' : 'down'
}

// First open to last close of a series' candles, in percent.
export function seriesChange(series) {
  const candles = series?.candles || []
  if (!candles.length) return null
  const open = Number(candles[0].open)
  const close = Number(candles[candles.length - 1].close)
  if (!open) return null
  return {
    open,
    close,
    high: Math.max(...candles.map((c) => Number(c.high))),
    low: Math.min(...candles.map((c) => Number(c.low))),
    pct: ((close - open) / open) * 100,
  }
}

// Article bodies use a light structure: '## Heading' lines, '- ' list lines,
// blank lines between paragraphs. Rendered as text nodes, never as HTML.
export function parseArticleBlocks(text) {
  const blocks = []
  for (const chunk of String(text || '').replace(/\r\n/g, '\n').split(/\n{2,}/)) {
    let paragraph = []
    let list = null
    const flush = () => {
      if (paragraph.length) blocks.push({ type: 'p', text: paragraph.join(' ') })
      if (list) blocks.push({ type: 'ul', items: list })
      paragraph = []
      list = null
    }
    for (const raw of chunk.split('\n')) {
      const line = raw.trim()
      if (!line) continue
      const heading = line.match(/^#{1,6}\s+(.*)$/)
      const item = line.match(/^[-*•]\s+(.*)$/)
      if (heading) {
        flush()
        blocks.push({ type: 'h2', text: heading[1].replace(/\*\*/g, '') })
      } else if (item) {
        if (paragraph.length) flush()
        list = list || []
        list.push(item[1].replace(/\*\*/g, ''))
      } else {
        if (list) flush()
        paragraph.push(line.replace(/\*\*/g, ''))
      }
    }
    flush()
  }
  return blocks
}
