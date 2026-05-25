"""Positive catalyst overlay — the upside mirror of structural_risks.py.

Same shape as structural_risks: sector-wide catalysts that lift all peers, plus
company-specific catalysts that single names benefit from disproportionately.

Used to:
  1. Add a `catalyst_bonus` to screen scores (partially offsets risk penalty so we
     don't blindly down-weight a name with a real positive setup).
  2. Inject into Claude prompts so research notes / morning briefs include a "Bull
     Triggers" section that the analyst must explicitly address.

Bonus is intentionally smaller than risk penalty — institutional research bias
should be "limited downside first, then upside". Max bonus ~25 pts vs max
risk penalty ~45 pts.

Last refreshed: 2026-05.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Each entry: {catalyst: short label, strength: 0.0-1.0, detail: 1-line context}

# =========================================================================
# SECTOR-LEVEL CATALYSTS
# =========================================================================

SECTOR_CATALYSTS: Dict[str, Dict[str, Any]] = {

    "IT": {
        "label": "Indian IT Services",
        "overall_strength": 0.4,
        "catalysts": [
            {"catalyst": "US BFSI discretionary tech spend revival post Fed-cuts",
             "strength": 0.6,
             "detail": "Fed easing cycle historically takes 6-9 months to filter into BFSI "
                       "tech budgets; would lift Tier-1 IT growth by 200-400bps."},
            {"catalyst": "GenAI revenue monetization scaling",
             "strength": 0.5,
             "detail": "If Indian IT can convert GenAI productivity into platform / outcome-"
                       "based revenue (not just T&M discount), thesis flips from threat to "
                       "opportunity."},
            {"catalyst": "INR depreciation tailwind",
             "strength": 0.4,
             "detail": "Every 1% INR weakening = ~30-40bps EBITDA margin tailwind."},
            {"catalyst": "Aggressive buybacks across sector",
             "strength": 0.4,
             "detail": "TCS, Wipro, HCL, Infosys all sit on net-cash positions; large "
                       "buybacks would tighten free float and re-rate multiples."},
        ],
    },
    "Software": {"label": "IT alias", "overall_strength": 0.4, "catalysts": []},

    "Banks": {
        "label": "Indian Banks",
        "overall_strength": 0.5,
        "catalysts": [
            {"catalyst": "RBI rate cut cycle — credit demand revival",
             "strength": 0.6,
             "detail": "Each 25bps cut historically lifts credit growth by 100-150bps "
                       "over 6 months; biggest beneficiaries are housing + retail-heavy banks."},
            {"catalyst": "Deposit war easing as SFB / fintech slow down",
             "strength": 0.4,
             "detail": "If aggressive deposit-pricing competitors decelerate, NIM compression "
                       "thesis weakens."},
            {"catalyst": "Corporate capex cycle pickup",
             "strength": 0.5,
             "detail": "Private capex finally turning; corporate loan demand at large banks "
                       "would re-rate the segment."},
            {"catalyst": "PSU bank reform / privatization news flow",
             "strength": 0.4,
             "detail": "Government IBC actions + selective privatization = re-rating "
                       "trigger for PSU bank cohort."},
        ],
    },
    "Finance": {
        "label": "NBFCs",
        "overall_strength": 0.4,
        "catalysts": [
            {"catalyst": "RBI rate cut directly cuts CoF",
             "strength": 0.6,
             "detail": "NBFCs benefit faster than banks on rate cuts (no deposit base "
                       "anchor); spreads expand 30-50bps."},
            {"catalyst": "Risk-weight reversal if consumer loan stress eases",
             "strength": 0.5,
             "detail": "RBI could roll back 125% risk weight if asset quality stabilizes; "
                       "direct earnings boost for Bajaj Finance, SBI Cards."},
        ],
    },
    "Insurance": {
        "label": "Insurance",
        "overall_strength": 0.4,
        "catalysts": [
            {"catalyst": "VNB margin recovery + protection mix",
             "strength": 0.5,
             "detail": "Shift from ULIP to protection products improves margins structurally."},
            {"catalyst": "Health + retail attachment scaling",
             "strength": 0.5,
             "detail": "Bancassurance + digital channels driving retail policy count."},
        ],
    },

    "Pharmaceuticals": {
        "label": "Indian Pharma",
        "overall_strength": 0.5,
        "catalysts": [
            {"catalyst": "Complex generics + injectables pricing power",
             "strength": 0.6,
             "detail": "Complex injectables / inhalers / topicals seeing pricing stability "
                       "vs plain vanilla erosion; higher-margin growth engines."},
            {"catalyst": "Domestic acute + chronic pricing growth",
             "strength": 0.5,
             "detail": "Indian pharma market growing 8-10% on volume + price; chronic "
                       "therapies driving mix."},
            {"catalyst": "China API supply disruption = India pricing power",
             "strength": 0.4,
             "detail": "If China loses sustained API competitiveness, Indian API+CDMO "
                       "players re-rate."},
            {"catalyst": "Specialty / biologics launches scaling",
             "strength": 0.5,
             "detail": "Sun Pharma Ilumya, Dr Reddy biosims could finally crystallize "
                       "specialty pivot."},
        ],
    },
    "Healthcare": {
        "label": "Hospitals / Diagnostics",
        "overall_severity": 0.5,
        "catalysts": [
            {"catalyst": "Medical tourism revival + insurance penetration",
             "strength": 0.5,
             "detail": "ARPOB growth from international patient mix + retail insurance "
                       "growth at 25%+."},
            {"catalyst": "Capacity additions reaching mature occupancy",
             "strength": 0.5,
             "detail": "Apollo, Manipal, Max ramping FY26-27 — mature beds drive EBITDA "
                       "leverage."},
        ],
    },

    "FMCG": {
        "label": "Consumer Staples",
        "overall_strength": 0.5,
        "catalysts": [
            {"catalyst": "Rural recovery — first signs of volume pickup",
             "strength": 0.6,
             "detail": "Normal monsoon + MSP hikes + lower inflation finally lifting "
                       "rural FMCG volumes; multi-quarter tailwind if it holds."},
            {"catalyst": "GST rationalization → 5% slab inclusion",
             "strength": 0.4,
             "detail": "If select FMCG SKUs move to lower GST slab (proposal discussed), "
                       "margin tailwind without volume risk."},
            {"catalyst": "Premium / new-age share for legacy players",
             "strength": 0.5,
             "detail": "Legacy FMCG buying / building D2C brands to defend premium share "
                       "(HUL beauty, ITC FMCG)."},
        ],
    },
    "Consumer Durables": {
        "label": "Consumer Durables",
        "overall_strength": 0.5,
        "catalysts": [
            {"catalyst": "Hot summer + good monsoon = AC/cooler tailwind",
             "strength": 0.6,
             "detail": "Voltas, Blue Star, Havells all benefit if summer extends."},
            {"catalyst": "Wedding season + festive demand",
             "strength": 0.4,
             "detail": "Q3 historically strongest; jewellery, appliances benefit."},
        ],
    },
    "Retailing": {
        "label": "Retailing",
        "overall_strength": 0.4,
        "catalysts": [
            {"catalyst": "Premiumization in apparel + grocery",
             "strength": 0.5,
             "detail": "Trent, Avenue Supermarts seeing premium category growth >25%."},
            {"catalyst": "Festive same-store-growth pickup",
             "strength": 0.4,
             "detail": "Diwali season + wedding demand drive Q3 SSSG."},
        ],
    },

    "Auto": {
        "label": "Auto OEMs",
        "overall_strength": 0.45,
        "catalysts": [
            {"catalyst": "EV transition tailwind for early movers",
             "strength": 0.6,
             "detail": "Tata Motors, M&M leading EV — PLI benefits + green-cess incentives."},
            {"catalyst": "Rural recovery → 2W revival",
             "strength": 0.5,
             "detail": "Hero, Bajaj 2W volumes recover with rural income; high operating "
                       "leverage."},
            {"catalyst": "Premium SUV mix expansion",
             "strength": 0.5,
             "detail": "Mahindra XUV, Maruti Brezza/Grand Vitara, Tata Punch driving mix up."},
            {"catalyst": "Commercial vehicle replacement cycle",
             "strength": 0.4,
             "detail": "BS-VI vehicles aging; CV replacement cycle bottom turning."},
        ],
    },
    "Auto Ancillaries": {
        "label": "Auto Ancillaries",
        "overall_strength": 0.4,
        "catalysts": [
            {"catalyst": "EV content per vehicle rising (battery management, electronics)",
             "strength": 0.5,
             "detail": "EV total electronics content 2-3x ICE; well-positioned ancillaries "
                       "(Sona Comstar, Endurance) benefit."},
            {"catalyst": "Localization of premium components",
             "strength": 0.5,
             "detail": "PLI for auto components driving Indian sourcing share at OEMs."},
        ],
    },

    "Cement": {
        "label": "Cement",
        "overall_strength": 0.5,
        "catalysts": [
            {"catalyst": "Infra capex + housing volumes",
             "strength": 0.6,
             "detail": "Govt infra spending + PMAY housing drive volume growth 6-8%."},
            {"catalyst": "Coal / pet coke cost normalization",
             "strength": 0.5,
             "detail": "If fuel inputs stabilize, margin recovery to historical band."},
            {"catalyst": "Consolidation premium for survivors",
             "strength": 0.5,
             "detail": "Smaller players struggling; UltraTech, Ambuja, Shree benefit from "
                       "Adani-led market discipline if it stabilizes."},
        ],
    },
    "Chemicals": {
        "label": "Specialty Chemicals",
        "overall_strength": 0.4,
        "catalysts": [
            {"catalyst": "China+1 supply chain shift to India",
             "strength": 0.6,
             "detail": "Global MNCs diversifying away from China; Indian specialty chemical "
                       "players win new contracts (PI Industries, SRF, Navin Fluorine)."},
            {"catalyst": "Agrochem cycle revival",
             "strength": 0.4,
             "detail": "Glyphosate / herbicide prices stabilizing; farm income recovery "
                       "lifts demand."},
        ],
    },
    "Steel": {
        "label": "Steel",
        "overall_strength": 0.4,
        "catalysts": [
            {"catalyst": "China property stimulus reviving steel demand",
             "strength": 0.5,
             "detail": "Any meaningful China property stabilization = global steel price "
                       "tailwind."},
            {"catalyst": "Indian infra capex + safeguard duties",
             "strength": 0.5,
             "detail": "Safeguard duty on cheap imports + infra spending support domestic "
                       "pricing."},
        ],
    },
    "Metals": {
        "label": "Non-Ferrous Metals",
        "overall_strength": 0.4,
        "catalysts": [
            {"catalyst": "Copper supercycle from energy transition",
             "strength": 0.6,
             "detail": "EV + grid + renewables = structurally rising copper demand; Hindalco "
                       "Novelis benefits."},
            {"catalyst": "Aluminium tightness from smelter shutdowns",
             "strength": 0.4,
             "detail": "European + Chinese smelter closures support aluminium prices."},
        ],
    },

    "Oil & Gas": {
        "label": "Oil & Gas",
        "overall_strength": 0.4,
        "catalysts": [
            {"catalyst": "City gas distribution + green hydrogen pivots",
             "strength": 0.5,
             "detail": "GAIL, Indraprastha, Mahanagar CGD penetration story intact; gas "
                       "demand structural."},
            {"catalyst": "OMC marketing margins normalizing post-election",
             "strength": 0.5,
             "detail": "Post electoral cycle, fuel price freedom often returns; large "
                       "earnings reset for IOC, BPCL, HPCL."},
            {"catalyst": "Reliance new-energy revenue ramp",
             "strength": 0.5,
             "detail": "Solar PV + battery + electrolyser capex starting commercial "
                       "production FY26-27."},
        ],
    },
    "Power": {
        "label": "Power",
        "overall_severity": 0.5,
        "catalysts": [
            {"catalyst": "Peak power demand growth at 9-10%",
             "strength": 0.6,
             "detail": "India peak demand rising faster than supply; thermal + renewables "
                       "both benefit."},
            {"catalyst": "Discom revival under RDSS scheme",
             "strength": 0.4,
             "detail": "Govt scheme to improve discom finances reduces working capital risk."},
            {"catalyst": "Pump storage + nuclear additions",
             "strength": 0.4,
             "detail": "New capex segments for NTPC, Tata Power; multi-year visibility."},
        ],
    },
    "Utilities": {"label": "Utilities — see Power", "overall_strength": 0.5, "catalysts": []},

    "Capital Goods": {
        "label": "Capital Goods",
        "overall_strength": 0.6,
        "catalysts": [
            {"catalyst": "Private capex cycle finally turning",
             "strength": 0.7,
             "detail": "After decade of underinvestment, private capex orders pickup at "
                       "L&T, ABB, Siemens. Multi-year operating leverage."},
            {"catalyst": "Defence + railways + power T&D capex",
             "strength": 0.6,
             "detail": "Govt defence indigenization, Vande Bharat trains, T&D capex all "
                       "drive multi-year visibility."},
            {"catalyst": "PLI scheme expansion to new sectors",
             "strength": 0.4,
             "detail": "PLI extending to capital goods, components, electronics — capex multiplier."},
        ],
    },
    "Construction": {
        "label": "Construction",
        "overall_strength": 0.5,
        "catalysts": [
            {"catalyst": "Hybrid annuity + EPC mix shift",
             "strength": 0.5,
             "detail": "HAM model reduces working capital strain; ROIC improves."},
            {"catalyst": "Order inflow at multi-year high",
             "strength": 0.5,
             "detail": "L&T, KEC, Larsen orders at record; revenue visibility extending."},
        ],
    },
    "Infrastructure": {"label": "Infra — see Construction", "overall_strength": 0.5, "catalysts": []},
    "Realty": {
        "label": "Realty",
        "overall_strength": 0.5,
        "catalysts": [
            {"catalyst": "Sales velocity at multi-year highs in premium",
             "strength": 0.6,
             "detail": "Top developers (DLF, Lodha, Godrej Properties, Prestige) booking "
                       "1.5-2x prior cycle; pricing power back."},
            {"catalyst": "Commercial REIT yields compressing",
             "strength": 0.4,
             "detail": "Embassy, Mindspace REITs at fair yield; sentiment positive for "
                       "office developers."},
        ],
    },
    "Logistics": {
        "label": "Logistics",
        "overall_strength": 0.4,
        "catalysts": [
            {"catalyst": "Multi-modal infra (DFC, gati shakti) leveraging",
             "strength": 0.5,
             "detail": "Dedicated freight corridor, port-rail-road integration drives "
                       "share of road-to-rail shift."},
            {"catalyst": "E-commerce 3PL growth",
             "strength": 0.4,
             "detail": "Even with captive networks, 3PLs benefit from e-comm volume CAGR."},
        ],
    },

    "Telecom": {
        "label": "Telecom",
        "overall_strength": 0.55,
        "catalysts": [
            {"catalyst": "Tariff hike cycle resumption",
             "strength": 0.7,
             "detail": "Industry needs ARPU at ₹250+ for healthy ROIC; Bharti / Jio drove "
                       "two hikes in FY25; another likely."},
            {"catalyst": "Vi exit or further consolidation",
             "strength": 0.5,
             "detail": "3→2 player would re-rate Bharti and Jio sharply."},
            {"catalyst": "5G + FWA monetization",
             "strength": 0.4,
             "detail": "Fixed wireless access + enterprise 5G slowly building data ARPU."},
        ],
    },
    "Media": {"label": "Media", "overall_strength": 0.2, "catalysts": []},

    # ============ Defence ============
    "Defence": {
        "label": "Defence + Aerospace",
        "overall_strength": 0.7,
        "catalysts": [
            {"catalyst": "Defence capex multi-year ramp + indigenization",
             "strength": 0.8,
             "detail": "Defence budget ~₹6.2L Cr; 75% domestic procurement target = "
                       "multi-year revenue visibility for HAL, BEL, BDL."},
            {"catalyst": "Export market scaling (BrahMos, Tejas, weapon systems)",
             "strength": 0.6,
             "detail": "Defence exports growing 25-30% YoY; geopolitical demand from "
                       "Philippines, Armenia, etc."},
            {"catalyst": "Order book at multi-year highs",
             "strength": 0.7,
             "detail": "HAL ₹1L Cr+, BEL ₹70K Cr+ order books = 3-4x revenue cover."},
            {"catalyst": "Private participation + tier-2 suppliers",
             "strength": 0.5,
             "detail": "Larsen, Tata, Mahindra all building defence verticals; tier-2 "
                       "suppliers benefit."},
        ],
    },

    # ============ Renewable Energy ============
    "Renewable Energy": {
        "label": "Renewables",
        "overall_strength": 0.7,
        "catalysts": [
            {"catalyst": "500 GW renewable target by 2030 — capex multiplier",
             "strength": 0.8,
             "detail": "India needs ~50 GW/yr addition to hit target; equipment + EPC "
                       "+ developers all benefit."},
            {"catalyst": "PLI scheme + ALMM list driving domestic manufacturing",
             "strength": 0.6,
             "detail": "Solar PV PLI + ALMM (approved list of models) creating moat for "
                       "Waaree, Reliance, Adani."},
            {"catalyst": "Energy storage + green hydrogen optionality",
             "strength": 0.6,
             "detail": "Battery storage + electrolysers add 2-3 multiplier on existing "
                       "renewable capex base."},
            {"catalyst": "Falling tariffs improving project ROIC",
             "strength": 0.4,
             "detail": "Module cost decline outpacing tariff cuts; project IRR improving."},
        ],
    },

    # ============ Aviation ============
    "Aviation": {
        "label": "Aviation",
        "overall_strength": 0.5,
        "catalysts": [
            {"catalyst": "Yield discipline as Akasa + Air India compete rationally",
             "strength": 0.6,
             "detail": "Industry has shown pricing discipline post-Go First exit; ATR + "
                       "RASK both improving."},
            {"catalyst": "International travel recovery + India outbound",
             "strength": 0.6,
             "detail": "Outbound Indian travelers 2x pre-COVID; international yield is "
                       "higher margin."},
            {"catalyst": "Airport infrastructure expansion → fleet growth runway",
             "strength": 0.5,
             "detail": "Noida + Mumbai 2 + Goa Mopa + new Bangalore terminals = "
                       "additional slot capacity."},
        ],
    },

    # ============ Hotels ============
    "Hotels": {
        "label": "Hotels",
        "overall_strength": 0.6,
        "catalysts": [
            {"catalyst": "Wedding + leisure travel super-cycle",
             "strength": 0.7,
             "detail": "Indian wedding + leisure spend at structural highs; demand "
                       "ahead of supply through FY27."},
            {"catalyst": "ARR + RevPAR pricing power",
             "strength": 0.6,
             "detail": "Five-star ARR up 15-20% YoY; supply tight in Mumbai/Delhi/Bangalore."},
            {"catalyst": "Managed-only / asset-light expansion improving ROCE",
             "strength": 0.5,
             "detail": "Indian Hotels (Ginger, Vivanta), Lemon Tree, Chalet shifting to "
                       "management contracts."},
        ],
    },

    # ============ Sugar ============
    "Sugar": {
        "label": "Sugar + Ethanol",
        "overall_strength": 0.5,
        "catalysts": [
            {"catalyst": "Ethanol blending target 20% by 2025 — sugar pivot to ethanol",
             "strength": 0.7,
             "detail": "Govt mandate creates structural demand for sugar diversion to "
                       "ethanol; better realizations."},
            {"catalyst": "Sugar export window reopening",
             "strength": 0.5,
             "detail": "Surplus FY26 = export quota likely reopened; international prices "
                       "supportive."},
            {"catalyst": "Power co-generation (bagasse) revenue",
             "strength": 0.4,
             "detail": "Renewable bagasse-based power adds steady cash flow."},
        ],
    },

    # ============ Fertilizers ============
    "Fertilizers": {
        "label": "Fertilizers + Agri",
        "overall_strength": 0.4,
        "catalysts": [
            {"catalyst": "Agri input inflation easing → margin recovery",
             "strength": 0.5,
             "detail": "Phos-acid + ammonia + gas prices normalizing; pass-through margin "
                       "improving."},
            {"catalyst": "Govt push for fortified / specialty fertilizers",
             "strength": 0.5,
             "detail": "Nano-urea, water-soluble fertilizers — higher margin / lower "
                       "subsidy dependence."},
            {"catalyst": "Monsoon-led demand normalization",
             "strength": 0.5,
             "detail": "Normal monsoon FY26 expected; volume tailwind."},
        ],
    },

    # ============ Internet ============
    "Internet": {
        "label": "Internet / E-commerce / Digital",
        "overall_strength": 0.55,
        "catalysts": [
            {"catalyst": "Path to profitability finally materializing (Zomato, Paytm)",
             "strength": 0.7,
             "detail": "Zomato turning PAT-positive; Paytm break-even visible — re-rating "
                       "trigger when sustained."},
            {"catalyst": "Quick-commerce vertical extending to non-food categories",
             "strength": 0.6,
             "detail": "Blinkit BBQ, Zepto Cafe, Instamart pharmacy — TAM expansion."},
            {"catalyst": "AI-led personalization driving conversion + take rates",
             "strength": 0.5,
             "detail": "Better recommendations + retention; lower CAC."},
            {"catalyst": "India consumer-internet TAM CAGR 15-20%",
             "strength": 0.5,
             "detail": "Internet penetration + digital payments + Tier-2/3 e-commerce all "
                       "compounding."},
        ],
    },

    # ============ Textiles ============
    "Textiles": {
        "label": "Textiles",
        "overall_strength": 0.4,
        "catalysts": [
            {"catalyst": "China+1 in apparel sourcing accelerating",
             "strength": 0.6,
             "detail": "Western retailers (Walmart, H&M, Inditex) shifting away from China; "
                       "India share rising."},
            {"catalyst": "PLI for textiles + man-made fibres",
             "strength": 0.5,
             "detail": "₹10K Cr PLI driving capex; backward-integrated players benefit."},
            {"catalyst": "Cotton normalization + duty structure",
             "strength": 0.4,
             "detail": "Import duty changes + global cotton prices stabilizing."},
        ],
    },
}


# =========================================================================
# COMPANY-LEVEL CATALYSTS
# =========================================================================

COMPANY_CATALYSTS: Dict[str, Dict[str, Any]] = {

    # ============ IT ============
    "TCS": {"overall_strength": 0.4, "catalysts": [
        {"catalyst": "Buyback announcement (last in CY23)", "strength": 0.5,
         "detail": "TCS historically returns capital every 18-24 months; buyback would "
                   "tighten free float + re-rate."},
        {"catalyst": "TCV >$10bn quarterly run-rate", "strength": 0.5,
         "detail": "If deal wins re-accelerate, validates AI-led repositioning."},
        {"catalyst": "GenAI revenue disclosure", "strength": 0.5,
         "detail": "First Indian IT to disclose a meaningful GenAI revenue line would "
                   "re-rate the cohort."},
    ]},
    "INFY": {"overall_strength": 0.4, "catalysts": [
        {"catalyst": "FY26 guidance band upgrade", "strength": 0.5,
         "detail": "Two consecutive in-line/beat quarters could trigger guidance raise."},
        {"catalyst": "AI platform monetization (Topaz)", "strength": 0.4,
         "detail": "If Topaz GenAI platform shows traction, valuation re-rate."},
    ]},
    "WIPRO": {"overall_strength": 0.3, "catalysts": [
        {"catalyst": "New CEO turnaround execution", "strength": 0.4,
         "detail": "Stable leadership + simpler operating model could narrow growth gap."},
        {"catalyst": "Aggressive buyback announcement", "strength": 0.4,
         "detail": "Sitting on ~$5bn net cash; large buyback would re-rate."},
    ]},
    "HCLTECH": {"overall_strength": 0.45, "catalysts": [
        {"catalyst": "ER&D segment growing 15-20% — best in class", "strength": 0.6,
         "detail": "Engineering services structurally less AI-disrupted, growing faster."},
        {"catalyst": "Dividend yield support (3-4%)", "strength": 0.4,
         "detail": "Highest payout among Tier-1 IT; downside cushion."},
    ]},

    # ============ Banks ============
    "HDFCBANK": {"overall_strength": 0.5, "catalysts": [
        {"catalyst": "Post-merger funding normalization", "strength": 0.6,
         "detail": "LCR + CoF improvement playing out; NIM bottoming H1 FY26."},
        {"catalyst": "Improving deposit-credit growth gap", "strength": 0.5,
         "detail": "Recent deposit traction starting to close the gap; if sustained, "
                   "earnings re-rate."},
    ]},
    "ICICIBANK": {"overall_strength": 0.6, "catalysts": [
        {"catalyst": "Best execution franchise — consistent compounder", "strength": 0.6,
         "detail": "RoA 2.4%+ vs peers 1.8-2.2%; pricing premium justified."},
        {"catalyst": "Subsidiary monetization (ICICI Pru, AMC, Securities)", "strength": 0.4,
         "detail": "SOTP unlock potential."},
    ]},
    "SBIN": {"overall_strength": 0.5, "catalysts": [
        {"catalyst": "Subsidiary value unlock (SBI Cards, SBI Life)", "strength": 0.5,
         "detail": "Listed subs at premium valuations; SOTP discount narrows."},
        {"catalyst": "Bond yield rally → MTM gains", "strength": 0.4,
         "detail": "Large AFS book benefits if yields fall meaningfully."},
    ]},
    "AXISBANK": {"overall_strength": 0.4, "catalysts": [
        {"catalyst": "Citi customer book monetization", "strength": 0.5,
         "detail": "Citi consumer book cross-sell starting to deliver; revenue uplift "
                   "with limited additional cost."},
    ]},
    "KOTAKBANK": {"overall_strength": 0.4, "catalysts": [
        {"catalyst": "Digital onboarding restrictions lifted", "strength": 0.4,
         "detail": "RBI restrictions lifted; customer acquisition can scale again."},
    ]},
    "BAJFINANCE": {"overall_strength": 0.45, "catalysts": [
        {"catalyst": "Risk weight reversal if asset quality stabilizes", "strength": 0.6,
         "detail": "Direct ROE uplift; could lift earnings 15-20%."},
        {"catalyst": "AUM crossing ₹4 lakh Cr — scale milestone", "strength": 0.4,
         "detail": "Operating leverage from scale; cost-to-income falling."},
    ]},
    "MUTHOOTFIN": {"overall_strength": 0.5, "catalysts": [
        {"catalyst": "Gold price tailwind + branch expansion", "strength": 0.6,
         "detail": "Gold +20% YTD lifts AUM and gold-price-linked income."},
        {"catalyst": "Geographic expansion (non-South India)", "strength": 0.4,
         "detail": "Branch additions in north + east markets driving 18-20% AUM growth."},
    ]},

    # ============ Pharma ============
    "SUNPHARMA": {"overall_strength": 0.45, "catalysts": [
        {"catalyst": "Ilumya (psoriasis) scaling globally",
         "strength": 0.6,
         "detail": "Specialty drug with 30%+ margins; meaningful contribution to FY26 EBITDA."},
        {"catalyst": "Domestic chronic therapy growth 12-14%",
         "strength": 0.5,
         "detail": "India branded business steady compounder; offsets US generics noise."},
    ]},
    "DRREDDY": {"overall_strength": 0.4, "catalysts": [
        {"catalyst": "gRevlimid replacement pipeline (gAffinitor, gPemmetrexed)",
         "strength": 0.5,
         "detail": "Multiple complex generics to plug $500m+ revenue gap."},
        {"catalyst": "Russia / Brazil EM growth",
         "strength": 0.4,
         "detail": "EM markets growing 15-20%; offsets US noise."},
    ]},
    "CIPLA": {"overall_strength": 0.5, "catalysts": [
        {"catalyst": "gAdvair launch (when it finally happens)",
         "strength": 0.7,
         "detail": "$500M+ revenue opportunity; would be largest single launch in years."},
        {"catalyst": "South Africa private-market growth",
         "strength": 0.4,
         "detail": "Cipla Medpro consistently 15-20% growth."},
    ]},
    "DIVISLAB": {"overall_strength": 0.45, "catalysts": [
        {"catalyst": "Custom-synthesis CDMO order pipeline",
         "strength": 0.6,
         "detail": "China+1 driving new MNC contracts; visibility for FY26-27 strong."},
    ]},

    # ============ FMCG ============
    "HINDUNILVR": {"overall_strength": 0.5, "catalysts": [
        {"catalyst": "Rural recovery — first-mover beneficiary",
         "strength": 0.7,
         "detail": "Most rural-exposed FMCG = first-derivative play if rural cycle turns."},
        {"catalyst": "GST rationalization on FMCG",
         "strength": 0.4,
         "detail": "Lower GST slabs being discussed for select FMCG SKUs."},
    ]},
    "ITC": {"overall_strength": 0.4, "catalysts": [
        {"catalyst": "Hotels demerger value crystallization",
         "strength": 0.5,
         "detail": "ITC Hotels separately listed; SOTP discount narrows."},
        {"catalyst": "Cigarette volume stability + price-led growth",
         "strength": 0.5,
         "detail": "5-6% YoY revenue growth on stable volumes + price; predictable cash flow."},
        {"catalyst": "FMCG margin expansion to double-digit",
         "strength": 0.4,
         "detail": "FMCG EBITDA margin 8-9% currently; target 12-14% over 3 years."},
    ]},
    "NESTLEIND": {"overall_strength": 0.4, "catalysts": [
        {"catalyst": "Rural distribution expansion",
         "strength": 0.5,
         "detail": "Distribution depth in Tier 3+ towns driving incremental growth."},
        {"catalyst": "Premium category launches (Nespresso, KitKat variants)",
         "strength": 0.4,
         "detail": "Premiumization helping ASP and margin."},
    ]},
    "BRITANNIA": {"overall_strength": 0.45, "catalysts": [
        {"catalyst": "Rural FMCG cycle turning",
         "strength": 0.6,
         "detail": "Most rural-exposed = biggest beneficiary of rural revival."},
        {"catalyst": "Premium biscuit + adjacency entry (dairy, croissants)",
         "strength": 0.4,
         "detail": "Category expansion adds growth runway."},
    ]},
    "MARICO": {"overall_strength": 0.4, "catalysts": [
        {"catalyst": "Premium hair/personal care launches",
         "strength": 0.4,
         "detail": "Beardo, Plix acquisitions driving premium share."},
        {"catalyst": "Copra price stabilization",
         "strength": 0.5,
         "detail": "If coconut input prices ease, immediate margin tailwind."},
    ]},

    # ============ Auto ============
    "MARUTI": {"overall_strength": 0.4, "catalysts": [
        {"catalyst": "SUV mix improvement + EV launches (FY26-27)",
         "strength": 0.5,
         "detail": "eVitara + first BEV launch; can claw back some EV share."},
        {"catalyst": "Suzuki global EV platform leverage",
         "strength": 0.4,
         "detail": "Shared dev costs with Suzuki; capex efficiency advantage."},
    ]},
    "M&M": {"overall_strength": 0.55, "catalysts": [
        {"catalyst": "SUV market share gains (XUV700, Scorpio-N, Thar)",
         "strength": 0.7,
         "detail": "Mahindra SUV order book 200K+ vehicles; market share consistently rising."},
        {"catalyst": "EV BE5 / XEV9e launches FY26",
         "strength": 0.5,
         "detail": "EV roadmap on track; positioned ahead of Maruti."},
        {"catalyst": "Tractor cycle bottom + farm income revival",
         "strength": 0.5,
         "detail": "If monsoon normal, tractor demand bottoms — high operating leverage."},
    ]},
    "TATAMOTORS": {"overall_strength": 0.5, "catalysts": [
        {"catalyst": "JLR new product cycle (Range Rover EV, Defender EV)",
         "strength": 0.6,
         "detail": "Premium EV pipeline FY26-27; high-margin offering."},
        {"catalyst": "India PV EV leadership (45%+ share)",
         "strength": 0.6,
         "detail": "First-mover advantage in mass-market EV (Nexon, Tigor, Punch EV)."},
        {"catalyst": "Debt reduction continuing",
         "strength": 0.4,
         "detail": "Net debt down from peak; FCF generation strong."},
    ]},
    "BAJAJ-AUTO": {"overall_strength": 0.5, "catalysts": [
        {"catalyst": "Triumph + KTM premium 2W expansion",
         "strength": 0.6,
         "detail": "JV with Triumph + KTM driving premium mix to 25%+."},
        {"catalyst": "Export market recovery (LATAM, Africa)",
         "strength": 0.4,
         "detail": "EM 2W demand recovering; Bajaj has highest export mix."},
    ]},
    "EICHERMOT": {"overall_strength": 0.55, "catalysts": [
        {"catalyst": "Royal Enfield middleweight platform success",
         "strength": 0.7,
         "detail": "Himalayan 450, Shotgun, Super Meteor expanding premium 450cc+ segment."},
        {"catalyst": "Global RE expansion (Europe, Americas)",
         "strength": 0.5,
         "detail": "International volumes growing 30%+ — high margin export."},
    ]},
    "HEROMOTOCO": {"overall_strength": 0.35, "catalysts": [
        {"catalyst": "Rural 2W demand revival",
         "strength": 0.5,
         "detail": "Most rural-skewed; high operating leverage if cycle turns."},
    ]},

    # ============ Cement / Materials ============
    "ULTRATECH": {"overall_strength": 0.55, "catalysts": [
        {"catalyst": "Capacity to 200mt+ by FY27",
         "strength": 0.6,
         "detail": "Largest capacity = largest volume operating leverage."},
        {"catalyst": "Infra capex cycle volume tailwind",
         "strength": 0.5,
         "detail": "Public + private capex drives 6-8% volume growth."},
    ]},
    "GRASIM": {"overall_strength": 0.4, "catalysts": [
        {"catalyst": "Paints venture starting commercial revenue FY26",
         "strength": 0.5,
         "detail": "Birla Opus could capture 5-10% paint market share over 5 years."},
        {"catalyst": "VSF + chemicals normalizing cycle",
         "strength": 0.4,
         "detail": "Commodity bottom; price recovery would lift EBITDA materially."},
    ]},
    "ASIANPAINT": {"overall_strength": 0.3, "catalysts": [
        {"catalyst": "Premiumization in decoratives + global expansion",
         "strength": 0.4,
         "detail": "Premium emulsions + waterproofing growing 15%+."},
        {"catalyst": "Industrial paints (auto) recovery",
         "strength": 0.3,
         "detail": "Auto OEM demand recovery flows to industrial paint segment."},
    ]},

    # ============ Energy ============
    "RELIANCE": {"overall_strength": 0.5, "catalysts": [
        {"catalyst": "Jio IPO / value crystallization",
         "strength": 0.7,
         "detail": "Jio + Retail IPO catalysts could unlock 30-40% SOTP discount."},
        {"catalyst": "New-energy revenue ramp FY26-27",
         "strength": 0.5,
         "detail": "Solar PV, battery, electrolyser commercial production starting."},
        {"catalyst": "Telecom tariff hikes — Jio EBITDA growth",
         "strength": 0.5,
         "detail": "If industry tariff hike happens, Jio biggest beneficiary."},
    ]},
    "ONGC": {"overall_strength": 0.4, "catalysts": [
        {"catalyst": "Krishna-Godavari production ramp",
         "strength": 0.5,
         "detail": "Deep-water KG-DWN-98/2 finally producing; volume growth visibility."},
        {"catalyst": "Higher domestic gas prices",
         "strength": 0.4,
         "detail": "Govt allowed pricing freedom for new fields; positive earnings impact."},
    ]},
    "COALINDIA": {"overall_strength": 0.45, "catalysts": [
        {"catalyst": "FSA reset + e-auction premium",
         "strength": 0.5,
         "detail": "Pricing leverage from tight power-sector demand."},
        {"catalyst": "Dividend yield + buyback potential",
         "strength": 0.5,
         "detail": "High FCF + low capex needs = capital return story."},
    ]},
    "NTPC": {"overall_strength": 0.55, "catalysts": [
        {"catalyst": "NGEL listing — renewable value crystallization",
         "strength": 0.7,
         "detail": "NTPC Green Energy IPO done; sets benchmark for renewable subsidiary value."},
        {"catalyst": "Peak power demand visibility",
         "strength": 0.5,
         "detail": "9-10% peak demand growth = guaranteed PLF; operating leverage."},
    ]},
    "POWERGRID": {"overall_strength": 0.5, "catalysts": [
        {"catalyst": "Transmission capex cycle revival",
         "strength": 0.6,
         "detail": "Renewable evacuation + grid strengthening drives ₹2-2.5L Cr capex over 5y."},
    ]},

    # ============ Industrials / Other ============
    "LT": {"overall_strength": 0.55, "catalysts": [
        {"catalyst": "Order inflow at multi-year highs",
         "strength": 0.7,
         "detail": "FY25 order inflow ₹3L Cr+; book-to-bill near 3x = multi-year visibility."},
        {"catalyst": "Defence + green energy capex multipliers",
         "strength": 0.6,
         "detail": "L&T positioned across defence, hydrogen, renewables EPC."},
    ]},
    "TITAN": {"overall_strength": 0.5, "catalysts": [
        {"catalyst": "Jewellery SSSG + market share gains",
         "strength": 0.6,
         "detail": "Organized jewellery share rising from ~35% to 40%+ over 5 years."},
        {"catalyst": "International expansion (US, UAE)",
         "strength": 0.4,
         "detail": "Tanishq global stores driving incremental growth runway."},
    ]},
    "PIDILITIND": {"overall_strength": 0.45, "catalysts": [
        {"catalyst": "Construction cycle revival → Fevicol volume",
         "strength": 0.5,
         "detail": "RE + infra capex drives core Fevicol demand."},
        {"catalyst": "New-product category expansion (waterproofing, art)",
         "strength": 0.4,
         "detail": "Adjacent categories driving above-market growth."},
    ]},
    "APOLLOHOSP": {"overall_strength": 0.55, "catalysts": [
        {"catalyst": "Mature hospital occupancy + ARPOB growth",
         "strength": 0.6,
         "detail": "Occupancy at 70%+; ARPOB 8-10% YoY = operating leverage."},
        {"catalyst": "AHLL turnaround + Pharmacy 24x7 break-even",
         "strength": 0.5,
         "detail": "Loss-making units approaching break-even; consolidated PAT lift."},
    ]},
    "PAGEIND": {"overall_strength": 0.35, "catalysts": [
        {"catalyst": "Volume growth normalization",
         "strength": 0.4,
         "detail": "After 2y stagnation, channel destocking ending; volume recovery."},
    ]},
}


# =========================================================================
# Public API
# =========================================================================

def sector_catalysts(sector: str) -> Dict[str, Any]:
    if not sector:
        return {"label": "Unknown", "overall_strength": 0.0, "catalysts": []}
    if sector in SECTOR_CATALYSTS:
        return SECTOR_CATALYSTS[sector]
    for k, v in SECTOR_CATALYSTS.items():
        if k.lower() in sector.lower() or sector.lower() in k.lower():
            return v
    return {"label": sector, "overall_strength": 0.0, "catalysts": []}


def company_catalysts(ticker: str) -> Dict[str, Any]:
    if not ticker:
        return {"overall_strength": 0.0, "catalysts": []}
    return COMPANY_CATALYSTS.get(ticker.upper(),
                                 {"overall_strength": 0.0, "catalysts": []})


def catalyst_bonus(sector: str = None, ticker: str = None) -> float:
    """Bonus to add back to score. sector×15 + company×10. Max ~25 pts (half of risk max)."""
    sec = sector_catalysts(sector).get("overall_strength", 0) if sector else 0
    co = company_catalysts(ticker).get("overall_strength", 0) if ticker else 0
    return round(sec * 15 + co * 10, 2)


def catalyst_breakdown(sector: str = None, ticker: str = None) -> Dict[str, float]:
    sec_s = sector_catalysts(sector).get("overall_strength", 0) if sector else 0
    co_s = company_catalysts(ticker).get("overall_strength", 0) if ticker else 0
    return {
        "sector_catalyst_bonus": round(sec_s * 15, 2),
        "company_catalyst_bonus": round(co_s * 10, 2),
        "total_catalyst_bonus": round(sec_s * 15 + co_s * 10, 2),
    }


def catalysts_as_prompt_block(sector: str = None, ticker: str = None) -> str:
    """Format BOTH sector + company catalysts for prompt injection."""
    blocks = []
    if sector:
        e = sector_catalysts(sector)
        if e.get("catalysts"):
            blocks.append(f"**Sector: {e['label']}** (catalyst strength {e['overall_strength']:.2f}/1.0)\n")
            blocks.append("Sector-wide bullish triggers (lift all peers):")
            for c in e["catalysts"]:
                blocks.append(f"- **{c['catalyst']}** (str {c['strength']:.2f}): {c['detail']}")
            blocks.append("")
    if ticker:
        e = company_catalysts(ticker)
        if e.get("catalysts"):
            blocks.append(f"**{ticker.upper()} — name-specific bullish overlay** "
                         f"(strength {e['overall_strength']:.2f}/1.0)\n")
            blocks.append("Triggers specific to this name (in addition to sector):")
            for c in e["catalysts"]:
                blocks.append(f"- **{c['catalyst']}** (str {c['strength']:.2f}): {c['detail']}")
            blocks.append("")
    return "\n".join(blocks) if blocks else "_No curated catalysts on file._"
