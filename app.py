import io
import math
import os
import zipfile
from typing import Dict, List, Optional, Tuple

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


def _detect_convertible_columns(df: pd.DataFrame) -> List[str]:
    candidates = [
        "FROM",
        "TO",
        "AT",
        "DEPTH",
        "MD",
        "LENGTH",
        "THICKNESS",
        "ELEVATION",
        "RL",
        "X",
        "Y",
        "Z",
        "EAST",
        "NORTH",
    ]
    numeric_cols = set(df.select_dtypes(include="number").columns.tolist())
    detected = []
    for col in df.columns:
        name = str(col).upper()
        if col in numeric_cols and any(key in name for key in candidates):
            detected.append(col)
    return detected


def _convert_columns(df: pd.DataFrame, columns: List[str], factor: float) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        out[col] = pd.to_numeric(out[col], errors="coerce") * factor
    return out




def _summarize_conversion(df_before: pd.DataFrame, df_after: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    rows = []
    for col in columns:
        before = pd.to_numeric(df_before[col], errors="coerce")
        after = pd.to_numeric(df_after[col], errors="coerce")
        rows.append({
            "columna": col,
            "no_nulos": int(after.notna().sum()),
            "min_before": float(before.min()) if before.notna().any() else None,
            "max_before": float(before.max()) if before.notna().any() else None,
            "min_after": float(after.min()) if after.notna().any() else None,
            "max_after": float(after.max()) if after.notna().any() else None,
        })
    return pd.DataFrame(rows)


def _from_to_warnings(df: pd.DataFrame) -> List[str]:
    warnings: List[str] = []
    upper = {str(c).upper(): c for c in df.columns}
    from_col = upper.get("FROM")
    to_col = upper.get("TO")
    if from_col and to_col:
        from_num = pd.to_numeric(df[from_col], errors="coerce")
        to_num = pd.to_numeric(df[to_col], errors="coerce")
        bad = int(((from_num > to_num) & from_num.notna() & to_num.notna()).sum())
        if bad > 0:
            warnings.append(f"Se detectaron {bad} intervalos con FROM > TO.")
    return warnings




def _pick_default_coordinate_cols(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    cols = df.columns.tolist()
    return {
        "x": _auto_select(cols, ["EAST", "EASTING", "X", "XCOLLAR", "X_LOCAL"]),
        "y": _auto_select(cols, ["NORTH", "NORTHING", "Y", "YCOLLAR", "Y_LOCAL"]),
        "z": _auto_select(cols, ["ELEVATION", "RL", "Z", "ZCOLLAR", "Z_LOCAL"]),
    }


def _transform_coordinates(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    z_col: Optional[str],
    tx: float,
    ty: float,
    tz: float,
    scale_xy: float,
    rotation_deg: float,
    scale_z: float,
    inverse: bool,
) -> pd.DataFrame:
    out = df.copy()
    x = pd.to_numeric(out[x_col], errors="coerce")
    y = pd.to_numeric(out[y_col], errors="coerce")

    theta = math.radians(rotation_deg)
    c = math.cos(theta)
    s = math.sin(theta)

    if not inverse:
        xr = scale_xy * (x * c - y * s) + tx
        yr = scale_xy * (x * s + y * c) + ty
        out[x_col] = xr
        out[y_col] = yr
        if z_col:
            z = pd.to_numeric(out[z_col], errors="coerce")
            out[z_col] = (z * scale_z) + tz
    else:
        x0 = (x - tx) / scale_xy if scale_xy != 0 else x * float("nan")
        y0 = (y - ty) / scale_xy if scale_xy != 0 else y * float("nan")
        xr = x0 * c + y0 * s
        yr = -x0 * s + y0 * c
        out[x_col] = xr
        out[y_col] = yr
        if z_col:
            z = pd.to_numeric(out[z_col], errors="coerce")
            out[z_col] = (z - tz) / scale_z if scale_z != 0 else z * float("nan")

    return out

def _prepare_uploaded_files(
    f_collar,
    f_survey,
    f_assays,
    extra_files,
) -> List[Tuple[str, object]]:
    uploaded_files: List[Tuple[str, object]] = []
    for label, f in [("Collar", f_collar), ("Survey", f_survey), ("Assays", f_assays)]:
        if f is not None:
            uploaded_files.append((label, f))
    for f in extra_files or []:
        uploaded_files.append((f"Extra: {f.name}", f))
    return uploaded_files

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

tab_compare, tab_collar, tab_survey, tab_assay, tab_convert = st.tabs([
    "Comparar OLD vs NEW",
    "Validar Collar",
    "Validar Survey",
    "Validar Assay",
    "Transformar unidades",
])

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

with tab_convert:
    st.subheader("Transformación de unidades (pies ↔ metros)")
    st.caption("Carga Collar, Survey, Assays y cualquier otro archivo para convertir columnas numéricas de distancia.")

    c0, c1, c2 = st.columns([2, 1, 1])
    with c0:
        direction = st.radio(
            "Dirección de conversión",
            options=["Pies → Metros", "Metros → Pies"],
            horizontal=True,
        )
    with c1:
        decimals = st.number_input("Decimales", min_value=0, max_value=8, value=3, step=1)
    with c2:
        convert_all_numeric = st.toggle("Convertir todas las numéricas", value=False)

    factor = 0.3048 if direction == "Pies → Metros" else 3.280839895

    st.markdown("#### Transformación de sistema de coordenadas (opcional)")
    coord_transform = st.toggle("Aplicar transformación de coordenadas", value=False)

    coord_mode = "Sin transformación"
    source_crs = "Local"
    target_crs = "Local"
    tx = ty = tz = 0.0
    scale_xy = scale_z = 1.0
    rotation_deg = 0.0
    inverse_transform = False

    if coord_transform:
        cm1, cm2, cm3 = st.columns(3)
        with cm1:
            source_crs = st.text_input("CRS origen", value="LOCAL_MINE_GRID")
        with cm2:
            target_crs = st.text_input("CRS destino", value="WGS84_UTM")
        with cm3:
            coord_mode = st.selectbox("Modo", options=["Local → Global", "Global → Local (inversa)"])

        cp1, cp2, cp3, cp4 = st.columns(4)
        with cp1:
            tx = st.number_input("Traslación X", value=0.0, format="%.6f")
            ty = st.number_input("Traslación Y", value=0.0, format="%.6f")
        with cp2:
            tz = st.number_input("Traslación Z", value=0.0, format="%.6f")
            rotation_deg = st.number_input("Rotación XY (grados)", value=0.0, format="%.6f")
        with cp3:
            scale_xy = st.number_input("Escala XY", min_value=0.0, value=1.0, format="%.9f")
            scale_z = st.number_input("Escala Z", min_value=0.0, value=1.0, format="%.9f")
        with cp4:
            st.markdown("**Modelo aplicado**")
            st.caption("X' = Tx + Sxy*(X*cosθ - Y*sinθ)")
            st.caption("Y' = Ty + Sxy*(X*sinθ + Y*cosθ)")
            st.caption("Z' = Tz + Sz*Z")

        inverse_transform = coord_mode == "Global → Local (inversa)"

    c1, c2, c3 = st.columns(3)
    with c1:
        f_collar = st.file_uploader("Collar (CSV)", type=["csv"], key="conv_collar")
    with c2:
        f_survey = st.file_uploader("Survey (CSV)", type=["csv"], key="conv_survey")
    with c3:
        f_assays = st.file_uploader("Assays (CSV)", type=["csv"], key="conv_assays")

    f_extra = st.file_uploader(
        "Otros archivos (lithology, geology, etc.)",
        type=["csv"],
        accept_multiple_files=True,
        key="conv_extra",
    )

    uploaded_files = _prepare_uploaded_files(f_collar, f_survey, f_assays, f_extra)

    if uploaded_files:
        st.markdown("#### Selección de columnas a convertir")
        dfs: Dict[str, pd.DataFrame] = {}
        selected_by_file: Dict[str, List[str]] = {}

        for i, (label, uploaded) in enumerate(uploaded_files):
            df = _read_csv(uploaded, encoding)
            file_key = f"{i}_{uploaded.name}"
            dfs[file_key] = df

            detected = _detect_convertible_columns(df)
            numeric_cols = df.select_dtypes(include="number").columns.tolist()
            default_cols = numeric_cols if convert_all_numeric else detected

            with st.expander(f"{label} — {uploaded.name}", expanded=(i < 3)):
                st.write(f"Filas: {len(df)} · Columnas: {len(df.columns)}")
                selected = st.multiselect(
                    "Columnas a convertir",
                    options=numeric_cols,
                    default=default_cols,
                    key=f"conv_cols_{file_key}",
                )
                selected_by_file[file_key] = selected

                if coord_transform:
                    defaults = _pick_default_coordinate_cols(df)
                    cx1, cx2, cx3 = st.columns(3)
                    with cx1:
                        x_col = st.selectbox(
                            "Columna X",
                            options=df.columns.tolist(),
                            index=df.columns.tolist().index(defaults["x"]) if defaults["x"] in df.columns else 0,
                            key=f"x_{file_key}",
                        )
                    with cx2:
                        y_col = st.selectbox(
                            "Columna Y",
                            options=df.columns.tolist(),
                            index=df.columns.tolist().index(defaults["y"]) if defaults["y"] in df.columns else 0,
                            key=f"y_{file_key}",
                        )
                    with cx3:
                        z_opts = ["(sin Z)"] + df.columns.tolist()
                        z_default = defaults["z"] if defaults["z"] in df.columns else "(sin Z)"
                        z_col = st.selectbox(
                            "Columna Z (opcional)",
                            options=z_opts,
                            index=z_opts.index(z_default) if z_default in z_opts else 0,
                            key=f"z_{file_key}",
                        )
                    selected_by_file[f"coord_{file_key}"] = [x_col, y_col, z_col]

                st.dataframe(df.head(10), use_container_width=True, height=220)

        if st.button("Transformar archivos", type="primary"):
            output_files: Dict[str, bytes] = {}
            summary_rows = []
            report_rows = []

            for (_, uploaded), (file_key, df) in zip(uploaded_files, dfs.items()):
                selected_cols = selected_by_file.get(file_key, [])
                converted = _convert_columns(df, selected_cols, factor) if selected_cols else df.copy()
                if selected_cols:
                    converted[selected_cols] = converted[selected_cols].round(int(decimals))

                if coord_transform:
                    x_col, y_col, z_col = selected_by_file.get(f"coord_{file_key}", [None, None, "(sin Z)"])
                    z_col = None if z_col == "(sin Z)" else z_col
                    if x_col and y_col:
                        converted = _transform_coordinates(
                            df=converted,
                            x_col=x_col,
                            y_col=y_col,
                            z_col=z_col,
                            tx=float(tx),
                            ty=float(ty),
                            tz=float(tz),
                            scale_xy=float(scale_xy),
                            rotation_deg=float(rotation_deg),
                            scale_z=float(scale_z),
                            inverse=bool(inverse_transform),
                        )
                        coord_cols = [x_col, y_col] + ([z_col] if z_col else [])
                        converted[coord_cols] = converted[coord_cols].round(int(decimals))

                base, _ = os.path.splitext(uploaded.name)
                suffix = "m" if direction == "Pies → Metros" else "ft"
                out_name = f"{base}_{suffix}.csv"
                output_files[out_name] = _df_to_csv_bytes(converted)

                summary = _summarize_conversion(df, converted, selected_cols) if selected_cols else pd.DataFrame()
                warnings_list = _from_to_warnings(converted)
                summary_rows.append({
                    "archivo": uploaded.name,
                    "columnas_convertidas": len(selected_cols),
                    "advertencias": " | ".join(warnings_list) if warnings_list else "OK",
                    "output": out_name,
                    "crs": f"{source_crs} -> {target_crs}" if coord_transform else "Sin cambio",
                    "modo_coord": coord_mode if coord_transform else "Sin transformación",
                })

                for _, row in summary.iterrows():
                    report_rows.append({"archivo": uploaded.name, **row.to_dict()})

                st.markdown(f"##### Resultado: {uploaded.name}")
                if warnings_list:
                    for w in warnings_list:
                        st.warning(w)
                if selected_cols:
                    compare_cols = selected_cols[: min(3, len(selected_cols))]
                    preview = pd.concat(
                        [df[compare_cols].head(8).add_suffix("_before"), converted[compare_cols].head(8).add_suffix("_after")],
                        axis=1,
                    )
                    st.dataframe(preview, use_container_width=True, height=220)
                st.download_button(
                    f"Descargar {out_name}",
                    data=output_files[out_name],
                    file_name=out_name,
                    mime="text/csv",
                    key=f"dl_{file_key}",
                )

            summary_df = pd.DataFrame(summary_rows)
            report_df = pd.DataFrame(report_rows)
            if not report_df.empty:
                output_files["conversion_report.csv"] = _df_to_csv_bytes(report_df)

            st.success("Conversión completada. Puedes descargar cada CSV por separado o todo en ZIP.")
            st.dataframe(summary_df, use_container_width=True)
            st.download_button(
                "Descargar resultados convertidos (.zip)",
                data=_zip_bytes(output_files),
                file_name="db_units_converted.zip",
                mime="application/zip",
            )
    else:
        st.info("Sube al menos un archivo CSV para convertir unidades.")
