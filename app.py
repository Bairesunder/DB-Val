import io
import zipfile
from typing import List, Optional, Tuple

import pandas as pd
import streamlit as st

from dbcheck_core import (
    read_csv_uploaded,
    compare_data,
    validate_collar,
    validate_survey,
    validate_assay,
)

st.set_page_config(
    page_title="DB Comparison & Validation",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------- Theme / CSS (minimal, like the mock) ----------
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.1rem; padding-bottom: 2.2rem; max-width: 1250px;}
      h1, h2, h3 {letter-spacing: -0.02em;}
      header {visibility: hidden; height: 0px;}
      .stTabs [data-baseweb="tab-list"] {gap: 10px;}
      .stTabs [data-baseweb="tab"] {height: 44px; padding-left: 14px; padding-right: 14px; border-radius: 10px;}
      div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 16px;
        padding: 14px 16px;
        box-shadow: 0 1px 2px rgba(16,24,40,0.06);
      }
      .card {
        background: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 16px;
        padding: 14px 16px;
        box-shadow: 0 1px 2px rgba(16,24,40,0.06);
      }
      .card-title {font-weight: 650; font-size: 0.95rem; margin-bottom: 10px;}
      .muted {color:#6B7280; font-size: 0.9rem;}
      .stButton button {border-radius: 12px; padding: 0.70rem 1rem; font-weight: 600;}
      section[data-testid="stFileUploaderDropzone"] {
        border-radius: 14px;
        border: 1px dashed #CBD5E1;
        background: #F8FAFC;
      }
      div[data-testid="stDataFrame"] {border-radius: 14px; border: 1px solid #E5E7EB; overflow: hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)

def card(title: str, subtitle: Optional[str] = None) -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(f'<div class="card-title">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="muted">{subtitle}</div>', unsafe_allow_html=True)

def end_card() -> None:
    st.markdown("</div>", unsafe_allow_html=True)

def to_zip_bytes(files: List[Tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files:
            z.writestr(name, data)
    return buf.getvalue()

st.title("DB Comparison & Validation")
st.caption("Interfaz minimalista para comparar OLD vs NEW y ejecutar validaciones de BBDD (drilling).")

tab_compare, tab_collar, tab_survey, tab_assay = st.tabs(
    ["OLD vs NEW", "Validar Collar", "Validar Survey", "Validar Assay"]
)

# =========================
# TAB 1 — OLD vs NEW
# =========================
with tab_compare:
    st.header("Comparar Bases de Datos")
    st.divider()

    left, right = st.columns([1, 1], gap="large")

    with left:
        card("Parámetros", "Selecciona tipo de tabla y tolerancia numérica.")
        ftype_ui = st.selectbox("Tipo de Análisis", ["Collar", "Survey", "Assay", "Litho"], index=0)
        tol = st.number_input("Tolerancia numérica (abs delta)", min_value=0.0, value=0.001, step=0.0001, format="%.6f")
        compat = st.toggle("Modo compatible con el script", value=True,
                           help="Activa fillna(0) antes de comparar (reproduce comportamiento del script original).")
        end_card()

    with right:
        card("Llaves / Claves", "Mapea las columnas clave para la comparación.")
        bhid = st.text_input("ID de sondeo (BHID/HOLEID)", value="BHID")
        at = st.text_input("AT (solo Survey)", value="AT")
        from_i = st.text_input("FROM (Assay/Litho)", value="FROM")
        to_i = st.text_input("TO (Assay/Litho)", value="TO")
        end_card()

    st.divider()

    c1, c2 = st.columns(2, gap="large")
    with c1:
        card('Archivo "OLD"', "CSV antiguo.")
        old_file = st.file_uploader("Subir Archivo Antiguo", type=["csv"], key="cmp_old")
        end_card()
    with c2:
        card('Archivo "NEW"', "CSV nuevo.")
        new_file = st.file_uploader("Subir Archivo Nuevo", type=["csv"], key="cmp_new")
        end_card()

    if old_file and new_file:
        df_old = read_csv_uploaded(old_file)
        df_new = read_csv_uploaded(new_file)

        st.divider()
        card("Vista rápida", "Primeras filas de OLD y NEW para confirmar columnas.")
        p1, p2 = st.columns(2, gap="large")
        with p1:
            st.write("OLD")
            st.dataframe(df_old.head(10), use_container_width=True)
        with p2:
            st.write("NEW")
            st.dataframe(df_new.head(10), use_container_width=True)
        end_card()

        st.divider()

        run = st.button("Iniciar Comparación", type="primary")
        if run:
            ftype = ftype_ui.lower()
            res = compare_data(
                ftype=ftype,
                df_old=df_old,
                df_new=df_new,
                bhid=bhid,
                at=at if ftype == "survey" else None,
                from_i=from_i if ftype in ("assay", "litho") else None,
                to_i=to_i if ftype in ("assay", "litho") else None,
                tol=tol,
                compat_fillna=compat,
            )

            m1, m2, m3, m4 = st.columns(4, gap="large")
            m1.metric("Registros OLD Únicos", int(res["summary"]["old_unique"]))
            m2.metric("Registros NEW Únicos", int(res["summary"]["new_unique"]))
            m3.metric("Coincidencias Totales", int(res["summary"]["matches"]))
            m4.metric("Registros con Diferencias", int(res["summary"]["records_with_differences"]))

            st.divider()
            sub1, sub2, sub3 = st.tabs(["Registros Adicionales", "Tabla de Diferencias", "Conteo por Columnas"])

            with sub1:
                card("Registros adicionales", "Filas que solo están en OLD o solo en NEW.")
                st.dataframe(res["additional_rows"], use_container_width=True, hide_index=True)
                end_card()

            with sub2:
                card("Tabla de diferencias", "Binario 0/1 por columna + valores OLD/NEW donde difiere.")
                st.dataframe(res["diff_table"], use_container_width=True, hide_index=True)
                end_card()

            with sub3:
                card("Conteo por columnas", "Ranking de columnas con más diferencias.")
                st.dataframe(res["diff_counts"], use_container_width=True, hide_index=True)
                end_card()

            # Download ZIP
            zip_bytes = to_zip_bytes([
                (f"different_{ftype}s.csv", res["additional_rows"].to_csv(index=False).encode("utf-8")),
                (f"different_data_{ftype}.csv", res["diff_table"].to_csv(index=False).encode("utf-8")),
                (f"diff_counts_{ftype}.csv", res["diff_counts"].to_csv(index=False).encode("utf-8")),
            ])
            st.download_button(
                "Descargar Resultados (ZIP)",
                data=zip_bytes,
                file_name=f"compare_{ftype}.zip",
                mime="application/zip",
                use_container_width=True,
            )

# =========================
# TAB 2 — Collar validation
# =========================
with tab_collar:
    st.header("Validar Collar")
    st.divider()

    left, right = st.columns([1, 1], gap="large")
    with left:
        card("Entrada", "Sube el CSV de collar.")
        collar_file = st.file_uploader("Subir Collar CSV", type=["csv"], key="collar_file")
        end_card()
    with right:
        card("Columnas", "Mapeo de columnas requeridas.")
        bhid = st.text_input("BHID/HOLEID", value="BHID", key="collar_bhid")
        xcol = st.text_input("X", value="X", key="collar_x")
        ycol = st.text_input("Y", value="Y", key="collar_y")
        zcol = st.text_input("Z", value="Z", key="collar_z")
        end_card()

    if collar_file:
        df = read_csv_uploaded(collar_file)

        st.divider()
        card("Vista rápida", "Comprueba columnas antes de validar.")
        st.dataframe(df.head(15), use_container_width=True)
        end_card()

        st.divider()
        run = st.button("Validar Collar", type="primary", key="run_collar")
        if run:
            summary, issues = validate_collar(df, bhid=bhid, x=xcol, y=ycol, z=zcol)

            c1, c2 = st.columns([1, 2], gap="large")
            with c1:
                card("Tipos de error", "Selecciona un tipo para filtrar el detalle.")
                st.dataframe(summary, use_container_width=True, hide_index=True)
                tipos = ["Todos"] + summary["TYPE"].astype(str).tolist()
                tipo_sel = st.selectbox("Filtrar por tipo de error", tipos, index=0)
                end_card()

            with c2:
                card("Detalle (filtrado)", "Filtrado visual de registros para el tipo seleccionado.")
                if tipo_sel == "Todos":
                    df_f = issues.copy()
                else:
                    df_f = issues[issues["TYPE"].astype(str) == str(tipo_sel)].copy()

                st.caption(f"Registros: {len(df_f):,}")
                st.dataframe(df_f, use_container_width=True, hide_index=True)
                end_card()

                st.download_button(
                    "Descargar CSV filtrado",
                    df_f.to_csv(index=False).encode("utf-8"),
                    file_name=f"collar_issues_{tipo_sel}.csv".replace(" ", "_"),
                    mime="text/csv",
                    use_container_width=True,
                )

            # Download full ZIP
            zip_bytes = to_zip_bytes([
                ("collar_error_summary.csv", summary.to_csv(index=False).encode("utf-8")),
                ("error_collar.csv", issues.to_csv(index=False).encode("utf-8")),
            ])
            st.download_button(
                "Descargar Resultados (ZIP)",
                data=zip_bytes,
                file_name="validate_collar.zip",
                mime="application/zip",
                use_container_width=True,
            )

# =========================
# TAB 3 — Survey validation
# =========================
with tab_survey:
    st.header("Validar Survey")
    st.divider()

    left, right = st.columns([1, 1], gap="large")
    with left:
        card("Entrada", "Sube el CSV de survey.")
        survey_file = st.file_uploader("Subir Survey CSV", type=["csv"], key="survey_file")
        end_card()
    with right:
        card("Columnas", "Mapeo de columnas requeridas + umbral DLS.")
        bhid = st.text_input("BHID/HOLEID", value="BHID", key="survey_bhid")
        at = st.text_input("AT", value="AT", key="survey_at")
        az = st.text_input("Azimuth", value="BRG", key="survey_az")
        dip = st.text_input("Dip/Inclination", value="DIP", key="survey_dip")
        dls_thr = st.number_input("Umbral DLS (deg/30m)", min_value=0.0, value=15.0, step=0.5, key="survey_dls_thr")
        end_card()

    if survey_file:
        df = read_csv_uploaded(survey_file)

        st.divider()
        card("Vista rápida", "Comprueba columnas antes de validar.")
        st.dataframe(df.head(15), use_container_width=True)
        end_card()

        st.divider()
        run = st.button("Validar Survey", type="primary", key="run_survey")
        if run:
            summary, issues, dls_df = validate_survey(df, bhid=bhid, at=at, az=az, dip=dip, dls_threshold=dls_thr)

            c1, c2 = st.columns([1, 2], gap="large")
            with c1:
                card("Tipos de error", "Selecciona un tipo para filtrar el detalle.")
                st.dataframe(summary, use_container_width=True, hide_index=True)
                tipos = ["Todos"] + summary["TYPE"].astype(str).tolist()
                tipo_sel = st.selectbox("Filtrar por tipo de error", tipos, index=0, key="survey_tipo")
                end_card()

            with c2:
                card("Detalle (filtrado)", "Registros para el tipo seleccionado.")
                if tipo_sel == "Todos":
                    df_f = issues.copy()
                else:
                    df_f = issues[issues["TYPE"].astype(str) == str(tipo_sel)].copy()

                st.caption(f"Registros: {len(df_f):,}")
                st.dataframe(df_f, use_container_width=True, hide_index=True)
                end_card()

                st.download_button(
                    "Descargar CSV filtrado",
                    df_f.to_csv(index=False).encode("utf-8"),
                    file_name=f"survey_issues_{tipo_sel}.csv".replace(" ", "_"),
                    mime="text/csv",
                    use_container_width=True,
                )

            zip_bytes = to_zip_bytes([
                ("survey_error_summary.csv", summary.to_csv(index=False).encode("utf-8")),
                ("error_survey.csv", issues.to_csv(index=False).encode("utf-8")),
                ("survey_dls.csv", dls_df.to_csv(index=False).encode("utf-8")),
            ])
            st.download_button(
                "Descargar Resultados (ZIP)",
                data=zip_bytes,
                file_name="validate_survey.zip",
                mime="application/zip",
                use_container_width=True,
            )

# =========================
# TAB 4 — Assay validation
# =========================
with tab_assay:
    st.header("Validar Assay")
    st.divider()

    left, right = st.columns([1, 1], gap="large")
    with left:
        card("Entrada", "Sube el CSV de assay.")
        assay_file = st.file_uploader("Subir Assay CSV", type=["csv"], key="assay_file")
        end_card()
    with right:
        card("Columnas", "Mapeo de columnas + selección de grades y máximos.")
        bhid = st.text_input("BHID/HOLEID", value="BHID", key="assay_bhid")
        from_i = st.text_input("FROM", value="FROM", key="assay_from")
        to_i = st.text_input("TO", value="TO", key="assay_to")
        sampleid = st.text_input("Sample ID (opcional)", value="", key="assay_sampleid")
        grades_txt = st.text_input("Campos de ley (separados por coma)", value="AU,AG", key="assay_grades")
        maxes_txt = st.text_input("Máximos (mismo orden, separados por coma)", value="20,500", key="assay_maxes")
        end_card()

    if assay_file:
        df = read_csv_uploaded(assay_file)

        st.divider()
        card("Vista rápida", "Comprueba columnas antes de validar.")
        st.dataframe(df.head(15), use_container_width=True)
        end_card()

        st.divider()
        run = st.button("Validar Assay", type="primary", key="run_assay")
        if run:
            grades = [g.strip() for g in grades_txt.split(",") if g.strip()]
            maxes = [float(x.strip()) for x in maxes_txt.split(",") if x.strip()]

            if len(grades) == 0:
                st.error("Define al menos un campo de ley.")
                st.stop()
            if len(maxes) != len(grades):
                st.error("El número de máximos debe coincidir con el número de campos de ley.")
                st.stop()

            summary, issues = validate_assay(
                df,
                bhid=bhid,
                from_i=from_i,
                to_i=to_i,
                grade_fields=grades,
                maxes=maxes,
                sampleid=(sampleid.strip() or None),
            )

            c1, c2 = st.columns([1, 2], gap="large")
            with c1:
                card("Tipos de error", "Selecciona un tipo para filtrar el detalle.")
                st.dataframe(summary, use_container_width=True, hide_index=True)
                tipos = ["Todos"] + summary["TYPE"].astype(str).tolist()
                tipo_sel = st.selectbox("Filtrar por tipo de error", tipos, index=0, key="assay_tipo")
                end_card()

            with c2:
                card("Detalle (filtrado)", "Registros para el tipo seleccionado.")
                if tipo_sel == "Todos":
                    df_f = issues.copy()
                else:
                    df_f = issues[issues["TYPE"].astype(str) == str(tipo_sel)].copy()

                st.caption(f"Registros: {len(df_f):,}")
                st.dataframe(df_f, use_container_width=True, hide_index=True)
                end_card()

                st.download_button(
                    "Descargar CSV filtrado",
                    df_f.to_csv(index=False).encode("utf-8"),
                    file_name=f"assay_issues_{tipo_sel}.csv".replace(" ", "_"),
                    mime="text/csv",
                    use_container_width=True,
                )

            zip_bytes = to_zip_bytes([
                ("assay_error_summary.csv", summary.to_csv(index=False).encode("utf-8")),
                ("error_assay.csv", issues.to_csv(index=False).encode("utf-8")),
            ])
            st.download_button(
                "Descargar Resultados (ZIP)",
                data=zip_bytes,
                file_name="validate_assay.zip",
                mime="application/zip",
                use_container_width=True,
            )
