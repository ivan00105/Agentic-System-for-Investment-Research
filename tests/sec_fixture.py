"""Small synthetic accession-specific SEC responses, never live financial evidence."""
import httpx


def source_response(request, payload):
    if "companyfacts" in request.url.path:
        return httpx.Response(200, json=payload)
    revenue = next(f for f in payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"] if f["start"] == "2024-01-01")
    if request.url.path.endswith("-index.htm"):
        base = str(request.url).rsplit("/", 1)[0]
        return httpx.Response(200, text=f'<html>CIK: 0000789019 {revenue["accn"]} Filing Date {revenue["filed"]} Period of Report {revenue["end"]}<table><tr><td>1</td><td>10-K</td><td><a href="{base}/annual.htm">annual.htm</a></td><td>10-K</td></tr></table></html>')
    income = next((f for f in payload["facts"]["us-gaap"].get("OperatingIncomeLoss", {}).get("units", {}).get("USD", []) if f["start"] == revenue["start"]), None)
    def fact(tag, value):
        return f'<ix:nonFraction id="{tag}" name="us-gaap:{tag}" contextRef="annual" unitRef="usd" decimals="0" scale="0">{value}</ix:nonFraction>'
    html = f'''<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
    <ix:nonNumeric name="dei:EntityCentralIndexKey">0000789019</ix:nonNumeric>
    <ix:nonNumeric name="dei:DocumentType">10-K</ix:nonNumeric>
    <ix:nonNumeric name="dei:DocumentPeriodEndDate">{revenue["end"]}</ix:nonNumeric>
    <ix:nonNumeric name="dei:AmendmentFlag">false</ix:nonNumeric>
    <p>SYNTHETIC: consolidated financial statements; accounting principles generally accepted in the United States.</p>
    <xbrli:context id="annual"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000789019</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>{revenue["start"]}</xbrli:startDate><xbrli:endDate>{revenue["end"]}</xbrli:endDate></xbrli:period></xbrli:context>
    <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
    <table><tr><td>Total revenue</td><td>{fact("Revenues", revenue["val"])}</td></tr>
    {"<tr><td>Operating income</td><td>" + fact("OperatingIncomeLoss", income["val"]) + "</td></tr>" if income else ""}</table></html>'''
    return httpx.Response(200, text=html)
