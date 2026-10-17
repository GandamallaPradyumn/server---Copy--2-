import streamlit as st
import pandas as pd
import importlib
import json
import ast
from utils import get_mysql_engine, insert_to_mysql


def run_etl_dashboard():

    # ----------------------------
    # Load DB Credentials
    # ----------------------------
    with open("config.json", "r") as f:
        config = json.load(f)

    # ----------------------------
    # Initialize Session State
    # ----------------------------
    if "file_uploader_key" not in st.session_state:
        st.session_state.file_uploader_key = 0

    for key in ["original_df", "raw_df", "transformed_df", "target_table", "validation_report", "last_uploaded_name"]:
        if key not in st.session_state:
            st.session_state[key] = None if key != "validation_report" else {}

    # ----------------------------
    # File Uploader (Dynamic Key)
    # ----------------------------
    uploaded_file = st.file_uploader(
        "📁 Upload your CSV file",
        type=["csv"],
        key=f"file_uploader_{st.session_state.file_uploader_key}",
    )

    # ----------------------------
    # Correct handling (only reset when file CHANGES)
    # ----------------------------
    if uploaded_file is not None:

        # If NEW file uploaded
        if st.session_state.last_uploaded_name != uploaded_file.name:

            df = pd.read_csv(uploaded_file)

            st.session_state.original_df = df
            st.session_state.raw_df = df.copy()

            # Reset transform results only for a new file
            st.session_state.transformed_df = None
            st.session_state.target_table = None
            st.session_state.validation_report = {}

            st.session_state.last_uploaded_name = uploaded_file.name

    # ----------------------------
    # Control Bar
    # ----------------------------
    col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])

    with col1:
        dataset_type = st.selectbox(
            "Select Dataset Type",
            ["Operational Data", "Leave & Absent", "Driver Details", "Service Master"]
        )

    with col2:
        preview_btn = st.button("🔍 Preview CSV")

    with col3:
        transform_btn = st.button("⚙ Transform Data")

    with col4:
        load_btn = st.button("🚀 Load into Database")

    with col5:
        reset_btn = st.button("♻ Reset Transform")

    # ----------------------------
    # RESET (Perfect Reset)
    # ----------------------------
    if reset_btn:

        for key in ["original_df", "raw_df", "transformed_df",
                    "target_table", "validation_report", "last_uploaded_name"]:
            st.session_state[key] = None

        # Regenerate uploader widget
        st.session_state.file_uploader_key += 1

        st.success("🔄 Fully reset. Upload a new file.")
        st.rerun()

    # ----------------------------
    # Enforce: No file = stop UI
    # ----------------------------
    if st.session_state.original_df is None:
        st.info("📥 Please upload a CSV file to start.")
        return

    # ----------------------------
    # PREVIEW BUTTON
    # ----------------------------
    if preview_btn:
        if st.session_state.transformed_df is not None:
            st.subheader("🧮 Transformed Data Preview (First 10 Rows)")
            st.dataframe(st.session_state.transformed_df.head(10))
        else:
            st.subheader("🧾 Raw Data Preview (First 10 Rows)")
            st.dataframe(st.session_state.raw_df.head(10))

    # ----------------------------
    # TRANSFORM BUTTON
    # ----------------------------
    if transform_btn:

        st.subheader("⚙ Applying Transformations...")

        module_map = {
            "Operational Data": "operational_data",
            "Leave & Absent": "leave_absent",
            "Driver Details": "driver_details",
            "Service Master": "service_master",
        }

        module_name = module_map.get(dataset_type)

        if module_name:
            transformer = importlib.import_module(module_name)

            try:
                result = transformer.transform(st.session_state.raw_df.copy())

                if isinstance(result, tuple) and len(result) == 3:
                    transformed_df, target_table, validation_report = result
                else:
                    transformed_df, target_table = result
                    validation_report = {}

                st.session_state.transformed_df = transformed_df
                st.session_state.target_table = target_table
                st.session_state.validation_report = validation_report

                # Validate
                unmapped = validation_report.get("unmapped_depots", [])
                missing_data = {
                    k: v for k, v in validation_report.items() if k != "unmapped_depots"
                }

                if unmapped:
                    st.warning(
                        f"⚠ Unmapped depots found ({len(unmapped)}): "
                        + ", ".join(unmapped[:10])
                        + (" ..." if len(unmapped) > 10 else "")
                    )

                if missing_data:
                    st.error("❌ Missing values detected:")
                    for col, count in missing_data.items():
                        st.markdown(f"- {col} → Missing rows: {count}")

                st.success(f"✅ Transformation complete for {dataset_type}!")
                st.dataframe(transformed_df.head(10))

            except Exception as e:
                st.error(f"❌ Transformation failed: {e}")

    # ----------------------------
    # LOAD BUTTON
    # ----------------------------
    if load_btn:

        if st.session_state.transformed_df is None:
            st.warning("⚠ Please transform your data before loading.")
        else:
            transformed_df = st.session_state.transformed_df
            target_table = st.session_state.target_table

            if target_table is None:
                st.error("❌ Target table not defined.")
            else:
                engine = get_mysql_engine(config)
                with st.spinner("⏳ Loading into MySQL..."):
                    insert_to_mysql(engine, transformed_df, target_table)

                st.success(f"✅ Successfully loaded into {target_table}!")
