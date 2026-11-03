// Small hand-drawn SVG charts (REFERENCE §10: no chart library). Every value is also in the chart's label for
// screen readers, and the figures come from records the run already saved.
import type { ReactNode } from 'react'
import type { ChartPoint, CompanyChart } from '../../api'

const W = 320, H = 150, TOP = 22, BOTTOM = 26, SIDE = 10
const short = (label: string) => label.replace(' trillion', 'T').replace(' billion', 'B').replace(' million', 'M')
// Only every nth year gets a tick when there are many, so labels never overlap.
const ticked = (i: number, n: number) => n <= 8 || i % Math.ceil(n / 8) === 0 || i === n - 1

function scale(values: number[], fromZero: boolean) {
  const max = Math.max(...values, ...(fromZero ? [0] : [])), min = Math.min(...values, ...(fromZero ? [0] : []))
  const pad = fromZero ? 0 : (max - min) * 0.15 || Math.abs(max) * 0.05 || 1
  const [lo, hi] = [min - pad, max + pad]
  return (v: number) => TOP + (hi - v) / (hi - lo) * (H - TOP - BOTTOM)
}

function Figure({title, label, children}: {title: string; label: string; children: ReactNode}) {
  return <figure className="chart"><figcaption>{title}</figcaption><svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>{children}</svg></figure>
}

export function BarChart({title, points}: {title: string; points: ChartPoint[]}) {
  const y = scale(points.map(p => p.value), true)
  const step = (W - 2 * SIDE) / points.length
  return <Figure title={title} label={`${title}: ${points.map(p => `${p.end} ${p.label}`).join('; ')}`}>
    <line className="axis" x1={SIDE} x2={W - SIDE} y1={y(0)} y2={y(0)} />
    {points.map((p, i) => {
      const x = SIDE + i * step + step * 0.15, width = step * 0.7, top = Math.min(y(p.value), y(0))
      return <g key={p.end}>
        <rect className="bar" x={x} y={top} width={width} height={Math.max(Math.abs(y(p.value) - y(0)), 1)} />
        {points.length <= 8 && <text className="value" x={x + width / 2} y={top - 5}>{short(p.label)}</text>}
        {ticked(i, points.length) && <text className="tick" x={x + width / 2} y={H - 9}>{p.end.slice(0, 4)}</text>}
      </g>
    })}
  </Figure>
}

export function LineChart({title, points}: {title: string; points: ChartPoint[]}) {
  const y = scale(points.map(p => p.value), false)
  const x = (i: number) => points.length === 1 ? W / 2 : SIDE + 14 + i * (W - 2 * SIDE - 28) / (points.length - 1)
  return <Figure title={title} label={`${title}: ${points.map(p => `${p.end} ${p.label}`).join('; ')}`}>
    <polyline className="line" points={points.map((p, i) => `${x(i)},${y(p.value)}`).join(' ')} />
    {points.map((p, i) => <g key={p.end}>
      <circle className="dot" cx={x(i)} cy={y(p.value)} r={3} />
      {points.length <= 8 && <text className="value" x={x(i)} y={y(p.value) - 8}>{p.label}</text>}
      {ticked(i, points.length) && <text className="tick" x={x(i)} y={H - 9}>{p.end.slice(0, 4)}</text>}
    </g>)}
  </Figure>
}

export function PriceChart({ticker, points}: {ticker: string; points: [string, number][]}) {
  const closes = points.map(p => p[1])
  const y = scale(closes, false)
  const x = (i: number) => SIDE + i * (W - 2 * SIDE) / Math.max(points.length - 1, 1)
  const [low, high] = [Math.min(...closes), Math.max(...closes)]
  const [first, last] = [points[0], points[points.length - 1]]
  const money = (v: number) => `$${v.toFixed(2)}`
  return <Figure title={`${ticker} closing price (as traded)`} label={`${ticker} closing price from ${first[0]} (${money(first[1])}) to ${last[0]} (${money(last[1])}); low ${money(low)}, high ${money(high)}`}>
    <polyline className="line" points={points.map((p, i) => `${x(i)},${y(p[1])}`).join(' ')} />
    <text className="value start" x={SIDE} y={12}>high {money(high)} · low {money(low)}</text>
    <text className="value end" x={W - SIDE} y={Math.max(y(last[1]) - 8, 12)}>{money(last[1])}</text>
    <text className="tick start" x={SIDE} y={H - 9}>{first[0]}</text>
    <text className="tick end" x={W - SIDE} y={H - 9}>{last[0]}</text>
  </Figure>
}

export function CompanyCharts({chart, many}: {chart: CompanyChart; many: boolean}) {
  const charts = [
    chart.revenue.length > 0 && <BarChart key="revenue" title="Revenue by fiscal year" points={chart.revenue} />,
    chart.margin.points.length > 0 && <LineChart key="margin" title={`${chart.margin.label} by fiscal year`} points={chart.margin.points} />,
    chart.price && chart.price.points.length > 1 && <PriceChart key="price" ticker={chart.price.ticker ?? 'Share'} points={chart.price.points} />,
  ].filter(Boolean)
  if (!charts.length) return null
  return <div className="chart-row">{many && <h4>{chart.company}</h4>}<div className="charts">{charts}</div></div>
}
