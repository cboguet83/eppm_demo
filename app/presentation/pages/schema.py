"""Screen 3: Parameters Definition View (Dynamic Schema Builder)."""

from collections.abc import Callable
from typing import Any, TypeVar

import pandas as pd
import streamlit as st

from app.application.exceptions import SchemaStorageError, ProjectTypeStorageError
from app.application.services.schema import SchemaService
from app.application.services.project_types import ProjectTypeService
from app.domain.projects.property_values import SUPPORTED_PROPERTY_TYPES
from app.presentation.i18n import SUPPORTED_LOCALES, get_current_locale, t
from app.presentation.components.schema_frames import groups_frame, parameters_frame, options_frame
from app.presentation.pages.project_types import applicability_input, render_project_types

PARAM_TYPES = list(SUPPORTED_PROPERTY_TYPES)
CHOICE_TYPES = ("ENUM", "MULTI_ENUM", "TAGS")
_Result = TypeVar("_Result")


def _save(action: Callable[..., _Result], *args: Any, **kwargs: Any) -> _Result:
    """Handle application errors at the widget boundary; arguments are form data."""
    try:
        return action(*args, **kwargs)
    except (ValueError, SchemaStorageError) as exc:
        st.error(str(exc))
        st.stop()


def render_schema_definition(service: SchemaService, type_service: ProjectTypeService) -> None:
    """Render schema administration through injected application services."""
    try:
        _render_schema_definition(service, type_service)
    except (ValueError, SchemaStorageError, ProjectTypeStorageError) as exc:
        st.error(str(exc))


def _render_schema_definition(service: SchemaService, type_service: ProjectTypeService) -> None:
    """Renders the Parameters Definition screen for schema groups, fields, options, and live tree."""
    tab_groups, tab_params, tab_options, tab_preview, tab_types = st.tabs([
        t("schema.tab_groups"),
        t("schema.tab_params"),
        t("schema.tab_options"),
        t('schema.tab_tree', default='Live Schema Tree'),
        t("project_types.title"),
    ])

    snapshot = service.get_snapshot()
    groups = groups_frame(snapshot.groups)
    params = parameters_frame(snapshot.parameters)
    options = options_frame(snapshot.options)
    with tab_types:
        render_project_types(type_service, options)

    with tab_groups:
        _render_groups(service, groups)
    with tab_params:
        _render_parameters(service, type_service, groups, params)
        _render_alias_translations(service, params)
    with tab_options:
        _render_options(service, params, options)
    with tab_preview:
        _render_schema_tree(groups, params, options)


def _render_alias_translations(service: SchemaService, params: pd.DataFrame) -> None:
    """Maintain localized aliases separately from stable IDs and default labels."""
    if params.empty:
        return
    with st.expander("Parameter alias translations"):
        labels = dict(zip(params["param_id"], params["param_name"]))
        param_id = st.selectbox("Parameter", list(labels), format_func=labels.get,
            key="schema_alias_property")
        locale = st.selectbox("Translation language", list(SUPPORTED_LOCALES),
            format_func=SUPPORTED_LOCALES.get,
            index=list(SUPPORTED_LOCALES).index(get_current_locale()), key="schema_alias_locale")
        translations = service.get_alias_translations(locale)
        with st.form(f"schema_alias_form_{param_id}_{locale}"):
            alias = st.text_input("Translated alias", value=translations.get(param_id, ""))
            st.caption("Leave blank to use the default alias, or the parameter name when no alias is set.")
            if st.form_submit_button("Save alias translation"):
                _save(service.set_alias_translation, param_id, locale, alias)
                st.rerun()


def _render_groups(service: SchemaService, groups: pd.DataFrame) -> None:
    st.subheader(t("schema.grp_create_header"))
    col_left, col_right = st.columns(2)

    # Section A: Add New Group
    with col_left:
        st.markdown(f"#### {t('schema.grp_create_header')}")
        next_avail_order = service.get_next_available_group_order()

        with st.form("form_add_group"):
            new_grp_name = st.text_input(t("schema.grp_name"), placeholder=t("schema.grp_name_placeholder"))
            new_grp_order = st.number_input(
                t("schema.grp_order"),
                min_value=1,
                value=next_avail_order,
                step=1,
                help=f"Next available display order is {next_avail_order}",
            )
            btn_add_grp = st.form_submit_button(t("schema.btn_create_grp"), width="stretch")

            if btn_add_grp:
                clean_name = new_grp_name.strip()
                _save(service.create_group, clean_name, int(new_grp_order), auto_assign_order=True)
                st.success(t("schema.msg_grp_created", name=clean_name))
                st.rerun()

    # Section B: Edit Existing Group
    with col_right:
        st.markdown("#### Edit Existing Schema Group")
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
                edit_grp_name = st.text_input(t("schema.grp_name"), value=str(curr_grp["group_name"]))
                edit_grp_order = st.number_input(
                    t("schema.grp_order"),
                    min_value=1,
                    value=int(curr_grp["display_order"]),
                    step=1,
                )
                btn_save_grp = st.form_submit_button("Save Changes", width="stretch")

                if btn_save_grp:
                    updated = _save(service.update_group, grp_id_to_edit, edit_grp_name, int(edit_grp_order))
                    if not updated:
                        st.error("The selected group no longer exists.")
                        st.stop()
                    st.success(f"Group '{edit_grp_name.strip()}' updated successfully!")
                    st.rerun()

    st.divider()
    st.write("##### Existing Schema Groups")
    if groups.empty:
        st.info("No groups created yet.")
    else:
        st.dataframe(groups, width="stretch", hide_index=True)

        st.write("##### Delete Schema Group")
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
        if st.button(t("schema.btn_del_grp"), key="btn_del_grp", disabled=not confirm_del_grp):
            _save(service.delete_group, del_grp_id)
            st.success(f"Group '{del_grp_name}' deleted successfully.")
            st.rerun()


