"""Risk Refresh management view.

Two main jobs:
  1. Show staleness — which sectors haven't been refreshed recently
  2. Run Claude refresh on selected sector — show diff → user clicks Approve

Plus an audit log of every change ever proposed / applied / rejected.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from src.agent.risk_refresh import (
    RiskRefreshAgent,
    all_log_entries,
    all_sectors,
    last_refreshed,
    list_proposed,
    mark_sector_refreshed,
    mark_status,
    refresh_batch,
    staleness_report,
)
# (sector lists pulled from risk_refresh.all_sectors() to avoid duplicating logic)


@st.cache_data(ttl=300, show_spinner=False)
def _staleness():
    return staleness_report(max_age_days=30)


@st.cache_resource
def _agent() -> RiskRefreshAgent:
    return RiskRefreshAgent()


def render() -> None:
    st.header("Risk + Catalyst Refresh")
    st.caption("Claude-powered weekly refresh. Reads recent news + policy items, proposes "
               "updates to the structural-risk / catalyst database, you review + approve.")

    agent = _agent()
    if not agent.available:
        st.error("ANTHROPIC_API_KEY missing — add it to `.env` to enable refresh agent.")
        return

    # === Staleness overview ===
    stale = _staleness()
    st.subheader("Refresh status")
    if not stale:
        st.success("✓ All sectors refreshed within last 30 days.")
    else:
        st.warning(f"{len(stale)} sectors need refresh (>30 days old).")
        with st.expander("Show stale sectors", expanded=False):
            st.dataframe(pd.DataFrame(stale), width="stretch", hide_index=True)

    # === BULK REFRESH (one-click for everything) ===
    st.markdown("---")
    st.subheader("Bulk refresh — one click does all sectors")
    st.caption(
        "Iterates through every sector. For each, Claude reads news + policy and either "
        "proposes changes (you'll review below) or marks the sector reviewed-no-changes. "
        "Takes 10-20 minutes total (35 sectors × ~20-30s each). Leave this tab open; safe "
        "to switch tabs and come back."
    )

    cols_bulk = st.columns([2, 1, 1])
    mode = cols_bulk[0].radio(
        "Scope",
        ["Stale sectors only (recommended)", "ALL sectors (force refresh everything)"],
        horizontal=True,
    )
    do_bulk = cols_bulk[1].button("🚀 Refresh batch now", type="primary", width="stretch")
    estimate_cost = cols_bulk[2].caption(
        f"Est cost: ~${0.03 * len(stale if 'Stale' in mode else all_sectors()):.2f} "
        "(Claude tokens)"
    )

    if do_bulk:
        sectors_to_run = ([s["sector"] for s in stale] if "Stale" in mode
                          else all_sectors())
        if not sectors_to_run:
            st.success("Nothing to refresh — all sectors are fresh.")
        else:
            st.info(f"Refreshing {len(sectors_to_run)} sectors. Live progress below…")
            progress = st.progress(0)
            status_box = st.empty()
            results_box = st.container()
            results_table = []
            counts = {"ok": 0, "no_changes": 0, "error": 0, "total_proposals": 0}

            for i, r in enumerate(refresh_batch(sectors_to_run, sleep_between=5)):
                counts[r["status"]] = counts.get(r["status"], 0) + 1
                counts["total_proposals"] += r.get("proposed_count", 0)
                results_table.append(r)

                # Live update progress
                pct = (i + 1) / len(sectors_to_run)
                progress.progress(pct)

                emoji = {"ok": "📝", "no_changes": "✓", "error": "⚠"}.get(r["status"], "·")
                status_box.markdown(
                    f"**{i+1}/{len(sectors_to_run)}** · {emoji} **{r['sector']}** — "
                    f"{r['status']} ({r['proposed_count']} proposed, "
                    f"{r['elapsed_seconds']}s) · "
                    f"_running totals: {counts['ok']} with changes, "
                    f"{counts['no_changes']} no-change, {counts['error']} errors, "
                    f"{counts['total_proposals']} proposals to review_"
                )

            progress.progress(1.0)
            st.success(
                f"✓ Batch complete. **{counts['total_proposals']} proposals** across "
                f"{counts['ok']} sectors awaiting review. "
                f"{counts['no_changes']} sectors had no changes. "
                f"{counts['error']} errored (rerun those individually below)."
            )
            with results_box.expander("Per-sector results", expanded=True):
                st.dataframe(pd.DataFrame(results_table), width="stretch", hide_index=True)
            _staleness.clear()

    # === Single-sector refresh (kept for ad-hoc / error retries) ===
    st.markdown("---")
    st.subheader("Run refresh on a single sector (ad-hoc)")
    all_sec_list = all_sectors()
    cols = st.columns([3, 1])
    selected = cols[0].selectbox("Sector", all_sec_list,
                                 help="Pick a sector. Claude reads recent news + policy "
                                      "and proposes updates.")
    run = cols[1].button("🔄 Refresh", width="stretch")

    if run:
        with st.spinner(f"Claude is analyzing {selected}…"):
            proposed = agent.propose_changes(selected, lookback_days=14)
        if not proposed:
            mark_sector_refreshed(selected)
            st.success(f"No changes proposed for {selected} — entries still relevant.")
            _staleness.clear()
        else:
            st.success(f"{len(proposed)} change(s) proposed for {selected}. Review below.")
        st.rerun()

    # === Proposed changes awaiting approval ===
    st.markdown("---")
    st.subheader("Proposed changes (awaiting approval)")
    proposed_rows = list_proposed()
    if not proposed_rows:
        st.info("No pending proposals. Run a refresh on any sector above.")
    else:
        for row in proposed_rows:
            with st.expander(
                f"**{row['sector']}** — {row['action']} {row['kind']}: "
                f"{row['item'] or '(overall)'}",
                expanded=True,
            ):
                cols = st.columns([3, 1, 1])
                with cols[0]:
                    if row["action"] == "severity_change":
                        st.write(f"**Old severity:** {row['old_value']}  →  "
                                 f"**New severity:** {row['new_value']}")
                    elif row["action"] == "add":
                        st.write(f"**Severity:** {row['new_value']}")
                    elif row["action"] == "retire":
                        st.write("Retire this entry — no longer relevant.")
                    elif row["action"] == "overall_change":
                        st.write(f"**Old overall:** {row['old_value']}  →  "
                                 f"**New overall:** {row['new_value']}")
                    st.write(f"**Reason:** {row['reason']}")
                    st.caption(f"Proposed: {row['proposed_at']}")
                with cols[1]:
                    if st.button("✓ Approve", key=f"a_{row['id']}", width="stretch"):
                        mark_status(row["id"], "approved")
                        # In a future iteration we'd also patch the structural_risks.py
                        # file with the change. For now, "approved" + manual review of
                        # the diff log is the trust-establishment step.
                        st.success("Approved. Manually patch the change into "
                                   "src/data/structural_risks.py to apply.")
                        st.rerun()
                with cols[2]:
                    if st.button("✗ Reject", key=f"r_{row['id']}", width="stretch"):
                        mark_status(row["id"], "rejected")
                        st.info("Rejected.")
                        st.rerun()

    # === Audit log ===
    st.markdown("---")
    st.subheader("Audit log (last 200 entries)")
    entries = all_log_entries(200)
    if entries:
        df = pd.DataFrame(entries)
        display = df[["proposed_at", "sector", "kind", "action", "item",
                      "old_value", "new_value", "status", "reason"]]
        st.dataframe(display, width="stretch", hide_index=True)
    else:
        st.caption("No history yet — runs will populate.")
