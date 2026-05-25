"""Curated sector + company structural-risk database.

This is **judgment data** (not scraped) — hand-maintained lists of the structural /
disruption headwinds each sector and each major name faces, as of the date below.
Used in two places:

  1. Injected into Claude prompts so research notes and morning briefs MUST address
     these risks in the Bear Thesis section (rather than only looking at financials).
  2. `risk_penalty(ticker)` returns a 0-45 point penalty applied to quant screen rankings
     so backward-looking financial beauty doesn't blind us to forward-looking erosion.

Total penalty = sector_severity × 30 + company_severity × 15.

**Refresh quarterly.** Replace risks as theses play out; add new ones as they emerge.
Last refreshed: 2026-05.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Each entry: {risk: short label, severity: 0.0-1.0, detail: 1-line context}

# =========================================================================
# SECTOR-LEVEL RISKS (applies to every name in the sector)
# =========================================================================

SECTOR_STRUCTURAL_RISKS: Dict[str, Dict[str, Any]] = {

    # ============ IT / Tech Services ============
    "IT": {
        "label": "Indian IT Services",
        "overall_severity": 0.75,
        "risks": [
            {"risk": "GenAI compresses T&M revenue", "severity": 0.8,
             "detail": "Code-gen + agentic AI (Cursor, Claude, Copilot) automates 10-30% of "
                       "routine application maintenance, testing, L1/L2 support — exactly the "
                       "high-volume offshoring base."},
            {"risk": "GCC in-housing reduces TAM", "severity": 0.7,
             "detail": "MNCs aggressively building Global Capability Centers in India; "
                       "captives now do work previously offshored. JPMC, Walmart, Apple "
                       "expanding India HC at 20-30% CAGR."},
            {"risk": "Hyperscaler margin capture", "severity": 0.6,
             "detail": "AWS / Azure / GCP take infrastructure margin; Indian IT relegated "
                       "to lower-margin app development around their stacks."},
            {"risk": "US H-1B visa risk", "severity": 0.5,
             "detail": "Tightening H-1B caps + denial rates inflate onsite delivery costs."},
            {"risk": "BFSI / Retail discretionary budget cuts", "severity": 0.6,
             "detail": "Largest verticals (~50% of revenue); clients deferring discretionary "
                       "tech spend amid macro uncertainty."},
            {"risk": "Historical PE band permanently reset lower", "severity": 0.7,
             "detail": "Sector traded at 25-30x for 15 years on 12-15% INR growth assumption. "
                       "If growth normalizes to 5-8%, fair PE is 16-20x. 'Reverting to mean' "
                       "may anchor to wrong mean."},
        ],
    },
    "Software": {"label": "Indian IT (alias)", "overall_severity": 0.75,
                 "risks": [{"risk": "See IT sector entry", "severity": 0.75, "detail": ""}]},

    # ============ Banks ============
    "Banks": {
        "label": "Indian Private + PSU Banks",
        "overall_severity": 0.55,
        "risks": [
            {"risk": "NIM compression as deposits reprice faster than loans", "severity": 0.7,
             "detail": "SFB / fintech / market-linked competition raising cost of funds while "
                       "RBI rate cuts squeeze loan yields. 20-40 bps NIM compression possible FY26-27."},
            {"risk": "Unsecured lending stress", "severity": 0.6,
             "detail": "Personal loans, credit cards, microfinance showing rising slippages. "
                       "RBI risk weights raised 25%→125%; further tightening possible."},
            {"risk": "Slowing credit growth post FY24 peak", "severity": 0.5,
             "detail": "Credit growth decelerating 20%+ → 12-14%; corporate capex demand muted "
                       "vs household loans saturating."},
            {"risk": "Fintech / UPI commoditizing CASA float income", "severity": 0.4,
             "detail": "Float income compressed; PhonePe, GPay, Paytm have larger txn share "
                       "than any bank."},
            {"risk": "Bond yield duration risk", "severity": 0.4,
             "detail": "AFS bond books vulnerable if yields back up; treasury gains running off."},
        ],
    },
    "Finance": {
        "label": "NBFCs",
        "overall_severity": 0.5,
        "risks": [
            {"risk": "Cost of funds disadvantage vs banks", "severity": 0.6,
             "detail": "NBFCs borrow at 8-10%; banks fund at 6-7%. Structural disadvantage "
                       "compresses spreads when rate cycle turns."},
            {"risk": "RBI tighter risk weights on consumer lending", "severity": 0.6,
             "detail": "Risk weights raised 25%→125% on unsecured. Direct hit to Bajaj Finance, "
                       "Muthoot, SBI Cards."},
            {"risk": "Co-lending dependency", "severity": 0.4,
             "detail": "Many NBFCs rely on bank co-lending; can be withdrawn or tightened."},
            {"risk": "Liquidity risk in non-AAA names", "severity": 0.5,
             "detail": "Post-IL&FS, market funding for sub-AAA NBFCs remains tight; refinancing "
                       "risk in stress."},
        ],
    },
    "Insurance": {
        "label": "Life + General Insurance",
        "overall_severity": 0.35,
        "risks": [
            {"risk": "ULIP tax change FY24 reducing demand", "severity": 0.5,
             "detail": "Removal of LTCG exemption on ULIPs >₹5L premium hit traditional / "
                       "ULIP mix; pivot to protection harder."},
            {"risk": "Regulator pricing pressure on health/motor", "severity": 0.4,
             "detail": "IRDAI rate review on motor third-party, health portability rules "
                       "limit pricing power."},
            {"risk": "Embedded value optics misleading", "severity": 0.4,
             "detail": "VNB margin growth slowing; market re-rating EV multiples lower."},
            {"risk": "Bancassurance commission dependency", "severity": 0.4,
             "detail": "30-50% of distribution via parent banks; if bank refocuses, "
                       "growth suffers."},
        ],
    },

    # ============ Pharma / Healthcare ============
    "Pharmaceuticals": {
        "label": "Indian Pharma",
        "overall_severity": 0.5,
        "risks": [
            {"risk": "US generics price erosion", "severity": 0.7,
             "detail": "5-10% YoY price erosion in plain vanilla generics; channel "
                       "consolidation (CVS, Walgreens) keeps pricing weak."},
            {"risk": "USFDA inspection / 483 risk", "severity": 0.6,
             "detail": "Warning Letters / Import Alerts can shut a plant 12-18 months. Sun, "
                       "Dr Reddy, Aurobindo all had recent observations."},
            {"risk": "Biosimilars eroding biologic revenue", "severity": 0.5,
             "detail": "Specialty drugs off-patent, biosimilar competition compresses "
                       "margin layer Indian pharma was banking on."},
            {"risk": "Domestic NLEM pricing controls", "severity": 0.4,
             "detail": "Indian govt regularly adds new categories to price control; "
                       "reduces pricing power on bestsellers."},
            {"risk": "China API supply chain dependence", "severity": 0.5,
             "detail": "60-70% KSM / intermediates sourced from China; geopolitics / "
                       "production disruption inflates input costs."},
        ],
    },
    "Healthcare": {
        "label": "Hospitals / Diagnostics",
        "overall_severity": 0.4,
        "risks": [
            {"risk": "ARPOB growth ceiling", "severity": 0.4,
             "detail": "Hospital tariffs face affordability ceiling; insurance negotiation "
                       "pressure on private chains."},
            {"risk": "Diagnostic chain price war", "severity": 0.6,
             "detail": "Tata 1mg, PharmEasy, Practo aggressive pricing eroding margins of "
                       "Dr Lal, Metropolis, Thyrocare."},
            {"risk": "PMJAY scheme reimbursement caps", "severity": 0.4,
             "detail": "Govt insurance schemes cap procedure rates; secondary care "
                       "margin pressure."},
            {"risk": "Capacity addition cycle", "severity": 0.3,
             "detail": "Top chains (Apollo, Manipal, Fortis) all in build-out — near-term "
                       "occupancy / ROIC dilution."},
        ],
    },

    # ============ Consumer ============
    "FMCG": {
        "label": "Consumer Staples",
        "overall_severity": 0.5,
        "risks": [
            {"risk": "Rural slowdown — volumes weak for 6+ quarters", "severity": 0.6,
             "detail": "Rural ~35-40% of FMCG revenue; weak monsoon + inflation hitting rural "
                       "wages keeping volume growth low single-digit."},
            {"risk": "Quick-commerce eroding traditional trade margin", "severity": 0.6,
             "detail": "Blinkit / Zepto / Instamart capture impulse purchases at lower "
                       "margins; brand promiscuity rising."},
            {"risk": "D2C brand share gains in premium", "severity": 0.5,
             "detail": "Mamaearth, Sugar, Wow, Bombay Shaving etc. taking share in premium "
                       "personal care / beauty."},
            {"risk": "Premiumization only at top of pyramid", "severity": 0.4,
             "detail": "Mass segment (60-70% of volumes) trading down to regional / unbranded."},
            {"risk": "Raw material volatility (palm oil, crude)", "severity": 0.4,
             "detail": "Key inputs cyclical; FMCG often unable to pass through fast enough."},
        ],
    },
    "Personal Care": {"label": "Personal Care — see FMCG", "overall_severity": 0.5,
                      "risks": [{"risk": "See FMCG", "severity": 0.5, "detail": ""}]},
    "Consumer Durables": {
        "label": "Consumer Durables / Appliances",
        "overall_severity": 0.4,
        "risks": [
            {"risk": "Premium watch / jewellery competition", "severity": 0.4,
             "detail": "International luxury entries (Rolex, Cartier) capturing top-end "
                       "share; Tanishq/Titan moving up to defend."},
            {"risk": "Air-cooling category seasonality + monsoon", "severity": 0.4,
             "detail": "AC/cooler demand highly weather-correlated; volume volatility."},
            {"risk": "E-commerce price compression", "severity": 0.5,
             "detail": "Amazon/Flipkart sales events training consumers to wait for discounts; "
                       "brand pricing power eroding."},
            {"risk": "Chinese imports / smart-home competition", "severity": 0.4,
             "detail": "Xiaomi, OnePlus entering appliances; price-performance disrupts "
                       "domestic premiums."},
        ],
    },
    "Retailing": {
        "label": "Organized Retail",
        "overall_severity": 0.5,
        "risks": [
            {"risk": "Quick-commerce + D2C disruption", "severity": 0.6,
             "detail": "Brick-and-mortar challenged by 10-min delivery + D2C aggregators."},
            {"risk": "Rental cost inflation in metros", "severity": 0.5,
             "detail": "Top-tier mall rents rising 8-15% annually; same-store-margins squeezed."},
            {"risk": "Inventory turn pressure from fast fashion", "severity": 0.5,
             "detail": "Zudio (Trent), Reliance Trends compressing margins of established "
                       "premium apparel players."},
            {"risk": "Reliance Retail aggressive expansion", "severity": 0.5,
             "detail": "Reliance Retail capex creates oversupply in apparel + grocery; "
                       "pricing power industry-wide eroded."},
        ],
    },

    # ============ Auto ============
    "Auto": {
        "label": "Auto OEMs",
        "overall_severity": 0.6,
        "risks": [
            {"risk": "EV transition risk — ICE-heavy OEMs vulnerable", "severity": 0.7,
             "detail": "Hero, Bajaj losing 2W share to Ola, TVS iQube, Ather. Maruti behind "
                       "Tata, Hyundai, MG in 4W EV roadmap. ICE depreciation risk on 2-3y view."},
            {"risk": "Used car / lease competition", "severity": 0.4,
             "detail": "Cars24, Spinny, OLX driving used-car prices down; lengthening "
                       "replacement cycles."},
            {"risk": "Premiumization helping some / hurting others", "severity": 0.4,
             "detail": "Royal Enfield, BMW, Mercedes gaining; mass-market Maruti, Hero "
                       "facing volume pressure."},
            {"risk": "Rising insurance + cost of ownership", "severity": 0.4,
             "detail": "Combined insurance + fuel + maintenance now 12-15% of vehicle cost "
                       "annually — affordability ceiling."},
            {"risk": "Chip shortage cycle + semiconductor margin", "severity": 0.4,
             "detail": "Premium-segment chip allocation drives mix; supply-chain dependency."},
        ],
    },
    "Auto Ancillaries": {
        "label": "Auto Ancillaries",
        "overall_severity": 0.5,
        "risks": [
            {"risk": "EV transition reduces drivetrain content", "severity": 0.7,
             "detail": "EVs have 30% fewer parts; engine / transmission ancillaries "
                       "structurally exposed."},
            {"risk": "Customer concentration", "severity": 0.4,
             "detail": "Top 2-3 OEMs often >50% of revenue; vulnerable to single-customer shifts."},
            {"risk": "EV electronics share migration", "severity": 0.6,
             "detail": "EV BoM shifts to battery/electronics — players like Bosch must "
                       "build new IP or cede content share to Korean/Chinese vendors."},
            {"risk": "RM (steel, aluminium, copper) pass-through lag", "severity": 0.4,
             "detail": "Margin pressure when RM moves faster than annual pricing windows."},
        ],
    },

    # ============ Cement / Materials ============
    "Cement": {
        "label": "Cement",
        "overall_severity": 0.5,
        "risks": [
            {"risk": "Pricing power weakening — consolidation slowed", "severity": 0.6,
             "detail": "Pan-India price hikes failing to stick; Adani entry post-Ambuja/ACC "
                       "keeping pricing competitive."},
            {"risk": "Coal / pet coke cost volatility", "severity": 0.5,
             "detail": "Imported pet coke 30-40% of cost; INR + global coal price moves "
                       "directly hit margins."},
            {"risk": "Freight cost (rail vs road)", "severity": 0.3,
             "detail": "Higher rail freight + diesel keeping logistics cost 20%+ of sales."},
            {"risk": "Real estate / infra demand cyclical", "severity": 0.4,
             "detail": "70%+ demand from housing + infra; cyclical exposure."},
        ],
    },
    "Chemicals": {
        "label": "Specialty Chemicals",
        "overall_severity": 0.45,
        "risks": [
            {"risk": "China dumping in commodity chemicals", "severity": 0.6,
             "detail": "Chinese capacity glut depressing global prices; affects commodity / "
                       "mid-specialty Indian producers."},
            {"risk": "Order book inconsistency in specialty", "severity": 0.4,
             "detail": "Lumpy MNC customer demand; quarterly numbers volatile."},
            {"risk": "Agrochemical farm-income sensitivity", "severity": 0.4,
             "detail": "Glyphosate-class players hit by farm income trough + global glut."},
            {"risk": "Capacity over-build in fluorine chemistry", "severity": 0.5,
             "detail": "Multiple Indian players adding fluorine capacity; if China stays "
                       "competitive, ROIC dilutes."},
        ],
    },
    "Steel": {
        "label": "Steel",
        "overall_severity": 0.5,
        "risks": [
            {"risk": "China steel exports depressing global prices", "severity": 0.7,
             "detail": "China running steel exports at 100mt+/yr; global prices anchored low."},
            {"risk": "Decarbonization capex burden", "severity": 0.5,
             "detail": "Green steel transition requires 10-15B USD per major player by 2030; "
                       "ROIC pressure."},
            {"risk": "Coking coal cost volatility", "severity": 0.5,
             "detail": "Australian coking coal exposure; geopolitics + freight inflate."},
            {"risk": "Domestic infrastructure demand vs export market", "severity": 0.4,
             "detail": "If India infra spend slows + exports stay weak, capacity utilization "
                       "drops below break-even for marginal producers."},
        ],
    },
    "Metals": {
        "label": "Non-Ferrous Metals",
        "overall_severity": 0.5,
        "risks": [
            {"risk": "China stimulus dependency", "severity": 0.6,
             "detail": "Aluminium / copper / zinc prices highly correlated with Chinese real-"
                       "estate / infrastructure activity."},
            {"risk": "Hindalco/Novelis Europe exposure", "severity": 0.4,
             "detail": "Auto-related demand cyclical + carbon transition cost in Europe."},
            {"risk": "Royalty / mining lease cost increases", "severity": 0.4,
             "detail": "State govt royalty hikes + DMF compress operating margin."},
            {"risk": "ESG capex / financing cost rising", "severity": 0.4,
             "detail": "Mining permits longer; ESG-linked debt covenants tightening."},
        ],
    },

    # ============ Energy / Utilities ============
    "Oil & Gas": {
        "label": "Oil & Gas",
        "overall_severity": 0.55,
        "risks": [
            {"risk": "Renewable transition long-term demand erosion", "severity": 0.5,
             "detail": "EV adoption + renewables capping long-term oil demand growth; "
                       "refining margins structurally peaking."},
            {"risk": "Marketing margin caps for OMCs", "severity": 0.7,
             "detail": "Government regularly caps fuel pump prices around elections / high oil; "
                       "volatile policy risk for IOC, BPCL, HPCL."},
            {"risk": "Crude price ceiling from US shale", "severity": 0.4,
             "detail": "Shale economics cap upside; oil-correlated names face capped earnings "
                       "upside cycle."},
            {"risk": "Upstream capex underspend → reserve depletion", "severity": 0.4,
             "detail": "ONGC, Oil India reserves declining; new finds slow."},
        ],
    },
    "Power": {
        "label": "Power Utilities",
        "overall_severity": 0.4,
        "risks": [
            {"risk": "Renewable transition capex burden", "severity": 0.5,
             "detail": "Thermal players must invest in renewables (NTPC 60GW by 2032); "
                       "near-term ROIC dilution."},
            {"risk": "Discom payment delays", "severity": 0.5,
             "detail": "State discoms chronically delayed; working capital + receivable bloat."},
            {"risk": "Coal supply uncertainty + e-auction price", "severity": 0.4,
             "detail": "Linkage coal vs e-auction premium directly hits variable cost of "
                       "thermal IPPs."},
            {"risk": "PPA tariff renegotiation risk", "severity": 0.4,
             "detail": "States periodically renegotiate / cancel high-tariff PPAs."},
        ],
    },
    "Utilities": {"label": "Utilities — see Power", "overall_severity": 0.4, "risks": []},

    # ============ Industrials / Realty ============
    "Capital Goods": {
        "label": "Capital Goods",
        "overall_severity": 0.4,
        "risks": [
            {"risk": "Order book quality — PSU vs private mix", "severity": 0.5,
             "detail": "PSU orders lower margin; private capex order pickup uncertain."},
            {"risk": "Working capital stretch", "severity": 0.4,
             "detail": "Long execution cycles + payment delays inflate WC days."},
            {"risk": "Commodity pass-through lag", "severity": 0.4,
             "detail": "Steel/copper input cost volatility eats margins on fixed-price contracts."},
            {"risk": "Government order concentration", "severity": 0.5,
             "detail": "Defence / railway / power are 40-60% of order book — single-customer "
                       "policy risk."},
        ],
    },
    "Construction": {
        "label": "Construction / Infra EPC",
        "overall_severity": 0.5,
        "risks": [
            {"risk": "Working capital + payment delay (PSU clients)", "severity": 0.6,
             "detail": "NHAI / state PWD delays inflate WC; promoter pledge / debt risk."},
            {"risk": "Bid-margin compression in road EPC", "severity": 0.5,
             "detail": "Aggressive L1 bidding by smaller players compressing project ROIC."},
            {"risk": "Land acquisition + RoW delays", "severity": 0.5,
             "detail": "Project delays beyond 6-12 months compound interest cost + LD penalty."},
            {"risk": "Commodity pass-through risk", "severity": 0.4,
             "detail": "Steel + cement price moves not always passed through in fixed-price "
                       "contracts."},
        ],
    },
    "Infrastructure": {"label": "Infra — see Construction", "overall_severity": 0.5, "risks": []},
    "Realty": {
        "label": "Real Estate",
        "overall_severity": 0.45,
        "risks": [
            {"risk": "Interest-rate sensitivity", "severity": 0.6,
             "detail": "Home loan rates directly impact demand; rate cycle turning is near-term "
                       "tailwind but longer-term risk if rates re-tighten."},
            {"risk": "Inventory build-up cycle risk", "severity": 0.4,
             "detail": "Top metros heading into 18+ months of inventory in select segments."},
            {"risk": "REIT alternative competing for capital", "severity": 0.4,
             "detail": "Commercial REITs offer 7-9% distribution; pulls retail money from "
                       "physical real-estate."},
            {"risk": "Approval cycle + RERA dispute backlog", "severity": 0.4,
             "detail": "Project approvals stretching 18-24 months; cash-flow timing risk."},
        ],
    },
    "Logistics": {
        "label": "Logistics",
        "overall_severity": 0.4,
        "risks": [
            {"risk": "Trucking + diesel cost pass-through", "severity": 0.4,
             "detail": "Driver wage inflation + diesel cost not always passed through to client."},
            {"risk": "E-commerce captive logistics", "severity": 0.5,
             "detail": "Amazon, Flipkart, Meesho building own networks; 3PLs lose share of "
                       "the highest-volume business."},
            {"risk": "Port congestion / global trade shocks", "severity": 0.4,
             "detail": "Red Sea / Panama Canal disruptions add variability."},
            {"risk": "Multi-modal CapEx burden (rail, warehousing)", "severity": 0.4,
             "detail": "Need to invest in DFC + warehousing to stay competitive; ROIC short-term dilutive."},
        ],
    },

    # ============ Telecom / Media ============
    "Telecom": {
        "label": "Telecom",
        "overall_severity": 0.4,
        "risks": [
            {"risk": "Vi survival uncertainty (positive or negative)", "severity": 0.5,
             "detail": "Vi exit = upside for Bharti / Jio (3→2 player). Vi survives = ARPU "
                       "growth limited. Asymmetric."},
            {"risk": "5G monetization slower than expected", "severity": 0.5,
             "detail": "5G capex done; premium pricing not yet stuck; tariff hikes limited."},
            {"risk": "OTT margin compression", "severity": 0.4,
             "detail": "Voice / SMS revenue eroded — WhatsApp / RCS taking share; data ARPU "
                       "must scale to compensate."},
            {"risk": "Spectrum auction reserves outflow", "severity": 0.4,
             "detail": "Periodic spectrum auctions tie up 5-10K Cr/operator; depreciation drag."},
        ],
    },
    "Media": {
        "label": "Media",
        "overall_severity": 0.6,
        "risks": [
            {"risk": "Streaming-led ad migration", "severity": 0.7,
             "detail": "TV ad share losing to digital / OTT permanently; Zee, Sun TV "
                       "structurally pressured."},
            {"risk": "Cord-cutting + DTH subscriber decline", "severity": 0.6,
             "detail": "Pay-TV subscribers declining; subscription revenue base eroding."},
            {"risk": "Content cost inflation", "severity": 0.5,
             "detail": "Sports / movie rights bidding wars; content cost rising faster than "
                       "ad revenue."},
            {"risk": "Regulatory NTO content + price caps", "severity": 0.4,
             "detail": "TRAI tariff orders limit pricing power on bouquet vs a-la-carte."},
        ],
    },

    # ============ Defence & Aerospace ============
    "Defence": {
        "label": "Defence + Aerospace",
        "overall_severity": 0.3,
        "risks": [
            {"risk": "Order execution lag — multi-year delivery cycles", "severity": 0.4,
             "detail": "HAL Tejas, BEL radar deliveries stretched; revenue recognition lumpy."},
            {"risk": "Government concentration — single-customer risk", "severity": 0.5,
             "detail": "MoD is 90%+ of HAL/BEL revenue; budget allocation + policy shifts "
                       "directly hit order book."},
            {"risk": "Export market still nascent", "severity": 0.4,
             "detail": "Defence export target ₹35K Cr by 2025; actual ₹16K Cr — slower ramp "
                       "than promised."},
            {"risk": "Working capital + receivable bloat from MoD", "severity": 0.4,
             "detail": "MoD payment cycles 9-12 months; financing cost compresses ROE."},
            {"risk": "Valuation already pricing strong order pipeline", "severity": 0.5,
             "detail": "HAL, BEL trading at 30-40x earnings — historical band is 15-20x; "
                       "any execution miss = sharp de-rating."},
        ],
    },

    # ============ Renewable Energy ============
    "Renewable Energy": {
        "label": "Renewables (Solar / Wind)",
        "overall_severity": 0.5,
        "risks": [
            {"risk": "Module / cell pricing pressure from China", "severity": 0.6,
             "detail": "Solar module prices dropped 60% in 2 years; squeeze on equipment "
                       "manufacturer margins."},
            {"risk": "Discom PPA payment delays + curtailment", "severity": 0.6,
             "detail": "State discoms slow on renewable PPA payments; curtailment (forced "
                       "shutdowns) eat into PLF."},
            {"risk": "Land + grid evacuation bottlenecks", "severity": 0.5,
             "detail": "GW-scale projects delayed 6-18 months on land/connection issues."},
            {"risk": "PLI execution risk for solar manufacturing", "severity": 0.5,
             "detail": "Reliance, Adani, Tata Power, Waaree all in capex race; oversupply risk "
                       "if all deliver simultaneously."},
            {"risk": "Tariff caps in competitive auctions", "severity": 0.5,
             "detail": "Aggressive bidding at ₹2.5-3/unit makes new projects ROIC-marginal."},
        ],
    },

    # ============ Aviation ============
    "Aviation": {
        "label": "Aviation",
        "overall_severity": 0.5,
        "risks": [
            {"risk": "Crude oil price = 35-40% of operating cost", "severity": 0.7,
             "detail": "ATF cost directly hits margins; INR weakness + crude up = double "
                       "headwind."},
            {"risk": "Yield pressure as supply (new aircraft) returns", "severity": 0.5,
             "detail": "Air India + Akasa + IndiGo deliveries adding capacity; yields under "
                       "pressure FY26-27."},
            {"risk": "Regulatory tariff caps (route-level)", "severity": 0.4,
             "detail": "DGCA / ministry periodically caps fares on peak routes."},
            {"risk": "MRO + maintenance cost inflation", "severity": 0.5,
             "detail": "Pratt & Whitney engine issues (IndiGo grounded 60+ aircraft); "
                       "compensation + capacity loss."},
            {"risk": "Airport charges + slot constraints", "severity": 0.4,
             "detail": "New terminal charges + slot scarcity at Delhi/Mumbai/Bangalore inflate cost."},
        ],
    },

    # ============ Hotels / Hospitality ============
    "Hotels": {
        "label": "Hotels + Hospitality",
        "overall_severity": 0.4,
        "risks": [
            {"risk": "ARR / RevPAR cyclical post-COVID peak", "severity": 0.5,
             "detail": "Post-COVID revenge travel normalizing; FY26 RevPAR growth slowing "
                       "to mid-single-digit."},
            {"risk": "Supply additions in luxury + upper-upscale", "severity": 0.6,
             "detail": "Marriott, Hyatt, IHG aggressive India build-out; ~50K new rooms "
                       "FY26-28."},
            {"risk": "Wage + food cost inflation", "severity": 0.4,
             "detail": "Staff costs 20-25% of revenue; rising wages compress GOP margins."},
            {"risk": "Corporate travel budget cuts in slowdown", "severity": 0.5,
             "detail": "Business travel ~40-50% of revenue at upper-tier hotels; cyclical."},
        ],
    },

    # ============ Sugar / Ethanol ============
    "Sugar": {
        "label": "Sugar + Ethanol",
        "overall_severity": 0.55,
        "risks": [
            {"risk": "Government export caps + cane price (FRP) hikes", "severity": 0.7,
             "detail": "Annual FRP hikes + export bans squeeze margins; political sensitivity "
                       "to sugar prices."},
            {"risk": "Ethanol pricing notification delays", "severity": 0.5,
             "detail": "OMC ethanol procurement price set by govt; periodic delays in "
                       "notification."},
            {"risk": "Cane availability + weather risk", "severity": 0.6,
             "detail": "UP / Maharashtra cane availability fluctuates ±15% YoY on monsoon."},
            {"risk": "Working capital cycle — long cane payment terms", "severity": 0.4,
             "detail": "Cane growers paid over 9-18 months; high finance cost."},
        ],
    },

    # ============ Agri / Fertilizers ============
    "Fertilizers": {
        "label": "Fertilizers + Agri",
        "overall_severity": 0.5,
        "risks": [
            {"risk": "Subsidy payment cycle (NPK, urea)", "severity": 0.6,
             "detail": "Govt subsidy clearing delayed periodically; large working capital "
                       "blockage."},
            {"risk": "Natural gas / phosphate / potash input prices", "severity": 0.6,
             "detail": "Imported phos-acid + potash + gas prices volatile; pass-through "
                       "limited."},
            {"risk": "Nutrient-Based Subsidy (NBS) revisions", "severity": 0.5,
             "detail": "Govt NBS rate revisions can compress margins meaningfully."},
            {"risk": "Erratic monsoon impacting consumption", "severity": 0.5,
             "detail": "Demand directly tracks sowing area; monsoon failures hit volumes."},
        ],
    },

    # ============ Internet / E-commerce / Digital ============
    "Internet": {
        "label": "Internet / E-commerce / Digital",
        "overall_severity": 0.6,
        "risks": [
            {"risk": "Path to profitability still unproven for many", "severity": 0.7,
             "detail": "Zomato, Paytm, Nykaa, Policybazaar still optimizing for unit economics; "
                       "any growth scare → severe de-rating."},
            {"risk": "Quick-commerce burn (Blinkit, Zepto, Instamart)", "severity": 0.6,
             "detail": "Customer acquisition + dark store capex burning $200M+/yr at each player; "
                       "consolidation will determine winners."},
            {"risk": "Payment / fintech regulatory tightening (RBI, NPCI)", "severity": 0.6,
             "detail": "UPI revenue cap, KYC tightening, payment aggregator licensing — "
                       "regulatory unpredictability."},
            {"risk": "PE/VC funding cycles + valuation reset", "severity": 0.5,
             "detail": "Funding winters compress valuations; further pre-IPO names re-rate down."},
            {"risk": "AI-driven commerce search disruption", "severity": 0.4,
             "detail": "ChatGPT / Perplexity changing product discovery; SEO-led traffic at risk."},
        ],
    },

    # ============ Textiles / Apparel ============
    "Textiles": {
        "label": "Textiles + Apparel",
        "overall_severity": 0.5,
        "risks": [
            {"risk": "Cotton price volatility — RM is 40-50% of cost", "severity": 0.6,
             "detail": "MCX cotton swings 20%+ annually; gross margin volatility extreme."},
            {"risk": "Bangladesh / Vietnam competition in apparel exports", "severity": 0.6,
             "detail": "Lower labour costs + zero-duty access to EU; India losing share in "
                       "basics."},
            {"risk": "Working capital stretch in exports", "severity": 0.4,
             "detail": "120-180 day receivables; finance cost compresses margin."},
            {"risk": "Quick-commerce + fast-fashion D2C", "severity": 0.5,
             "detail": "Zudio, Reliance Trends pressuring premium apparel pricing."},
            {"risk": "PLI scheme execution risk", "severity": 0.4,
             "detail": "₹10K Cr PLI for textiles; demand uncertain post-incentive period."},
        ],
    },
}


# =========================================================================
# COMPANY-LEVEL OVERLAYS (specific to each ticker, in addition to sector)
# =========================================================================

COMPANY_STRUCTURAL_RISKS: Dict[str, Dict[str, Any]] = {

    # ============ IT — name-level differentiation ============
    "TCS": {"overall_severity": 0.5, "risks": [
        {"risk": "BFSI concentration ~50% of revenue", "severity": 0.6,
         "detail": "Among top-5 IT, TCS has highest BFSI mix — most exposed to GCC "
                   "migration of JPMC, Walmart, Citi, BAML."},
        {"risk": "BSNL contract roll-off lapping in H2 FY26", "severity": 0.4,
         "detail": "One-off lift from BSNL deal exits; growth optics worsen near-term."},
        {"risk": "Slowest growing top-3 — already de-rated", "severity": 0.5,
         "detail": "Stock down 34% in 1Y; market has partially priced reset but "
                   "no clear catalyst for re-rating above 20x."},
    ]},
    "INFY": {"overall_severity": 0.45, "risks": [
        {"risk": "Consulting + Retail/CPG vertical exposure", "severity": 0.6,
         "detail": "Retail + CPG ~15% of revenue — most discretionary; first to be cut "
                   "in any client tech budget tightening."},
        {"risk": "Aggressive guidance reset risk", "severity": 0.5,
         "detail": "Management has cut FY26 guidance band twice; further reset still possible."},
        {"risk": "Cobalt / GenAI investments — ROIC unproven", "severity": 0.4,
         "detail": "Heavy investment in AI platform / training; payback timeline unclear."},
    ]},
    "WIPRO": {"overall_severity": 0.6, "risks": [
        {"risk": "Slowest growth among top-5 IT — structurally weakest", "severity": 0.7,
         "detail": "CEO transition + 3y of organic growth lagging peers; deal pipeline weakest."},
        {"risk": "Capco acquisition integration drag", "severity": 0.5,
         "detail": "$1.45bn acquisition; consulting integration disappointing on revenue / "
                   "margin synergies."},
        {"risk": "iCS (cloud + digital) revenue volatile", "severity": 0.5,
         "detail": "Discretionary segment more cyclical than peers; FY26 guide reflects this."},
    ]},
    "HCLTECH": {"overall_severity": 0.4, "risks": [
        {"risk": "Engineering services more AI-resistant — relative strength", "severity": 0.3,
         "detail": "ERS segment (~17% revenue) less automatable than IT ops; provides defensive moat."},
        {"risk": "Hyperscaler partnership margin compression", "severity": 0.5,
         "detail": "AWS / Azure deal-share growing but lower margin than legacy IT ops."},
        {"risk": "Mode 1 (IT ops) revenue declining", "severity": 0.5,
         "detail": "Legacy IT outsourcing base shrinking; mode 2/3 growth must accelerate."},
    ]},
    "TECHM": {"overall_severity": 0.55, "risks": [
        {"risk": "Telecom vertical concentration ~40%", "severity": 0.6,
         "detail": "Largest telecom-vertical exposure; 5G capex cycle ending = revenue headwind."},
        {"risk": "BPS margin pressure", "severity": 0.5,
         "detail": "BPS contributes ~25% of revenue at lower margin; mix worsens earnings."},
        {"risk": "Re-rating dependency on Tech Mahindra-Mahindra ecosystem", "severity": 0.4,
         "detail": "Parent group group capex / M&A overhang."},
    ]},
    "LTIM": {"overall_severity": 0.4, "risks": [
        {"risk": "Recent LTI + Mindtree merger integration", "severity": 0.5,
         "detail": "Merger one year in; revenue synergies underwhelming, attrition elevated."},
        {"risk": "BFSI overweight (45%+)", "severity": 0.5,
         "detail": "Largest BFSI mix among Tier-1.5 IT; sensitive to US bank IT budget."},
    ]},

    # ============ Banks — name-level differentiation ============
    "HDFCBANK": {"overall_severity": 0.5, "risks": [
        {"risk": "Post-merger funding drag (HDFC Ltd integration)", "severity": 0.7,
         "detail": "Inherited HDFC Ltd's higher cost of funds; LCR optimization underway "
                   "but margins compressed for next 4-6 quarters."},
        {"risk": "Deposit growth lagging credit growth", "severity": 0.6,
         "detail": "Sub-15% deposit growth vs 18%+ credit growth post-merger; structural "
                   "constraint on lending pace."},
        {"risk": "Loss of premium NIM cohort (mortgage replacements)", "severity": 0.4,
         "detail": "Original HDFC mortgages re-pricing down as repaid; new asset yields lower."},
    ]},
    "ICICIBANK": {"overall_severity": 0.2, "risks": [
        {"risk": "Best-in-class execution — minimal name-specific drag", "severity": 0.2,
         "detail": "Most consistent NIM defense; tech-led ops give margin advantage."},
    ]},
    "SBIN": {"overall_severity": 0.5, "risks": [
        {"risk": "Government directed lending — agri / MSME stress", "severity": 0.6,
         "detail": "Policy / political pressure to lend creates portfolio quality risk."},
        {"risk": "Treasury gains running off as yields stabilize", "severity": 0.5,
         "detail": "FY24-25 treasury bumper gains won't repeat; core PPOP needs to compensate."},
        {"risk": "Subsidiary value crystallization slow", "severity": 0.4,
         "detail": "SBI Cards, SBI Life IPO uplift already priced; further re-rating capped."},
    ]},
    "AXISBANK": {"overall_severity": 0.45, "risks": [
        {"risk": "Citi consumer book integration overhang", "severity": 0.5,
         "detail": "Citi acquisition customer attrition + tech migration costs."},
        {"risk": "Unsecured retail loan mix (~10%)", "severity": 0.6,
         "detail": "Higher unsecured exposure than ICICI/HDFC; vulnerable to RBI risk-weight "
                   "tightening."},
    ]},
    "KOTAKBANK": {"overall_severity": 0.55, "risks": [
        {"risk": "Uday Kotak succession + RBI restrictions", "severity": 0.6,
         "detail": "RBI restrictions on new digital customer additions (lifted 2025 but trust "
                   "deficit lingers); CEO transition execution risk."},
        {"risk": "Highest CASA legacy means worst NIM compression", "severity": 0.6,
         "detail": "60%+ CASA — most exposed to deposit re-pricing; NIM compression most acute."},
    ]},
    "INDUSINDBK": {"overall_severity": 0.7, "risks": [
        {"risk": "Microfinance + derivatives accounting issues", "severity": 0.8,
         "detail": "FY25 derivatives losses + MFI portfolio stress shook investor confidence; "
                   "governance overhang."},
        {"risk": "Below-peer credit growth + NIM pressure", "severity": 0.6,
         "detail": "Worst growth among top private banks 4 quarters running."},
    ]},
    "BAJFINANCE": {"overall_severity": 0.6, "risks": [
        {"risk": "Highest exposure to RBI risk-weight tightening", "severity": 0.8,
         "detail": "Consumer durables financing + personal loans = 40%+ AUM; directly hit "
                   "by 25%→125% risk-weight increase."},
        {"risk": "Customer acquisition slowing post-digital saturation", "severity": 0.5,
         "detail": "85M customers; incremental growth getting harder + costlier."},
        {"risk": "Co-lending arrangement fragility", "severity": 0.4,
         "detail": "Bank co-lending share rising; if banks pull back, AUM growth slows."},
    ]},
    "MUTHOOTFIN": {"overall_severity": 0.4, "risks": [
        {"risk": "Single-collateral concentration (gold)", "severity": 0.5,
         "detail": "Gold price drawdown could trigger margin calls + LTV breaches."},
        {"risk": "Regulatory LTV cap on gold loans", "severity": 0.5,
         "detail": "RBI periodically tightens gold-loan LTV; affects portfolio growth."},
        {"risk": "Bank competition (SBI Gold Loan) intensifying", "severity": 0.4,
         "detail": "Public sector banks pricing gold loans 100-200bps below NBFCs."},
    ]},

    # ============ Pharma — name-level ============
    "SUNPHARMA": {"overall_severity": 0.4, "risks": [
        {"risk": "Halol facility FDA observations recurring", "severity": 0.5,
         "detail": "Plant has been under intermittent FDA scrutiny; further Warning Letter "
                   "would impact $1bn+ revenue."},
        {"risk": "Specialty pipeline (Ilumya, Cequa) needs to scale", "severity": 0.5,
         "detail": "Specialty bet to offset generics erosion; commercialization slower than peers."},
    ]},
    "DRREDDY": {"overall_severity": 0.6, "risks": [
        {"risk": "gRevlimid exclusivity ending FY26", "severity": 0.8,
         "detail": "~$1bn opportunity rolling off; replacements (gNuvigil, biosims) not "
                   "scaling fast enough."},
        {"risk": "Biosimilar pipeline disappointing", "severity": 0.5,
         "detail": "rituximab, pegfilgrastim launches under-delivering on expectations."},
    ]},
    "CIPLA": {"overall_severity": 0.45, "risks": [
        {"risk": "gAdvair launch repeatedly delayed", "severity": 0.6,
         "detail": "Respiratory pipeline ($500M opportunity) launch slipping; FDA hurdles."},
        {"risk": "South Africa / EM market currency risk", "severity": 0.4,
         "detail": "ZAR / EM exposure adds reporting volatility."},
    ]},
    "DIVISLAB": {"overall_severity": 0.55, "risks": [
        {"risk": "API customer concentration (BMS, Sartans)", "severity": 0.6,
         "detail": "Top 2-3 customers >40% of API revenue; contract loss = severe earnings hit."},
        {"risk": "China API competition reviving", "severity": 0.5,
         "detail": "China API players normalizing post-COVID; pricing pressure returning."},
    ]},

    # ============ FMCG — name-level ============
    "HINDUNILVR": {"overall_severity": 0.5, "risks": [
        {"risk": "Mass-market over-exposure — rural stagnation directly hits", "severity": 0.6,
         "detail": "~40% revenue from rural; most exposed to rural FMCG cycle."},
        {"risk": "Beauty + skincare D2C share loss", "severity": 0.6,
         "detail": "Premium beauty (Lakme, Pond's) losing share to Mamaearth, Sugar, "
                   "Nykaa-house brands."},
        {"risk": "Premium tea / coffee margin pressure", "severity": 0.4,
         "detail": "Tea commodity price hike; pricing pass-through limited."},
    ]},
    "ITC": {"overall_severity": 0.5, "risks": [
        {"risk": "Cigarette demand ceiling + tax risk", "severity": 0.6,
         "detail": "85%+ profit from cigarettes; volumes flat-to-declining structurally + "
                   "perennial GST/excise hike risk."},
        {"risk": "Hotels demerger overhang", "severity": 0.4,
         "detail": "ITC Hotels demerger completed but value unlock optics pending."},
        {"risk": "FMCG / paperboard margins thin", "severity": 0.4,
         "detail": "Non-cigarette FMCG profitability 2-5% margins, well below industry."},
        {"risk": "ESG (tobacco) investor avoidance", "severity": 0.4,
         "detail": "International ESG mandates exclude tobacco; long-term FII flow constraint."},
    ]},
    "NESTLEIND": {"overall_severity": 0.5, "risks": [
        {"risk": "Maggi pricing power waning", "severity": 0.5,
         "detail": "Premium price stress; competition from Patanjali, regional players."},
        {"risk": "Baby food category de-growth", "severity": 0.5,
         "detail": "Nan / Cerelac volume growth lowest in years."},
        {"risk": "Parent (Nestle SA) royalty + brand cost", "severity": 0.4,
         "detail": "5%+ royalty to parent eats margin; periodic shareholder vote risk."},
    ]},
    "BRITANNIA": {"overall_severity": 0.5, "risks": [
        {"risk": "Highest rural exposure in FMCG", "severity": 0.6,
         "detail": "65%+ revenue from biscuits, ~45% from rural — most rural-cycle sensitive."},
        {"risk": "Premium biscuit competitive intensity", "severity": 0.5,
         "detail": "Mondelez, Parle premiumizing aggressively; share loss in cookies."},
    ]},
    "DABUR": {"overall_severity": 0.5, "risks": [
        {"risk": "Honey + chyawanprash category volatility", "severity": 0.4,
         "detail": "Ayurveda categories more cyclical post-COVID demand normalization."},
        {"risk": "Patanjali / Baba Ramdev competitive overhang", "severity": 0.5,
         "detail": "Authentic Ayurveda perception erosion vs Patanjali pricing."},
        {"risk": "Real juice + Vatika hair products margin pressure", "severity": 0.4,
         "detail": "Beverage category palm-oil + sugar cost volatile."},
    ]},
    "MARICO": {"overall_severity": 0.45, "risks": [
        {"risk": "Parachute (coconut) margin volatility — copra prices", "severity": 0.5,
         "detail": "Copra is 40% of COGS; cyclical price exposure."},
        {"risk": "Saffola edible oil — slow growth in mature category", "severity": 0.4,
         "detail": "Premium edible oil saturation; new launches needed to drive growth."},
    ]},
    "TATACONSUM": {"overall_severity": 0.3, "risks": [
        {"risk": "Salt / tea consolidation gains plateauing", "severity": 0.4,
         "detail": "Market share gains from Tata Salt + Tata Tea slowing."},
        {"risk": "Starbucks JV economics dilutive", "severity": 0.4,
         "detail": "JV with Starbucks lower margin than core business."},
    ]},

    # ============ Auto — name-level ============
    "MARUTI": {"overall_severity": 0.5, "risks": [
        {"risk": "EV roadmap weakest among top 4W OEMs", "severity": 0.7,
         "detail": "EV mix <3% vs Tata 30%, Hyundai/MG faster; first launch only in 2025."},
        {"risk": "Premium segment share loss", "severity": 0.5,
         "detail": "Brezza/Grand Vitara not fully matching Hyundai Creta scale; mass-market "
                   "Suzuki brand image limits premium pricing."},
        {"risk": "Hybrid technology bet vs pure EV", "severity": 0.4,
         "detail": "Maruti's hybrid pivot may underperform if government tilts EV incentives "
                   "harder."},
    ]},
    "M&M": {"overall_severity": 0.4, "risks": [
        {"risk": "Tractor cycle peak risk — 65%+ market share", "severity": 0.6,
         "detail": "Tractor sales near cyclical peak; below-normal monsoon = sharp decline."},
        {"risk": "EV BE5 / XEV9e capex burn", "severity": 0.4,
         "detail": "INR 30K+ Cr EV capex; ROIC dilution near-term."},
    ]},
    "TATAMOTORS": {"overall_severity": 0.55, "risks": [
        {"risk": "JLR cyclicality + China demand exposure", "severity": 0.7,
         "detail": "60%+ of profits from JLR; China sales softening + UK/EU EV transition risk."},
        {"risk": "India PV competitive intensity", "severity": 0.5,
         "detail": "Hyundai, Kia, MG closing gap in SUV; price competition intensifying."},
    ]},
    "BAJAJ-AUTO": {"overall_severity": 0.4, "risks": [
        {"risk": "2W EV transition — Chetak behind TVS/Ola/Ather", "severity": 0.5,
         "detail": "EV share growing but Chetak market share <8% vs Ola 25%."},
        {"risk": "Export market currency volatility (LATAM, Africa)", "severity": 0.4,
         "detail": "Significant export exposure to volatile EM currencies."},
    ]},
    "HEROMOTOCO": {"overall_severity": 0.55, "risks": [
        {"risk": "Lowest premium mix among 2W OEMs", "severity": 0.6,
         "detail": "85%+ commuter category; below 250cc segment under cyclical + EV pressure."},
        {"risk": "EV strategy late — Vida slow ramp", "severity": 0.6,
         "detail": "Vida launched late; market share <3% in EV vs TVS 20%."},
    ]},
    "EICHERMOT": {"overall_severity": 0.4, "risks": [
        {"risk": "Royal Enfield premium tailwind structural — but middleweight competition rising",
         "severity": 0.5,
         "detail": "Triumph, Harley-Davidson, BMW entering 350-650cc segment; pricing power threat."},
        {"risk": "VECV commercial-vehicle cycle exposure", "severity": 0.4,
         "detail": "JV with Volvo trucks cyclical; freight rate sensitive."},
    ]},

    # ============ Cement / Materials ============
    "ULTRATECH": {"overall_severity": 0.4, "risks": [
        {"risk": "Acquisition appetite stretching balance sheet", "severity": 0.5,
         "detail": "Kesoram + India Cements deals raising leverage; integration risk."},
        {"risk": "Adani entry pressuring east + west markets", "severity": 0.5,
         "detail": "Ambuja + ACC + Sanghi + Penna giving Adani group ~140mt capacity by 2028; "
                   "regional pricing pressure."},
    ]},
    "GRASIM": {"overall_severity": 0.5, "risks": [
        {"risk": "Paints venture (Birla Opus) capex burn", "severity": 0.6,
         "detail": "₹10K Cr paint capex; ROIC dilutive for 3-5 years; Asian Paints/Berger "
                   "incumbent moat strong."},
        {"risk": "VSF (viscose) commodity price volatility", "severity": 0.4,
         "detail": "Commodity nature of VSF + cotton substitution risk."},
    ]},
    "ASIANPAINT": {"overall_severity": 0.55, "risks": [
        {"risk": "Birla Opus entry threat (severe)", "severity": 0.7,
         "detail": "Aditya Birla (Grasim) entering decoratives with ₹10K Cr capex; "
                   "MOAT explicitly being challenged."},
        {"risk": "Premium decoratives pricing power eroding", "severity": 0.5,
         "detail": "Berger, Akzo Nobel premiumizing aggressively; dealer margin pressure."},
        {"risk": "Crude derivative (titanium dioxide) cost", "severity": 0.4,
         "detail": "Key input cost cyclical; pass-through limited."},
    ]},
    "BERGEPAINT": {"overall_severity": 0.5, "risks": [
        {"risk": "Smaller than ASIANPAINT — less scale to absorb Birla entry", "severity": 0.6,
         "detail": "Will face same Birla Opus pressure with smaller balance sheet."},
        {"risk": "Industrial paints (auto) cyclicality", "severity": 0.4,
         "detail": "30% revenue from industrial paints; auto cycle sensitive."},
    ]},
    "PIDILITIND": {"overall_severity": 0.35, "risks": [
        {"risk": "Construction cycle dependency", "severity": 0.5,
         "detail": "Fevicol + construction chemicals tied to RE / infra cycle."},
        {"risk": "VAM (vinyl acetate monomer) cost volatility", "severity": 0.4,
         "detail": "Key raw material cyclical; gross margin volatility."},
    ]},
    "JSWSTEEL": {"overall_severity": 0.5, "risks": [
        {"risk": "Leverage above peers — net debt >₹75K Cr", "severity": 0.6,
         "detail": "Highest leverage in domestic steel; vulnerable in down-cycle."},
        {"risk": "BPSL acquisition integration", "severity": 0.4,
         "detail": "Bhushan Power deal added capacity but at premium; ROIC dilutive."},
    ]},
    "TATASTEEL": {"overall_severity": 0.5, "risks": [
        {"risk": "UK operations losses + restructuring", "severity": 0.7,
         "detail": "UK Port Talbot transition to electric arc furnace; £2bn+ near-term cost."},
        {"risk": "EU carbon border tax + green steel capex", "severity": 0.5,
         "detail": "CBAM compliance + 5+bn EUR green steel transition cost."},
    ]},
    "HINDALCO": {"overall_severity": 0.4, "risks": [
        {"risk": "Novelis (US auto sheet) cyclicality", "severity": 0.6,
         "detail": "Auto demand softening + EU EV slowdown pressure Novelis EBITDA."},
        {"risk": "Aluminium price vs power cost squeeze", "severity": 0.5,
         "detail": "Captive power cost rising; aluminium price not always cooperative."},
    ]},

    # ============ Energy / Power ============
    "RELIANCE": {"overall_severity": 0.45, "risks": [
        {"risk": "Jio ARPU growth dependent on tariff hike cycle", "severity": 0.5,
         "detail": "Telecom is 30% of EBITDA; ARPU progression depends on industry tariff "
                   "discipline (Vi survival is key)."},
        {"risk": "Retail rollout slowing — store-rationalization", "severity": 0.5,
         "detail": "Reliance Retail growth softer than expected; Q3-Q4 EBITDA misses."},
        {"risk": "Petchem cycle bottom — global PE/PP demand soft", "severity": 0.5,
         "detail": "Petchem ~25% of EBITDA; global oversupply + demand weakness."},
        {"risk": "New energy capex execution + ROIC", "severity": 0.5,
         "detail": "$10bn+ new-energy capex with multi-year payback; near-term return drag."},
    ]},
    "ONGC": {"overall_severity": 0.5, "risks": [
        {"risk": "Domestic crude price ceiling", "severity": 0.6,
         "detail": "Government-controlled APM gas + crude pricing; downside protection but "
                   "upside capped."},
        {"risk": "Reserve depletion + exploration disappointments", "severity": 0.5,
         "detail": "Output stagnant; new finds (KG basin) consistently delayed."},
    ]},
    "COALINDIA": {"overall_severity": 0.55, "risks": [
        {"risk": "Long-term renewable substitution", "severity": 0.7,
         "detail": "India renewable target 500GW by 2030 = thermal coal demand peak "
                   "approaching this decade."},
        {"risk": "FY26 production target ambitious — execution risk", "severity": 0.5,
         "detail": "Target 1bn tonnes; weather/labour disruptions create downside."},
        {"risk": "FSA (Fuel Supply Agreement) discount drag", "severity": 0.4,
         "detail": "60%+ volume sold to power sector at discounted FSA price."},
    ]},
    "NTPC": {"overall_severity": 0.3, "risks": [
        {"risk": "60GW renewable capex execution + ROIC", "severity": 0.4,
         "detail": "₹6L Cr capex by 2032; near-term ROIC dilution."},
        {"risk": "Coal cost vs PPA pass-through lag", "severity": 0.4,
         "detail": "Variable cost recovery from discoms delayed; working capital pressure."},
    ]},
    "POWERGRID": {"overall_severity": 0.25, "risks": [
        {"risk": "Regulated returns capped at ~15% RoE", "severity": 0.3,
         "detail": "Tariff regulation limits upside; predictable but no re-rating optionality."},
        {"risk": "TBCB (Tariff Based Competitive Bidding) loss risk", "severity": 0.4,
         "detail": "Increasing TBCB projects = lower margin vs cost-plus."},
    ]},
    "TATAPOWER": {"overall_severity": 0.4, "risks": [
        {"risk": "Mundra UMPP underrecovery + import coal cost", "severity": 0.5,
         "detail": "Imported coal price volatility hits Mundra plant economics."},
        {"risk": "Renewable IPP execution + receivables", "severity": 0.4,
         "detail": "Discom payment delays + capex stretch."},
    ]},

    # ============ Telecom / Media ============
    "BHARTIARTL": {"overall_severity": 0.3, "risks": [
        {"risk": "Africa Bharti volatility (FX, regulation)", "severity": 0.4,
         "detail": "Nigeria devaluation, regulatory pressure in DRC, Kenya."},
        {"risk": "5G monetization slower than capex", "severity": 0.4,
         "detail": "Heavy 5G capex done; ARPU uplift incremental."},
    ]},

    # ============ Capital Goods / Industrials ============
    "LT": {"overall_severity": 0.3, "risks": [
        {"risk": "Order book quality — mix shifting to lower-margin govt projects", "severity": 0.4,
         "detail": "Defence + hydrocarbon orders lower margin than urban infra."},
        {"risk": "LTIM listing arbitrage gone", "severity": 0.3,
         "detail": "Past value-unlock from LTIM done; further sub-listing harder."},
        {"risk": "Heavy engineering margin pressure", "severity": 0.4,
         "detail": "Big-ticket EPC commodity input exposure + execution risk."},
    ]},
    "ADANIENT": {"overall_severity": 0.55, "risks": [
        {"risk": "Adani group governance / leverage overhang", "severity": 0.7,
         "detail": "Hindenburg fallout lingers; group-level debt + collateral concentration risk."},
        {"risk": "New business execution (airports, data centers)", "severity": 0.5,
         "detail": "Multiple capex programs simultaneously; execution + ROIC unproven."},
    ]},

    # ============ Other notable ============
    "TITAN": {"overall_severity": 0.4, "risks": [
        {"risk": "Gold price volatility + jewellery same-store growth", "severity": 0.5,
         "detail": "Tanishq growth highly correlated with gold price + wedding cycle."},
        {"risk": "International competition in premium watches", "severity": 0.4,
         "detail": "Rolex, Cartier, Hublot direct retail entries pressuring premium share."},
        {"risk": "CaratLane integration drag", "severity": 0.3,
         "detail": "Acquisition near book value; growth synergies still being realized."},
    ]},
    "PAGEIND": {"overall_severity": 0.55, "risks": [
        {"risk": "Premium innerwear category saturation", "severity": 0.6,
         "detail": "Jockey premium pricing under pressure; D2C competition (Bummer, "
                   "DaMENSCH) eroding share."},
        {"risk": "Quick-commerce + e-comm pricing transparency", "severity": 0.5,
         "detail": "Brand premium pricing harder when prices comparable instantly."},
    ]},
    "APOLLOHOSP": {"overall_severity": 0.3, "risks": [
        {"risk": "AHLL (Apollo Health & Lifestyle) profitability", "severity": 0.4,
         "detail": "Primary care + diagnostic chain still loss-making."},
        {"risk": "Pharmacy 24x7 execution + competition", "severity": 0.4,
         "detail": "Tata 1mg, PharmEasy aggressive in e-pharmacy."},
    ]},
}


# =========================================================================
# Public API
# =========================================================================

def for_sector(sector: str) -> Dict[str, Any]:
    """Lookup sector risks. Returns the full entry, or low-risk default if unknown."""
    if not sector:
        return {"label": "Unknown sector", "overall_severity": 0.0, "risks": []}
    if sector in SECTOR_STRUCTURAL_RISKS:
        return SECTOR_STRUCTURAL_RISKS[sector]
    for key, entry in SECTOR_STRUCTURAL_RISKS.items():
        if key.lower() in sector.lower() or sector.lower() in key.lower():
            return entry
    return {"label": sector, "overall_severity": 0.0, "risks": []}


def for_company(ticker: str) -> Dict[str, Any]:
    """Lookup company-specific risks. Returns empty if no overlay defined for ticker."""
    if not ticker:
        return {"overall_severity": 0.0, "risks": []}
    return COMPANY_STRUCTURAL_RISKS.get(ticker.upper(),
                                        {"overall_severity": 0.0, "risks": []})


def risk_penalty(sector: str = None, ticker: str = None) -> float:
    """Return total penalty to subtract from quant score.

    Total = (sector_severity × 30) + (company_severity × 15).
    Max possible ~45 pts (sector 30 + company 15). Floor at 0.
    """
    sec = for_sector(sector) if sector else {"overall_severity": 0}
    co = for_company(ticker) if ticker else {"overall_severity": 0}
    penalty = sec.get("overall_severity", 0) * 30 + co.get("overall_severity", 0) * 15
    return round(penalty, 2)


def risks_as_prompt_block(sector: str = None, ticker: str = None) -> str:
    """Format BOTH sector risks AND company-specific risks for injection into Claude prompts."""
    blocks = []
    if sector:
        entry = for_sector(sector)
        if entry.get("risks"):
            blocks.append(f"**Sector: {entry['label']}** "
                         f"(severity {entry['overall_severity']:.2f}/1.0)\n")
            blocks.append("Sector-wide structural risks (apply to all peers):")
            for r in entry["risks"]:
                blocks.append(f"- **{r['risk']}** (sev {r['severity']:.2f}): {r['detail']}")
            blocks.append("")
    if ticker:
        co = for_company(ticker)
        if co.get("risks"):
            blocks.append(f"**{ticker.upper()} — name-specific structural overlay** "
                         f"(severity {co['overall_severity']:.2f}/1.0)\n")
            blocks.append("Issues specific to this name (in addition to sector risks above):")
            for r in co["risks"]:
                blocks.append(f"- **{r['risk']}** (sev {r['severity']:.2f}): {r['detail']}")
            blocks.append("")
    if not blocks:
        return "_No curated structural risks on file for this name._"
    return "\n".join(blocks)


def penalty_breakdown(sector: str = None, ticker: str = None) -> Dict[str, float]:
    """Return the penalty components separately — useful for screen output transparency."""
    sec_sev = for_sector(sector).get("overall_severity", 0) if sector else 0
    co_sev = for_company(ticker).get("overall_severity", 0) if ticker else 0
    return {
        "sector_penalty": round(sec_sev * 30, 2),
        "company_penalty": round(co_sev * 15, 2),
        "total_penalty": round(sec_sev * 30 + co_sev * 15, 2),
    }
