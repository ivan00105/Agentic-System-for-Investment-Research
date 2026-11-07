// Beginner view: each finance term a report uses, explained once in plain words.
const TERMS: {term: string; match: RegExp; plain: string}[] = [
  {term: 'Revenue', match: /\brevenues?\b|\bsales\b/i, plain: 'the money a company takes in from selling its products and services, before any costs.'},
  {term: 'Operating income', match: /\boperating income\b/i, plain: 'what is left of revenue after the costs of running the business, before interest and tax.'},
  {term: 'Net income', match: /\bnet income\b|\bearnings\b|\bprofits?\b/i, plain: 'the profit left after every cost, interest and tax.'},
  {term: 'Margin', match: /\bmargins?\b/i, plain: 'a profit as a share of revenue. A 25% operating margin keeps 25 cents of every dollar of sales after running costs.'},
  {term: 'Percentage points (pp)', match: /\bpercentage points?\b|\bpp\b/i, plain: 'the plain difference between two percentages: a margin going from 10% to 12% is up 2 percentage points.'},
  {term: 'Revenue growth', match: /\bgrowth\b|\bgrew\b|\bgrowing\b/i, plain: 'how much revenue rose (or fell) against the year before, as a percentage.'},
  {term: 'Operating cash flow', match: /\boperating cash flow\b|\bcash from operations\b/i, plain: 'the cash the business itself brought in during the year, which can differ from its profit.'},
  {term: 'Capital spending (capex)', match: /\bcapex\b|\bcapital (spending|expenditures?)\b/i, plain: 'money spent on buildings, machines and other long-lived things the business needs.'},
  {term: 'Free cash flow', match: /\bfree cash flow\b|\bFCF\b/i, plain: 'operating cash flow minus capital spending: the cash left that could repay debt, pay dividends or buy back shares.'},
  {term: 'Market cap', match: /\bmarket cap(italisation|italization)?\b|\bmarket value\b/i, plain: 'the value of all the company\'s shares at today\'s price.'},
  {term: 'P/E (price to earnings)', match: /\bP\/E\b|\bprice[- ]to[- ]earnings\b/i, plain: 'market cap divided by yearly net income: how many years of today\'s profit the share price pays for. Higher usually means investors expect growth.'},
  {term: 'P/S (price to sales)', match: /\bP\/S\b|\bprice[- ]to[- ]sales\b/i, plain: 'market cap divided by yearly revenue, useful when profits are small or negative.'},
  {term: 'P/B (price to book)', match: /\bP\/B\b|\bprice[- ]to[- ]book\b/i, plain: 'market cap divided by the accounting value of what shareholders own.'},
  {term: 'FCF yield', match: /\bFCF yield\b|\bfree cash flow yield\b/i, plain: 'free cash flow divided by market cap: the cash the business makes for each dollar of share value.'},
  {term: 'Valuation', match: /\bvaluations?\b|\bvalued\b/i, plain: 'how expensive the shares are compared with what the company earns or sells, usually shown as P/E or P/S.'},
  {term: 'Volatility', match: /\bvolatil(e|ity)\b/i, plain: 'how much the share price jumps around. 30% a year means moves of about that size are normal over a year.'},
  {term: 'Drawdown', match: /\bdrawdowns?\b/i, plain: 'the biggest fall from a high point to a later low. A -40% drawdown means the price once lost 40% from its peak.'},
  {term: 'Beta', match: /\bbeta\b/i, plain: 'how much the share tends to move when the whole market moves: 1 moves with the market, above 1 more, below 1 less.'},
  {term: 'Fiscal year', match: /\bfiscal\b|\bFY ?\d/i, plain: 'a company\'s own accounting year, which often does not end in December (Apple\'s ends in September).'},
  {term: '10-K', match: /\b10-Ks?\b/i, plain: 'the yearly report every US-listed company files with the SEC: audited figures, the business and its risks.'},
  {term: '10-Q', match: /\b10-Qs?\b/i, plain: 'the shorter, unaudited quarterly report filed with the SEC.'},
  {term: '8-K', match: /\b8-Ks?\b/i, plain: 'a short SEC filing about an important event, such as results, a new chief executive or a big deal.'},
  {term: 'SEC', match: /\bSEC\b/, plain: 'the US Securities and Exchange Commission, the regulator that receives company filings.'},
  {term: 'Bull and bear case', match: /\bbull(ish)?\b|\bbear(ish)?\b/i, plain: 'the strongest reasons for (bull) and against (bear) the company, side by side.'},
  {term: 'Adjusted prices', match: /\badjusted (close|prices?)\b/i, plain: 'past prices recalculated for splits and dividends so returns compare fairly. Nobody could actually trade at them.'},
  {term: 'Screen', match: /\bscreen(ed|ing)?\b/i, plain: 'a filter that keeps only the companies meeting stated rules, such as margin above 25%.'},
  {term: 'Survivorship bias', match: /\bsurvivorship\b/i, plain: 'a list of today\'s companies leaves out those that failed or left, so it looks better than history really was.'},
]

export function termsIn(texts: string[]) {
  const text = texts.join('\n')
  return TERMS.filter(t => t.match.test(text))
}

export function Glossary({texts}: {texts: string[]}) {
  const found = termsIn(texts)
  if (!found.length) return null
  return <section className="report-section glossary" aria-labelledby="glossary-title">
    <h2 id="glossary-title">Words used in this report</h2>
    <p className="muted">Each finance term here, explained once in plain words. Switch the detail level to Standard to hide this.</p>
    <dl>{found.map(t => <div key={t.term}><dt>{t.term}</dt><dd>{t.plain}</dd></div>)}</dl>
  </section>
}
