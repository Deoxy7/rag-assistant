"""Streamlit demo UI: ask a question, watch the answer stream, open each citation on its PDF page.

    make ui            # needs `make serve` running (RAG_API_URL, default http://127.0.0.1:8000)

Streamlit reruns this whole script on every interaction, top to bottom. So
anything that must survive a click (the last answer, its sources) lives in
st.session_state, and anything slow and repeatable (the document list, page
images) is cached with st.cache_data.
"""

import html

import streamlit as st

from ui import results
from ui.client import APIError, Client

st.set_page_config(page_title="10-K RAG assistant", page_icon="📄", layout="wide")


@st.cache_resource
def client() -> Client:
    return Client()


@st.cache_data(ttl=300, show_spinner=False)
def documents() -> list[dict]:
    return client().documents()


@st.cache_data(max_entries=64, show_spinner=False)
def page_image(chunk_id: int, page: int) -> bytes:
    return client().page_png(chunk_id, page)


def safe_markdown(text: str) -> str:
    """The API already strips links and images; escaping "![" and raw HTML here is the second layer
    (Streamlit renders markdown, and a rendered image would fetch its URL)."""
    # "$" is escaped too: Streamlit would read "$23.6 … $16.4" as LaTeX math.
    return html.escape(text, quote=False).replace("![", "!\\[").replace("$", "\\$")


# --- sidebar: what to search --------------------------------------------------------------------

with st.sidebar:
    st.header("Documents")
    try:
        docs = documents()
    except Exception as exc:          # API down: say so instead of a traceback
        st.error(f"API not reachable at {client().base_url}: {exc}\n\nStart it with `make serve`.")
        st.stop()
    companies = sorted({d["company"] for d in docs})
    years = sorted({d["fiscal_year"] for d in docs})
    picked_companies = st.multiselect("Companies", companies, placeholder="All companies")
    picked_years = st.multiselect("Fiscal years", years, placeholder="All years")
    k = st.slider("Chunks to retrieve (k)", 1, 20, 10)
    shown = [d for d in docs if (not picked_companies or d["company"] in picked_companies)
             and (not picked_years or d["fiscal_year"] in picked_years)]
    st.caption(f"Searching {len(shown)} of {len(docs)} filings · {sum(d['chunks'] for d in shown):,} chunks")
    st.dataframe([{"filing": f"{d['company']} {d['fiscal_year']}", "pages": d["pages"], "chunks": d["chunks"]}
                  for d in shown], hide_index=True, width="stretch")

# A radio, not st.tabs: tabs run every tab's code on each rerun (a /stats call per keystroke) and
# draw hidden tabs' data grids at zero width; a radio renders only the selected view.
view = st.radio("View", ["Ask", "Eval results", "Live stats"], horizontal=True, label_visibility="collapsed")

# --- Ask ----------------------------------------------------------------------------------------