def _render_parameters(service: SchemaService, type_service: ProjectTypeService,
                       groups: pd.DataFrame, params: pd.DataFrame) -> None:
    st.subheader(t("schema.param_create_header"))
    with st.container():
        col1, col2 = st.columns(2)
        auto_id = service.generate_param_id()
        col1.text_input(
            t("schema.param_id"),
            value=auto_id,
            disabled=True,
            help=t("schema.param_id_help"),
        )
        new_param_name = col2.text_input(t("schema.param_name"), placeholder=t("schema.param_name_placeholder"))

        col3, col4 = st.columns(2)
        grp_options: list[int | None] = [None]
        grp_map: dict[int | None, str] = {None: t("schema.param_group_none")}
        if not groups.empty:
            for _, g in groups.iterrows():
                gid = int(g["id"])
                grp_options.append(gid)
                grp_map[gid] = f"{g['group_name']} (Order: {g['display_order']})"

        selected_gid = col3.selectbox(
            t("schema.param_group_assign"),
            options=grp_options,
            format_func=lambda x: grp_map.get(x, "Unknown"),
        )
        selected_ptype = col4.selectbox(
            t("schema.param_type"),
            options=PARAM_TYPES,
            help="TEXT, ENUM (Single choice), MULTI_ENUM (Multiple choices), TAGS (Tag pills), URL (Link), DATE, NUMBER, HYPERLINK",
        )

        col5, col6 = st.columns(2)
        new_param_alias = col5.text_input(
            t("schema.param_alias", default="Parameter Alias (Optional)"),
            placeholder=t("schema.param_alias_placeholder", default="e.g. code ligne"),
        )
        new_param_mandatory = col6.checkbox(
            t("schema.param_mandatory", default="Mandatory parameter (required to save project)"),
            value=False,
        )

        initial_opts = ""
        if selected_ptype in CHOICE_TYPES:
            initial_opts = st.text_input(
                t("schema.param_initial_options"),
                placeholder="Option 1, Option 2, Option 3",
            )

        applies_to_all, type_ids = applicability_input(type_service, "new_property")
        btn_add_param = st.button(t("schema.btn_add_param"), width="stretch")
        if btn_add_param:
            raw_opts = [value.strip() for value in initial_opts.split(",") if value.strip()]
            created_id = _save(
                service.create_parameter, None, selected_gid, new_param_name, selected_ptype,
                new_param_mandatory, new_param_alias, applies_to_all, type_ids,
                initial_options=raw_opts,
            )
            st.success(t("schema.msg_param_created", name=new_param_name.strip(), id=created_id))
            st.rerun()

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

        params_display["Group"] = params_display["Group"].fillna(t("schema.param_group_none"))
        cols_to_show = ["param_id", "Group", "param_name"]
        if "alias" in params_display.columns:
            cols_to_show.append("alias")
        cols_to_show.append("param_type")
        if "mandatory" in params_display.columns:
            params_display["mandatory"] = params_display["mandatory"].apply(lambda x: "Yes" if bool(x) else "No")
            cols_to_show.append("mandatory")

        st.dataframe(
            params_display[cols_to_show],
            width="stretch",
            hide_index=True,
        )

        edit_pid = st.selectbox(t("project_types.edit_property"), params["param_id"].tolist())
        edit_prop = params[params["param_id"] == edit_pid].iloc[0]
        with st.container(border=True):
            edit_name = st.text_input(t("schema.param_name"), value=edit_prop["param_name"], key=f"edit_name_{edit_pid}")
            edit_alias = st.text_input(t("schema.param_alias"), value=edit_prop["alias"] or "", key=f"edit_alias_{edit_pid}")
            edit_type = st.selectbox(t("schema.param_type"), PARAM_TYPES, index=PARAM_TYPES.index(edit_prop["param_type"]), key=f"edit_kind_{edit_pid}")
            edit_mandatory = st.checkbox(t("schema.param_mandatory"), value=bool(edit_prop["mandatory"]), key=f"edit_required_{edit_pid}")
            current_gid = int(edit_prop["group_id"]) if pd.notna(edit_prop["group_id"]) else None
            edit_group = st.selectbox(t("schema.param_group_assign"), grp_options, index=grp_options.index(current_gid), format_func=grp_map.get, key=f"edit_group_{edit_pid}")
            edit_all, edit_types = applicability_input(type_service, f"edit_{edit_pid}", edit_pid)
            if st.button(t("project_types.save_property")):
                updated = _save(service.update_parameter, edit_pid, edit_group, edit_name, edit_type,
                                edit_mandatory, edit_alias, edit_all, edit_types)
                if not updated:
                    st.error("The selected property no longer exists.")
                    st.stop()
                st.rerun()
        del_param_id = st.selectbox("Select Parameter to Delete", options=params["param_id"].tolist())
        if st.button(t("schema.btn_del_param"), key="btn_del_param"):
            _save(service.delete_parameter, del_param_id)
            st.success(f"Parameter '{del_param_id}' deleted.")
            st.rerun()


