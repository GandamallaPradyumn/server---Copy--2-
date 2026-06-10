import streamlit as st
import os
import tempfile
import shutil
from dynamic_scheduling_master.app import (
    run_pipeline,
    run_prediction,
    run_scheduling,
)

def render_operations_controls():
    st.title("Inbound Daily File Upload")
    # Fixed destination folder
    destination_folder = r"C:\Users\prady\OneDrive\Desktop\server - Copy (2)\dynamic_scheduling_master\data\inbound_daily"

    st.write("Destination Folder:")
    st.code(destination_folder)

    # Upload files
    uploaded_files = st.file_uploader(
        "Upload Inbound Files",
        accept_multiple_files=True
    )

    # Move button
    if st.button("Move Files to Inbound Folder"):

        if not uploaded_files:
            st.warning("Please upload files")

        else:

            moved_files = []

            for uploaded_file in uploaded_files:

                # Save to temp
                temp_path = os.path.join(tempfile.gettempdir(), uploaded_file.name)

                with open(temp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                # Final destination (same name)
                final_path = os.path.join(destination_folder, uploaded_file.name)

                # Move file
                shutil.move(temp_path, final_path)

                moved_files.append(uploaded_file.name)

            st.success("Files moved successfully")

            st.write("Moved Files:")
            for file in moved_files:
                st.write(file)

    st.markdown("## Daily Operations")

    # Create 3 equal columns
    col1, col2, col3 = st.columns(3)

    # --- BUTTON 1 ---
    with col1:
        if st.button("Run Data Pipeline", use_container_width=True):
            with st.spinner("Running data pipeline..."):
                try:
                    result = run_pipeline()
                    st.success(
                        f"Pipeline complete — "
                        f"Depot files: {result['depot_files_processed']}, "
                        f"Service files: {result['service_files_processed']}"
                    )
                except Exception as e:
                    st.error(f"Pipeline failed: {e}")

            st.cache_data.clear()
            st.rerun()

    # --- BUTTON 2 ---
    with col2:
        if st.button("Run Demand Prediction", use_container_width=True):
            with st.spinner("Running demand prediction..."):
                try:
                    result = run_prediction()
                    st.success(
                        f"Predictions generated for {result['prediction_date']}"
                    )
                except Exception as e:
                    st.error(f"Prediction failed: {e}")

            st.cache_data.clear()
            st.rerun()

    # --- BUTTON 3 ---
    with col3:
        if st.button("Run Supply Scheduling", use_container_width=True):
            with st.spinner("Running supply scheduling..."):
                try:
                    result = run_scheduling()
                    st.success(
                        f"Scheduling complete for {result['target_date']} — "
                        f"{result['depots_processed']} depot(s)"
                    )
                except Exception as e:
                    st.error(f"Scheduling failed: {e}")

            st.cache_data.clear()
            st.rerun()
