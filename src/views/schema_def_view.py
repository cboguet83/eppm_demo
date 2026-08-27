"""Screen 3: Parameters Definition View (Dynamic Schema Builder)."""

import sqlite3
from typing import Optional

import pandas as pd
import streamlit as st

from src.models.constants import (
    PARAM_TYPE_ENUM,
    PARAM_TYPE_MULTI_ENUM,
    PARAM_TYPE_TAGS,
    PARAM_TYPES,
)
from src.repositories.schema_repo import SchemaRepository
from src.services.schema_service import SchemaService


def render_schema_definition(schema_repo: SchemaRepository) -> None:
    """Renders the Parameters Definition screen for schema groups, fields, options, and live tree."""
    st.header("⚙️ Parameters Definition (Schema Builder)")
    st.caption("Define custom attributes and taxonomies that dynamically render across all projects and portfolios.")

    tab_groups, tab_params, tab_options, tab_preview = st.tabs([
        "📁 Schema Groups",
        "🏷️ Parameters & Fields",
        "🔘 Discrete Enum & Tags Options",
        "👁️ Live Schema Tree",
    ])

    groups = schema_repo.get_all_groups()
    params = schema_repo.get_all_parameters()
    options = schema_repo.get_all_options()

    # --------------------------------------------------------------------------
    # TAB 1: SCHEMA GROUPS
    # --------------------------------------------------------------------------
    with tab_groups:
        st.subheader("Manage Schema Groups")
        col_left, col_right = st.columns(2)

        # Section A: Add New Group
        with col_left:
            st.markdown("#### ➕ Add New Schema Group")
            next_avail_order = SchemaService.get_next_available_group_order()
            existing_orders = groups["display_order"].tolist() if not groups.empty else []

            with st.form("form_add_group"):
                new_grp_name = st.text_input("Group Name *", placeholder="e.g. Risk & Compliance")
                new_grp_order = st.number_input(
                    "Display Order *",
                    min_value=1,
                    value=next_avail_order,
                    step=1,
                    help=f"Next available display order is {next_avail_order}",
                )
                btn_add_grp = st.form_submit_button("➕ Add Schema Group", width="stretch")

                if btn_add_grp:
                    clean_name = new_grp_name.strip()
                    int_order = int(new_grp_order)

                    if not clean_name:
                        st.error("Group name cannot be empty.")
                    elif int_order in existing_orders:
                        st.warning(
                            f"Display Order **{int_order}** is already in use by another group. Auto-assigned to next available order: **{next_avail_order}**."
                        )
                        try:
                            schema_repo.create_group(clean_name, next_avail_order)
                            st.success(f"Group '{clean_name}' created with Display Order {next_avail_order}!")
                            st.rerun()
                        except sqlite3.IntegrityError as err:
                            st.error(f"Failed to create group: {err}")
                    else:
                        try:
                            schema_repo.create_group(clean_name, int_order)
                            st.success(f"Group '{clean_name}' created successfully with Display Order {int_order}!")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error(f"A group named '{clean_name}' already exists.")

        # Section B: Edit Existing Group
        with col_right:
            st.markdown("#### ✏️ Edit Existing Schema Group")
            if groups.empty:
                st.caption("No groups available to edit.")
            else:
                grp_id_to_edit = st.selectbox(
                    "Select Group to Edit",
                    options=groups["id"].tolist(),
                    format_func=lambda x: f"{x} - {groups[groups['id'] == x]['group_name'].iloc[0]} (Order: {groups[groups['id'] == x]['display_order'].iloc[0]})",
                    key="sb_edit_group",
                )
                curr_grp = groups[groups["id"] == grp_id_to_edit].iloc[0]

                with st.form("form_edit_group"):
                    edit_grp_name = st.text_input("Group Name *", value=str(curr_grp["group_name"]))
                    edit_grp_order = st.number_input(
                        "Display Order *",
                        min_value=1,
                        value=int(curr_grp["display_order"]),
                        step=1,
                    )
                    btn_save_grp = st.form_submit_button("💾 Save Changes", width="stretch")

                    if btn_save_grp:
                        clean_name = edit_grp_name.strip()
                        new_order = int(edit_grp_order)

                        if not clean_name:
                            st.error("Group name cannot be empty.")
                        else:
                            other_orders = groups[groups["id"] != grp_id_to_edit]["display_order"].tolist()
                            if new_order in other_orders:
                                st.error(f"Display Order {new_order} is already used by another group.")
                            else:
                                try:
                                    schema_repo.update_group(grp_id_to_edit, clean_name, new_order)
                                    st.success(f"Group '{clean_name}' updated successfully!")
                                    st.rerun()
                                except sqlite3.IntegrityError:
                                    st.error(f"Group name '{clean_name}' already exists.")

        st.divider()
        st.write("##### Existing Schema Groups")
        if groups.empty:
            st.info("No groups created yet.")
        else:
            st.dataframe(groups, width="stretch", hide_index=True)

            st.write("##### 🗑️ Delete Schema Group")
            del_col1, del_col2 = st.columns([2, 2])
            del_grp_id = del_col1.selectbox(
                "Select Group to Delete",
                options=groups["id"].tolist(),
                format_func=lambda x: f"{x} - {groups[groups['id'] == x]['group_name'].iloc[0]}",
                key="sb_del_grp",
            )
            del_grp_name = groups[groups["id"] == del_grp_id]["group_name"].iloc[0]
            confirm_del_grp = del_col2.checkbox(
                f"Confirm deletion of group '{del_grp_name}' (Assigned parameters will become ungrouped)",
                key="chk_confirm_del_grp",
            )
            if st.button("🗑️ Delete Selected Group", key="btn_del_grp", disabled=not confirm_del_grp):
                schema_repo.delete_group(del_grp_id)
                st.success(f"Group '{del_grp_name}' deleted successfully.")
                st.rerun()

    # --------------------------------------------------------------------------
    # TAB 2: PARAMETERS & FIELDS
    # --------------------------------------------------------------------------
    with tab_params:
        st.subheader("Manage Schema Parameters")
        with st.form("form_add_param"):
            col1, col2 = st.columns(2)
            auto_id = SchemaService.generate_param_id()
            new_param_id = col1.text_input(
                "Parameter ID *",
                value=auto_id,
                disabled=True,
                help="Auto-calculated unique identifier key",
            )
            new_param_name = col2.text_input("Parameter Label / Name *", placeholder="e.g. Tech Stack or Department")

            col3, col4 = st.columns(2)
            grp_options: list[Optional[int]] = [None]
            grp_map: dict[Optional[int], str] = {None: "📌 (No Group / General)"}
            if not groups.empty:
                for _, g in groups.iterrows():
                    gid = int(g["id"])
                    grp_options.append(gid)
                    grp_map[gid] = f"📁 {g['group_name']} (Order: {g['display_order']})"

            selected_gid = col3.selectbox(
                "Assign to Group (Optional)",
                options=grp_options,
                format_func=lambda x: grp_map.get(x, "Unknown"),
            )
            selected_ptype = col4.selectbox(
                "Parameter Data Type *",
                options=PARAM_TYPES,
                help="TEXT, ENUM (Single choice), MULTI_ENUM (Multiple choices), TAGS (Tag pills), URL (Link)",
            )

            initial_opts = ""
            if selected_ptype in (PARAM_TYPE_ENUM, PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS):
                initial_opts = st.text_input(
                    "Initial Option / Tag Values (comma-separated)",
                    placeholder="Option 1, Option 2, Option 3",
                )

            btn_add_param = st.form_submit_button("➕ Add Parameter", width="stretch")
            if btn_add_param:
                clean_pid = auto_id.strip() if auto_id else new_param_id.strip()
                clean_pname = new_param_name.strip()
                if not clean_pid or not clean_pname:
                    st.error("Parameter ID and Label are required.")
                else:
                    try:
                        schema_repo.create_parameter(
                            param_id=clean_pid,
                            group_id=selected_gid,
                            param_name=clean_pname,
                            param_type=selected_ptype,
                        )

                        if selected_ptype in (PARAM_TYPE_ENUM, PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS) and initial_opts.strip():
                            raw_opts = [o.strip() for o in initial_opts.split(",") if o.strip()]
                            for idx, opt_val in enumerate(raw_opts, 1):
                                schema_repo.add_option(clean_pid, opt_val, idx)

                        st.success(f"Parameter '{clean_pid} - {clean_pname}' ({selected_ptype}) created successfully!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error(f"Parameter ID '{clean_pid}' already exists.")

        st.write("##### Existing Parameters")
        if params.empty:
            st.info("No parameters created yet.")
        else:
            params_display = params.copy()
            if not groups.empty:
                params_display = pd.merge(
                    params_display,
                    groups[["id", "group_name"]].rename(columns={"id": "group_id", "group_name": "Group"}),
                    on="group_id",
                    how="left",
                )
            else:
                params_display["Group"] = None

            params_display["Group"] = params_display["Group"].fillna("(No Group / General)")
            st.dataframe(
                params_display[["param_id", "Group", "param_name", "param_type"]],
                width="stretch",
                hide_index=True,
            )

            del_param_id = st.selectbox("Select Parameter to Delete", options=params["param_id"].tolist())
            if st.button("🗑️ Delete Selected Parameter", key="btn_del_param"):
                schema_repo.delete_parameter(del_param_id)
                st.success(f"Parameter '{del_param_id}' deleted.")
                st.rerun()

    # --------------------------------------------------------------------------
    # TAB 3: DISCRETE ENUM & TAGS OPTIONS
    # --------------------------------------------------------------------------
    with tab_options:
        st.subheader("Manage Enum & Tags Option Values")
        tag_or_enum_params = params[params["param_type"].isin([PARAM_TYPE_ENUM, PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS])]

        if tag_or_enum_params.empty:
            st.info("No ENUM, MULTI_ENUM, or TAGS parameters configured yet.")
        else:
            p_map = dict(zip(tag_or_enum_params["param_id"], tag_or_enum_params["param_name"]))
            target_pid = st.selectbox(
                "Select Parameter",
                options=tag_or_enum_params["param_id"].tolist(),
                format_func=lambda x: f"{x} - {p_map.get(x, '')} ({tag_or_enum_params[tag_or_enum_params['param_id'] == x]['param_type'].iloc[0]})",
            )

            current_opts = options[options["param_id"] == target_pid]
            st.write(f"**Current Options / Tags for `{target_pid}`:**")
            if current_opts.empty:
                st.caption("No options configured yet.")
            else:
                st.dataframe(
                    current_opts[["id", "option_value", "display_order"]],
                    width="stretch",
                    hide_index=True,
                )

            with st.form("form_add_opt"):
                col1, col2 = st.columns([3, 1])
                opt_val = col1.text_input("New Option / Tag Value *", placeholder="e.g. Critical or Cloud Native")
                opt_ord = col2.number_input("Display Order", min_value=0, value=len(current_opts) + 1, step=1)
                btn_add_opt = st.form_submit_button("➕ Add Value")

                if btn_add_opt:
                    if not opt_val.strip():
                        st.error("Value cannot be empty.")
                    else:
                        schema_repo.add_option(target_pid, opt_val.strip(), int(opt_ord))
                        st.success(f"Option '{opt_val}' added!")
                        st.rerun()

            if not current_opts.empty:
                del_opt_id = st.selectbox(
                    "Delete Option",
                    options=current_opts["id"].tolist(),
                    format_func=lambda x: str(current_opts[current_opts["id"] == x]["option_value"].iloc[0]),
                )
                if st.button("🗑️ Delete Selected Option"):
                    schema_repo.delete_option(del_opt_id)
                    st.success("Option deleted.")
                    st.rerun()

    # --------------------------------------------------------------------------
    # TAB 4: LIVE SCHEMA TREE
    # --------------------------------------------------------------------------
    with tab_preview:
        st.subheader("Schema Hierarchy Explorer")
        if groups.empty and params.empty:
            st.info("Schema is empty.")
        else:
            # Grouped parameters
            if not groups.empty:
                for _, grp in groups.iterrows():
                    gid = grp["id"]
                    st.markdown(f"### 📁 `{grp['group_name']}` (Order: {grp['display_order']})")
                    grp_params = params[params["group_id"] == gid]
                    if grp_params.empty:
                        st.caption("  *No parameters assigned to this group.*")
                    else:
                        for _, p in grp_params.iterrows():
                            pid = p["param_id"]
                            ptype = p["param_type"]
                            pname = p["param_name"]
                            st.markdown(f"- 🏷️ **{pname}** (`{pid}`) — Type: `{ptype}`")
                            if ptype in (PARAM_TYPE_ENUM, PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS):
                                p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                                if p_opts:
                                    st.markdown("  - Options/Tags: " + ", ".join([f"`{o}`" for o in p_opts]))
                                else:
                                    st.markdown("  - *No options defined.*")
                    st.divider()

            # Ungrouped parameters
            ungrouped_params = params[params["group_id"].isna() | (params["group_id"] == None)]  # noqa: E711
            if not ungrouped_params.empty:
                st.markdown("### 📌 General Parameters (No Group Assigned)")
                for _, p in ungrouped_params.iterrows():
                    pid = p["param_id"]
                    ptype = p["param_type"]
                    pname = p["param_name"]
                    st.markdown(f"- 🏷️ **{pname}** (`{pid}`) — Type: `{ptype}`")
                    if ptype in (PARAM_TYPE_ENUM, PARAM_TYPE_MULTI_ENUM, PARAM_TYPE_TAGS):
                        p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                        if p_opts:
                            st.markdown("  - Options/Tags: " + ", ".join([f"`{o}`" for o in p_opts]))
                        else:
                            st.markdown("  - *No options defined.*")