def _render_options(service: SchemaService, params: pd.DataFrame, options: pd.DataFrame) -> None:
    st.subheader(t("schema.opt_manage_header"))
    tag_or_enum_params = params[params["param_type"].isin(CHOICE_TYPES)]

    if tag_or_enum_params.empty:
        st.info("No ENUM, MULTI_ENUM, or TAGS parameters configured yet.")
    else:
        p_map = dict(zip(tag_or_enum_params["param_id"], tag_or_enum_params["param_name"]))
        target_pid = st.selectbox(
            t("schema.opt_select_param"),
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
            opt_val = col1.text_input(t("schema.opt_new_val"), placeholder="e.g. Critical or Cloud Native")
            opt_ord = col2.number_input(t("schema.opt_order"), min_value=0, value=len(current_opts) + 1, step=1)
            btn_add_opt = st.form_submit_button(t("schema.btn_add_opt"))

            if btn_add_opt:
                _save(service.add_option, target_pid, opt_val, int(opt_ord))
                st.success(t("schema.msg_opt_created", value=opt_val))
                st.rerun()

        if not current_opts.empty:
            del_opt_id = st.selectbox(
                "Delete Option",
                options=current_opts["id"].tolist(),
                format_func=lambda x: str(current_opts[current_opts["id"] == x]["option_value"].iloc[0]),
            )
            if st.button("Delete Selected Option"):
                _save(service.delete_option, del_opt_id)
                st.success("Option deleted.")
                st.rerun()


def _render_schema_tree(groups: pd.DataFrame, params: pd.DataFrame, options: pd.DataFrame) -> None:
    st.subheader("Schema Hierarchy Explorer")
    if groups.empty and params.empty:
        st.info("Schema is empty.")
    else:
        # Grouped parameters
        if not groups.empty:
            for _, grp in groups.iterrows():
                gid = grp["id"]
                st.markdown(f"### `{grp['group_name']}` (Order: {grp['display_order']})")
                grp_params = params[params["group_id"] == gid]
                if grp_params.empty:
                    st.caption("  *No parameters assigned to this group.*")
                else:
                    for _, p in grp_params.iterrows():
                        pid = p["param_id"]
                        ptype = p["param_type"]
                        pname = p["param_name"]
                        st.markdown(f"- **{pname}** (`{pid}`) — Type: `{ptype}`")
                        if ptype in CHOICE_TYPES:
                            p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                            if p_opts:
                                st.markdown("  - Options/Tags: " + ", ".join([f"`{o}`" for o in p_opts]))
                            else:
                                st.markdown("  - *No options defined.*")
                st.divider()

        # Ungrouped parameters
        ungrouped_params = params[params["group_id"].isna()]
        if not ungrouped_params.empty:
            st.markdown(f"### {t('schema.param_group_none')}")
            for _, p in ungrouped_params.iterrows():
                pid = p["param_id"]
                ptype = p["param_type"]
                pname = p["param_name"]
                st.markdown(f"- **{pname}** (`{pid}`) — Type: `{ptype}`")
                if ptype in CHOICE_TYPES:
                    p_opts = options[options["param_id"] == pid]["option_value"].tolist()
                    if p_opts:
                        st.markdown("  - Options/Tags: " + ", ".join([f"`{o}`" for o in p_opts]))
                    else:
                        st.markdown("  - *No options defined.*")
