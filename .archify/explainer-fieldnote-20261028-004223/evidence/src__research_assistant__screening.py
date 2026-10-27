from .contracts import Candidate, Screen, UNIVERSE


def screen_companies(companies, screen: Screen):
    candidates = []
    for company in companies:
        margin = next(m.value for m in company.metrics if m.id == "operating_margin")
        sector = UNIVERSE[company.ticker]["sector"]
        if screen.sector != "All" and screen.sector != sector:
            eligibility, reason = "fail", "Sector does not match the requested screen."
        elif margin is None:
            eligibility, reason = "unknown", "Annual operating margin is unavailable; unknown cannot pass."
        elif margin < screen.min_operating_margin:
            eligibility, reason = "fail", "Operating margin is below the required threshold."
        else:
            eligibility, reason = "pass", "Meets the requested sector and operating-margin criteria."
        candidates.append(Candidate(ticker=company.ticker, company=company.company, sector=sector, eligibility=eligibility, reason=reason, operating_margin=margin))
    candidates.sort(key=lambda c: c.ticker)
    for candidate in [c for c in candidates if c.eligibility == "pass"][:screen.limit]:
        candidate.selected = True
    return candidates
