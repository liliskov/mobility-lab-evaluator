from __future__ import annotations

import json

import streamlit as st

from evaluator import REQUIRED_FILES, REQUIRED_OUTPUT_COLUMNS, evaluate_submission


st.set_page_config(
    page_title="Pipeline Lab Evaluator",
    page_icon="🚆",
    layout="wide",
)

st.markdown(
    """
    <style>
      .stApp { background: linear-gradient(180deg, #f2f6fb 0%, #ffffff 46%); }
      .block-container { max-width: 1180px; padding-top: 2.3rem; }
      h1 { color: #17365f; letter-spacing: -0.035em; }
      [data-testid="stMetric"] { background: white; border: 1px solid #d5deea; padding: 1rem; border-radius: .8rem; }
      .contract { background: #eef4fb; border-left: 4px solid #245b9c; padding: 1rem 1.2rem; border-radius: .5rem; }
      .small-note { color: #5c6878; font-size: .88rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Pipeline Lab Evaluator")
st.caption("Big Data Technology · Belgian rail mobility and OpenStreetMap")

st.markdown(
    """
    <div class="contract">
      Upload the result of an end-to-end mobility pipeline. The evaluator checks the
      output contract, lineage, reconciliation, data quality, idempotency and
      OpenStreetMap enrichment. It does not execute student code or assign an official grade.
    </div>
    """,
    unsafe_allow_html=True,
)

left, right = st.columns([0.92, 1.25], gap="large")

with left:
    st.subheader("Submission")
    uploaded = st.file_uploader(
        "Upload submission.zip",
        type=["zip"],
        help="The archive may contain folders, but must include the three required files.",
    )

    with st.expander("Required package", expanded=True):
        st.code("\n".join(sorted(REQUIRED_FILES)), language="text")

    with st.expander("Required output columns"):
        st.code("\n".join(REQUIRED_OUTPUT_COLUMNS), language="text")

    st.markdown(
        '<p class="small-note">Prototype limit: 25 MB. Uploaded code is never executed.</p>',
        unsafe_allow_html=True,
    )

with right:
    st.subheader("Evaluation")

    if uploaded is None:
        st.info("Upload a submission package to run the deterministic checks.")
    else:
        try:
            result = evaluate_submission(uploaded.getvalue())
        except ValueError as exc:
            st.error(str(exc))
            st.stop()

        first, second, third = st.columns(3)
        first.metric("Score", f"{result['score']}/{result['maximum']}")
        second.metric("Rows evaluated", result["rows"])
        third.metric("Checks passed", f"{result['checks_passed']}/{result['checks_total']}")

        progress = result["score"] / result["maximum"] if result["maximum"] else 0
        st.progress(progress)

        for check in result["checks"]:
            message = (
                f"**{check['name']} — {check['points']}/{check['maximum']}**  \n"
                f"{check['detail']}"
            )
            if check["status"] == "pass":
                st.success(message)
            elif check["status"] == "warning":
                st.warning(message)
            else:
                st.error(message)

        st.download_button(
            "Download feedback JSON",
            data=json.dumps(result, indent=2),
            file_name="pipeline-lab-feedback.json",
            mime="application/json",
        )

st.divider()
st.markdown(
    '<p class="small-note">Formative prototype · no submission data is persisted by the application.</p>',
    unsafe_allow_html=True,
)