if view == "Ask":
    st.title("Ask the 10-K filings")
    with st.form("ask"):
        question = st.text_input("Question", placeholder="What was AMD's net revenue in 2022?", max_chars=2000)
        submitted = st.form_submit_button("Ask", type="primary")

    if submitted and question.strip():
        box, status = st.empty(), st.empty()
        text, sources = "", []
        c = client()
        try:
            status.info("Retrieving…")
            for event, data in c.stream(question, picked_companies, picked_years, k):
                if event == "sources":
                    sources = data
                    status.info(f"Retrieved {len(sources)} sources · generating…")
                elif event == "delta":
                    text += data
                    box.markdown(safe_markdown(text) + " ▌")
                elif event == "answer":
                    st.session_state["last"] = {"answer": data, "sources": sources, "timings": vars(c.timings)}
            status.empty()
        except APIError as exc:
            status.error(f"{exc.code}: {exc.message}")
            st.session_state.pop("last", None)
        except Exception as exc:
            status.error(f"Request failed: {exc}")
            st.session_state.pop("last", None)
        box.empty()

    last = st.session_state.get("last")
    if last:
        a, by_id = last["answer"], {s["chunk_id"]: s for s in last["sources"]}
        if a["refused"]:
            st.warning(a["answer"])
        else:
            st.markdown(safe_markdown(a["answer"]))
        if a.get("quarantined"):
            st.error(f"{len(a['quarantined'])} retrieved passage(s) were kept out of the prompt as likely prompt "
                     "injections: " + ", ".join(f"{q['doc_key']} p.{q['page_number']} ({', '.join(q['signals'])})"
                                                for q in a["quarantined"]))
        if a["uncited_sentences"]:
            st.caption("⚠️ Uncited: " + " · ".join(a["uncited_sentences"]))

        st.subheader("Citations")
        if not a["citations"]:
            st.caption("No citations.")
        for cit in a["citations"]:
            src = by_id.get(cit["chunk_id"], {})
            # Every widget click reruns the script; without `expanded=` the expander would close again
            # the moment its own "Show the PDF page" toggle is switched on.
            with st.expander(f"[{cit['n']}] {cit['label']}  ·  {' › '.join(src.get('section', []))}",
                             expanded=bool(st.session_state.get(f"show-{cit['n']}"))):
                left, right = st.columns([1, 1])
                with left:
                    pages_txt = (f"PDF page {cit['page_number']}" if cit["page_end"] == cit["page_number"]
                                 else f"PDF pages {cit['page_number']}–{cit['page_end']}")
                    st.caption(f"chunk {cit['chunk_id']} · {cit['doc_key']} · {pages_txt} · "
                               f"chars {cit['char_start']:,}–{cit['char_end']:,}")
                    st.text(src.get("text", ""))
                with right:
                    pages = list(range(cit["page_number"], cit["page_end"] + 1))
                    page = st.selectbox("Page", pages, key=f"page-{cit['n']}") if len(pages) > 1 else pages[0]
                    if st.toggle("Show the PDF page", key=f"show-{cit['n']}"):
                        try:
                            st.image(page_image(cit["chunk_id"], page), caption=f"PDF page {page}, cited text highlighted")
                        except APIError as exc:
                            st.info(f"Page preview unavailable: {exc.message}")

        with st.expander("All retrieved sources"):
            st.dataframe([{"n": s["n"], "filing": f"{s['company']} {s['fiscal_year']}", "page": s["page_number"],
                           "score": round(s["score"], 3), "cited": s["chunk_id"] in {c["chunk_id"] for c in a["citations"]},
                           "text": s["text"][:160]} for s in last["sources"]], hide_index=True, width="stretch")

        u, t = a["usage"], last["timings"]
        cols = st.columns(4)
        cols[0].metric("Time to sources", f"{t['sources_ms']:,.0f} ms" if t["sources_ms"] else "—")
        cols[1].metric("Time to first token", f"{t['first_delta_ms']:,.0f} ms" if t["first_delta_ms"] else "—")
        cols[2].metric("Total", f"{t['done_ms']:,.0f} ms" if t["done_ms"] else "—")
        cols[3].metric("Tokens in / out", f"{u['input_tokens']:,} / {u['output_tokens']:,}")
        st.caption(f"{u['provider']} · {u['model']} · {'cached' if u['cached'] else 'live'} · list price "
                   f"\\${u['list_usd']:.4f}, billed \\${u['billed_usd']:.4f} · request {a['request_id']}")   # \$: not LaTeX

# --- Eval results -------------------------------------------------------------------------------

if view == "Eval results":
    st.title("Eval results")
    runs = results.list_runs()
    if not runs:
        st.info("No results yet: run `make eval`.")
    else:
        run = st.selectbox("Run", runs, index=results.default_index(runs), format_func=lambda r: r.label)
        data = results.load(run)
        if run.kind == "injection":
            st.caption(f"Prompt-injection suite · model {data.get('model')} · {data.get('n')} trials per configuration")
            st.dataframe(results.injection_table(data), hide_index=True, width="stretch")
            st.json(data.get("summary", {}))
        else:
            h = results.headline(data)
            st.caption(f"{h['config']} · {h['questions']} questions" + (" · closed book" if h["closed book"] else "")
                       + (f" · generator {h['generator']} · judge {h['judge']}" if h["generator"] else ""))
            cols = st.columns(5)
            for col, key in zip(cols, ("hit@5", "recall@10", "correctness", "faithfulness", "false refusals")):
                col.metric(key, "—" if h[key] is None else f"{h[key]:.3f}")
            rows = results.question_rows(data)
            types = sorted({r["type"] for r in rows if r["type"]})
            pick = st.multiselect("Question types", types, default=types)
            st.dataframe([r for r in rows if r["type"] in pick], hide_index=True, width="stretch")
        abl = results.latest_ablation()
        if abl:
            with st.expander(f"Ablation table ({abl[0].name}, {len(abl[1])} configurations)"):
                st.dataframe(abl[1], hide_index=True, width="stretch")

# --- Live stats ---------------------------------------------------------------------------------

if view == "Live stats":
    st.title("Live stats")
    hours = st.select_slider("Window", options=[1, 6, 24, 168], value=24, format_func=lambda h: f"{h} h")
    try:
        s = client().stats(hours)
    except Exception as exc:
        st.error(f"/stats failed: {exc}")
    else:
        cols = st.columns(4)
        cols[0].metric("Requests", s["requests"])
        cols[1].metric("Errors", s["errors"])
        cols[2].metric("Cache hit rate", "—" if s["cache_hit_rate"] is None else f"{s['cache_hit_rate']:.0%}")
        cols[3].metric("List \\$ / 1k requests", "—" if s["list_usd_per_1k_requests"] is None
                       else f"\\${s['list_usd_per_1k_requests']:.2f}")
        st.dataframe([{"stage": k, **v} for k, v in s.get("stages", {}).items()], hide_index=True, width="stretch")
