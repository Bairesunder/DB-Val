import io
import zipfile
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st

from dbcheck_core import (
    compare_data,
    validate_assay,
    validate_collar,
    validate_survey,
    suggest_columns,
)

APP_TITLE = "DBCheck — Validación y comparación de BBDD (drilling)"

st.set_page_config(
    page_title=APP_TITLE,
    layout="wide",
    initial_sidebar_state="expanded",
)

# Minimal CSS polish
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

st.title(APP_TITLE)
st.caption("Interfaz minimalista para ejecutar el script de validación/comparación con archivos CSV.")

with st.sidebar:
    st.subheader("Entradas")
    encoding = st.selectbox("Encoding CSV", ["ISO-8859-1", "utf-8", "cp1252"], index=0)
    st.markdown('<div class="small-note">Por defecto se mantiene ISO-8859-1 (igual que el script original).</div>', unsafe_allow_html=True)
    st.divider()
    script_compatible = st.toggle("Modo compatible con el script (fillna=0 en comparación)", value=True)
    st.markdown('<div class="small-note">Actívalo si quieres reproducir exactamente el comportamiento histórico del script.</div>', unsafe_allow_html=True)

tab_compare, tab_collar, tab_survey, tab_assay = st.tabs(["Comparar OLD vs NEW", "Validar Collar", "Validar Survey", "Validar Assay"])

# --------------------------
# 1) COMPARE
# --------------------------
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

        st.write("Vista rápida")
        st.dataframe(df_old.head(20), use_container_width=True)

        cols_old = df_old.columns.tolist()
        cols_new = df_new.columns.tolist()
        # Prefer columns from OLD for mapping
        cols = cols_old

        st.markdown("#### Mapeo de columnas (clave)")
        bhid_def = _auto_select(cols, ["BHID", "HOLEID", "HOLE_ID", "HOLE", "BH_ID"])
        bhid = _mapping_ui("Hole ID (BHID)", cols, bhid_def)

        at = from_i = to_i = None
        if ftype == "survey":
            at_def = _auto_select(cols, ["AT", "DEPTH", "MD", "DEPTH_M", "MEASDEPTH"])
            at = _mapping_ui("AT (profundidad medida)", cols, at_def)
        if ftype in ("assay", "litho"):
            from_def = _auto_select(cols, ["FROM", "FROM_M", "DEPTH_FROM", "FR"])
            to_def = _auto_select(cols, ["TO", "TO_M", "DEPTH_TO", "DEPTH2", "T"])
            from_i = _mapping_ui("FROM", cols, from_def)
            to_i = _mapping_ui("TO", cols, to_def)

        run = st.button("Ejecutar comparación", type="primary")

        if run:
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
                m1, m2, m3 = st.columns(3)
                m1.metric("Registros OLD", res.n_old)
                m2.metric("Registros NEW", res.n_new)
                m3.metric("Registros en común (match)", res.n_match)

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

                st.markdown("#### Diferencias por columna (conteo)")
                st.dataframe(res.diff_counts, use_container_width=True, height=260)

                st.markdown("#### Tabla de diferencias (binaria + valores old/new)")
                st.dataframe(res.differences, use_container_width=True, height=420)

                # Downloads
                files = {
                    f"different_{ftype}s.csv": _df_to_csv_bytes(res.additional_records),
                    f"different_data_{ftype}.csv": _df_to_csv_bytes(res.differences),
                    f"diff_counts_{ftype}.csv": _df_to_csv_bytes(res.diff_counts),
                }
                zip_blob = _zip_bytes(files)
                st.download_button(
                    "Descargar resultados (.zip)",
                    data=zip_blob,
                    file_name=f"dbcheck_compare_{ftype}.zip",
                    mime="application/zip",
                )

    else:
        st.info("Sube ambos CSV (OLD y NEW) para habilitar la comparación.")

# --------------------------
# 2) COLLAR VALIDATION
# --------------------------
with tab_collar:
    st.subheader("Validar Collar")
    f = st.file_uploader("CSV Collar", type=["csv"], key="collar_file")
    if f:
        df = _read_csv(f, encoding)
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
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.metric("Errores detectados", int(len(res.errors)))
                with c2:
                    st.dataframe(res.summary, use_container_width=True, height=240)

                st.markdown("#### Registros con error")
                st.dataframe(res.errors, use_container_width=True, height=420)

                files = {
                    "error_collar.csv": _df_to_csv_bytes(res.errors),
                    "error_collar_summary.csv": _df_to_csv_bytes(res.summary),
                }
                st.download_button(
                    "Descargar resultados (.zip)",
                    data=_zip_bytes(files),
                    file_name="dbcheck_collar_validation.zip",
                    mime="application/zip",
                )
    else:
        st.info("Sube un CSV de collar para habilitar la validación.")

# --------------------------
# 3) SURVEY VALIDATION
# --------------------------
with tab_survey:
    st.subheader("Validar Survey")
    f = st.file_uploader("CSV Survey", type=["csv"], key="survey_file")
    if f:
        df = _read_csv(f, encoding)
        st.write("Vista rápida")
        st.dataframe(df.head(20), use_container_width=True)

        cols = df.columns.tolist()
        st.markdown("#### Mapeo de columnas")
        bhid = _mapping_ui("Hole ID", cols, _auto_select(cols, ["HOLEID", "BHID", "HOLE_ID", "HOLE"]))
        at = _mapping_ui("Depth/AT", cols, _auto_select(cols, ["AT", "DEPTH", "MD", "MEASDEPTH"]))
        # IMPORTANT: enforce explicit azimuth/dip mapping (common confusion in scripts)
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
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.metric("Errores detectados", int(len(res.errors)))
                with c2:
                    st.dataframe(res.summary, use_container_width=True, height=240)

                st.markdown("#### Registros con error")
                st.dataframe(res.errors, use_container_width=True, height=420)

                st.markdown("#### Survey con DLS calculado (debug / QA)")
                st.dataframe(res.extra["survey_dls"].head(200), use_container_width=True, height=320)

                files = {
                    "error_survey.csv": _df_to_csv_bytes(res.errors),
                    "error_survey_summary.csv": _df_to_csv_bytes(res.summary),
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

# --------------------------
# 4) ASSAY VALIDATION
# --------------------------
with tab_assay:
    st.subheader("Validar Assay")
    f = st.file_uploader("CSV Assay", type=["csv"], key="assay_file")
    if f:
        df = _read_csv(f, encoding)
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
        if grade_fields:
            maxes = []
            for gf in grade_fields:
                maxes.append(st.number_input(f"Max {gf}", min_value=0.0, value=2.0, step=0.5))
        else:
            maxes = []

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
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.metric("Errores detectados", int(len(res.errors)))
                with c2:
                    st.dataframe(res.summary, use_container_width=True, height=240)

                st.markdown("#### Registros con error")
                st.dataframe(res.errors, use_container_width=True, height=420)

                files = {
                    "error_assay.csv": _df_to_csv_bytes(res.errors),
                    "error_assay_summary.csv": _df_to_csv_bytes(res.summary),
                }
                st.download_button(
                    "Descargar resultados (.zip)",
                    data=_zip_bytes(files),
                    file_name="dbcheck_assay_validation.zip",
                    mime="application/zip",
                )
    else:
        st.info("Sube un CSV de assays para habilitar la validación.")
