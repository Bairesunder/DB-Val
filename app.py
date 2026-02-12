import io
import zipfile
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

from dbcheck_core import (
    compare_data,
    suggest_columns,
    validate_assay,
    validate_collar,
    validate_survey,
)

APP_TITLE = "DBCheck — Validación y comparación de BBDD (drilling)"

SEVERITY_BY_TYPE = {
    "invalid dip/azimuth": "Crítico",
    "from/to overlaps": "Crítico",
    "null values": "Mayor",
    "zero/null values": "Mayor",
    "duplicated hole id": "Mayor",
    "duplicated sample id": "Mayor",
    "duplicated values": "Mayor",
    "duplicated coordinates": "Mayor",
    "unexpected grades": "Mayor",
    "negative/zero values": "Mayor",
    "dls": "Mayor",
    "coordinates to be reviewed": "Menor",
    "rounded coordinates": "Menor",
    "inverted x and y": "Menor",
    "recurring assays": "Info",
    "holeid with spaces on last character": "Info",
}

SEVERITY_ORDER = ["Crítico", "Mayor", "Menor", "Info"]

st.set_page_config(
    page_title=APP_TITLE,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 0.5rem; }
    .stTabs [data-baseweb="tab"] { padding: 0.35rem 0.9rem; }
    .small-note { color: #6b7280; font-size: 0.9rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _read_csv(uploaded, encoding: str) -> pd.DataFrame:
    return pd.read_csv(uploaded, encoding=encoding, low_memory=False)


def _df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def _zip_bytes(files: Dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _auto_select(columns: List[str], candidates: List[str]) -> Optional[str]:
    return suggest_columns(columns, candidates)


def _mapping_ui(label: str, columns: List[str], default: Optional[str]) -> str:
    if default not in columns:
        default = None
    idx = columns.index(default) if default in columns else 0
    return st.selectbox(label, options=columns, index=idx)


def _severity_from_type(type_value: str) -> str:
    normalized = str(type_value).strip().lower()
    for key, sev in SEVERITY_BY_TYPE.items():
        if key == "dls" and normalized.startswith("dls"):
            return sev
        if normalized == key:
            return sev
    return "Info"


def _quality_profile(df: pd.DataFrame, title: str) -> None:
    with st.expander(f"Perfil de calidad — {title}", expanded=False):
        c1, c2, c3 = st.columns(3)
        c1.metric("Filas", len(df))
        c2.metric("Columnas", len(df.columns))
        c3.metric("Duplicados exactos", int(df.duplicated().sum()))

        nulls = (
            df.isnull().mean().mul(100).round(2).sort_values(ascending=False).reset_index()
            .rename(columns={"index": "column", 0: "%_null"})
        )
        st.markdown("**Top columnas por % de nulos**")
        st.dataframe(nulls.head(15), use_container_width=True, height=250)

        num_cols = df.select_dtypes(include="number")
        if not num_cols.empty:
            stats = num_cols.describe(percentiles=[0.5, 0.95]).T.reset_index().rename(columns={"index": "column"})
            view_cols = [c for c in ["column", "min", "50%", "95%", "max"] if c in stats.columns]
            st.markdown("**Resumen de rangos numéricos**")
            st.dataframe(stats[view_cols].head(30), use_container_width=True, height=260)


def _render_error_dashboard(errors: pd.DataFrame, bhid_col: str, depth_col: Optional[str] = None) -> pd.DataFrame:
    if errors.empty:
        st.success("No se detectaron errores con las reglas actuales.")
        return errors

    df = errors.copy()
    df["SEVERITY"] = df["TYPE"].apply(_severity_from_type)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Errores detectados", int(len(df)))
    m2.metric("Pozos afectados", int(df[bhid_col].nunique()) if bhid_col in df.columns else 0)
    m3.metric("Críticos", int((df["SEVERITY"] == "Crítico").sum()))
    m4.metric("Mayores", int((df["SEVERITY"] == "Mayor").sum()))

    sev_summary = (
        df.groupby("SEVERITY", as_index=False)
        .size()
        .rename(columns={"size": "n"})
    )
    sev_summary["SEVERITY"] = pd.Categorical(sev_summary["SEVERITY"], categories=SEVERITY_ORDER, ordered=True)
    sev_summary = sev_summary.sort_values("SEVERITY")

    st.markdown("#### Distribución por severidad")
    st.bar_chart(sev_summary.set_index("SEVERITY")["n"])

    type_summary = df.groupby("TYPE", as_index=False).size().rename(columns={"size": "n"}).sort_values("n", ascending=False)
    st.markdown("#### Top errores por tipo")
    st.dataframe(type_summary.head(10), use_container_width=True, height=220)

    st.markdown("#### Filtros")
    f1, f2, f3 = st.columns(3)
    with f1:
        sev_selected = st.multiselect("Severidad", options=SEVERITY_ORDER, default=SEVERITY_ORDER)
    with f2:
        type_selected = st.multiselect("Tipo de error", options=sorted(df["TYPE"].dropna().astype(str).unique().tolist()))
    with f3:
        bhid_query = st.text_input("Buscar Hole ID contiene", value="").strip().lower()

    filtered = df.copy()
    if sev_selected:
        filtered = filtered[filtered["SEVERITY"].isin(sev_selected)]
    if type_selected:
        filtered = filtered[filtered["TYPE"].isin(type_selected)]
    if bhid_query and bhid_col in filtered.columns:
        filtered = filtered[filtered[bhid_col].astype(str).str.lower().str.contains(bhid_query, na=False)]

    if depth_col and depth_col in filtered.columns:
        depth_num = pd.to_numeric(filtered[depth_col], errors="coerce")
        depth_num = depth_num.dropna()
        if not depth_num.empty and depth_num.min() < depth_num.max():
            dmin, dmax = float(depth_num.min()), float(depth_num.max())
            sel_min, sel_max = st.slider("Rango de profundidad", min_value=dmin, max_value=dmax, value=(dmin, dmax))
            depth_vals = pd.to_numeric(filtered[depth_col], errors="coerce")
            filtered = filtered[(depth_vals >= sel_min) & (depth_vals <= sel_max)]

    return filtered


st.title(APP_TITLE)
st.caption("Interfaz para ejecutar validación/comparación con dashboard de calidad, severidad y filtros.")

with st.sidebar:
    st.subheader("Entradas")
    encoding = st.selectbox("Encoding CSV", ["ISO-8859-1", "utf-8", "cp1252"], index=0)
    st.markdown('<div class="small-note">Por defecto se mantiene ISO-8859-1 (igual que el script original).</div>', unsafe_allow_html=True)
    st.divider()
    script_compatible = st.toggle("Modo compatible con el script (fillna=0 en comparación)", value=True)
    st.markdown('<div class="small-note">Actívalo si quieres reproducir exactamente el comportamiento histórico del script.</div>', unsafe_allow_html=True)

tab_compare, tab_collar, tab_survey, tab_assay = st.tabs(["Comparar OLD vs NEW", "Validar Collar", "Validar Survey", "Validar Assay"])

with tab_compare:
    st.subheader("Comparar OLD vs NEW")
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        ftype = st.selectbox("Tipo de tabla", ["collar", "survey", "assay", "litho"], index=0)
    with c2:
        tol = st.number_input("Tolerancia numérica (abs delta)", min_value=0.0, value=0.001, step=0.001, format="%.6f")
    with c3:
        st.write("")

    f_old = st.file_uploader("CSV OLD", type=["csv"], key="compare_old")
    f_new = st.file_uploader("CSV NEW", type=["csv"], key="compare_new")

    if f_old and f_new:
        df_old = _read_csv(f_old, encoding)
        df_new = _read_csv(f_new, encoding)
        _quality_profile(df_old, "OLD")
        _quality_profile(df_new, "NEW")

        st.write("Vista rápida")
        st.dataframe(df_old.head(20), use_container_width=True)

        cols = df_old.columns.tolist()
        st.markdown("#### Mapeo de columnas (clave)")
        bhid = _mapping_ui("Hole ID (BHID)", cols, _auto_select(cols, ["BHID", "HOLEID", "HOLE_ID", "HOLE", "BH_ID"]))

        at = from_i = to_i = None
        if ftype == "survey":
            at = _mapping_ui("AT (profundidad medida)", cols, _auto_select(cols, ["AT", "DEPTH", "MD", "DEPTH_M", "MEASDEPTH"]))
        if ftype in ("assay", "litho"):
            from_i = _mapping_ui("FROM", cols, _auto_select(cols, ["FROM", "FROM_M", "DEPTH_FROM", "FR"]))
            to_i = _mapping_ui("TO", cols, _auto_select(cols, ["TO", "TO_M", "DEPTH_TO", "DEPTH2", "T"]))

        if st.button("Ejecutar comparación", type="primary"):
            try:
                res = compare_data(
                    ftype=ftype,
                    df_old=df_old,
                    df_new=df_new,
                    bhid=bhid,
                    at=at,
                    from_i=from_i,
                    to_i=to_i,
                    numeric_tolerance=float(tol),
                    script_compatible_fillna=script_compatible,
                )
            except Exception as e:
                st.error(f"Error ejecutando comparación: {e}")
            else:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Registros OLD", res.n_old)
                m2.metric("Registros NEW", res.n_new)
                m3.metric("Match", res.n_match)
                m4.metric("Registros extra", int(len(res.additional_records)))

                st.markdown("#### Top columnas con diferencias")
                st.dataframe(res.diff_counts.head(15), use_container_width=True, height=240)

                st.markdown("#### Columnas no coincidentes")
                cc1, cc2 = st.columns(2)
                with cc1:
                    st.write("Solo en OLD")
                    st.write(res.col_only_old if res.col_only_old else "—")
                with cc2:
                    st.write("Solo en NEW")
                    st.write(res.col_only_new if res.col_only_new else "—")

                st.markdown("#### Registros adicionales/diferentes (por clave)")
                st.dataframe(res.additional_records, use_container_width=True, height=260)

                st.markdown("#### Tabla de diferencias (binaria + valores old/new)")
                st.dataframe(res.differences, use_container_width=True, height=420)

                files = {
                    f"different_{ftype}s.csv": _df_to_csv_bytes(res.additional_records),
                    f"different_data_{ftype}.csv": _df_to_csv_bytes(res.differences),
                    f"diff_counts_{ftype}.csv": _df_to_csv_bytes(res.diff_counts),
                }
                st.download_button(
                    "Descargar resultados (.zip)",
                    data=_zip_bytes(files),
                    file_name=f"dbcheck_compare_{ftype}.zip",
                    mime="application/zip",
                )
    else:
        st.info("Sube ambos CSV (OLD y NEW) para habilitar la comparación.")

with tab_collar:
    st.subheader("Validar Collar")
    f = st.file_uploader("CSV Collar", type=["csv"], key="collar_file")
    if f:
        df = _read_csv(f, encoding)
        _quality_profile(df, "Collar")

        st.write("Vista rápida")
        st.dataframe(df.head(20), use_container_width=True)

        cols = df.columns.tolist()
        st.markdown("#### Mapeo de columnas")
        bhid = _mapping_ui("Hole ID", cols, _auto_select(cols, ["HOLEID", "BHID", "HOLE_ID", "HOLE"]))
        x = _mapping_ui("Easting (X)", cols, _auto_select(cols, ["EAST", "EASTING", "X", "XCOLLAR"]))
        y = _mapping_ui("Northing (Y)", cols, _auto_select(cols, ["NORTH", "NORTHING", "Y", "YCOLLAR"]))
        z = _mapping_ui("Elevation (Z)", cols, _auto_select(cols, ["ELEVATION", "RL", "Z", "ZCOLLAR"]))

        if st.button("Ejecutar validación de collar", type="primary"):
            try:
                res = validate_collar(df=df, bhid=bhid, x=x, y=y, z=z)
            except Exception as e:
                st.error(f"Error: {e}")
            else:
                st.markdown("#### Dashboard de errores")
                filtered = _render_error_dashboard(res.errors, bhid_col=bhid)

                st.markdown("#### Resumen por tipo")
                st.dataframe(res.summary, use_container_width=True, height=220)

                st.markdown("#### Registros con error (filtrados)")
                st.dataframe(filtered, use_container_width=True, height=420)

                export_summary = filtered.groupby(["TYPE", "SEVERITY"], as_index=False).size().rename(columns={"size": "n"}) if not filtered.empty else res.summary
                files = {
                    "error_collar.csv": _df_to_csv_bytes(filtered),
                    "error_collar_summary.csv": _df_to_csv_bytes(export_summary),
                }
                st.download_button(
                    "Descargar resultados (.zip)",
                    data=_zip_bytes(files),
                    file_name="dbcheck_collar_validation.zip",
                    mime="application/zip",
                )
    else:
        st.info("Sube un CSV de collar para habilitar la validación.")

with tab_survey:
    st.subheader("Validar Survey")
    f = st.file_uploader("CSV Survey", type=["csv"], key="survey_file")
    if f:
        df = _read_csv(f, encoding)
        _quality_profile(df, "Survey")

        st.write("Vista rápida")
        st.dataframe(df.head(20), use_container_width=True)

        cols = df.columns.tolist()
        st.markdown("#### Mapeo de columnas")
        bhid = _mapping_ui("Hole ID", cols, _auto_select(cols, ["HOLEID", "BHID", "HOLE_ID", "HOLE"]))
        at = _mapping_ui("Depth/AT", cols, _auto_select(cols, ["AT", "DEPTH", "MD", "MEASDEPTH"]))
        az = _mapping_ui("Azimuth (0–360)", cols, _auto_select(cols, ["AZIMUTH", "AZI", "BRG", "BEARING"]))
        dip = _mapping_ui("Dip/Inclination (-90–90)", cols, _auto_select(cols, ["DIP", "INCLINATION", "INC"]))

        dls_th = st.number_input("Umbral DLS (°/30m)", min_value=0.0, value=15.0, step=1.0)
        dup_global = st.toggle("Duplicados globales (igual que script)", value=True)

        if st.button("Ejecutar validación de survey", type="primary"):
            try:
                res = validate_survey(
                    df=df,
                    bhid=bhid,
                    at=at,
                    azimuth=az,
                    dip=dip,
                    dls_threshold_deg_per_30m=float(dls_th),
                    check_duplicates_globally=dup_global,
                )
            except Exception as e:
                st.error(f"Error: {e}")
            else:
                st.markdown("#### Dashboard de errores")
                filtered = _render_error_dashboard(res.errors, bhid_col=bhid, depth_col=at)

                st.markdown("#### Resumen por tipo")
                st.dataframe(res.summary, use_container_width=True, height=220)

                st.markdown("#### Registros con error (filtrados)")
                st.dataframe(filtered, use_container_width=True, height=420)

                st.markdown("#### Survey con DLS calculado (debug / QA)")
                st.dataframe(res.extra["survey_dls"].head(200), use_container_width=True, height=320)

                export_summary = filtered.groupby(["TYPE", "SEVERITY"], as_index=False).size().rename(columns={"size": "n"}) if not filtered.empty else res.summary
                files = {
                    "error_survey.csv": _df_to_csv_bytes(filtered),
                    "error_survey_summary.csv": _df_to_csv_bytes(export_summary),
                    "survey_dls.csv": _df_to_csv_bytes(res.extra["survey_dls"]),
                }
                st.download_button(
                    "Descargar resultados (.zip)",
                    data=_zip_bytes(files),
                    file_name="dbcheck_survey_validation.zip",
                    mime="application/zip",
                )
    else:
        st.info("Sube un CSV de survey para habilitar la validación.")

with tab_assay:
    st.subheader("Validar Assay")
    f = st.file_uploader("CSV Assay", type=["csv"], key="assay_file")
    if f:
        df = _read_csv(f, encoding)
        _quality_profile(df, "Assay")

        st.write("Vista rápida")
        st.dataframe(df.head(20), use_container_width=True)

        cols = df.columns.tolist()
        st.markdown("#### Mapeo de columnas (base)")
        bhid = _mapping_ui("Hole ID", cols, _auto_select(cols, ["HOLEID", "BHID", "HOLE_ID", "HOLE"]))
        from_i = _mapping_ui("FROM", cols, _auto_select(cols, ["FROM", "FROM_M", "DEPTH_FROM", "FR"]))
        to_i = _mapping_ui("TO", cols, _auto_select(cols, ["TO", "TO_M", "DEPTH_TO", "T"]))

        st.markdown("#### Campos de ley / analíticas")
        default_grades = [c for c in cols if any(k in c.upper() for k in ["AU", "AG", "CU", "ZN", "PB", "S", "FE"])]
        grade_fields = st.multiselect("Selecciona columnas de ley", options=cols, default=default_grades[:6])

        sampleid = st.selectbox("Sample ID (opcional)", options=["(no)"] + cols, index=0)
        sampleid = None if sampleid == "(no)" else sampleid

        st.markdown("#### Máximos esperados (para 'unexpected grades')")
        maxes = [st.number_input(f"Max {gf}", min_value=0.0, value=2.0, step=0.5) for gf in grade_fields] if grade_fields else []

        if st.button("Ejecutar validación de assay", type="primary", disabled=(len(grade_fields) == 0)):
            try:
                res = validate_assay(
                    df=df,
                    bhid=bhid,
                    from_i=from_i,
                    to_i=to_i,
                    grade_fields=grade_fields,
                    maxes=maxes,
                    sampleid=sampleid,
                )
            except Exception as e:
                st.error(f"Error: {e}")
            else:
                st.markdown("#### Dashboard de errores")
                filtered = _render_error_dashboard(res.errors, bhid_col=bhid, depth_col=from_i)

                st.markdown("#### Resumen por tipo")
                st.dataframe(res.summary, use_container_width=True, height=220)

                st.markdown("#### Registros con error (filtrados)")
                st.dataframe(filtered, use_container_width=True, height=420)

                export_summary = filtered.groupby(["TYPE", "SEVERITY"], as_index=False).size().rename(columns={"size": "n"}) if not filtered.empty else res.summary
                files = {
                    "error_assay.csv": _df_to_csv_bytes(filtered),
                    "error_assay_summary.csv": _df_to_csv_bytes(export_summary),
                }
                st.download_button(
                    "Descargar resultados (.zip)",
                    data=_zip_bytes(files),
                    file_name="dbcheck_assay_validation.zip",
                    mime="application/zip",
                )
    else:
        st.info("Sube un CSV de assays para habilitar la validación.")
